# foundry: kind=migration domain=client-intelligence-platform
"""cip_113: usage_collected becomes NET of succeeded refunds (Tim, 2026-07-18).

The contract (SS3.1) pays revenue share on "Usage Fees actually received by Company." A usage fee
collected then refunded was not, in the end, received. cip_111 landed the refund objects; cip_113
nets them into the commission base as a first-class variable.

THE RULE (validated on prod): a refund is allocated to the is_ps_base SHARE of its invoice pro-rata
(a $1,475 refund on a $1,675 invoice whose usage is $368 nets ~the usage share, not $1,475), minus
any amount already booked as a negative reconciliation line (no double-subtract), capped so a cell
never goes below 0. Succeeded refunds only. Credit notes stay evidence-only. Reason-agnostic
(correct for duplicates AND genuine returns). Impact (verified on prod): collected -$3,498.03 total
(-$620.41 china), gross mgmt_fee_owed -$33.72; recovery $13,716.66 -> $13,712.58 (-$4.08 - smaller
than the fee drop because ps_claim_owed is floored per brand net of what Wayward already paid, and
the refunded brands are mostly already paid).

WHAT CHANGES:
  - lens_ps_refund_allocation (NEW): the netting, per brand x product x month + the transparency surface.
  - lens_ps_commission_ledger: usage_collected NET (same signature -> no cascade). Everything reading
    the ledger/claim (ar_aging, monthly, partner_payout, reconciliation, statement_drift, ...) nets free.
  - lens_ps_china_verdict / lens_ps_china_companies: their independent usage_collected money columns
    netted too (else they'd show the old number).
  - lens_ps_monthly_summary: + usage_refunded (gross -> net transparency in reporting).
  - RETIRE lens_ps_billed_vs_collected + lens_ps_partner_performance: dead pre-cip_104 diagnostics
    (0 downstream, superseded) that were stale independent copies of the collected formula.

Revision ID: cip_113_refund_netting
Revises: cip_112_statement_drift
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_113_refund_netting"
down_revision: str | Sequence[str] | None = "cip_112_statement_drift"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_REFUND_LENS = r"""CREATE VIEW lens_ps_refund_allocation AS
WITH succ AS (
    SELECT invoice_id, sum(amount) AS refund_total
    FROM ps_stripe_refunds
    WHERE status = 'succeeded' AND invoice_id IS NOT NULL
    GROUP BY 1
),
inv AS (
    SELECT stripe_invoice_id,
           sum(amount) FILTER (WHERE invoice_status = 'paid') AS inv_paid_total,
           -COALESCE(sum(amount) FILTER (WHERE invoice_status='paid' AND is_ps_base AND amount<0),0) AS neg_base
    FROM ps_stripe_invoice_lines GROUP BY 1
),
unc AS (
    SELECT s.invoice_id, i.inv_paid_total,
           GREATEST(s.refund_total - i.neg_base, 0) AS uncovered
    FROM succ s JOIN inv i ON i.stripe_invoice_id = s.invoice_id
),
alloc AS (
    SELECT l.wayward_brand_id, l.product_id, l.billing_month::date AS period_month,
           sum(LEAST(u.uncovered, u.inv_paid_total) * (l.amount / NULLIF(u.inv_paid_total,0))) AS raw
    FROM ps_stripe_invoice_lines l
    JOIN unc u ON u.invoice_id = l.stripe_invoice_id
    WHERE l.is_ps_base AND l.amount > 0 AND l.invoice_status = 'paid'
      AND l.product_id IS NOT NULL AND l.wayward_brand_id IS NOT NULL AND l.billing_month IS NOT NULL
    GROUP BY 1,2,3
),
gross AS (
    SELECT wayward_brand_id, product_id, billing_month::date AS period_month,
           sum(amount) FILTER (WHERE invoice_status='paid') AS gross_collected
    FROM ps_stripe_invoice_lines
    WHERE is_ps_base AND product_id IS NOT NULL AND wayward_brand_id IS NOT NULL AND billing_month IS NOT NULL
    GROUP BY 1,2,3
)
SELECT a.wayward_brand_id, a.product_id, a.period_month,
       round(a.raw,2) AS usage_refund_raw,
       round(LEAST(a.raw, GREATEST(g.gross_collected,0)),2) AS usage_refund_netted
FROM alloc a JOIN gross g USING (wayward_brand_id, product_id, period_month)
WHERE a.raw > 0.005"""
_REFUND_COMMENT = r"""Refund netted OUT of usage_collected, per brand x product x month. Succeeded refunds only, allocated to the is_ps_base SHARE of the invoice pro-rata (never the raw amount - refunds hit the whole invoice incl. non-base pass-through), minus Wayward's already-booked negative reconciliation lines (uncovered remainder), capped so collected never goes below 0 from a refund. Credit notes are evidence-only (ps_stripe_credit_notes), not netted. See REFUND-NETTING-PLAN.md."""
_LEDGER_NET = r"""CREATE OR REPLACE VIEW lens_ps_commission_ledger AS WITH collected AS (
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
_LEDGER_GROSS = r"""CREATE OR REPLACE VIEW lens_ps_commission_ledger AS WITH collected AS (
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
        c.usage_collected AS usage_collected, c.usage_billed,
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
_LEDGER_COMMENT = r"""Per brand x product x month commission ledger. usage_collected is NET of succeeded refunds (cip_113: gross paid is_ps_base minus lens_ps_refund_allocation.usage_refund_netted) - the contract's 'Usage Fees actually received'. usage_billed stays gross. mgmt_fee = net collected x the 10/6/3 ladder when claimable."""
_CV_NET = r""" WITH agg AS (
         SELECT s.wayward_brand_id,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,
            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS confirming,
            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,
            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,
            max(
                CASE s.strength
                    WHEN 'definitional'::text THEN 6
                    WHEN 'confirmed'::text THEN 5
                    WHEN 'strong'::text THEN 4
                    WHEN 'moderate'::text THEN 3
                    WHEN 'weak'::text THEN 2
                    ELSE 1
                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS best_china_rank,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,
            max(s.evidence) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_rationale,
            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_by
           FROM ps_nationality_signals s
          GROUP BY s.wayward_brand_id
        ), money AS (
         SELECT ps_stripe_invoice_lines.wayward_brand_id,
            sum(ps_stripe_invoice_lines.amount) FILTER (WHERE ps_stripe_invoice_lines.invoice_status = 'paid'::text) AS collected
           FROM ps_stripe_invoice_lines
          WHERE ps_stripe_invoice_lines.is_ps_base AND ps_stripe_invoice_lines.product_id IS NOT NULL AND ps_stripe_invoice_lines.wayward_brand_id IS NOT NULL AND ps_stripe_invoice_lines.billing_month IS NOT NULL
          GROUP BY ps_stripe_invoice_lines.wayward_brand_id
        )
 SELECT b.wayward_brand_id,
    b.brand_name,
    b.signup_date,
        CASE
            WHEN a.human_not_china THEN 'not_china'::text
            WHEN a.human_china THEN 'china'::text
            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN 'china'::text
            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text
            ELSE 'unknown'::text
        END AS verdict,
        CASE
            WHEN a.human_not_china OR a.human_china THEN 'human'::text
            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN
            CASE a.best_china_rank
                WHEN 6 THEN 'definitional'::text
                WHEN 5 THEN 'confirmed'::text
                WHEN 4 THEN 'strong'::text
                ELSE 'confirmed'::text
            END
            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text
            ELSE NULL::text
        END AS verdict_strength,
    a.china_evidence,
    a.not_china_evidence,
    COALESCE(a.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,
    a.manual_rationale,
    a.manual_by,
    COALESCE(a.confirming, 0::bigint) > 0 AND COALESCE(a.legal_not_china, 0::bigint) > 0 AS has_conflict,
    COALESCE(st.is_excluded, false) AS is_excluded,
    st.buckets AS excluded_buckets,
    m.wayward_brand_id IS NOT NULL AS ever_billed,
    round(COALESCE(m.collected, 0::numeric) - COALESCE(rf.brand_refund, 0::numeric), 2) AS usage_collected,
    NULL::numeric AS ps_owed_claimable,
    NULL::numeric AS ps_paid,
    NULL::numeric AS shortfall,
    NULL::numeric AS hypothetical_if_all_claimable
   FROM ps_brands b
     LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN agg a ON a.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN (SELECT wayward_brand_id, sum(usage_refund_netted) AS brand_refund FROM lens_ps_refund_allocation GROUP BY wayward_brand_id) rf ON rf.wayward_brand_id = b.wayward_brand_id"""
_CV_GROSS = r""" WITH agg AS (
         SELECT s.wayward_brand_id,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,
            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS confirming,
            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,
            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,
            max(
                CASE s.strength
                    WHEN 'definitional'::text THEN 6
                    WHEN 'confirmed'::text THEN 5
                    WHEN 'strong'::text THEN 4
                    WHEN 'moderate'::text THEN 3
                    WHEN 'weak'::text THEN 2
                    ELSE 1
                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS best_china_rank,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,
            max(s.evidence) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_rationale,
            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_by
           FROM ps_nationality_signals s
          GROUP BY s.wayward_brand_id
        ), money AS (
         SELECT ps_stripe_invoice_lines.wayward_brand_id,
            sum(ps_stripe_invoice_lines.amount) FILTER (WHERE ps_stripe_invoice_lines.invoice_status = 'paid'::text) AS collected
           FROM ps_stripe_invoice_lines
          WHERE ps_stripe_invoice_lines.is_ps_base AND ps_stripe_invoice_lines.product_id IS NOT NULL AND ps_stripe_invoice_lines.wayward_brand_id IS NOT NULL AND ps_stripe_invoice_lines.billing_month IS NOT NULL
          GROUP BY ps_stripe_invoice_lines.wayward_brand_id
        )
 SELECT b.wayward_brand_id,
    b.brand_name,
    b.signup_date,
        CASE
            WHEN a.human_not_china THEN 'not_china'::text
            WHEN a.human_china THEN 'china'::text
            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN 'china'::text
            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text
            ELSE 'unknown'::text
        END AS verdict,
        CASE
            WHEN a.human_not_china OR a.human_china THEN 'human'::text
            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN
            CASE a.best_china_rank
                WHEN 6 THEN 'definitional'::text
                WHEN 5 THEN 'confirmed'::text
                WHEN 4 THEN 'strong'::text
                ELSE 'confirmed'::text
            END
            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text
            ELSE NULL::text
        END AS verdict_strength,
    a.china_evidence,
    a.not_china_evidence,
    COALESCE(a.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,
    a.manual_rationale,
    a.manual_by,
    COALESCE(a.confirming, 0::bigint) > 0 AND COALESCE(a.legal_not_china, 0::bigint) > 0 AS has_conflict,
    COALESCE(st.is_excluded, false) AS is_excluded,
    st.buckets AS excluded_buckets,
    m.wayward_brand_id IS NOT NULL AS ever_billed,
    round(COALESCE(m.collected, 0::numeric), 2) AS usage_collected,
    NULL::numeric AS ps_owed_claimable,
    NULL::numeric AS ps_paid,
    NULL::numeric AS shortfall,
    NULL::numeric AS hypothetical_if_all_claimable
   FROM ps_brands b
     LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN agg a ON a.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id"""
_CC_NET = r""" WITH member AS (
         SELECT b.wayward_brand_id,
            COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS company_id,
            b.brand_name,
            b.canonical_brand_id IS NOT NULL AND b.canonical_brand_id <> b.wayward_brand_id AS is_alias_row
           FROM ps_brands b
        ), sig AS (
         SELECT m.company_id,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,
            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS confirming,
            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,
            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,
            max(
                CASE s.strength
                    WHEN 'definitional'::text THEN 6
                    WHEN 'confirmed'::text THEN 5
                    WHEN 'strong'::text THEN 4
                    WHEN 'moderate'::text THEN 3
                    WHEN 'weak'::text THEN 2
                    ELSE 1
                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS best_china_rank,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,
            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS decided_by
           FROM member m
             LEFT JOIN ps_nationality_signals s ON s.wayward_brand_id = m.wayward_brand_id
          GROUP BY m.company_id
        ), shape AS (
         SELECT m.company_id,
            count(*) AS sibling_rows,
            min(m.brand_name) FILTER (WHERE NOT m.is_alias_row) AS head_name,
            min(m.brand_name) AS any_name,
            bool_or(r.reality = 'REAL'::text) AS is_real,
            bool_or(r.reality = 'JUNK'::text) AS any_row_junk,
            bool_or(r.ever_billed) AS ever_billed,
            bool_or(r.wayward_onboarded_them) AS onboarded,
            bool_or(r.on_a_frozen_list) AS on_a_frozen_list,
            bool_or(r.on_eric_sheet) AS on_eric_sheet
           FROM member m
             JOIN lens_ps_brand_reality r ON r.wayward_brand_id = m.wayward_brand_id
          GROUP BY m.company_id
        ), money AS (
         SELECT m.company_id,
            round(sum(l.amount) FILTER (WHERE l.invoice_status = 'paid'::text), 2) AS usage_collected
           FROM member m
             JOIN ps_stripe_invoice_lines l ON l.wayward_brand_id = m.wayward_brand_id
          WHERE l.is_ps_base AND l.product_id IS NOT NULL AND l.billing_month IS NOT NULL
          GROUP BY m.company_id
        )
 SELECT sh.company_id,
    COALESCE(sh.head_name, sh.any_name) AS company_name,
        CASE
            WHEN sg.human_not_china THEN 'not_china'::text
            WHEN sg.human_china THEN 'china'::text
            WHEN COALESCE(sg.confirming, 0::bigint) > 0 THEN 'china'::text
            WHEN COALESCE(sg.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text
            ELSE 'unknown'::text
        END AS verdict,
        CASE
            WHEN sg.human_not_china OR sg.human_china THEN 'human'::text
            WHEN COALESCE(sg.confirming, 0::bigint) > 0 THEN
            CASE sg.best_china_rank
                WHEN 6 THEN 'definitional'::text
                WHEN 5 THEN 'confirmed'::text
                WHEN 4 THEN 'strong'::text
                ELSE 'confirmed'::text
            END
            WHEN COALESCE(sg.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text
            ELSE NULL::text
        END AS verdict_strength,
    sg.china_evidence,
    sg.not_china_evidence,
    COALESCE(sg.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,
    sg.decided_by,
    sh.sibling_rows,
    sh.sibling_rows > 1 AS is_split_identity,
        CASE
            WHEN sh.is_real THEN 'REAL'::text
            WHEN sh.any_row_junk THEN 'JUNK'::text
            ELSE 'GHOST'::text
        END AS reality,
    sh.ever_billed,
    sh.onboarded,
    sh.on_a_frozen_list,
    sh.on_eric_sheet,
    round(COALESCE(mo.usage_collected, 0::numeric) - COALESCE(cr.company_refund, 0::numeric), 2) AS usage_collected
   FROM shape sh
     JOIN sig sg ON sg.company_id = sh.company_id
     LEFT JOIN money mo ON mo.company_id = sh.company_id
     LEFT JOIN (SELECT m2.company_id, sum(ra.usage_refund_netted) AS company_refund FROM member m2 JOIN lens_ps_refund_allocation ra ON ra.wayward_brand_id = m2.wayward_brand_id GROUP BY m2.company_id) cr ON cr.company_id = sh.company_id"""
_CC_GROSS = r""" WITH member AS (
         SELECT b.wayward_brand_id,
            COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS company_id,
            b.brand_name,
            b.canonical_brand_id IS NOT NULL AND b.canonical_brand_id <> b.wayward_brand_id AS is_alias_row
           FROM ps_brands b
        ), sig AS (
         SELECT m.company_id,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,
            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS confirming,
            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,
            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,
            max(
                CASE s.strength
                    WHEN 'definitional'::text THEN 6
                    WHEN 'confirmed'::text THEN 5
                    WHEN 'strong'::text THEN 4
                    WHEN 'moderate'::text THEN 3
                    WHEN 'weak'::text THEN 2
                    ELSE 1
                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS best_china_rank,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,
            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS decided_by
           FROM member m
             LEFT JOIN ps_nationality_signals s ON s.wayward_brand_id = m.wayward_brand_id
          GROUP BY m.company_id
        ), shape AS (
         SELECT m.company_id,
            count(*) AS sibling_rows,
            min(m.brand_name) FILTER (WHERE NOT m.is_alias_row) AS head_name,
            min(m.brand_name) AS any_name,
            bool_or(r.reality = 'REAL'::text) AS is_real,
            bool_or(r.reality = 'JUNK'::text) AS any_row_junk,
            bool_or(r.ever_billed) AS ever_billed,
            bool_or(r.wayward_onboarded_them) AS onboarded,
            bool_or(r.on_a_frozen_list) AS on_a_frozen_list,
            bool_or(r.on_eric_sheet) AS on_eric_sheet
           FROM member m
             JOIN lens_ps_brand_reality r ON r.wayward_brand_id = m.wayward_brand_id
          GROUP BY m.company_id
        ), money AS (
         SELECT m.company_id,
            round(sum(l.amount) FILTER (WHERE l.invoice_status = 'paid'::text), 2) AS usage_collected
           FROM member m
             JOIN ps_stripe_invoice_lines l ON l.wayward_brand_id = m.wayward_brand_id
          WHERE l.is_ps_base AND l.product_id IS NOT NULL AND l.billing_month IS NOT NULL
          GROUP BY m.company_id
        )
 SELECT sh.company_id,
    COALESCE(sh.head_name, sh.any_name) AS company_name,
        CASE
            WHEN sg.human_not_china THEN 'not_china'::text
            WHEN sg.human_china THEN 'china'::text
            WHEN COALESCE(sg.confirming, 0::bigint) > 0 THEN 'china'::text
            WHEN COALESCE(sg.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text
            ELSE 'unknown'::text
        END AS verdict,
        CASE
            WHEN sg.human_not_china OR sg.human_china THEN 'human'::text
            WHEN COALESCE(sg.confirming, 0::bigint) > 0 THEN
            CASE sg.best_china_rank
                WHEN 6 THEN 'definitional'::text
                WHEN 5 THEN 'confirmed'::text
                WHEN 4 THEN 'strong'::text
                ELSE 'confirmed'::text
            END
            WHEN COALESCE(sg.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text
            ELSE NULL::text
        END AS verdict_strength,
    sg.china_evidence,
    sg.not_china_evidence,
    COALESCE(sg.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,
    sg.decided_by,
    sh.sibling_rows,
    sh.sibling_rows > 1 AS is_split_identity,
        CASE
            WHEN sh.is_real THEN 'REAL'::text
            WHEN sh.any_row_junk THEN 'JUNK'::text
            ELSE 'GHOST'::text
        END AS reality,
    sh.ever_billed,
    sh.onboarded,
    sh.on_a_frozen_list,
    sh.on_eric_sheet,
    mo.usage_collected
   FROM shape sh
     JOIN sig sg ON sg.company_id = sh.company_id
     LEFT JOIN money mo ON mo.company_id = sh.company_id"""
_MS_NET = r""" SELECT l.period_month,
    l.product_id,
    round(sum(usage_collected) FILTER (WHERE claimable), 2) AS collected_claimable,
    round(sum(mgmt_fee_owed), 2) AS mgmt_fee_owed,
    round(sum(partner_fee_owed), 2) AS partner_fee_owed,
    round(sum(mgmt_fee_owed) - sum(partner_fee_owed), 2) AS net_owed,
    count(DISTINCT l.wayward_brand_id) FILTER (WHERE claimable) AS claimable_brands,
    round(sum(COALESCE(ra.usage_refund_netted, 0)) FILTER (WHERE claimable), 2) AS usage_refunded
   FROM lens_ps_commission_ledger l
     LEFT JOIN lens_ps_refund_allocation ra ON ra.wayward_brand_id = l.wayward_brand_id AND ra.product_id = l.product_id AND ra.period_month = l.period_month
  GROUP BY l.period_month, l.product_id"""
_MS_GROSS = r""" SELECT period_month,
    product_id,
    round(sum(usage_collected) FILTER (WHERE claimable), 2) AS collected_claimable,
    round(sum(mgmt_fee_owed), 2) AS mgmt_fee_owed,
    round(sum(partner_fee_owed), 2) AS partner_fee_owed,
    round(sum(mgmt_fee_owed) - sum(partner_fee_owed), 2) AS net_owed,
    count(DISTINCT wayward_brand_id) FILTER (WHERE claimable) AS claimable_brands
   FROM lens_ps_commission_ledger
  GROUP BY period_month, product_id"""
_BVC = r""" SELECT tenant_id,
    wayward_brand_id,
    client_id,
    billing_month,
    product_id,
    sum(amount) AS usage_billed,
    sum(amount) FILTER (WHERE invoice_status = 'paid'::text) AS usage_collected,
    sum(amount) FILTER (WHERE invoice_status = 'open'::text) AS usage_outstanding,
    sum(amount) FILTER (WHERE invoice_status = 'paid'::text) * 0.10 AS ps_10pct_earned,
    count(DISTINCT stripe_invoice_id) AS invoices
   FROM ps_stripe_invoice_lines l
  WHERE is_ps_base
  GROUP BY tenant_id, wayward_brand_id, client_id, billing_month, product_id"""
_PP = r""" WITH onboarded AS (
         SELECT o.wayward_brand_id,
            max(o.value) FILTER (WHERE o.field = 'deal_source'::text) AS deal_source,
            max(o.value) FILTER (WHERE o.field = 'referral_source'::text) AS referral_source,
            min(o.observed_at) AS onboarded_at
           FROM ps_brand_observations o
          WHERE o.source_system ~~ 'slack:%%'::text AND o.wayward_brand_id IS NOT NULL
          GROUP BY o.wayward_brand_id
        ), attributed AS (
         SELECT ob.wayward_brand_id,
            ob.onboarded_at,
            COALESCE(( SELECT NULLIF(pc.lead_source_initial, 'unassigned'::text) AS "nullif"
                   FROM ps_partner_credit pc
                  WHERE pc.wayward_brand_id = ob.wayward_brand_id AND pc.lead_source_initial IS NOT NULL
                 LIMIT 1),
                CASE
                    WHEN ob.deal_source ~~ 'China Referral - %%'::text THEN lower(replace(ob.deal_source, 'China Referral - '::text, ''::text))
                    ELSE NULL::text
                END, 'unattributed'::text) AS partner
           FROM onboarded ob
        ), sold AS (
         SELECT ps_stripe_invoice_lines.wayward_brand_id,
            min(ps_stripe_invoice_lines.billing_month) AS first_sale,
            sum(ps_stripe_invoice_lines.amount) FILTER (WHERE ps_stripe_invoice_lines.invoice_status = 'paid'::text) AS usage_collected
           FROM ps_stripe_invoice_lines
          WHERE ps_stripe_invoice_lines.is_ps_base AND ps_stripe_invoice_lines.amount > 0::numeric AND ps_stripe_invoice_lines.wayward_brand_id IS NOT NULL
          GROUP BY ps_stripe_invoice_lines.wayward_brand_id
        ), quiet AS (
         SELECT DISTINCT ps_product_subscriptions.wayward_brand_id
           FROM ps_product_subscriptions
          WHERE ps_product_subscriptions.dormant_since IS NOT NULL
        )
 SELECT a.partner,
    r.name AS partner_name,
    r.company_name,
    count(*) AS brands_onboarded,
    count(s.wayward_brand_id) AS brands_that_sold,
    count(*) - count(s.wayward_brand_id) AS signed_and_died,
    round(100.0 * count(s.wayward_brand_id)::numeric / NULLIF(count(*), 0)::numeric, 1) AS production_rate_pct,
    count(q.wayward_brand_id) AS sold_then_went_quiet,
    round(sum(s.usage_collected), 2) AS usage_fees_generated,
    round(avg(s.usage_collected), 2) AS avg_per_producing_brand,
    round(avg((s.first_sale - a.onboarded_at::date)::numeric), 0) AS avg_days_to_first_sale
   FROM attributed a
     LEFT JOIN sold s ON s.wayward_brand_id = a.wayward_brand_id
     LEFT JOIN quiet q ON q.wayward_brand_id = a.wayward_brand_id
     LEFT JOIN ps_partner_registry r ON r.partner_id = a.partner
  GROUP BY a.partner, r.name, r.company_name"""


def upgrade() -> None:
    op.execute(_REFUND_LENS)
    op.execute(f"COMMENT ON VIEW lens_ps_refund_allocation IS $c${_REFUND_COMMENT}$c$")
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_refund_allocation TO {role}")
    op.execute(_LEDGER_NET)
    op.execute(f"COMMENT ON VIEW lens_ps_commission_ledger IS $c${_LEDGER_COMMENT}$c$")
    op.execute("CREATE OR REPLACE VIEW lens_ps_china_verdict AS " + _CV_NET)
    op.execute("CREATE OR REPLACE VIEW lens_ps_china_companies AS " + _CC_NET)
    op.execute("CREATE OR REPLACE VIEW lens_ps_monthly_summary AS " + _MS_NET)
    op.execute("DROP VIEW IF EXISTS lens_ps_billed_vs_collected")
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_performance")


def downgrade() -> None:
    # revert the money views to gross, then drop the refund lens they depend on
    op.execute(_LEDGER_GROSS)
    op.execute("CREATE OR REPLACE VIEW lens_ps_china_verdict AS " + _CV_GROSS)
    op.execute("CREATE OR REPLACE VIEW lens_ps_china_companies AS " + _CC_GROSS)
    op.execute("DROP VIEW IF EXISTS lens_ps_monthly_summary")
    op.execute("CREATE VIEW lens_ps_monthly_summary AS " + _MS_GROSS)
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_monthly_summary TO {role}")
    op.execute("DROP VIEW IF EXISTS lens_ps_refund_allocation")
    # recreate the retired legacy diagnostics
    for name, sql in (("lens_ps_billed_vs_collected", _BVC), ("lens_ps_partner_performance", _PP)):
        op.execute(f"CREATE VIEW {name} AS " + sql)
        for role in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {name} TO {role}")
