"""cip_160 wayward indicators lens (CDP BE-3)

lens_ps_wayward_indicators: does Wayward's OWN data flag this brand china? One row per brand with
>=1 china-pointing signal from a WAYWARD-INDICATOR source (slack brand-connections, intake wechat,
chinese-partner referral, their HubSpot, their exports, the contract Exhibit A exclusion list, Eric's
sheet). Boolean always-true in-lens (absence=false, resolved downstream via LEFT JOIN). Classify by
SOURCE not signal-name (wayward_country_cn leaks from stripe:address_country); guard points_to='china'
(wayward_country_other points not_china). Additive sibling view; grants to the 5 reader roles.
Tim-resolved BROAD wayward-indicator source list (CDP 2026-08-06); under this list the just_pay pool
= 1,043.

Revision ID: cip_160_wayward_indicators
Revises: cip_159_wayward_acknowledgment
Create Date: 2026-08-06
"""
from alembic import op

revision = "cip_160_wayward_indicators"
down_revision = "cip_159_wayward_acknowledgment"
branch_labels = None
depends_on = None

_READ_ROLES = (
    "ps_reporting_reader",
    "cip_query_reader",
    "cip_metabase_project_silk",
    "cip_twenty_project_silk",
    "metabase_reader_foundry",
)

_VIEW_SQL = """
CREATE OR REPLACE VIEW lens_ps_wayward_indicators AS
SELECT
    s.wayward_brand_id,
    true AS wayward_indicates_china,
    array_agg(DISTINCT s.source_system ORDER BY s.source_system) AS indicator_sources,
    (ARRAY['definitional','strong','confirmed','moderate'])[
        min(CASE s.strength WHEN 'definitional' THEN 1 WHEN 'strong' THEN 2
                            WHEN 'confirmed' THEN 3 WHEN 'moderate' THEN 4 ELSE 5 END)
    ] AS strength
FROM ps_nationality_signals s
WHERE s.points_to = 'china'
  AND ( s.source_system = 'slack:amazon-brand-connections'
     OR s.source_system LIKE 'intake:wechat_report%'
     OR s.source_system = 'cip:ps_partner_credit'
     OR s.source_system LIKE 'hubspot:%'
     OR s.source_system LIKE 'wayward:%'
     OR s.signal = 'on_exclusion_list'
     OR s.signal = 'eric_sheet' )
GROUP BY s.wayward_brand_id
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_VIEW_SQL)
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_wayward_indicators TO {role}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_wayward_indicators")
