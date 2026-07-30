# foundry: kind=migration domain=client-intelligence-platform
"""cip_143 — lens_ps_contribution: per-month fee split by state bucket (RDL 1.5b, P4a Unit economics).

CLEAN-BUILD-PLAN Phase 1.5b. EXPAND-ONLY. Built on POST-cip_140 data (inherits the money decision).

Shared join rule (QC S2): the status grid is per (brand, month) with `collected` and NO fee; the
ledger is per (brand, product, month). So pre-aggregate ledger mgmt_fee_owed/partner_fee_owed to
(brand, month) FIRST, then LEFT JOIN the grid on (brand, month) — never grid->ledger directly (fans
out by product). Per period_month, split sum(mgmt_fee) across the state buckets. The buckets PARTITION
cleanly (each brand-month in exactly one): re_engaged (the flag) | new (state='new', not re_engaged) |
producing (state='producing', not re_engaged) | other (quiet/dormant/churned residual, not re_engaged).
AC: new + re_engaged + producing + other == total_fee (NULLIF/COALESCE guarded). Also emits partner_fee
+ net_kept for the Unit-economics chain. Grant to the reporting read set.

Revision ID: cip_143_contribution (21 chars <= 32)
Revises: cip_142_nationality_trail
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_143_contribution"
down_revision: str | Sequence[str] | None = "cip_142_nationality_trail"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_VIEW = r"""
CREATE VIEW lens_ps_contribution AS
WITH fee AS (
    SELECT wayward_brand_id, period_month,
           sum(mgmt_fee_owed)    AS mgmt_fee,
           sum(partner_fee_owed) AS partner_fee
    FROM lens_ps_commission_ledger
    GROUP BY wayward_brand_id, period_month
),
gf AS (
    SELECT g.month AS period_month, g.state, g.re_engaged,
           COALESCE(fee.mgmt_fee, 0)    AS mgmt_fee,
           COALESCE(fee.partner_fee, 0) AS partner_fee
    FROM lens_ps_brand_status_grid g
    LEFT JOIN fee ON fee.wayward_brand_id = g.wayward_brand_id AND fee.period_month = g.month
)
SELECT period_month,
       round(sum(mgmt_fee), 2)                                                                     AS total_fee,
       round(sum(mgmt_fee) FILTER (WHERE re_engaged), 2)                                           AS re_engaged_fee,
       round(sum(mgmt_fee) FILTER (WHERE state = 'new'      AND NOT re_engaged), 2)                AS new_fee,
       round(sum(mgmt_fee) FILTER (WHERE state = 'producing' AND NOT re_engaged), 2)               AS producing_fee,
       round(sum(mgmt_fee) FILTER (WHERE state NOT IN ('new','producing') AND NOT re_engaged), 2)  AS other_fee,
       round(sum(partner_fee), 2)                                                                  AS partner_fee,
       round(sum(mgmt_fee) - sum(partner_fee), 2)                                                  AS net_kept,
       CASE WHEN sum(mgmt_fee) = 0 THEN NULL
            ELSE round(100.0 * (sum(mgmt_fee) - sum(partner_fee)) / NULLIF(sum(mgmt_fee), 0), 1) END AS net_kept_margin_pct
FROM gf
GROUP BY period_month;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_VIEW)
    op.execute(f'GRANT SELECT ON lens_ps_contribution TO {_READER};')
    for role in _READ_ROLES:
        op.execute(f'GRANT SELECT ON lens_ps_contribution TO {role};')
    print("cip_143: lens_ps_contribution created + granted")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_contribution;")
