# foundry: kind=migration domain=client-intelligence-platform
"""cip_137 — brand status model (R5), invoice day bands v2, partner-rate basis vocabulary.

CLEAN-BUILD-PLAN v2.2 Phase 0 items 1, 3, 4a (reports-project-silk). EXPAND-ONLY per
live-read-lenses.md: every view here is NEW (no live-read lens is replaced or reshaped;
lens_ps_open_invoices_v2 LAYERS OVER v1, which keeps serving the deployed build untouched).

1) lens_ps_brand_status_grid / lens_ps_brand_status / lens_ps_brand_movement — the R5
   month-grain MECE state machine over ledger collected money (refund-netted), computed on a
   generate_series brand-month spine (the ledger is sparse: months with no billing have no
   rows). States per month with precedence: churned (6+ months no collected) > dormant (3-5)
   > new (first-ever collected month) > producing (collected this month, has a prior
   collected month) > quiet (last collected 1-2 months ago). Flags, not states:
   re_engaged (producing after 3+ empty months), at_risk_trend (producing, MoM down 50%+,
   COMPLETE months only — the current partial month never flags).
   Restatement caveat (honest limit of a memoryless view): a refund reallocation restates
   history in place, so states/movement can shift between reads INCLUDING mid-month
   demotions; cross-snapshot protection arrives with A3 period-close. The consuming screens
   carry that footnote (R5 rules it lives on-screen, not here).
   SUBSUMES lens_ps_china_brands_producing for all NEW code ("producing", one definition);
   that lens is retired at cutover via the Phase-7 checklist, not here.
   Population note: brands with zero collected-ever have NO rows here (no state); Brand book
   LEFT JOINs and renders "no billing history".

2) lens_ps_open_invoices_v2 — v1 + the design's day bands (0_30/31_60/61_90/90_plus) as
   day_band. THE invoice-status vocabulary source for every new screen (Brand 360 +
   Collections read the same lens; the two-sides aging separation stands: customer-side day
   bands here, our-side claim aging untouched in lens_ps_ar_aging).

3) ps_partner_rate.basis vocabulary — agreed | default (BUILD-LIST D4/A9; plan Phase 0 item
   4a): the uniform backfill rows are honestly 'default'; the FAS set_rate write (staged
   separately for review) writes 'agreed'. The fee engine reads rate_pct via the cip_131
   COALESCE and never reads basis, so this relabel changes no money.

Reader: explicit GRANT SELECT per the cip_123/cip_125 pattern (views run as owner; nested
reads resolve under owner privileges; the reader needs the top-level lens only).

Apply-time notes: probe the live FAS foreign head for FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS
immediately before apply (it MOVES); apply outside :10-:50 UTC (sync windows); probe
SELECT DISTINCT basis FROM ps_partner_rate first (an unexpected value aborts at the CHECK).
at_risk_trend is gated to COMPLETE months (an MTD-vs-full-prior-month comparison would flag
nearly every producing brand early in a month); the current-month row always reads false.

Revision ID: cip_137_status_bands_rates (26 chars; alembic_version is VARCHAR(32))
Revises: cip_136_perf_indexes
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

revision: str = "cip_137_status_bands_rates"
down_revision: str | Sequence[str] | None = "cip_136_perf_indexes"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"

_GRID = r"""
CREATE VIEW lens_ps_brand_status_grid AS
WITH collected AS (
    SELECT wayward_brand_id,
           period_month,
           SUM(usage_collected) AS collected
    FROM lens_ps_commission_ledger
    GROUP BY wayward_brand_id, period_month
),
bounds AS (
    SELECT wayward_brand_id,
           MIN(period_month) FILTER (WHERE collected > 0) AS first_collected_month
    FROM collected
    GROUP BY wayward_brand_id
),
spine AS (
    SELECT b.wayward_brand_id,
           gs::date AS month,
           b.first_collected_month
    FROM bounds b
    CROSS JOIN LATERAL generate_series(
        b.first_collected_month,
        date_trunc('month', CURRENT_DATE)::date,
        interval '1 month'
    ) gs
    WHERE b.first_collected_month IS NOT NULL
),
joined AS (
    SELECT s.wayward_brand_id,
           s.month,
           s.first_collected_month,
           COALESCE(c.collected, 0) AS collected,
           MAX(CASE WHEN COALESCE(c.collected, 0) > 0 THEN s.month END)
               OVER (PARTITION BY s.wayward_brand_id ORDER BY s.month
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS last_collected_month,
           LAG(COALESCE(c.collected, 0)) OVER (PARTITION BY s.wayward_brand_id ORDER BY s.month) AS prev_collected
    FROM spine s
    LEFT JOIN collected c
           ON c.wayward_brand_id = s.wayward_brand_id AND c.period_month = s.month
),
gap AS (
    SELECT *,
           -- exact for first-of-month DATEs (the sync writer builds billing_month via
           -- strptime('%B %Y').date(), so every period_month is day 1)
           ((EXTRACT(year  FROM month) - EXTRACT(year  FROM last_collected_month)) * 12
          + (EXTRACT(month FROM month) - EXTRACT(month FROM last_collected_month)))::int AS months_since,
           -- the month of the PREVIOUS collected month strictly before this row (for re_engaged)
           MAX(CASE WHEN collected > 0 THEN month END)
               OVER (PARTITION BY wayward_brand_id ORDER BY month
                     ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_collected_month
    FROM joined
)
SELECT wayward_brand_id,
       month,
       collected::numeric(14,2)                                   AS collected,
       first_collected_month,
       last_collected_month,
       months_since,
       CASE
           WHEN collected > 0 AND month = first_collected_month   THEN 'new'
           WHEN collected > 0                                     THEN 'producing'
           WHEN months_since >= 6                                 THEN 'churned'
           WHEN months_since >= 3                                 THEN 'dormant'
           ELSE 'quiet'
       END                                                        AS state,
       (collected > 0
        AND prev_collected_month IS NOT NULL
        AND ((EXTRACT(year  FROM month) - EXTRACT(year  FROM prev_collected_month)) * 12
           + (EXTRACT(month FROM month) - EXTRACT(month FROM prev_collected_month)))::int >= 4)
                                                                  AS re_engaged,
       (collected > 0
        AND COALESCE(prev_collected, 0) > 0
        AND collected <= 0.5 * prev_collected
        AND month < date_trunc('month', CURRENT_DATE)::date)      AS at_risk_trend
FROM gap
"""

_CURRENT = r"""
CREATE VIEW lens_ps_brand_status AS
SELECT DISTINCT ON (wayward_brand_id)
       wayward_brand_id, month, collected, first_collected_month, last_collected_month,
       months_since, state, re_engaged, at_risk_trend
FROM lens_ps_brand_status_grid
ORDER BY wayward_brand_id, month DESC
"""

_MOVEMENT = r"""
CREATE VIEW lens_ps_brand_movement AS
-- monthly movement EVENTS (added / re_engaged / churn-entries); net is an event balance,
-- not a producing-base walk (a 4-5 month gap re-engager adds +1 with no prior -1)
WITH transitions AS (
    SELECT month,
           state,
           re_engaged,
           LAG(state) OVER (PARTITION BY wayward_brand_id ORDER BY month) AS prev_state
    FROM lens_ps_brand_status_grid
)
SELECT month,
       COUNT(*) FILTER (WHERE state = 'new')                                          AS added,
       COUNT(*) FILTER (WHERE re_engaged)                                             AS re_engaged,
       COUNT(*) FILTER (WHERE state = 'churned' AND prev_state IS DISTINCT FROM 'churned') AS churned,
       (COUNT(*) FILTER (WHERE state = 'new')
      + COUNT(*) FILTER (WHERE re_engaged)
      - COUNT(*) FILTER (WHERE state = 'churned' AND prev_state IS DISTINCT FROM 'churned'))::int AS net
FROM transitions
GROUP BY month
"""

_INVOICES_V2 = r"""
CREATE VIEW lens_ps_open_invoices_v2 AS
SELECT v1.*,
       CASE
           WHEN v1.aging_bucket = 'unknown' THEN 'unknown'
           WHEN v1.days_outstanding <= 30 THEN '0_30'
           WHEN v1.days_outstanding <= 60 THEN '31_60'
           WHEN v1.days_outstanding <= 90 THEN '61_90'
           ELSE '90_plus'
       END AS day_band
FROM lens_ps_open_invoices v1
"""

_LENSES = ("lens_ps_brand_status_grid", "lens_ps_brand_status",
           "lens_ps_brand_movement", "lens_ps_open_invoices_v2")

# cip_129 ruling (Tim 2026-07-24): reporting lenses are visible to the FULL read set,
# not app-only — else Metabase/query/twenty drift re-opens.
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # plan section-2 lock discipline: fail fast behind app reads, never queue
    op.execute("SET LOCAL lock_timeout = '5s'")
    for ddl in (_GRID, _CURRENT, _MOVEMENT, _INVOICES_V2):
        op.execute(ddl)
    for lens in _LENSES:
        op.execute(f'GRANT SELECT ON "{lens}" TO {_READER};')
        for role in _READ_ROLES:
            op.execute(f'GRANT SELECT ON "{lens}" TO {role};')

    # BUILD-LIST D4/A9: basis vocabulary. The backfill rows are honestly 'default'; the
    # engine never reads basis (money unchanged). CHECK permits NULL for legacy safety.
    # ps_partner_rate has FORCE RLS (cip_131): set the tenant GUC per its precedent.
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")
    op.execute("UPDATE ps_partner_rate SET basis = 'default' WHERE basis = 'backfill_uniform'")
    op.execute(
        "ALTER TABLE ps_partner_rate ADD CONSTRAINT ck_partner_rate_basis "
        "CHECK (basis IS NULL OR basis IN ('agreed', 'default'))"
    )
    print(f"cip_137: created + granted {len(_LENSES)} lenses to {_READER}; partner-rate basis vocabulary set")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE ps_partner_rate DROP CONSTRAINT IF EXISTS ck_partner_rate_basis")
    # revert ONLY the cip_131-backfill relabel; future FAS 'agreed' rows stay untouched
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")
    op.execute("UPDATE ps_partner_rate SET basis = 'backfill_uniform' "
               "WHERE basis = 'default' AND set_by = 'backfill:cip_131'")
    for lens in reversed(_LENSES):
        op.execute(f'DROP VIEW IF EXISTS "{lens}"')
