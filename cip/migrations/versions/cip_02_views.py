# foundry: kind=migration domain=client-intelligence-platform
"""CIP M1 — cip_views + cip_views_history + RLS.

Lens config rows: each row is a saved filter definition (not a PG view).
filter_config JSONB is applied as a WHERE predicate at query time, AND-composed
with the active RLS scope. An empty filter_config ({}) is a no-op (Lens-A).

History table: SCD Type 2 — records when a lens definition changes.

Revision ID: cip_02_views
Revises: cip_01_clients
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_02_views"
down_revision: Union[str, Sequence[str], None] = "cip_01_clients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cip_views ─────────────────────────────────────────────────────────────
    op.create_table(
        "cip_views",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Provenance §3
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_connector", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("previous_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ingestion_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "authority",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'validated'"),
        ),
        # Domain columns
        sa.Column("view_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "filter_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("owner_type", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Text(), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "source_connector", "source_id",
            name="uq_cip_views_source",
        ),
    )

    op.create_index(
        "idx_cip_views_tenant_client", "cip_views", ["tenant_id", "client_id"]
    )
    op.create_index("idx_cip_views_tenant", "cip_views", ["tenant_id"])

    # ── cip_views_history (SCD Type 2) ────────────────────────────────────────
    op.create_table(
        "cip_views_history",
        sa.Column(
            "history_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        # Provenance snapshot
        sa.Column("source_connector", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ingestion_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False),
        # Domain snapshot
        sa.Column("view_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("filter_config", postgresql.JSONB(), nullable=True),
        sa.Column("owner_type", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_cip_views_history_valid_range",
        ),
    )

    op.create_index(
        "idx_cip_views_history_record", "cip_views_history", ["record_id"]
    )
    op.create_index(
        "idx_cip_views_history_temporal",
        "cip_views_history",
        ["record_id", "valid_from", "valid_to"],
    )
    op.create_index(
        "idx_cip_views_history_tenant", "cip_views_history", ["tenant_id"]
    )

    # ── RLS ───────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE cip_views ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_views FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_views "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )

    op.execute("ALTER TABLE cip_views_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_views_history FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_views_history "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_views_history")
    op.execute("ALTER TABLE cip_views_history NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_views_history DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_views")
    op.execute("ALTER TABLE cip_views NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_views DISABLE ROW LEVEL SECURITY")

    op.drop_index("idx_cip_views_history_tenant", table_name="cip_views_history")
    op.drop_index("idx_cip_views_history_temporal", table_name="cip_views_history")
    op.drop_index("idx_cip_views_history_record", table_name="cip_views_history")
    op.drop_table("cip_views_history")

    op.drop_index("idx_cip_views_tenant", table_name="cip_views")
    op.drop_index("idx_cip_views_tenant_client", table_name="cip_views")
    op.drop_table("cip_views")
