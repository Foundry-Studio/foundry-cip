---
doc_type: phase_plan
project_id: client-intelligence-platform
pm_project_id: 596825db-61bc-4899-bc6c-e207489ca35d
phase: 1
shape: D
status: locked
owner: tim
authors: [tim, atlas]
created: 2026-04-17
last_updated: 2026-04-17
appetite: 8 weeks
primary_tenant: wayward
locks: [D-117, D-118, D-119, D-120, D-121, P-21]
pillars_lit: [ingestion, structured-store, unstructured-store, lens-engine, consumption-surfaces-partial, access-ops-minimum]
pillars_dark: [push-sync, intelligence-alerts]
consumer_acceptance: ali-opens-metabase-switches-lenses-sees-live-wayward-data
---

# CIP Phase 1 — Shape D: Inbound + Lens Validation + Minimum Consumption

> This doc authors Phase 1 in Atlas's four-section plan shape: **VISION** (why this phase exists), **WDGLL** (what done looks like), **SPEC** (technical requirements), **PLAN** (execution sequence). Phase 0 is COMPLETE. Phase 2+ are provisional shapes in `ROADMAP.md` — each gets its own VISION/WDGLL/SPEC/PLAN when its turn comes.

---

## VISION — Why Phase 1 Exists

### The bet

Phase 1 bets that if we can get **live Wayward data flowing from two external systems into one structured store with history, then surface that data through two different lenses in one read tool**, we will have proved the three most novel claims in the CIP architecture in a single eight-week arc:

1. The connector framework is the right abstraction (not per-venture one-off ingestion scripts).
2. The Lens Engine is the right abstraction (not per-consumer SQL forks).
3. The three-data-layer model — Originals + Derived Knowledge + Structured Data — composes cleanly into one product without the layers leaking into each other.

If those three claims hold under real data, the rest of CIP (Push & Sync, multi-tenant, intelligence, write-back, scale) is additive and well-understood — phases can be authored as they ship. If those claims fail, we want to find out in Phase 1, not Phase 4.

### Why this shape (architectural, not appetite-driven)

Four hard constraints fixed the scope:

**(1) HubSpot's 20-revision retention makes delayed HubSpot sync = permanent data loss.** HubSpot keeps only the last 20 property revisions per record. Every day we sync structured but skip HubSpot is a day of history we can never recover. HubSpot is therefore mandatory IN Phase 1. Zendesk history is retrievable later; HubSpot history is not. This single constraint turns HubSpot from a "nice to have" into the hard floor of Phase 1.

**(2) The Lens Engine is the novel abstraction with the highest retrofit cost.** P-21 (Multi-Lens by Default) says every data surface assumes N consumers with N filter configs. If we build Phase 1 with a single-consumer dashboard and try to retrofit lenses in Phase 2, we pay the cost twice: once building the single-view dashboard, once tearing it apart and re-wiring it. One lens proves nothing (any SELECT is a lens-of-one). Two lenses on the same data is the minimum validation of P-21 — Wayward's EcomLever and Project Silk are the natural pair because they already consume the same data today through two different lenses in production.

**(3) The connector framework stress-tests itself better with HubSpot's 4-object topology than Zendesk alone.** Zendesk has a simple ticket/user/organization shape. HubSpot has contacts, companies, deals, and notes with non-trivial relationship graphs. A framework designed only against Zendesk would miss the join-and-relationship complexity that shows up the moment HubSpot enters the picture. Building the framework against both simultaneously ensures the CIPConnector Protocol is general enough to serve future connectors (Chatwoot, partner CRMs, Bob sources, Rocky Ridge sources) without a second round of re-architecture.

**(4) Push & Sync has a well-understood problem shape and is additive.** We already have `zendesk_to_chatwoot.py` working in production — the mechanics of outbound delivery are not the novel claim. Push depends on Phase 1's structured store existing; Phase 1 does not depend on push. Deferring Push & Sync to Phase 2 takes nothing off the critical path and keeps Phase 1 narrow enough to ship.

### What Phase 1 is NOT

- Not a multi-tenant proof (that's Phase 3).
- Not a push-to-Chatwoot replacement (that's Phase 2 — the current one-off script keeps running in the meantime).
- Not a chatbot or agent MCP surface (Phase 2–3).
- Not an anomaly-detection or freshness-signal system (Phase 4–5).
- Not a dedicated CIP database (Phase 6).
- Not full observability — Phase 1 ships `cip_sync_runs` audit and RLS + SET LOCAL enforcement, and no more.

Anything in that list is a deliberate deferral, not an oversight. The roadmap documents where it lands.

### Primary consumer

**Ali** (EcomLever ops) is the Phase 1 human consumer. When Ali opens Metabase, switches between EcomLever Full View and PS China View, and sees live Wayward data from Zendesk and HubSpot with history captured from day one — Phase 1 is done. Ali is the acceptance test for "did the Lens Engine abstraction land."

---

## SOLVE FOR — Wayward's CIP

Wayward doesn't have "a client." Wayward *is* a tenant of CIP, operated through two distinct partner relationships that each need different visibility into the same underlying data.

### The two partner relationships

- **EcomLever** — the consumer-facing ops arm. Ali runs Wayward's operations through here. Needs to see everything.
- **Project Silk** — the China-facing partnership. PS handles the China side of Wayward's business. Needs to see only the China-relevant slice — no access to non-China customers or deals.

Both partners consume the same underlying Wayward data (Zendesk tickets, HubSpot contacts/companies/deals/notes). They consume it through legitimately different scopes. Today, each partner gets its slice through cobbled-together paths: ad-hoc Metabase queries, the one-off `zendesk_to_chatwoot.py` routing script, manual data entry into Project Silk's Twenty CRM to mirror Wayward's HubSpot. Three structural problems with that state:

1. **Data drift between partners.** EcomLever's view and PS's view can diverge silently. Same ticket, different filters applied inconsistently, different conclusions about what's happening.
2. **Permanent history loss.** HubSpot retains only 20 property revisions per record. Any day Wayward's data isn't captured into something durable is intelligence gone forever.
3. **Labor tax that scales with partners.** Someone maintains the ad hoc routing scripts and manual CRM mirroring. That tax scales with every new partner relationship Wayward adds.

### What CIP solves for Wayward — EcomLever-side (Ali)

- **One dashboard surface** (Metabase) unifying Zendesk + HubSpot in live view, no context switch.
- **"What's the state of this customer?"** answered in seconds across support tickets + deal pipeline + contact history, without jumping between three systems.
- **History preserved against HubSpot's 20-revision retention** — every property change is an SCD row in `cip_*_history`, queryable across time.
- **EcomLever Full View** = the baseline truth. No filters. Unfiltered consumer lens.
- **Foundation for Phase 2 push** — once CIP is the source of truth, `zendesk_to_chatwoot.py` can retire and Chatwoot routing becomes a configured lens, not a one-off script Ali has to babysit.

### What CIP solves for Wayward — Project Silk-side

- **PS China View** = the same underlying data, lens-filtered to only the China-relevant slice (by `hs_language` on contacts, by `country` on companies, by language/org fields on Zendesk). PS sees *only* what's in their scope.
- **No data drift.** PS's view comes from the same rows EcomLever's view uses. Filters apply consistently because they're centralized in `cip_views.filter_config`, not scattered in per-partner SQL.
- **Phase 2 unblocks PS's CRM population.** Twenty (PS's CRM) gets pushed the lens-filtered slice of Wayward's HubSpot, automatically. No more manual data entry to keep Twenty in sync.
- **Phase 2 unblocks PS ticket routing.** Chatwoot routing per lens — PS's China-scoped tickets land in PS's inbox; everything else goes to EcomLever's inbox.
- **Partnership stays aligned** without waiting on Wayward to manually curate what gets shared.

### The novel claim being validated

Two partner relationships with legitimately different scopes of access, one data store, no data drift, no per-partner SQL fork. The Lens Engine (P-21) is the abstraction that makes this work. Phase 1 proves the *read* side works (Metabase + two lenses). Phase 2 proves the *push* side works (Chatwoot + Twenty routing through lenses). Phase 3 generalizes to a second tenant.

### Why Wayward first (not Rocky Ridge, not Bob)

- Wayward already runs on HubSpot + Zendesk — Phase 1's connector set is Wayward-native anyway.
- Wayward has two distinct partner relationships with naturally different scopes — the lens pair is organic, not contrived.
- Wayward's HubSpot 20-revision retention is a live production risk today — CIP Phase 1 directly buys history protection.
- EcomLever and Project Silk are both Shatcher-adjacent — friction-free pilot access for debugging and iteration.
- Rocky Ridge and Bob don't have the same partner-pair shape. They'd stress different parts of CIP (multi-tenant, single-lens) more naturally in Phase 3.

### What Wayward's CIP is NOT solving in Phase 1

- Not solving outbound delivery — `zendesk_to_chatwoot.py` keeps running during Phase 1, gets replaced in Phase 2.
- Not solving PS CRM population — that's a Phase 2 push concern.
- Not solving cross-tenant pattern detection — needs a second tenant (Phase 3) plus intelligence layer (Phases 4–5).
- Not solving anomaly alerts — Phase 4.

---

## WDGLL — What Done Looks Like

Phase 1 is complete when **all** of the following are observable:

### Data flow

1. **Zendesk connector** streams tickets, users, and organizations on a recurring schedule into Wayward's CIP tables. Every row carries all 9 provenance columns (tenant_id, client_id, source_connector, source_id, ingested_at, refreshed_at, previous_version_id, ingestion_batch_id, authority). Sync runs write to `cip_sync_runs` with start/end, row counts, and error state.
2. **HubSpot connector** streams contacts, companies, deals, and notes on a recurring schedule. History capture is active from the very first sync (not deferred). Every change produces an SCD Type 2 `_history` row.
3. **Knowledge ingestion** receives ticket bodies, note content, and document attachments via `knowledge_ingester_service.ingest_text_content()` with CIP-scoped `source_type` values (`cip_zendesk_ticket`, `cip_hubspot_note`, `cip_client_document`). Chunks land in Pinecone under the venture namespace. `cip_files` rows point originals (R2) to derived chunks.
4. **Graph extraction** runs as the non-fatal post-vector hook (D-067). New node types (Client, Ticket, Deal, Contact) and edge types (SUPPORTS, PURCHASED) are registered in `graph_templates` for Wayward.

### Lens surface

5. **Metabase dashboard** is deployed with a lens switcher. Two lenses resolve from the same underlying tables:
   - **EcomLever Full View** — unfiltered consumer lens for Ali.
   - **PS China View** — filtered for Project Silk's China-facing workflow (language / region / org filters).
6. Ali can switch between lenses without leaving Metabase and see consistent, live data in both.

### Governance

7. **RLS policies** on every `cip_*` table enforce `tenant_id` isolation. `SET LOCAL` middleware scopes every query.
8. **Migrations cip_01 through cip_08** are applied to the shared Foundry PostgreSQL. Schema matches `architecture/ARCHITECTURE.md` §2–§12 exactly.
9. **Discoverability registry** (D-121) has rows for every Phase 1 artifact: the one `cip_client` row (Wayward's first tracked client), both lenses in `cip_views`, both connectors in Integration Mesh's connector registry, every sync run in `cip_sync_runs`, every ingested chunk in `knowledge_chunks`, every extracted graph entity in FalkorDB.
10. **Authority levels** are populated correctly: connector-ingested data = `ingested`, manual entries (if any) = `validated`, anything extracted by an agent (none in Phase 1) would be `agent_discovered`.

### Non-criteria (intentional)

- **Push to Chatwoot is NOT part of Phase 1 done.** The existing one-off script continues running. Replacement ships in Phase 2.
- **Second tenant is NOT part of Phase 1 done.** Wayward is the sole tenant. Dual-tenant proof lands in Phase 3.
- **REST API / chatbot / MCP tools are NOT part of Phase 1 done.** Metabase is the sole consumption surface in Phase 1.
- **Freshness decay visualization is NOT part of Phase 1 done.** Freshness is computed and stored; surfacing it in Metabase lands in Phase 4.

### Exit gate

Phase 1 exits when Tim demos the dashboard to Ali, Ali switches lenses, and the data is live and right. If Ali finds the lens filter is wrong or the dashboard is stale, that's a Phase 1 bug, not a Phase 2 deferral.

---

## SPEC — Technical Requirements

### S1. Database migrations (cip_01 → cip_08)

Each migration is a single Alembic file under `migrations/versions/`. All tables carry the 9 provenance columns and a matching `_history` table for SCD Type 2. DDL is authoritative in `architecture/ARCHITECTURE.md` §2–§12.

- **cip_01** — `cip_clients` + `cip_clients_history` (subject-of-intelligence entities; separate from `tenants`).
- **cip_02** — `cip_views` + `cip_views_history` (lens config rows with `filter_config` JSONB).
- **cip_03** — `cip_sync_runs` (append-only audit, no history table).
- **cip_04** — `cip_files` + `cip_files_history` (metadata registry linking R2 originals → derived chunks).
- **cip_05** — `cip_contacts` + `cip_contacts_history` (HubSpot contacts).
- **cip_06** — `cip_companies` + `cip_companies_history` (HubSpot companies).
- **cip_07** — `cip_deals` + `cip_deals_history` (HubSpot deals).
- **cip_08** — `cip_tickets` + `cip_tickets_history` (Zendesk tickets). Users and orgs land in `cip_contacts` / `cip_companies` to avoid duplicate entity types.

**Migrations ship with RLS policies enabled from cip_01.** No table exists without tenant scoping.

### S2. Ingestion & Connectors — framework inside Integration Mesh (D-118)

**Location:** `platform/integration-mesh/src/connectors/cip/` (not in the CIP product folder — the connector framework is a platform capability hosted in Integration Mesh; CIP's specific connectors are its first instances).

**Framework deliverables:**

- **`CIPConnector` Protocol** — abstract interface with methods: `authenticate()`, `stream_records(cursor, batch_size)`, `describe_schema()`, `rate_limit_policy`, `incremental_key()`. Implementations are swappable.
- **`CIPMapper` Protocol** — abstract interface that transforms source records into `cip_*` rows. Methods: `map(record) -> Iterable[CIPRow]`, `overflow_fields() -> list[str]`, `authority() -> str`.
- **Ingestion pipeline orchestrator** — wraps connector + mapper + DB writer + SCD differ + `cip_sync_runs` audit. One entry point: `run_sync(connector_id, tenant_id, client_id, db)`.
- **Graph/Knowledge post-hook** — after structured writes land, the orchestrator calls `knowledge_ingester_service.ingest_text_content()` for any text fields marked `ingest_as_knowledge=True` in the mapper. Graph extraction runs via the existing non-fatal post-vector hook (D-067).

**Phase 1 connector instances:**

- **`ZendeskConnector`** — OAuth2 auth, incremental by `updated_at`, streams `/api/v2/tickets.json`, `/api/v2/users.json`, `/api/v2/organizations.json`. Rate limit: 400 req/min per account. Paginates via `next_page`.
- **`HubSpotConnector`** — private app token auth, incremental by `hs_lastmodifieddate`, streams `/crm/v3/objects/contacts`, `/crm/v3/objects/companies`, `/crm/v3/objects/deals`, `/crm/v3/objects/notes`. Rate limit: 100 req/10s. Paginates via `after` cursor. Property split between structured columns and `properties` JSONB overflow is **locked for Phase 1** (table below). Per Phase 0 decision #9, dashboardable/filterable/joinable/lens-predicate-relevant fields become columns; everything else lands in overflow.

**Locked HubSpot property split — Phase 1:**

| Object | Structured columns (dashboardable / filterable / joinable / lens predicate) | JSONB overflow |
|--------|---|---|
| **Companies** (`cip_companies`) | `hubspot_id`, `name`, `domain`, `country`, `state`, `city`, `zip`, `industry`, `lifecyclestage`, `type`, `numberofemployees`, `annualrevenue`, `hubspot_owner_id`, `createdate`, `hs_lastmodifieddate` | Custom fields, analytics properties (e.g., `hs_analytics_*`), integration metadata, source tracking |
| **Contacts** (`cip_contacts`) | `hubspot_id`, `email`, `firstname`, `lastname`, `phone`, `country`, `state`, `city`, `jobtitle`, `lifecyclestage`, `hs_lead_status`, `hs_language`, `hs_analytics_source`, `hubspot_owner_id`, `associatedcompanyid`, `createdate`, `hs_lastmodifieddate` | Form fill fields, marketing analytics, custom contact properties |
| **Deals** (`cip_deals`) | `hubspot_id`, `dealname`, `amount`, `closedate`, `dealstage`, `pipeline`, `dealtype`, `hubspot_owner_id`, `associatedcompanyid`, `associatedcontactids` (array), `createdate`, `hs_lastmodifieddate` | Probability scores, custom deal fields, weighted-value derivations |
| **Notes / engagements** (stored in `cip_tickets` or a dedicated `cip_notes` table — final table decision in Milestone 1) | `hubspot_id`, `hs_createdate`, `hs_lastmodifieddate`, `associated_object_type`, `associated_object_id`, `hubspot_owner_id` | Engagement type metadata; **note body** flows through the Knowledge ingester as text content, not a structured column |

**Why these specific columns:**
- `country` / `state` / `city` on companies + `country` / `hs_language` on contacts are the authoritative PS China View filter fields — must be columns.
- `email` on contacts is the dedup key — must be column.
- `associatedcompanyid` / `associatedcontactids` are join keys — must be columns.
- `hubspot_owner_id` lets us slice by Wayward rep in dashboards — must be column.
- `lifecyclestage` / `hs_lead_status` / `dealstage` / `pipeline` drive core dashboard tiles — must be columns.
- `amount` / `closedate` / `createdate` / `hs_lastmodifieddate` are dashboard + SCD keys — must be columns.

**Adding columns later:** if a field in overflow becomes dashboardable, add a structured column in a subsequent migration. The `cip_connector_property_registry` (see S7) tracks which fields have been promoted.

**What stress-tests the framework:** HubSpot's 4-object topology exercises relationship mapping, property overflow, and incremental keys; Zendesk's simpler shape validates the framework doesn't over-fit to HubSpot. If the framework can handle both without branching, it's general enough.

**Contract edit required:** `docs/subsystems/integration/CONTRACT.md` already has the R0031 note about this; when framework ships, update subsystem status PARTIAL → ACTIVE.

### S3. Unstructured Store — Knowledge + Graph consumption (D-119)

**No new subsystem work.** CIP consumes the existing Knowledge Subsystem and Graph Subsystem as-is.

**`cip_clients` population model:**

For Wayward, `cip_clients` is a 1:1 mirror of HubSpot companies. Every HubSpot company row becomes one `cip_clients` row at first HubSpot sync. No manual picking. No curated "first client" — the whole HubSpot company list is the subject-of-intelligence registry for Wayward. This is what Wayward's CIP actually means: every company Wayward tracks in HubSpot is a subject CIP has structured, unstructured, and original data about.

Mechanism: the HubSpot connector's company mapper writes **both** a `cip_companies` row (with all the HubSpot fields per the property split table above) **and** a `cip_clients` row (with `client_id`, `tenant_id=wayward-tenant-id`, `source_connector='hubspot'`, `source_id=hubspot_company_id`, `name=company.name`, `domain=company.domain`, authority=`ingested`). The two tables stay linked by `cip_clients.source_id = cip_companies.hubspot_id`. Future tenants may use a different `cip_clients` population strategy (manual curation, different connector mapping) — the 1:1 HubSpot-mirror is Wayward-specific.

Different tenants may define "subjects" differently. For Wayward, subjects = HubSpot companies. For Rocky Ridge (Phase 3), subjects would be visitors or members (whatever Rocky Ridge's CRM treats as its primary entity). `cip_clients` is the pattern; the population mapping is per-tenant config.

**Knowledge integration:**

- Add three `source_type` values to `knowledge_sources` table: `cip_zendesk_ticket`, `cip_hubspot_note`, `cip_client_document`.
- For each `cip_client` that has ingestible content (all of them for Wayward), create one `knowledge_sources` row per source_type with `tenant_id` scoping and ingestion_config JSONB capturing the connector's chunking defaults (D-055: 512 tokens ± 25%, 125 overlap).
- Ingestion flows through `knowledge_ingester_service.ingest_text_content(content, source_id, tenant_id, db)`. No changes to the ingester itself.
- Authority level on ingested chunks: `ingested` (this is the neutral source-origin value; `agent_discovered` is reserved for Phase 5 write-back).

**Graph integration:**

- Extend Wayward's `graph_templates` row with new node types: `Client`, `Ticket`, `Deal`, `Contact`, `Document`. New edge types: `SUPPORTS` (Client–Ticket), `PURCHASED` (Contact–Deal), `EMPLOYS` (Company–Contact), `ABOUT` (Note–any entity).
- Extraction runs via the existing `graph_extractor_service.extract_and_upsert(chunk_id, content, tenant_id, db)` post-vector hook. Non-fatal per D-067 — if FalkorDB is down, structured and knowledge writes still complete.

**`cip_files` glue:**

- Every document attachment (Zendesk ticket attachments, HubSpot notes with file refs, manually-uploaded client docs) creates one `cip_files` row. `cip_files.linked_chunk_ids` is a UUID[] column pointing to the `knowledge_chunks` rows derived from that file. R2 path in `cip_files.r2_path`.

### S4. Lens Engine — two lenses on same data (P-21 canonical example)

**Two `cip_views` rows** for Wayward's first `cip_client`:

- **EcomLever Full View**
  - `view_id` = generated UUID
  - `view_name` = "EcomLever Full View"
  - `filter_config` = `{}` (empty — unfiltered)
  - Audience: Ali, EcomLever ops

- **PS China View**
  - `view_id` = generated UUID
  - `view_name` = "PS China View"
  - `filter_config` = (provisional; finalized at kickoff) — likely shape: `{"language": ["zh-CN", "zh-TW"], "region": ["CN", "HK", "TW"], "org_tags": ["project-silk", "ps-partner"]}`
  - Audience: Project Silk team

**Filter resolution:** at query time, lens resolver applies `filter_config` as a WHERE predicate composed onto the base RLS-scoped query. No per-consumer SQL forks. No hardcoded "admin sees all" branches.

**Open decision for kickoff:** exact shape of PS China View `filter_config`. Needs Tim's sign-off on which HubSpot fields (company country? contact language? deal region?) and which Zendesk fields (organization tag? requester locale?) are authoritative for the China-facing filter. Draft in kickoff session, write into `filter_config` as a single decision commit.

### S5. Consumption Surfaces — Metabase only, with lens switcher

**Sole Phase 1 surface is Metabase.** REST API, chatbots, and MCP tools are Phase 2–3.

- Deploy Metabase connected to Foundry's shared PostgreSQL. Credentials scoped read-only to `cip_*` tables for the Wayward tenant.
- One Metabase "collection" per client (Wayward in Phase 1).
- Two dashboards backing the two lenses: "EcomLever Full View" dashboard and "PS China View" dashboard.
- Lens switcher: Metabase's dashboard-level filter, or (cleaner) a parameterized SQL question that resolves the `view_id` at runtime. Final UX decided during build — the important constraint is that switching lenses does not require a query rewrite, just a parameter change.
- Dashboards show: ticket volume, ticket aging, contact/company counts, deal pipeline, recent activity. Exact tiles sharpened during build, but they're all plain SQL against `cip_*` — no special Lens-Engine UI code in Phase 1.

### S6. Access & Operations — minimum viable

**Phase 1 ships the bare minimum to avoid tenant leaks; full maturity is Phase 6.**

- RLS policies on every `cip_*` table scoped by `tenant_id`. Migrations install them.
- `SET LOCAL app.current_tenant = '<uuid>'` middleware applied to every request that touches CIP tables. Metabase connection uses a service account with RLS bypass disabled.
- `cip_sync_runs` audit table — every connector run writes a row with `started_at`, `ended_at`, `status`, `rows_ingested`, `rows_history`, `error_detail` (JSONB).
- **Not in Phase 1:** retention policies, observability dashboards, per-connector health alerts, slow-query monitoring, backup/restore rehearsal. All deferred to Phase 6.

### S7. Discoverability (D-121)

Every Phase 1 artifact must be queryable by agents and scripts per NN-01 + STD-08:

- **Connectors:** Integration Mesh connector registry has rows for `zendesk_cip_v1` and `hubspot_cip_v1`.
- **Views:** `cip_views` has both rows.
- **Sync runs:** `cip_sync_runs` is the registry for itself.
- **Files:** `cip_files` is the registry for itself.
- **Chunks:** `knowledge_chunks.source_id` FK to `knowledge_sources` provides the join.
- **Source types:** new `source_type` values added to a `knowledge_source_types` enum or registry (whichever exists — verify against live schema during build).
- **Graph entities:** FalkorDB is self-registering via Cypher; graph_templates documents the schema.
- **Connector properties:** `cip_connector_property_registry` table (new in Phase 1, see below) — the authoritative map of where every ingested field lives.

If any of these is not queryable by `foundry_mcp_db_query` or equivalent at Phase 1 exit, D-121 is violated and it's a Phase 1 bug.

#### `cip_connector_property_registry` (Phase 1 table)

**Purpose:** answer the question "for connector X, object type Y, where do I find property Z?" — without the agent/analyst having to know the source system's schema. Populated at connector setup time by introspecting the source system's schema API. Refreshed on a schedule (TBD — likely weekly).

**Schema:**

| column | type | meaning |
|---|---|---|
| `registry_id` | uuid PK | row id |
| `tenant_id` | uuid FK | scope (RLS) |
| `connector` | text | `'hubspot'`, `'zendesk'`, etc. |
| `object_type` | text | `'companies'`, `'contacts'`, `'deals'`, `'notes'`, `'tickets'`, `'users'`, `'organizations'`, etc. |
| `property_name` | text | source system's property key (`hs_language`, `annualrevenue`, `custom_xyz`) |
| `property_type` | text | source system's type (`string`, `number`, `datetime`, `enumeration`, etc.) |
| `storage_location` | text | `'column'` or `'overflow'` |
| `column_name` | text nullable | if `storage_location='column'`, the CIP column name (may differ from property_name — e.g., normalization) |
| `cip_table` | text | target CIP table (`cip_companies`, `cip_contacts`, etc.) |
| `description` | text nullable | from source system's field metadata |
| `is_custom` | boolean | true if it's a tenant-custom property (e.g., a Wayward-specific HubSpot field) |
| `first_seen_at` | timestamptz | when this property was first observed |
| `last_synced_schema_at` | timestamptz | when the registry was last reconciled against the source system's schema |

**Usage pattern for agents:**

```sql
-- What's on a HubSpot company?
SELECT property_name, storage_location, column_name
FROM cip_connector_property_registry
WHERE connector = 'hubspot' AND object_type = 'companies' AND tenant_id = <wayward>
ORDER BY storage_location, property_name;

-- Then to query a specific field:
-- If storage_location='column':   SELECT <column_name> FROM cip_companies WHERE ...
-- If storage_location='overflow': SELECT properties->>'<property_name>' FROM cip_companies WHERE ...
```

**Phase 2+ layering:** a `foundry_mcp_cip_describe_properties(connector, object_type)` MCP tool wraps the registry query so agents call a tool instead of writing SQL. Phase 1 ships the registry table + population logic only. Phase 2/3 ships the tool.

**Why Phase 1 (not deferred):** without this registry, no agent and no ad-hoc analyst can find overflow fields without knowing HubSpot's schema intimately. That violates D-121 and NN-01 (discoverability). The registry is low-cost (one table + one population routine that runs at connector setup), high-leverage (every future connector reuses the pattern).

### S8. Non-negotiables

Enforced throughout Phase 1:

- **D-026** — every query scoped by `tenant_id`. No exceptions.
- **D-017** — no hardcoded agent or client names in code. All behavior from config.
- **D-018 / D-031 / D-077** — no direct LLM SDK imports. All model calls through LLM Roster.
- **CSS classification** — every new file has `# foundry: kind=X domain=Y`.
- **Timestamps UTC, UUIDs v4.**
- **Master branch only.** No feature branches, no PRs.

---

## PLAN — Execution Sequence

Eight weeks is a target, not a contract. Milestones are ordered by dependency, not calendar.

### Milestone 1 — Foundation (Week 1)

**Goal:** migrations apply cleanly, registry tables exist, tenant isolation verified.

- Apply migrations cip_01 through cip_08 + `cip_connector_property_registry` migration to dev DB. Verify RLS policies trip correctly on cross-tenant queries.
- Resolve notes/engagements table decision (dedicated `cip_notes` vs inclusion in `cip_tickets`) — Milestone 1 decision, write as part of migration cip_08 or a new cip_09.
- Write smoke test: insert a `cip_views` row, `SET LOCAL` to wrong tenant, expect zero rows back. No `cip_clients` rows needed yet — those auto-populate from HubSpot in Milestone 4.
- Add migration runbook to `docs/operations/` (cip_* migration procedure — idempotency, rollback).

**Exit:** dev environment has full CIP schema including property registry, Wayward tenant exists, RLS verified. `cip_clients` remains empty until HubSpot first sync.

### Milestone 2 — Connector Framework (Weeks 1–3)

**Goal:** `CIPConnector` Protocol, `CIPMapper` Protocol, and ingestion pipeline orchestrator live inside Integration Mesh.

- Define `CIPConnector` and `CIPMapper` ABCs in `platform/integration-mesh/src/connectors/cip/base.py`.
- Implement ingestion pipeline orchestrator with SCD differ and `cip_sync_runs` audit.
- Scaffold connector registry hooks.
- Write unit tests against two mock connectors (not Zendesk/HubSpot yet — fake shapes that exercise overflow, incremental keys, history diffing).

**Exit:** framework passes its own tests with synthetic data; no external-API calls yet.

### Milestone 3 — Zendesk Connector (Weeks 3–4)

**Goal:** Zendesk data flowing into `cip_tickets`, `cip_contacts`, `cip_companies` with history.

- Implement `ZendeskConnector` (auth, stream, rate limit, incremental cursor).
- Implement `ZendeskTicketMapper`, `ZendeskUserMapper`, `ZendeskOrgMapper`.
- First live sync against Wayward's Zendesk (read-only). Verify row counts, verify provenance columns populated, verify `cip_sync_runs` row written.
- Trigger post-vector hook against ticket bodies → Knowledge ingestion → Graph extraction. Confirm chunks land in Pinecone with `source_type='cip_zendesk_ticket'`.

**Exit:** live Wayward Zendesk data in `cip_*` tables, history captured on second sync, knowledge chunks in Pinecone, graph entities in FalkorDB.

### Milestone 4 — HubSpot Connector (Weeks 4–6) ⬅ LONGEST MILESTONE

**Goal:** HubSpot data flowing into `cip_contacts`, `cip_companies`, `cip_deals`, and notes target table. `cip_clients` auto-populates from HubSpot companies. History active from first sync. Property registry populated.

- Property split is **already locked** in S2 — no kickoff decision required. Build directly against the locked table.
- Implement `HubSpotConnector` with private app token auth.
- Implement `HubSpotContactMapper`, `HubSpotCompanyMapper`, `HubSpotDealMapper`, `HubSpotNoteMapper`. Company mapper writes **both** `cip_companies` **and** `cip_clients` (per S3 — one HubSpot company = one `cip_clients` row).
- **Introspect HubSpot schema API** at connector setup and populate `cip_connector_property_registry` with one row per HubSpot property across contacts, companies, deals, notes. Mark each row's `storage_location` per the S2 locked split; custom Wayward-specific properties that didn't appear in the split table get `storage_location='overflow'` automatically.
- First live sync against Wayward's HubSpot. Verify relationship mappings (contact → company, deal → contact/company, note → any) and that `cip_clients` has one row per HubSpot company.
- **Critical:** confirm history capture is working from the very first sync. Once the first sync lands, HubSpot's 20-revision retention clock has already ticked — any field that was at revision 19 yesterday and is at revision 20 today is lost if we didn't capture it. Run the first sync early in the milestone.

**Exit:** live Wayward HubSpot data in `cip_*` tables, `cip_clients` populated 1:1 from HubSpot companies, first sync run captures revision 20 of every property that had ≥ 20 changes, `cip_connector_property_registry` has a row for every HubSpot property encountered.

### Milestone 5 — Lens Engine + `cip_views` (Weeks 6–7)

**Goal:** two lenses registered, filter resolver working.

- Write both `cip_views` rows (EcomLever Full View, PS China View). PS China View `filter_config` finalized with Tim.
- Implement lens resolver — given a `view_id` and a base query, returns the filtered query. RLS-composed.
- Write integration tests: same underlying data, two queries via two views, different row counts, no per-consumer branching.

**Exit:** `SELECT * FROM cip_tickets WHERE <lens-applied>` returns correct rows for both lenses.

### Milestone 6 — Metabase (Week 7)

**Goal:** dashboards live, lens switcher working, Ali can use it.

- Deploy Metabase to staging (shared Foundry PostgreSQL).
- Create Wayward collection. Build two dashboards (one per lens).
- Wire lens switcher (parameter-based at dashboard level).
- Load test: full Wayward dataset, verify response times are reasonable (< 5s per tile is the Phase 1 target; optimization is Phase 6).

**Exit:** Ali opens staging Metabase, switches between lenses, data looks right.

### Milestone 7 — Demo + Lock (Week 8)

**Goal:** Phase 1 exit gate — Tim demos to Ali, Ali signs off, Phase 1 marked DONE.

- Tim walks Ali through both lenses.
- Collect Ali's first-round feedback. Anything that's "the filter is wrong" or "the dashboard is stale" gets fixed in Phase 1. Anything that's "I wish I could also see X" or "can we push this to Chatwoot" gets triaged into Phase 2.
- Phase 1 retrospective: what did the connector framework teach us? Did the Lens Engine abstraction survive first contact? What should Phase 2 sharpen?
- **WORKBENCH → `products/client-intelligence-platform/` move** — once Phase 1 ships, the project graduates to the governed location per FOUNDRY-TAXONOMY.md. This is a Tier 3 move (governed repo-path change); proposed to `pending-review.md` before execution.

**Exit:** Phase 1 LOCKED DONE. ROADMAP.md updated. PM scopes for the 6 lit pillars advance to "lit, producing ongoing work" status. Phase 2 VISION/WDGLL/SPEC/PLAN begins.

### Risks & contingencies

**R1. HubSpot auth or rate-limit issues delay Milestone 4.**
*Mitigation:* Milestone 4 starts first sync as early as possible. Even a partial first sync captures history from that moment onward. If HubSpot blocks us entirely, Phase 1 has to reshape — the 20-revision constraint is non-negotiable.

**R2. Knowledge/Graph subsystems prove incompatible with CIP content shape.**
*Mitigation:* the post-vector hook is non-fatal (D-067). If graph extraction chokes on ticket content, structured writes still complete. Knowledge ingestion is more important — if `ingest_text_content()` can't handle the content, we flag it, fix it in Knowledge, and proceed. CIP does not own the fix but does escalate.

**R3. Lens filter_config for PS China View is harder to pin down than expected.**
*Mitigation:* ship EcomLever Full View (empty filter — trivially correct) first. PS China View can be refined iteratively as Project Silk users look at early data and correct it. The key is that the Lens Engine *mechanism* works; the specific filter is tunable.

**R4. Metabase performance sags under full Wayward data.**
*Mitigation:* add indexes on hot query paths (tenant_id, client_id, source_id, updated_at). Materialized views are explicitly Phase 6 — Phase 1 just needs to not be embarrassing.

**R5. Appetite blows past 8 weeks.**
*Mitigation:* the lock is on *scope* (6 of 8 pillars lit), not weeks. If scope ships in 10 weeks, Phase 1 is still Phase 1. If weeks 9–10 arrive and scope isn't shipping, Atlas proposes a rescope to Tim (which pillar drops to minimum-minimum, what defers to Phase 1.5). The forbidden move is quietly widening scope to keep the 8-week calendar.

### Dependencies

- Integration Mesh subsystem must remain in its current state or move forward. No refactors during Phase 1 work.
- Knowledge Subsystem must remain in its current state (LIVE per CONTRACT.md). No breaking changes during Phase 1 work.
- Graph Subsystem must remain in its current state (LIVE per CONTRACT.md). No breaking changes during Phase 1 work.
- Wayward venture must provide Zendesk and HubSpot credentials in the first few days of Phase 1.
- Ali's availability for the Milestone 7 demo must be lined up by end of Milestone 5.

### What this plan does NOT commit to

- Exact week counts per milestone (estimates, not contracts).
- Specific Metabase tile layouts (decided during build, not locked here).
- Exact HubSpot property subset (decided at Milestone 4 kickoff, with Tim).
- Exact PS China View filter shape (decided with Tim during Milestone 5).
- A Phase 2 start date (that's a Phase 2 authoring decision).

---

## Cross-references

- `README.md` — Shape D pin + 8-pillar table + scope IDs
- `ROADMAP.md` — pillar-aligned phase sequence (this is Phase 1 of that roadmap)
- `architecture/ARCHITECTURE.md` — Phase 0 DDL + §13–§19 hardening layer
- `docs/DECISION-LOG.md` — D-117, D-118, D-119, D-120, D-121
- `docs/architecture/principles/DESIGN-PRINCIPLES.md` — P-21 (Multi-Lens by Default)
- `docs/subsystems/integration/CONTRACT.md` — framework host
- `docs/subsystems/knowledge/CONTRACT.md` — Knowledge consumer notes (D-119)
- `docs/subsystems/graph/CONTRACT.md` — Graph consumer notes (D-119)

## Authoring note

This doc is the working plan for CIP Phase 1. When Phase 1 kicks off (Milestone 1), this doc becomes the execution reference. Milestones get tracked as PM tasks under the 6 lit pillar scopes. Status updates land as `pm_task_update` + `pm_comment`, not as edits to this doc. The doc itself updates only when scope changes — and scope changes require real-time Tim authorization (Tier 3).
