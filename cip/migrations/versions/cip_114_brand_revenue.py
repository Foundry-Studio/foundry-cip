# foundry: kind=migration domain=client-intelligence-platform
"""cip_114: brand revenue (GMV / ad-spend) — the data-asset layer.

WHY THIS EXISTS (DATA-EXPANSION-PLAN.md, Sprint 1)
--------------------------------------------------
The money engine only stores FEES (the usage/commission Stripe lines). The raw
revenue those fees are computed FROM — a brand's **GMV** (Connect) / **ad-spend**
(Boost) — was never stored. Storing it turns CIP into a reusable data asset
(reporting stage ① + CRM/data-products on other ventures), not just a commission
engine. This is the first capture in that expansion.

WHAT (additive — the money engine is NOT touched)
-------------------------------------------------
  1. ps_brand_revenue  — the physical home for a RAW GMV/ad-spend feed when one
     lands (source='wayward_feed'|'amazon'). EMPTY today. Source-tagged so raw
     overrides derived per (brand,product,month).
  2. lens_ps_brand_revenue — the read surface. Computes DERIVED revenue LIVE:
       GMV      = billed usage fee ÷ wayward_client_fee_rate   (product 'connect')
       ad_spend = billed usage fee ÷ wayward_client_fee_rate   (product 'boosted')
     …and COALESCEs any raw row from ps_brand_revenue over the derived figure.
     Always fresh (no materialize/refresh), fully queryable/exportable.

DERIVATION NOTES
----------------
  • Numerator = GROSS billed usage (is_ps_base, invoice_status IN ('paid','open'),
    voids excluded) — GMV occurred whether or not the fee was collected. NOT net
    of refunds (that is the money engine's 'collected', a different question).
  • Rate = lens_ps_product_eligibility.wayward_client_fee_rate, a decimal fraction
    (0.0005–0.05). Guarded with NULLIF: no/zero rate → revenue is NULL (surfaced,
    honest — ~1,164 of 2,849 billed pairs lack a rate today, pending the P3
    client-fee-rate feed). GREATEST(…,0) so a recon-heavy month can't go negative.
  • basis='gross_billed', source='derived'. A DB CHECK enforces revenue ≥ 0.

BLAST RADIUS: additive only. No existing lens/table modified → the recovery
number (sum ps_claim_owed china) is penny-identical before/after. Verified on apply.

Revision ID: cip_114_brand_revenue
Revises: cip_113_refund_netting
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_114_brand_revenue"
down_revision: str | Sequence[str] | None = "cip_113_refund_netting"
branch_labels = None
depends_on = None

# Same RLS predicate + read-role set as every sibling ps_* / cip_* table (cip_49,
# cip_111). NULLIF guards the "no tenant set" case → unscoped connection sees zero.
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def _secure(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON {table} USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON {table} TO {r}")


_LENS = """
CREATE VIEW lens_ps_brand_revenue AS
WITH billed AS (
    SELECT wayward_brand_id, product_id, billing_month::date AS period_month,
           sum(amount) AS usage_fee_billed
      FROM ps_stripe_invoice_lines
     WHERE is_ps_base
       AND invoice_status IN ('paid', 'open')
       AND wayward_brand_id IS NOT NULL AND product_id IS NOT NULL AND billing_month IS NOT NULL
     GROUP BY 1, 2, 3
),
derived AS (
    SELECT b.wayward_brand_id, b.product_id, b.period_month,
           CASE WHEN b.product_id = 'boosted' THEN 'ad_spend' ELSE 'gmv' END AS revenue_type,
           b.usage_fee_billed,
           e.wayward_client_fee_rate AS rate_used,
           CASE WHEN COALESCE(e.wayward_client_fee_rate, 0) = 0 THEN NULL
                ELSE GREATEST(round(b.usage_fee_billed / e.wayward_client_fee_rate, 2), 0)
           END AS revenue_amount
      FROM billed b
      LEFT JOIN lens_ps_product_eligibility e
             ON e.wayward_brand_id = b.wayward_brand_id AND e.product_id = b.product_id
)
SELECT d.wayward_brand_id,
       pb.brand_name,
       d.product_id,
       d.period_month,
       d.revenue_type,
       COALESCE(r.revenue_amount, d.revenue_amount) AS revenue_amount,
       d.usage_fee_billed,
       COALESCE(r.rate_used, d.rate_used) AS rate_used,
       COALESCE(r.source, 'derived') AS source,
       COALESCE(r.basis, 'gross_billed') AS basis,
       (d.revenue_amount IS NULL) AS rate_missing
  FROM derived d
  JOIN ps_brands pb ON pb.wayward_brand_id = d.wayward_brand_id
  LEFT JOIN ps_brand_revenue r
         ON r.wayward_brand_id = d.wayward_brand_id
        AND r.product_id = d.product_id
        AND r.period_month = d.period_month
"""


def upgrade() -> None:
    # ── raw-feed home (empty today; source-tagged; overrides derived) ────────
    op.execute(
        """
        CREATE TABLE ps_brand_revenue (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL,
            wayward_brand_id UUID NOT NULL,
            product_id       TEXT NOT NULL,            -- 'connect' | 'boosted'
            period_month     DATE NOT NULL,
            revenue_type     TEXT NOT NULL,            -- 'gmv' | 'ad_spend'
            revenue_amount   NUMERIC(16,2) CHECK (revenue_amount >= 0),
            usage_fee_billed NUMERIC(14,2),            -- the numerator (audit)
            rate_used        NUMERIC(8,4),             -- the denominator (audit)
            basis            TEXT NOT NULL DEFAULT 'gross_billed',
            source           TEXT NOT NULL DEFAULT 'derived'
                             CHECK (source IN ('derived', 'wayward_feed', 'amazon')),
            computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, wayward_brand_id, product_id, period_month, source)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_brand_revenue_brand ON ps_brand_revenue "
        "(tenant_id, wayward_brand_id, period_month)"
    )
    op.execute(
        "COMMENT ON TABLE ps_brand_revenue IS $c$"
        "Physical home for a RAW brand GMV/ad-spend feed (source='wayward_feed'|'amazon') "
        "when one lands. EMPTY until then. Source-tagged; a raw row OVERRIDES the derived "
        "figure for its (brand,product,month) via lens_ps_brand_revenue. The DERIVED revenue "
        "is NOT materialised here — it is computed live in the lens (always fresh). Additive: "
        "the money engine does not read this table.$c$"
    )
    _secure("ps_brand_revenue")

    # ── the read surface: derived-live, raw-overrides ───────────────────────
    op.execute(_LENS)
    op.execute(
        "COMMENT ON VIEW lens_ps_brand_revenue IS $c$"
        "Brand revenue per brand×product×month: GMV (product 'connect') / ad-spend "
        "('boosted') = gross billed usage fee ÷ wayward_client_fee_rate, computed LIVE; a raw "
        "row in ps_brand_revenue overrides it. revenue_amount is NULL + rate_missing=true when "
        "no client fee rate exists (pending the P3 fee-rate feed). basis='gross_billed' (NOT "
        "net of refunds — that is the money engine's 'collected'). source in derived|wayward_"
        "feed|amazon. Data-asset read surface; does not feed the commission math.$c$"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_brand_revenue TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_revenue")
    op.execute("DROP TABLE IF EXISTS ps_brand_revenue CASCADE")
