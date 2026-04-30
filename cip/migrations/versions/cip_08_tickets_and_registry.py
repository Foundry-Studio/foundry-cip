# foundry: kind=migration domain=client-intelligence-platform
"""CIP M1 — cip_tickets + cip_tickets_history + cip_connector_property_registry + RLS.

Two deliverables in one migration per SPEC §3:

1. cip_tickets + cip_tickets_history — generic support/helpdesk ticket shape.
   requester_id is a soft FK to cip_contacts (UUID only, no REFERENCES).
   History table: SCD Type 2.

2. cip_connector_property_registry — discoverability table (D-121).
   Authoritative map of where every ingested field lives (column vs. JSONB
   overflow, which cip_table, which connector).
   Populated at connector setup by FixtureConnector.describe_schema().
   Also has RLS — tenant-scoped operational metadata.
   NO history table: registry rows are updated in-place (last_synced_schema_at
   tracks recency); no temporal audit needed per SPEC.

Revision ID: cip_08_tickets_and_registry
Revises: cip_07_deals
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_08_tickets_and_registry"
down_revision: str | Sequence[str] | None = "cip_07_deals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cip_tickets ───────────────────────────────────────────────────────────
    op.create_table(
        "cip_tickets",
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
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("priority", sa.Text(), nullable=True),
        sa.Column("ticket_type", sa.Text(), nullable=True),
        # Soft FK to cip_contacts
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requester_email", sa.Text(), nullable=True),
        sa.Column("assignee_name", sa.Text(), nullable=True),
        sa.Column("group_name", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("satisfaction_rating", sa.Text(), nullable=True),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
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
            name="uq_cip_tickets_source",
        ),
    )

    op.create_index(
        "idx_cip_tickets_tenant_client", "cip_tickets", ["tenant_id", "client_id"]
    )
    op.create_index(
        "idx_cip_tickets_status",
        "cip_tickets",
        ["tenant_id", "client_id", "status"],
        postgresql_where=sa.text("status IS NOT NULL"),
    )
    op.create_index(
        "idx_cip_tickets_freshness",
        "cip_tickets",
        ["tenant_id", "client_id", sa.text("refreshed_at DESC")],
    )
    op.create_index(
        "idx_cip_tickets_tags",
        "cip_tickets",
        ["tags"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_cip_tickets_source_dates",
        "cip_tickets",
        ["tenant_id", sa.text("source_created_at DESC")],
        postgresql_where=sa.text("source_created_at IS NOT NULL"),
    )

    # ── cip_tickets_history (SCD Type 2) ──────────────────────────────────────
    op.create_table(
        "cip_tickets_history",
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
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("priority", sa.Text(), nullable=True),
        sa.Column("ticket_type", sa.Text(), nullable=True),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requester_email", sa.Text(), nullable=True),
        sa.Column("assignee_name", sa.Text(), nullable=True),
        sa.Column("group_name", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("satisfaction_rating", sa.Text(), nullable=True),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_cip_tickets_history_valid_range",
        ),
    )

    op.create_index(
        "idx_cip_tickets_history_record", "cip_tickets_history", ["record_id"]
    )
    op.create_index(
        "idx_cip_tickets_history_temporal",
        "cip_tickets_history",
        ["record_id", "valid_from", "valid_to"],
    )
    op.create_index(
        "idx_cip_tickets_history_tenant", "cip_tickets_history", ["tenant_id"]
    )

    # ── cip_connector_property_registry (D-121 discoverability) ───────────────
    # Authoritative map: for every ingested field, records where it lives
    # (column vs overflow), which cip_table, which connector, property type.
    # Populated at connector setup by CIPConnector.describe_schema().
    # No history table: recency tracked via last_synced_schema_at.
    op.create_table(
        "cip_connector_property_registry",
        sa.Column(
            "registry_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connector", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("property_name", sa.Text(), nullable=False),
        sa.Column("property_type", sa.Text(), nullable=False),
        sa.Column("storage_location", sa.Text(), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=True),
        sa.Column("cip_table", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_custom",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_synced_schema_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "property_type IN ('string','number','datetime','enumeration','reference','boolean','array','object')",
            name="ck_cip_registry_property_type",
        ),
        sa.CheckConstraint(
            "storage_location IN ('column','overflow')",
            name="ck_cip_registry_storage_location",
        ),
        sa.UniqueConstraint(
            "tenant_id", "connector", "object_type", "property_name",
            name="uq_cip_registry_tenant_connector_prop",
        ),
    )

    op.create_index(
        "idx_cip_registry_tenant", "cip_connector_property_registry", ["tenant_id"]
    )
    op.create_index(
        "idx_cip_registry_tenant_connector",
        "cip_connector_property_registry",
        ["tenant_id", "connector"],
    )
    op.create_index(
        "idx_cip_registry_tenant_table",
        "cip_connector_property_registry",
        ["tenant_id", "cip_table"],
    )

    # ── RLS ───────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE cip_tickets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_tickets FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_tickets "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )

    op.execute("ALTER TABLE cip_tickets_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_tickets_history FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_tickets_history "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )

    op.execute("ALTER TABLE cip_connector_property_registry ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_connector_property_registry FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_connector_property_registry "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )


def downgrade() -> None:
    # Drop in reverse: policy/RLS → registry → history → main
    op.execute(
        "DROP POLICY IF EXISTS cip_tenant_scope ON cip_connector_property_registry"
    )
    op.execute(
        "ALTER TABLE cip_connector_property_registry NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE cip_connector_property_registry DISABLE ROW LEVEL SECURITY"
    )

    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_tickets_history")
    op.execute("ALTER TABLE cip_tickets_history NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_tickets_history DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_tickets")
    op.execute("ALTER TABLE cip_tickets NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_tickets DISABLE ROW LEVEL SECURITY")

    op.drop_index(
        "idx_cip_registry_tenant_table",
        table_name="cip_connector_property_registry",
    )
    op.drop_index(
        "idx_cip_registry_tenant_connector",
        table_name="cip_connector_property_registry",
    )
    op.drop_index(
        "idx_cip_registry_tenant",
        table_name="cip_connector_property_registry",
    )
    op.drop_table("cip_connector_property_registry")

    op.drop_index("idx_cip_tickets_history_tenant", table_name="cip_tickets_history")
    op.drop_index("idx_cip_tickets_history_temporal", table_name="cip_tickets_history")
    op.drop_index("idx_cip_tickets_history_record", table_name="cip_tickets_history")
    op.drop_table("cip_tickets_history")

    op.drop_index("idx_cip_tickets_source_dates", table_name="cip_tickets")
    op.drop_index("idx_cip_tickets_tags", table_name="cip_tickets")
    op.drop_index("idx_cip_tickets_freshness", table_name="cip_tickets")
    op.drop_index("idx_cip_tickets_status", table_name="cip_tickets")
    op.drop_index("idx_cip_tickets_tenant_client", table_name="cip_tickets")
    op.drop_table("cip_tickets")
