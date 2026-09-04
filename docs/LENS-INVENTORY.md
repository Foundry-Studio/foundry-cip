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
| `lens_china_clients` | cip_166, cip_18 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | Wayward — all China Referral deals (any sub-attribution) |
| `lens_china_companies` | cip_166, cip_24 | GUC-only | cip_query_reader, cip_metabase_project_silk | Wayward — companies appearing as hs_primary_associated_company on a China-Referral deal |
| `lens_china_contacts` | cip_166, cip_24 | GUC-only | cip_query_reader, cip_metabase_project_silk | Wayward — contacts whose associatedcompanyid resolves to a China company |
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
| `lens_ps_added_current` | cip_75 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_ar_aging` | cip_109 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_assignment_current` | cip_134 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_attribution_at_risk` | cip_77 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_brand_contact_book` | cip_100, cip_76 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_brand_header` | cip_126 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_brand_hubspot` | cip_76 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_brand_movement` | cip_137 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_brand_reality` | cip_110, cip_122, cip_83, cip_85 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_brand_revenue` | cip_114 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_brand_status` | cip_137 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_brand_status_grid` | cip_137 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_brand_tickets` | cip_141 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_cash_ledger` | cip_123 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_china_brands_financial_summary` | cip_26, cip_32 | tenant-pinned + GUC | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | PS — financial aggregates per brand: SUM(amount), COUNT(deals), MIN/MAX(close_date) |
| `lens_ps_china_chase_list` | cip_83, cip_85, cip_86, cip_88, cip_89, cip_95 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_china_companies` | cip_110, cip_113, cip_92, cip_95 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_china_contention` | cip_117 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_china_deal_financials` | cip_32 | tenant-pinned + GUC | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | PS — per-deal financial read-surface: total_fees_paid, lifetime_gmv, invoices_paid, overdue_invoices, account_creation_date (already-mirrored cip_deals.properties, exposed for Metabase ASK 5) |
| `lens_ps_china_evidence_grid` | cip_94 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_china_pools` | cip_162 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_china_research_queue` | cip_156 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_china_verdict` | cip_110, cip_113, cip_116, cip_121, cip_156, cip_157, cip_66, cip_67, cip_73, cip_80, cip_88, cip_89, cip_95 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_claim` | cip_104, cip_168 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_close_board` | cip_138 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_cohorts` | cip_146 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_collection_queue` | cip_163, cip_164 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_commission_ledger` | cip_104, cip_107, cip_113, cip_131, cip_165, cip_168 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_concentration` | cip_145 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_contribution` | cip_143 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_coverage` | cip_125 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_customer_payments` | cip_133 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_days_to_pay` | cip_151 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_deal_timeline` | cip_77 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_email_party` | cip_147 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_excluded_partner_performance` | cip_109 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_exclusion_status` | cip_68 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_fee_at_risk` | cip_144 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_gate_signals` | cip_138, cip_139 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_identity_health` | cip_54 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_identity_provenance` | cip_56 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_integrity_checks` | ? | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_invariants` | cip_125, cip_140, cip_167 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_monthly_summary` | cip_109, cip_113 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_nationality_review_state` | cip_150 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_nationality_trail` | cip_142 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_open_invoices` | cip_123 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_open_invoices_v2` | cip_137 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_open_questions` | cip_47 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | Open information gaps grouped by who can answer them — drives questionnaires and Slack outreach. |
| `lens_ps_partner_detail` | cip_174 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_partner_payout_summary` | cip_109 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_partner_rate` | cip_152 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_period_figures` | cip_138 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_period_state` | cip_138 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_pipeline` | cip_132 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_product_eligibility` | cip_105, cip_106, cip_130, cip_131 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_rate_clock` | cip_50, cip_53, cip_91 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | The rate clock per brand x product: productive date, current 10/6/3 tier, and when it steps down. Drives roll-off forecasting. |
| `lens_ps_rate_schedule` | cip_104 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_readout_current` | cip_149 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_readout_history` | cip_149 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_refund_allocation` | cip_113 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_refund_events` | cip_124 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_restatement_log` | cip_138 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_source_freshness` | cip_78 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_source_freshness_v2` | cip_138 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_statement_drift` | cip_112 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_statements_history` | cip_126 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_usage_reconciliation` | cip_138, cip_148 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_wayward_acknowledgment` | cip_159 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_wayward_indicators` | cip_160 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_wayward_reconciliation` | cip_108 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_ps_wayward_stated` | cip_109 | GUC-only | cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk | — |
| `lens_tenant_manifest_properties` | cip_14 | GUC-only | cip_query_reader, cip_metabase_role | — |
| `lens_tenant_manifest_sync_health` | cip_14 | GUC-only | cip_query_reader, cip_metabase_role | — |
| `lens_tim_attributed_deals` | cip_18 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | Wayward — deals attributed to Tim Jordan (China Referral - Tim) |
| `lens_wayward_attribution_summary` | cip_18 | GUC-only | cip_query_reader, cip_metabase_role, cip_metabase_project_silk | Wayward — aggregate stats per attribution source (deal counts, closed-won counts/amounts, pipeline value, date range) |

_92 lens views. Roles: `cip_query_reader` (agent SQL / Path 1, cip_31), `cip_metabase_role` (Foundry-internal Metabase, cip_09), `cip_metabase_project_silk` (PS Metabase, cip_21), `cip_twenty_project_silk` (PS Twenty CRM mirror, cip_25)._
