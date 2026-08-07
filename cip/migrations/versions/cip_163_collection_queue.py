"""cip_163 collection queue lens (CDP money axis)

lens_ps_collection_queue: makes the four posture pools money-aware by joining OUR Stripe-derived
claim (lens_ps_claim.ps_claim_owed) so the board shows what is actually collectible. Additive
SIBLING of lens_ps_china_pools (that view is NOT modified).

money_status:
  no_revenue_yet = brand absent from lens_ps_claim = zero ps_stripe_invoice_lines(is_ps_base) ever
                   = never onboarded on the Wayward platform
  owed_now       = net still owed after payments (ps_claim_owed > 0, cip_158-floored)
  settled        = billed but nothing currently outstanding
queue (each brand exactly one): investigate | watch | settled | reconcile | just_pay | make_the_case.
Expected (grounded 2026-08-07): reconcile 132 / just_pay 159 / make_the_case 100 / watch 1201 /
settled 770 / investigate 80 (sum 2442); owed_now = 391 brands ~ $16,758. Grants to the 5 reader roles.

Revision ID: cip_163_collection_queue
Revises: cip_162_china_pools
Create Date: 2026-08-07
"""
from alembic import op

revision = "cip_163_collection_queue"
down_revision = "cip_162_china_pools"
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
CREATE OR REPLACE VIEW lens_ps_collection_queue AS
WITH m AS (
    SELECT
        p.wayward_brand_id,
        p.pool,
        round(COALESCE(c.ps_claim_owed, 0), 2) AS owed_amount,
        CASE
            WHEN c.wayward_brand_id IS NULL           THEN 'no_revenue_yet'
            WHEN COALESCE(c.ps_claim_owed, 0) > 0.005 THEN 'owed_now'
            ELSE 'settled'
        END AS money_status
    FROM lens_ps_china_pools p
    LEFT JOIN lens_ps_claim c ON c.wayward_brand_id = p.wayward_brand_id
)
SELECT
    m.wayward_brand_id,
    m.pool,
    m.money_status,
    m.owed_amount,
    CASE
        WHEN m.pool = 'investigate'            THEN 'investigate'
        WHEN m.money_status = 'no_revenue_yet' THEN 'watch'
        WHEN m.money_status = 'settled'        THEN 'settled'
        WHEN m.pool = 'acknowledged_paid'      THEN 'reconcile'
        WHEN m.pool = 'just_pay'               THEN 'just_pay'
        WHEN m.pool = 'make_the_case'          THEN 'make_the_case'
    END AS queue
FROM m
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_VIEW_SQL)
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_collection_queue TO {role}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_collection_queue")
