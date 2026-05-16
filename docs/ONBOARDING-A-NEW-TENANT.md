# foundry: kind=doc domain=client-intelligence-platform
---
kind: doc
domain: client-intelligence-platform
status: active
last_updated: 2026-05-15
authors: [tim, cc-session-2026-05-15]
supersedes: >
  Earlier `TENANT-ONBOARDING-CHECKLIST.md` skeleton (Phase 1 M0). That file remains as
  a generic mechanical checklist; this runbook is the FULL discovery-first
  procedure new tenants run through. The checklist is the "what",
  this runbook is the "how + why + what to investigate first".
---

# Onboarding a New Tenant to CIP — Discovery-First Runbook

> **The cardinal rule:** every new tenant gets a **FULL discovery investigation** of every data source they use BEFORE we decide what to ingest. The default is "take it ALL" — we build columns for everything they have, with overflow JSONB for anything we don't promote to first-class columns. Decisions about what NOT to take are explicit and reasoned, not accidental.
>
> This runbook is invoked once per new tenant (Wayward, Rocky Ridge, future ventures). It pairs with the "Add a Use Case" procedure (PM scope `0e9b06e6`) and the Connector Authoring Guide (which covers writing a NEW connector class — this runbook covers wiring an EXISTING connector to a NEW tenant).

## When to use this runbook

- New venture or client onboarding to CIP for the first time (Wayward, Rocky Ridge, future)
- Existing tenant adding a brand-new data source (e.g., Wayward adding Plaid 6 months from now)
- Re-baselining an existing tenant after a major upstream system change (CRM swap, ticketing migration)

Do **NOT** use this runbook for:
- Re-running an already-onboarded tenant's normal sync (just call `run_sync()` directly)
- Configuration changes on an existing connector that don't change the data shape

## Cardinal principles

1. **Default = take everything.** Unless there's a concrete reason NOT to ingest a field, it goes into CIP. Storage is cheap; missing data is expensive. Tim's 2026-05-15 incident illustrated this: months of "default behavior" was 4 properties per HubSpot record out of 292/443/435 available. Custom segmentation, ownership, partnership data was all simply not being fetched. We don't want to repeat that pattern.

2. **No silent failures.** Every per-entity / per-field / per-record skip emits a structured event into `cip_sync_runs.error_detail`. If something didn't make it into CIP, an operator must be able to see WHY without log-spelunking.

3. **Discover before you map.** Don't trust your assumptions about what the source contains. Call its property-discovery API (`/crm/v3/properties/{type}` for HubSpot, etc.) and look at the actual data shape FIRST. Common surprise: tenants use custom properties for segmentation that don't match your mental model.

4. **First-class columns OR JSONB overflow — both are fine.** Promote a field to a first-class column when you'll filter/index/join on it heavily. Otherwise it lives in the `properties` JSONB and is still queryable via `properties->>'fieldname'`. The promotion decision is reversible (a future migration can promote a JSONB key to a column).

5. **Manifest the tenant after onboarding.** Once data is flowing, the tenant manifest (`lens_tenant_manifest` per scope `9c3d1393` follow-up) tells the next operator/agent/human exactly what's in CIP for this tenant. If you can't see it on the manifest, an agent can't find it either.

## The 7 phases

### Phase 0 — Stakeholder alignment (Tim + Atlas + new tenant lead)

Before any code runs, answer these:

- **What is this tenant's primary CIP use case?** (CS dashboards? Sales analytics? Compliance? RAG-for-chatbot? All of the above?)
- **What data sources do they use?** (HubSpot for CRM, Zendesk for support, Plaid for finance, Drive for docs, etc.)
- **Who in their org has API access / can grant tokens?** Names + escalation path.
- **Are there fields known to be sensitive?** (PII, financial, legal) — decide whether to ingest or hash at the connector boundary.
- **What's the ingestion budget?** (HubSpot's API has 100k req/day cap on some plans; large tenants may need a paid uplift.)
- **What's the historical depth we need?** (HubSpot retains 20-revision property history by default; full audit-trail history requires Enterprise. Zendesk audit log retention depends on plan.)

Output: a 1-page **Tenant Profile** doc filed in `docs/tenants/<tenant_uuid>/PROFILE.md`. Even a rough version is fine; it gets refined through onboarding.

### Phase 1 — Credential acquisition + permission audit

For EACH data source the tenant uses:

1. **Get the credential** (HubSpot PAT, Zendesk API token, Plaid Link token, etc.). Store in `.foundry-secrets.yaml` (gitignored) AND in the Railway env where the production sync will run (use `railway variables --set` so the values are versioned by Railway, NOT in chat).
2. **Audit the credential's permission scope.**
   - HubSpot: hit `/integrations/v1/me` or just try a probe call on each object type. Note which entities 403. (Wayward example: tickets are 403 because Wayward uses Zendesk for tickets — token doesn't have the scope. NOT a bug; a deliberate choice.)
   - Zendesk: hit `/api/v2/users/me.json` to confirm auth, then `/api/v2/account/settings.json` to see plan tier.
   - Other sources: equivalent probe.
3. **Document which entities are unavailable and why.** This goes in the Tenant Profile. Future operators will see this and won't waste a day re-discovering it.

### Phase 2 — Full source discovery (the part the previous default missed)

For EACH source × entity:

1. **Call the source's property catalog endpoint:**
   - HubSpot: `GET /crm/v3/properties/{companies|contacts|deals|tickets|notes|...}` — returns every property the portal exposes, including custom ones
   - Zendesk: `GET /api/v2/ticket_fields.json`, `GET /api/v2/organization_fields.json`, `GET /api/v2/user_fields.json`
   - Other sources: equivalent
2. **Save the catalog** to `docs/tenants/<tenant_uuid>/discovery/<source>-<entity>-properties.json` — raw response, no transformation.
3. **Build a per-entity field summary**: count of total properties, count of custom (non-vendor-defined), grouping by "group" / "category" if the source provides it. Flag anything that looks important (`*owner*`, `*segment*`, `*market*`, `*region*`, `*partner*`, `*referral*`, etc.).
4. **Show the summary to Tim** before authoring the mapper.

This phase is mandatory. **No mapper authoring without a discovery doc.**

### Phase 3 — Mapping decisions (default = take everything)

For each property in the discovery output, decide:

- **First-class column** — if you'll filter/join/aggregate on it heavily AND the data type is stable.
  - Likely candidates: `name`, `domain`, `country`, `region`, `email`, `phone`, `lifecycle_stage`, `owner_id`, primary segmentation fields.
  - If choosing first-class, add it to `_DOMAIN_FIELDS_BY_TYPE` in the connector's mapper AND ensure the cip_* migration has the column (write a new migration if needed — `cip_NN_<purpose>.py`).
- **JSONB overflow (default)** — everything else. Lands in the `properties` JSONB column. Queryable via `properties->>'field_name'`. Indexable via GIN if specific keys turn out to be hot.

**Default rule when in doubt: JSONB overflow.** It's reversible — a future promotion migration is cheap. A field NEVER pulled is expensive (re-running history is bandwidth-heavy and sometimes impossible).

**Custom property handling**: ALWAYS take them. They're tenant-specific and represent the tenant's real business model (partner registry, segmentation, ROAS targets, etc.). Never skip a custom property without a documented reason in the Tenant Profile.

### Phase 4 — Trial sync (small batch)

Before the full sync:

1. **Limit the trial** to one entity, one page (~50-100 records). Use the existing `run_wayward_*` scripts as templates for the new tenant.
2. **Inspect what landed** in `cip_*` + the `properties` JSONB. Is every field present? Does the schema-drift test (`tests/connectors/test_mapper_schema_drift.py`) still pass?
3. **Inspect the `cip_connector_property_registry` rows** — every property should have a registry entry with its label, description, data_type, is_custom flag. If anything is missing, the registry-population code in the connector has a gap.
4. **Verify the source's auth + rate-limit policy** is honored (check headers in the response — `X-Hubspot-Rate-Limit-Remaining` etc.).

If anything is off, FIX before the full sync. Don't ingest dirty data at scale.

### Phase 5 — Full current-state sync

1. **Wipe any prior partial data** for the tenant (rare — only if a previous attempt left an inconsistent state).
2. **Launch the full sync** with the production env vars.
3. **Monitor `cip_sync_runs`** every 30 min — status should progress from `running` to `success` (or `partial` if known per-entity scope issues are skipped per-entity).
4. **At completion**: verify row counts match expectations. If the source reports 50k records and CIP has 49.5k, investigate the 500-record gap. Common causes: incremental key conflicts, dedup on source_id, soft-deleted source records.

### Phase 6 — Historical backfill (D-159 mandatory)

After current-state succeeds:

1. **Launch the corresponding `run_<tenant>_<source>_backfill.py`**. For each source-side history endpoint (HubSpot Property History, Zendesk Ticket Audits, etc.), the connector emits `HistoricalRecord` objects that the persister writes to `cip_*_history` tables.
2. **Same monitoring loop** as Phase 5. Expect this phase to take 2-5x as long as current-state due to per-record API calls (audit endpoints) and per-record DB upserts.
3. **Per-record SAVEPOINT isolation** (post-2026-05-15) ensures one bad record doesn't kill the batch. If you see `failed` rows in `cip_sync_runs.error_detail`, those are PER-RECORD failures with reasons logged — the rest of the run still committed.

### Phase 7 — Manifest + validation + handoff

1. **Generate the tenant manifest** — once `lens_tenant_manifest` ships (scope to be filed alongside this runbook), running the manifest query against the new tenant produces a complete inventory: connectors active, tables populated, property catalog, lenses available, knowledge sources, last-sync timestamps.
2. **Save the manifest** to `docs/tenants/<tenant_uuid>/MANIFEST.md` (markdown export of the SQL view) so it's discoverable in the repo + readable without DB access.
3. **Smoke-test the four access paths** (per VISION §7g):
   - SQL via `foundry_mcp_db_query` with RLS — returns tenant rows
   - Vector retrieval via Knowledge Subsystem — returns embeddings of derived knowledge
   - Graph retrieval via Graph Subsystem — returns entity relationships
   - File resolver — signed R2 URLs from `cip_files`
4. **File any "gap" PM scopes**: anything the tenant has that CIP doesn't yet pull (e.g., Wayward's Firefly transcripts → HubSpot Engagements connector follow-up scope).
5. **Hand off**: post a tenant onboarding summary to JOS inbox so the next session has full context.

## Common discovery surprises (lessons from past tenants)

| Surprise | Where it bit us | The lesson |
|---|---|---|
| Tenant has 73x more properties than the default slim list | Wayward 2026-05-15 | Always discover before mapping. Never trust the connector's hardcoded property defaults. |
| Token lacks one entity's scope (e.g., HubSpot tickets) | Wayward 2026-05-14 | Audit permission per entity in Phase 1. Document expected-unavailable entities. |
| Source returns mismatched-precision timestamps for the same instant | Wayward 2026-05-15 (SCD-2 valid_range) | Parse timestamps to typed values BEFORE sorting / comparing. Never sort timestamps as strings. |
| Source-side custom property has unstable type (was string, now array) | Hypothetical, but very likely | Mapper field-resilience: unknown → overflow, never crash. Drift detector flags the change for promotion review. |
| Source returns 414 on large property lists in GET | Wayward 2026-05-15 (contacts backfill) | Use POST batch/read endpoints for any property list > ~100 items. Keep URL params minimal. |
| Source has a hidden 50-record cap on property-history requests | Wayward 2026-05-15 | Read the docs. Test against real data, not stub. |
| Source's legacy endpoint silently page-1-loops on cursor-migrated portals | Wayward 2026-05-13 (orgs) + 2026-05-15 (tickets backfill) | When a vendor offers both legacy + cursor pagination, ALWAYS use cursor (even in code paths that look superficially fine). Test against a real tenant's data, not just a stub: stubs don't reproduce the silent-loop behavior. Validate via "unique source_ids covered grows monotonically" — if it plateaus, you're looping. |
| Audit-style backfill re-iterates same records, generating 1000x duplicate history rows | Wayward 2026-05-15 (Zendesk ticket backfill) | Monitor `COUNT(DISTINCT source_id)` in the history table during long-running backfills. A flat curve = pagination bug. A reasonable per-source-id history row count (1-100, depending on source) should be the upper bound; anything >>100 suggests re-iteration. |
| Persister single-record path is too slow for engagement-heavy entities | Wayward 2026-05-16 (HubSpot contacts backfill ran at 4 contacts/min) | The batched insert path (`persist_history_records_batch`, added 2026-05-16) is the default for backfill flushes. If a future bug forces a fallback to per-record SAVEPOINTs for many flushes in a row, the throughput will tank. Watch `cip_sync_runs.error_detail` for "batched persist failed; falling back" log signatures. |

## Outputs of a complete onboarding

For each newly-onboarded tenant, the repo should contain:

```
docs/tenants/<tenant_uuid>/
├── PROFILE.md                 # Stakeholder + use-case + permission profile
├── MANIFEST.md                # Auto-generated post-sync data inventory
└── discovery/
    ├── hubspot-companies-properties.json
    ├── hubspot-contacts-properties.json
    ├── hubspot-deals-properties.json
    ├── zendesk-ticket-fields.json
    ├── zendesk-organization-fields.json
    └── ...
```

Plus PM scope filed for any tenant-specific gaps surfaced during discovery.

## Cross-references

- `TENANT-ONBOARDING-CHECKLIST.md` — generic mechanical checklist (less verbose than this runbook)
- `CONNECTOR-AUTHORING-GUIDE.md` — for writing a brand-new connector class (different from this — that's "build a new connector", this is "wire an existing connector to a new tenant")
- `MIGRATION-RUNBOOK.md` — for applying cip_* migrations to a new tenant's DB
- `SYNC-ORCHESTRATOR-GUIDE.md` — for invoking `run_sync` / `run_backfill` programmatically
- `vision/VISION.md` §7g — Four Access Paths (the validation gate)
- `vision/ROADMAP.md` — Procedures section, "Add a Use Case" ritual (PM scope `0e9b06e6`)

## Status

**Active** as of 2026-05-15. First real-world test: Wayward Phase 2 onboarding (in progress). Lessons from each onboarding flow back into this runbook (it's a living document; bump `last_updated` whenever a tenant teaches us something new).
