# foundry: kind=migration domain=client-intelligence-platform
"""cip_168: add the nested earned measure (mgmt_fee_earned + partner_fee_earned).

The "earned" half of the two-layer claim model. lens_ps_commission_ledger already
carries usage_billed (paid+open, over is_ps_base lines) and usage_collected (paid,
refund-netted). The existing mgmt_fee_owed = rate x usage_COLLECTED is the
collectible/cash layer -- what is actually due now. This adds:

  mgmt_fee_earned    = claimable ? round(rate x usage_BILLED, 2) : 0
  partner_fee_earned = the partner analog on usage_BILLED (same 10%-window gate)

the pipeline/accrual layer -- what we have earned as usage is invoiced, before the
client pays. Purely ADDITIVE: no existing figure changes. mgmt_fee_owed,
partner_fee_owed, and every prior column are byte-for-byte untouched; the two new
columns are APPENDED at the end so CREATE OR REPLACE VIEW preserves column order
AND all existing grants (six reader roles).

GUARDRAILS (locked, QC'd by adversarial review 2026-08-21):
  * earned CONTAINS owed (usage_billed is a superset of usage_collected) -> the two
    layers are NESTED, never summed anywhere.
  * earned is a CUMULATIVE-PIPELINE figure, not monthly recognized revenue
    (usage_billed includes 'open' invoices that can later void).
  * partner_fee_earned mirrors partner_fee_owed exactly (same credit-window +
    mgmt_rate = 0.10 gate) so the two layers stay internally consistent.

Downgrade is a deliberate documented no-op: the two columns are additive and
harmless, and removing them would require DROP + recreate of three dependent views
(ledger -> claim -> invariants) plus re-granting six reader roles -- strictly
riskier than leaving two unused columns in place. To revert, fix-forward with a
CREATE OR REPLACE restoring the prior definitions (captured in the migration PR).

Revision ID: cip_168_earned_measure
Revises: cip_167_claim_floor_fix
"""
from __future__ import annotations

from alembic import op

revision: str = "cip_168_earned_measure"
down_revision: str | None = "cip_167_claim_floor_fix"
branch_labels = None
depends_on = None


# lens_ps_commission_ledger with mgmt_fee_earned + partner_fee_earned appended.
# Body is the exact prior definition (pg_get_viewdef) with two trailing columns added.
_LEDGER = """CREATE OR REPLACE VIEW lens_ps_commission_ledger AS
 WITH collected AS (
         SELECT ps_stripe_invoice_lines.wayward_brand_id,
            ps_stripe_invoice_lines.product_id,
            ps_stripe_invoice_lines.billing_month AS period_month,
            COALESCE(sum(ps_stripe_invoice_lines.amount) FILTER (WHERE ps_stripe_invoice_lines.invoice_status = 'paid'::text), 0::numeric) AS usage_collected,
            COALESCE(sum(ps_stripe_invoice_lines.amount) FILTER (WHERE ps_stripe_invoice_lines.invoice_status = ANY (ARRAY['paid'::text, 'open'::text])), 0::numeric) AS usage_billed
           FROM ps_stripe_invoice_lines
          WHERE ps_stripe_invoice_lines.is_ps_base AND ps_stripe_invoice_lines.product_id IS NOT NULL AND ps_stripe_invoice_lines.wayward_brand_id IS NOT NULL AND ps_stripe_invoice_lines.billing_month IS NOT NULL
          GROUP BY ps_stripe_invoice_lines.wayward_brand_id, ps_stripe_invoice_lines.product_id, ps_stripe_invoice_lines.billing_month
        ), excl AS (
         SELECT ps_excluded_brands.wayward_brand_id,
            bool_or(ps_excluded_brands.disposition = 'flat_fee_era_eric'::text) AS any_flat_fee,
            bool_or(ps_excluded_brands.disposition = 'excluded'::text) AS any_excluded,
            max(ps_excluded_brands.ours_revenue_from) AS ours_revenue_from
           FROM ps_excluded_brands
          WHERE ps_excluded_brands.wayward_brand_id IS NOT NULL
          GROUP BY ps_excluded_brands.wayward_brand_id
        ), graded AS (
         SELECT c.wayward_brand_id,
            c.product_id,
            c.period_month,
            c.usage_collected - COALESCE(ra.usage_refund_netted, 0::numeric) AS usage_collected,
            c.usage_billed,
            v.verdict,
                CASE
                    WHEN e.wayward_brand_id IS NULL THEN 'never_listed'::text
                    WHEN e.any_flat_fee AND NOT e.any_excluded THEN 'flat_fee_era_eric'::text
                    ELSE 'excluded'::text
                END AS ownership,
                CASE
                    WHEN e.wayward_brand_id IS NULL THEN '2025-10-01'::date
                    WHEN e.any_flat_fee AND NOT e.any_excluded THEN e.ours_revenue_from
                    ELSE NULL::date
                END AS ours_revenue_from,
                CASE
                    WHEN rs.effective_anchor IS NULL THEN 0.10
                    WHEN c.period_month < rs.rate_10_until THEN 0.10
                    WHEN c.period_month < rs.rate_6_until THEN 0.06
                    ELSE 0.03
                END AS mgmt_rate,
            pc.partner_of_record,
            COALESCE(pc.partner_rate, 0::numeric) AS partner_rate_pct,
            pc.credit_start,
            pc.credit_end,
            COALESCE(el.ps_rev_share_eligible, false) AND c.period_month >=
                CASE
                    WHEN e.any_flat_fee AND NOT e.any_excluded THEN e.ours_revenue_from
                    ELSE '2025-10-01'::date
                END AS claimable
           FROM collected c
             LEFT JOIN lens_ps_rate_schedule rs USING (wayward_brand_id, product_id)
             LEFT JOIN lens_ps_china_verdict v ON v.wayward_brand_id = c.wayward_brand_id
             LEFT JOIN excl e ON e.wayward_brand_id = c.wayward_brand_id
             LEFT JOIN ps_partner_credit pc ON pc.wayward_brand_id = c.wayward_brand_id AND pc.product_id = c.product_id
             LEFT JOIN lens_ps_product_eligibility el ON el.wayward_brand_id = c.wayward_brand_id AND el.product_id = c.product_id
             LEFT JOIN lens_ps_refund_allocation ra ON ra.wayward_brand_id = c.wayward_brand_id AND ra.product_id = c.product_id AND ra.period_month = c.period_month
        )
 SELECT wayward_brand_id,
    product_id,
    period_month,
    usage_billed,
    usage_collected,
    verdict,
    ownership,
    ours_revenue_from,
    mgmt_rate,
    claimable,
        CASE
            WHEN claimable THEN round(usage_collected * mgmt_rate, 2)
            ELSE 0::numeric
        END AS mgmt_fee_owed,
    partner_of_record,
    partner_rate_pct,
        CASE
            WHEN claimable AND period_month >= COALESCE(credit_start, period_month) AND period_month <= COALESCE(credit_end, period_month) AND mgmt_rate = 0.10 THEN round(usage_collected * partner_rate_pct / 100.0, 2)
            ELSE 0::numeric
        END AS partner_fee_owed,
        CASE
            WHEN verdict = 'china'::text THEN 'claimable'::text
            WHEN verdict = 'unknown'::text THEN 'unknown_nationality'::text
            ELSE 'not_china'::text
        END AS claim_status,
        CASE
            WHEN claimable THEN round(usage_billed * mgmt_rate, 2)
            ELSE 0::numeric
        END AS mgmt_fee_earned,
        CASE
            WHEN claimable AND period_month >= COALESCE(credit_start, period_month) AND period_month <= COALESCE(credit_end, period_month) AND mgmt_rate = 0.10 THEN round(usage_billed * partner_rate_pct / 100.0, 2)
            ELSE 0::numeric
        END AS partner_fee_earned
   FROM graded g"""


# lens_ps_claim with mgmt_fee_earned + partner_fee_earned rolled up and appended.
_CLAIM = """CREATE OR REPLACE VIEW lens_ps_claim AS
 WITH owed AS (
         SELECT lens_ps_commission_ledger.wayward_brand_id,
            max(lens_ps_commission_ledger.verdict) AS verdict,
            max(lens_ps_commission_ledger.ownership) AS ownership,
            sum(lens_ps_commission_ledger.mgmt_fee_owed) AS mgmt_fee_owed,
            sum(lens_ps_commission_ledger.partner_fee_owed) AS partner_fee_owed,
            max(lens_ps_commission_ledger.partner_of_record) AS partner_of_record,
            bool_or(lens_ps_commission_ledger.claim_status = 'unknown_nationality'::text) AS any_unknown,
            sum(lens_ps_commission_ledger.mgmt_fee_earned) AS mgmt_fee_earned,
            sum(lens_ps_commission_ledger.partner_fee_earned) AS partner_fee_earned
           FROM lens_ps_commission_ledger
          GROUP BY lens_ps_commission_ledger.wayward_brand_id
        ), paid AS (
         SELECT ps_payment_events.wayward_brand_id,
            sum(ps_payment_events.rev_share_stated) AS wayward_paid
           FROM ps_payment_events
          WHERE ps_payment_events.wayward_brand_id IS NOT NULL
          GROUP BY ps_payment_events.wayward_brand_id
        ), ppaid AS (
         SELECT ps_partner_payouts.wayward_brand_id,
            sum(ps_partner_payouts.amount_paid) AS partner_paid
           FROM ps_partner_payouts
          WHERE ps_partner_payouts.wayward_brand_id IS NOT NULL
          GROUP BY ps_partner_payouts.wayward_brand_id
        )
 SELECT o.wayward_brand_id,
    b.brand_name,
    o.verdict,
    o.ownership,
    round(o.mgmt_fee_owed, 2) AS mgmt_fee_owed,
    round(COALESCE(p.wayward_paid, 0::numeric), 2) AS wayward_paid,
    round(GREATEST(o.mgmt_fee_owed - GREATEST(COALESCE(p.wayward_paid, 0::numeric), 0::numeric), 0::numeric), 2) AS ps_claim_owed,
    o.partner_of_record,
    round(o.partner_fee_owed, 2) AS partner_fee_owed,
    round(COALESCE(pp.partner_paid, 0::numeric), 2) AS partner_paid,
    round(GREATEST(o.partner_fee_owed - GREATEST(COALESCE(pp.partner_paid, 0::numeric), 0::numeric), 0::numeric), 2) AS partner_claim_owed,
    round(o.mgmt_fee_earned, 2) AS mgmt_fee_earned,
    round(o.partner_fee_earned, 2) AS partner_fee_earned
   FROM owed o
     JOIN ps_brands b ON b.wayward_brand_id = o.wayward_brand_id
     LEFT JOIN paid p ON p.wayward_brand_id = o.wayward_brand_id
     LEFT JOIN ppaid pp ON pp.wayward_brand_id = o.wayward_brand_id"""


def upgrade() -> None:
    # Order matters: recreate the ledger first (adds the two source columns),
    # then the claim rollup that consumes them. Both are append-only
    # CREATE OR REPLACE, so column order and all existing grants are preserved.
    op.execute(_LEDGER)
    op.execute(_CLAIM)


def downgrade() -> None:
    # Deliberate no-op. The added columns are additive and harmless; reverting
    # would require DROP + recreate of lens_ps_commission_ledger, lens_ps_claim,
    # and lens_ps_invariants plus re-granting six reader roles -- riskier than
    # leaving two unused columns. Fix-forward with the captured prior defs if a
    # true revert is ever required.
    pass
