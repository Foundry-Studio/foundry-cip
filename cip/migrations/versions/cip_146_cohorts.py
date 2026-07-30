# foundry: kind=migration domain=client-intelligence-platform
"""cip_146 — lens_ps_cohorts: brand retention cohorts (RDL 1.5b, P4a Unit economics).

CLEAN-BUILD-PLAN Phase 1.5b. EXPAND-ONLY. Post-cip_140.

Brand cohort by first_collected_month (the grid anchor) x months_since: per cell, how many brands of
the cohort are STILL collecting (collected > 0) at that month offset, plus the cohort size, both split
referred/direct. Referred = brand has a partner_name on lens_ps_product_eligibility (cip_130). The
EconVM cohorts summary (m3/m6/m12 retention % + m12 referred vs direct) is computed FROM this grid in
the DTO. AC: at months_since = 0 the retained count == the cohort size (every brand is active in its
own first-collected month). NULLIF-guarded. Grant to the read set.

Revision ID: cip_146_cohorts (16 chars <= 32)
Revises: cip_145_concentration
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_146_cohorts"
down_revision: str | Sequence[str] | None = "cip_145_concentration"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_VIEW = r"""
CREATE VIEW lens_ps_cohorts AS
WITH ref AS (SELECT DISTINCT wayward_brand_id FROM lens_ps_product_eligibility WHERE partner_name IS NOT NULL),
grid AS (
    -- offset_m is the PER-ROW cohort offset (month minus first_collected_month), NOT the grid's
    -- months_since column (a per-brand as-of-now constant). This is what a retention cohort needs.
    SELECT g.wayward_brand_id,
           g.first_collected_month AS cohort,
           ( (EXTRACT(YEAR FROM g.month) - EXTRACT(YEAR FROM g.first_collected_month)) * 12
           + (EXTRACT(MONTH FROM g.month) - EXTRACT(MONTH FROM g.first_collected_month)) )::int AS offset_m,
           (g.collected > 0)                 AS active,
           (r.wayward_brand_id IS NOT NULL)  AS referred
    FROM lens_ps_brand_status_grid g
    LEFT JOIN ref r ON r.wayward_brand_id = g.wayward_brand_id
    WHERE g.first_collected_month IS NOT NULL
),
size AS (
    SELECT cohort,
           count(DISTINCT wayward_brand_id)                             AS cohort_size,
           count(DISTINCT wayward_brand_id) FILTER (WHERE referred)     AS cohort_size_referred,
           count(DISTINCT wayward_brand_id) FILTER (WHERE NOT referred) AS cohort_size_direct
    FROM grid GROUP BY cohort
)
SELECT g.cohort,
       g.offset_m AS months_since,
       s.cohort_size,
       s.cohort_size_referred,
       s.cohort_size_direct,
       count(DISTINCT g.wayward_brand_id) FILTER (WHERE g.active)                     AS retained,
       count(DISTINCT g.wayward_brand_id) FILTER (WHERE g.active AND g.referred)      AS retained_referred,
       count(DISTINCT g.wayward_brand_id) FILTER (WHERE g.active AND NOT g.referred)  AS retained_direct,
       round(100.0 * count(DISTINCT g.wayward_brand_id) FILTER (WHERE g.active) / NULLIF(s.cohort_size, 0), 1) AS retained_pct
FROM grid g
JOIN size s ON s.cohort = g.cohort
GROUP BY g.cohort, g.offset_m, s.cohort_size, s.cohort_size_referred, s.cohort_size_direct;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_VIEW)
    op.execute(f'GRANT SELECT ON lens_ps_cohorts TO {_READER};')
    for role in _READ_ROLES:
        op.execute(f'GRANT SELECT ON lens_ps_cohorts TO {role};')
    print("cip_146: lens_ps_cohorts created + granted")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_cohorts;")
