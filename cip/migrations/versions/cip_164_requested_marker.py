"""cip_164 requested marker (CDP: mark-as-requested)

Adds a lightweight 'we asked Wayward to flip this brand' marker WITHOUT touching the china
declaration. Two parts:
  1. ps_nationality_request_log: an append-only log of request events (set by the external report
     agent via FAS nationality.mark_requested). A marker, NOT a declaration state.
  2. lens_ps_collection_queue re-created to APPEND requested_at + is_requested (latest request per
     brand). Every existing column + the queue logic is unchanged, so a marked make_the_case brand
     STILL reads queue='make_the_case' (still owed until they actually pay), now with is_requested=true.

Additive. The log table needs no reader grant (the view reads it via owner privilege, like every lens
over ps_ tables). Grants re-asserted on the view.

Revision ID: cip_164_requested_marker
Revises: cip_163_collection_queue
Create Date: 2026-08-07
"""
from alembic import op

revision = "cip_164_requested_marker"
down_revision = "cip_163_collection_queue"
branch_labels = None
depends_on = None

_READ_ROLES = (
    "ps_reporting_reader",
    "cip_query_reader",
    "cip_metabase_project_silk",
    "cip_twenty_project_silk",
    "metabase_reader_foundry",
)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS ps_nationality_request_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    wayward_brand_id uuid NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT now(),
    requested_by text,
    note text
)
"""

# lens_ps_collection_queue with requested_at + is_requested APPENDED (existing cols unchanged/in order,
# so CREATE OR REPLACE is legal and preserves grants).
_VIEW_WITH_MARKER = """
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
),
req AS (
    SELECT wayward_brand_id, max(requested_at) AS requested_at
    FROM ps_nationality_request_log
    GROUP BY wayward_brand_id
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
    END AS queue,
    r.requested_at,
    (r.requested_at IS NOT NULL) AS is_requested
FROM m
LEFT JOIN req r ON r.wayward_brand_id = m.wayward_brand_id
"""

# exact cip_163 body (no marker) for downgrade
_VIEW_ORIGINAL = """
CREATE VIEW lens_ps_collection_queue AS
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
    op.execute(_CREATE_TABLE)
    op.execute("CREATE INDEX IF NOT EXISTS ix_nat_req_log_brand ON ps_nationality_request_log (wayward_brand_id)")
    op.execute(_VIEW_WITH_MARKER)
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_collection_queue TO {role}")


def downgrade() -> None:
    # Recreate the view WITHOUT the marker columns first (drops its dependency on the log table),
    # then drop the table. DROP + CREATE because CREATE OR REPLACE cannot remove columns.
    op.execute("DROP VIEW IF EXISTS lens_ps_collection_queue")
    op.execute(_VIEW_ORIGINAL)
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_collection_queue TO {role}")
    op.execute("DROP TABLE IF EXISTS ps_nationality_request_log")
