# foundry: kind=migration domain=client-intelligence-platform
"""cip_32: PS deal-financials read-surface lens (Metabase ASK 5, PM e5bfb702).

Phase 2.7 dest-side lens. Metabase's PS dashboard can't reach the deal
financial fields (total_fees_paid, lifetime_gmv, invoices_paid,
overdue_invoices, account_creation_date) even though they're ALREADY
mirrored into the PS tenant's cip_deals.properties JSONB. The gap is
purely a missing read-surface: cip_metabase_project_silk is lens-scoped
(SELECT on the lens_ps_china_* views only — no grant on raw cip_deals),
so the data is only reachable through a lens, and no existing lens
exposes these fields.

NOT a mirror/persister/schema change. The data is in place — verified
against prod 2026-05-24 under GUC=PS (078a37d6-…): of 1,407 PS deals,
942 carry total_fees_paid (SUM $771,115.93, MAX $150,666.57), 1,099
lifetime_gmv, 942 invoices_paid, 942 overdue_invoices, 1,401
account_creation_date. All cast cleanly (numeric / date).

Two changes:

(a) NEW view lens_ps_china_deal_financials (deal grain) — surfaces the
    per-deal financial fields, joined to the brand for name/hubspot id.

(b) CREATE OR REPLACE lens_ps_china_brands_financial_summary — keeps
    every existing column (deal_count, total_amount, earliest/latest
    close, the companion_data enums) and ADDS per-brand SUM rollups of
    the financial fields + brand_onboarded_date (MIN account_creation).

Both pinned to the PS tenant + GUC double-scope, copied verbatim from
the cip_26 lens_ps_china_brands_* idiom so isolation behaves identically
(no GUC → 0 rows; non-PS GUC → 0 rows).

Grant: cip_metabase_project_silk gets SELECT on the new lens (the
summary lens is already granted from cip_26). Registered in cip_views.

Revision ID: cip_32_ps_deal_financials_lens
Revises: cip_31_query_reader_role
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_32_ps_deal_financials_lens"
down_revision: str | Sequence[str] | None = "cip_31_query_reader_role"
branch_labels = None
depends_on = None


# Project Silk tenant — same constant the cip_26 lenses pin to.
PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

_NEW_VIEW = "lens_ps_china_deal_financials"
_NEW_VIEW_SLUG = "ps-china-deal-financials"
_NEW_VIEW_DESC = (
    "PS — per-deal financial read-surface: total_fees_paid, lifetime_gmv, "
    "invoices_paid, overdue_invoices, account_creation_date (already-mirrored "
    "cip_deals.properties, exposed for Metabase ASK 5)"
)

# Roles that read PS lenses (mirrors cip_26's grant set).
_GRANT_ROLES = ("cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # ── (a) New deal-grain financial lens ───────────────────────────────
    # Tenant-pin + GUC double-scope copied verbatim from cip_26's
    # lens_ps_china_brands_* views so cross-tenant isolation is identical.
    # NULLIF(...,'')::numeric guards empty-string JSONB values (verified
    # in prod: all non-empty values cast cleanly).
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_china_deal_financials AS
        SELECT
            d.id            AS deal_id,
            d.tenant_id,
            d.client_id,
            cl.name         AS brand_name,
            cl.source_id    AS hubspot_company_id,
            d.source_id     AS deal_source_id,
            d.close_date,
            d.amount,
            NULLIF(d.properties->>'total_fees_paid','')::numeric   AS total_fees_paid,
            NULLIF(d.properties->>'lifetime_gmv','')::numeric      AS lifetime_gmv,
            NULLIF(d.properties->>'invoices_paid','')::numeric     AS invoices_paid,
            NULLIF(d.properties->>'overdue_invoices','')::numeric  AS overdue_invoices,
            NULLIF(d.properties->>'account_creation_date','')      AS account_creation_date
        FROM cip_deals d
        JOIN cip_clients cl
          ON cl.client_id = d.client_id
         AND cl.tenant_id = d.tenant_id
        WHERE d.tenant_id = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid
          AND d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
        """
    )

    # ── (b) Extend the summary lens with per-brand financial rollups ────
    # Every existing column preserved (deal_count, total_amount,
    # earliest_close, latest_close, the companion enums); ADD the SUM
    # rollups + brand_onboarded_date. Same grain (GROUP BY client) so the
    # LEFT JOIN cip_deals shape is unchanged.
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
            MAX(d.close_date)     AS latest_close,
            SUM(NULLIF(d.properties->>'total_fees_paid','')::numeric)    AS total_fees_paid,
            SUM(NULLIF(d.properties->>'lifetime_gmv','')::numeric)       AS lifetime_gmv,
            SUM(NULLIF(d.properties->>'invoices_paid','')::numeric)      AS invoices_paid,
            SUM(NULLIF(d.properties->>'overdue_invoices','')::numeric)   AS overdue_invoices,
            MIN(NULLIF(d.properties->>'account_creation_date','')::date) AS brand_onboarded_date
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

    # ── (c) Register the new lens in cip_views (D-121 discoverability) ──
    esc_desc = _NEW_VIEW_DESC.replace("'", "''")
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
            '{_NEW_VIEW_SLUG}',
            NOW(), NOW(), gen_random_uuid(), 'validated',
            '{_NEW_VIEW}',
            '{esc_desc}',
            '{{"slug": "{_NEW_VIEW_SLUG}", "sql_view": "{_NEW_VIEW}", "filter_kind": "ps_deal_financials", "phase": "2.7"}}'::jsonb,
            'system',
            'cip',
            false,
            NOW(), NOW()
        )
        ON CONFLICT DO NOTHING
        """
    )

    # ── (d) Grant SELECT on the new lens to the PS-side roles ───────────
    for role in _GRANT_ROLES:
        op.execute(f"GRANT SELECT ON {_NEW_VIEW} TO {role}")


def downgrade() -> None:
    for role in _GRANT_ROLES:
        op.execute(f"REVOKE ALL ON {_NEW_VIEW} FROM {role}")

    op.execute(
        "DELETE FROM cip_views WHERE source_connector='lens-mirror' "
        f"AND source_id = '{_NEW_VIEW_SLUG}'"
    )

    op.execute(f"DROP VIEW IF EXISTS {_NEW_VIEW}")

    # Restore the summary lens to its cip_26 shape (drop the added rollups).
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
