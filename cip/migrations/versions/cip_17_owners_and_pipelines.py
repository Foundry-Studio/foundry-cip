# foundry: kind=migration domain=client-intelligence-platform
"""CIP M2 step — cip_owners + cip_pipeline_stages reference tables + RLS.

Per PM scope cb6750f0 (HubSpot Owners + Pipelines resolver). Two
small reference tables sidecarred to cip_engagements / cip_deals
to resolve raw source IDs into human-readable names + labels.

Why separate tables (vs JSONB on existing rows):
  - Owners + stages are small (~10-20 rows total per tenant)
  - One owner connects to thousands of engagements; per-row denorm
    would waste storage + lose update propagation
  - cip_owners pattern matches cip_clients (vendor-agnostic, source-
    tagged): future Zendesk users can land here too with
    source_connector='zendesk-v1'

Owners 403 note (Wayward PAT 2026-05-17):
  HubSpot's /crm/v3/owners returns 403 for Wayward's PAT — scope
  `crm.objects.owners.read` not granted. Owners table is therefore
  filled by operator seed (one-shot script when names are known) OR
  populated by future PATs that have the scope. Both code paths
  supported.

Pipelines work fully — /crm/v3/pipelines/deals returns 200 with all
stages + labels + probabilities for Wayward portal 242173321.

Revision ID: cip_17_owners_and_pipelines
Revises: cip_16_engagements
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_17_owners_and_pipelines"
down_revision: str | Sequence[str] | None = "cip_16_engagements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cip_owners ─────────────────────────────────────────────────────
    op.create_table(
        "cip_owners",
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
        # Identity
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("role", sa.Text(), nullable=True),
        # How this row was populated
        sa.Column("populated_by", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        # Provenance + timestamps
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "properties",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "populated_by IN ('manual','api','inferred')",
            name="ck_cip_owners_populated_by",
        ),
        sa.UniqueConstraint(
            "tenant_id", "source_connector", "source_id",
            name="uq_cip_owners_source",
        ),
    )
    op.create_index(
        "idx_cip_owners_tenant_client",
        "cip_owners",
        ["tenant_id", "client_id"],
    )
    op.create_index(
        "idx_cip_owners_email",
        "cip_owners",
        ["tenant_id", "email"],
        postgresql_where=sa.text("email IS NOT NULL"),
    )

    # ── cip_pipeline_stages ────────────────────────────────────────────
    op.create_table(
        "cip_pipeline_stages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_connector", sa.Text(), nullable=False),
        # Pipeline + stage identity (composite)
        sa.Column("pipeline_id", sa.Text(), nullable=False),
        sa.Column("pipeline_label", sa.Text(), nullable=False),
        sa.Column("stage_id", sa.Text(), nullable=False),
        sa.Column("stage_label", sa.Text(), nullable=False),
        sa.Column("probability", sa.Numeric(5, 4), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # Vendor extras
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
            "tenant_id", "source_connector", "pipeline_id", "stage_id",
            name="uq_cip_pipeline_stages_source",
        ),
    )
    op.create_index(
        "idx_cip_pipeline_stages_tenant_pipeline",
        "cip_pipeline_stages",
        ["tenant_id", "pipeline_id"],
    )
    op.create_index(
        "idx_cip_pipeline_stages_lookup",
        "cip_pipeline_stages",
        ["tenant_id", "source_connector", "stage_id"],
    )

    # ── RLS ────────────────────────────────────────────────────────────
    for tbl in ("cip_owners", "cip_pipeline_stages"):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY cip_tenant_scope ON {tbl} "
            f"USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
        )

    # ── lens_engagements_with_owners ───────────────────────────────────
    # Resolves owner_source_id → owner name/email via cip_owners LEFT JOIN.
    # Rows with no matching owner row still show (owner fields NULL).
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_engagements_with_owners AS
        SELECT
            e.id,
            e.tenant_id,
            e.client_id,
            e.source_connector,
            e.source_id,
            e.engagement_type,
            e.title,
            e.body,
            e.engagement_at,
            e.source_created_at,
            e.source_updated_at,
            e.status,
            e.priority,
            e.task_type,
            e.completion_date,
            e.start_time,
            e.end_time,
            e.location,
            e.outcome,
            e.external_url,
            e.duration_seconds,
            e.recording_url,
            e.has_transcript,
            e.transcript,
            e.contact_source_ids,
            e.deal_source_ids,
            e.company_source_ids,
            e.ticket_source_ids,
            e.owner_source_id,
            o.name AS owner_name,
            o.email AS owner_email,
            o.role AS owner_role,
            o.archived AS owner_archived,
            e.properties,
            e.created_at,
            e.updated_at
        FROM cip_engagements e
        LEFT JOIN cip_owners o
            ON o.tenant_id = e.tenant_id
           AND o.source_connector = e.source_connector
           AND o.source_id = e.owner_source_id
        WHERE e.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
        """
    )

    # ── lens_deals_with_stage_labels ───────────────────────────────────
    # Resolves cip_deals.stage (HubSpot stage_id) → human-readable label
    # via cip_pipeline_stages LEFT JOIN.
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_deals_with_stage_labels AS
        SELECT
            d.id,
            d.tenant_id,
            d.client_id,
            d.source_connector,
            d.source_id,
            d.name,
            d.amount,
            d.stage AS stage_id,
            s.stage_label,
            s.pipeline_id,
            s.pipeline_label,
            s.probability AS stage_probability,
            d.pipeline,
            d.close_date,
            d.currency,
            d.probability AS deal_probability,
            d.company_id,
            d.contact_id,
            d.tags,
            d.properties,
            d.ingested_at,
            d.refreshed_at,
            d.created_at,
            d.updated_at
        FROM cip_deals d
        LEFT JOIN cip_pipeline_stages s
            ON s.tenant_id = d.tenant_id
           AND s.source_connector = d.source_connector
           AND s.stage_id = d.stage
        WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
        """
    )

    # Grant to cip_metabase_role (consistent with cip_09 + cip_14)
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cip_metabase_role') THEN "
        "GRANT SELECT ON lens_engagements_with_owners TO cip_metabase_role; "
        "GRANT SELECT ON lens_deals_with_stage_labels TO cip_metabase_role; "
        "END IF; END $$;"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cip_metabase_role') THEN "
        "REVOKE SELECT ON lens_deals_with_stage_labels FROM cip_metabase_role; "
        "REVOKE SELECT ON lens_engagements_with_owners FROM cip_metabase_role; "
        "END IF; END $$;"
    )
    op.execute("DROP VIEW IF EXISTS lens_deals_with_stage_labels")
    op.execute("DROP VIEW IF EXISTS lens_engagements_with_owners")

    for tbl in ("cip_pipeline_stages", "cip_owners"):
        op.execute(f"DROP POLICY IF EXISTS cip_tenant_scope ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")

    op.drop_index("idx_cip_pipeline_stages_lookup", table_name="cip_pipeline_stages")
    op.drop_index("idx_cip_pipeline_stages_tenant_pipeline", table_name="cip_pipeline_stages")
    op.drop_table("cip_pipeline_stages")

    op.drop_index("idx_cip_owners_email", table_name="cip_owners")
    op.drop_index("idx_cip_owners_tenant_client", table_name="cip_owners")
    op.drop_table("cip_owners")
