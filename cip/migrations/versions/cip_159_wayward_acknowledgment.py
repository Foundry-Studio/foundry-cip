"""cip_159 wayward acknowledgment lens

lens_ps_wayward_acknowledgment: one row per brand Wayward has PAID on the monthly report
(ps_payment_events) = they have acknowledged it is claimable. Additive sibling view; feeds the
CDP four-pool model (ACKNOWLEDGED-PAID directly; the unpaid pools by absence via LEFT JOIN).

Acknowledgment = presence on ps_payment_events (ever-paid; Tim CDP BE-2 default 2026-08-06).
total_paid = sum(rev_share_stated) = what Wayward paid US (consistent with lens_ps_claim's paid CTE),
NOT total_amount_paid (Wayward gross). New views inherit no grants (cip_155 lesson) -> GRANT to the
5 reader roles.

Revision ID: cip_159_wayward_acknowledgment
Revises: cip_158_claim_phantom_floor
Create Date: 2026-08-06
"""
from alembic import op

revision = "cip_159_wayward_acknowledgment"
down_revision = "cip_158_claim_phantom_floor"
branch_labels = None
depends_on = None

_READER_ROLES = [
    "cip_query_reader",
    "ps_reporting_reader",
    "cip_metabase_project_silk",
    "cip_twenty_project_silk",
    "metabase_reader_foundry",
]

_VIEW_SQL = """
CREATE VIEW lens_ps_wayward_acknowledgment AS
SELECT
    wayward_brand_id,
    true AS acknowledged,
    max(payment_date) AS latest_payment_date,
    round(sum(rev_share_stated), 2) AS total_paid,
    count(*) AS payment_count
FROM ps_payment_events
WHERE wayward_brand_id IS NOT NULL
GROUP BY wayward_brand_id
"""


def upgrade() -> None:
    op.execute(_VIEW_SQL)
    for role in _READER_ROLES:
        op.execute(f'GRANT SELECT ON lens_ps_wayward_acknowledgment TO "{role}"')


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_wayward_acknowledgment")
