# foundry: kind=migration domain=client-intelligence-platform
"""CIP M2 step — Wayward-specific attribution lens views (PM scope da6a0110).

Per PM scope da6a0110 (Wayward v1 First Tenant) + Block 5 of the
post-M8 work plan.

Materializes the ad-hoc SQL queries Tim has been running by hand for
attribution research, as proper lens_* SQL views consumable through:
  - Metabase (cip_metabase_role grants)
  - cip_views catalog (registered via this migration as cip_views rows)
  - lens_query_for_table() helper (Path 1 of four-access-paths)

Source field: cip_deals.properties->>'source' carries Wayward's
affiliate-owner attribution. Distribution (2026-05-17):

    China Referral - Eric         809   ← top
    (NULL / no source set)        684
    China Referral - Tim          380
    Organic                       282
    China Referral - Adina        200
    Hyphen Social Migration       154
    Agency Referral               143
    Event / Trade Show            109
    Other                         107
    Cold Email Outbound            44
    Cold LinkedIn Outbound         29
    China Referral - Jeremy Dai    25
    MDS                            20
    Existing Customer Referral     19
    China Referral - Shallow        8
    China Referral - OpenLight      6
    Paid Referral - Folium          6
    ... (long tail)

Lens views created (8):
  - lens_china_clients               — all `China Referral - *` deals
  - lens_tim_attributed_deals        — `China Referral - Tim`
  - lens_eric_attributed_deals       — `China Referral - Eric`
  - lens_adina_attributed_deals      — `China Referral - Adina`
  - lens_openlight_attributed_deals  — `China Referral - OpenLight`
  - lens_jeremy_attributed_deals     — `China Referral - Jeremy Dai`
  - lens_hyphen_migration_deals      — `Hyphen Social Migration`
  - lens_wayward_attribution_summary — aggregate stats per source

Each domain lens JOINs cip_pipeline_stages so stage_label is human-
readable (built on lens_deals_with_stage_labels' resolution pattern
from cip_17).

Revision ID: cip_18_wayward_attr_lenses
Revises: cip_17_owners_and_pipelines
"""
from collections.abc import Sequence

from alembic import op

revision: str = "cip_18_wayward_attr_lenses"
down_revision: str | Sequence[str] | None = "cip_17_owners_and_pipelines"
branch_labels = None
depends_on = None


# Canonical Wayward IDs (locked per PM decision c575c81c).
ECOMLEVER_TENANT = "dec814db-722a-4730-8e60-51afc4a5dad9"
WAYWARD_CLIENT = "661ecab4-dddb-5924-a34d-af1c5133132d"


# Per-attribution lens definitions.
# (lens_name, description, source_filter_sql, source_value_for_cip_views)
_DOMAIN_LENSES: list[tuple[str, str, str, str]] = [
    (
        "lens_china_clients",
        "Wayward — all China Referral deals (any sub-attribution)",
        "d.properties->>'source' LIKE 'China Referral%'",
        "china",
    ),
    (
        "lens_tim_attributed_deals",
        "Wayward — deals attributed to Tim Jordan (China Referral - Tim)",
        "d.properties->>'source' = 'China Referral - Tim'",
        "tim",
    ),
    (
        "lens_eric_attributed_deals",
        "Wayward — deals attributed to Eric (China Referral - Eric / LYTASAUR)",
        "d.properties->>'source' = 'China Referral - Eric'",
        "eric",
    ),
    (
        "lens_adina_attributed_deals",
        "Wayward — deals attributed to Adina (China Referral - Adina)",
        "d.properties->>'source' = 'China Referral - Adina'",
        "adina",
    ),
    (
        "lens_openlight_attributed_deals",
        "Wayward — deals attributed to OpenLight (China Referral - OpenLight)",
        "d.properties->>'source' = 'China Referral - OpenLight'",
        "openlight",
    ),
    (
        "lens_jeremy_attributed_deals",
        "Wayward — deals attributed to Jeremy Dai (China Referral - Jeremy Dai)",
        "d.properties->>'source' = 'China Referral - Jeremy Dai'",
        "jeremy-dai",
    ),
    (
        "lens_hyphen_migration_deals",
        "Wayward — deals migrated from Hyphen Social (post-acquisition)",
        "d.properties->>'source' = 'Hyphen Social Migration'",
        "hyphen-migration",
    ),
]


def _make_domain_lens_sql(view_name: str, filter_sql: str) -> str:
    """Domain lens template — selects from cip_deals, JOINs cip_pipeline_stages
    for stage_label resolution. Tenant-scoped via app.current_tenant GUC.
    """
    return f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT
            d.id,
            d.tenant_id,
            d.client_id,
            d.source_connector,
            d.source_id,
            d.name AS deal_name,
            d.amount,
            d.currency,
            d.close_date,
            d.stage AS stage_id,
            s.stage_label,
            s.pipeline_id,
            s.pipeline_label,
            s.probability AS stage_probability,
            d.probability AS deal_probability,
            d.properties->>'source' AS attribution_source,
            d.properties->>'segment' AS segment,
            d.properties->>'rev_share_partner' AS rev_share_partner,
            d.properties->>'paid_referral' AS paid_referral,
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
          AND d.source_connector = 'hubspot-v1'
          AND ({filter_sql})
    """


def upgrade() -> None:
    # ── Domain lens views (7) ─────────────────────────────────────────
    for view_name, description, filter_sql, _slug in _DOMAIN_LENSES:
        op.execute(_make_domain_lens_sql(view_name, filter_sql))

    # ── Aggregate summary lens ────────────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_wayward_attribution_summary AS
        SELECT
            d.tenant_id,
            COALESCE(d.properties->>'source', '(unattributed)') AS attribution_source,
            COUNT(*) AS deal_count,
            COUNT(*) FILTER (WHERE s.stage_label = 'Closed Won - Active Customer'
                              OR s.stage_label = 'Closed Won - Invoice Paid'
                              OR s.stage_label LIKE 'Closed Won%') AS closed_won_count,
            COUNT(*) FILTER (WHERE s.stage_label LIKE 'Closed Lost%'
                              OR s.stage_label LIKE 'Closed%lost%') AS closed_lost_count,
            COUNT(*) FILTER (WHERE s.probability IS NOT NULL AND s.probability < 1.0
                              AND s.probability > 0.0) AS in_pipeline_count,
            COALESCE(SUM(d.amount) FILTER (WHERE s.stage_label LIKE 'Closed Won%'), 0) AS closed_won_amount,
            COALESCE(SUM(d.amount) FILTER (WHERE s.probability IS NOT NULL AND s.probability < 1.0
                                            AND s.probability > 0.0), 0) AS in_pipeline_amount,
            MIN(d.created_at) AS first_deal_at,
            MAX(d.created_at) AS last_deal_at
        FROM cip_deals d
        LEFT JOIN cip_pipeline_stages s
            ON s.tenant_id = d.tenant_id
           AND s.source_connector = d.source_connector
           AND s.stage_id = d.stage
        WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
          AND d.source_connector = 'hubspot-v1'
        GROUP BY d.tenant_id, COALESCE(d.properties->>'source', '(unattributed)')
        ORDER BY deal_count DESC
        """
    )

    # ── Grant SELECT to cip_metabase_role ─────────────────────────────
    grants = ", ".join([name for name, _, _, _ in _DOMAIN_LENSES])
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cip_metabase_role') THEN "
        f"GRANT SELECT ON {grants} TO cip_metabase_role; "
        f"GRANT SELECT ON lens_wayward_attribution_summary TO cip_metabase_role; "
        f"END IF; END $$;"
    )

    # ── Register lenses in cip_views catalog ──────────────────────────
    # Per the manifest pattern: every lens has a discoverable cip_views row.
    # Note: cip_views uses (tenant_id, slug) UNIQUE constraint; ON CONFLICT
    # handles re-runs cleanly.
    op.execute(f"SELECT set_config('app.current_tenant', '{ECOMLEVER_TENANT}', true)")
    for view_name, description, _filter, slug in _DOMAIN_LENSES:
        op.execute(
            f"""
            INSERT INTO cip_views (
                tenant_id, client_id, source_connector, source_id,
                ingestion_batch_id,
                view_name, description, filter_config,
                owner_type, owner_id, is_default
            ) VALUES (
                '{ECOMLEVER_TENANT}', '{WAYWARD_CLIENT}', 'hubspot-v1',
                'wayward-{slug}',
                gen_random_uuid(),
                '{view_name}',
                '{description.replace("'", "''")}',
                '{{"sql_view": "{view_name}", "filter_kind": "attribution", "slug": "wayward-{slug}"}}'::jsonb,
                'system', 'cip', false
            )
            ON CONFLICT (tenant_id, source_connector, source_id) DO UPDATE SET
                view_name = EXCLUDED.view_name,
                description = EXCLUDED.description,
                filter_config = EXCLUDED.filter_config,
                updated_at = now()
            """
        )
    op.execute(
        f"""
        INSERT INTO cip_views (
            tenant_id, client_id, source_connector, source_id,
            ingestion_batch_id,
            view_name, description, filter_config,
            owner_type, owner_id, is_default
        ) VALUES (
            '{ECOMLEVER_TENANT}', '{WAYWARD_CLIENT}', 'hubspot-v1',
            'wayward-attribution-summary',
            gen_random_uuid(),
            'lens_wayward_attribution_summary',
            'Wayward — aggregate stats per attribution source (deal counts, closed-won counts/amounts, pipeline value, date range)',
            '{{"sql_view": "lens_wayward_attribution_summary", "filter_kind": "aggregate", "slug": "wayward-attribution-summary"}}'::jsonb,
            'system', 'cip', false
        )
        ON CONFLICT (tenant_id, source_connector, source_id) DO UPDATE SET
            view_name = EXCLUDED.view_name,
            description = EXCLUDED.description,
            filter_config = EXCLUDED.filter_config,
            updated_at = now()
        """
    )


def downgrade() -> None:
    # Best-effort revoke (no-op if role missing).
    grants = ", ".join([name for name, _, _, _ in _DOMAIN_LENSES])
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cip_metabase_role') THEN "
        f"REVOKE SELECT ON {grants} FROM cip_metabase_role; "
        f"REVOKE SELECT ON lens_wayward_attribution_summary FROM cip_metabase_role; "
        f"END IF; END $$;"
    )

    # Drop cip_views rows
    op.execute(f"SELECT set_config('app.current_tenant', '{ECOMLEVER_TENANT}', true)")
    op.execute(
        f"DELETE FROM cip_views WHERE tenant_id = '{ECOMLEVER_TENANT}' "
        f"AND source_id IN ("
        + ",".join([f"'wayward-{slug}'" for _, _, _, slug in _DOMAIN_LENSES])
        + ", 'wayward-attribution-summary')"
    )

    # Drop views
    op.execute("DROP VIEW IF EXISTS lens_wayward_attribution_summary")
    for view_name, _, _, _ in _DOMAIN_LENSES:
        op.execute(f"DROP VIEW IF EXISTS {view_name}")
