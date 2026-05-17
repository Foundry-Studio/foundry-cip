# foundry: kind=migration domain=client-intelligence-platform
"""CIP M2 step — seed Wayward as a client under EcomLever tenant.

VISION §4 defines the tenant model as: **tenants are operators/ventures;
clients are the subjects of intelligence INSIDE a tenant**. EcomLever
is the venture-tenant (UUID `dec814db-722a-4730-8e60-51afc4a5dad9`,
already in the `tenants` table); Wayward is the client whose data
CIP ingests for EcomLever.

Until 2026-05-16, an implementation shortcut from 2026-05-12 ("locked
coordinate" doc at `Foundry-Agent-System/WORKBENCH/tim/wayward-tenant-coordinates.md`)
used `b0000000-0000-0000-0000-000000000001` as the Wayward tenant_id.
That was a working stand-in, not VISION-aligned. This migration starts
the correction: seed Wayward as a row in `cip_clients` under EcomLever's
tenant_id. The companion one-shot data migration (NOT in alembic; see
`scripts/migrate_b0_to_ecomlever.py`) updates all existing cip_* rows
from the placeholder tenant_id to (EcomLever tenant_id, Wayward client_id).

Idempotent — re-running is safe (ON CONFLICT DO NOTHING on the
(tenant_id, slug) unique constraint).

Constants locked into the migration so the Wayward client_id is
identical across all environments (dev, staging, prod). Derived
deterministically:
  client_id = uuid5(namespace=EcomLever_tenant_id, name='wayward')
            = 661ecab4-dddb-5924-a34d-af1c5133132d

Revision ID: cip_12_seed_wayward_client
Revises: cip_11_sync_mode_backfill
"""
from collections.abc import Sequence

from alembic import op

revision: str = "cip_12_seed_wayward_client"
down_revision: str | Sequence[str] | None = "cip_11_sync_mode_backfill"
branch_labels = None
depends_on = None

ECOMLEVER_TENANT_ID = "dec814db-722a-4730-8e60-51afc4a5dad9"
WAYWARD_CLIENT_ID = "661ecab4-dddb-5924-a34d-af1c5133132d"


def upgrade() -> None:
    # Bypass RLS for this DDL-adjacent seed — alembic runs as superuser
    # but cip_clients has FORCE ROW LEVEL SECURITY which applies even
    # to table owners unless the policy lets the operation through.
    # The policy uses app.current_tenant; set it to EcomLever so the
    # INSERT passes the USING clause.
    op.execute(
        f"SELECT set_config('app.current_tenant', '{ECOMLEVER_TENANT_ID}', true)"
    )

    op.execute(
        f"""
        INSERT INTO cip_clients (
            id, tenant_id, client_id,
            source_connector, source_id,
            ingestion_batch_id, authority,
            name, slug, industry,
            metadata
        ) VALUES (
            gen_random_uuid(),
            '{ECOMLEVER_TENANT_ID}'::uuid,
            '{WAYWARD_CLIENT_ID}'::uuid,
            'manual', 'wayward',
            gen_random_uuid(), 'validated',
            'Wayward', 'wayward', 'amazon-affiliate-marketing',
            '{{
                "parent_venture": "EcomLever",
                "source_systems": ["hubspot-v1", "zendesk-v1"],
                "seeded_at": "2026-05-16",
                "seeded_by": "cip_12_seed_wayward_client migration",
                "supersedes_placeholder_tenant_id": "b0000000-0000-0000-0000-000000000001"
            }}'::jsonb
        )
        ON CONFLICT (tenant_id, slug) DO NOTHING
        """
    )


def downgrade() -> None:
    # Delete the seeded Wayward client row. Safe because the migration is
    # data-seed-only — no schema changes.
    op.execute(
        f"SELECT set_config('app.current_tenant', '{ECOMLEVER_TENANT_ID}', true)"
    )
    op.execute(
        f"""
        DELETE FROM cip_clients
        WHERE tenant_id = '{ECOMLEVER_TENANT_ID}'::uuid
          AND client_id = '{WAYWARD_CLIENT_ID}'::uuid
          AND slug = 'wayward'
        """
    )
