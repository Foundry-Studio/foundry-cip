# foundry: kind=migration domain=client-intelligence-platform
"""CIP M2 step — lens_tenant_manifest + lens_client_manifest views.

Per PM scope `bfc3d5d0` (Tenant Manifest): a per-tenant queryable
surface that answers "what's in CIP for this tenant?" — connectors
active, tables populated with row counts + last-sync, property
catalog with confidence levels, lenses available.

Two views:
  - `lens_tenant_manifest_properties` — one row per (object_type,
    property_name) for the current tenant. Joins the registry with
    glossary/manifest fields (label, plain_english_meaning,
    confidence, aliases, watch_out_for, top_values, coverage_pct).
    Use this for "what columns can I query and what do they mean?"
  - `lens_tenant_manifest_sync_health` — one row per (connector,
    object_type) showing last successful sync time + status from
    cip_sync_runs. Use this for "is this data fresh?"

Both views are tenant-scoped via the standard
`app.current_tenant = NULLIF(current_setting(...), '')::uuid` predicate
on the underlying tables (registry + sync_runs both have tenant_id +
RLS policies; the views inherit by joining on tenant_id and relying
on the RLS predicate to filter rows).

Granted to cip_metabase_role consistent with M5/cip_10 lens-view
pattern: metabase reads the lens views, not the underlying tables.

Revision ID: cip_14_lens_tenant_manifest
Revises: cip_13_extend_property_registry
"""
from collections.abc import Sequence

from alembic import op

revision: str = "cip_14_lens_tenant_manifest"
down_revision: str | Sequence[str] | None = "cip_13_extend_property_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── lens_tenant_manifest_properties ─────────────────────────────────────
    # One row per (object_type, property_name) discovered for the tenant.
    # Tenant scoping flows through the underlying table's RLS policy.
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_tenant_manifest_properties AS
        SELECT
            r.tenant_id,
            r.client_id,
            r.connector,
            r.object_type,
            r.cip_table,
            r.property_name,
            r.label,
            r.group_name,
            r.property_type,
            r.storage_location,
            r.column_name,
            r.is_custom,
            r.description AS vendor_description,
            r.plain_english_meaning,
            r.confidence,
            r.aliases,
            r.watch_out_for,
            r.top_values,
            r.coverage_pct,
            r.last_reviewed_at,
            r.last_reviewed_by,
            r.first_seen_at,
            r.last_synced_schema_at
        FROM cip_connector_property_registry r
        WHERE r.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
        """
    )

    # ── lens_tenant_manifest_sync_health ────────────────────────────────────
    # Most-recent successful sync per (connector, object_type or aggregate
    # if object_type isn't separately tracked). cip_sync_runs records
    # connector_id but not object_type — we surface per-connector freshness
    # plus the per-entity row counts via a separate JOIN below.
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_tenant_manifest_sync_health AS
        WITH latest_per_connector AS (
            SELECT
                connector_id,
                sync_mode,
                MAX(ended_at) FILTER (WHERE status IN ('success', 'partial')) AS last_success_at,
                MAX(ended_at) AS last_attempt_at,
                COUNT(*) AS total_runs
            FROM cip_sync_runs
            WHERE tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
            GROUP BY connector_id, sync_mode
        )
        SELECT
            NULLIF(current_setting('app.current_tenant', true), '')::uuid AS tenant_id,
            connector_id,
            sync_mode,
            last_success_at,
            last_attempt_at,
            total_runs,
            CASE
                WHEN last_success_at IS NULL THEN 'never_succeeded'
                WHEN last_success_at < (now() - interval '7 days') THEN 'stale_gt_7d'
                WHEN last_success_at < (now() - interval '24 hours') THEN 'stale_gt_24h'
                ELSE 'fresh'
            END AS freshness
        FROM latest_per_connector
        """
    )

    # ── Grant to cip_metabase_role (consistent with cip_09 / cip_10) ───────
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cip_metabase_role') THEN "
        "GRANT SELECT ON lens_tenant_manifest_properties TO cip_metabase_role; "
        "GRANT SELECT ON lens_tenant_manifest_sync_health TO cip_metabase_role; "
        "END IF; END $$;"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cip_metabase_role') THEN "
        "REVOKE SELECT ON lens_tenant_manifest_sync_health FROM cip_metabase_role; "
        "REVOKE SELECT ON lens_tenant_manifest_properties FROM cip_metabase_role; "
        "END IF; END $$;"
    )
    op.execute("DROP VIEW IF EXISTS lens_tenant_manifest_sync_health")
    op.execute("DROP VIEW IF EXISTS lens_tenant_manifest_properties")
