# foundry: kind=migration domain=client-intelligence-platform
"""CIP M2 step — cip_engagements unified table + history + RLS.

Per PM scope 9952dd26 (HubSpot Engagements). Unified table with
engagement_type discriminator instead of 5 separate tables. Rationale:

  - Engagements share association model (link to contacts/deals/
    companies/tickets via source_id arrays)
  - Engagements share temporal model (source_created/updated/
    engagement_at)
  - Many real queries are "show me all activity on deal X" — easier
    with a unified table + type filter than 5-way UNION ALL
  - Nullable columns are inexpensive in Postgres
  - Discriminator pattern is well-established (Stripe events, Linear
    history)

Engagement types (subset implemented in v1):
  - note     — HubSpot Notes (5065 in Wayward), body only
  - meeting  — HubSpot Meetings (3485 in Wayward), title+body+times
  - task     — HubSpot Tasks (4002 in Wayward), subject+body+status
  - call     — HubSpot Calls (0 in Wayward; reserved for future tenants
              with call logging integrated, optionally with transcript
              via hs_call_body / hs_call_recording_url / hs_call_*)
  - email    — HubSpot Emails (currently 403-blocked by token scope;
              reserved for tenants whose token can access them)

Firefly note: Tim 2026-05-16 asked to investigate Firefly transcripts
via HubSpot. Wayward portal currently has 0 hs_call rows, so no
transcripts to backfill. If a future tenant has Firefly→HubSpot call
logging, the call.hs_call_body + recording_url + has_transcript +
transcription_id properties land in this same table under
engagement_type='call'.

Revision ID: cip_16_engagements
Revises: cip_15_ticket_comments
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_16_engagements"
down_revision: str | Sequence[str] | None = "cip_15_ticket_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cip_engagements",
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
        # Discriminator
        sa.Column("engagement_type", sa.Text(), nullable=False),
        # Common domain fields
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("owner_source_id", sa.Text(), nullable=True),
        sa.Column(
            "engagement_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "source_created_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "source_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
        # Per-type optional fields
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("priority", sa.Text(), nullable=True),
        sa.Column("task_type", sa.Text(), nullable=True),
        sa.Column(
            "completion_date", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("recording_url", sa.Text(), nullable=True),
        sa.Column("has_transcript", sa.Boolean(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        # Associations (soft FKs via source_id arrays — joined per-type)
        sa.Column(
            "contact_source_ids",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "deal_source_ids",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "company_source_ids",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "ticket_source_ids",
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
        sa.CheckConstraint(
            "engagement_type IN ('note','meeting','task','call','email')",
            name="ck_cip_engagements_type",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "client_id",
            "source_connector",
            "source_id",
            name="uq_cip_engagements_source",
        ),
    )

    op.create_index(
        "idx_cip_engagements_tenant_client",
        "cip_engagements",
        ["tenant_id", "client_id"],
    )
    op.create_index(
        "idx_cip_engagements_type",
        "cip_engagements",
        ["tenant_id", "engagement_type"],
    )
    op.create_index(
        "idx_cip_engagements_engagement_at",
        "cip_engagements",
        ["tenant_id", sa.text("engagement_at DESC")],
        postgresql_where=sa.text("engagement_at IS NOT NULL"),
    )
    op.create_index(
        "idx_cip_engagements_owner",
        "cip_engagements",
        ["tenant_id", "owner_source_id"],
        postgresql_where=sa.text("owner_source_id IS NOT NULL"),
    )
    # GIN indexes on the association arrays so per-deal / per-contact
    # lookups stay fast even at 100K+ engagements
    op.create_index(
        "idx_cip_engagements_deal_ids",
        "cip_engagements",
        ["deal_source_ids"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_cip_engagements_contact_ids",
        "cip_engagements",
        ["contact_source_ids"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_cip_engagements_company_ids",
        "cip_engagements",
        ["company_source_ids"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_cip_engagements_ticket_ids",
        "cip_engagements",
        ["ticket_source_ids"],
        postgresql_using="gin",
    )

    # ── cip_engagements_history (SCD-2) ──────────────────────────────────
    op.create_table(
        "cip_engagements_history",
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
        sa.Column("engagement_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("owner_source_id", sa.Text(), nullable=True),
        sa.Column("engagement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_created_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "source_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("priority", sa.Text(), nullable=True),
        sa.Column("task_type", sa.Text(), nullable=True),
        sa.Column(
            "completion_date", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("recording_url", sa.Text(), nullable=True),
        sa.Column("has_transcript", sa.Boolean(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column(
            "contact_source_ids", postgresql.ARRAY(sa.Text()), nullable=True
        ),
        sa.Column(
            "deal_source_ids", postgresql.ARRAY(sa.Text()), nullable=True
        ),
        sa.Column(
            "company_source_ids", postgresql.ARRAY(sa.Text()), nullable=True
        ),
        sa.Column(
            "ticket_source_ids", postgresql.ARRAY(sa.Text()), nullable=True
        ),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_cip_engagements_history_valid_range",
        ),
    )

    op.create_index(
        "idx_cip_engagements_history_record",
        "cip_engagements_history",
        ["record_id"],
    )
    op.create_index(
        "idx_cip_engagements_history_temporal",
        "cip_engagements_history",
        ["record_id", "valid_from", "valid_to"],
    )
    op.create_index(
        "idx_cip_engagements_history_tenant",
        "cip_engagements_history",
        ["tenant_id"],
    )

    # ── RLS ───────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE cip_engagements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_engagements FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_engagements "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )

    op.execute(
        "ALTER TABLE cip_engagements_history ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE cip_engagements_history FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_engagements_history "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS cip_tenant_scope ON cip_engagements_history"
    )
    op.execute(
        "ALTER TABLE cip_engagements_history NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE cip_engagements_history DISABLE ROW LEVEL SECURITY"
    )

    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_engagements")
    op.execute("ALTER TABLE cip_engagements NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_engagements DISABLE ROW LEVEL SECURITY")

    for idx in (
        "idx_cip_engagements_history_tenant",
        "idx_cip_engagements_history_temporal",
        "idx_cip_engagements_history_record",
    ):
        op.drop_index(idx, table_name="cip_engagements_history")
    op.drop_table("cip_engagements_history")

    for idx in (
        "idx_cip_engagements_ticket_ids",
        "idx_cip_engagements_company_ids",
        "idx_cip_engagements_contact_ids",
        "idx_cip_engagements_deal_ids",
        "idx_cip_engagements_owner",
        "idx_cip_engagements_engagement_at",
        "idx_cip_engagements_type",
        "idx_cip_engagements_tenant_client",
    ):
        op.drop_index(idx, table_name="cip_engagements")
    op.drop_table("cip_engagements")
