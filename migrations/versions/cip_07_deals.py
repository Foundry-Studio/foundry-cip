# foundry: kind=migration domain=client-intelligence-platform
"""CIP M1 — cip_deals + cip_deals_history + RLS.

Generic deal shape. Phase 2 maps HubSpot deals here.
company_id and contact_id are soft FKs to cip_companies / cip_contacts
(UUID only, no REFERENCES — cross-table FK enforced at the application
layer so migrations can apply independently).

History table: SCD Type 2.

Revision ID: cip_07_deals
Revises: cip_06_companies
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_07_deals"
down_revision: Union[str, Sequence[str], None] = "cip_06_companies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cip_deals ─────────────────────────────────────────────────────────────
    op.create_table(
        "cip_deals",
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
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True, server_default="USD"),
        sa.Column("close_date", sa.Date(), nullable=True),
        # Soft FKs — application layer enforces referential integrity
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pipeline", sa.Text(), nullable=True),
        sa.Column("probability", sa.Numeric(), nullable=True),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
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
        sa.UniqueConstraint(
            "tenant_id", "client_id", "source_connector", "source_id",
            name="uq_cip_deals_source",
        ),
    )

    op.create_index(
        "idx_cip_deals_tenant_client", "cip_deals", ["tenant_id", "client_id"]
    )
    op.create_index(
        "idx_cip_deals_pipeline", "cip_deals", ["tenant_id", "client_id", "stage"]
    )
    op.create_index(
        "idx_cip_deals_amount",
        "cip_deals",
        ["tenant_id", sa.text("amount DESC")],
        postgresql_where=sa.text("amount IS NOT NULL"),
    )
    op.create_index(
        "idx_cip_deals_freshness",
        "cip_deals",
        ["tenant_id", "client_id", sa.text("refreshed_at DESC")],
    )

    # ── cip_deals_history (SCD Type 2) ────────────────────────────────────────
    op.create_table(
        "cip_deals_history",
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
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("close_date", sa.Date(), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pipeline", sa.Text(), nullable=True),
        sa.Column("probability", sa.Numeric(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_cip_deals_history_valid_range",
        ),
    )

    op.create_index(
        "idx_cip_deals_history_record", "cip_deals_history", ["record_id"]
    )
    op.create_index(
        "idx_cip_deals_history_temporal",
        "cip_deals_history",
        ["record_id", "valid_from", "valid_to"],
    )
    op.create_index(
        "idx_cip_deals_history_tenant", "cip_deals_history", ["tenant_id"]
    )

    # ── RLS ───────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE cip_deals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_deals FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_deals "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )

    op.execute("ALTER TABLE cip_deals_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_deals_history FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_deals_history "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_deals_history")
    op.execute("ALTER TABLE cip_deals_history NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_deals_history DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_deals")
    op.execute("ALTER TABLE cip_deals NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_deals DISABLE ROW LEVEL SECURITY")

    op.drop_index("idx_cip_deals_history_tenant", table_name="cip_deals_history")
    op.drop_index("idx_cip_deals_history_temporal", table_name="cip_deals_history")
    op.drop_index("idx_cip_deals_history_record", table_name="cip_deals_history")
    op.drop_table("cip_deals_history")

    op.drop_index("idx_cip_deals_freshness", table_name="cip_deals")
    op.drop_index("idx_cip_deals_amount", table_name="cip_deals")
    op.drop_index("idx_cip_deals_pipeline", table_name="cip_deals")
    op.drop_index("idx_cip_deals_tenant_client", table_name="cip_deals")
    op.drop_table("cip_deals")
