# foundry: kind=migration domain=client-intelligence-platform
"""cip_144 — lens_ps_fee_at_risk: per-brand fee tagged with its risk cause(s) (RDL 1.5b, P4a).

CLEAN-BUILD-PLAN Phase 1.5b. EXPAND-ONLY. Post-cip_140 data.

Per brand (anchored on the UNION of at-risk brands so none is dropped), the brand's lifetime mgmt_fee
tagged with the FOUR EconVM causes (a brand may carry several; deduped — the fee is counted ONCE, the
causes listed): overdue_90 (an open_invoices_v2 invoice in the 90_plus day_band), in_contention (in
lens_ps_china_contention), at_risk_or_dormant (grid at_risk_trend IS TRUE OR state='dormant'), no_rate
(rate_clock productive_date IS NULL — no rate anchor). Emits boolean flags + a causes[] array. Only
brands with >=1 cause appear. Also feeds the R7 attention queue (Home). Every ratio NULLIF-guarded.
DELEGATED: fee_at_risk = lifetime sum(mgmt_fee_owed) per brand (the fee that brand represents); the
DTO/screen may window it. Grant to the read set.

Revision ID: cip_144_fee_at_risk (20 chars <= 32)
Revises: cip_143_contribution
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_144_fee_at_risk"
down_revision: str | Sequence[str] | None = "cip_143_contribution"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_VIEW = r"""
CREATE VIEW lens_ps_fee_at_risk AS
WITH fee AS (
    SELECT wayward_brand_id, sum(mgmt_fee_owed) AS mgmt_fee
    FROM lens_ps_commission_ledger GROUP BY wayward_brand_id
),
overdue    AS (SELECT DISTINCT wayward_brand_id FROM lens_ps_open_invoices_v2 WHERE day_band = '90_plus'),
contention AS (SELECT DISTINCT wayward_brand_id FROM lens_ps_china_contention),
atrisk     AS (SELECT DISTINCT wayward_brand_id FROM lens_ps_brand_status_grid WHERE at_risk_trend IS TRUE OR state = 'dormant'),
norate     AS (SELECT DISTINCT wayward_brand_id FROM lens_ps_rate_clock WHERE productive_date IS NULL),
at_risk_brands AS (
    SELECT wayward_brand_id FROM overdue
    UNION SELECT wayward_brand_id FROM contention
    UNION SELECT wayward_brand_id FROM atrisk
    UNION SELECT wayward_brand_id FROM norate
)
SELECT ab.wayward_brand_id,
       bh.brand_name,
       round(COALESCE(f.mgmt_fee, 0), 2) AS fee_at_risk,
       (o.wayward_brand_id  IS NOT NULL) AS overdue_90,
       (c.wayward_brand_id  IS NOT NULL) AS in_contention,
       (a.wayward_brand_id  IS NOT NULL) AS at_risk_or_dormant,
       (nr.wayward_brand_id IS NOT NULL) AS no_rate,
       array_remove(ARRAY[
           CASE WHEN o.wayward_brand_id  IS NOT NULL THEN 'overdue_90' END,
           CASE WHEN c.wayward_brand_id  IS NOT NULL THEN 'in_contention' END,
           CASE WHEN a.wayward_brand_id  IS NOT NULL THEN 'at_risk_or_dormant' END,
           CASE WHEN nr.wayward_brand_id IS NOT NULL THEN 'no_rate' END
       ], NULL) AS causes
FROM at_risk_brands ab
LEFT JOIN lens_ps_brand_header bh ON bh.wayward_brand_id = ab.wayward_brand_id
LEFT JOIN fee f       ON f.wayward_brand_id  = ab.wayward_brand_id
LEFT JOIN overdue o   ON o.wayward_brand_id  = ab.wayward_brand_id
LEFT JOIN contention c ON c.wayward_brand_id = ab.wayward_brand_id
LEFT JOIN atrisk a    ON a.wayward_brand_id  = ab.wayward_brand_id
LEFT JOIN norate nr   ON nr.wayward_brand_id = ab.wayward_brand_id;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_VIEW)
    op.execute(f'GRANT SELECT ON lens_ps_fee_at_risk TO {_READER};')
    for role in _READ_ROLES:
        op.execute(f'GRANT SELECT ON lens_ps_fee_at_risk TO {role};')
    print("cip_144: lens_ps_fee_at_risk created + granted")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_fee_at_risk;")
