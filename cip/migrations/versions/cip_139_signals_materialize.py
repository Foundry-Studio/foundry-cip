# foundry: kind=migration domain=client-intelligence-platform
"""cip_139 — materialize the gate-signals CTEs (41s -> sub-second class).

The cip_138 apply verification measured lens_ps_gate_signals at 41.4s as the reader:
Postgres 12+ inlines non-materialized CTEs, so the heavy tie-out CTE (a full ledger +
balance-txn evaluation) re-ran for EVERY scalar subselect on EVERY period row. This
REPLACEs the view (safe: brand-new lens, zero consumers, not on live-read-lenses.md)
with MATERIALIZED on the seven shared CTEs so each evaluates exactly once per query.
Body otherwise byte-identical to cip_138's _SIGNALS.

Revision ID: cip_139_signals_materialize (28 chars; alembic_version is VARCHAR(32))
Revises: cip_138_trust_layer
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_139_signals_materialize"
down_revision: str | Sequence[str] | None = "cip_138_trust_layer"
branch_labels = None
depends_on = None

_SIGNALS_MAT = r"""
CREATE OR REPLACE VIEW lens_ps_gate_signals AS
WITH periods AS (
    SELECT DISTINCT period_month AS period FROM lens_ps_commission_ledger
    UNION
    SELECT date_trunc('month', (now() AT TIME ZONE 'UTC'))::date
),
stale AS MATERIALIZED (
    SELECT source, hours_since, threshold_hours
    FROM lens_ps_source_freshness_v2
    WHERE NOT excluded_from_freshness
      AND threshold_hours IS NOT NULL
      AND hours_since > threshold_hours
),
inv_fail AS MATERIALIZED (
    SELECT string_agg(check_key, ', ') AS keys, count(*) AS n
    FROM lens_ps_invariants WHERE status = 'fail'
),
tie AS MATERIALIZED (
    SELECT period, residual, tie, refund_txns_unposted, unposted_amount
    FROM lens_ps_usage_reconciliation
),
cov AS MATERIALIZED (
    SELECT check_key, pct FROM lens_ps_coverage
),
cont AS MATERIALIZED (
    SELECT count(*) FILTER (WHERE review_priority = 'high') AS high_n,
           round(sum(usage_collected) FILTER (WHERE review_priority = 'high'), 2) AS high_money
    FROM lens_ps_china_contention
),
rates AS MATERIALIZED (
    SELECT count(DISTINCT party_id) AS on_default
    FROM ps_partner_rate
    WHERE basis = 'default' AND effective_to IS NULL
),
claim AS MATERIALIZED (
    SELECT count(*) FILTER (WHERE delta_status = 'unacknowledged_unpaid') AS unack_n,
           round(sum(ps_claim_owed) FILTER (WHERE delta_status = 'unacknowledged_unpaid'), 2) AS unack_money
    FROM lens_ps_wayward_reconciliation
),
raw AS (
    SELECT p.period, g.gate_key, g.bad, g.found, g.money_affected
    FROM periods p
    CROSS JOIN LATERAL (
        SELECT 'feeds_current',
               EXISTS (SELECT 1 FROM stale),
               COALESCE((SELECT 'stale: ' || string_agg(source || ' (' || hours_since || 'h > ' || threshold_hours || 'h)', '; ') FROM stale),
                        'all feeds within threshold'),
               NULL::numeric
        UNION ALL
        SELECT 'invariants_clean',
               (SELECT n FROM inv_fail) > 0,
               COALESCE((SELECT 'failing: ' || keys FROM inv_fail WHERE n > 0), 'all invariants clean'),
               NULL::numeric
        UNION ALL
        SELECT 'refunds_posted',
               COALESCE((SELECT refund_txns_unposted FROM tie t WHERE t.period = p.period), 0) > 0,
               'unposted refund txns in period: ' ||
                   COALESCE((SELECT refund_txns_unposted FROM tie t WHERE t.period = p.period), 0),
               (SELECT unposted_amount FROM tie t WHERE t.period = p.period)
        UNION ALL
        SELECT 'usage_reconciles',
               NOT COALESCE((SELECT tie FROM tie t WHERE t.period = p.period), false),
               'residual after reconciling items: $' ||
                   COALESCE((SELECT residual FROM tie t WHERE t.period = p.period), 0),
               (SELECT abs(residual) FROM tie t WHERE t.period = p.period)
        UNION ALL
        SELECT 'fee_rate_coverage',
               COALESCE((SELECT pct FROM cov WHERE check_key = 'coverage.fee_rate'), 100) < 98,
               'client fee-rate coverage (GMV denominator): ' ||
                   COALESCE((SELECT pct FROM cov WHERE check_key = 'coverage.fee_rate')::text, 'n/a') || '%',
               NULL::numeric
        UNION ALL
        SELECT 'nationality_current',
               COALESCE((SELECT high_n FROM cont), 0) > 0,
               'high-priority contention: ' || COALESCE((SELECT high_n FROM cont), 0) ||
                   ' brands; nationality coverage ' ||
                   COALESCE((SELECT pct FROM cov WHERE check_key = 'coverage.nationality')::text, 'n/a') || '%',
               (SELECT high_money FROM cont)
        UNION ALL
        SELECT 'partner_rates_on_file',
               COALESCE((SELECT on_default FROM rates), 0) > 0,
               'parties accruing on the uniform default rate: ' || COALESCE((SELECT on_default FROM rates), 0),
               NULL::numeric
        UNION ALL
        SELECT 'claim_lines_reconciled',
               COALESCE((SELECT unack_n FROM claim), 0) > 0,
               'unacknowledged brands: ' || COALESCE((SELECT unack_n FROM claim), 0),
               (SELECT unack_money FROM claim)
    ) AS g(gate_key, bad, found, money_affected)
)
SELECT r.period, r.gate_key,
       pol.kind,
       CASE WHEN NOT r.bad THEN 'passing'
            WHEN pol.kind = 'hard' THEN 'failing'
            ELSE 'review' END AS result,
       r.found,
       pol.owner_team,
       pol.owner_name,
       r.money_affected
FROM raw r
JOIN ps_gate_policy pol ON pol.gate_key = r.gate_key
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_SIGNALS_MAT)
    print("cip_139: gate-signals CTEs materialized")


def downgrade() -> None:
    # reverting to the inlined form is a re-run of cip_138's body; not needed in practice
    pass
