# foundry: kind=test domain=client-intelligence-platform
"""Unit tests for cip.integration_mesh.sync.ps_stripe_extras shaping.

The new logic in Sprint 2 is the Stripe-object → row shaping: card_country
extraction, balance-transaction fee/net, customer→brand resolution, and
subscription price parsing. These are pure functions (no DB), so they are tested
directly. The run orchestration reuses ps_stripe_sync's already-tested transport +
SyncRunRecorder; the DB upserts are verified by the prod backfill (Sprint 2 report).
"""
from __future__ import annotations

import json

from cip.integration_mesh.sync.ps_stripe_extras import (
    shape_balance_txn,
    shape_charge,
    shape_dispute,
    shape_payout,
    shape_price,
    shape_product,
    shape_sub,
)

TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
BMAP = {"cus_CN1": "11111111-1111-1111-1111-111111111111"}


# ── charges ──────────────────────────────────────────────────────────────────


def test_shape_charge_extracts_card_country_fee_net_and_brand() -> None:
    charge = {
        "id": "ch_1", "invoice": "in_1", "customer": "cus_CN1",
        "amount": 2305, "currency": "usd", "status": "succeeded", "created": 1_700_000_000,
        "payment_method_details": {"card": {"country": "CN", "brand": "visa", "funding": "credit"}},
        "balance_transaction": {"fee": 131, "net": 2174},
    }
    row = shape_charge(charge, BMAP, TENANT)
    assert row["cid"] == "ch_1"
    assert row["country"] == "CN"          # the nationality signal
    assert row["brand_name"] == "visa"
    assert row["funding"] == "credit"
    assert row["amount"] == 23.05          # cents → dollars
    assert row["fee"] == 1.31              # from balance_transaction
    assert row["net"] == 21.74
    assert row["brand"] == BMAP["cus_CN1"]  # customer → brand resolution
    assert row["inv"] == "in_1"
    assert row["created"] is not None


def test_shape_charge_unexpanded_balance_txn_yields_null_fee_net() -> None:
    # If balance_transaction wasn't expanded it's a string id (or absent) → fee/net None.
    charge = {"id": "ch_2", "customer": None, "amount": 500,
              "balance_transaction": "txn_abc", "payment_method_details": {}}
    row = shape_charge(charge, BMAP, TENANT)
    assert row["fee"] is None
    assert row["net"] is None
    assert row["country"] is None
    assert row["brand"] is None            # no customer → no brand


def test_shape_charge_missing_card_details_is_safe() -> None:
    row = shape_charge({"id": "ch_3", "amount": None}, BMAP, TENANT)
    assert row["country"] is None
    assert row["brand_name"] is None
    assert row["amount"] is None           # _money(None) → None


def test_shape_charge_unknown_customer_leaves_brand_null() -> None:
    row = shape_charge({"id": "ch_4", "customer": "cus_UNSEEN", "amount": 100}, BMAP, TENANT)
    assert row["brand"] is None


# ── disputes ─────────────────────────────────────────────────────────────────


def test_shape_dispute() -> None:
    d = {"id": "dp_1", "charge": "ch_9", "amount": 456, "currency": "usd",
         "reason": "fraudulent", "status": "lost", "created": 1_700_000_000}
    row = shape_dispute(d, TENANT)
    assert row["did"] == "dp_1"
    assert row["charge"] == "ch_9"
    assert row["amount"] == 4.56
    assert row["reason"] == "fraudulent"
    assert row["status"] == "lost"


# ── products ─────────────────────────────────────────────────────────────────


def test_shape_product_serialises_metadata_json() -> None:
    p = {"id": "prod_1", "name": "Commission Fee", "active": True,
         "description": "d", "metadata": {"k": "v"}, "created": 1, "updated": 2}
    row = shape_product(p, TENANT)
    assert row["pid"] == "prod_1"
    assert row["active"] is True
    assert json.loads(row["metadata"]) == {"k": "v"}   # dict → JSON string for jsonb bind


def test_shape_product_null_metadata_is_empty_object() -> None:
    row = shape_product({"id": "prod_2"}, TENANT)
    assert json.loads(row["metadata"]) == {}


# ── subscriptions ────────────────────────────────────────────────────────────


def test_shape_sub_extracts_price_from_first_item() -> None:
    s = {
        "id": "sub_1", "customer": "cus_CN1", "status": "active", "currency": "usd",
        "current_period_start": 1_700_000_000, "current_period_end": 1_702_000_000, "created": 1,
        "items": {"data": [{"price": {"id": "price_1", "product": "prod_1", "unit_amount": 4900,
                                       "recurring": {"interval": "month"}}}]},
    }
    row = shape_sub(s, BMAP, TENANT)
    assert row["sid"] == "sub_1"
    assert row["price"] == "price_1"
    assert row["product"] == "prod_1"
    assert row["unit"] == 49.0
    assert row["interval"] == "month"
    assert row["brand"] == BMAP["cus_CN1"]


def test_shape_sub_no_items_is_safe() -> None:
    row = shape_sub({"id": "sub_2", "customer": None}, BMAP, TENANT)
    assert row["price"] is None
    assert row["unit"] is None
    assert row["interval"] is None


# ── payouts / balance_transactions / prices (cip_118) ──────────────────────────


def test_shape_payout() -> None:
    p = {"id": "po_1", "amount": 500000, "currency": "usd", "status": "paid",
         "method": "standard", "type": "bank_account", "automatic": True,
         "balance_transaction": "txn_po1", "description": "weekly",
         "statement_descriptor": "WAYWARD", "arrival_date": 1_700_000_000,
         "created": 1_699_900_000}
    row = shape_payout(p, TENANT)
    assert row["pid"] == "po_1"
    assert row["amount"] == 5000.00        # cents -> dollars
    assert row["status"] == "paid"
    assert row["automatic"] is True
    assert row["btid"] == "txn_po1"
    assert row["arrival"] is not None


def test_shape_balance_txn_charge_with_fee_net() -> None:
    b = {"id": "txn_1", "amount": 2305, "fee": 131, "net": 2174, "currency": "usd",
         "type": "charge", "reporting_category": "charge", "source": "ch_1",
         "status": "available", "available_on": 1_700_000_000, "created": 1_699_990_000}
    row = shape_balance_txn(b, TENANT)
    assert row["bid"] == "txn_1"
    assert row["amount"] == 23.05
    assert row["fee"] == 1.31
    assert row["net"] == 21.74
    assert row["ttype"] == "charge"
    assert row["source"] == "ch_1"          # links back to the charge


def test_shape_balance_txn_expanded_source_uses_id() -> None:
    # if source is expanded to an object, we still store its id
    b = {"id": "txn_2", "amount": -500, "fee": 0, "net": -500, "type": "refund",
         "source": {"id": "re_9", "object": "refund"}}
    row = shape_balance_txn(b, TENANT)
    assert row["source"] == "re_9"
    assert row["ttype"] == "refund"
    assert row["net"] == -5.00


def test_shape_price() -> None:
    p = {"id": "price_1", "product": "prod_1", "unit_amount": 4900, "currency": "usd",
         "type": "recurring", "recurring": {"interval": "month"}, "active": True,
         "nickname": "monthly", "created": 1_700_000_000}
    row = shape_price(p, TENANT)
    assert row["pid"] == "price_1"
    assert row["product"] == "prod_1"
    assert row["unit"] == 49.00
    assert row["interval"] == "month"
    assert row["active"] is True


def test_shape_price_one_time_no_recurring() -> None:
    row = shape_price({"id": "price_2", "type": "one_time", "unit_amount": 100}, TENANT)
    assert row["interval"] is None
    assert row["unit"] == 1.00
