# foundry: kind=migration domain=client-intelligence-platform
"""cip_34: lens_ps_china_commission — PS China attribution + commission lens.

PM cip_34 (china-commission-audit handoff, Tim sign-off 2026-05-25).
A PS-tenant reporting lens that joins the attribution layer
(cip_clients.companion_data, the 5 keys added in this cycle) with the
mirrored deal financials, projecting per brand:

  name, attribution_owner, conditional, ps_lead_source, ps_sales_lead,
  ps_cs_lead, billed (SUM total_fees_billed), paid (SUM total_fees_paid),
  gap (billed - paid = China AR), commission (10% of paid).

Join shape (PS tenant): cip_deals.client_id = cip_clients.client_id —
per-brand in the PS tenant (the mirror's Pass-2 resolved per-brand
client_ids; cip_26's lenses already join this way). NOTE the handoff's
"client_id = Wayward client" caveat is the EcomLever tenant, not PS;
re-verified on prod 2026-05-25 (1,407 PS deals → 1,404 distinct
client_ids = 1,404 cip_clients).

Fee fields live in cip_deals.properties (HubSpot-mirrored):
total_fees_billed, total_fees_paid. NULLIF(...,'')::numeric guards
empty-string. Commission = 10% of paid (PS's Wayward rate).

PS-tenant pin + GUC double-scope, copied from cip_26 — isolation
behaves identically (no GUC → 0 rows; non-PS GUC → 0 rows).

Register in cip_views (D-121); GRANT SELECT to cip_metabase_project_silk
+ cip_query_reader.

Revision ID: cip_34_ps_china_commission_lens
Revises: cip_33_identity_links
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_34_ps_china_commission_lens"
down_revision: str | Sequence[str] | None = "cip_33_identity_links"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_VIEW = "lens_ps_china_commission"
_SLUG = "ps-china-commission"
_DESC = (
    "PS — per-brand China attribution + commission: attribution_owner, "
    "conditional, lead_source, sales/cs lead, fees billed/paid, AR gap, "
    "10% commission on paid"
)
_GRANT_ROLES = ("cip_metabase_project_silk", "cip_query_reader")


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_china_commission AS
        SELECT
            cl.client_id,
            cl.tenant_id,
            cl.source_id     AS hubspot_company_id,
            cl.name          AS brand_name,
            cl.companion_data->>'ps_attribution_owner' AS attribution_owner,
            cl.companion_data->>'ps_conditional'        AS conditional,
            cl.companion_data->>'ps_lead_source'        AS ps_lead_source,
            cl.companion_data->>'ps_sales_lead'         AS ps_sales_lead,
            cl.companion_data->>'ps_cs_lead'            AS ps_cs_lead,
            COALESCE(SUM(NULLIF(d.properties->>'total_fees_billed','')::numeric), 0) AS total_fees_billed,
            COALESCE(SUM(NULLIF(d.properties->>'total_fees_paid','')::numeric), 0)   AS total_fees_paid,
            COALESCE(SUM(NULLIF(d.properties->>'total_fees_billed','')::numeric), 0)
              - COALESCE(SUM(NULLIF(d.properties->>'total_fees_paid','')::numeric), 0) AS ar_gap,
            ROUND(
                COALESCE(SUM(NULLIF(d.properties->>'total_fees_paid','')::numeric), 0) * 0.10,
                2
            ) AS commission_10pct_of_paid,
            COUNT(d.id) AS deal_count
        FROM cip_clients cl
        LEFT JOIN cip_deals d
               ON d.client_id = cl.client_id
              AND d.tenant_id = cl.tenant_id
        WHERE cl.tenant_id = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid
          AND cl.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
        GROUP BY
            cl.client_id, cl.tenant_id, cl.source_id, cl.name, cl.companion_data
        """
    )

    esc_desc = _DESC.replace("'", "''")
    op.execute(
        f"""
        INSERT INTO cip_views (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            view_name, description, filter_config,
            owner_type, owner_id, is_default, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), '{PS_TENANT}', NULL, 'lens-mirror', '{_SLUG}',
            NOW(), NOW(), gen_random_uuid(), 'validated',
            '{_VIEW}', '{esc_desc}',
            '{{"slug": "{_SLUG}", "sql_view": "{_VIEW}", "filter_kind": "ps_china_commission", "phase": "2.7"}}'::jsonb,
            'system', 'cip', false, NOW(), NOW()
        )
        ON CONFLICT DO NOTHING
        """
    )

    for role in _GRANT_ROLES:
        op.execute(f"GRANT SELECT ON {_VIEW} TO {role}")


def downgrade() -> None:
    for role in _GRANT_ROLES:
        op.execute(f"REVOKE ALL ON {_VIEW} FROM {role}")
    op.execute(
        "DELETE FROM cip_views WHERE source_connector='lens-mirror' "
        f"AND source_id = '{_SLUG}'"
    )
    op.execute(f"DROP VIEW IF EXISTS {_VIEW}")
