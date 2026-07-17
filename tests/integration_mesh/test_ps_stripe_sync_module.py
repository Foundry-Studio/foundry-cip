# foundry: kind=test domain=client-intelligence-platform
"""Behavioural tests for cip.integration_mesh.sync.ps_stripe_sync.run_ps_stripe_sync.

A FakeTransport stands in for live Stripe (there is no STRIPE_API_KEY in this env). The tests pin
the properties the lift + the live design must hold:

  (a) incremental applies 3 events (invoice.paid / charge.refunded / credit_note.created) into the
      spine + evidence tables via the verbatim classify() kernel, records the events, advances the
      cursor, and writes a heartbeat;
  (b) re-running the same events lands ZERO new rows (hydrate-by-ID + events-processed de-dupe);
  (c) a held advisory lock makes the run skip cleanly + record a skipped heartbeat;
  (d) full mode upserts customers/invoices/refunds/credit-notes, seeds the cursor from an events
      probe, and prunes a synthetic 60-day-old processed-event row;
  (e) an invoice with >10 lines paginates correctly (the latent-bug fix — the one-shot script read
      only the embedded 10-line page).

seeded_engine runs `alembic upgrade head` against a testcontainer whose default user is a BYPASSRLS
superuser, so rows are scoped by the module's own explicit tenant predicates (as in production under
the RLS policy). A dedicated synthetic tenant keeps these rows off every other suite's toes.
"""
from __future__ import annotations

import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from cip.integration_mesh.orchestrator import _advisory_lock_key
from cip.integration_mesh.sync.ps_stripe_sync import (
    CONNECTOR_ID,
    StripeHTTPError,
    run_ps_stripe_sync,
)

TENANT = "00000000-0000-0000-0000-0000000000c1"
BRAND = "c1b10000-0000-4000-8000-000000000001"
BRAND2 = "c1b20000-0000-4000-8000-000000000002"
NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=UTC)


def _ep(dt: datetime) -> int:
    return int(dt.timestamp())


# ── Fake Stripe objects ──────────────────────────────────────────────────────


def _line(lid: str, desc: str, amount: int) -> dict:
    return {
        "id": lid, "description": desc, "amount": amount, "currency": "usd",
        "quantity": 1, "period": {"start": None, "end": None},
    }


def _inv(iid: str, cust: str, lines: list[dict], *, status: str = "paid",
         lines_has_more: bool = False) -> dict:
    total = sum(ln["amount"] for ln in lines)
    paid = status == "paid"
    return {
        "id": iid, "customer": cust, "status": status, "paid": paid,
        "collection_method": "charge_automatically",
        "amount_due": total, "amount_paid": total if paid else 0,
        "amount_remaining": 0 if paid else total, "subtotal": total, "total": total,
        "currency": "usd", "number": iid.upper(), "hosted_invoice_url": None,
        "created": _ep(NOW), "period_start": None, "period_end": None, "due_date": None,
        "lines": {"data": lines, "has_more": lines_has_more},
    }


def _cust(cid: str, *, brand: str | None = None, desc: str | None = None,
          name: str | None = None) -> dict:
    meta = {"brandId": brand} if brand else {}
    return {
        "id": cid, "metadata": meta, "description": desc, "email": None, "name": name,
        "address": {}, "preferred_locales": [], "created": _ep(NOW), "balance": 0,
        "currency": "usd", "delinquent": False, "livemode": True, "phone": None,
    }


def _charge(chid: str, invoice: str, refunds: list[dict]) -> dict:
    return {"id": chid, "invoice": invoice, "refunds": {"data": refunds, "has_more": False}}


def _refund(rid: str, charge: str | dict, amount: int, *, reason: str | None = None) -> dict:
    return {
        "id": rid, "charge": charge, "amount": amount, "currency": "usd",
        "status": "succeeded", "reason": reason, "created": _ep(NOW),
    }


def _cn(cnid: str, invoice: str, total: int, *, reason: str | None = None) -> dict:
    return {
        "id": cnid, "invoice": invoice, "total": total, "currency": "usd",
        "status": "issued", "reason": reason, "created": _ep(NOW),
    }


def _event(eid: str, etype: str, obj_id: str, created: int) -> dict:
    return {"id": eid, "type": etype, "created": created, "data": {"object": {"id": obj_id}}}


class FakeTransport:
    """In-memory Stripe read surface. ``get(path, params=None) -> dict``; raises
    StripeHTTPError(404) for an unknown object id (so _hydrate's gone-object path is real)."""

    def __init__(self) -> None:
        self.invoices: dict[str, dict] = {}
        self.line_pages: dict[str, list[dict]] = {}   # inv_id -> queued /lines pages
        self.customers: dict[str, dict] = {}
        self.charges: dict[str, dict] = {}
        self.credit_notes: dict[str, dict] = {}
        self.feed_events: list[dict] = []
        self.probe_event: dict | None = None
        self.list_customers: list[dict] = []
        self.list_invoices: list[dict] = []
        self.list_refunds: list[dict] = []
        self.list_credit_notes: list[dict] = []
        self.calls: list[tuple[str, dict]] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        params = params or {}
        self.calls.append((path, dict(params)))
        if path == "events":
            if "created[gt]" in params:
                return {"data": list(self.feed_events), "has_more": False}
            return {"data": [self.probe_event] if self.probe_event else [], "has_more": False}
        if path.startswith("invoices/") and path.endswith("/lines"):
            inv_id = path[len("invoices/"):-len("/lines")]
            queue = self.line_pages.get(inv_id, [])
            return queue.pop(0) if queue else {"data": [], "has_more": False}
        if path == "invoices":
            return {"data": list(self.list_invoices), "has_more": False}
        if path.startswith("invoices/"):
            return self._one(self.invoices, path[len("invoices/"):], "invoice")
        if path == "customers":
            return {"data": list(self.list_customers), "has_more": False}
        if path.startswith("customers/"):
            return self._one(self.customers, path[len("customers/"):], "customer")
        if path.startswith("charges/") and path.endswith("/refunds"):
            chid = path[len("charges/"):-len("/refunds")]
            ch = self.charges.get(chid, {})
            return {"data": list((ch.get("refunds") or {}).get("data", [])), "has_more": False}
        if path.startswith("charges/"):
            return self._one(self.charges, path[len("charges/"):], "charge")
        if path == "credit_notes":
            return {"data": list(self.list_credit_notes), "has_more": False}
        if path.startswith("credit_notes/"):
            return self._one(self.credit_notes, path[len("credit_notes/"):], "credit note")
        if path == "refunds":
            return {"data": list(self.list_refunds), "has_more": False}
        raise AssertionError(f"FakeTransport got unexpected path: {path!r}")

    @staticmethod
    def _one(store: dict[str, dict], oid: str, label: str) -> dict:
        if oid not in store:
            raise StripeHTTPError(404, f"no such {label} {oid}")
        return store[oid]


# ── Fixtures ─────────────────────────────────────────────────────────────────

_CLEAN_TABLES = (
    "ps_stripe_invoice_lines", "ps_stripe_invoices", "ps_stripe_refunds",
    "ps_stripe_credit_notes", "ps_stripe_events_processed", "cip_sync_runs",
    "ps_stripe_customers",  # before ps_brands (FK)
    "ps_products",          # after lines (lines->ps_products FK, ON DELETE RESTRICT)
)


def _cleanup(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": TENANT})
        for tbl in _CLEAN_TABLES:
            conn.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :t"), {"t": TENANT})
        conn.execute(text("DELETE FROM ps_brands WHERE tenant_id = :t"), {"t": TENANT})


def _seed_products(engine: Engine) -> None:
    """ps_products is a controlled dimension seeded per-tenant by migration for the real PS
    tenant (cip_39); the synthetic test tenant needs the same two rows so the invoice-line
    FK (tenant_id, product_id) -> ps_products is satisfiable."""
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": TENANT})
        conn.execute(
            text(
                "INSERT INTO ps_products (id, tenant_id, product_id, name, fee_basis) VALUES "
                "(gen_random_uuid(), :t, 'connect', 'Connect', 'gmv_pct'), "
                "(gen_random_uuid(), :t, 'boosted', 'Boosted', 'ad_spend_pct') "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": TENANT},
        )


def _seed_success_cursor(engine: Engine, cursor: dict, started_at: datetime) -> None:
    """A prior successful ps-stripe-v1 run so incremental has a cursor to resume from."""
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": TENANT})
        conn.execute(
            text(
                "INSERT INTO cip_sync_runs (id, tenant_id, connector_id, connector_name, "
                "batch_id, sync_mode, status, started_at, cursor_state, metadata) VALUES "
                "(:id, :t, :cid, 'seed', :bid, 'incremental', 'success', :sa, "
                "CAST(:cs AS jsonb), CAST('{}' AS jsonb))"
            ),
            {"id": str(uuid4()), "t": TENANT, "cid": CONNECTOR_ID, "bid": str(uuid4()),
             "sa": started_at, "cs": json.dumps(cursor)},
        )


@pytest.fixture
def seeded(seeded_engine: Engine) -> Generator[Engine, None, None]:
    _cleanup(seeded_engine)
    _seed_products(seeded_engine)
    try:
        yield seeded_engine
    finally:
        _cleanup(seeded_engine)


def _count(engine: Engine, sql: str, **params: object) -> int:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar() or 0


# ── (a) + (b) incremental applies, then is idempotent ────────────────────────


def _incremental_fake() -> FakeTransport:
    fake = FakeTransport()
    fake.invoices["in_1"] = _inv(
        "in_1", "cus_1",
        [_line("il_1", "April 2026 - Wayward Connect - Attribution Usage Fee", 1000)],
    )
    fake.customers["cus_1"] = _cust("cus_1", brand=BRAND, name="Brand One")
    fake.charges["ch_1"] = _charge(
        "ch_1", "in_1", [_refund("re_1", "ch_1", 500, reason="requested_by_customer")]
    )
    fake.credit_notes["cn_1"] = _cn("cn_1", "in_1", 200, reason="order_change")
    fake.feed_events = [
        _event("evt_1", "invoice.paid", "in_1", _ep(NOW - timedelta(minutes=30))),
        _event("evt_2", "charge.refunded", "ch_1", _ep(NOW - timedelta(minutes=20))),
        _event("evt_3", "credit_note.created", "cn_1", _ep(NOW - timedelta(minutes=10))),
    ]
    return fake


@pytest.mark.requires_postgres
def test_incremental_applies_then_idempotent(seeded: Engine) -> None:
    engine = seeded
    _seed_success_cursor(
        engine,
        {"last_event_created": (NOW - timedelta(hours=1)).isoformat(), "last_event_id": "evt_seed"},
        NOW - timedelta(days=1),
    )
    fake = _incremental_fake()

    r1 = run_ps_stripe_sync(engine, tenant_id=TENANT, mode="incremental", transport=fake, now=NOW)

    assert r1["status"] == "success"
    assert r1["effective_mode"] == "incremental" and r1["escalated_to_full"] is False
    assert (r1["invoices"], r1["lines"], r1["refunds"], r1["credit_notes"]) == (1, 1, 1, 1)
    assert r1["events_applied"] == 3

    # classify() landed the usage line correctly (verbatim kernel). Tenant-scope every read:
    # stripe_line_id is unique PER TENANT, and neighbouring suites (test_cip_104/107) seed rows
    # with the same generated ids (il_1, ...) under their own tenant.
    with engine.connect() as conn:
        line = conn.execute(text(
            "SELECT is_ps_base, product_id, channel, fee_type, billing_month, brand_id_source "
            "FROM ps_stripe_invoice_lines WHERE stripe_line_id = 'il_1' AND tenant_id = :t"
        ), {"t": TENANT}).fetchone()
    assert line[0] is True and line[1] == "connect" and line[2] == "wayward_connect"
    assert line[3] == "usage" and str(line[4]) == "2026-04-01" and line[5] == "stripe_metadata"

    # evidence rows landed with resolved invoice ids
    assert _count(engine, "SELECT amount FROM ps_stripe_refunds WHERE stripe_refund_id='re_1' "
                  "AND tenant_id=:t", t=TENANT) == 5
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT invoice_id FROM ps_stripe_refunds WHERE stripe_refund_id='re_1' "
            "AND tenant_id=:t"
        ), {"t": TENANT}).scalar() == "in_1"
        assert conn.execute(text(
            "SELECT invoice_id FROM ps_stripe_credit_notes WHERE stripe_credit_note_id='cn_1' "
            "AND tenant_id=:t"
        ), {"t": TENANT}).scalar() == "in_1"

    # cursor advanced to the newest event (evt_3, created NOW-10min)
    assert r1["cursor"]["last_event_id"] == "evt_3"
    assert r1["cursor"]["last_event_created"] == (NOW - timedelta(minutes=10)).isoformat()

    # heartbeat row: counters mapped (created=refunds+cn+events=5; updated=inv+lines=2; ingested=7)
    with engine.connect() as conn:
        hb = conn.execute(text(
            "SELECT status, sync_mode, rows_created, rows_updated, rows_ingested "
            "FROM cip_sync_runs WHERE id = :id"
        ), {"id": r1["sync_run_id"]}).fetchone()
    assert hb[0] == "success" and hb[1] == "incremental"
    assert (hb[2], hb[3], hb[4]) == (5, 2, 7)

    # (b) re-run the same events → nothing new; all three de-duped
    r2 = run_ps_stripe_sync(engine, tenant_id=TENANT, mode="incremental", transport=fake, now=NOW)
    assert r2["events_applied"] == 0
    assert r2["events_skipped_duplicate"] == 3
    assert (r2["invoices"], r2["lines"], r2["refunds"], r2["credit_notes"]) == (0, 0, 0, 0)
    assert _count(engine, "SELECT count(*) FROM ps_stripe_invoice_lines WHERE tenant_id=:t",
                  t=TENANT) == 1
    assert _count(engine, "SELECT count(*) FROM ps_stripe_events_processed WHERE tenant_id=:t",
                  t=TENANT) == 3


# ── (c) advisory lock held → skip ────────────────────────────────────────────


@pytest.mark.requires_postgres
def test_lock_held_returns_skipped(seeded: Engine) -> None:
    engine = seeded
    key = _advisory_lock_key(UUID(TENANT), CONNECTOR_ID)
    holder = engine.connect()
    try:
        assert holder.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar() is True
        holder.commit()

        result = run_ps_stripe_sync(
            engine, tenant_id=TENANT, mode="incremental", transport=FakeTransport(), now=NOW
        )
        assert result["status"] == "skipped" and result["reason"] == "lock-held"

        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT status, error_detail->>'reason' FROM cip_sync_runs WHERE id = :id"
            ), {"id": result["sync_run_id"]}).fetchone()
        assert row[0] == "partial" and row[1] == "lock-held"
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        holder.commit()
        holder.close()


# ── (d) full mode upserts + seeds cursor + prunes old events ─────────────────


@pytest.mark.requires_postgres
def test_full_mode_upserts_seeds_cursor_and_prunes(seeded: Engine) -> None:
    engine = seeded
    # a 60-day-old processed-event row that the 45-day prune must remove
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_stripe_events_processed "
            "(event_id, tenant_id, event_created, event_type, object_id) "
            "VALUES ('evt_old', :t, :old, 'invoice.paid', 'in_old')"
        ), {"t": TENANT, "old": NOW - timedelta(days=60)})

    fake = FakeTransport()
    fake.list_customers = [_cust("cus_2", brand=BRAND2, name="Brand Two")]
    fake.list_invoices = [_inv(
        "in_2", "cus_2",
        [_line("il_2", "May 2026 - Amazon - Boosted Affiliate - Usage Fee", 2000)],
    )]
    # refund with an EXPANDED charge (full mode uses expand[]=data.charge) → invoice via the charge
    fake.list_refunds = [_refund("re_2", {"id": "ch_2", "invoice": "in_2"}, 700)]
    fake.list_credit_notes = [_cn("cn_2", "in_2", 300)]
    fake.probe_event = _event(
        "evt_probe", "invoice.paid", "in_2", _ep(NOW - timedelta(minutes=5))
    )

    result = run_ps_stripe_sync(engine, tenant_id=TENANT, mode="full", transport=fake, now=NOW)

    assert result["effective_mode"] == "full" and result["escalated_to_full"] is False
    assert (result["invoices"], result["lines"], result["customers"]) == (1, 1, 1)
    assert (result["refunds"], result["credit_notes"]) == (1, 1)
    assert result["cursor"]["last_event_id"] == "evt_probe"
    assert result["cursor"]["last_event_created"] == (NOW - timedelta(minutes=5)).isoformat()
    assert result["events_pruned"] >= 1

    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT count(*) FROM ps_stripe_events_processed WHERE event_id = 'evt_old' "
            "AND tenant_id = :t"
        ), {"t": TENANT}).scalar() == 0
        assert conn.execute(text(
            "SELECT count(*) FROM ps_brands WHERE wayward_brand_id = :b"
        ), {"b": BRAND2}).scalar() == 1
        assert conn.execute(text(
            "SELECT invoice_id FROM ps_stripe_refunds WHERE stripe_refund_id = 're_2' "
            "AND tenant_id = :t"
        ), {"t": TENANT}).scalar() == "in_2"


# ── (e) invoice with >10 lines paginates (latent-bug fix) ────────────────────


@pytest.mark.requires_postgres
def test_invoice_over_ten_lines_paginates(seeded: Engine) -> None:
    engine = seeded
    _seed_success_cursor(
        engine,
        {"last_event_created": (NOW - timedelta(hours=1)).isoformat(), "last_event_id": "evt_seed"},
        NOW - timedelta(days=1),
    )
    desc = "April 2026 - Wayward Connect - Attribution Usage Fee"
    embedded = [_line(f"il_{i}", desc, 100) for i in range(10)]         # the 10-line embed cap
    extra = [_line(f"il_{i}", desc, 100) for i in range(10, 15)]        # 5 that ONLY /lines returns

    fake = FakeTransport()
    fake.invoices["in_big"] = _inv("in_big", "cus_b", embedded, lines_has_more=True)
    fake.line_pages["in_big"] = [{"data": extra, "has_more": False}]
    fake.customers["cus_b"] = _cust("cus_b", brand=BRAND)
    fake.feed_events = [
        _event("evt_big", "invoice.paid", "in_big", _ep(NOW - timedelta(minutes=5)))
    ]

    result = run_ps_stripe_sync(
        engine, tenant_id=TENANT, mode="incremental", transport=fake, now=NOW
    )

    assert result["lines"] == 15, "all 15 lines must land — not just the embedded 10"
    assert _count(
        engine,
        "SELECT count(*) FROM ps_stripe_invoice_lines WHERE stripe_invoice_id='in_big' "
        "AND tenant_id=:t", t=TENANT,
    ) == 15
