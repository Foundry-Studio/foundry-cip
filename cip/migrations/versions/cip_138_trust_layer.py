# foundry: kind=migration domain=client-intelligence-platform
"""cip_138 — the trust layer: feed registry (A5), period close (A3/R1), gate signals, R10 tie-out.

CLEAN-BUILD-PLAN v2.2 Phase 3 backend (reports-project-silk; Tim-directed batch 2026-07-29).
EXPAND-ONLY per live-read-lenses.md: every object here is NEW; no live-read lens is touched
(lens_ps_source_freshness v1 keeps serving the deployed build; v2 layers beside it).

1) ps_feed_registry (A5): the blast-radius registry. Seeded self-capturing from the LIVE
   lens_ps_source_freshness names (never guessed), then curated by pattern (owner, cadence,
   threshold_hours, blocks[]) per feed-expectations.md, including the two freshness
   EXCLUSIONS copied out of the old app (FixtureConnector, ASK6 deal-history backfill) and
   the Jake feed as the declared SPOF (R9). Global config table (no tenant column) matching
   the freshness lens it joins.

2) lens_ps_source_freshness_v2: v1 joined to the registry (adds owner, threshold_hours,
   blocks, excluded_from_freshness). Consumers filter excluded rows at source.

3) A3 per R1: ps_periods (close state; open/blocked/closed/restated are DERIVED, never
   stored), ps_period_gates (run_id + evaluated_at per the close staleness rule),
   ps_period_snapshot (VERSIONED: close writes v1; a restatement inserts v(n+1) + a
   ps_period_restatements row in one txn; readers take MAX(version)), ps_period_restatements.
   All four tenant-scoped with ENABLE+FORCE RLS per the cip_131 pattern. Writes go ONLY
   through the governed FAS actions (gate.accept / period.close / period.reopen /
   period.restate); nothing app-side writes these tables.

4) lens_ps_period_state / lens_ps_period_figures / lens_ps_close_board: the derived state
   machine (blocked = any hard gate failing; restated = restatements exist), the
   MAX(version) figure reader (figureForPeriod's source), and the /close screen surface.

5) lens_ps_gate_signals: the evaluator's SQL — all 8 gates computed live for the current
   and prior month (the two closeable candidates). The FAS evaluator job upserts
   ps_period_gates from this view with a fresh run_id; period.close re-checks against it
   server-side. Gate meanings pinned by R10 and the v2.2 contract table; every predicate
   below reads verified columns only.

6) lens_ps_usage_reconciliation (R10, MONTH grain): engine collected vs Stripe balance-txn
   charges net of refunds by txn month, with COMPUTED reconciling columns (cross-month
   refund remap via lens_ps_refund_allocation's original-month axis; refund-posting
   completeness via re_-id membership). GRAIN DEVIATION recorded: the pinned line-grain
   bridge is unbuildable today (ps_stripe_invoices carries no charge_id; only refunds do),
   so the lens ties at month grain; the gate runs SOFT until two consecutive ties and its
   hard-flip is a manual Tim ruling either way (R10).

Reader: every new lens granted to ps_reporting_reader + the full read set (cip_129 ruling).

Apply-time notes: probe the live FAS foreign head immediately before apply (it MOVES);
apply outside :10-:50 UTC; the tables are new so no live lock risk beyond registry seeding.

Revision ID: cip_138_trust_layer (19 chars; alembic_version is VARCHAR(32))
Revises: cip_137_status_bands_rates
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_138_trust_layer"
down_revision: str | Sequence[str] | None = "cip_137_status_bands_rates"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"

_TABLES = r"""
CREATE TABLE ps_feed_registry (
    source                  TEXT PRIMARY KEY,
    owner                   TEXT,
    mode                    TEXT,
    expected_cadence        TEXT,
    threshold_hours         INT,
    blocks                  TEXT[] NOT NULL DEFAULT '{}',
    excluded_from_freshness BOOLEAN NOT NULL DEFAULT false,
    note                    TEXT
);

CREATE TABLE ps_periods (
    tenant_id  UUID NOT NULL,
    period     DATE NOT NULL CHECK (date_trunc('month', period)::date = period),
    closed_by  TEXT,
    closed_at  TIMESTAMPTZ,
    note       TEXT,
    PRIMARY KEY (tenant_id, period)
);

CREATE TABLE ps_period_gates (
    tenant_id       UUID NOT NULL,
    period          DATE NOT NULL,
    gate_key        TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('hard', 'soft')),
    result          TEXT NOT NULL CHECK (result IN ('passing', 'failing', 'review')),
    found           TEXT,
    owner_team      TEXT,
    money_affected  NUMERIC(14,2),
    run_id          UUID NOT NULL,
    evaluated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_by     TEXT,
    accepted_at     TIMESTAMPTZ,
    accepted_note   TEXT,
    PRIMARY KEY (tenant_id, period, gate_key)
);

CREATE TABLE ps_period_snapshot (
    tenant_id      UUID NOT NULL,
    period         DATE NOT NULL,
    figure_key     TEXT NOT NULL,
    version        INT  NOT NULL CHECK (version >= 1),
    value          NUMERIC(14,2),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    restatement_id UUID,
    PRIMARY KEY (tenant_id, period, figure_key, version)
);

CREATE TABLE ps_period_restatements (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    period      DATE NOT NULL,
    figure_key  TEXT NOT NULL,
    from_value  NUMERIC(14,2),
    to_value    NUMERIC(14,2),
    reason      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_STATE = r"""
CREATE VIEW lens_ps_period_state AS
SELECT p.tenant_id,
       p.period,
       p.closed_by,
       p.closed_at,
       CASE
           WHEN p.closed_at IS NULL AND EXISTS (
               SELECT 1 FROM ps_period_gates g
               WHERE g.tenant_id = p.tenant_id AND g.period = p.period
                 AND g.kind = 'hard' AND g.result = 'failing')
               THEN 'blocked'
           WHEN p.closed_at IS NULL THEN 'open'
           WHEN EXISTS (
               SELECT 1 FROM ps_period_restatements r
               WHERE r.tenant_id = p.tenant_id AND r.period = p.period)
               THEN 'restated'
           ELSE 'closed'
       END AS state
FROM ps_periods p
"""

_FIGURES = r"""
CREATE VIEW lens_ps_period_figures AS
SELECT DISTINCT ON (tenant_id, period, figure_key)
       tenant_id, period, figure_key, version, value, created_at,
       (version > 1) AS restated
FROM ps_period_snapshot
ORDER BY tenant_id, period, figure_key, version DESC
"""

_BOARD = r"""
CREATE VIEW lens_ps_close_board AS
SELECT s.tenant_id, s.period, s.state, s.closed_by, s.closed_at,
       g.gate_key, g.kind, g.result, g.found, g.owner_team, g.money_affected,
       g.run_id, g.evaluated_at, g.accepted_by, g.accepted_at, g.accepted_note
FROM lens_ps_period_state s
LEFT JOIN ps_period_gates g
       ON g.tenant_id = s.tenant_id AND g.period = s.period
"""

_TIEOUT = r"""
CREATE VIEW lens_ps_usage_reconciliation AS
WITH months AS (
    SELECT date_trunc('month', CURRENT_DATE)::date AS m
    UNION ALL
    SELECT (date_trunc('month', CURRENT_DATE) - interval '1 month')::date
),
engine AS (
    SELECT period_month AS m, round(sum(usage_collected), 2) AS engine_collected
    FROM lens_ps_commission_ledger GROUP BY 1
),
stripe AS (
    SELECT date_trunc('month', txn_created)::date AS m,
           round(sum(amount) FILTER (WHERE txn_type = 'charge'), 2)              AS charges_gross,
           round(COALESCE(-sum(amount) FILTER (WHERE txn_type = 'refund'), 0), 2) AS refunds_txn_month
    FROM ps_stripe_balance_transactions
    WHERE status IN ('available', 'pending')
    GROUP BY 1
),
refunds_original AS (
    -- the engine nets refunds back into ORIGINAL billing months (cip_113); this is the
    -- cross-month remap reconciling column
    SELECT period_month AS m, round(sum(refunded), 2) AS refunds_original_month
    FROM lens_ps_refund_allocation GROUP BY 1
),
posting AS (
    -- refund-posting completeness: every refund balance-txn (re_) should exist in
    -- ps_stripe_refunds by id
    SELECT date_trunc('month', bt.txn_created)::date AS m,
           count(*) FILTER (WHERE r.stripe_refund_id IS NULL) AS refund_txns_unposted
    FROM ps_stripe_balance_transactions bt
    LEFT JOIN ps_stripe_refunds r ON r.stripe_refund_id = bt.source_id
    WHERE bt.txn_type = 'refund'
    GROUP BY 1
)
SELECT mo.m                                    AS period,
       COALESCE(e.engine_collected, 0)         AS engine_collected,
       COALESCE(s.charges_gross, 0)            AS stripe_charges_gross,
       COALESCE(s.refunds_txn_month, 0)        AS stripe_refunds_txn_month,
       COALESCE(ro.refunds_original_month, 0)  AS refunds_original_month,
       COALESCE(p.refund_txns_unposted, 0)     AS refund_txns_unposted,
       -- month-grain residual AFTER the reconciling items: engine collected is net of
       -- refunds at ORIGINAL month; stripe is charges minus refunds at TXN month; the
       -- (refunds_txn - refunds_original) term remaps the two refund axes so cross-month
       -- refunds stop being false residual. Both raw axes stay exposed for the reviewer.
       round(COALESCE(e.engine_collected, 0)
             - (COALESCE(s.charges_gross, 0) - COALESCE(s.refunds_txn_month, 0))
             + (COALESCE(s.refunds_txn_month, 0) - COALESCE(ro.refunds_original_month, 0)), 2)
                                                AS residual,
       (abs(COALESCE(e.engine_collected, 0)
            - (COALESCE(s.charges_gross, 0) - COALESCE(s.refunds_txn_month, 0))
            + (COALESCE(s.refunds_txn_month, 0) - COALESCE(ro.refunds_original_month, 0)))
        <= GREATEST(50, 0.01 * abs(COALESCE(e.engine_collected, 0)))) AS tie
FROM months mo
LEFT JOIN engine e            ON e.m  = mo.m
LEFT JOIN stripe s            ON s.m  = mo.m
LEFT JOIN refunds_original ro ON ro.m = mo.m
LEFT JOIN posting p           ON p.m  = mo.m
"""

_SIGNALS = r"""
CREATE VIEW lens_ps_gate_signals AS
WITH periods AS (
    SELECT date_trunc('month', CURRENT_DATE)::date AS period
    UNION ALL
    SELECT (date_trunc('month', CURRENT_DATE) - interval '1 month')::date
),
stale AS (
    SELECT source, hours_since, threshold_hours
    FROM lens_ps_source_freshness_v2
    WHERE NOT excluded_from_freshness
      AND threshold_hours IS NOT NULL
      AND hours_since > threshold_hours
),
inv_fail AS (
    SELECT string_agg(check_key, ', ') AS keys, count(*) AS n
    FROM lens_ps_invariants WHERE status = 'fail'
),
tie AS (
    SELECT period, residual, tie, refund_txns_unposted FROM lens_ps_usage_reconciliation
),
cov AS (
    SELECT check_key, pct FROM lens_ps_coverage
),
cont AS (
    SELECT count(*) FILTER (WHERE review_priority = 'high') AS high_n,
           round(sum(usage_collected) FILTER (WHERE review_priority = 'high'), 2) AS high_money
    FROM lens_ps_china_contention
),
rates AS (
    SELECT count(DISTINCT party_id) AS on_default
    FROM ps_partner_rate
    WHERE basis = 'default' AND effective_to IS NULL
),
claim AS (
    SELECT count(*) FILTER (WHERE delta_status = 'unacknowledged_unpaid') AS unack_n,
           round(sum(ps_claim_owed) FILTER (WHERE delta_status = 'unacknowledged_unpaid'), 2) AS unack_money
    FROM lens_ps_wayward_reconciliation
)
SELECT p.period, g.gate_key, g.kind, g.result, g.found, g.owner_team, g.money_affected
FROM periods p
CROSS JOIN LATERAL (
    SELECT 'feeds_current', 'hard',
           CASE WHEN EXISTS (SELECT 1 FROM stale) THEN 'failing' ELSE 'passing' END,
           COALESCE((SELECT 'stale: ' || string_agg(source || ' (' || hours_since || 'h > ' || threshold_hours || 'h)', '; ') FROM stale),
                    'all feeds within threshold'),
           'data', NULL::numeric
    UNION ALL
    SELECT 'invariants_clean', 'hard',
           CASE WHEN (SELECT n FROM inv_fail) > 0 THEN 'failing' ELSE 'passing' END,
           COALESCE((SELECT 'failing: ' || keys FROM inv_fail WHERE n > 0), 'all invariants clean'),
           'data', NULL::numeric
    UNION ALL
    SELECT 'refunds_posted', 'hard',
           CASE WHEN COALESCE((SELECT refund_txns_unposted FROM tie t WHERE t.period = p.period), 0) > 0
                THEN 'failing' ELSE 'passing' END,
           'unposted refund txns in period: ' ||
               COALESCE((SELECT refund_txns_unposted FROM tie t WHERE t.period = p.period), 0),
           'data', NULL::numeric
    UNION ALL
    SELECT 'usage_reconciles', 'soft',
           -- SOFT until two consecutive ties, then a manual Tim ruling flips it hard (R10)
           CASE WHEN COALESCE((SELECT tie FROM tie t WHERE t.period = p.period), false)
                THEN 'passing' ELSE 'review' END,
           'residual after reconciling items: $' ||
               COALESCE((SELECT residual FROM tie t WHERE t.period = p.period), 0),
           'finance', (SELECT abs(residual) FROM tie t WHERE t.period = p.period)
    UNION ALL
    SELECT 'fee_rate_coverage', 'soft',
           CASE WHEN COALESCE((SELECT pct FROM cov WHERE check_key = 'coverage.fee_rate'), 100) >= 98
                THEN 'passing' ELSE 'review' END,
           'client fee-rate coverage (GMV denominator): ' ||
               COALESCE((SELECT pct FROM cov WHERE check_key = 'coverage.fee_rate')::text, 'n/a') || '%',
           'finance', NULL::numeric
    UNION ALL
    SELECT 'nationality_current', 'soft',
           CASE WHEN COALESCE((SELECT high_n FROM cont), 0) > 0 THEN 'review' ELSE 'passing' END,
           'high-priority contention: ' || COALESCE((SELECT high_n FROM cont), 0) ||
               ' brands; nationality coverage ' ||
               COALESCE((SELECT pct FROM cov WHERE check_key = 'coverage.nationality')::text, 'n/a') || '%',
           'cs', (SELECT high_money FROM cont)
    UNION ALL
    SELECT 'partner_rates_on_file', 'soft',
           CASE WHEN COALESCE((SELECT on_default FROM rates), 0) > 0 THEN 'review' ELSE 'passing' END,
           'parties accruing on the uniform default rate: ' || COALESCE((SELECT on_default FROM rates), 0),
           'partners', NULL::numeric
    UNION ALL
    SELECT 'claim_lines_reconciled', 'soft',
           CASE WHEN COALESCE((SELECT unack_n FROM claim), 0) > 0 THEN 'review' ELSE 'passing' END,
           'unacknowledged brands: ' || COALESCE((SELECT unack_n FROM claim), 0),
           'finance', (SELECT unack_money FROM claim)
) AS g(gate_key, kind, result, found, owner_team, money_affected)
"""

_FRESHNESS_V2 = r"""
CREATE VIEW lens_ps_source_freshness_v2 AS
SELECT f.*,
       r.owner,
       r.expected_cadence,
       r.threshold_hours,
       COALESCE(r.blocks, '{}')                    AS blocks,
       COALESCE(r.excluded_from_freshness, false)  AS excluded_from_freshness
FROM lens_ps_source_freshness f
LEFT JOIN ps_feed_registry r ON r.source = f.source
"""

_LENSES = ("lens_ps_source_freshness_v2", "lens_ps_period_state", "lens_ps_period_figures",
           "lens_ps_close_board", "lens_ps_usage_reconciliation", "lens_ps_gate_signals")

_RLS_TABLES = ("ps_periods", "ps_period_gates", "ps_period_snapshot", "ps_period_restatements")

_SEED_CAPTURE = """
    INSERT INTO ps_feed_registry (source, mode)
    SELECT DISTINCT source, mode FROM lens_ps_source_freshness
    ON CONFLICT (source) DO NOTHING
"""

_SEED_CURATE = """
    UPDATE ps_feed_registry SET
        owner = CASE
            WHEN source ILIKE '%jake%' OR source ILIKE '%payment report%' THEN 'Tim (via Jake)'
            ELSE 'engine (data)' END,
        expected_cadence = CASE
            WHEN source ILIKE '%jake%' OR source ILIKE '%payment report%' THEN 'monthly'
            WHEN mode = 'MANUAL' THEN 'manual'
            ELSE 'hourly' END,
        threshold_hours = CASE
            WHEN source ILIKE '%jake%' OR source ILIKE '%payment report%' THEN 840
            WHEN mode = 'MANUAL' THEN NULL
            ELSE 26 END,
        blocks = CASE
            WHEN source ILIKE '%jake%' OR source ILIKE '%payment report%'
                THEN ARRAY['wayward_claim','cash_in','days_to_pay','close.feeds_current','close.claim_lines_reconciled']
            WHEN source ILIKE '%hubspot%'
                THEN ARRAY['brand_book','nationality','partner_attribution','claim_recon']
            WHEN source ILIKE '%zendesk%'
                THEN ARRAY['cs_tickets']
            WHEN source ILIKE '%stripe%'
                THEN ARRAY['revenue','collected','fee_engine','usage_reconciles','collections','refunds']
            WHEN source ILIKE '%mirror%'
                THEN ARRAY['cip_downstream']
            ELSE '{}'::text[] END
"""

_SEED_EXCLUSIONS = """
    INSERT INTO ps_feed_registry (source, mode, excluded_from_freshness, note) VALUES
        ('FixtureConnector', 'scheduled', true, 'test/demo connector; excluded per feed-expectations.md'),
        ('ASK6 deal-history backfill', 'MANUAL', true, 'one-time backfill, finished; excluded per feed-expectations.md')
    ON CONFLICT (source) DO UPDATE
        SET excluded_from_freshness = true, note = EXCLUDED.note
"""


def upgrade() -> None:
    # plan section-2 lock discipline
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")

    op.execute(_TABLES)
    for t in _RLS_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {t}_tenant ON {t} USING ({_PRED}) WITH CHECK ({_PRED})")

    # A5 registry: self-capture the REAL feed names from the live freshness lens, then curate
    op.execute(_SEED_CAPTURE)
    op.execute(_SEED_CURATE)
    op.execute(_SEED_EXCLUSIONS)

    for ddl in (_FRESHNESS_V2, _STATE, _FIGURES, _BOARD, _TIEOUT, _SIGNALS):
        op.execute(ddl)
    for lens in _LENSES:
        op.execute(f'GRANT SELECT ON "{lens}" TO {_READER};')
        for role in _READ_ROLES:
            op.execute(f'GRANT SELECT ON "{lens}" TO {role};')
    print(f"cip_138: trust layer up — registry seeded, 4 RLS tables, {len(_LENSES)} lenses granted")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for lens in reversed(_LENSES):
        op.execute(f'DROP VIEW IF EXISTS "{lens}"')
    for t in reversed(_RLS_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t}")
    op.execute("DROP TABLE IF EXISTS ps_feed_registry")
