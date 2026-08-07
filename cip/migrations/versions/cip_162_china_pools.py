"""cip_162 china pools lens (CDP BE-5)

lens_ps_china_pools: the four-pool operating view. Takes OUR current declaration state (latest row per
brand from the append-only ps_nationality_review_state), keeps only declared_china + investigate, and
classifies each declared_china brand against the two WAYWARD-side signals:
  - acknowledged_paid : Wayward has paid us for it (present in lens_ps_wayward_acknowledgment)
  - just_pay          : unpaid, but Wayward's own data flags china (lens_ps_wayward_indicators)      -> just make them pay
  - make_the_case     : unpaid, and no wayward indicator                                             -> we must argue it
  - investigate       : we have not declared yet (evidence exists, verdict still unknown)

declared_not is excluded (not a pool). request_sent is excluded here too (no such rows exist until the
BE-6 write-path ships; its pool placement is deferred to that chunk). DISTINCT ON (created_at DESC) is
a safety no-op today (one row per brand) but is REQUIRED once BE-6 makes the table append-only.

Grounded 2026-08-06: expected pool sizes acknowledged_paid 615 + just_pay 1,043 + make_the_case 704 +
investigate 80 = 2,442 rows, each brand in exactly one pool. Additive sibling of the china_contention
family (does NOT touch it). Grants to the 5 reader roles.

Revision ID: cip_162_china_pools
Revises: cip_161_declaration_seed
Create Date: 2026-08-06
"""
from alembic import op

revision = "cip_162_china_pools"
down_revision = "cip_161_declaration_seed"
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
CREATE OR REPLACE VIEW lens_ps_china_pools AS
WITH decl AS (
    SELECT DISTINCT ON (wayward_brand_id) wayward_brand_id, state
    FROM ps_nationality_review_state
    WHERE state IN ('investigate','declared_china','declared_not','request_sent')
    ORDER BY wayward_brand_id, created_at DESC
)
SELECT
    d.wayward_brand_id,
    CASE
        WHEN d.state = 'declared_china' AND ack.wayward_brand_id IS NOT NULL
            THEN 'acknowledged_paid'
        WHEN d.state = 'declared_china' AND ack.wayward_brand_id IS NULL AND wi.wayward_brand_id IS NOT NULL
            THEN 'just_pay'
        WHEN d.state = 'declared_china' AND ack.wayward_brand_id IS NULL AND wi.wayward_brand_id IS NULL
            THEN 'make_the_case'
        WHEN d.state = 'investigate'
            THEN 'investigate'
    END AS pool
FROM decl d
LEFT JOIN lens_ps_wayward_acknowledgment ack ON ack.wayward_brand_id = d.wayward_brand_id
LEFT JOIN lens_ps_wayward_indicators   wi  ON wi.wayward_brand_id  = d.wayward_brand_id
WHERE d.state IN ('declared_china','investigate')
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_VIEW_SQL)
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_pools TO {role}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_pools")
