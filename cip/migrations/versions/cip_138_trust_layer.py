# foundry: kind=migration domain=client-intelligence-platform
"""cip_138 — the trust layer: feed registry (A5), period close (A3/R1), gate policy/signals, R10 tie-out.

CLEAN-BUILD-PLAN v2.2 Phase 3 backend (reports-project-silk; Tim-directed batch 2026-07-29).
EXPAND-ONLY per live-read-lenses.md: every object here is NEW; no live-read lens is touched
(lens_ps_source_freshness v1 keeps serving the deployed build; v2 layers beside it).

1) ps_feed_registry (A5): blast-radius registry, seeded self-capturing from the LIVE
   lens_ps_source_freshness names, then curated per feed-expectations.md. Only
   mode='scheduled' feeds get a staleness threshold (26h); manual/on-demand feeds
   (incl. 'ADDED (human knowledge)') get NULL except the Jake payment feed (840h, the
   declared SPOF, R9). The two freshness exclusions move in from the old app.

2) lens_ps_source_freshness_v2: v1 + registry columns (owner, threshold, blocks, excluded).

3) A3 per R1: ps_periods (only closed_by/closed_at stored; open/blocked/closed/restated are
   DERIVED), ps_period_gates (run_id + evaluated_at per the close staleness rule),
   ps_period_snapshot (VERSIONED; close writes v1, re-close after reopen writes v(max+1),
   a restatement inserts v(n+1) + a ps_period_restatements row in one txn; readers take
   MAX(version)), ps_period_restatements. All tenant-scoped ENABLE+FORCE RLS per cip_131.
   Writes go ONLY through the governed FAS actions.

4) ps_gate_policy: gate kind + owner as DATA (8 seeded rows). The R10 soft->hard flip (and
   symmetric downgrade) is a governed FAS write updating ONE policy row with note + audit,
   never a view migration; historical gate rows keep the kind they were evaluated under.
   usage_reconciles seeds SOFT per R10 (kit lists it hard-track; flips manually after two
   consecutive ties). Owners per the v2.2 ruling: Tim default; feeds/invariants = data.

5) ps_figure_catalog: THE frozen figure_key list (R1's "shared constant") as a seeded table
   both the FAS close write and the app reader consume — one source of truth instead of
   mirrored cross-repo constants (deviation-improvement over the plan's wording; echoed to
   the batch report). Chain figures + claim totals + per-product fee/net.

6) lens_ps_period_state / lens_ps_period_figures / lens_ps_close_board: derived state
   (blocked = any hard gate failing; restated = restatements EXIST, per R1 — figures'
   restated flag keys on restatement_id, so reopen+re-close does not misreport),
   MAX(version) figures, and the /close board (gates LEFT JOIN state so pre-first-close
   boards render; state defaults 'open').

7) lens_ps_gate_signals: the evaluator's SQL, ALL LEDGER MONTHS + current (so the oldest
   genuinely closeable historic month is evaluable, per the Phase-3 AC), joined to
   ps_gate_policy for kind/owner; result words derive from the JOINED kind (hard->failing,
   soft->review). FAS evaluator contract (for the builder): upsert ps_period_gates AND
   ps_periods rows for each evaluated period; a new run_id CLEARS accepted_* (a stale
   acceptance must not satisfy close); period.close enforces hard-passing AND
   soft-accepted-with-note AND same-complete-run freshness (6h).

8) lens_ps_usage_reconciliation (R10, MONTH grain): engine base-net collected vs Stripe
   balance-txn charges net of refunds by txn month (UTC-truncated), with BOTH required
   reconciling columns computed: non_base_collected (paid NOT-is_ps_base lines — the
   engine's base-only scope vs Stripe's whole-charge scope) and the cross-month refund
   remap (refunds at txn month vs the engine's original-month netting via
   lens_ps_refund_allocation.usage_refund_netted), plus re_-id posting completeness.
   GRAIN NOTE (corrected by QC): the charge-to-invoice bridge DOES exist
   (ps_stripe_charges.stripe_invoice_id, extras sync); ps_stripe_invoices itself just has
   no charge_id. Month grain ships as the pragmatic v1 (the residual still carries the
   accrual-vs-cash billing-lag term between billing_month and txn month); the R10
   line-grain rebuild on the charges bridge is queued for the P4a backend slice. Gate runs
   SOFT until two consecutive NON-VACUOUS ties (tie is NULL for empty months); hard-flip is
   a manual Tim ruling on ps_gate_policy. All month truncation is pinned UTC (R10).

Reader: every new lens granted to ps_reporting_reader + the full read set (cip_129).

Apply-time notes: probe the live FAS foreign head immediately before apply (it MOVES);
apply outside :10-:50 UTC; run SELECT DISTINCT source, mode FROM lens_ps_source_freshness
first and eyeball the curation match (esp. any balance-txn/extras source name).

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

CREATE TABLE ps_gate_policy (
    gate_key   TEXT PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('hard', 'soft')),
    owner_team TEXT NOT NULL,
    owner_name TEXT NOT NULL DEFAULT 'Tim',
    flipped_by TEXT,
    flipped_at TIMESTAMPTZ,
    note       TEXT
);

CREATE TABLE ps_figure_catalog (
    figure_key  TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    note        TEXT
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
    period          DATE NOT NULL CHECK (date_trunc('month', period)::date = period),
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
    accepted_run_id UUID,
    PRIMARY KEY (tenant_id, period, gate_key)
);

CREATE TABLE ps_period_snapshot (
    tenant_id      UUID NOT NULL,
    period         DATE NOT NULL CHECK (date_trunc('month', period)::date = period),
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
    period      DATE NOT NULL CHECK (date_trunc('month', period)::date = period),
    figure_key  TEXT NOT NULL,
    from_value  NUMERIC(14,2),
    to_value    NUMERIC(14,2),
    reason      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE ps_period_snapshot
    ADD CONSTRAINT fk_snapshot_restatement
    FOREIGN KEY (restatement_id) REFERENCES ps_period_restatements(id);
CREATE INDEX ix_restatements_period ON ps_period_restatements (tenant_id, period);
"""

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
            WHEN mode <> 'scheduled' THEN 'manual/on-demand'
            ELSE 'hourly' END,
        threshold_hours = CASE
            WHEN source ILIKE '%jake%' OR source ILIKE '%payment report%' THEN 840
            WHEN mode <> 'scheduled' THEN NULL
            ELSE 26 END,
        note = CASE
            WHEN source ILIKE '%jake%' OR source ILIKE '%payment report%' THEN 'declared SPOF (R9)'
            ELSE note END,
        blocks = CASE
            WHEN source ILIKE '%jake%' OR source ILIKE '%payment report%'
                THEN ARRAY['wayward_claim','cash_in','days_to_pay']
            WHEN source ILIKE '%balance%' OR source ILIKE '%extras%'
                THEN ARRAY['usage_reconciles']
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

_SEED_POLICY = """
    INSERT INTO ps_gate_policy (gate_key, kind, owner_team, owner_name, note) VALUES
        ('feeds_current',          'hard', 'data',     'engine', 'all non-excluded scheduled feeds within threshold'),
        ('invariants_clean',       'hard', 'data',     'engine', 'lens_ps_invariants all clean'),
        ('refunds_posted',         'hard', 'data',     'engine', 'every refund balance-txn posted to ps_stripe_refunds by re_ id'),
        ('usage_reconciles',       'soft', 'finance',  'Tim',    'R10: SOFT until two consecutive ties, then manual flip on this row'),
        ('fee_rate_coverage',      'soft', 'finance',  'Tim',    'client fee-rate coverage (the GMV denominator)'),
        ('nationality_current',    'soft', 'cs',       'Tim',    'no high-priority contention'),
        ('partner_rates_on_file',  'soft', 'partners', 'Tim',    'no party accruing on the uniform default basis'),
        ('claim_lines_reconciled', 'soft', 'finance',  'Tim',    'no unacknowledged claim brands')
    ON CONFLICT (gate_key) DO NOTHING
"""

_SEED_CATALOG = """
    INSERT INTO ps_figure_catalog (figure_key, source_kind, note) VALUES
        ('usage_billed',            'chain', 'lens_ps_pipeline.usage_billed for the period'),
        ('collected',               'chain', 'lens_ps_pipeline.collected for the period'),
        ('fee_earned',              'chain', 'lens_ps_pipeline mgmt fee for the period'),
        ('partner_share',           'chain', 'lens_ps_pipeline partner fee for the period'),
        ('net_kept',                'chain', 'lens_ps_pipeline net_to_us for the period'),
        ('claim_still_owed',        'claim', 'lens_ps_claim sum(ps_claim_owed) as of close'),
        ('claim_earned',            'claim', 'lens_ps_claim sum(mgmt_fee_owed) as of close'),
        ('claim_paid',              'claim', 'lens_ps_claim sum(wayward_paid) as of close'),
        ('claim_overpaid',          'claim', 'per the footing bridge as of close'),
        ('claim_refund_adjustment', 'claim', 'per the footing bridge as of close'),
        ('fee_earned_connect',      'per_product', 'monthly_summary fee, product connect'),
        ('fee_earned_boosted',      'per_product', 'monthly_summary fee, product boosted'),
        ('net_kept_connect',        'per_product', 'monthly_summary net, product connect'),
        ('net_kept_boosted',        'per_product', 'monthly_summary net, product boosted')
    ON CONFLICT (figure_key) DO NOTHING
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

_STATE = r"""
CREATE VIEW lens_ps_period_state AS
-- spine = periods UNION gate periods, so the board is never blind before the first close
WITH spine AS (
    SELECT tenant_id, period FROM ps_periods
    UNION
    SELECT tenant_id, period FROM ps_period_gates
)
SELECT sp.tenant_id,
       sp.period,
       p.closed_by,
       p.closed_at,
       CASE
           WHEN p.closed_at IS NULL AND EXISTS (
               SELECT 1 FROM ps_period_gates g
               WHERE g.tenant_id = sp.tenant_id AND g.period = sp.period
                 AND g.kind = 'hard' AND g.result = 'failing')
               THEN 'blocked'
           WHEN p.closed_at IS NULL THEN 'open'
           WHEN EXISTS (
               SELECT 1 FROM ps_period_restatements r
               WHERE r.tenant_id = sp.tenant_id AND r.period = sp.period)
               THEN 'restated'
           ELSE 'closed'
       END AS state
FROM spine sp
LEFT JOIN ps_periods p ON p.tenant_id = sp.tenant_id AND p.period = sp.period
"""

_RESTATEMENT_LOG = r"""
CREATE VIEW lens_ps_restatement_log AS
SELECT id, tenant_id, period, figure_key, from_value, to_value, reason, actor, detected_at
FROM ps_period_restatements
"""

_FIGURES = r"""
CREATE VIEW lens_ps_period_figures AS
SELECT DISTINCT ON (tenant_id, period, figure_key)
       tenant_id, period, figure_key, version, value, created_at,
       (restatement_id IS NOT NULL) AS restated
FROM ps_period_snapshot
ORDER BY tenant_id, period, figure_key, version DESC
"""

_BOARD = r"""
CREATE VIEW lens_ps_close_board AS
SELECT g.tenant_id, g.period,
       COALESCE(s.state, 'open') AS state,
       s.closed_by, s.closed_at,
       g.gate_key, g.kind, g.result, g.found, g.owner_team, g.money_affected,
       g.run_id, g.evaluated_at, g.accepted_by, g.accepted_at, g.accepted_note
FROM ps_period_gates g
LEFT JOIN lens_ps_period_state s
       ON s.tenant_id = g.tenant_id AND s.period = g.period
"""

_TIEOUT = r"""
CREATE VIEW lens_ps_usage_reconciliation AS
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
    -- R10 reconciling column 1: Stripe charges settle WHOLE invoices; the engine scope is
    -- is_ps_base only. Paid non-base line collected, at the lines' billing_month axis.
    SELECT billing_month::date AS m, round(sum(amount), 2) AS non_base_collected
    FROM ps_stripe_invoice_lines
    WHERE NOT is_ps_base AND invoice_status = 'paid' AND billing_month IS NOT NULL
    GROUP BY 1
),
stripe AS (
    -- 'payment' = PaymentIntent py_ txns; 'payment_refund' their refunds (extras sync doc)
    SELECT date_trunc('month', txn_created AT TIME ZONE 'UTC')::date AS m,
           round(sum(amount) FILTER (WHERE txn_type IN ('charge', 'payment')), 2)  AS charges_gross,
           round(COALESCE(-sum(amount) FILTER (WHERE txn_type IN ('refund', 'payment_refund')), 0), 2)
                                                                                    AS refunds_txn_month
    FROM ps_stripe_balance_transactions
    WHERE status IN ('available', 'pending')
    GROUP BY 1
),
refunds_original AS (
    -- R10 reconciling column 2: the engine nets refunds into ORIGINAL billing months
    SELECT period_month AS m, round(sum(usage_refund_netted), 2) AS refunds_original_month
    FROM lens_ps_refund_allocation GROUP BY 1
),
posting AS (
    -- refund-posting completeness by re_ id, with the unposted MONEY for the gate
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
       -- residual after BOTH reconciling items. Sign PROVEN by QC's worked example (a
       -- cross-month refund must cancel to 0, not double): the remap term is SUBTRACTED,
       -- collapsing to engine + non_base - charges_gross + refunds_original.
       round((COALESCE(e.engine_collected, 0) + COALESCE(nb.non_base_collected, 0))
             - COALESCE(s.charges_gross, 0)
             + COALESCE(ro.refunds_original_month, 0), 2)
                                                AS residual,
       -- tie is NULL (unknown, not vacuously true) when the month has no data on either
       -- axis, so empty months can never feed the two-consecutive-ties evidence
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

_SIGNALS = r"""
CREATE VIEW lens_ps_gate_signals AS
WITH periods AS (
    SELECT DISTINCT period_month AS period FROM lens_ps_commission_ledger
    UNION
    SELECT date_trunc('month', (now() AT TIME ZONE 'UTC'))::date
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
    SELECT period, residual, tie, refund_txns_unposted, unposted_amount
    FROM lens_ps_usage_reconciliation
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

_LENSES = ("lens_ps_source_freshness_v2", "lens_ps_period_state", "lens_ps_period_figures",
           "lens_ps_close_board", "lens_ps_restatement_log",
           "lens_ps_usage_reconciliation", "lens_ps_gate_signals")

_RLS_TABLES = ("ps_periods", "ps_period_gates", "ps_period_snapshot", "ps_period_restatements")


def upgrade() -> None:
    # plan section-2 lock discipline
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")

    op.execute(_TABLES)
    for t in _RLS_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY cip_tenant_scope ON {t} USING ({_PRED}) WITH CHECK ({_PRED})")
        # the governed FAS writer (least-privilege path; cip_131 precedent). No DELETE:
        # nothing in the four write contracts deletes.
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {t} TO ps_reporting_writer")

    op.execute(_SEED_CAPTURE)
    op.execute(_SEED_CURATE)
    op.execute(_SEED_EXCLUSIONS)
    op.execute(_SEED_POLICY)
    op.execute(_SEED_CATALOG)

    for ddl in (_FRESHNESS_V2, _STATE, _RESTATEMENT_LOG, _FIGURES, _BOARD, _TIEOUT, _SIGNALS):
        op.execute(ddl)
    for lens in _LENSES:
        op.execute(f'GRANT SELECT ON "{lens}" TO {_READER};')
        for role in _READ_ROLES:
            op.execute(f'GRANT SELECT ON "{lens}" TO {role};')
    print(f"cip_138: trust layer up — registry+policy+catalog seeded, 4 RLS tables, {len(_LENSES)} lenses granted")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for lens in reversed(_LENSES):
        op.execute(f'DROP VIEW IF EXISTS "{lens}"')
    for t in reversed(_RLS_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t}")
    op.execute("DROP TABLE IF EXISTS ps_figure_catalog")
    op.execute("DROP TABLE IF EXISTS ps_gate_policy")
    op.execute("DROP TABLE IF EXISTS ps_feed_registry")
