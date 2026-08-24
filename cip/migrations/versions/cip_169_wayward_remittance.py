# foundry: kind=migration domain=client-intelligence-platform
"""cip_169: ps_wayward_remittance + lens_ps_wayward_remittance_recon (Tim, 2026-08-24).

The CASH-BASIS layer of the two-layer claim model, and the #3 retention store. Wayward's
monthly "Tim Rev Share Report" is what THEY state they owe us, computed on client payments
(cash basis, keyed by the client PAYMENT_DATE). Rather than recompute that number from our
Stripe tables (an adversarial QC on 2026-08-21 found recompute breaks on 586 undated paid
invoices, the is_ps_base-vs-fee_type usage selector, refunds on a separate date axis, and our
10/6/3 vs their flat 10%), we INGEST Wayward's report verbatim as the cash-basis source of
truth and reconcile it against our accrual claim (lens_ps_claim).

ps_wayward_remittance: one row per report line (grain = brand x payment x report_month),
storing exactly what Wayward stated. Immutable append per report_month (the loader deletes +
reinserts a whole month for idempotency). Mirrors the ps_ table pattern (cip_101): tenant_id +
FORCE RLS + cip_tenant_scope.

lens_ps_wayward_remittance_recon: per china-referral brand, cumulative OUR claim (mgmt_fee_owed,
collected-basis accrual) + OUR pipeline (mgmt_fee_earned) vs cumulative WAYWARD-stated
(rev_share_owed_stated, cash basis) vs WAYWARD-paid (ps_payment_events via lens_ps_claim), with
the claim-minus-remitted difference and the aging (last report month). A reconciliation view for
the dashboard + the Wayward response -- NOT a claim input. Granted to the reporting reader set so
the reports app can read it.

Additive + isolated: nothing references the table or lens yet (the dashboard is 10c/#16).

Revision ID: cip_169_wayward_remittance
Revises: cip_168_earned_measure
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_169_wayward_remittance"
down_revision: str | Sequence[str] | None = "cip_168_earned_measure"
branch_labels = None
depends_on = None

# The raw table stays internal to the cip read roles (matches cip_101).
_TABLE_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
# The reconciliation LENS is a read surface for the reports app -> full reporting reader set
# (the roles cip_120 added, confirmed present on lens_ps_commission_ledger).
_LENS_READ_ROLES = (
    "cip_query_reader",
    "cip_metabase_project_silk",
    "cip_twenty_project_silk",
    "metabase_reader_foundry",
    "ps_reporting_reader",
    "ps_reporting_writer",
)

_RECON_LENS = """
CREATE VIEW lens_ps_wayward_remittance_recon AS
WITH remitted AS (
    SELECT wayward_brand_id,
           sum(rev_share_owed_stated) AS cum_remitted_stated,
           sum(usage_fees_paid)       AS cum_usage_paid_stated,
           max(report_month)          AS last_report_month,
           count(*)                   AS report_rows
    FROM ps_wayward_remittance
    WHERE wayward_brand_id IS NOT NULL
    GROUP BY wayward_brand_id
)
SELECT
    COALESCE(c.wayward_brand_id, r.wayward_brand_id)              AS wayward_brand_id,
    c.brand_name,
    c.verdict,
    round(COALESCE(c.mgmt_fee_owed, 0), 2)                        AS cum_claimed_owed,
    round(COALESCE(c.mgmt_fee_earned, 0), 2)                      AS cum_claimed_earned,
    round(COALESCE(r.cum_remitted_stated, 0), 2)                  AS cum_remitted_stated,
    round(COALESCE(r.cum_usage_paid_stated, 0), 2)               AS cum_usage_remitted,
    round(COALESCE(c.wayward_paid, 0), 2)                         AS cum_wayward_paid,
    round(COALESCE(c.mgmt_fee_owed, 0) - COALESCE(r.cum_remitted_stated, 0), 2) AS claim_minus_remitted,
    r.last_report_month,
    COALESCE(r.report_rows, 0)                                    AS report_rows,
    CASE
        WHEN r.wayward_brand_id IS NULL                     THEN 'no_remittance'
        WHEN c.wayward_brand_id IS NULL                     THEN 'remitted_no_claim'
        WHEN abs(COALESCE(c.mgmt_fee_owed, 0) - COALESCE(r.cum_remitted_stated, 0)) <= 1.00 THEN 'reconciled'
        WHEN COALESCE(c.mgmt_fee_owed, 0) > COALESCE(r.cum_remitted_stated, 0) THEN 'under_remitted'
        ELSE 'over_remitted'
    END AS recon_status
FROM lens_ps_claim c
FULL OUTER JOIN remitted r ON r.wayward_brand_id = c.wayward_brand_id
WHERE c.verdict = 'china' OR r.wayward_brand_id IS NOT NULL
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ps_wayward_remittance (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL,
            report_month date NOT NULL,
            customer_id text,
            wayward_brand_id uuid,
            brand_name text,
            payment_date date,
            signup_raw text,
            stripe_invoice_ids text,
            stripe_invoice_links text,
            commission_fees_paid numeric,
            usage_fees_paid numeric,
            saas_fees_paid numeric,
            cc_processing_fees_paid numeric,
            total_amount_paid numeric,
            rev_share_owed_stated numeric,
            months_from_signup numeric,
            days_from_signup numeric,
            source_file text,
            ingested_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ps_wayward_remittance_month_idx ON ps_wayward_remittance (tenant_id, report_month)")
    op.execute("CREATE INDEX ps_wayward_remittance_brand_idx ON ps_wayward_remittance (tenant_id, wayward_brand_id)")
    # tenant isolation, mirroring the other ps_ tables (FORCE so even the table owner is scoped)
    op.execute("ALTER TABLE ps_wayward_remittance ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_wayward_remittance FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON ps_wayward_remittance "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )
    op.execute(
        "COMMENT ON TABLE ps_wayward_remittance IS "
        "'Wayward monthly Rev Share Report, ingested verbatim -- the CASH-BASIS source of truth "
        "(what Wayward states they owe us, computed on client payments by PAYMENT_DATE). Grain = "
        "brand x payment x report_month. Immutable append per report_month (loader deletes + "
        "reinserts a whole month). rev_share_owed_stated is WAYWARD''S number, never recomputed. "
        "Reconciled against our accrual claim in lens_ps_wayward_remittance_recon. Retention store "
        "for #3; backfill of prior months = #15.'"
    )
    for r in _TABLE_READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_wayward_remittance TO {r}")
    # cip_rls_test_role is provisioned only by the pytest harness — guard for the raw Tier-C container
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cip_rls_test_role') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON ps_wayward_remittance TO cip_rls_test_role;
            END IF;
        END $$;
        """
    )
    op.execute(_RECON_LENS)
    op.execute(
        "COMMENT ON VIEW lens_ps_wayward_remittance_recon IS "
        "$c$Scope = every china brand (by our verdict) PLUS any brand Wayward actually remitted on "
        "(so a remitted brand we currently call non-china, e.g. a pending flip, still surfaces). "
        "Per brand: cumulative OUR claim (cum_claimed_owed = mgmt_fee_owed, "
        "collected-basis accrual) + OUR pipeline (cum_claimed_earned = mgmt_fee_earned) vs "
        "cumulative WAYWARD-stated (cum_remitted_stated = sum of rev_share_owed_stated from the "
        "ingested reports, cash basis) vs WAYWARD-paid (cum_wayward_paid from ps_payment_events). "
        "claim_minus_remitted = owed - remitted. recon_status: reconciled (|diff|<=$1), "
        "under_remitted (we claim more than Wayward states), over_remitted, remitted_no_claim, "
        "no_remittance. Reconciliation / negotiation view for the dashboard + Wayward response -- "
        "NOT a claim input.$c$"
    )
    for r in _LENS_READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_wayward_remittance_recon TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_wayward_remittance_recon")
    op.execute("DROP TABLE IF EXISTS ps_wayward_remittance")
