# foundry: kind=migration domain=client-intelligence-platform
"""CIP M2 step — cip_marketing_emails + cip_contact_lists + membership.

Per PM scope 510fff61 (HubSpot Marketing Emails + Lists, Tier 2).

Three small tables for campaign-level email + list-segmentation
analytics:
  - cip_marketing_emails — campaign-level emails (NOT 1:1 transactional;
    distinct from engagement_type='email' which lives in
    cip_engagements). Statistics (delivered/opened/clicked/etc.) carried
    in properties JSONB to avoid per-stat column churn as HubSpot
    evolves their email stats schema.
  - cip_contact_lists — segmented contact groups. Dynamic (criteria-
    based) and static (hand-curated) shapes both fit; filters JSONB
    carries dynamic-list criteria.
  - cip_contact_list_memberships — M:N join. Optional; only populated
    for static lists with explicit member rosters. Dynamic lists
    re-resolve against contact filters at query time.

Revision ID: cip_20_marketing_lists
Revises: cip_19_knowledge_chunks
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_20_marketing_lists"
down_revision: str | Sequence[str] | None = "cip_19_knowledge_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cip_marketing_emails ─────────────────────────────────────────
    op.create_table(
        "cip_marketing_emails",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_connector", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "refreshed_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "previous_version_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column(
            "ingestion_batch_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column(
            "authority", sa.Text(), nullable=False,
            server_default=sa.text("'validated'"),
        ),
        # Campaign identity
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("email_type", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("from_name", sa.Text(), nullable=True),
        sa.Column("from_email", sa.Text(), nullable=True),
        # Aggregate stats live in JSONB to absorb HubSpot's stat-shape
        # evolution without column churn (delivered/opened/clicked/
        # bounced/unsubscribed/spamreports/etc.).
        sa.Column(
            "stats", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "properties", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "client_id", "source_connector", "source_id",
            name="uq_cip_marketing_emails_source",
        ),
    )
    op.create_index(
        "idx_cip_marketing_emails_tenant_client",
        "cip_marketing_emails", ["tenant_id", "client_id"],
    )
    op.create_index(
        "idx_cip_marketing_emails_state",
        "cip_marketing_emails", ["tenant_id", "state"],
        postgresql_where=sa.text("state IS NOT NULL"),
    )
    op.create_index(
        "idx_cip_marketing_emails_published",
        "cip_marketing_emails",
        ["tenant_id", sa.text("published_at DESC")],
        postgresql_where=sa.text("published_at IS NOT NULL"),
    )

    # ── cip_contact_lists ────────────────────────────────────────────
    op.create_table(
        "cip_contact_lists",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_connector", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "refreshed_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "previous_version_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column(
            "ingestion_batch_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column(
            "authority", sa.Text(), nullable=False,
            server_default=sa.text("'validated'"),
        ),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("list_type", sa.Text(), nullable=True),  # 'dynamic' | 'static'
        sa.Column("processing_type", sa.Text(), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=True),
        sa.Column(
            "filters", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "properties", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "client_id", "source_connector", "source_id",
            name="uq_cip_contact_lists_source",
        ),
    )
    op.create_index(
        "idx_cip_contact_lists_tenant_client",
        "cip_contact_lists", ["tenant_id", "client_id"],
    )
    op.create_index(
        "idx_cip_contact_lists_type",
        "cip_contact_lists", ["tenant_id", "list_type"],
        postgresql_where=sa.text("list_type IS NOT NULL"),
    )

    # ── cip_contact_list_memberships ─────────────────────────────────
    # Only populated for static lists (dynamic re-resolve at query time).
    op.create_table(
        "cip_contact_list_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_connector", sa.Text(), nullable=False),
        sa.Column("list_source_id", sa.Text(), nullable=False),
        sa.Column("contact_source_id", sa.Text(), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "source_connector", "list_source_id", "contact_source_id",
            name="uq_cip_contact_list_memberships",
        ),
    )
    op.create_index(
        "idx_cip_contact_list_memberships_list",
        "cip_contact_list_memberships",
        ["tenant_id", "list_source_id"],
    )
    op.create_index(
        "idx_cip_contact_list_memberships_contact",
        "cip_contact_list_memberships",
        ["tenant_id", "contact_source_id"],
    )

    # ── RLS ──────────────────────────────────────────────────────────
    for tbl in (
        "cip_marketing_emails", "cip_contact_lists", "cip_contact_list_memberships",
    ):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY cip_tenant_scope ON {tbl} "
            f"USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
        )


def downgrade() -> None:
    for tbl in (
        "cip_contact_list_memberships", "cip_contact_lists", "cip_marketing_emails",
    ):
        op.execute(f"DROP POLICY IF EXISTS cip_tenant_scope ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")

    for idx in (
        "idx_cip_contact_list_memberships_contact",
        "idx_cip_contact_list_memberships_list",
    ):
        op.drop_index(idx, table_name="cip_contact_list_memberships")
    op.drop_table("cip_contact_list_memberships")

    for idx in ("idx_cip_contact_lists_type", "idx_cip_contact_lists_tenant_client"):
        op.drop_index(idx, table_name="cip_contact_lists")
    op.drop_table("cip_contact_lists")

    for idx in (
        "idx_cip_marketing_emails_published",
        "idx_cip_marketing_emails_state",
        "idx_cip_marketing_emails_tenant_client",
    ):
        op.drop_index(idx, table_name="cip_marketing_emails")
    op.drop_table("cip_marketing_emails")
