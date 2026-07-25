# foundry: kind=migration domain=client-intelligence-platform
"""cip_132: pipeline projections (BE-3) — a read-only per-month china roll-up of the
"follow-a-dollar" pipeline. RATE-MATH ON ACTUALS, NOT A FORECAST.

Design of record: WORKBENCH/china-audit/REPORTING-BACKEND-CHECKPOINT.md ("BE-3", §3/§4) +
REPORTING-ROUND3-DEEP-PLAN.md (BE-3 row) + CONTEXT-PACK-ps-reporting.md §4 ("money in flight —
what today's actuals become"). Tim's §4 resolutions (2026-07-25) are baked in below.

WHAT THIS ADDS (purely additive; nothing renamed, altered, or dropped):
  * lens_ps_pipeline — ONE row per period_month. It only ROLLS UP EXISTING surfaces
    (lens_ps_commission_ledger, ps_partner_payouts, ps_payment_events); it rewrites no money lens
    and creates no table. Read-only + additive => ZERO money-movement BY CONSTRUCTION.

MONEY-NEUTRAL BY CONSTRUCTION — and reconciled live (tenant PS 078a37d6…, 2026-07-25):
  * The billed/collected/fee stages are a straight GROUP BY period_month of the CLAIMABLE china
    rows of lens_ps_commission_ledger (WHERE l.claimable — china AND eligible AND in the ownership
    window; the ledger's mgmt/partner fees are already 0 for non-claimable rows). Summed across the
    9 live months this equals lens_ps_monthly_summary to the penny: mgmt_fee_owed Σ = $33,083.02,
    partner_fee_owed Σ = $1,041.74 (the BE-2 invariant baseline), net_to_us Σ = $32,041.28,
    usage_collected Σ = $332,916.48. No lens is materialized — this recomputes on read like its
    siblings, so BE-2's free retro/forward rate recompute is preserved.

STAGES & DECISIONS (each a documented §4 call — see the COMMENT ON VIEW at the bottom):
  * accrued_gmv (Connect) / accrued_ad_spend (Boost) — "accrued-not-yet-billed". There is NO
    pre-invoice feed today (Tim, 2026-07-15) => surfaced as $0 columns until a feed exists. Connect
    GMV and Boost ad-spend are DIFFERENT UNITS => two SEPARATE columns, NEVER summed.
  * usage_billed -> usage_collected -> billed_not_collected (= billed − collected). Both are USD
    Stripe amounts (safe to sum across products); collected is refund-netted, billed is gross.
  * mgmt_fee_owed (our commission) -> partner_fee_owed (referral share).
  * partner_paid_in_month (ps_partner_payouts.amount_paid, DOLLARS) -> partner_owed_not_paid
    (= partner_fee_owed − partner_paid_in_month). Partner payouts carry a PERFORMANCE month
    (period_month — the axis cip_101 was designed to reconcile on), so this residual is same-axis
    and clean. (ps_partner_payouts is empty today => partner_paid = 0 => the residual = the full
    fee, correctly.) A single month may go negative on a catch-up payment — it is an honest
    per-period difference, NOT the GREATEST(…,0) entity-level figure in lens_ps_partner_payout_summary.
  * net_to_us (= mgmt_fee_owed − partner_fee_owed) — the §6 margin extra (== monthly_summary.net_owed).
  * wayward_paid_in_month (ps_payment_events.rev_share_stated) on a PAYMENT/CASH-RECEIVED basis:
    ps_payment_events has NO performance month and payment_date lands ~2 months after the usage it
    settles (cip_77: "Never compare it to a usage month"). So this column sits on a DIFFERENT TIME
    AXIS than the fee stages — flagged payment-basis in the view COMMENT. It is NOT netted against
    anything here (the entity-level netting is lens_ps_claim.ps_claim_owed = $14,077.02).

CHINA SCOPE: the ledger stages filter china via `claimable` (matching lens_ps_monthly_summary).
wayward_paid (ps_payment_events) is china-scoped by an explicit `wayward_brand_id IN (china verdict)`
filter — this view is the FINAL aggregate, so (unlike lens_ps_claim, which scopes china via its
consumer's downstream verdict filter) it must gate china itself; without it 4 non-china rows / $13.26
would leak into a china-pipeline column. partner_paid (ps_partner_payouts) is the china-program payout
ledger by construction (cip_101), is empty today, and carries no brand key to verdict-join — so it is
trusted as china-program (revisit if it ever holds non-china payouts).

Revision ID: cip_132_pipeline   (16 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_131_partner_rate
APPLY-TIME (not in file): export FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS="solo_kimi_k3_engine_dir"
for env.py's cross-pollution guard (the shared prod DB carries a foreign monorepo revision).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_132_pipeline"
down_revision: str | Sequence[str] | None = "cip_131_partner_rate"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
# The lens read-role set + the reporting app's reader (cip_129/130/131 convention). A lens_ps_*
# VIEW still gets an EXPLICIT grant here — cip_120's auto-enumeration is a one-time grant, not live.
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
_READER = "ps_reporting_reader"

# ── lens_ps_pipeline — ONE row per period_month. Every money column is a clean per-period
#    aggregate; Connect GMV and Boost ad-spend are kept in SEPARATE columns and never summed. ─────
_PIPELINE_VIEW = r"""CREATE OR REPLACE VIEW lens_ps_pipeline AS
WITH ledger_roll AS (
    -- Performance-month roll-up of the CLAIMABLE china book (== lens_ps_monthly_summary summed
    -- across product_id). usage_* are USD and summable across products; collected is refund-netted
    -- (the ledger nets ps_refund_allocation), billed is gross. Fees are already 0 for non-claimable
    -- rows, so WHERE claimable simply scopes the population coherently to the fee base.
    SELECT l.period_month,
           round(sum(l.usage_billed), 2)     AS usage_billed,
           round(sum(l.usage_collected), 2)  AS usage_collected,
           round(sum(l.mgmt_fee_owed), 2)    AS mgmt_fee_owed,
           round(sum(l.partner_fee_owed), 2) AS partner_fee_owed
    FROM lens_ps_commission_ledger l
    WHERE l.claimable
    GROUP BY l.period_month
),
partner_paid AS (
    -- What we actually PAID partners, on the PERFORMANCE month (period_month) — the axis cip_101
    -- was built to reconcile against partner_owed. amount_paid is DOLLARS. (Table empty today.)
    SELECT period_month,
           round(sum(amount_paid), 2) AS partner_paid_in_month
    FROM ps_partner_payouts
    WHERE period_month IS NOT NULL
    GROUP BY period_month
),
wayward_paid AS (
    -- What WAYWARD paid US, on the PAYMENT month (cash-received basis). ps_payment_events has no
    -- performance month; payment_date lands ~2 months after the usage it settles (cip_77) => a
    -- DIFFERENT time axis than the fee stages. rev_share_stated matches lens_ps_claim.wayward_paid.
    -- CHINA-SCOPED via lens_ps_china_verdict: this view is the FINAL aggregate, so (unlike lens_ps_claim,
    -- which scopes china through its consumer's downstream verdict filter) it must gate china itself —
    -- without this, non-china cash would leak into a china-pipeline column.
    SELECT date_trunc('month', pe.payment_date)::date AS period_month,
           round(sum(pe.rev_share_stated), 2) AS wayward_paid_in_month
    FROM ps_payment_events pe
    WHERE pe.payment_date IS NOT NULL AND pe.wayward_brand_id IS NOT NULL
      AND pe.wayward_brand_id IN (SELECT wayward_brand_id FROM lens_ps_china_verdict WHERE verdict = 'china')
    GROUP BY date_trunc('month', pe.payment_date)::date
),
bounds AS (
    SELECT min(period_month) AS lo, max(period_month) AS hi
    FROM ( SELECT period_month FROM ledger_roll
           UNION ALL SELECT period_month FROM partner_paid
           UNION ALL SELECT period_month FROM wayward_paid ) allm
),
months AS (   -- DENSE month spine: every month from earliest to latest activity, so a zero-activity
              -- INTERIOR month still yields a row (clean trends/charts; no silent gap). Empty book => 0 rows.
    SELECT generate_series(b.lo, b.hi, INTERVAL '1 month')::date AS period_month
    FROM bounds b WHERE b.lo IS NOT NULL
)
SELECT
    m.period_month,
    -- accrued-not-yet-billed: NO pre-invoice feed today (Tim, 2026-07-15) => $0. Connect GMV and
    -- Boost ad-spend are DIFFERENT UNITS => two columns, NEVER added together.
    0::numeric AS accrued_gmv,
    0::numeric AS accrued_ad_spend,
    COALESCE(lr.usage_billed, 0)    AS usage_billed,
    COALESCE(lr.usage_collected, 0) AS usage_collected,
    COALESCE(lr.usage_billed, 0) - COALESCE(lr.usage_collected, 0)       AS billed_not_collected,
    COALESCE(lr.mgmt_fee_owed, 0)    AS mgmt_fee_owed,
    COALESCE(lr.partner_fee_owed, 0) AS partner_fee_owed,
    COALESCE(pp.partner_paid_in_month, 0) AS partner_paid_in_month,
    COALESCE(lr.partner_fee_owed, 0) - COALESCE(pp.partner_paid_in_month, 0) AS partner_owed_not_paid,
    COALESCE(lr.mgmt_fee_owed, 0) - COALESCE(lr.partner_fee_owed, 0)         AS net_to_us,
    COALESCE(wp.wayward_paid_in_month, 0) AS wayward_paid_in_month
FROM months m
LEFT JOIN ledger_roll  lr ON lr.period_month = m.period_month
LEFT JOIN partner_paid pp ON pp.period_month = m.period_month
LEFT JOIN wayward_paid wp ON wp.period_month = m.period_month
ORDER BY m.period_month"""

_VIEW_COMMENT = (
    "COMMENT ON VIEW lens_ps_pipeline IS $c$BE-3 (cip_132): per-month china roll-up of the "
    "follow-a-dollar pipeline. RATE-MATH ON ACTUALS, NOT A FORECAST. ONE row per period_month; "
    "read-only, additive — it only rolls up lens_ps_commission_ledger (claimable china rows, == "
    "lens_ps_monthly_summary), ps_partner_payouts, and ps_payment_events. UNITS NEVER SUMMED: "
    "accrued_gmv (Connect GMV) and accrued_ad_spend (Boost ad-spend) are DIFFERENT units, kept as "
    "separate columns; both are $0 until a pre-invoice feed exists (no feed today, Tim 2026-07-15). "
    "usage_billed/usage_collected/fees are USD and summed across products; collected is refund-"
    "netted, billed is gross; billed_not_collected = billed(gross) − collected(refund-net) = open "
    "invoices + refunded amounts (NOT pure unpaid AR). mgmt_fee_owed = our "
    "commission; net_to_us = mgmt_fee_owed − partner_fee_owed (== monthly_summary.net_owed). "
    "partner_paid_in_month = ps_partner_payouts.amount_paid on the PERFORMANCE month (period_month); "
    "partner_owed_not_paid = partner_fee_owed − partner_paid_in_month (an honest per-period "
    "difference, may go negative on a catch-up payment — NOT the GREATEST(,0) claim figure). "
    "wayward_paid_in_month = ps_payment_events.rev_share_stated (china-scoped) on a PAYMENT/CASH-RECEIVED basis "
    "(payment_date, ~2 months after the usage it settles) — a DIFFERENT time axis than the fee "
    "stages; do not net it against a usage month. The entity-level netting lives in lens_ps_claim "
    "(ps_claim_owed).$c$"
)


def _grant_lens_reads(view: str) -> None:
    for role in (*_READ_ROLES, _READER):
        op.execute(f"GRANT SELECT ON {view} TO {role}")


def upgrade() -> None:
    # Pattern parity with cip_130/131 (harmless here — this migration has NO DML, only DDL/GRANT).
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")

    op.execute(_PIPELINE_VIEW)
    _grant_lens_reads("lens_ps_pipeline")
    op.execute(_VIEW_COMMENT)

    print(
        "cip_132: created lens_ps_pipeline (per-month china follow-a-dollar roll-up; reconciles to "
        "lens_ps_monthly_summary) + reads to the 3 read roles + ps_reporting_reader"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_pipeline")
