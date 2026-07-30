# foundry: kind=migration domain=client-intelligence-platform
"""cip_145 — lens_ps_concentration: per-month book concentration (RDL 1.5b, P4a Unit economics).

CLEAN-BUILD-PLAN Phase 1.5b. EXPAND-ONLY. Post-cip_140.

Per period_month, per the EconVM concentration object: top_brand_share_pct + top5_share_pct (brand
share of COLLECTED, from the status grid), referred_share_of_book_pct (referred GMV / total GMV) and
top3_partner_share_of_referred_gmv_pct (partner-level over REFERRED GMV). Two DIFFERENT bases, each
stated in its column name: collected (grid) for the brand shares, GMV (brand_revenue revenue_type=gmv)
for the referred/partner shares. Referred = brand-product with a partner_name on
lens_ps_product_eligibility (cip_130). All ratios NULLIF-guarded. AC: shares monotone
(top_brand <= top5), all <= 100. Grant to the read set.

Revision ID: cip_145_concentration (21 chars <= 32)
Revises: cip_144_fee_at_risk
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_145_concentration"
down_revision: str | Sequence[str] | None = "cip_144_fee_at_risk"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_VIEW = r"""
CREATE VIEW lens_ps_concentration AS
WITH coll AS (
    SELECT month AS period_month, wayward_brand_id, collected
    FROM lens_ps_brand_status_grid WHERE collected > 0
),
ranked AS (
    SELECT period_month, collected,
           row_number() OVER (PARTITION BY period_month ORDER BY collected DESC) AS rn,
           sum(collected) OVER (PARTITION BY period_month) AS tot
    FROM coll
),
conc AS (
    SELECT period_month,
           round(max(collected) FILTER (WHERE rn = 1) / NULLIF(max(tot), 0) * 100, 1) AS top_brand_share_pct,
           round(sum(collected) FILTER (WHERE rn <= 5) / NULLIF(max(tot), 0) * 100, 1) AS top5_share_pct
    FROM ranked GROUP BY period_month
),
gmv AS (
    SELECT br.period_month, br.wayward_brand_id,
           sum(br.revenue_amount)          AS gmv,
           bool_or(pe.partner_name IS NOT NULL) AS referred,
           max(pe.partner_name)            AS partner
    FROM lens_ps_brand_revenue br
    LEFT JOIN lens_ps_product_eligibility pe
      ON pe.wayward_brand_id = br.wayward_brand_id AND pe.product_id = br.product_id
    WHERE br.revenue_type = 'gmv'
    GROUP BY br.period_month, br.wayward_brand_id
),
refshare AS (
    SELECT period_month,
           round(sum(gmv) FILTER (WHERE referred) / NULLIF(sum(gmv), 0) * 100, 1) AS referred_share_of_book_pct
    FROM gmv GROUP BY period_month
),
partner_gmv AS (
    SELECT period_month, partner, sum(gmv) AS pgmv,
           row_number() OVER (PARTITION BY period_month ORDER BY sum(gmv) DESC) AS prn,
           sum(sum(gmv)) OVER (PARTITION BY period_month) AS ref_tot
    FROM gmv WHERE referred AND partner IS NOT NULL
    GROUP BY period_month, partner
),
top3p AS (
    SELECT period_month,
           round(sum(pgmv) FILTER (WHERE prn <= 3) / NULLIF(max(ref_tot), 0) * 100, 1) AS top3_partner_share_of_referred_gmv_pct
    FROM partner_gmv GROUP BY period_month
)
SELECT c.period_month,
       c.top_brand_share_pct,
       c.top5_share_pct,
       rs.referred_share_of_book_pct,
       t3.top3_partner_share_of_referred_gmv_pct
FROM conc c
LEFT JOIN refshare rs ON rs.period_month = c.period_month
LEFT JOIN top3p t3    ON t3.period_month = c.period_month;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_VIEW)
    op.execute(f'GRANT SELECT ON lens_ps_concentration TO {_READER};')
    for role in _READ_ROLES:
        op.execute(f'GRANT SELECT ON lens_ps_concentration TO {role};')
    print("cip_145: lens_ps_concentration created + granted")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_concentration;")
