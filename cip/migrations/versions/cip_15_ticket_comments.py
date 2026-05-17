# foundry: kind=migration domain=client-intelligence-platform
"""CIP M2 step — cip_ticket_comments + cip_ticket_comments_history + RLS.

Per PM scope 28739b6e (Zendesk Ticket Comments + Attachments) + PM
decision 3ae063ea (separate table, NOT JSONB array on cip_tickets —
rationale: per-comment SCD-2 history + per-comment query/filter +
knowledge-embedding-per-comment granularity + attachment FK to comment
all require row-level addressability).

Per-comment shape:
  - author_id (Zendesk user id) + author_email — already-resolved or to-resolve
  - body (plain text) + html_body — the conversational content
  - is_public — distinguishes customer-facing replies from internal notes
  - via_channel — email / web / api / chat etc. (from Zendesk's via.channel)
  - attachments_count + attachment_urls — denormalized counter + URL list;
    full R2 staging deferred to a follow-up. URLs are durable until
    attachments are deleted at the source.
  - properties JSONB for any vendor extras (metadata, via.source, etc.)

Join model: comments link to cip_tickets via ticket_source_id (text =
Zendesk's ticket id) + source_connector. NOT a hard FK to cip_tickets.id
(soft join, matching every other cip_* cross-table reference).

Revision ID: cip_15_ticket_comments
Revises: cip_14_lens_tenant_manifest
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_15_ticket_comments"
down_revision: str | Sequence[str] | None = "cip_14_lens_tenant_manifest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cip_ticket_comments ───────────────────────────────────────────────
    op.create_table(
        "cip_ticket_comments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Provenance
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
        sa.Column(
            "previous_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "ingestion_batch_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "authority",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'validated'"),
        ),
        # Join key — soft FK to cip_tickets (denormalized for query simplicity).
        sa.Column("ticket_source_id", sa.Text(), nullable=False),
        # Comment domain columns
        sa.Column("author_id", sa.Text(), nullable=True),
        sa.Column("author_email", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=True),
        sa.Column("via_channel", sa.Text(), nullable=True),
        sa.Column(
            "attachments_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "attachment_urls",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "source_created_at", sa.DateTime(timezone=True), nullable=True
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
            "tenant_id",
            "client_id",
            "source_connector",
            "source_id",
            name="uq_cip_ticket_comments_source",
        ),
    )

    op.create_index(
        "idx_cip_ticket_comments_tenant_client",
        "cip_ticket_comments",
        ["tenant_id", "client_id"],
    )
    op.create_index(
        "idx_cip_ticket_comments_ticket",
        "cip_ticket_comments",
        ["tenant_id", "source_connector", "ticket_source_id"],
    )
    op.create_index(
        "idx_cip_ticket_comments_source_created",
        "cip_ticket_comments",
        ["tenant_id", sa.text("source_created_at DESC")],
        postgresql_where=sa.text("source_created_at IS NOT NULL"),
    )
    op.create_index(
        "idx_cip_ticket_comments_author",
        "cip_ticket_comments",
        ["tenant_id", "author_id"],
        postgresql_where=sa.text("author_id IS NOT NULL"),
    )

    # ── cip_ticket_comments_history (SCD Type 2) ─────────────────────────
    op.create_table(
        "cip_ticket_comments_history",
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
        sa.Column(
            "previous_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "ingestion_batch_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("authority", sa.Text(), nullable=False),
        # Domain snapshot
        sa.Column("ticket_source_id", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Text(), nullable=True),
        sa.Column("author_email", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=True),
        sa.Column("via_channel", sa.Text(), nullable=True),
        sa.Column("attachments_count", sa.Integer(), nullable=True),
        sa.Column(
            "attachment_urls", postgresql.ARRAY(sa.Text()), nullable=True
        ),
        sa.Column(
            "source_created_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_cip_ticket_comments_history_valid_range",
        ),
    )

    op.create_index(
        "idx_cip_ticket_comments_history_record",
        "cip_ticket_comments_history",
        ["record_id"],
    )
    op.create_index(
        "idx_cip_ticket_comments_history_temporal",
        "cip_ticket_comments_history",
        ["record_id", "valid_from", "valid_to"],
    )
    op.create_index(
        "idx_cip_ticket_comments_history_tenant",
        "cip_ticket_comments_history",
        ["tenant_id"],
    )

    # ── RLS ───────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE cip_ticket_comments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_ticket_comments FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_ticket_comments "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )

    op.execute(
        "ALTER TABLE cip_ticket_comments_history ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE cip_ticket_comments_history FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_ticket_comments_history "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS cip_tenant_scope ON cip_ticket_comments_history"
    )
    op.execute(
        "ALTER TABLE cip_ticket_comments_history NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE cip_ticket_comments_history DISABLE ROW LEVEL SECURITY"
    )

    op.execute(
        "DROP POLICY IF EXISTS cip_tenant_scope ON cip_ticket_comments"
    )
    op.execute("ALTER TABLE cip_ticket_comments NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_ticket_comments DISABLE ROW LEVEL SECURITY")

    op.drop_index(
        "idx_cip_ticket_comments_history_tenant",
        table_name="cip_ticket_comments_history",
    )
    op.drop_index(
        "idx_cip_ticket_comments_history_temporal",
        table_name="cip_ticket_comments_history",
    )
    op.drop_index(
        "idx_cip_ticket_comments_history_record",
        table_name="cip_ticket_comments_history",
    )
    op.drop_table("cip_ticket_comments_history")

    op.drop_index(
        "idx_cip_ticket_comments_author", table_name="cip_ticket_comments"
    )
    op.drop_index(
        "idx_cip_ticket_comments_source_created",
        table_name="cip_ticket_comments",
    )
    op.drop_index(
        "idx_cip_ticket_comments_ticket", table_name="cip_ticket_comments"
    )
    op.drop_index(
        "idx_cip_ticket_comments_tenant_client",
        table_name="cip_ticket_comments",
    )
    op.drop_table("cip_ticket_comments")
