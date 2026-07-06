---
doc_type: reference
owner: tim
status: active
generated_by: scripts/generate_lens_inventory.py
---
# CIP Lens Inventory

Every `lens_*` view in the CIP schema — the read surface exposed to Metabase, the Twenty
CRM mirror, and the agent SQL bridge (`cip_query_reader`). Raw `cip_*` tables are never
granted to these roles (P-21); all consumption goes through a lens.

**This file is generated** — do not hand-edit. Regenerate against a full-chain scratch DB:

```bash
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/cip \
    python scripts/generate_lens_inventory.py
```

Scope legend: **GUC-only** = tenant selected purely by the `app.current_tenant` session GUC
(reusable across tenants); **tenant-pinned + GUC** = view body also hardcodes a specific
tenant UUID (PS-owned lenses) *and* re-checks the GUC, so it yields rows only under that tenant.

| Lens view | Migration | Tenant scope | Grants (SELECT) | Purpose |
|---|---|---|---|---|
| `lens_adina_attributed_deals` | cip_18 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | Wayward — deals attributed to Adina (China Referral - Adina) |
| `lens_all_companies` | cip_09 | GUC-only | cip_query_reader, cip_metabase_role | — |
| `lens_china_clients` | cip_18 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | Wayward — all China Referral deals (any sub-attribution) |
| `lens_china_companies` | cip_24 | GUC-only | cip_query_reader, cip_metabase_project_silk | Wayward — companies appearing as hs_primary_associated_company on a China-Referral deal |
| `lens_china_contacts` | cip_24 | GUC-only | cip_query_reader, cip_metabase_project_silk | Wayward — contacts whose associatedcompanyid resolves to a China company |
| `lens_china_deals_history` | cip_36 | GUC-only | cip_query_reader, cip_metabase_project_silk | China-attributed deals — SCD-2 history snapshots. Tenant-pinned via GUC; subset defined by current cip_deals.properties->>'source' LIKE 'China Referral%' for the active tenant. |
| `lens_china_tickets` | cip_33 | GUC-only | cip_query_reader, cip_metabase_project_silk | Wayward — Zendesk tickets whose requester resolves (>=0.9) via cip_identity_links to a China-Referral brand |
| `lens_companies_history` | cip_10 | GUC-only | cip_query_reader, cip_metabase_role | — |
| `lens_deals_history` | cip_29 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | — |
| `lens_deals_with_stage_labels` | cip_17 | GUC-only | cip_query_reader, cip_metabase_role | — |
| `lens_engagements_with_owners` | cip_17 | GUC-only | cip_query_reader, cip_metabase_role | — |
| `lens_eric_attributed_deals` | cip_18 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | Wayward — deals attributed to Eric (China Referral - Eric / LYTASAUR) |
| `lens_eu_west_companies` | cip_09 | GUC-only | cip_query_reader, cip_metabase_role | — |
| `lens_hyphen_migration_deals` | cip_18 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | Wayward — deals migrated from Hyphen Social (post-acquisition) |
| `lens_jeremy_attributed_deals` | cip_18 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | Wayward — deals attributed to Jeremy Dai (China Referral - Jeremy Dai) |
| `lens_openlight_attributed_deals` | cip_18 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | Wayward — deals attributed to OpenLight (China Referral - OpenLight) |
| `lens_ps_china_brands_all` | cip_26 | tenant-pinned + GUC | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | PS — master view: every PS china brand with companion_data + EcomLever-mirrored company identity |
| `lens_ps_china_brands_by_original_attribution` | cip_26 | tenant-pinned + GUC | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | PS — per-deal drilldown with EcomLever attribution sourcer (Eric / Tim / Adina / Jeremy / OpenLight / ...) |
| `lens_ps_china_brands_financial_summary` | cip_26, cip_32 | tenant-pinned + GUC | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | PS — financial aggregates per brand: SUM(amount), COUNT(deals), MIN/MAX(close_date) |
| `lens_ps_china_brands_onboarded` | cip_26 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | PS — brands where companion_data.ps_onboarded_status = 'onboarded' |
| `lens_ps_china_brands_producing` | cip_26 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | PS — brands where companion_data.ps_engagement_health = 'producing' |
| `lens_ps_china_commission` | cip_34 | tenant-pinned + GUC | cip_query_reader, cip_metabase_project_silk | PS — per-brand China attribution + commission: attribution_owner, conditional, lead_source, sales/cs lead, fees billed/paid, AR gap, 10% commission on paid |
| `lens_ps_china_deal_financials` | cip_32 | tenant-pinned + GUC | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | PS — per-deal financial read-surface: total_fees_paid, lifetime_gmv, invoices_paid, overdue_invoices, account_creation_date (already-mirrored cip_deals.properties, exposed for Metabase ASK 5) |
| `lens_tenant_manifest_properties` | cip_14 | GUC-only | cip_query_reader, cip_metabase_role | — |
| `lens_tenant_manifest_sync_health` | cip_14 | GUC-only | cip_query_reader, cip_metabase_role | — |
| `lens_tim_attributed_deals` | cip_18 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | Wayward — deals attributed to Tim Jordan (China Referral - Tim) |
| `lens_wayward_attribution_summary` | cip_18 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | Wayward — aggregate stats per attribution source (deal counts, closed-won counts/amounts, pipeline value, date range) |

_27 lens views. Roles: `cip_query_reader` (agent SQL / Path 1, cip_31), `cip_metabase_role` (Foundry-internal Metabase, cip_09), `cip_metabase_project_silk` (PS Metabase, cip_21), `cip_twenty_project_silk` (PS Twenty CRM mirror, cip_25)._
