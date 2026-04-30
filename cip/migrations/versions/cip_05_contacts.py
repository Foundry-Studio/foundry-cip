# foundry: kind=migration domain=client-intelligence-platform
"""CIP M1 — cip_contacts + cip_contacts_history + RLS.

Generic contact shape. Phase 2 maps HubSpot contacts and Zendesk users here.
No Phase-2-specific columns in this migration — only the generic shape.

History table: SCD Type 2.

Revision ID: cip_05_contacts
Revises: cip_04_files
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_05_contacts"
down_revision: Union[str, Sequence[str], None] = "cip_04_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cip_contacts ──────────────────────────────────────────────────────────
    op.create_table(
        "cip_contacts",
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
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("company_name", sa.Text(), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("lifecycle_stage", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "tenant_id", "client_id", "source_connector", "source_id",
            name="uq_cip_contacts_source",
        ),
    )

    op.create_index(
        "idx_cip_contacts_tenant_client", "cip_contacts", ["tenant_id", "client_id"]
    )
    op.create_index(
        "idx_cip_contacts_email", "cip_contacts", ["tenant_id", "email"],
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "idx_cip_contacts_company", "cip_contacts", ["tenant_id", "company_id"],
        postgresql_where=sa.text("company_id IS NOT NULL"),
    )
    op.create_index(
        "idx_cip_contacts_freshness",
        "cip_contacts",
        ["tenant_id", "client_id", sa.text("refreshed_at DESC")],
    )
    op.create_index(
        "idx_cip_contacts_tags",
        "cip_contacts",
        ["tags"],
        postgresql_using="gin",
    )

    # ── cip_contacts_history (SCD Type 2) ─────────────────────────────────────
    op.create_table(
        "cip_contacts_history",
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
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("company_name", sa.Text(), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("lifecycle_stage", sa.Text(), nullable=True),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_cip_contacts_history_valid_range",
        ),
    )

    op.create_index(
        "idx_cip_contacts_history_record", "cip_contacts_history", ["record_id"]
    )
    op.create_index(
        "idx_cip_contacts_history_temporal",
        "cip_contacts_history",
        ["record_id", "valid_from", "valid_to"],
    )
    op.create_index(
        "idx_cip_contacts_history_tenant", "cip_contacts_history", ["tenant_id"]
    )

    # ── RLS ───────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE cip_contacts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_contacts FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_contacts "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )

    op.execute("ALTER TABLE cip_contacts_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_contacts_history FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_contacts_history "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_contacts_history")
    op.execute("ALTER TABLE cip_contacts_history NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_contacts_history DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_contacts")
    op.execute("ALTER TABLE cip_contacts NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_contacts DISABLE ROW LEVEL SECURITY")

    op.drop_index("idx_cip_contacts_history_tenant", table_name="cip_contacts_history")
    op.drop_index("idx_cip_contacts_history_temporal", table_name="cip_contacts_history")
    op.drop_index("idx_cip_contacts_history_record", table_name="cip_contacts_history")
    op.drop_table("cip_contacts_history")

    op.drop_index("idx_cip_contacts_tags", table_name="cip_contacts")
    op.drop_index("idx_cip_contacts_freshness", table_name="cip_contacts")
    op.drop_index("idx_cip_contacts_company", table_name="cip_contacts")
    op.drop_index("idx_cip_contacts_email", table_name="cip_contacts")
    op.drop_index("idx_cip_contacts_tenant_client", table_name="cip_contacts")
    op.drop_table("cip_contacts")
