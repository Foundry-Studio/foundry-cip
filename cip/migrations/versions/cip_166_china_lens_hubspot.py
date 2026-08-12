# foundry: kind=migration domain=client-intelligence-platform
"""cip_166: re-point the china-filter lenses to hubspot-v1 (mirror starvation fix).

The EcomLever -> Project Silk LensMirror pulls its china subset from three views:
lens_china_companies / lens_china_clients / lens_china_contacts. Those views filtered
EcomLever data on source_connector IN ('lens-mirror-companies-v1', 'lens-mirror-deals-v1',
'lens-mirror-contacts-v1'). Around 2026-08-04 the china deals/companies/contacts
consolidated onto the DIRECT HubSpot sync (source_connector='hubspot-v1'), so the views
matched nothing and returned 0 rows, and the mirror silently pulled an empty source. PS
china dimension data (deals, companies, contacts, wayward_stated, reconciliation) has been
frozen since 08-04.

FIX: swap the stale 'lens-mirror-*-v1' connector tags to 'hubspot-v1' in all three views.
The china definition is UNCHANGED: a 'China Referral%' deal (China Referral - Eric/Tim/Adina/
Jeremy Dai/Shallow/OpenLight = the referral partners), Wayward's own acknowledged china set.
Verified against live data: the new filter yields 1,562 companies / 1,590 deals / 1,164 contacts,
matching the frozen mirror set (1,560 companies, +2 new brands over the freeze). Once shipped,
the hourly cip_ps_lens_mirror schedule (enabled, firing) self-heals within an hour; no manual
catch-up. CREATE OR REPLACE VIEW keeps the same columns and preserves grants.

Revision ID: cip_166_china_lens_hubspot
Revises: cip_165_partner_comm_10pct
"""
from __future__ import annotations

from alembic import op

revision: str = "cip_166_china_lens_hubspot"
down_revision: str | None = "cip_165_partner_comm_10pct"
branch_labels = None
depends_on = None

# ── FIXED (hubspot-v1) ────────────────────────────────────────────────────────

_COMPANIES = r"""CREATE OR REPLACE VIEW lens_china_companies AS
 SELECT id, tenant_id, client_id, source_connector, source_id, ingested_at, refreshed_at,
        previous_version_id, ingestion_batch_id, authority, name, domain, industry, region,
        language, country, city, employee_count, annual_revenue, tags, properties, created_at,
        updated_at, companion_data
   FROM cip_companies c
  WHERE tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
    AND source_connector = 'hubspot-v1'
    AND source_id IN (
        SELECT DISTINCT d.properties ->> 'hs_primary_associated_company'
          FROM cip_deals d
         WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
           AND d.source_connector = 'hubspot-v1'
           AND (d.properties ->> 'source') LIKE 'China Referral%'
           AND (d.properties ->> 'hs_primary_associated_company') IS NOT NULL)"""

_CLIENTS = r"""CREATE OR REPLACE VIEW lens_china_clients AS
 SELECT d.id, d.tenant_id, d.client_id, d.source_connector, d.source_id, d.name AS deal_name,
        d.amount, d.currency, d.close_date, d.stage AS stage_id, s.stage_label, s.pipeline_id,
        s.pipeline_label, s.probability AS stage_probability, d.probability AS deal_probability,
        d.properties ->> 'source' AS attribution_source,
        d.properties ->> 'segment' AS segment,
        d.properties ->> 'rev_share_partner' AS rev_share_partner,
        d.properties ->> 'paid_referral' AS paid_referral,
        d.company_id, d.contact_id, d.tags, d.properties, d.ingested_at, d.refreshed_at,
        d.created_at, d.updated_at
   FROM cip_deals d
   LEFT JOIN cip_pipeline_stages s
     ON s.tenant_id = d.tenant_id AND s.source_connector = d.source_connector AND s.stage_id = d.stage
  WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
    AND d.source_connector = 'hubspot-v1'
    AND (d.properties ->> 'source') LIKE 'China Referral%'"""

_CONTACTS = r"""CREATE OR REPLACE VIEW lens_china_contacts AS
 SELECT id, tenant_id, client_id, source_connector, source_id, ingested_at, refreshed_at,
        previous_version_id, ingestion_batch_id, authority, email, phone, first_name, last_name,
        company_name, company_id, title, country, city, tags, lifecycle_stage, properties,
        created_at, updated_at, companion_data
   FROM cip_contacts ct
  WHERE tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
    AND source_connector = 'hubspot-v1'
    AND (properties ->> 'associatedcompanyid') IN (
        SELECT DISTINCT d.properties ->> 'hs_primary_associated_company'
          FROM cip_deals d
         WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
           AND d.source_connector = 'hubspot-v1'
           AND (d.properties ->> 'source') LIKE 'China Referral%'
           AND (d.properties ->> 'hs_primary_associated_company') IS NOT NULL)"""

# ── PRIOR (lens-mirror-*-v1) for downgrade ────────────────────────────────────

_COMPANIES_PREV = r"""CREATE OR REPLACE VIEW lens_china_companies AS
 SELECT id, tenant_id, client_id, source_connector, source_id, ingested_at, refreshed_at,
        previous_version_id, ingestion_batch_id, authority, name, domain, industry, region,
        language, country, city, employee_count, annual_revenue, tags, properties, created_at,
        updated_at, companion_data
   FROM cip_companies c
  WHERE tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
    AND source_connector = 'lens-mirror-companies-v1'
    AND source_id IN (
        SELECT DISTINCT d.properties ->> 'hs_primary_associated_company'
          FROM cip_deals d
         WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
           AND d.source_connector = 'lens-mirror-deals-v1'
           AND (d.properties ->> 'source') LIKE 'China Referral%'
           AND (d.properties ->> 'hs_primary_associated_company') IS NOT NULL)"""

_CLIENTS_PREV = r"""CREATE OR REPLACE VIEW lens_china_clients AS
 SELECT d.id, d.tenant_id, d.client_id, d.source_connector, d.source_id, d.name AS deal_name,
        d.amount, d.currency, d.close_date, d.stage AS stage_id, s.stage_label, s.pipeline_id,
        s.pipeline_label, s.probability AS stage_probability, d.probability AS deal_probability,
        d.properties ->> 'source' AS attribution_source,
        d.properties ->> 'segment' AS segment,
        d.properties ->> 'rev_share_partner' AS rev_share_partner,
        d.properties ->> 'paid_referral' AS paid_referral,
        d.company_id, d.contact_id, d.tags, d.properties, d.ingested_at, d.refreshed_at,
        d.created_at, d.updated_at
   FROM cip_deals d
   LEFT JOIN cip_pipeline_stages s
     ON s.tenant_id = d.tenant_id AND s.source_connector = d.source_connector AND s.stage_id = d.stage
  WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
    AND d.source_connector = 'lens-mirror-deals-v1'
    AND (d.properties ->> 'source') LIKE 'China Referral%'"""

_CONTACTS_PREV = r"""CREATE OR REPLACE VIEW lens_china_contacts AS
 SELECT id, tenant_id, client_id, source_connector, source_id, ingested_at, refreshed_at,
        previous_version_id, ingestion_batch_id, authority, email, phone, first_name, last_name,
        company_name, company_id, title, country, city, tags, lifecycle_stage, properties,
        created_at, updated_at, companion_data
   FROM cip_contacts ct
  WHERE tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
    AND source_connector = 'lens-mirror-contacts-v1'
    AND (properties ->> 'associatedcompanyid') IN (
        SELECT DISTINCT d.properties ->> 'hs_primary_associated_company'
          FROM cip_deals d
         WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
           AND d.source_connector = 'lens-mirror-deals-v1'
           AND (d.properties ->> 'source') LIKE 'China Referral%'
           AND (d.properties ->> 'hs_primary_associated_company') IS NOT NULL)"""


def upgrade() -> None:
    op.execute(_COMPANIES)
    op.execute(_CLIENTS)
    op.execute(_CONTACTS)


def downgrade() -> None:
    op.execute(_COMPANIES_PREV)
    op.execute(_CLIENTS_PREV)
    op.execute(_CONTACTS_PREV)
