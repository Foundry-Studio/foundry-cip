# foundry: kind=migration domain=client-intelligence-platform
"""cip_97: remove the superseded cip_clients nationality name-signal system + its 4 dead views.

Tim, 2026-07-14: clean out the older nationality system now that the audit's source of truth is
ps_nationality_signals -> lens_ps_china_verdict (cip_82-95).

WHAT THIS REMOVES
-----------------
1. The five `cip_clients.nationality_*` columns (class / review_status / decided_at / decided_by /
   rationale), their 2 CHECK constraints and 2 indexes. They were populated once
   (decided_by='rule:nationality_v1') by a name-signal rule pass — the exact "country/name decides
   nationality" logic the audit deliberately rejected. Superseded; not automated (no FAS reference,
   no scheduler, not imported by any module).
2. Four now-dead views that read those columns:
   - lens_ps_eligibility          — its only readers were the money-writer scripts retired in this
                                     same change (compute_monthly_earnings.py, compute_claimability.py);
                                     no view depends on it.
   - lens_ps_china_commission_v2  — read by no code.
   - lens_ps_brand_opportunity    — read by no code.
   - lens_ps_nationality_gap      — read by no code; its whole purpose was the (now dead) gap.
   Verified: none of the four has a view dependent, and the KEPT money statement lenses
   (lens_ps_claim_reconciliation / _client_statement / _partner_statement / _unclaimed) read none
   of them. The China audit lenses (verdict / companies / reality / evidence_grid / chase_list) do
   NOT read them either — they read lens_ps_exclusion_status, not lens_ps_eligibility.

DATA / MONEY. Zero movement to the China book and zero to the money spine: ps_monthly_earnings is
untouched (kept as a frozen snapshot), and nothing the audit reads changes. The raw Stripe facts
(ps_stripe_*) are untouched. This is pure dead-surface removal.

REVERSIBLE. downgrade re-creates the columns/constraints/indexes and all four views verbatim (empty
column data on the way back is inherent to a DROP COLUMN and is expected).

Revision ID: cip_97_remove_nationality_system
Revises: cip_95_retire_probable
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_97_remove_nationality_system"
down_revision: str | Sequence[str] | None = "cip_95_retire_probable"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# ── the four view definitions, verbatim from pg_get_viewdef (for a faithful downgrade) ──
_V_ELIGIBILITY = """
CREATE VIEW lens_ps_eligibility AS
 WITH billed AS (
         SELECT ps_stripe_invoice_lines.wayward_brand_id,
            min(ps_stripe_invoice_lines.billing_month) AS first_billed_month,
            max(ps_stripe_invoice_lines.billing_month) AS last_billed_month,
            bool_or(ps_stripe_invoice_lines.billing_month >= '2025-12-01'::date) AS bills_in_our_era,
            max(ps_stripe_invoice_lines.client_id::text)::uuid AS client_id
           FROM ps_stripe_invoice_lines
          WHERE ps_stripe_invoice_lines.is_ps_base AND ps_stripe_invoice_lines.amount > 0::numeric AND ps_stripe_invoice_lines.billing_month IS NOT NULL AND ps_stripe_invoice_lines.wayward_brand_id IS NOT NULL
          GROUP BY ps_stripe_invoice_lines.wayward_brand_id
        ), obs AS (
         SELECT ps_brand_observations.wayward_brand_id,
            max(ps_brand_observations.client_id::text)::uuid AS client_id,
            max(ps_brand_observations.value) FILTER (WHERE ps_brand_observations.field = 'brand_name'::text) AS brand_name,
            max(ps_brand_observations.value) FILTER (WHERE ps_brand_observations.field = 'country'::text) AS wayward_country,
            max(ps_brand_observations.value) FILTER (WHERE ps_brand_observations.field = 'deal_source'::text) AS deal_source
           FROM ps_brand_observations
          GROUP BY ps_brand_observations.wayward_brand_id
        )
 SELECT br.wayward_brand_id,
    COALESCE(b.client_id, obs.client_id) AS client_id,
    COALESCE(obs.brand_name, br.brand_name) AS brand_name,
    b.first_billed_month,
    b.last_billed_month,
    b.bills_in_our_era,
    br.signup_date AS onboarded,
    br.signup_date_source AS onboarded_source,
    obs.deal_source,
    obs.wayward_country,
    c.nationality_class,
    st.buckets AS excluded_bucket,
    st.is_excluded,
    st.someone_else_earning,
    st.is_winnable,
    (c.nationality_class = ANY (ARRAY['chinese_confirmed'::text, 'chinese_suspected'::text])) OR obs.wayward_country = 'CN'::text AS is_chinese,
    br.signup_date > '2025-11-18'::date AS post_takeover,
        CASE
            WHEN st.is_excluded THEN 'excluded'::text
            WHEN NOT ((c.nationality_class = ANY (ARRAY['chinese_confirmed'::text, 'chinese_suspected'::text])) OR obs.wayward_country = 'CN'::text) THEN 'not_chinese'::text
            WHEN br.signup_date > '2025-11-18'::date THEN 'eligible_rule_a'::text
            WHEN b.bills_in_our_era THEN 'eligible_rule_b'::text
            WHEN b.first_billed_month IS NULL THEN 'never_billed'::text
            ELSE 'stopped_billing_pre_december'::text
        END AS eligibility,
        CASE
            WHEN st.is_excluded THEN NULL::date
            WHEN br.signup_date > '2025-11-18'::date THEN b.first_billed_month
            WHEN b.bills_in_our_era THEN '2025-12-01'::date
            ELSE NULL::date
        END AS credit_starts
   FROM ps_brands br
     JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = br.wayward_brand_id
     LEFT JOIN billed b ON b.wayward_brand_id = br.wayward_brand_id
     LEFT JOIN obs ON obs.wayward_brand_id = br.wayward_brand_id
     LEFT JOIN cip_clients c ON c.id = COALESCE(b.client_id, obs.client_id)
"""

_V_COMMISSION_V2 = """
CREATE VIEW lens_ps_china_commission_v2 AS
 WITH pay AS (
         SELECT pe.tenant_id,
            pe.wayward_brand_id,
            count(*) AS payment_count,
            min(pe.payment_date) AS first_payment,
            max(pe.payment_date) AS latest_payment,
            sum(pe.usage_fees_paid) AS usage_fees_paid_total,
            sum(pe.commission_fees_paid) AS commission_fees_paid_total,
            sum(pe.total_amount_paid) AS total_amount_paid,
            sum(pe.rev_share_stated) AS commission_accrued,
            sum(pe.rev_share_computed) AS commission_computed
           FROM ps_payment_events pe
          WHERE pe.tenant_id = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid AND pe.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid
          GROUP BY pe.tenant_id, pe.wayward_brand_id
        )
 SELECT cl.id AS client_id,
    cl.tenant_id,
    cl.wayward_brand_id,
    cl.name AS brand_name,
    cl.nationality_class,
    cl.exhibit_a,
    cl.exhibit_a_matched_name,
    cl.lifecycle_status,
    cl.performance_tier,
    attr.ps_attribution_owner,
    attr.ps_lead_source,
    attr.ps_conditional,
    pc.partner_of_record,
    pc.referral_detail_raw,
    pc.credit_start,
    pc.credit_end,
        CASE
            WHEN pc.partner_of_record IS NULL THEN 'none'::text
            WHEN pc.credit_end IS NOT NULL AND now()::date > pc.credit_end THEN 'expired'::text
            ELSE 'active'::text
        END AS credit_window_state,
    COALESCE(pay.payment_count, 0::bigint) AS payment_count,
    pay.first_payment,
    pay.latest_payment,
    COALESCE(pay.usage_fees_paid_total, 0::numeric) AS usage_fees_paid_total,
    COALESCE(pay.commission_fees_paid_total, 0::numeric) AS commission_fees_paid_total,
    COALESCE(pay.total_amount_paid, 0::numeric) AS total_amount_paid,
    COALESCE(pay.commission_accrued, 0::numeric) AS commission_accrued,
    COALESCE(pay.commission_computed, 0::numeric) AS commission_computed,
    COALESCE(pay.commission_accrued, 0::numeric) - COALESCE(pay.commission_computed, 0::numeric) AS commission_variance
   FROM cip_clients cl
     LEFT JOIN pay ON pay.wayward_brand_id = cl.wayward_brand_id
     LEFT JOIN LATERAL ( SELECT a.ps_attribution_owner,
            a.ps_lead_source,
            a.ps_conditional
           FROM ps_attribution a
          WHERE a.tenant_id = cl.tenant_id AND a.client_id = cl.id AND a.effective_to IS NULL
          ORDER BY a.effective_from DESC
         LIMIT 1) attr ON true
     LEFT JOIN LATERAL ( SELECT c.partner_of_record,
            c.referral_detail_raw,
            c.credit_start,
            c.credit_end
           FROM ps_partner_credit c
          WHERE c.tenant_id = cl.tenant_id AND c.client_id = cl.id
          ORDER BY c.credit_start DESC NULLS LAST
         LIMIT 1) pc ON true
  WHERE cl.tenant_id = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid AND cl.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND (cl.nationality_class = 'chinese_confirmed'::text OR pay.wayward_brand_id IS NOT NULL)
"""

_V_BRAND_OPPORTUNITY = """
CREATE VIEW lens_ps_brand_opportunity AS
 WITH credit AS (
         SELECT DISTINCT ON (ps_partner_credit.client_id, ps_partner_credit.product_id) ps_partner_credit.client_id,
            ps_partner_credit.product_id,
            ps_partner_credit.partner_of_record,
            ps_partner_credit.deal_type,
            ps_partner_credit.partner_rate
           FROM ps_partner_credit
          WHERE ps_partner_credit.credit_end IS NULL OR ps_partner_credit.credit_end > now()
          ORDER BY ps_partner_credit.client_id, ps_partner_credit.product_id, ps_partner_credit.determined_at DESC NULLS LAST, ps_partner_credit.created_at DESC
        ), attr AS (
         SELECT DISTINCT ON (ps_attribution.client_id, ps_attribution.product_id) ps_attribution.client_id,
            ps_attribution.product_id,
            ps_attribution.ps_sales_lead,
            ps_attribution.ps_cs_lead
           FROM ps_attribution
          WHERE ps_attribution.effective_to IS NULL
          ORDER BY ps_attribution.client_id, ps_attribution.product_id, ps_attribution.effective_from DESC NULLS LAST
        ), subs AS (
         SELECT DISTINCT ON (ps_product_subscriptions.client_id, ps_product_subscriptions.product_id) ps_product_subscriptions.client_id,
            ps_product_subscriptions.product_id,
            ps_product_subscriptions.last_activity_at,
            ps_product_subscriptions.activity_source
           FROM ps_product_subscriptions
          ORDER BY ps_product_subscriptions.client_id, ps_product_subscriptions.product_id, ps_product_subscriptions.last_activity_at DESC NULLS LAST
        )
 SELECT c.id AS client_id,
    c.tenant_id,
    c.name AS brand_name,
    c.wayward_brand_id,
    c.nationality_class,
    c.exhibit_a,
    con.partner_of_record AS connect_partner,
    con.deal_type AS connect_deal_type,
    bst.partner_of_record AS boost_partner,
    bst.deal_type AS boost_deal_type,
    att.ps_sales_lead AS connect_sales_lead,
    cs.last_activity_at AS connect_last_activity,
    cs.activity_source AS connect_activity_source,
    bs.last_activity_at AS boost_last_activity,
    cs.last_activity_at IS NOT NULL AND cs.last_activity_at < (now() - '90 days'::interval) AS connect_dormant,
    bs.last_activity_at IS NOT NULL AND bs.last_activity_at < (now() - '90 days'::interval) AS boost_dormant,
    cs.last_activity_at IS NULL AS connect_activity_unknown,
    bst.partner_of_record IS NULL OR bst.partner_of_record = 'unassigned'::text AS boost_open_to_ps,
    COALESCE(cs.last_activity_at < (now() - '90 days'::interval), false) AS connect_reactivatable,
        CASE
            WHEN con.deal_type = 'flat_fee'::text THEN 'eric_flat_fee'::text
            WHEN con.deal_type = 'rev_share'::text AND COALESCE(con.partner_rate, 0::numeric) >= 10::numeric THEN 'partner_full_10'::text
            WHEN con.deal_type = 'rev_share'::text THEN 'partner_split'::text
            WHEN con.partner_of_record = 'unassigned'::text THEN 'ps_direct'::text
            ELSE 'undetermined'::text
        END AS ps_bucket
   FROM cip_clients c
     LEFT JOIN credit con ON con.client_id = c.id AND con.product_id = 'connect'::text
     LEFT JOIN credit bst ON bst.client_id = c.id AND bst.product_id = 'boosted'::text
     LEFT JOIN attr att ON att.client_id = c.id AND att.product_id = 'connect'::text
     LEFT JOIN subs cs ON cs.client_id = c.id AND cs.product_id = 'connect'::text
     LEFT JOIN subs bs ON bs.client_id = c.id AND bs.product_id = 'boosted'::text
"""

_V_NATIONALITY_GAP = """
CREATE VIEW lens_ps_nationality_gap AS
 WITH ctry AS (
         SELECT ps_brand_observations.wayward_brand_id,
            max(ps_brand_observations.value) FILTER (WHERE ps_brand_observations.value ~ '^[A-Z]{2}$'::text) AS country
           FROM ps_brand_observations
          WHERE ps_brand_observations.field = 'country'::text
          GROUP BY ps_brand_observations.wayward_brand_id
        ), money AS (
         SELECT e.wayward_brand_id,
            sum(e.usage_collected) AS collected,
            sum(e.usage_collected) FILTER (WHERE e.period_month >= '2025-12-01'::date) AS collected_our_era,
            min(e.period_month) AS first_month,
            max(e.period_month) AS last_month
           FROM ps_monthly_earnings e
          GROUP BY e.wayward_brand_id
        )
 SELECT b.wayward_brand_id,
    b.brand_name,
    b.signup_date,
    c.country AS wayward_country,
    cl.nationality_class,
    pc.partner_of_record,
    pc.deal_source,
    x.bucket AS excluded_bucket,
    round(m.collected, 2) AS collected_all_time,
    round(m.collected_our_era, 2) AS collected_our_era,
    round(m.collected_our_era * 0.10, 2) AS ps_at_stake_if_chinese,
    m.first_month,
    m.last_month
   FROM ps_brands b
     JOIN money m ON m.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN ctry c ON c.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN cip_clients cl ON cl.id = b.client_id
     LEFT JOIN ps_excluded_brands x ON x.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN LATERAL ( SELECT p.partner_of_record,
            p.deal_source
           FROM ps_partner_credit p
          WHERE p.wayward_brand_id = b.wayward_brand_id
         LIMIT 1) pc ON true
  WHERE c.country IS NULL AND COALESCE(cl.nationality_class, 'unknown'::text) = 'unknown'::text AND m.collected > 0::numeric
"""

# view -> the read roles it originally carried (rls_test_role grants are test artifacts, omitted)
_VIEW_GRANTS = {
    "lens_ps_eligibility": ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk"),
    "lens_ps_china_commission_v2": ("cip_query_reader", "cip_metabase_project_silk"),
    "lens_ps_brand_opportunity": ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk"),
    "lens_ps_nationality_gap": ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk"),
}
_NAT_COLS = (
    "nationality_class", "nationality_review_status", "nationality_decided_at",
    "nationality_decided_by", "nationality_rationale",
)


def upgrade() -> None:
    # 1. the four dead views (each verified to have no view dependents)
    for v in ("lens_ps_eligibility", "lens_ps_china_commission_v2",
              "lens_ps_brand_opportunity", "lens_ps_nationality_gap"):
        op.execute(f"DROP VIEW IF EXISTS {v}")

    # 2. indexes, then constraints, then the columns
    op.execute("DROP INDEX IF EXISTS idx_cip_clients_nationality")
    op.execute("DROP INDEX IF EXISTS idx_cip_clients_nationality_review")
    op.execute("ALTER TABLE cip_clients DROP CONSTRAINT IF EXISTS cip_clients_nationality_class_check")
    op.execute("ALTER TABLE cip_clients DROP CONSTRAINT IF EXISTS cip_clients_nationality_review_status_check")
    for col in _NAT_COLS:
        op.execute(f"ALTER TABLE cip_clients DROP COLUMN IF EXISTS {col}")


def downgrade() -> None:
    # columns (empty on the way back — inherent to a dropped column)
    op.execute("ALTER TABLE cip_clients ADD COLUMN nationality_class text NOT NULL DEFAULT 'unknown'")
    op.execute("ALTER TABLE cip_clients ADD COLUMN nationality_review_status text")
    op.execute("ALTER TABLE cip_clients ADD COLUMN nationality_decided_at timestamptz")
    op.execute("ALTER TABLE cip_clients ADD COLUMN nationality_decided_by text")
    op.execute("ALTER TABLE cip_clients ADD COLUMN nationality_rationale text")
    op.execute(
        "ALTER TABLE cip_clients ADD CONSTRAINT cip_clients_nationality_class_check "
        "CHECK (nationality_class = ANY (ARRAY['chinese_confirmed','chinese_suspected','non_chinese','unknown']))"
    )
    op.execute(
        "ALTER TABLE cip_clients ADD CONSTRAINT cip_clients_nationality_review_status_check "
        "CHECK (nationality_review_status IS NULL OR nationality_review_status = ANY "
        "(ARRAY['pending','probable','confirmed','escalated']))"
    )
    op.execute("CREATE INDEX idx_cip_clients_nationality ON cip_clients (tenant_id, nationality_class)")
    op.execute(
        "CREATE INDEX idx_cip_clients_nationality_review ON cip_clients (tenant_id, nationality_review_status) "
        "WHERE nationality_review_status IS NOT NULL"
    )
    for sql in (_V_ELIGIBILITY, _V_COMMISSION_V2, _V_BRAND_OPPORTUNITY, _V_NATIONALITY_GAP):
        op.execute(sql)
    for view, roles in _VIEW_GRANTS.items():
        for r in roles:
            op.execute(f"GRANT SELECT ON {view} TO {r}")
