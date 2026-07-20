# foundry: kind=migration domain=client-intelligence-platform
"""cip_118: Stripe cash-reconciliation extras — payouts, balance_transactions, prices.

WHY (DATA-EXPANSION-PLAN Sprint 2 — the cash-recon piece that was descoped)
--------------------------------------------------------------------------
Sprint 2 (cip_115) captured charges/disputes/products/subscriptions but silently
dropped the plan's "balance_transactions/payouts for cash reconciliation" (plan
§UPDATE line 20). This closes that gap so CIP holds the FULL Stripe money surface
the current key already exposes:

  1. ps_stripe_payouts             — Stripe -> Wayward's bank cash-out events
     (amount, arrival_date, status). "When/how much did Wayward actually get paid
     out." Not in the money engine — a cash-recon + data-asset surface.
  2. ps_stripe_balance_transactions — the FULL money ledger: one row per money
     movement (charge/refund/payout/adjustment/fee) with its **fee** + **net**.
     This is the authoritative fee/net source (covers refunds + payouts too, not
     just charges) and lets a charge's fee/net be derived by source id, so the
     charges sync no longer needs the slow per-charge balance_transaction expand.
  3. ps_stripe_prices              — the Stripe price catalog (the fee amounts
     behind the products). Completes "products/prices"; may be sparse (Wayward
     bills by metered usage, not fixed prices).

ADDITIVE — the money engine (lens_ps_claim etc.) is NOT touched. Captured by the
sibling ps-stripe-extras-v1 sync. Amounts in DOLLARS (via _money), like cip_115.

Revision ID: cip_118_stripe_cash_recon
Revises: cip_117_china_contention
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_118_stripe_cash_recon"
down_revision: str | Sequence[str] | None = "cip_117_china_contention"
branch_labels = None
depends_on = None

_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
_TABLES = (
    "ps_stripe_payouts",
    "ps_stripe_balance_transactions",
    "ps_stripe_prices",
)


def _secure(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON {table} USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON {table} TO {r}")


def upgrade() -> None:
    # ── 1. payouts (Stripe -> Wayward bank cash-out) ─────────────────────────
    op.execute(
        """
        CREATE TABLE ps_stripe_payouts (
            stripe_payout_id  TEXT NOT NULL,           -- po_...
            tenant_id         UUID NOT NULL,
            amount            NUMERIC(14,2),           -- DOLLARS
            currency          TEXT,
            status            TEXT,                    -- paid | pending | in_transit | failed | canceled
            payout_method     TEXT,                    -- standard | instant
            payout_type       TEXT,                    -- bank_account | card
            automatic         BOOLEAN,
            balance_txn_id    TEXT,                    -- the payout's own balance txn
            description       TEXT,
            statement_descriptor TEXT,
            arrival_date      TIMESTAMPTZ,             -- when it lands in the bank
            payout_created    TIMESTAMPTZ,
            ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, stripe_payout_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_payouts_arrival ON ps_stripe_payouts "
        "(tenant_id, arrival_date)"
    )
    op.execute(
        "COMMENT ON TABLE ps_stripe_payouts IS $c$Stripe -> Wayward bank cash-out events "
        "(ps-stripe-extras-v1). Amounts DOLLARS. Cash-recon/data-asset — not the money "
        "engine.$c$"
    )
    _secure("ps_stripe_payouts")

    # ── 2. balance_transactions (the full money ledger + fee/net) ────────────
    op.execute(
        """
        CREATE TABLE ps_stripe_balance_transactions (
            stripe_balance_txn_id TEXT NOT NULL,       -- txn_...
            tenant_id         UUID NOT NULL,
            amount            NUMERIC(14,2),           -- DOLLARS (gross of the movement)
            fee               NUMERIC(14,2),           -- Stripe fee on it
            net               NUMERIC(14,2),           -- amount - fee
            currency          TEXT,
            txn_type          TEXT,                    -- charge | refund | payout | adjustment | stripe_fee | ...
            reporting_category TEXT,                   -- charge | refund | payout | fee | ...
            source_id         TEXT,                    -- the source object (ch_ | re_ | po_ | ...)
            status            TEXT,                    -- available | pending
            available_on      TIMESTAMPTZ,
            txn_created       TIMESTAMPTZ,
            description       TEXT,
            ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, stripe_balance_txn_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_bt_source ON ps_stripe_balance_transactions "
        "(tenant_id, source_id)"
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_bt_type ON ps_stripe_balance_transactions "
        "(tenant_id, txn_type)"
    )
    op.execute(
        "COMMENT ON TABLE ps_stripe_balance_transactions IS $c$The full Stripe money ledger "
        "(ps-stripe-extras-v1): one row per money movement (charge/refund/payout/adjustment/"
        "fee) with fee + net. The authoritative fee/net source; a charge's fee/net is derived "
        "by source_id = the charge id. Amounts DOLLARS. Not the money engine.$c$"
    )
    _secure("ps_stripe_balance_transactions")

    # ── 3. prices (the fee amounts behind the products) ──────────────────────
    op.execute(
        """
        CREATE TABLE ps_stripe_prices (
            stripe_price_id   TEXT NOT NULL,           -- price_...
            tenant_id         UUID NOT NULL,
            stripe_product_id TEXT,                    -- prod_...
            unit_amount       NUMERIC(14,2),           -- DOLLARS
            currency          TEXT,
            price_type        TEXT,                    -- one_time | recurring
            recurring_interval TEXT,                   -- month | year | NULL
            active            BOOLEAN,
            nickname          TEXT,
            price_created     TIMESTAMPTZ,
            ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, stripe_price_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ps_stripe_prices IS $c$Stripe price catalog (ps-stripe-extras-v1). "
        "The fee amounts behind ps_stripe_products. May be sparse (Wayward bills metered "
        "usage, not fixed prices). Amounts DOLLARS. Reference only — not the money engine.$c$"
    )
    _secure("ps_stripe_prices")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
