# foundry: kind=migration domain=client-intelligence-platform
"""CIP M1 — cip_files + cip_files_history + RLS.

Metadata registry linking R2 originals to their derived knowledge chunks.
Every file ingested by CIP gets one row here; r2_path is the canonical
location in Cloudflare R2 under the tenant namespace.

linked_chunk_ids is a UUID[] column pointing to knowledge_chunks rows
derived from this file.

History table: SCD Type 2 — records changes to file metadata.

Revision ID: cip_04_files
Revises: cip_03_sync_runs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_04_files"
down_revision: str | Sequence[str] | None = "cip_03_sync_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cip_files ─────────────────────────────────────────────────────────────
    op.create_table(
        "cip_files",
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
        sa.Column("source_id", sa.Text(), nullable=True),
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
        sa.Column("r2_path", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column(
            "linked_chunk_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
        sa.Column(
            "properties",
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
    )

    op.create_index(
        "idx_cip_files_tenant_client", "cip_files", ["tenant_id", "client_id"]
    )
    op.create_index("idx_cip_files_tenant", "cip_files", ["tenant_id"])
    op.create_index(
        "idx_cip_files_sha256", "cip_files", ["tenant_id", "sha256"],
        postgresql_where=sa.text("sha256 IS NOT NULL"),
    )
    op.create_index(
        "idx_cip_files_freshness",
        "cip_files",
        ["tenant_id", "client_id", sa.text("refreshed_at DESC")],
    )

    # ── cip_files_history (SCD Type 2) ────────────────────────────────────────
    op.create_table(
        "cip_files_history",
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
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ingestion_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False),
        # Domain snapshot
        sa.Column("r2_path", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column(
            "linked_chunk_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_cip_files_history_valid_range",
        ),
    )

    op.create_index(
        "idx_cip_files_history_record", "cip_files_history", ["record_id"]
    )
    op.create_index(
        "idx_cip_files_history_temporal",
        "cip_files_history",
        ["record_id", "valid_from", "valid_to"],
    )
    op.create_index(
        "idx_cip_files_history_tenant", "cip_files_history", ["tenant_id"]
    )

    # ── RLS ───────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE cip_files ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_files FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_files "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )

    op.execute("ALTER TABLE cip_files_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_files_history FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_files_history "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_files_history")
    op.execute("ALTER TABLE cip_files_history NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_files_history DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_files")
    op.execute("ALTER TABLE cip_files NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_files DISABLE ROW LEVEL SECURITY")

    op.drop_index("idx_cip_files_history_tenant", table_name="cip_files_history")
    op.drop_index("idx_cip_files_history_temporal", table_name="cip_files_history")
    op.drop_index("idx_cip_files_history_record", table_name="cip_files_history")
    op.drop_table("cip_files_history")

    op.drop_index("idx_cip_files_freshness", table_name="cip_files")
    op.drop_index("idx_cip_files_sha256", table_name="cip_files")
    op.drop_index("idx_cip_files_tenant", table_name="cip_files")
    op.drop_index("idx_cip_files_tenant_client", table_name="cip_files")
    op.drop_table("cip_files")
