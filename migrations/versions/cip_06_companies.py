# foundry: kind=migration domain=client-intelligence-platform
"""CIP M1 — cip_companies + cip_companies_history + RLS.

Generic company shape. Includes `region` and `language` columns which
are dimension columns used by the Lens Engine (Lens-B filters on region).

History table: SCD Type 2.

Revision ID: cip_06_companies
Revises: cip_05_contacts
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_06_companies"
down_revision: Union[str, Sequence[str], None] = "cip_05_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cip_companies ─────────────────────────────────────────────────────────
    op.create_table(
        "cip_companies",
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
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        # Lens Engine dimensions — region is used by Lens-B (filter_config region=EMEA)
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("annual_revenue", sa.Numeric(), nullable=True),
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
            name="uq_cip_companies_source",
        ),
    )

    op.create_index(
        "idx_cip_companies_tenant_client",
        "cip_companies",
        ["tenant_id", "client_id"],
    )
    op.create_index(
        "idx_cip_companies_name", "cip_companies", ["tenant_id", "name"]
    )
    op.create_index(
        "idx_cip_companies_region", "cip_companies", ["tenant_id", "region"],
        postgresql_where=sa.text("region IS NOT NULL"),
    )
    op.create_index(
        "idx_cip_companies_tags",
        "cip_companies",
        ["tags"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_cip_companies_freshness",
        "cip_companies",
        ["tenant_id", "client_id", sa.text("refreshed_at DESC")],
    )

    # ── cip_companies_history (SCD Type 2) ────────────────────────────────────
    op.create_table(
        "cip_companies_history",
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
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("annual_revenue", sa.Numeric(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_cip_companies_history_valid_range",
        ),
    )

    op.create_index(
        "idx_cip_companies_history_record", "cip_companies_history", ["record_id"]
    )
    op.create_index(
        "idx_cip_companies_history_temporal",
        "cip_companies_history",
        ["record_id", "valid_from", "valid_to"],
    )
    op.create_index(
        "idx_cip_companies_history_tenant", "cip_companies_history", ["tenant_id"]
    )

    # ── RLS ───────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE cip_companies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_companies FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_companies "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )

    op.execute("ALTER TABLE cip_companies_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_companies_history FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_companies_history "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_companies_history")
    op.execute("ALTER TABLE cip_companies_history NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_companies_history DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_companies")
    op.execute("ALTER TABLE cip_companies NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_companies DISABLE ROW LEVEL SECURITY")

    op.drop_index("idx_cip_companies_history_tenant", table_name="cip_companies_history")
    op.drop_index("idx_cip_companies_history_temporal", table_name="cip_companies_history")
    op.drop_index("idx_cip_companies_history_record", table_name="cip_companies_history")
    op.drop_table("cip_companies_history")

    op.drop_index("idx_cip_companies_freshness", table_name="cip_companies")
    op.drop_index("idx_cip_companies_tags", table_name="cip_companies")
    op.drop_index("idx_cip_companies_region", table_name="cip_companies")
    op.drop_index("idx_cip_companies_name", table_name="cip_companies")
    op.drop_index("idx_cip_companies_tenant_client", table_name="cip_companies")
    op.drop_table("cip_companies")
