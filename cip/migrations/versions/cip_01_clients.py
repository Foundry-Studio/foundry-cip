# foundry: kind=migration domain=client-intelligence-platform
"""CIP M1 — cip_clients + cip_clients_history + RLS.

Subjects of intelligence: one row per client within a venture tenant.
Separate from `tenants` (which represents ventures/operators). Clients
are the *objects* CIP collects intelligence about; tenants are the *owners*.

History table: SCD Type 2 — every overwritten record gets one row here.

Revision ID: cip_01_clients
Revises: None (foundry-cip alembic chain root)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_01_clients"
down_revision: str | Sequence[str] | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cip_clients ──────────────────────────────────────────────────────────
    op.create_table(
        "cip_clients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Provenance §3 — tenant first per D-026
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
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
        sa.UniqueConstraint("tenant_id", "slug", name="uq_cip_clients_tenant_slug"),
        sa.UniqueConstraint(
            "tenant_id", "source_connector", "source_id",
            name="uq_cip_clients_source",
        ),
    )

    op.create_index("idx_cip_clients_tenant", "cip_clients", ["tenant_id"])
    op.create_index(
        "idx_cip_clients_tenant_client", "cip_clients", ["tenant_id", "client_id"]
    )
    op.create_index(
        "idx_cip_clients_freshness",
        "cip_clients",
        ["tenant_id", sa.text("refreshed_at DESC")],
    )

    # ── cip_clients_history (SCD Type 2) ─────────────────────────────────────
    op.create_table(
        "cip_clients_history",
        sa.Column(
            "history_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        # tenant_id on history table — required for RLS
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
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
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_cip_clients_history_valid_range",
        ),
    )

    op.create_index(
        "idx_cip_clients_history_record",
        "cip_clients_history",
        ["record_id"],
    )
    op.create_index(
        "idx_cip_clients_history_temporal",
        "cip_clients_history",
        ["record_id", "valid_from", "valid_to"],
    )
    op.create_index(
        "idx_cip_clients_history_tenant",
        "cip_clients_history",
        ["tenant_id"],
    )

    # ── RLS ──────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE cip_clients ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_clients FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_clients "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )

    op.execute("ALTER TABLE cip_clients_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_clients_history FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_clients_history "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )


def downgrade() -> None:
    # Drop in reverse: policy → RLS → history → main
    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_clients_history")
    op.execute("ALTER TABLE cip_clients_history NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_clients_history DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_clients")
    op.execute("ALTER TABLE cip_clients NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_clients DISABLE ROW LEVEL SECURITY")

    op.drop_index("idx_cip_clients_history_tenant", table_name="cip_clients_history")
    op.drop_index("idx_cip_clients_history_temporal", table_name="cip_clients_history")
    op.drop_index("idx_cip_clients_history_record", table_name="cip_clients_history")
    op.drop_table("cip_clients_history")

    op.drop_index("idx_cip_clients_freshness", table_name="cip_clients")
    op.drop_index("idx_cip_clients_tenant_client", table_name="cip_clients")
    op.drop_index("idx_cip_clients_tenant", table_name="cip_clients")
    op.drop_table("cip_clients")
