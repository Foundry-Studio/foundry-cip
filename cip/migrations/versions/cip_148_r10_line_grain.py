# foundry: kind=migration domain=client-intelligence-platform
"""cip_148 — R10 line-grain tie-out: sharpen lens_ps_usage_reconciliation residual/tie (RDL 1.5b).

CLEAN-BUILD-PLAN Phase 1.5b R10. LIVE-LENS REPLACE (NOT additive): lens_ps_usage_reconciliation is in
prod (cip_138) with a live HARD-gate consumer — lens_ps_gate_signals binds period/residual/tie/
refund_txns_unposted/unposted_amount (cip_139), feeding lens_ps_close_board + the FAS evaluator.

CONTRACT (frozen, cip_138): the 10 columns stay in EXACT order/type; CREATE OR REPLACE only APPENDS
`unbridged_charges` (11th). The engine/non_base/stripe/refunds_original/posting CTEs are PRESERVED
VERBATIM (refund_txns_unposted/unposted_amount are independent of the charge bridge — the hard
refunds_posted gate is unchanged). ONLY `residual`/`tie` sharpen: from the month-grain
(charges_gross - non_base) proxy to a LINE-GRAIN base-charge computed via the ps_stripe_charges ->
stripe_invoice_id -> invoice bridge: base_charge = charge.amount * (sum base paid $ / NULLIF(sum all
paid $, 0)) per invoice, AMOUNT-weighted, divide-by-zero guarded, UTC month truncation. residual =
engine_collected - base_charges + refunds_original_month (same sign structure as month-grain, sharper
base term). tie tolerance GREATEST($50, 1% engine) + the exact NULL-on-empty-month semantics preserved
(the two-consecutive-ties gate depends on NULL != false). unbridged_charges surfaces charges with no
invoice bridge (181/19,212 live). cip_140=B moves no money, so the residual delta is pure sharpening.

Same PRE/POST rigor as cip_140; downgrade restores the cip_138 body VERBATIM (captured below).

Revision ID: cip_148_r10_line_grain (22 chars <= 32)
Revises: cip_147_email_party_grants
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_148_r10_line_grain"
down_revision: str | Sequence[str] | None = "cip_147_email_party_grants"
branch_labels = None
depends_on = None

# The line-grain rebuild. engine/non_base/stripe/refunds_original/posting are cip_138 VERBATIM; the NEW
# inv_share/base_charge CTEs + the line-grain residual/tie + appended unbridged_charges are the change.
_TIEOUT_V2 = r"""
CREATE OR REPLACE VIEW lens_ps_usage_reconciliation AS
WITH months AS (
    SELECT DISTINCT period_month AS m FROM lens_ps_commission_ledger
    UNION
    SELECT date_trunc('month', (now() AT TIME ZONE 'UTC'))::date
),
engine AS (
    SELECT period_month AS m, round(sum(usage_collected), 2) AS engine_collected
    FROM lens_ps_commission_ledger GROUP BY 1
),
non_base AS (
    SELECT billing_month::date AS m, round(sum(amount), 2) AS non_base_collected
    FROM ps_stripe_invoice_lines
    WHERE NOT is_ps_base AND invoice_status = 'paid' AND billing_month IS NOT NULL
    GROUP BY 1
),
stripe AS (
    SELECT date_trunc('month', txn_created AT TIME ZONE 'UTC')::date AS m,
           round(sum(amount) FILTER (WHERE txn_type IN ('charge', 'payment')), 2)  AS charges_gross,
           round(COALESCE(-sum(amount) FILTER (WHERE txn_type IN ('refund', 'payment_refund')), 0), 2)
                                                                                    AS refunds_txn_month
    FROM ps_stripe_balance_transactions
    WHERE status IN ('available', 'pending')
    GROUP BY 1
),
refunds_original AS (
    SELECT period_month AS m, round(sum(usage_refund_netted), 2) AS refunds_original_month
    FROM lens_ps_refund_allocation GROUP BY 1
),
posting AS (
    SELECT date_trunc('month', bt.txn_created AT TIME ZONE 'UTC')::date AS m,
           count(*) FILTER (WHERE r.stripe_refund_id IS NULL)                 AS refund_txns_unposted,
           round(COALESCE(-sum(bt.amount) FILTER (WHERE r.stripe_refund_id IS NULL), 0), 2)
                                                                              AS unposted_amount
    FROM ps_stripe_balance_transactions bt
    LEFT JOIN ps_stripe_refunds r ON r.stripe_refund_id = bt.source_id
    WHERE bt.txn_type IN ('refund', 'payment_refund')
    GROUP BY 1
),
-- NEW (R10 line-grain): base share of each invoice = base paid $ / all paid $ (amount-weighted).
inv_share AS (
    SELECT stripe_invoice_id,
           sum(amount) FILTER (WHERE is_ps_base) / NULLIF(sum(amount), 0) AS base_share
    FROM ps_stripe_invoice_lines
    WHERE invoice_status = 'paid'
    GROUP BY stripe_invoice_id
),
-- NEW: base portion of charges per month (via the bridge) + unbridged charges (no invoice match).
base_charge AS (
    SELECT date_trunc('month', ch.charge_created AT TIME ZONE 'UTC')::date AS m,
           round(sum(ch.amount * COALESCE(ish.base_share, 0)), 2)                    AS base_charges,
           round(COALESCE(sum(ch.amount) FILTER (WHERE ish.base_share IS NULL), 0), 2) AS unbridged_charges
    FROM ps_stripe_charges ch
    LEFT JOIN inv_share ish ON ish.stripe_invoice_id = ch.stripe_invoice_id
    WHERE ch.status = 'succeeded'
    GROUP BY 1
)
SELECT mo.m                                    AS period,
       COALESCE(e.engine_collected, 0)         AS engine_collected,
       COALESCE(nb.non_base_collected, 0)      AS non_base_collected,
       COALESCE(s.charges_gross, 0)            AS stripe_charges_gross,
       COALESCE(s.refunds_txn_month, 0)        AS stripe_refunds_txn_month,
       COALESCE(ro.refunds_original_month, 0)  AS refunds_original_month,
       COALESCE(p.refund_txns_unposted, 0)     AS refund_txns_unposted,
       COALESCE(p.unposted_amount, 0)          AS unposted_amount,
       -- LINE-GRAIN residual: engine base collected vs the base portion of charges, netting the
       -- engine's original-month refunds. Same sign structure as cip_138; sharper base term.
       round(COALESCE(e.engine_collected, 0) - COALESCE(bc.base_charges, 0)
             + COALESCE(ro.refunds_original_month, 0), 2)                          AS residual,
       -- NULL-on-empty semantics PRESERVED VERBATIM (same signals as cip_138); only the compared
       -- residual sharpens to line-grain.
       CASE WHEN e.engine_collected IS NULL AND s.charges_gross IS NULL
                 AND s.refunds_txn_month IS NULL THEN NULL
            ELSE (abs(COALESCE(e.engine_collected, 0) - COALESCE(bc.base_charges, 0)
                      + COALESCE(ro.refunds_original_month, 0))
                  <= GREATEST(50, 0.01 * abs(COALESCE(e.engine_collected, 0))))
       END                                       AS tie,
       COALESCE(bc.unbridged_charges, 0)       AS unbridged_charges
FROM months mo
LEFT JOIN engine e            ON e.m  = mo.m
LEFT JOIN non_base nb         ON nb.m = mo.m
LEFT JOIN stripe s            ON s.m  = mo.m
LEFT JOIN refunds_original ro ON ro.m = mo.m
LEFT JOIN posting p           ON p.m  = mo.m
LEFT JOIN base_charge bc      ON bc.m = mo.m
"""

# The exact cip_138 body, restored on downgrade (month-grain residual/tie, no unbridged_charges).
_TIEOUT_V1 = r"""
CREATE OR REPLACE VIEW lens_ps_usage_reconciliation AS
WITH months AS (
    SELECT DISTINCT period_month AS m FROM lens_ps_commission_ledger
    UNION
    SELECT date_trunc('month', (now() AT TIME ZONE 'UTC'))::date
),
engine AS (
    SELECT period_month AS m, round(sum(usage_collected), 2) AS engine_collected
    FROM lens_ps_commission_ledger GROUP BY 1
),
non_base AS (
    SELECT billing_month::date AS m, round(sum(amount), 2) AS non_base_collected
    FROM ps_stripe_invoice_lines
    WHERE NOT is_ps_base AND invoice_status = 'paid' AND billing_month IS NOT NULL
    GROUP BY 1
),
stripe AS (
    SELECT date_trunc('month', txn_created AT TIME ZONE 'UTC')::date AS m,
           round(sum(amount) FILTER (WHERE txn_type IN ('charge', 'payment')), 2)  AS charges_gross,
           round(COALESCE(-sum(amount) FILTER (WHERE txn_type IN ('refund', 'payment_refund')), 0), 2)
                                                                                    AS refunds_txn_month
    FROM ps_stripe_balance_transactions
    WHERE status IN ('available', 'pending')
    GROUP BY 1
),
refunds_original AS (
    SELECT period_month AS m, round(sum(usage_refund_netted), 2) AS refunds_original_month
    FROM lens_ps_refund_allocation GROUP BY 1
),
posting AS (
    SELECT date_trunc('month', bt.txn_created AT TIME ZONE 'UTC')::date AS m,
           count(*) FILTER (WHERE r.stripe_refund_id IS NULL)                 AS refund_txns_unposted,
           round(COALESCE(-sum(bt.amount) FILTER (WHERE r.stripe_refund_id IS NULL), 0), 2)
                                                                              AS unposted_amount
    FROM ps_stripe_balance_transactions bt
    LEFT JOIN ps_stripe_refunds r ON r.stripe_refund_id = bt.source_id
    WHERE bt.txn_type IN ('refund', 'payment_refund')
    GROUP BY 1
)
SELECT mo.m                                    AS period,
       COALESCE(e.engine_collected, 0)         AS engine_collected,
       COALESCE(nb.non_base_collected, 0)      AS non_base_collected,
       COALESCE(s.charges_gross, 0)            AS stripe_charges_gross,
       COALESCE(s.refunds_txn_month, 0)        AS stripe_refunds_txn_month,
       COALESCE(ro.refunds_original_month, 0)  AS refunds_original_month,
       COALESCE(p.refund_txns_unposted, 0)     AS refund_txns_unposted,
       COALESCE(p.unposted_amount, 0)          AS unposted_amount,
       round((COALESCE(e.engine_collected, 0) + COALESCE(nb.non_base_collected, 0))
             - COALESCE(s.charges_gross, 0)
             + COALESCE(ro.refunds_original_month, 0), 2)
                                                AS residual,
       CASE WHEN e.engine_collected IS NULL AND s.charges_gross IS NULL
                 AND s.refunds_txn_month IS NULL THEN NULL
            ELSE (abs((COALESCE(e.engine_collected, 0) + COALESCE(nb.non_base_collected, 0))
                      - COALESCE(s.charges_gross, 0)
                      + COALESCE(ro.refunds_original_month, 0))
                  <= GREATEST(50, 0.01 * abs(COALESCE(e.engine_collected, 0))))
       END                                       AS tie
FROM months mo
LEFT JOIN engine e            ON e.m  = mo.m
LEFT JOIN non_base nb         ON nb.m = mo.m
LEFT JOIN stripe s            ON s.m  = mo.m
LEFT JOIN refunds_original ro ON ro.m = mo.m
LEFT JOIN posting p           ON p.m  = mo.m
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_TIEOUT_V2)
    print("cip_148: R10 line-grain residual/tie + unbridged_charges (usage_reconciliation replaced)")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_TIEOUT_V1)
