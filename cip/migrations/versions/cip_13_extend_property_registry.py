# foundry: kind=migration domain=client-intelligence-platform
"""CIP M2 step — extend cip_connector_property_registry with manifest fields.

Per PM scope `bfc3d5d0` (Tenant Manifest) + `0246851d` (Tenant Property
Glossary): the registry needs to carry the plain-English semantic layer
agents and humans actually use, not just the vendor's bare-metal
property descriptors.

Adds:
  - `label` (TEXT) — vendor-supplied label (e.g., HubSpot "Source")
  - `group_name` (TEXT) — vendor-supplied grouping (e.g., HubSpot's
    "companyinformation", "warmly", "calendly")
  - `plain_english_meaning` (TEXT) — the tenant-specific semantic
    layer. The glossary file is the editable source-of-truth;
    `scripts/sync_glossary_to_registry.py` materializes markdown → DB.
  - `confidence` (TEXT) — one of verified / inferred / tentative /
    unknown per PROPERTY-GLOSSARY-PATTERN.md
  - `aliases` (TEXT[]) — alternate names humans/agents might search
    (e.g., 'affiliate_owner' for the canonical 'source')
  - `watch_out_for` (TEXT) — gotchas, dirty values, coverage caveats
  - `last_reviewed_at` (TIMESTAMPTZ) — when a human last touched this
  - `last_reviewed_by` (TEXT) — who reviewed
  - `top_values` (JSONB array of {value, count}) — auto-baseline
    sample of the most-common values
  - `coverage_pct` (NUMERIC(5,2)) — % of rows with this property set
  - `client_id` (UUID, nullable) — when a property applies to a
    specific client inside a tenant rather than the whole tenant

Plus CHECK constraint on confidence + a partial index on
(tenant_id, confidence) so the manifest's "show me everything that
needs review" query is fast.

Revision ID: cip_13_extend_property_registry
Revises: cip_12_seed_wayward_client
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_13_extend_property_registry"
down_revision: str | Sequence[str] | None = "cip_12_seed_wayward_client"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cip_connector_property_registry",
        sa.Column("label", sa.Text(), nullable=True),
    )
    op.add_column(
        "cip_connector_property_registry",
        sa.Column("group_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "cip_connector_property_registry",
        sa.Column("plain_english_meaning", sa.Text(), nullable=True),
    )
    op.add_column(
        "cip_connector_property_registry",
        sa.Column(
            "confidence",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'tentative'"),
        ),
    )
    op.add_column(
        "cip_connector_property_registry",
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "cip_connector_property_registry",
        sa.Column("watch_out_for", sa.Text(), nullable=True),
    )
    op.add_column(
        "cip_connector_property_registry",
        sa.Column(
            "last_reviewed_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "cip_connector_property_registry",
        sa.Column("last_reviewed_by", sa.Text(), nullable=True),
    )
    op.add_column(
        "cip_connector_property_registry",
        sa.Column(
            "top_values",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "cip_connector_property_registry",
        sa.Column("coverage_pct", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "cip_connector_property_registry",
        sa.Column(
            "client_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )

    op.create_check_constraint(
        "ck_cip_registry_confidence",
        "cip_connector_property_registry",
        "confidence IN ('verified', 'inferred', 'tentative', 'unknown')",
    )

    # Index for the manifest's "show me everything that needs review" query
    op.create_index(
        "idx_cip_registry_tenant_confidence",
        "cip_connector_property_registry",
        ["tenant_id", "confidence"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_cip_registry_tenant_confidence",
        table_name="cip_connector_property_registry",
    )
    op.drop_constraint(
        "ck_cip_registry_confidence",
        "cip_connector_property_registry",
        type_="check",
    )
    for col in (
        "client_id",
        "coverage_pct",
        "top_values",
        "last_reviewed_by",
        "last_reviewed_at",
        "watch_out_for",
        "aliases",
        "confidence",
        "plain_english_meaning",
        "group_name",
        "label",
    ):
        op.drop_column("cip_connector_property_registry", col)
