# foundry: kind=connector domain=client-intelligence-platform
"""ps_stripe_extras — sibling Stripe sync for the DATA-ASSET Stripe surface:
charges / disputes / products / subscriptions (cip_115) + payouts /
balance_transactions / prices (cip_118, the cash-recon ledger).

A SIBLING of the money-critical ``ps_stripe_sync`` (ps-stripe-v1): this connector
(``ps-stripe-extras-v1``) captures the DATA-ASSET extras and never touches the
money-critical Stripe SYNC path. Keeping it a sibling (the ``sync/`` dir already
holds several) means a bug here can't break the money feed.

``ps_stripe_balance_transactions`` is the full money ledger (fee/net per
charge/refund/payout); charges' fee/net are filled FROM it (source_id = the charge
id), so the charges pull needs no per-charge expand.

Full list-and-upsert (page + batch-commit; charges are ~tens of thousands). The
objects are append-mostly (a charge/dispute is immutable once settled), so a
periodic full refresh keeps them fresh without the events-cursor machinery the
money sync needs. Idempotent (``ON CONFLICT DO UPDATE``), advisory-locked (own key),
heartbeated via ``SyncRunRecorder``.

card_country (the issuing country of the payer's card) is captured AND, after each
sync, derived into the ``card_country_cn`` / ``card_country_hk`` china nationality
signals (cip_116, Tim-approved 2026-07-20 — see ``_derive_card_country_signals``).
This is the one money-adjacent thing the extras do: it can flip an *unknown* brand
to china. It is deliberately ONE-DIRECTIONAL — it only ever ADDS china evidence; a
human ``manual_review`` not_china still wins in the verdict lens, so a brand Tim
ruled not_china stays not_china even paying CN/HK cards (never assume not-china).

Reuses the proven transport + helpers from ps_stripe_sync (no new dependency).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from cip.integration_mesh.orchestrator import _advisory_lock_key
from cip.integration_mesh.sync.ps_stripe_sync import (
    PAGE,
    StripeTransport,
    _money,
    _paginate,
    _RealStripeTransport,
    _ts,
)
from cip.integration_mesh.sync_run_recorder import SyncRunRecorder

logger = logging.getLogger(__name__)

CONNECTOR_ID = "ps-stripe-extras-v1"
CONNECTOR_NAME = "PS Stripe Extras"

_UP_CHARGE = text(
    """
    INSERT INTO ps_stripe_charges
        (stripe_charge_id, tenant_id, stripe_invoice_id, stripe_customer_id, wayward_brand_id,
         amount, currency, fee, net, card_country, card_brand, card_funding, status, charge_created)
    VALUES (:cid, CAST(:t AS uuid), :inv, :cus, CAST(:brand AS uuid),
            :amount, :currency, :fee, :net, :country, :brand_name, :funding, :status, :created)
    ON CONFLICT (tenant_id, stripe_charge_id) DO UPDATE SET
        stripe_invoice_id=EXCLUDED.stripe_invoice_id,
        stripe_customer_id=EXCLUDED.stripe_customer_id,
        wayward_brand_id=EXCLUDED.wayward_brand_id, amount=EXCLUDED.amount,
        currency=EXCLUDED.currency, fee=EXCLUDED.fee, net=EXCLUDED.net,
        card_country=EXCLUDED.card_country, card_brand=EXCLUDED.card_brand,
        card_funding=EXCLUDED.card_funding, status=EXCLUDED.status,
        charge_created=EXCLUDED.charge_created, ingested_at=now()
    """
)
_UP_DISPUTE = text(
    """
    INSERT INTO ps_stripe_disputes
        (stripe_dispute_id, tenant_id, stripe_charge_id, amount, currency,
         reason, status, dispute_created)
    VALUES (:did, CAST(:t AS uuid), :charge, :amount, :currency, :reason, :status, :created)
    ON CONFLICT (tenant_id, stripe_dispute_id) DO UPDATE SET
        stripe_charge_id=EXCLUDED.stripe_charge_id, amount=EXCLUDED.amount,
        currency=EXCLUDED.currency, reason=EXCLUDED.reason, status=EXCLUDED.status,
        dispute_created=EXCLUDED.dispute_created, ingested_at=now()
    """
)
_UP_PRODUCT = text(
    """
    INSERT INTO ps_stripe_products
        (stripe_product_id, tenant_id, name, active, description, metadata,
         product_created, product_updated)
    VALUES (:pid, CAST(:t AS uuid), :name, :active, :description,
            CAST(:metadata AS jsonb), :created, :updated)
    ON CONFLICT (tenant_id, stripe_product_id) DO UPDATE SET
        name=EXCLUDED.name, active=EXCLUDED.active, description=EXCLUDED.description,
        metadata=EXCLUDED.metadata, product_updated=EXCLUDED.product_updated, ingested_at=now()
    """
)
_UP_SUB = text(
    """
    INSERT INTO ps_stripe_subscriptions
        (stripe_subscription_id, tenant_id, stripe_customer_id, wayward_brand_id, status, price_id,
         stripe_product_id, unit_amount, currency, recurring_interval,
         current_period_start, current_period_end, subscription_created)
    VALUES (:sid, CAST(:t AS uuid), :cus, CAST(:brand AS uuid), :status, :price, :product, :unit,
            :currency, :interval, :cps, :cpe, :created)
    ON CONFLICT (tenant_id, stripe_subscription_id) DO UPDATE SET
        status=EXCLUDED.status, price_id=EXCLUDED.price_id,
        stripe_product_id=EXCLUDED.stripe_product_id, unit_amount=EXCLUDED.unit_amount,
        currency=EXCLUDED.currency, recurring_interval=EXCLUDED.recurring_interval,
        current_period_start=EXCLUDED.current_period_start,
        current_period_end=EXCLUDED.current_period_end, ingested_at=now()
    """
)


_UP_PAYOUT = text(
    """
    INSERT INTO ps_stripe_payouts
        (stripe_payout_id, tenant_id, amount, currency, status, payout_method, payout_type,
         automatic, balance_txn_id, description, statement_descriptor, arrival_date, payout_created)
    VALUES (:pid, CAST(:t AS uuid), :amount, :currency, :status, :method, :ptype,
            :automatic, :btid, :description, :descriptor, :arrival, :created)
    ON CONFLICT (tenant_id, stripe_payout_id) DO UPDATE SET
        amount=EXCLUDED.amount, currency=EXCLUDED.currency, status=EXCLUDED.status,
        payout_method=EXCLUDED.payout_method, payout_type=EXCLUDED.payout_type,
        automatic=EXCLUDED.automatic, balance_txn_id=EXCLUDED.balance_txn_id,
        description=EXCLUDED.description, statement_descriptor=EXCLUDED.statement_descriptor,
        arrival_date=EXCLUDED.arrival_date, payout_created=EXCLUDED.payout_created,
        ingested_at=now()
    """
)
_UP_BALANCE_TXN = text(
    """
    INSERT INTO ps_stripe_balance_transactions
        (stripe_balance_txn_id, tenant_id, amount, fee, net, currency, txn_type,
         reporting_category, source_id, status, available_on, txn_created, description)
    VALUES (:bid, CAST(:t AS uuid), :amount, :fee, :net, :currency, :ttype,
            :category, :source, :status, :available, :created, :description)
    ON CONFLICT (tenant_id, stripe_balance_txn_id) DO UPDATE SET
        amount=EXCLUDED.amount, fee=EXCLUDED.fee, net=EXCLUDED.net, currency=EXCLUDED.currency,
        txn_type=EXCLUDED.txn_type, reporting_category=EXCLUDED.reporting_category,
        source_id=EXCLUDED.source_id, status=EXCLUDED.status, available_on=EXCLUDED.available_on,
        txn_created=EXCLUDED.txn_created, description=EXCLUDED.description, ingested_at=now()
    """
)
_UP_PRICE = text(
    """
    INSERT INTO ps_stripe_prices
        (stripe_price_id, tenant_id, stripe_product_id, unit_amount, currency, price_type,
         recurring_interval, active, nickname, price_created)
    VALUES (:pid, CAST(:t AS uuid), :product, :unit, :currency, :ptype,
            :interval, :active, :nickname, :created)
    ON CONFLICT (tenant_id, stripe_price_id) DO UPDATE SET
        stripe_product_id=EXCLUDED.stripe_product_id, unit_amount=EXCLUDED.unit_amount,
        currency=EXCLUDED.currency, price_type=EXCLUDED.price_type,
        recurring_interval=EXCLUDED.recurring_interval, active=EXCLUDED.active,
        nickname=EXCLUDED.nickname, price_created=EXCLUDED.price_created, ingested_at=now()
    """
)


def _brand_map(conn: Any, tenant: str) -> dict[str, str]:
    """stripe_customer_id -> wayward_brand_id (from the already-synced customers)."""
    rows = conn.execute(
        text(
            "SELECT stripe_customer_id, wayward_brand_id FROM ps_stripe_customers "
            "WHERE tenant_id = CAST(:t AS uuid) AND wayward_brand_id IS NOT NULL"
        ),
        {"t": tenant},
    ).fetchall()
    return {r[0]: str(r[1]) for r in rows}


def shape_charge(c: dict[str, Any], bmap: dict[str, str], tenant: str) -> dict[str, Any]:
    card = (c.get("payment_method_details") or {}).get("card") or {}
    bt = c.get("balance_transaction")
    bt = bt if isinstance(bt, dict) else {}
    cus = c.get("customer")
    return {
        "cid": c["id"], "t": tenant, "inv": c.get("invoice"), "cus": cus,
        "brand": bmap.get(cus) if cus else None,
        "amount": _money(c.get("amount")), "currency": c.get("currency"),
        "fee": _money(bt.get("fee")), "net": _money(bt.get("net")),
        "country": card.get("country"), "brand_name": card.get("brand"),
        "funding": card.get("funding"), "status": c.get("status"),
        "created": _ts(c.get("created")),
    }


def shape_dispute(d: dict[str, Any], tenant: str) -> dict[str, Any]:
    return {
        "did": d["id"], "t": tenant, "charge": d.get("charge"),
        "amount": _money(d.get("amount")), "currency": d.get("currency"),
        "reason": d.get("reason"), "status": d.get("status"), "created": _ts(d.get("created")),
    }


def shape_product(p: dict[str, Any], tenant: str) -> dict[str, Any]:
    return {
        "pid": p["id"], "t": tenant, "name": p.get("name"), "active": p.get("active"),
        "description": p.get("description"), "metadata": json.dumps(p.get("metadata") or {}),
        "created": _ts(p.get("created")), "updated": _ts(p.get("updated")),
    }


def shape_sub(s: dict[str, Any], bmap: dict[str, str], tenant: str) -> dict[str, Any]:
    item = ((s.get("items") or {}).get("data") or [{}])[0]
    price = item.get("price") or {}
    cus = s.get("customer")
    return {
        "sid": s["id"], "t": tenant, "cus": cus, "brand": bmap.get(cus) if cus else None,
        "status": s.get("status"), "price": price.get("id"), "product": price.get("product"),
        "unit": _money(price.get("unit_amount")), "currency": s.get("currency"),
        "interval": (price.get("recurring") or {}).get("interval"),
        "cps": _ts(s.get("current_period_start")), "cpe": _ts(s.get("current_period_end")),
        "created": _ts(s.get("created")),
    }


def shape_payout(p: dict[str, Any], tenant: str) -> dict[str, Any]:
    return {
        "pid": p["id"], "t": tenant, "amount": _money(p.get("amount")),
        "currency": p.get("currency"), "status": p.get("status"),
        "method": p.get("method"), "ptype": p.get("type"), "automatic": p.get("automatic"),
        "btid": p.get("balance_transaction"), "description": p.get("description"),
        "descriptor": p.get("statement_descriptor"),
        "arrival": _ts(p.get("arrival_date")), "created": _ts(p.get("created")),
    }


def shape_balance_txn(b: dict[str, Any], tenant: str) -> dict[str, Any]:
    src = b.get("source")  # a string id by default (ch_/re_/po_…); dict if expanded
    return {
        "bid": b["id"], "t": tenant, "amount": _money(b.get("amount")),
        "fee": _money(b.get("fee")), "net": _money(b.get("net")),
        "currency": b.get("currency"), "ttype": b.get("type"),
        "category": b.get("reporting_category"),
        "source": (src if isinstance(src, str)
                   else src.get("id") if isinstance(src, dict) else None),
        "status": b.get("status"), "available": _ts(b.get("available_on")),
        "created": _ts(b.get("created")), "description": b.get("description"),
    }


def shape_price(p: dict[str, Any], tenant: str) -> dict[str, Any]:
    return {
        "pid": p["id"], "t": tenant, "product": p.get("product"),
        "unit": _money(p.get("unit_amount")), "currency": p.get("currency"),
        "ptype": p.get("type"), "interval": (p.get("recurring") or {}).get("interval"),
        "active": p.get("active"), "nickname": p.get("nickname"),
        "created": _ts(p.get("created")),
    }


_DERIVE_CARD_SIGNALS = text(
    """
    INSERT INTO ps_nationality_signals
        (id, tenant_id, wayward_brand_id, signal, strength, points_to,
         evidence, source_system, asserted_by)
    SELECT gen_random_uuid(), CAST(:t AS uuid), wayward_brand_id,
           CASE WHEN cn >= hk THEN 'card_country_cn' ELSE 'card_country_hk' END,
           'strong', 'china',
           'Pays predominantly with ' || CASE WHEN cn >= hk THEN 'CN' ELSE 'HK' END
             || '-issued cards (' || cnhk || ' of ' || known
             || ' located charges) — Stripe payment_method_details.card.country',
           'stripe:card_country', :who
      FROM (
        SELECT wayward_brand_id,
               count(*) FILTER (WHERE card_country = 'CN') AS cn,
               count(*) FILTER (WHERE card_country = 'HK') AS hk,
               count(*) FILTER (WHERE card_country IN ('CN', 'HK')) AS cnhk,
               count(*) FILTER (WHERE card_country IS NOT NULL) AS known
          FROM ps_stripe_charges
         WHERE tenant_id = CAST(:t AS uuid) AND wayward_brand_id IS NOT NULL
         GROUP BY wayward_brand_id
      ) x
     WHERE cnhk > (known - cnhk)
    """
)


def _derive_card_country_signals(engine: Engine, tenant: str) -> int:
    """Regenerate the ``card_country_cn`` / ``card_country_hk`` china signals from
    the charges just synced. A brand paying predominantly (CN+HK > all other located
    charges) with CN/HK-issued cards gets a china signal (cip_116 promoted these to
    confirming signals). Delete-then-insert keeps it exactly current (a brand can
    drop out of dominance or switch CN↔HK). This ONLY ever ADDS china evidence — the
    verdict lens still lets a human ``manual_review`` not_china override it (checked
    first), so a Tim-ruled not_china brand stays not_china even paying CN/HK cards.
    Manual signals (other ``source_system``s, e.g. tim_batch_approval) are untouched.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM ps_nationality_signals WHERE tenant_id = CAST(:t AS uuid) "
                "AND source_system = 'stripe:card_country'"
            ),
            {"t": tenant},
        )
        res = conn.execute(_DERIVE_CARD_SIGNALS, {"t": tenant, "who": CONNECTOR_ID})
        return res.rowcount or 0


def _run_extras(
    engine: Engine, transport: StripeTransport, tenant_uuid: UUID, tenant: str
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    with SyncRunRecorder(
        engine, tenant_id=tenant_uuid, client_id=None,
        connector_id=CONNECTOR_ID, connector_name=CONNECTOR_NAME, sync_mode="full",
    ) as run:
        with engine.begin() as conn:
            bmap = _brand_map(conn, tenant)

        # charges: PAGE + BATCH-commit per page. Charges are the high-volume table
        # (tens of thousands on this account). Each page is one executemany, committed
        # immediately: bounded memory, resumable. NO expand — card_country is inline;
        # fee/net are filled from ps_stripe_balance_transactions below (the ledger),
        # ~6x cheaper than the per-charge balance_transaction expand.
        n_charges = 0
        after: str | None = None
        while True:
            params: dict[str, Any] = {"limit": PAGE}
            if after:
                params["starting_after"] = after
            page = transport.get("charges", params)
            rows = page.get("data", [])
            if rows:
                with engine.begin() as conn:
                    conn.execute(_UP_CHARGE, [shape_charge(c, bmap, tenant) for c in rows])
                n_charges += len(rows)
                after = rows[-1]["id"]
            if not rows or not page.get("has_more"):
                break
        counts["charges"] = n_charges

        # small tables (low volume): collect, then ONE batched upsert each.
        disputes = _paginate(transport, "disputes")
        if disputes:
            with engine.begin() as conn:
                conn.execute(_UP_DISPUTE, [shape_dispute(d, tenant) for d in disputes])
        counts["disputes"] = len(disputes)

        products = _paginate(transport, "products")
        if products:
            with engine.begin() as conn:
                conn.execute(_UP_PRODUCT, [shape_product(p, tenant) for p in products])
        counts["products"] = len(products)

        subs = _paginate(transport, "subscriptions", {"status": "all"})
        if subs:
            with engine.begin() as conn:
                conn.execute(_UP_SUB, [shape_sub(s, bmap, tenant) for s in subs])
        counts["subscriptions"] = len(subs)

        # payouts (Stripe -> Wayward bank cash-out) — low volume, collect + batch.
        payouts = _paginate(transport, "payouts")
        if payouts:
            with engine.begin() as conn:
                conn.execute(_UP_PAYOUT, [shape_payout(p, tenant) for p in payouts])
        counts["payouts"] = len(payouts)

        # balance_transactions (the full money ledger) — high volume, page + batch.
        n_bt = 0
        after = None
        while True:
            bt_params: dict[str, Any] = {"limit": PAGE}
            if after:
                bt_params["starting_after"] = after
            page = transport.get("balance_transactions", bt_params)
            rows = page.get("data", [])
            if rows:
                with engine.begin() as conn:
                    conn.execute(_UP_BALANCE_TXN, [shape_balance_txn(b, tenant) for b in rows])
                n_bt += len(rows)
                after = rows[-1]["id"]
            if not rows or not page.get("has_more"):
                break
        counts["balance_transactions"] = n_bt

        # prices (fee amounts behind the products) — low volume, collect + batch.
        prices = _paginate(transport, "prices")
        if prices:
            with engine.begin() as conn:
                conn.execute(_UP_PRICE, [shape_price(p, tenant) for p in prices])
        counts["prices"] = len(prices)

        # fill charges.fee/net from the ledger (bt.source_id = the charge id) — the
        # authoritative fee/net, so the charges pull skips the expensive expand.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE ps_stripe_charges c SET fee = b.fee, net = b.net "
                    "FROM ps_stripe_balance_transactions b "
                    "WHERE b.tenant_id = c.tenant_id AND b.source_id = c.stripe_charge_id "
                    # 'charge' = legacy ch_ txns, 'payment' = PaymentIntent py_ txns.
                    "AND b.txn_type IN ('charge', 'payment') "
                    "AND (c.fee IS DISTINCT FROM b.fee OR c.net IS DISTINCT FROM b.net)"
                )
            )

        total = sum(counts.values())
        run.counters.rows_received = total
        run.counters.rows_created = total

        # Derive the card_country china signal from the charges just synced
        # (cip_116). Additive china evidence only — a human manual_review not_china
        # still overrides it in the verdict lens.
        card_signals = _derive_card_country_signals(engine, tenant)
    return {
        "status": run.final_status, "sync_run_id": str(run.run_id),
        "tenant_id": tenant, "card_signals": card_signals, **counts,
    }


def run_ps_stripe_extras_sync(
    engine: Engine,
    *,
    tenant_id: UUID | str,
    transport: StripeTransport | None = None,
    now: datetime | None = None,  # noqa: ARG001 — parity with the sibling sync signature
) -> dict[str, Any]:
    """Full refresh of the Stripe extras (charges/disputes/products/subscriptions).

    Args mirror ps_stripe_sync: ``engine`` (CIP Postgres), ``tenant_id`` (REQUIRED,
    no hardcoded default — D-017/018/031), optional injected ``transport`` (tests
    inject a fake; prod reads STRIPE_API_KEY). Advisory-locked + heartbeated.
    """
    tenant_uuid = UUID(str(tenant_id))
    tenant_str = str(tenant_uuid)
    if transport is None:
        transport = _RealStripeTransport.from_env()

    lock_key = _advisory_lock_key(tenant_uuid, CONNECTOR_ID)
    lock_conn = engine.connect()
    try:
        got = lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}).scalar()
        lock_conn.commit()
        if not got:
            with SyncRunRecorder(
                engine, tenant_id=tenant_uuid, client_id=None,
                connector_id=CONNECTOR_ID, connector_name=CONNECTOR_NAME, sync_mode="full",
            ) as run:
                run.counters.error_detail = {"skipped": "lock-held"}
            return {"status": "skipped", "reason": "lock-held", "tenant_id": tenant_str}
        return _run_extras(engine, transport, tenant_uuid, tenant_str)
    finally:
        try:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key})
            lock_conn.commit()
        except Exception as unlock_err:  # noqa: BLE001
            logger.warning("ps-stripe-extras advisory unlock failed (conn GC): %s", unlock_err)
        lock_conn.close()
