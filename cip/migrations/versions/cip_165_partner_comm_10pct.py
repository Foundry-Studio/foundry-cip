# foundry: kind=migration domain=client-intelligence-platform
"""cip_165: partner commission ends when the management fee steps down (Tim, 2026-08-10).

partner_fee_owed gated on the partner credit window (credit_start/credit_end) but NOT on the
management-fee tier, so a partner inside their credit window kept earning after we stepped down from
10%. Tim's rule: the partner commission is eligible ONLY while we are at the 10% management fee, and
ENDS when the fee steps down (6% at 12mo, 3% at 18mo). Found 42 rows (42 brands, $80.80 reported)
leaking past the 10% window; ruled a bug. Fix: add `g.mgmt_rate = 0.10` to the partner_fee_owed
condition. CREATE OR REPLACE VIEW keeps the same columns and preserves grants. Money re-statement:
those 42 rows' partner_fee_owed becomes 0, raising net_kept and lowering owed-to-partners by ~$80.80.

Revision ID: cip_165_partner_comm_10pct
Revises: cip_164_requested_marker
"""
from __future__ import annotations

from alembic import op

revision: str = "cip_165_partner_comm_10pct"
down_revision: str | None = "cip_164_requested_marker"
branch_labels = None
depends_on = None

# The current (cip_113) ledger body with the fix: partner_fee_owed also requires mgmt_rate = 0.10.
_LEDGER_FIXED = r"""CREATE OR REPLACE VIEW lens_ps_commission_ledger AS WITH collected AS (
    SELECT wayward_brand_id, product_id, billing_month::date AS period_month,
           COALESCE(sum(amount) FILTER (WHERE invoice_status = 'paid'), 0) AS usage_collected,
           COALESCE(sum(amount) FILTER (WHERE invoice_status IN ('paid','open')), 0) AS usage_billed
    FROM ps_stripe_invoice_lines
    WHERE is_ps_base AND product_id IS NOT NULL AND wayward_brand_id IS NOT NULL AND billing_month IS NOT NULL
    GROUP BY 1, 2, 3
),
excl AS (
    SELECT wayward_brand_id,
           bool_or(disposition = 'flat_fee_era_eric') AS any_flat_fee,
           bool_or(disposition = 'excluded')          AS any_excluded,
           max(ours_revenue_from)                     AS ours_revenue_from
    FROM ps_excluded_brands WHERE wayward_brand_id IS NOT NULL GROUP BY 1
),
graded AS (
    SELECT
        c.wayward_brand_id, c.product_id, c.period_month,
        c.usage_collected - COALESCE(ra.usage_refund_netted, 0) AS usage_collected, c.usage_billed,
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
        (COALESCE(el.ps_rev_share_eligible, false)
         AND c.period_month >= CASE WHEN e.any_flat_fee AND NOT e.any_excluded
                                    THEN e.ours_revenue_from ELSE DATE '2025-10-01' END) AS claimable
    FROM collected c
    LEFT JOIN lens_ps_rate_schedule rs USING (wayward_brand_id, product_id)
    LEFT JOIN lens_ps_china_verdict v ON v.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN excl e ON e.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN ps_partner_credit pc
           ON pc.wayward_brand_id = c.wayward_brand_id AND pc.product_id = c.product_id
    LEFT JOIN lens_ps_product_eligibility el
           ON el.wayward_brand_id = c.wayward_brand_id AND el.product_id = c.product_id
    LEFT JOIN lens_ps_refund_allocation ra
           ON ra.wayward_brand_id = c.wayward_brand_id AND ra.product_id = c.product_id AND ra.period_month = c.period_month
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
              AND g.mgmt_rate = 0.10
         THEN round(g.usage_collected * g.partner_rate_pct / 100.0, 2)
         ELSE 0 END AS partner_fee_owed,
    CASE WHEN g.verdict = 'china'   THEN 'claimable'
         WHEN g.verdict = 'unknown' THEN 'unknown_nationality'
         ELSE 'not_china' END AS claim_status
FROM graded g"""

# The prior (cip_113) body, without the mgmt_rate = 0.10 gate, for downgrade.
_LEDGER_PREV = r"""CREATE OR REPLACE VIEW lens_ps_commission_ledger AS WITH collected AS (
    SELECT wayward_brand_id, product_id, billing_month::date AS period_month,
           COALESCE(sum(amount) FILTER (WHERE invoice_status = 'paid'), 0) AS usage_collected,
           COALESCE(sum(amount) FILTER (WHERE invoice_status IN ('paid','open')), 0) AS usage_billed
    FROM ps_stripe_invoice_lines
    WHERE is_ps_base AND product_id IS NOT NULL AND wayward_brand_id IS NOT NULL AND billing_month IS NOT NULL
    GROUP BY 1, 2, 3
),
excl AS (
    SELECT wayward_brand_id,
           bool_or(disposition = 'flat_fee_era_eric') AS any_flat_fee,
           bool_or(disposition = 'excluded')          AS any_excluded,
           max(ours_revenue_from)                     AS ours_revenue_from
    FROM ps_excluded_brands WHERE wayward_brand_id IS NOT NULL GROUP BY 1
),
graded AS (
    SELECT
        c.wayward_brand_id, c.product_id, c.period_month,
        c.usage_collected - COALESCE(ra.usage_refund_netted, 0) AS usage_collected, c.usage_billed,
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
        (COALESCE(el.ps_rev_share_eligible, false)
         AND c.period_month >= CASE WHEN e.any_flat_fee AND NOT e.any_excluded
                                    THEN e.ours_revenue_from ELSE DATE '2025-10-01' END) AS claimable
    FROM collected c
    LEFT JOIN lens_ps_rate_schedule rs USING (wayward_brand_id, product_id)
    LEFT JOIN lens_ps_china_verdict v ON v.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN excl e ON e.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN ps_partner_credit pc
           ON pc.wayward_brand_id = c.wayward_brand_id AND pc.product_id = c.product_id
    LEFT JOIN lens_ps_product_eligibility el
           ON el.wayward_brand_id = c.wayward_brand_id AND el.product_id = c.product_id
    LEFT JOIN lens_ps_refund_allocation ra
           ON ra.wayward_brand_id = c.wayward_brand_id AND ra.product_id = c.product_id AND ra.period_month = c.period_month
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
FROM graded g"""


def upgrade() -> None:
    op.execute(_LEDGER_FIXED)


def downgrade() -> None:
    op.execute(_LEDGER_PREV)
