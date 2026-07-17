# foundry: kind=module domain=client-intelligence-platform touches=integration,storage
"""Project Silk (PS) — Stripe live sync, lifted into the package (AUTOMATIONS-PLAN §3).

WHY THIS EXISTS
---------------
Stripe was a one-shot: all 75,658 lines landed by hand on 2026-07-13 and never
refreshed, so the money engine read a stale snapshot while looking "live". This
module makes Stripe a truly live feed the FAS scheduler can drive hourly — the
``ps_lens_mirror`` / ``signal_harvest`` precedent (a sync module + SyncRunRecorder
heartbeat, callable from scheduler / CLI / tests; the scripts become thin
operator wrappers).

HONESTY NOTE (review H5) — what is lifted verbatim vs replaced
-------------------------------------------------------------
The REUSED-VERBATIM kernels are the penny-reconciled parts: ``classify()`` (the
month/channel/fee_type/is_ps_base parser), the two invoice upsert statements
(``_INV`` / ``_LINE``), and the customer identity kernels (``shape()`` +
``_CUST_UPSERT`` / ``_TEACH_MASTER`` / ``_PROPAGATE_*``). Only the tenant binding
in ``shape()`` is parameterised (was a hardcoded ``PS_TENANT``) so the module is
tenant-scoped by argument (D-017/018/031). The old script ``run()`` CONTROL FLOW
is REPLACED, not lifted: the script prefetched the ENTIRE customer list on every
call (fine for a one-shot, impossible hourly); the incremental path here hydrates
per-event instead.

THE CHANGE FEED (best-practices §2, review C3.3)
------------------------------------------------
Poll ``/v1/events`` (NOT webhooks) as the change feed. A ``created`` cursor alone
silently misses mutations (paid→void, refunds, credit notes), so:
  - poll events since ``cursor.last_event_created − 24h`` (a lookback window that
    absorbs clock skew / late-visible events),
  - for each event, HYDRATE THE NAMED OBJECT BY ID (never trust the event
    payload) and upsert current state. Hydrate-by-ID IS the correctness guard:
    we always land current state, so replaying an event is idempotent — there is
    no separate version check (Stripe invoices carry no reliable ``updated`` to
    compare, and the upserts are unconditional ``ON CONFLICT DO UPDATE``).
  - ``ps_stripe_events_processed`` de-dupes already-applied events. Because
    hydrate-by-ID makes replays idempotent, that table is an OPTIMIZATION + audit
    trail, not a correctness requirement (a lost row = one redundant re-fetch).
  - a cursor that is missing or > 25 days old auto-escalates to a FULL pull (only
    5 days of slack inside Stripe's 30-day event horizon — don't let it slip).

WEEKLY FULL (``mode="full"``)
-----------------------------
The safety net for event-less mutations: re-pull ALL invoices (with the line-
pagination fix, see ``_all_invoice_lines``) + customers + refunds + credit notes,
then seed the cursor from a fresh ``/v1/events?limit=1`` probe so the next
incremental starts from "now − lookback". Deployment order (review M7): the full
refresh is STEP 0 — run once to close the 2026-07-13→now gap and seed the cursor,
THEN enable the hourly schedule.

REFUNDS + CREDIT NOTES ARE EVIDENCE-ONLY (review C1)
---------------------------------------------------
They are INGESTED, never netted into "collected" — refund economics are already
partially inside collected as Wayward's negative paid ``is_ps_base`` lines. See
``cip_111`` table comments + ``scripts/reconcile_refund_overlap.py``.

CONCURRENCY (review C3 — REQUIRED)
----------------------------------
Stripe is entirely a direct-upsert path (it does NOT go through ``run_sync``'s
advisory lock), so this module takes its OWN advisory lock keyed on
``_advisory_lock_key(tenant, 'ps-stripe-v1')`` (the orchestrator's key helper)
around BOTH modes — a second concurrent fire skips cleanly and records a skipped
heartbeat.

HEARTBEAT + COUNTER MAPPING (SyncRunRecorder — deployed schema collapses 7 → 5)
-------------------------------------------------------------------------------
Every run records a ``cip_sync_runs`` row (``connector_id='ps-stripe-v1'``,
``sync_mode`` = the mode that actually RAN). The upserts are unconditional
``ON CONFLICT DO UPDATE``, so a precise SCD insert/update split is not captured
(that is intentional — the kernels are reused verbatim). We map ROWS WRITTEN:
  - ``rows_created``  <- evidence + audit rows written (refunds + credit notes +
                        events_processed records) — insert-mostly in a live feed.
  - ``rows_updated``  <- money-spine rows written (invoice headers + lines +
                        customers) + identity-propagation rowcounts.
  - deployed ``rows_ingested`` = rows_created + rows_updated (total rows written).
  - ``rows_skipped`` <- events fetched but already in ps_stripe_events_processed
                        (the de-dupe optimization) — mapped via rows_skipped_duplicate.
  - ``rows_history`` stays 0 (no history side-table here).
The rich per-category detail is in the returned dict; the recorder counters are
the coarse heartbeat.

CURSOR STATE
------------
``{"last_event_created": <iso8601 UTC>, "last_event_id": "evt_..."}`` is written
DIRECTLY onto this run's ``cip_sync_runs`` row (the recorder's ``__exit__``
excludes ``cursor_state`` by contract, so it is preserved). The next run reads
the latest ``status='success'`` run's ``cursor_state`` for this connector_id.

Public API:
  ``run_ps_stripe_sync(engine, *, tenant_id, mode='incremental', transport=None,
                       now=None) -> dict``  (JSON-safe summary).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from cip.integration_mesh.orchestrator import _advisory_lock_key
from cip.integration_mesh.sync_run_recorder import SyncRunRecorder
from cip.integration_mesh.tenant_context import apply_tenant_context

logger = logging.getLogger(__name__)

# Canonical PS tenant (crm_companion_writeback.PS_TENANT_ID / cip_49). Exposed for
# the operator scripts; run_ps_stripe_sync itself REQUIRES tenant_id (no default).
PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

CONNECTOR_ID = "ps-stripe-v1"
CONNECTOR_NAME = "PS Stripe Live Sync"

API_BASE = "https://api.stripe.com/v1/"
PAGE = 100
LOOKBACK = timedelta(hours=24)          # §2/§3: absorbs skew + late-visible events
PRUNE_DAYS = 45                         # > Stripe's 30-day event retention
FULL_FALLBACK_DAYS = 25                 # cursor older than this → force full (5d slack)
THROTTLE_SECONDS = 0.1                  # ~10 req/s self-throttle (§2.6; volumes tiny)

# The change-feed subscription. Finalised from Stripe's event-types reference:
# the invoice lifecycle (create → finalize → paid/failed/void/uncollectible/delete),
# customer identity, credit notes, and charge refunds. Kept a module constant so the
# FAS schedule + tests + docs read the exact same list.
EVENT_TYPES: tuple[str, ...] = (
    "invoice.created",
    "invoice.updated",
    "invoice.finalized",
    "invoice.paid",
    "invoice.payment_failed",
    "invoice.voided",
    "invoice.marked_uncollectible",
    "invoice.deleted",
    "customer.created",
    "customer.updated",
    "credit_note.created",
    "credit_note.updated",
    "credit_note.voided",
    "charge.refunded",
)

_MONTH = re.compile(r"^([A-Z][a-z]+)\s+(\d{4})\s*-\s*(.*)$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


# ── Pure parsing kernels — LIFTED VERBATIM from scripts/ingest_stripe_invoices.py ──
# (penny-reconciled across all 75,658 lines; reuse, never re-derive — §1/§3)


def _ts(v: int | None) -> datetime | None:
    return datetime.fromtimestamp(v, UTC) if v else None


def _money(cents: int | None) -> float | None:
    return None if cents is None else round(cents / 100.0, 2)


def classify(description: str | None) -> dict[str, Any]:
    """'April 2026 - Wayward Connect - Attribution Usage Fee' -> structured facts."""
    d = (description or "").strip()
    billing_month = None
    m = _MONTH.match(d)
    rest = d
    if m:
        try:
            billing_month = datetime.strptime(
                f"{m.group(1)} {m.group(2)}", "%B %Y"
            ).date()
            rest = m.group(3)
        except ValueError:
            pass
    low = rest.lower()

    if "walmart" in low:
        channel = "walmart"
    elif "boosted" in low:
        channel = "amazon_boosted"
    elif "amazon" in low and "connect" in low:
        channel = "amazon_connect"
    elif "wayward connect" in low:
        channel = "wayward_connect"
    else:
        # Most lines name the BRAND, not the channel:
        #   "October 2025 - Roborock - Associates Usage Fee"
        #   "November 2025 - ALL BRANDS - Attribution Usage Fee"
        # An earlier version filed these as channel='other' with NO product, which silently
        # dropped $2.07M of usage fees — 71% of PS's own base — out of the per-product split.
        channel = "brand_direct"

    recon = "reconciliation" in low
    if "processing fee" in low:
        fee_type = "cc_processing"
    elif "saas" in low or "subscription" in low:
        fee_type = "saas"
    elif "usage" in low:
        fee_type = "reconciliation_usage" if recon else "usage"
    elif "commission" in low:
        fee_type = "reconciliation_commission" if recon else "commission"
    else:
        fee_type = "other"

    # PRODUCT: Boost is ALWAYS explicitly labelled "Boosted" in Wayward's billing — verified
    # across all 75,658 lines: no usage line says "boosted" without saying so plainly.
    # Therefore: no "boosted" in the text => it is CONNECT. This is what lets the
    # brand-named lines ("Roborock - Associates Usage Fee") be priced at all.
    is_usage = fee_type in ("usage", "reconciliation_usage")
    is_fee = is_usage or fee_type in ("commission", "reconciliation_commission")
    product = ("boosted" if "boosted" in low else "connect") if is_fee else None

    is_ps_base = is_usage
    return {
        "billing_month": billing_month, "channel": channel,
        "fee_type": fee_type, "product_id": product, "is_ps_base": is_ps_base,
    }


def shape(cu: dict[str, Any], tenant: str) -> dict[str, Any]:
    """Stripe customer -> our row. Resolves identity, and records how.

    LIFTED VERBATIM from scripts/ingest_stripe_customers.py; only the tenant is now
    an argument (was a hardcoded PS_TENANT) so the module is tenant-scoped by call.
    """
    meta = cu.get("metadata") or {}
    desc = (cu.get("description") or "").strip()

    brand = meta.get("brandId")
    source = "stripe_metadata" if brand and _UUID.match(brand) else None
    if not source:
        brand = None
    # Wayward wrote the id into `description` on the customers whose metadata is empty.
    if brand is None and _UUID.match(desc):
        brand, source = desc, "stripe_description"

    addr = cu.get("address") or {}
    locales = cu.get("preferred_locales") or []
    created = cu.get("created")

    return {
        "cid": cu["id"],
        "t": tenant,
        "brand": brand,
        "src": source,
        "auth0": meta.get("auth0id"),
        "ctype": meta.get("intCustomerType"),
        "email": (cu.get("email") or "").strip().lower() or None,
        "name": cu.get("name"),
        "desc": desc or None,
        "delinq": cu.get("delinquent"),
        # Stripe balance is integer cents; our column is dollars.
        "bal": (cu.get("balance") or 0) / 100.0,
        "cur": cu.get("currency"),
        "country": addr.get("country"),
        "phone": cu.get("phone"),
        "loc": ",".join(locales) or None,
        "created": _ts(created),
        "live": cu.get("livemode"),
    }


# ── Upsert SQL — invoice header + lines LIFTED VERBATIM (keys are the money spine) ──

# brand_id_source (:src) is NOT in the one-shot script's verbatim INSERT, but cip_56
# added a CHECK requiring it whenever wayward_brand_id is set. brand_of resolves via
# customer metadata.brandId ONLY, so its provenance is always 'stripe_metadata'; the
# NULL-brand rows are later filled by _PROPAGATE_* with the true 'stripe_description'
# source. (LATENT-BUG FIX — see _upsert_invoice; parsing/amount kernels unchanged.)
_INV = text("""
    INSERT INTO ps_stripe_invoices (
        tenant_id, stripe_invoice_id, stripe_customer_id, wayward_brand_id, client_id,
        brand_id_source,
        customer_email, customer_name, status, paid, collection_method,
        amount_due, amount_paid, amount_remaining, subtotal, total, currency,
        invoice_number, hosted_invoice_url, created_at_stripe,
        period_start, period_end, due_date
    ) VALUES (
        :t, :iid, :cid, CAST(:wbid AS uuid), CAST(:clid AS uuid),
        :src,
        :email, :name, :status, :paid, :cm,
        :due, :paid_amt, :rem, :sub, :tot, :cur,
        :num, :url, :created, :ps, :pe, :dd
    )
    ON CONFLICT (tenant_id, stripe_invoice_id) DO UPDATE SET
        status = EXCLUDED.status,
        paid = EXCLUDED.paid,
        amount_paid = EXCLUDED.amount_paid,
        amount_remaining = EXCLUDED.amount_remaining,
        ingested_at = now()
""")

_LINE = text("""
    INSERT INTO ps_stripe_invoice_lines (
        tenant_id, stripe_invoice_id, stripe_line_id, wayward_brand_id, client_id,
        brand_id_source,
        description, amount, currency, quantity,
        billing_month, channel, fee_type, product_id, is_ps_base,
        invoice_status, line_period_start, line_period_end
    ) VALUES (
        :t, :iid, :lid, CAST(:wbid AS uuid), CAST(:clid AS uuid),
        :src,
        :desc, :amt, :cur, :qty,
        :bm, :ch, :ft, :pid, :base,
        :istatus, :lps, :lpe
    )
    ON CONFLICT (tenant_id, stripe_line_id) DO UPDATE SET
        invoice_status = EXCLUDED.invoice_status,
        amount = EXCLUDED.amount,
        ingested_at = now()
""")

# ── Customer identity kernels — LIFTED VERBATIM from ingest_stripe_customers.py ──

_CUST_UPSERT = text("""
    INSERT INTO ps_stripe_customers (
        stripe_customer_id, tenant_id, wayward_brand_id, brand_id_source, auth0_id,
        customer_type, email, customer_name, description_raw, delinquent, balance,
        currency, address_country, phone, preferred_locales, created_at_stripe,
        livemode, ingested_at)
    VALUES (
        :cid, CAST(:t AS uuid), CAST(:brand AS uuid), :src, :auth0,
        :ctype, :email, :name, :desc, :delinq, :bal,
        :cur, :country, :phone, :loc, :created,
        :live, now())
    ON CONFLICT (stripe_customer_id) DO UPDATE SET
        wayward_brand_id = EXCLUDED.wayward_brand_id,
        brand_id_source  = EXCLUDED.brand_id_source,
        auth0_id         = EXCLUDED.auth0_id,
        customer_type    = EXCLUDED.customer_type,
        email            = EXCLUDED.email,
        customer_name    = EXCLUDED.customer_name,
        description_raw  = EXCLUDED.description_raw,
        delinquent       = EXCLUDED.delinquent,
        balance          = EXCLUDED.balance,
        currency         = EXCLUDED.currency,
        address_country  = EXCLUDED.address_country,
        phone            = EXCLUDED.phone,
        preferred_locales= EXCLUDED.preferred_locales,
        created_at_stripe= EXCLUDED.created_at_stripe,
        livemode         = EXCLUDED.livemode,
        ingested_at      = now()
""")

_TEACH_MASTER = text("""
    INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name, seen_in_stripe)
    VALUES (CAST(:brand AS uuid), CAST(:t AS uuid), :name, true)
    ON CONFLICT (wayward_brand_id) DO UPDATE
       SET seen_in_stripe = true,
           brand_name = COALESCE(ps_brands.brand_name, EXCLUDED.brand_name),
           updated_at = now()
""")

_PROPAGATE_INV = text("""
    UPDATE ps_stripe_invoices i
       SET wayward_brand_id = c.wayward_brand_id,
           brand_id_source  = c.brand_id_source
      FROM ps_stripe_customers c
     WHERE c.stripe_customer_id = i.stripe_customer_id
       AND i.tenant_id = :t
       AND i.wayward_brand_id IS NULL
       AND c.wayward_brand_id IS NOT NULL
""")

_PROPAGATE_LINES = text("""
    UPDATE ps_stripe_invoice_lines l
       SET wayward_brand_id = c.wayward_brand_id,
           brand_id_source  = c.brand_id_source
      FROM ps_stripe_invoices i
      JOIN ps_stripe_customers c ON c.stripe_customer_id = i.stripe_customer_id
     WHERE i.stripe_invoice_id = l.stripe_invoice_id
       AND l.tenant_id = :t
       AND l.wayward_brand_id IS NULL
       AND c.wayward_brand_id IS NOT NULL
""")

# ── NEW: evidence + audit upserts (simple ON CONFLICT DO UPDATE / DO NOTHING) ──

_REFUND = text("""
    INSERT INTO ps_stripe_refunds (
        stripe_refund_id, tenant_id, charge_id, invoice_id,
        amount, currency, status, reason, refund_created)
    VALUES (:rid, CAST(:t AS uuid), :chg, :inv,
        :amt, :cur, :status, :reason, :created)
    ON CONFLICT (tenant_id, stripe_refund_id) DO UPDATE SET
        charge_id      = EXCLUDED.charge_id,
        invoice_id     = EXCLUDED.invoice_id,
        amount         = EXCLUDED.amount,
        currency       = EXCLUDED.currency,
        status         = EXCLUDED.status,
        reason         = EXCLUDED.reason,
        refund_created = EXCLUDED.refund_created,
        ingested_at    = now()
""")

_CREDIT_NOTE = text("""
    INSERT INTO ps_stripe_credit_notes (
        stripe_credit_note_id, tenant_id, invoice_id,
        total, currency, status, reason, credit_note_created)
    VALUES (:cnid, CAST(:t AS uuid), :inv,
        :total, :cur, :status, :reason, :created)
    ON CONFLICT (tenant_id, stripe_credit_note_id) DO UPDATE SET
        invoice_id          = EXCLUDED.invoice_id,
        total               = EXCLUDED.total,
        currency            = EXCLUDED.currency,
        status              = EXCLUDED.status,
        reason              = EXCLUDED.reason,
        credit_note_created = EXCLUDED.credit_note_created,
        ingested_at         = now()
""")

_EVENT_PROCESSED = text("""
    INSERT INTO ps_stripe_events_processed (
        event_id, tenant_id, event_created, event_type, object_id)
    VALUES (:eid, CAST(:t AS uuid), :created, :etype, :oid)
    ON CONFLICT (event_id) DO NOTHING
""")

_PRUNE = text("""
    DELETE FROM ps_stripe_events_processed
    WHERE tenant_id = CAST(:t AS uuid) AND event_created < :cutoff
""")


# ── Transport (injectable) ───────────────────────────────────────────────────


class StripeHTTPError(Exception):
    """A non-2xx Stripe response. ``status`` is the HTTP status code."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Stripe HTTP {status}: {message}")
        self.status = status


class StripeTransport(Protocol):
    """Minimal Stripe read surface. Tests inject a fake; prod uses the real one.

    A single method so a fake is trivial. ``params`` values may be lists (Stripe's
    ``types[]`` / ``expand[]`` repeat-key convention). Must raise ``StripeHTTPError``
    on non-2xx (404 in particular is caught by ``_hydrate`` to mean "gone")."""

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


class _RealStripeTransport:
    """urllib-based Stripe GET client (no new dependency; mirrors the scripts'
    proven 429-backoff). Self-throttles to ~10 req/s (§2.6)."""

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    @classmethod
    def from_env(cls) -> _RealStripeTransport:
        key = os.environ.get("STRIPE_API_KEY")
        if not key:
            raise RuntimeError(
                "STRIPE_API_KEY is not set — cannot call Stripe. Set a restricted "
                "read-only key (scopes: Invoices, Customers, Credit notes, Charges, "
                "Refunds, Events) or inject a transport."
            )
        return cls(key)

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{API_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._key}"})
        for attempt in range(5):
            try:
                time.sleep(THROTTLE_SECONDS)  # polite self-throttle
                with urllib.request.urlopen(req) as r:
                    return json.load(r)
            except urllib.error.HTTPError as ex:  # noqa: PERF203
                if ex.code == 429 and attempt < 4:  # rate limited — back off
                    time.sleep(2 ** attempt)
                    continue
                raise StripeHTTPError(ex.code, ex.reason or "error") from ex
        raise RuntimeError("unreachable")


def _hydrate(transport: StripeTransport, path: str) -> dict[str, Any] | None:
    """GET an object by id; return None if Stripe says it's gone (404).

    invoice.deleted (drafts) and any race where the object vanished between the
    event and the poll land here — record the event, skip the upsert."""
    try:
        return transport.get(path)
    except StripeHTTPError as ex:
        if ex.status == 404:
            return None
        raise


def _all_invoice_lines(
    transport: StripeTransport, invoice: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return ALL line items for an invoice, paginating past the 10-line embed cap.

    LATENT-BUG FIX (review flag): the original ingest_stripe_invoices.py read only
    ``invoice['lines']['data']`` — the embedded sub-list, which Stripe caps at 10
    with ``has_more=true``. Any invoice with >10 lines silently DROPPED every line
    past the 10th. Here we start from the embedded page and page the rest via
    ``/v1/invoices/{id}/lines`` until ``has_more`` is false."""
    lines_obj = invoice.get("lines") or {}
    out = list(lines_obj.get("data", []))
    has_more = bool(lines_obj.get("has_more"))
    inv_id = invoice["id"]
    while has_more and out:
        page = transport.get(
            f"invoices/{inv_id}/lines",
            {"limit": PAGE, "starting_after": out[-1]["id"]},
        )
        rows = page.get("data", [])
        if not rows:
            break
        out.extend(rows)
        has_more = bool(page.get("has_more"))
    return out


def _paginate(
    transport: StripeTransport, path: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Collect every row across a Stripe list endpoint via ``starting_after``."""
    out: list[dict[str, Any]] = []
    after: str | None = None
    base = dict(params or {})
    base.setdefault("limit", PAGE)
    while True:
        p = dict(base)
        if after:
            p["starting_after"] = after
        page = transport.get(path, p)
        rows = page.get("data", [])
        out.extend(rows)
        if not rows or not page.get("has_more"):
            break
        after = rows[-1]["id"]
    return out


# ── Run context ──────────────────────────────────────────────────────────────


@dataclass
class _Ctx:
    """Everything the per-entity handlers need, so signatures stay small."""

    engine: Engine
    transport: StripeTransport
    tenant: str                       # tenant uuid as str (bind value)
    tenant_uuid: UUID
    now: datetime
    wbid_to_client: dict[str, str] = field(default_factory=dict)
    cust_brand: dict[str, str | None] = field(default_factory=dict)
    # rows-written tallies (mapped onto recorder counters at the end)
    n_invoices: int = 0
    n_lines: int = 0
    n_customers: int = 0
    n_refunds: int = 0
    n_credit_notes: int = 0
    n_events: int = 0
    n_events_skipped: int = 0
    n_propagated: int = 0
    n_pruned: int = 0

    def brand_of(self, cust_id: str | None) -> str | None:
        """customer id -> wayward_brand_id (metadata.brandId), hydrating + caching.

        Mirrors the scripts' ``brand_of``: invoices resolve identity through the
        customer's metadata; the fuller description-recovery lives in ``shape()``
        on the customer path, and ``_PROPAGATE_*`` fills any gaps at run end."""
        if not cust_id:
            return None
        if cust_id not in self.cust_brand:
            cu = _hydrate(self.transport, f"customers/{cust_id}")
            b = (cu.get("metadata") or {}).get("brandId") if cu else None
            self.cust_brand[cust_id] = b if b and _UUID.match(b) else None
        return self.cust_brand[cust_id]


def _load_wbid_to_client(ctx: _Ctx) -> None:
    with ctx.engine.begin() as conn:
        apply_tenant_context(conn, ctx.tenant_uuid)
        ctx.wbid_to_client = {
            str(w): str(c)
            for c, w in conn.execute(
                text(
                    "SELECT id, wayward_brand_id FROM cip_clients "
                    "WHERE wayward_brand_id IS NOT NULL"
                )
            ).fetchall()
        }


# ── Per-entity upserts (each caller supplies an open, tenant-scoped conn) ─────


def _upsert_invoice(ctx: _Ctx, conn: Connection, iv: dict[str, Any]) -> None:
    cust = iv.get("customer")
    if isinstance(cust, dict):
        cust = cust.get("id")
    wbid = ctx.brand_of(cust)
    clid = ctx.wbid_to_client.get(wbid) if wbid else None
    # brand_of is metadata-only, so a resolved brand is always stripe_metadata-sourced.
    src = "stripe_metadata" if wbid else None
    status = iv.get("status")
    # ps_stripe_invoices/lines.wayward_brand_id have an FK to ps_brands (cip_93). In the old
    # two-script model the customers script taught ps_brands FIRST; the live single-pass model
    # can see an invoice event BEFORE its customer event, so TEACH the brand inline to keep the
    # FK satisfied (idempotent; seen_in_stripe=true is correct — we saw it on a Stripe invoice).
    if wbid:
        conn.execute(
            _TEACH_MASTER,
            {"brand": wbid, "t": ctx.tenant, "name": iv.get("customer_name")},
        )
    conn.execute(_INV, {
        "t": ctx.tenant, "iid": iv["id"], "cid": cust,
        "wbid": wbid, "clid": clid, "src": src,
        "email": iv.get("customer_email"), "name": iv.get("customer_name"),
        "status": status, "paid": iv.get("paid"),
        "cm": iv.get("collection_method"),
        "due": _money(iv.get("amount_due")),
        "paid_amt": _money(iv.get("amount_paid")),
        "rem": _money(iv.get("amount_remaining")),
        "sub": _money(iv.get("subtotal")), "tot": _money(iv.get("total")),
        "cur": iv.get("currency"), "num": iv.get("number"),
        "url": iv.get("hosted_invoice_url"),
        "created": _ts(iv.get("created")),
        "ps": _ts(iv.get("period_start")), "pe": _ts(iv.get("period_end")),
        "dd": _ts(iv.get("due_date")),
    })
    ctx.n_invoices += 1
    for li in _all_invoice_lines(ctx.transport, iv):
        c = classify(li.get("description"))
        per = li.get("period") or {}
        conn.execute(_LINE, {
            "t": ctx.tenant, "iid": iv["id"], "lid": li["id"],
            "wbid": wbid, "clid": clid, "src": src,
            "desc": li.get("description"),
            "amt": _money(li.get("amount")),
            "cur": li.get("currency"), "qty": li.get("quantity"),
            "bm": c["billing_month"], "ch": c["channel"],
            "ft": c["fee_type"], "pid": c["product_id"],
            "base": c["is_ps_base"], "istatus": status,
            "lps": _ts(per.get("start")), "lpe": _ts(per.get("end")),
        })
        ctx.n_lines += 1


def _upsert_customer(ctx: _Ctx, conn: Connection, cu: dict[str, Any]) -> None:
    row = shape(cu, ctx.tenant)
    # cache the METADATA brand only (what brand_of resolves) so a same-run invoice
    # event stays stripe_metadata-sourced; description-sourced brands reach invoices
    # via _PROPAGATE_* with the correct provenance instead.
    meta_brand = (cu.get("metadata") or {}).get("brandId")
    ctx.cust_brand[cu["id"]] = meta_brand if meta_brand and _UUID.match(meta_brand) else None
    if row["brand"]:
        conn.execute(_TEACH_MASTER, {"brand": row["brand"], "t": ctx.tenant, "name": row["name"]})
    conn.execute(_CUST_UPSERT, row)
    ctx.n_customers += 1


def _upsert_refunds_from_charge(ctx: _Ctx, conn: Connection, charge: dict[str, Any]) -> None:
    inv = charge.get("invoice")
    if isinstance(inv, dict):
        inv = inv.get("id")
    refunds_obj = charge.get("refunds") or {}
    refunds = list(refunds_obj.get("data", []))
    if refunds_obj.get("has_more"):
        # rare, but page the rest for correctness (mirrors the line-pagination fix).
        refunds = _paginate(ctx.transport, f"charges/{charge['id']}/refunds")
    for rf in refunds:
        _upsert_one_refund(ctx, conn, rf, invoice_id=inv)


def _upsert_one_refund(
    ctx: _Ctx, conn: Connection, rf: dict[str, Any], *, invoice_id: str | None
) -> None:
    chg = rf.get("charge")
    if isinstance(chg, dict):
        chg = chg.get("id")
    inv = invoice_id
    if inv is None and isinstance(rf.get("charge"), dict):
        inv = (rf["charge"].get("invoice") or None)
        if isinstance(inv, dict):
            inv = inv.get("id")
    conn.execute(_REFUND, {
        "rid": rf["id"], "t": ctx.tenant, "chg": chg, "inv": inv,
        "amt": _money(rf.get("amount")), "cur": rf.get("currency"),
        "status": rf.get("status"), "reason": rf.get("reason"),
        "created": _ts(rf.get("created")),
    })
    ctx.n_refunds += 1


def _upsert_credit_note(ctx: _Ctx, conn: Connection, cn: dict[str, Any]) -> None:
    inv = cn.get("invoice")
    if isinstance(inv, dict):
        inv = inv.get("id")
    conn.execute(_CREDIT_NOTE, {
        "cnid": cn["id"], "t": ctx.tenant, "inv": inv,
        "total": _money(cn.get("total")), "cur": cn.get("currency"),
        "status": cn.get("status"), "reason": cn.get("reason"),
        "created": _ts(cn.get("created")),
    })
    ctx.n_credit_notes += 1


# ── Event application (incremental) ──────────────────────────────────────────


def _apply_event(ctx: _Ctx, event: dict[str, Any]) -> None:
    """Hydrate the named object by id + upsert + record the event — one txn.

    Hydrate-by-ID (not the event payload) is the correctness guard. A hydrate that
    404s (invoice.deleted / vanished object) records the event and skips the upsert."""
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    object_id = obj.get("id")

    with ctx.engine.begin() as conn:
        apply_tenant_context(conn, ctx.tenant_uuid)
        if etype.startswith("invoice."):
            full = _hydrate(ctx.transport, f"invoices/{object_id}")
            if full is not None:
                _upsert_invoice(ctx, conn, full)
        elif etype.startswith("customer."):
            full = _hydrate(ctx.transport, f"customers/{object_id}")
            if full is not None:
                _upsert_customer(ctx, conn, full)
        elif etype == "charge.refunded":
            full = _hydrate(ctx.transport, f"charges/{object_id}")
            if full is not None:
                _upsert_refunds_from_charge(ctx, conn, full)
        elif etype.startswith("credit_note."):
            full = _hydrate(ctx.transport, f"credit_notes/{object_id}")
            if full is not None:
                _upsert_credit_note(ctx, conn, full)
        else:  # defensive: an unexpected type still records so we don't re-fetch it
            logger.warning("ps-stripe: unhandled event type %s (recorded, skipped)", etype)

        conn.execute(_EVENT_PROCESSED, {
            "eid": event["id"], "t": ctx.tenant,
            "created": _ts(event.get("created")),
            "etype": etype, "oid": object_id,
        })
        ctx.n_events += 1


def _fetch_events(ctx: _Ctx, created_gt: int) -> list[dict[str, Any]]:
    return _paginate(ctx.transport, "events", {
        "limit": PAGE, "created[gt]": created_gt, "types[]": list(EVENT_TYPES),
    })


def _load_processed(ctx: _Ctx, event_ids: list[str]) -> set[str]:
    if not event_ids:
        return set()
    with ctx.engine.begin() as conn:
        apply_tenant_context(conn, ctx.tenant_uuid)
        rows = conn.execute(
            text(
                "SELECT event_id FROM ps_stripe_events_processed "
                "WHERE tenant_id = CAST(:t AS uuid) AND event_id = ANY(:ids)"
            ),
            {"t": ctx.tenant, "ids": event_ids},
        ).fetchall()
    return {r[0] for r in rows}


# ── Cursor + finalize helpers ────────────────────────────────────────────────


def _read_cursor(engine: Engine, tenant_uuid: UUID) -> dict[str, Any] | None:
    """Latest ``status='success'`` run's cursor_state for this connector."""
    with engine.begin() as conn:
        apply_tenant_context(conn, tenant_uuid)
        row = conn.execute(
            text(
                "SELECT cursor_state FROM cip_sync_runs "
                "WHERE tenant_id = :t AND connector_id = :c "
                "AND status = 'success' AND cursor_state IS NOT NULL "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {"t": str(tenant_uuid), "c": CONNECTOR_ID},
        ).scalar()
    if row is None:
        return None
    return row if isinstance(row, dict) else json.loads(row)


def _write_cursor(
    engine: Engine, tenant_uuid: UUID, run_id: UUID, cursor: dict[str, Any]
) -> None:
    """Write cursor_state onto THIS run's row (recorder __exit__ preserves it)."""
    with engine.begin() as conn:
        apply_tenant_context(conn, tenant_uuid)
        conn.execute(
            text(
                "UPDATE cip_sync_runs SET cursor_state = CAST(:c AS jsonb) WHERE id = :id"
            ),
            {"c": json.dumps(cursor, default=str), "id": str(run_id)},
        )


def _needs_full(cursor: dict[str, Any] | None, now: datetime) -> bool:
    """No cursor, or a cursor older than FULL_FALLBACK_DAYS → escalate to full
    (only 5 days of slack inside Stripe's 30-day event horizon)."""
    if not cursor or not cursor.get("last_event_created"):
        return True
    last = datetime.fromisoformat(cursor["last_event_created"])
    return (now - last) > timedelta(days=FULL_FALLBACK_DAYS)


def _propagate_and_prune(ctx: _Ctx) -> None:
    """Push recovered customer identities onto invoices/lines, then prune old
    processed-event rows. One tenant-scoped txn."""
    cutoff = ctx.now - timedelta(days=PRUNE_DAYS)
    with ctx.engine.begin() as conn:
        apply_tenant_context(conn, ctx.tenant_uuid)
        ctx.n_propagated += conn.execute(_PROPAGATE_INV, {"t": ctx.tenant}).rowcount or 0
        ctx.n_propagated += conn.execute(_PROPAGATE_LINES, {"t": ctx.tenant}).rowcount or 0
        ctx.n_pruned = conn.execute(_PRUNE, {"t": ctx.tenant, "cutoff": cutoff}).rowcount or 0


def _probe_cursor(ctx: _Ctx) -> dict[str, Any]:
    """Seed the cursor from the most recent event (full mode). Empty account →
    seed from ``now`` so the next incremental starts at now − lookback."""
    page = ctx.transport.get("events", {"limit": 1})
    rows = page.get("data", [])
    if rows:
        e = rows[0]
        return {
            "last_event_created": _ts(e["created"]).isoformat(),
            "last_event_id": e["id"],
        }
    return {"last_event_created": ctx.now.isoformat(), "last_event_id": None}


def _map_counters(ctx: _Ctx, run: SyncRunRecorder) -> None:
    # rows written, split evidence/audit (created) vs money-spine (updated); see docstring.
    run.counters.rows_created = ctx.n_refunds + ctx.n_credit_notes + ctx.n_events
    run.counters.rows_updated = (
        ctx.n_invoices + ctx.n_lines + ctx.n_customers + ctx.n_propagated
    )
    run.counters.rows_skipped_duplicate = ctx.n_events_skipped


def _summary(ctx: _Ctx) -> dict[str, Any]:
    return {
        "invoices": ctx.n_invoices,
        "lines": ctx.n_lines,
        "customers": ctx.n_customers,
        "refunds": ctx.n_refunds,
        "credit_notes": ctx.n_credit_notes,
        "events_applied": ctx.n_events,
        "events_skipped_duplicate": ctx.n_events_skipped,
        "identities_propagated": ctx.n_propagated,
        "events_pruned": ctx.n_pruned,
    }


# ── Mode bodies ──────────────────────────────────────────────────────────────


def _run_incremental(
    ctx: _Ctx, run: SyncRunRecorder, cursor: dict[str, Any]
) -> dict[str, Any]:
    _load_wbid_to_client(ctx)
    last_created = datetime.fromisoformat(cursor["last_event_created"])
    created_gt = int((last_created - LOOKBACK).timestamp())

    events = _fetch_events(ctx, created_gt)
    processed = _load_processed(ctx, [e["id"] for e in events])

    # high-water-mark starts at the current cursor; advance over ALL fetched events
    # (even already-applied ones move us past the lookback re-fetch window).
    hw_created = int(last_created.timestamp())
    hw_id = cursor.get("last_event_id") or ""
    for e in events:
        ec, eid = int(e["created"]), e["id"]
        if (ec, eid) > (hw_created, hw_id):
            hw_created, hw_id = ec, eid
        if eid in processed:
            ctx.n_events_skipped += 1
            continue
        _apply_event(ctx, e)

    new_cursor = {
        "last_event_created": _ts(hw_created).isoformat(),
        "last_event_id": hw_id or None,
    }
    _propagate_and_prune(ctx)
    _write_cursor(ctx.engine, ctx.tenant_uuid, run.run_id, new_cursor)
    _map_counters(ctx, run)
    out = _summary(ctx)
    out["cursor"] = new_cursor
    return out


def _run_full(ctx: _Ctx, run: SyncRunRecorder) -> dict[str, Any]:
    _load_wbid_to_client(ctx)

    # 1. Customers first (TEACH_MASTER seeds ps_brands so the invoice FK can bind),
    #    building the cust_brand cache for the invoice pass.
    customers = _paginate(ctx.transport, "customers")
    for cu in customers:
        with ctx.engine.begin() as conn:
            apply_tenant_context(conn, ctx.tenant_uuid)
            _upsert_customer(ctx, conn, cu)

    # 2. Invoices — list with lines expanded, then the pagination fix per invoice.
    invoices = _paginate(ctx.transport, "invoices", {"limit": PAGE, "expand[]": "data.lines"})
    for iv in invoices:
        with ctx.engine.begin() as conn:
            apply_tenant_context(conn, ctx.tenant_uuid)
            _upsert_invoice(ctx, conn, iv)

    # 3. Refunds (expand the charge so we can resolve invoice_id) + credit notes.
    for rf in _paginate(ctx.transport, "refunds", {"limit": PAGE, "expand[]": "data.charge"}):
        with ctx.engine.begin() as conn:
            apply_tenant_context(conn, ctx.tenant_uuid)
            _upsert_one_refund(ctx, conn, rf, invoice_id=None)
    for cn in _paginate(ctx.transport, "credit_notes"):
        with ctx.engine.begin() as conn:
            apply_tenant_context(conn, ctx.tenant_uuid)
            _upsert_credit_note(ctx, conn, cn)

    # 4. Propagate + prune, then seed the cursor from a fresh events probe.
    _propagate_and_prune(ctx)
    new_cursor = _probe_cursor(ctx)
    _write_cursor(ctx.engine, ctx.tenant_uuid, run.run_id, new_cursor)
    _map_counters(ctx, run)
    out = _summary(ctx)
    out["cursor"] = new_cursor
    return out


# ── Public entry point ───────────────────────────────────────────────────────


def run_ps_stripe_sync(
    engine: Engine,
    *,
    tenant_id: UUID | str,
    mode: str = "incremental",
    transport: StripeTransport | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the PS Stripe live sync (incremental hourly, or a weekly full).

    Args:
      engine: SQLAlchemy Engine on the CIP Postgres (``postgresql+psycopg://``).
        The FAS executor passes a NullPool engine, same as the sibling syncs.
      tenant_id: PS tenant UUID (str or UUID). REQUIRED — no hardcoded default
        (D-017/018/031); the operator scripts pass ``PS_TENANT``.
      mode: ``"incremental"`` (default) or ``"full"``. Incremental auto-escalates
        to full when the cursor is missing or > 25 days old (Stripe's events
        expire at 30 days).
      transport: a ``StripeTransport``. Defaults to a real urllib client that
        reads ``STRIPE_API_KEY`` at call time (clear error if missing); tests
        inject a fake.
      now: injectable UTC clock for deterministic tests (cursor-age + prune
        cutoff). Defaults to ``datetime.now(UTC)``.

    Returns a JSON-safe dict:
      ``{status, requested_mode, effective_mode, escalated_to_full, tenant_id,
         sync_run_id, sync_run_status, invoices, lines, customers, refunds,
         credit_notes, events_applied, events_skipped_duplicate,
         identities_propagated, events_pruned, cursor}`` — or, when another run
      holds the advisory lock: ``{status:"skipped", reason:"lock-held",
      sync_run_id, tenant_id, requested_mode}``.
    """
    if mode not in ("incremental", "full"):
        raise ValueError(f"mode must be 'incremental' or 'full', got {mode!r}")

    tenant_uuid = UUID(str(tenant_id))
    tenant_str = str(tenant_uuid)
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware (UTC)")
    if transport is None:
        transport = _RealStripeTransport.from_env()

    lock_key = _advisory_lock_key(tenant_uuid, CONNECTOR_ID)
    lock_conn = engine.connect()
    try:
        got = lock_conn.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}
        ).scalar()
        lock_conn.commit()  # session-level lock survives commit; keep conn out of a txn
        if not got:
            return _record_skip(engine, tenant_uuid, mode)
        return _run_locked(engine, transport, tenant_uuid, tenant_str, mode, now)
    finally:
        try:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key})
            lock_conn.commit()
        except Exception as unlock_err:  # noqa: BLE001
            logger.warning("ps-stripe advisory unlock failed (conn close will GC): %s", unlock_err)
        lock_conn.close()


def _record_skip(engine: Engine, tenant_uuid: UUID, mode: str) -> dict[str, Any]:
    """Record a skipped heartbeat + return the skip dict.

    cip_sync_runs.status has no 'skipped' enum value (CHECK: running/success/
    partial/failed), so a skip is encoded as status='partial' with
    error_detail.skipped — observable, distinct from a real zero-work success, and
    NOT counted as a failure (the FAS task returns cleanly; consecutive_failures
    only climbs on a raised task exception)."""
    with SyncRunRecorder(
        engine,
        tenant_id=tenant_uuid,
        client_id=None,
        connector_id=CONNECTOR_ID,
        connector_name=CONNECTOR_NAME,
        sync_mode=mode,
    ) as run:
        run.counters.error_detail = {"skipped": True, "reason": "lock-held"}
    logger.info("ps-stripe skipped (advisory lock held) tenant=%s mode=%s", tenant_uuid, mode)
    return {
        "status": "skipped",
        "reason": "lock-held",
        "requested_mode": mode,
        "tenant_id": str(tenant_uuid),
        "sync_run_id": str(run.run_id),
    }


def _run_locked(
    engine: Engine,
    transport: StripeTransport,
    tenant_uuid: UUID,
    tenant_str: str,
    requested_mode: str,
    now: datetime,
) -> dict[str, Any]:
    cursor = _read_cursor(engine, tenant_uuid)
    escalated = requested_mode == "incremental" and _needs_full(cursor, now)
    effective_mode = "full" if escalated else requested_mode
    if escalated:
        logger.info(
            "ps-stripe: incremental escalated to full (cursor missing or > %dd old)",
            FULL_FALLBACK_DAYS,
        )

    ctx = _Ctx(
        engine=engine, transport=transport, tenant=tenant_str,
        tenant_uuid=tenant_uuid, now=now,
    )

    with SyncRunRecorder(
        engine,
        tenant_id=tenant_uuid,
        client_id=None,
        connector_id=CONNECTOR_ID,
        connector_name=CONNECTOR_NAME,
        sync_mode=effective_mode,
    ) as run:
        if effective_mode == "full":
            detail = _run_full(ctx, run)
        else:
            assert cursor is not None  # _needs_full guarantees a usable cursor here
            detail = _run_incremental(ctx, run, cursor)

    logger.info(
        "ps-stripe done tenant=%s mode=%s status=%s invoices=%d lines=%d customers=%d "
        "refunds=%d credit_notes=%d events=%d pruned=%d",
        tenant_str, effective_mode, run.final_status, ctx.n_invoices, ctx.n_lines,
        ctx.n_customers, ctx.n_refunds, ctx.n_credit_notes, ctx.n_events, ctx.n_pruned,
    )

    return {
        "status": run.final_status,
        "requested_mode": requested_mode,
        "effective_mode": effective_mode,
        "escalated_to_full": escalated,
        "tenant_id": tenant_str,
        "sync_run_id": str(run.run_id),
        "sync_run_status": run.final_status,
        **detail,
    }
