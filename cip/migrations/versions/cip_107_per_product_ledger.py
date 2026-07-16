# foundry: kind=migration domain=client-intelligence-platform
"""cip_107: rewire the commission ledger to PER-PRODUCT eligibility (Tim, 2026-07-16).

cip_104's `claimable` gate used BRAND-level ownership: a rev-share-excluded brand was blocked on ALL
products. Per Tim's model (cip_105), eligibility is per product — rev-share exclusion is Connect-only,
so those brands' BOOST is ours. This repoints `claimable` at `lens_ps_product_eligibility.
ps_rev_share_eligible` (per brand x product, which also honors the ps_product_eligibility overrides),
with a per-product revenue-start (flat-fee 2025-12-01; everything else — incl. newly-eligible rev-share
Boost — the 2025-10-01 anchor).

Effect: surfaces the Boost management fee on rev-share brands that was previously invisible
(~$936 on 108 brands with existing Boost revenue, + all future Boost). CREATE OR REPLACE — same
columns, only the claimable/derived-fee logic changes; lens_ps_claim + the invariants are unaffected
structurally. Money-model change (Tim authorized): the recovery number GROWS.

Revision ID: cip_107_per_product_ledger
Revises: cip_106_wayward_fee_rate
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_107_per_product_ledger"
down_revision: str | Sequence[str] | None = "cip_106_wayward_fee_rate"
branch_labels = None
depends_on = None

# only the graded CTE's join set + claimable expression change vs cip_104; columns are identical.
_LEDGER_TMPL = """
CREATE OR REPLACE VIEW lens_ps_commission_ledger AS
WITH collected AS (
    SELECT wayward_brand_id, product_id, billing_month::date AS period_month,
           COALESCE(sum(amount) FILTER (WHERE invoice_status = 'paid'), 0) AS usage_collected,
           COALESCE(sum(amount) FILTER (WHERE invoice_status IN ('paid','open')), 0) AS usage_billed
    FROM ps_stripe_invoice_lines
    WHERE is_ps_base
      AND product_id IS NOT NULL
      AND wayward_brand_id IS NOT NULL
      AND billing_month IS NOT NULL
    GROUP BY 1, 2, 3
),
excl AS (
    SELECT wayward_brand_id,
           bool_or(disposition = 'flat_fee_era_eric') AS any_flat_fee,
           bool_or(disposition = 'excluded')          AS any_excluded,
           max(ours_revenue_from)                     AS ours_revenue_from
    FROM ps_excluded_brands
    WHERE wayward_brand_id IS NOT NULL
    GROUP BY 1
),
graded AS (
    SELECT
        c.wayward_brand_id, c.product_id, c.period_month,
        c.usage_collected, c.usage_billed,
        v.verdict,
        CASE WHEN e.wayward_brand_id IS NULL THEN 'never_listed'
             WHEN e.any_flat_fee AND NOT e.any_excluded THEN 'flat_fee_era_eric'
             ELSE 'excluded' END AS ownership,
        CASE WHEN e.wayward_brand_id IS NULL THEN DATE '2025-10-01'
             WHEN e.any_flat_fee AND NOT e.any_excluded THEN e.ours_revenue_from
             ELSE NULL END AS ours_revenue_from,
        CASE WHEN rs.effective_anchor IS NULL THEN 0.10
             WHEN c.period_month < rs.rate_10_until THEN 0.10
             WHEN c.period_month < rs.rate_6_until  THEN 0.06
             ELSE 0.03 END AS mgmt_rate,
        pc.partner_of_record,
        COALESCE(pc.partner_rate, 0) AS partner_rate_pct,
        pc.credit_start, pc.credit_end,
        {CLAIMABLE} AS claimable
    FROM collected c
    LEFT JOIN lens_ps_rate_schedule rs USING (wayward_brand_id, product_id)
    LEFT JOIN lens_ps_china_verdict v ON v.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN excl e ON e.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN ps_partner_credit pc
           ON pc.wayward_brand_id = c.wayward_brand_id AND pc.product_id = c.product_id
    {ELIG_JOIN}
)
SELECT
    g.wayward_brand_id, g.product_id, g.period_month,
    g.usage_billed, g.usage_collected,
    g.verdict, g.ownership, g.ours_revenue_from, g.mgmt_rate, g.claimable,
    CASE WHEN g.claimable THEN round(g.usage_collected * g.mgmt_rate, 2) ELSE 0 END AS mgmt_fee_owed,
    g.partner_of_record, g.partner_rate_pct,
    CASE WHEN g.claimable
              AND g.period_month >= COALESCE(g.credit_start, g.period_month)
              AND g.period_month <= COALESCE(g.credit_end, g.period_month)
         THEN round(g.usage_collected * g.partner_rate_pct / 100.0, 2)
         ELSE 0 END AS partner_fee_owed,
    CASE WHEN g.verdict = 'china'   THEN 'claimable'
         WHEN g.verdict = 'unknown' THEN 'unknown_nationality'
         ELSE 'not_china' END AS claim_status
FROM graded g
"""

# NEW (cip_107): per-product eligibility from lens_ps_product_eligibility (china-gated + overrides),
# with the flat-fee 2025-12-01 / else 2025-10-01 revenue-start (rev-share Boost anchors at 2025-10-01).
_CLAIMABLE_NEW = """(COALESCE(el.ps_rev_share_eligible, false)
         AND c.period_month >= CASE WHEN e.any_flat_fee AND NOT e.any_excluded
                                    THEN e.ours_revenue_from ELSE DATE '2025-10-01' END)"""
_ELIG_JOIN_NEW = """LEFT JOIN lens_ps_product_eligibility el
           ON el.wayward_brand_id = c.wayward_brand_id AND el.product_id = c.product_id"""

# OLD (cip_104): brand-level ownership, excluded blocked on all products.
_CLAIMABLE_OLD = """(v.verdict = 'china'
         AND (e.wayward_brand_id IS NULL OR (e.any_flat_fee AND NOT e.any_excluded))
         AND c.period_month >= CASE WHEN e.wayward_brand_id IS NULL THEN DATE '2025-10-01'
                                    WHEN e.any_flat_fee AND NOT e.any_excluded THEN e.ours_revenue_from
                                    ELSE NULL END)"""


def upgrade() -> None:
    op.execute(_LEDGER_TMPL.format(CLAIMABLE=_CLAIMABLE_NEW, ELIG_JOIN=_ELIG_JOIN_NEW))


def downgrade() -> None:
    op.execute(_LEDGER_TMPL.format(CLAIMABLE=_CLAIMABLE_OLD, ELIG_JOIN=""))
