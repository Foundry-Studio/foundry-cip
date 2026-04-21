# foundry: kind=migration domain=client-intelligence-platform
"""CIP M1 — cip_sync_runs + RLS.

Append-only audit log: one row per connector run. Records started_at,
ended_at, status, rows_ingested, rows_history, error_detail (JSONB).

Per SPEC §3: cip_03 does NOT have a history table (it is itself an audit
log; archiving an audit log is redundant).

Revision ID: cip_03_sync_runs
Revises: cip_02_views
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_03_sync_runs"
down_revision: Union[str, Sequence[str], None] = "cip_02_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cip_sync_runs ─────────────────────────────────────────────────────────
    op.create_table(
        "cip_sync_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # tenant_id — D-026 mandatory scope column
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("connector_name", sa.Text(), nullable=False),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column("sync_mode", sa.Text(), nullable=False, server_default="incremental"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "rows_ingested",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "rows_history",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "rows_created",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "rows_updated",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "rows_skipped",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_detail", postgresql.JSONB(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_state", postgresql.JSONB(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "status IN ('running','success','partial','failed')",
            name="ck_cip_sync_runs_status",
        ),
        sa.CheckConstraint(
            "sync_mode IN ('full','incremental')",
            name="ck_cip_sync_runs_sync_mode",
        ),
    )

    op.create_index(
        "idx_cip_sync_runs_tenant", "cip_sync_runs", ["tenant_id", "client_id"]
    )
    op.create_index(
        "idx_cip_sync_runs_connector",
        "cip_sync_runs",
        ["tenant_id", "connector_id", sa.text("started_at DESC")],
    )
    op.create_index(
        "idx_cip_sync_runs_batch", "cip_sync_runs", ["batch_id"]
    )
    op.create_index(
        "idx_cip_sync_runs_started",
        "cip_sync_runs",
        ["tenant_id", sa.text("started_at DESC")],
    )

    # ── RLS ───────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE cip_sync_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_sync_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_sync_runs "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_sync_runs")
    op.execute("ALTER TABLE cip_sync_runs NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_sync_runs DISABLE ROW LEVEL SECURITY")

    op.drop_index("idx_cip_sync_runs_started", table_name="cip_sync_runs")
    op.drop_index("idx_cip_sync_runs_batch", table_name="cip_sync_runs")
    op.drop_index("idx_cip_sync_runs_connector", table_name="cip_sync_runs")
    op.drop_index("idx_cip_sync_runs_tenant", table_name="cip_sync_runs")
    op.drop_table("cip_sync_runs")
