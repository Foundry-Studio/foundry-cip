# foundry: kind=migration domain=client-intelligence-platform
"""cip_26: Phase 2.7 — Project Silk destination-side lens recut.

Per Atlas-locked Phase 2.7 design (closed 2026-05-22 with Tim) for PM scope
250. PS owns its own slice of the cross-tenant mirror — five destination-side
lens views over the PS tenant's mirrored Wayward data + companion_data layer.

WHY DESTINATION-SIDE LENSES (CIP-SPEC-011):
- Source-side lenses (cip_18, cip_24) shape EcomLever's view of its own data.
- The mirror in Phase 2.6 materialised those into PS's `cip_*` tables.
- PS then needs ITS OWN reshape of that data — financial-summary slicing,
  onboarded-status filtering, original-attribution drill-down — using PS's
  companion_data layer that doesn't exist in EcomLever. That's a *recut*,
  not a re-issue of the source lens. Hence: PS-side views.

OWNERSHIP BOUNDARY (CIP-SPEC-012 §2):
- EcomLever-mirrored fields (source_id, name, properties.* domain fields)
  are owned by the SOURCE; mirror overwrites them every re-sync.
- companion_data (ps_onboarded_status, ps_engagement_health, ps_segment,
  financial annotations, PS-team notes) is owned by Project Silk via
  Twenty CRM through the column-level GRANT from cip_25.

THE FIVE VIEWS:
1. lens_ps_china_brands_all              — master: client × company mirror × companion
2. lens_ps_china_brands_onboarded        — companion_data->>'ps_onboarded_status' = 'onboarded'
3. lens_ps_china_brands_producing        — companion_data->>'ps_engagement_health' = 'producing'
4. lens_ps_china_brands_by_original_attribution — per-deal w/ Wayward attribution sourcer
5. lens_ps_china_brands_financial_summary — aggregate per brand (SUM, COUNT, MIN/MAX)

JOIN SHAPE (verified against prod 2026-05-22, PS tenant 078a37d6-...):
- cip_clients.client_id is the stable PS scope FK (legitimate, not deprecated).
- cip_companies.source_id = cip_clients.source_id = HubSpot company id
  (preserved by the mirror). 1,404 of 1,406 PS clients have a matching
  cip_companies row; the others are clients with no upstream company record.
- cip_deals.client_id is populated by the mirror's Pass-2 client_id resolution
  (NOT the deprecated cip_deals.company_id soft-FK).
- Original attribution comes from cip_deals.properties->>'source' — the
  EcomLever-side "China Referral - <name>" string, preserved through the mirror.

GUC + RLS DOUBLE-SCOPE (mirrors cip_24):
- Each view body filters by `tenant_id = current_setting('app.current_tenant')::uuid`.
- RLS is also active on the underlying tables.
- Net effect: any session that doesn't set `app.current_tenant` sees zero rows;
  any session that sets a non-PS tenant sees zero rows (mirrored data is
  PS-tenant-scoped only).

GRANTS:
- All five views get GRANT SELECT to `cip_metabase_project_silk` (cip_21 role)
  so Metabase can build dashboards.
- All five views get GRANT SELECT to `cip_twenty_project_silk` (cip_25 role)
  so Twenty CRM can read them.
- No write grants — these are views.

Revision ID: cip_26_ps_lens_views
Revises: cip_27_association_contract

(cip_26 was reserved for this Phase 2.7 slot in cip_27's docstring. cip_27
shipped first because the Association Contract was a separate Atlas ruling
that closed earlier the same day. cip_26 now chains from cip_27 as the
current head — Alembic supports non-contiguous numbering.)
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_26_ps_lens_views"
down_revision: str | Sequence[str] | None = "cip_27_association_contract"
branch_labels = None
depends_on = None


# Project Silk tenant — confirmed against `tenants` table 2026-05-22.
# Hardcoded here following the cip_18/cip_24 precedent (single canonical
# tenant; constants reviewed in migration source).
PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

# (view_name, description, slug). Registered in cip_views per D-121.
_VIEW_REGISTRATIONS = (
    (
        "lens_ps_china_brands_all",
        "PS — master view: every PS china brand with companion_data + EcomLever-mirrored company identity",
        "ps-china-brands-all",
    ),
    (
        "lens_ps_china_brands_onboarded",
        "PS — brands where companion_data.ps_onboarded_status = 'onboarded'",
        "ps-china-brands-onboarded",
    ),
    (
        "lens_ps_china_brands_producing",
        "PS — brands where companion_data.ps_engagement_health = 'producing'",
        "ps-china-brands-producing",
    ),
    (
        "lens_ps_china_brands_by_original_attribution",
        "PS — per-deal drilldown with EcomLever attribution sourcer (Eric / Tim / Adina / Jeremy / OpenLight / ...)",
        "ps-china-brands-by-original-attribution",
    ),
    (
        "lens_ps_china_brands_financial_summary",
        "PS — financial aggregates per brand: SUM(amount), COUNT(deals), MIN/MAX(close_date)",
        "ps-china-brands-financial-summary",
    ),
)

_GRANT_ROLES = ("cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # Two-clause tenant scoping per view body:
    #   tenant_id = PS_TENANT::uuid       — the lens name commits to PS;
    #                                       hardcoded so a superuser with
    #                                       GUC=<other-tenant> can't peek
    #                                       at non-PS rows of the same shape.
    #   AND tenant_id = current_setting('app.current_tenant')::uuid
    #                                     — preserves the cip_18/cip_24 GUC
    #                                       idiom; a session that hasn't set
    #                                       GUC gets zero rows (defense in
    #                                       depth for non-superuser callers
    #                                       where RLS also scopes).
    # Net effect: caller must be in PS GUC to see anything.

    # ── 1. lens_ps_china_brands_all (master) ────────────────────────────
    # LEFT JOIN cip_companies so a client without a matching mirrored
    # company row still appears (Atlas C-3: don't silently drop rows
    # whose upstream identity didn't survive the mirror).
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_china_brands_all AS
        SELECT
            cl.client_id,
            cl.tenant_id,
            cl.source_id          AS hubspot_company_id,
            cl.name               AS client_name,
            cl.initial_intake_route,
            cl.companion_data,
            cl.companion_data->>'ps_onboarded_status'  AS ps_onboarded_status,
            cl.companion_data->>'ps_engagement_health' AS ps_engagement_health,
            cl.companion_data->>'ps_segment'           AS ps_segment,
            co.id                 AS cip_company_id,
            co.name               AS company_name,
            co.domain             AS company_domain,
            co.country            AS company_country,
            co.industry           AS company_industry,
            cl.ingested_at,
            cl.refreshed_at
        FROM cip_clients cl
        LEFT JOIN cip_companies co
               ON co.source_id  = cl.source_id
              AND co.tenant_id  = cl.tenant_id
        WHERE cl.tenant_id = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid
          AND cl.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
        """
    )

    # ── 2. lens_ps_china_brands_onboarded ───────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_china_brands_onboarded AS
        SELECT *
        FROM lens_ps_china_brands_all
        WHERE ps_onboarded_status = 'onboarded'
        """
    )

    # ── 3. lens_ps_china_brands_producing ───────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_china_brands_producing AS
        SELECT *
        FROM lens_ps_china_brands_all
        WHERE ps_engagement_health = 'producing'
        """
    )

    # ── 4. lens_ps_china_brands_by_original_attribution ─────────────────
    # Per-deal row. Attribution sourcer name is extracted from the
    # 'China Referral - <name>' source string preserved by the mirror.
    # Deals whose source doesn't match that prefix get '(other)'.
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_china_brands_by_original_attribution AS
        SELECT
            d.id                  AS cip_deal_id,
            d.client_id,
            d.tenant_id,
            d.source_id           AS hubspot_deal_id,
            d.name                AS deal_name,
            cl.name               AS client_name,
            cl.companion_data->>'ps_onboarded_status'  AS ps_onboarded_status,
            cl.companion_data->>'ps_engagement_health' AS ps_engagement_health,
            cl.companion_data->>'ps_segment'           AS ps_segment,
            d.amount,
            d.currency,
            d.close_date,
            d.stage               AS deal_stage,
            d.pipeline            AS deal_pipeline,
            d.properties->>'source' AS attribution_source,
            CASE
                WHEN d.properties->>'source' LIKE 'China Referral - %'
                    THEN SUBSTRING(d.properties->>'source' FROM 'China Referral - (.+)$')
                ELSE '(other)'
            END AS attribution_sourcer
        FROM cip_deals d
        JOIN cip_clients cl
          ON cl.client_id = d.client_id
         AND cl.tenant_id = d.tenant_id
        WHERE d.tenant_id = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid
          AND d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
        """
    )

    # ── 5. lens_ps_china_brands_financial_summary ───────────────────────
    # Aggregate per brand. LEFT JOIN cip_deals so a brand with no deals
    # still shows up (count = 0, sum = NULL).
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_china_brands_financial_summary AS
        SELECT
            cl.client_id,
            cl.tenant_id,
            cl.source_id          AS hubspot_company_id,
            cl.name               AS client_name,
            cl.companion_data->>'ps_onboarded_status'  AS ps_onboarded_status,
            cl.companion_data->>'ps_engagement_health' AS ps_engagement_health,
            cl.companion_data->>'ps_segment'           AS ps_segment,
            COUNT(d.id)           AS deal_count,
            COALESCE(SUM(d.amount), 0) AS total_amount,
            MIN(d.close_date)     AS earliest_close,
            MAX(d.close_date)     AS latest_close
        FROM cip_clients cl
        LEFT JOIN cip_deals d
               ON d.client_id = cl.client_id
              AND d.tenant_id = cl.tenant_id
        WHERE cl.tenant_id = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid
          AND cl.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
        GROUP BY
            cl.client_id, cl.tenant_id, cl.source_id, cl.name,
            cl.companion_data
        """
    )

    # ── Register in cip_views (D-121 discoverability) ───────────────────
    for view_name, description, slug in _VIEW_REGISTRATIONS:
        esc_desc = description.replace("'", "''")
        op.execute(
            f"""
            INSERT INTO cip_views (
                id, tenant_id, client_id, source_connector, source_id,
                ingested_at, refreshed_at, ingestion_batch_id, authority,
                view_name, description, filter_config,
                owner_type, owner_id, is_default,
                created_at, updated_at
            ) VALUES (
                gen_random_uuid(),
                '{PS_TENANT}',
                NULL,
                'lens-mirror',
                '{slug}',
                NOW(), NOW(), gen_random_uuid(), 'validated',
                '{view_name}',
                '{esc_desc}',
                '{{"slug": "{slug}", "sql_view": "{view_name}", "filter_kind": "ps_companion_data_recut", "phase": "2.7"}}'::jsonb,
                'system',
                'cip',
                false,
                NOW(), NOW()
            )
            ON CONFLICT DO NOTHING
            """
        )

    # ── Grant SELECT to PS-side roles ───────────────────────────────────
    for role in _GRANT_ROLES:
        for view_name, _desc, _slug in _VIEW_REGISTRATIONS:
            op.execute(f"GRANT SELECT ON {view_name} TO {role}")


def downgrade() -> None:
    for role in _GRANT_ROLES:
        for view_name, _desc, _slug in _VIEW_REGISTRATIONS:
            op.execute(f"REVOKE ALL ON {view_name} FROM {role}")

    op.execute(
        "DELETE FROM cip_views WHERE source_connector='lens-mirror' "
        "AND source_id IN ("
        "'ps-china-brands-all',"
        "'ps-china-brands-onboarded',"
        "'ps-china-brands-producing',"
        "'ps-china-brands-by-original-attribution',"
        "'ps-china-brands-financial-summary')"
    )

    # Drop in reverse-dependency order: the filtered views depend on
    # lens_ps_china_brands_all, so they go first.
    op.execute("DROP VIEW IF EXISTS lens_ps_china_brands_financial_summary")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_brands_by_original_attribution")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_brands_producing")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_brands_onboarded")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_brands_all")
