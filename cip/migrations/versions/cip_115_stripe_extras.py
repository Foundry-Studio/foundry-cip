# foundry: kind=migration domain=client-intelligence-platform
"""cip_115: Stripe extras — charges (+ card country), disputes, products, subscriptions.

WHY THIS EXISTS (DATA-EXPANSION-PLAN.md, Sprint 2)
--------------------------------------------------
The live Stripe feed (cip_111 / ps-stripe-v1) captures invoices/lines/customers/
refunds. This adds the rest of the read surface the current restricted key already
exposes (probed 2026-07-18 — all in scope, no expansion):

  1. ps_stripe_charges       — the actual card charges behind the invoices, with
     **card_country** (payment_method_details.card.country — the ISSUING country
     of the payer's card, a nationality/risk signal), card brand/funding, and the
     balance-transaction **fee** + **net** (the true processing cost + cash).
  2. ps_stripe_disputes      — chargebacks (reason/status/amount).
  3. ps_stripe_products      — the Stripe product catalog (here: fee-label rows).
  4. ps_stripe_subscriptions — recurring plans (EXPECTED EMPTY: Wayward isn't
     subscription-billed — the 0-row probe. Created for completeness/future.)

ADDITIVE — the money engine is NOT touched. These are captured by the sibling
``ps_stripe_extras`` sync (connector_id='ps-stripe-extras-v1'), NOT the money sync.
The card_country → china nationality signal is COMPUTED for review, never written
silently (it can move money by flipping brands to china — gated, per the plan).

Amounts are stored in DOLLARS (the sync converts Stripe cents via _money), matching
ps_stripe_invoice_lines.

Revision ID: cip_115_stripe_extras
Revises: cip_114_brand_revenue
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_115_stripe_extras"
down_revision: str | Sequence[str] | None = "cip_114_brand_revenue"
branch_labels = None
depends_on = None

_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
_TABLES = (
    "ps_stripe_charges",
    "ps_stripe_disputes",
    "ps_stripe_products",
    "ps_stripe_subscriptions",
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
    # ── 1. charges (+ card country, fee, net) ───────────────────────────────
    op.execute(
        """
        CREATE TABLE ps_stripe_charges (
            stripe_charge_id  TEXT NOT NULL,           -- ch_...
            tenant_id         UUID NOT NULL,
            stripe_invoice_id TEXT,                    -- in_... (charge.invoice)
            stripe_customer_id TEXT,                   -- cus_...
            wayward_brand_id  UUID,                    -- resolved via the customer map
            amount            NUMERIC(14,2),           -- charged, DOLLARS
            currency          TEXT,
            fee               NUMERIC(14,2),           -- Stripe processing fee (balance_txn)
            net               NUMERIC(14,2),           -- amount − fee (balance_txn.net)
            card_country      TEXT,                    -- ISSUING country of the card (ISO-2)
            card_brand        TEXT,                    -- visa | mastercard | ...
            card_funding      TEXT,                    -- credit | debit | prepaid
            status            TEXT,                    -- succeeded | pending | failed
            charge_created    TIMESTAMPTZ,
            ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, stripe_charge_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_charges_brand ON ps_stripe_charges "
        "(tenant_id, wayward_brand_id)"
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_charges_country ON ps_stripe_charges "
        "(tenant_id, card_country)"
    )
    op.execute(
        "COMMENT ON TABLE ps_stripe_charges IS $c$"
        "The card charges behind the invoices (ps-stripe-extras-v1 sync). card_country is the "
        "ISSUING country of the payer's card (payment_method_details.card.country) — a SOFT "
        "china nationality signal (CN/HK), never auto-applied. fee/net are the balance-"
        "transaction processing cost + cash. Amounts in DOLLARS. Additive: not read by the "
        "money engine.$c$"
    )
    _secure("ps_stripe_charges")

    # ── 2. disputes (chargebacks) ───────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE ps_stripe_disputes (
            stripe_dispute_id TEXT NOT NULL,           -- dp_...
            tenant_id         UUID NOT NULL,
            stripe_charge_id  TEXT,                    -- ch_... disputed
            amount            NUMERIC(14,2),           -- DOLLARS
            currency          TEXT,
            reason            TEXT,                    -- fraudulent | duplicate | ...
            status            TEXT,                    -- won | lost | needs_response | ...
            dispute_created   TIMESTAMPTZ,
            ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, stripe_dispute_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_disputes_charge ON ps_stripe_disputes "
        "(tenant_id, stripe_charge_id)"
    )
    op.execute(
        "COMMENT ON TABLE ps_stripe_disputes IS $c$Chargebacks (ps-stripe-extras-v1). "
        "Amounts in DOLLARS. Risk/evidence only — not read by the money engine.$c$"
    )
    _secure("ps_stripe_disputes")

    # ── 3. products (the Stripe catalog) ────────────────────────────────────
    op.execute(
        """
        CREATE TABLE ps_stripe_products (
            stripe_product_id TEXT NOT NULL,           -- prod_...
            tenant_id         UUID NOT NULL,
            name              TEXT,
            active            BOOLEAN,
            description       TEXT,
            metadata          JSONB,
            product_created   TIMESTAMPTZ,
            product_updated   TIMESTAMPTZ,
            ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, stripe_product_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ps_stripe_products IS $c$Stripe product catalog "
        "(ps-stripe-extras-v1). Reference only — not read by the money engine.$c$"
    )
    _secure("ps_stripe_products")

    # ── 4. subscriptions (expected empty — Wayward isn't subscription-billed) ─
    op.execute(
        """
        CREATE TABLE ps_stripe_subscriptions (
            stripe_subscription_id TEXT NOT NULL,      -- sub_...
            tenant_id          UUID NOT NULL,
            stripe_customer_id TEXT,
            wayward_brand_id   UUID,
            status             TEXT,
            price_id           TEXT,
            stripe_product_id  TEXT,
            unit_amount        NUMERIC(14,2),          -- DOLLARS
            currency           TEXT,
            recurring_interval TEXT,                   -- month | year
            current_period_start TIMESTAMPTZ,
            current_period_end   TIMESTAMPTZ,
            subscription_created TIMESTAMPTZ,
            ingested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, stripe_subscription_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ps_stripe_subscriptions IS $c$Recurring plans "
        "(ps-stripe-extras-v1). Expected EMPTY — Wayward bills by invoice, not "
        "subscription. Created for completeness/future. Not read by the money engine.$c$"
    )
    _secure("ps_stripe_subscriptions")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
