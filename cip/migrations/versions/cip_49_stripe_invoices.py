# foundry: kind=migration domain=client-intelligence-platform
"""cip_49: Stripe invoices + invoice LINES — billed vs paid, per brand, per month, per product.

WHY THIS IS THE KEYSTONE
------------------------
Everything in CIP until now came from Jake's monthly reports — i.e. Wayward telling us
what Wayward paid us. We could only ever catch Wayward's own internal inconsistencies.
Stripe is the SOURCE: what was actually BILLED to the brand, and what was actually
COLLECTED. It covers EVERY brand, not just PS's book, and it decomposes the fees by
product — which Jake's single `USAGE_FEES_PAID` column does not.

THE JOIN IS EXACT, NOT FUZZY
----------------------------
Stripe customer metadata carries `brandId` — literally the wayward_brand_id:
    {"auth0id": "...", "brandId": "4f1b6224-...", "intCustomerType": "PARENT_BRAND"}
So invoice -> customer -> brandId -> cip_clients. No email matching, no name matching.
(We keep customer_email anyway, as a fallback and as evidence.)

THE LINE TABLE IS WHERE THE TRUTH LIVES
---------------------------------------
Line descriptions encode month + channel + fee type:
    "April 2026 - Wayward Connect - Attribution Usage Fee"
    "April 2026 - Amazon - Boosted Affiliate - ACC Bonus - Usage Fee"
    "June 2026 - Credit Card Processing Fee"
    "March 2026 - Walmart - Affiliate - Commission Fee"      <- a channel we did not know existed

So each line is parsed into: billing_month, channel, fee_type, product_id, is_ps_base.

  is_ps_base = TRUE only for USAGE fees (Connect + Boosted + their reconciliations).
  Commission fees are creator PASS-THROUGH and are NOT PS's base — this is the single
  most expensive misreading available (doc 11 exists because an agent made it), so the
  flag is computed at ingest and carries a comment saying so.

Reconciliation lines ("Attribution Reconciliation Usage") are ADJUSTMENTS to earlier
months and can be negative. They are usage fees and DO belong in the base — dropping them
would silently understate or overstate what we are owed.

Two tables, header + lines, rather than one flattened table: an invoice has many lines,
and collapsing them is exactly what destroyed the per-product split in Jake's reports.

Revision ID: cip_49_stripe_invoices
Revises: cip_48_frozen_exclusion
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_49_stripe_invoices"
down_revision: str | Sequence[str] | None = "cip_48_frozen_exclusion"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

CHANNELS = ("wayward_connect", "amazon_connect", "amazon_boosted", "walmart", "other")
FEE_TYPES = (
    "usage", "commission", "cc_processing", "saas",
    "reconciliation_usage", "reconciliation_commission", "other",
)


def upgrade() -> None:
    # ── Invoice header: billed vs paid ──────────────────────────────────────
    op.execute(
        """
        CREATE TABLE ps_stripe_invoices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,

            stripe_invoice_id TEXT NOT NULL,
            stripe_customer_id TEXT,
            wayward_brand_id UUID,        -- from customer.metadata.brandId — the EXACT key
            client_id UUID,
            customer_email TEXT,
            customer_name TEXT,

            status TEXT,                  -- draft|open|paid|uncollectible|void
            paid BOOLEAN,
            collection_method TEXT,

            amount_due NUMERIC(14,2),     -- BILLED
            amount_paid NUMERIC(14,2),    -- COLLECTED
            amount_remaining NUMERIC(14,2),
            subtotal NUMERIC(14,2),
            total NUMERIC(14,2),
            currency TEXT,

            invoice_number TEXT,
            hosted_invoice_url TEXT,
            created_at_stripe TIMESTAMPTZ,
            period_start TIMESTAMPTZ,
            period_end TIMESTAMPTZ,
            due_date TIMESTAMPTZ,

            ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, stripe_invoice_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_inv_brand ON ps_stripe_invoices "
        "(tenant_id, wayward_brand_id)"
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_inv_status ON ps_stripe_invoices "
        "(tenant_id, status, created_at_stripe)"
    )
    op.execute(
        "COMMENT ON TABLE ps_stripe_invoices IS "
        "'Stripe invoice HEADERS — what Wayward BILLED a brand (amount_due) versus what it "
        "actually COLLECTED (amount_paid). Every number in CIP before this came from Jake''s "
        "reports; this is the source. Covers EVERY brand, not just PS''s book. "
        "wayward_brand_id comes from Stripe customer metadata.brandId — an exact join, not a "
        "name/email guess. PS is paid on cash ACTUALLY RECEIVED (contract §4.1(b)), so "
        "amount_paid is what creates an obligation; amount_remaining is pipeline, not a claim.'"
    )
    op.execute("ALTER TABLE ps_stripe_invoices ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_stripe_invoices FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON ps_stripe_invoices "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )

    # ── Invoice LINES: the per-product truth ────────────────────────────────
    op.execute(
        f"""
        CREATE TABLE ps_stripe_invoice_lines (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,

            stripe_invoice_id TEXT NOT NULL,
            stripe_line_id TEXT NOT NULL,
            wayward_brand_id UUID,
            client_id UUID,

            description TEXT,             -- verbatim, as Stripe wrote it
            amount NUMERIC(14,2),         -- can be NEGATIVE (reconciliation adjustments)
            currency TEXT,
            quantity NUMERIC(14,4),

            -- parsed from the description: "April 2026 - Wayward Connect - Attribution Usage Fee"
            billing_month DATE,           -- the month the fee RELATES to (not when invoiced)
            channel TEXT
                CHECK (channel IS NULL OR channel IN
                       ({", ".join(f"'{c}'" for c in CHANNELS)})),
            fee_type TEXT
                CHECK (fee_type IS NULL OR fee_type IN
                       ({", ".join(f"'{f}'" for f in FEE_TYPES)})),
            product_id TEXT,              -- connect | boosted | NULL

            is_ps_base BOOLEAN NOT NULL DEFAULT false,

            invoice_status TEXT,          -- denormalised so "collected" is a line-level filter
            line_period_start TIMESTAMPTZ,
            line_period_end TIMESTAMPTZ,

            ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, stripe_line_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_lines_brand ON ps_stripe_invoice_lines "
        "(tenant_id, wayward_brand_id, billing_month)"
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_lines_base ON ps_stripe_invoice_lines "
        "(tenant_id, is_ps_base, invoice_status, billing_month)"
    )
    op.execute(
        "COMMENT ON COLUMN ps_stripe_invoice_lines.is_ps_base IS "
        "'TRUE only for USAGE fees (Connect + Boosted + their reconciliation adjustments). "
        "Project Silk''s revenue share is 10%% of USAGE FEES ONLY. "
        "COMMISSION fees are creator PASS-THROUGH — they are NOT Wayward''s revenue and NOT "
        "PS''s base. Treating COMMISSION_FEES as a base is the single most expensive misread "
        "available (11-MONEY-FLOW-EXPLAINER.md exists because an agent made exactly that "
        "mistake). CC processing and SaaS are also excluded. "
        "Computed at ingest so no downstream query has to get it right.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_stripe_invoice_lines.billing_month IS "
        "'The month the fee RELATES to, parsed from the description prefix (''April 2026 - "
        "...''), NOT the month the invoice was created. Jake''s reports are cash-basis by "
        "payment date; this is accrual-basis by service month. They will not line up, and "
        "that is expected — keep both.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_stripe_invoice_lines.amount IS "
        "'May be NEGATIVE. ''Attribution Reconciliation Usage'' lines are adjustments to "
        "earlier months. They ARE usage fees and DO belong in the base — dropping them "
        "would silently misstate what we are owed.'"
    )
    op.execute("ALTER TABLE ps_stripe_invoice_lines ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_stripe_invoice_lines FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON ps_stripe_invoice_lines "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )

    for t in ("ps_stripe_invoices", "ps_stripe_invoice_lines"):
        for r in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {t} TO {r}")

    # ── The lens: billed vs collected, per brand, per month, per product ────
    op.execute(
        """
        CREATE VIEW lens_ps_billed_vs_collected AS
        SELECT
            l.tenant_id,
            l.wayward_brand_id,
            l.client_id,
            l.billing_month,
            l.product_id,
            sum(l.amount)                                                   AS usage_billed,
            sum(l.amount) FILTER (WHERE l.invoice_status = 'paid')          AS usage_collected,
            sum(l.amount) FILTER (WHERE l.invoice_status = 'open')          AS usage_outstanding,
            sum(l.amount) FILTER (WHERE l.invoice_status = 'paid') * 0.10   AS ps_10pct_earned,
            count(DISTINCT l.stripe_invoice_id)                             AS invoices
        FROM ps_stripe_invoice_lines l
        WHERE l.is_ps_base
        GROUP BY 1,2,3,4,5
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_billed_vs_collected IS "
        "'USAGE fees only (is_ps_base), per brand, per billing month, per product. "
        "ps_10pct_earned is 10%% of COLLECTED usage — PS is paid on cash actually received "
        "(§4.1(b)), so outstanding is PIPELINE, not a claim. Does NOT apply the eligibility "
        "filter or the 10/6/3 step-down — join lens_ps_eligibility for that. This view is "
        "deliberately just the money, so it can be trusted on its own.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_billed_vs_collected TO {r}")

    _d = (
        "Stripe usage fees billed vs collected, per brand / month / product. The source of "
        "truth for what Wayward invoiced and actually got paid."
    ).replace("'", "''")
    op.execute(
        f"""
        INSERT INTO cip_views (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            view_name, description, filter_config,
            owner_type, owner_id, is_default, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), '{PS_TENANT}', NULL, 'stripe', 'ps_billed_vs_collected',
            NOW(), NOW(), gen_random_uuid(), 'validated',
            'lens_ps_billed_vs_collected', '{_d}',
            '{{"slug": "ps_billed_vs_collected", "sql_view": "lens_ps_billed_vs_collected", "filter_kind": "ps_billed_vs_collected", "phase": "3.0"}}'::jsonb,
            'system', 'cip', false, NOW(), NOW()
        )
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM cip_views WHERE view_name='lens_ps_billed_vs_collected'")
    op.execute("DROP VIEW IF EXISTS lens_ps_billed_vs_collected")
    op.execute("DROP TABLE IF EXISTS ps_stripe_invoice_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS ps_stripe_invoices CASCADE")
