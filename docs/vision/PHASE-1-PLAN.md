---
id: CIP-SPEC-005
uuid: e4f3107c-b6b7-4575-9433-4942673bf748
title: 'CIP Phase 1 — Plain Jane: Tenant-Neutral Blank-Slate Product'
type: spec
owner: tim
solve_for: Phase 1 binding plan — milestone-by-milestone execution plan that produced
  the foundation we have today.
stage_label: adopt
domain: meta
version: '1.0'
created: '2026-04-17'
last_modified: '2026-04-20'
last_reviewed: '2026-05-16'
review_cadence: 365
project_id: client-intelligence-platform
pm_project_id: 596825db-61bc-4899-bc6c-e207489ca35d
phase: 1
shape: plain-jane
authors:
- tim
- atlas
supersedes: '(1) 2026-04-17 Shape D (Wayward-as-primary-tenant + Zendesk/HubSpot connectors
  bundled into Phase 1) — rescoped 2026-04-20 per Tim''s "plain jane CIP" directive.
  Wayward specifics moved to Phase 2 Wayward Onboarding. Rocky Ridge remains Phase
  3. (2) 2026-04-20 evening cip_09 insertion (cross-tenant grants schema-only in Phase
  1) — moved to Phase 3 so Phase 1 ships pure plain-jane plumbing. Grants schema +
  runtime both live in Phase 3 where the multi-tenant proof actually exercises them.

  '
appetite: session-bound (milestone-ordered, not week-ordered)
primary_tenant: none — fixture tenant only (synthetic deterministic data)
locks:
- D-117
- D-118
- D-119
- D-120
- D-121
- P-21
pillars_lit:
- ingestion-framework
- structured-store
- unstructured-store
- lens-engine
- consumption-surfaces-partial
- access-ops-minimum
pillars_dark:
- push-sync
- intelligence-alerts
consumer_acceptance: fixture-tenant-demo-shows-two-lenses-switching + ten-doc-suite-published
  + four-access-paths-validated
---

# CIP Phase 1 — Plain Jane: Tenant-Neutral Blank-Slate Product

> Authors Phase 1 in Atlas's four-section shape: **VISION** (why this phase exists), **WDGLL** (what done looks like), **SPEC** (technical requirements), **PLAN** (execution sequence).
>
> Phase 0 is COMPLETE. Phase 2 (Wayward Onboarding) and Phase 3 (Rocky Ridge + Multi-Tenant + Cross-Tenant Grants Runtime) each get their own VISION/WDGLL/SPEC/PLAN when their turn comes.

---

## VISION — Why Phase 1 Exists

### The bet

Phase 1 bets that if we ship a **generic, tenant-neutral blank-slate CIP product**, validated end-to-end against a **synthetic fixture dataset**, and paired with a complete documentation suite sufficient for a second person to onboard any reasonable tenant without Atlas or Tim in the room — we will have proved four things at once:

1. **The CIPConnector / CIPMapper abstraction is real.** A `FixtureConnector` proves the Protocol without burning API quota, leaking real data, or waiting on external-system auth. Phase 2 plugs HubSpot and Zendesk into the same Protocol. If HubSpot/Zendesk can't fit the Protocol, that's a Phase 2 bug, not a Phase 1 redesign.
2. **The Lens Engine is real.** Two lenses on one fixture dataset is the minimum validation of P-21. Lens-A is unfiltered; Lens-B applies a single-dimension fixture filter. Same rows underneath, two legitimately different views on top.
3. **The three data layers compose.** Fixture originals (files in R2) → Derived Knowledge (chunks + graph entities) → Structured Data (cip_* rows) all line up for a single fixture client without the layers leaking into each other.
4. **The documentation is real.** Ten doc artifacts ship alongside the code, battle-tested by being used during the fixture build itself. If a doc is wrong, the fixture build exposes it; the doc gets revised before Phase 2 meets real data.

If those four claims hold under fixture conditions, Phase 2 (Wayward) is a **configuration and wiring exercise**, not a redesign. If they fail, we find out against synthetic data — where failure is cheap — not against Wayward's live HubSpot revision clock.

### Why tenant-neutral (not Wayward-first)

The prior Phase 1 shape ("Shape D") bundled Wayward's specific connectors and lenses into Phase 1. That conflates two problems: *building the product* and *onboarding a tenant to the product*. When those two problems ship together, the product carries Wayward-shaped fingerprints it shouldn't — a tenant-specific `cip_clients` population rule, tenant-specific property splits, tenant-specific lens filters. The product that ships at the end of Phase 1 must be the product that Rocky Ridge in Phase 3 can adopt without asking "which of these decisions are mine to make?"

Plain-jane Phase 1 separates those concerns:
- **Phase 1 = build the blank-slate product.** FixtureConnector stands in for any real connector. Two generic lenses prove the Lens Engine mechanism. Migrations are tenant-agnostic. Docs are written to the product, not to a tenant.
- **Phase 2 = onboard Wayward** (real HubSpot + Zendesk connectors, EcomLever + PS lenses, Wayward push targets). Uses the docs Phase 1 produced. Where the docs broke, Phase 2 hardens them.
- **Phase 3 = onboard Rocky Ridge and light up the cross-tenant grants runtime.** Uses the twice-hardened docs. Proves multi-tenant isolation.

This is the "shrink-wrap" frame: Phase 1 makes the box you can hand to a new engineer.

### The HubSpot 20-revision retention tradeoff

HubSpot retains only the last 20 property revisions per record. Every day Wayward runs without CIP history capture is permanent intelligence loss. Shape D put HubSpot in Phase 1 explicitly to start the capture clock as early as possible. Plain-jane Phase 1 delays the capture start because real HubSpot connector ships in Phase 2.

**Mitigation:** Phase 2 Wayward Onboarding runs HubSpot connector implementation as its longest-critical-path milestone (earliest start, first live sync early in the milestone). If the gap between Phase 1 exit and Phase 2 HubSpot first-sync is unacceptably long, an optional "HubSpot backup tape" mini-project can run in parallel with Phase 1 — a minimal script that dumps current HubSpot state to R2 daily, not through the CIP framework, so that when Phase 2's connector lands we can backfill history from the tapes. Decision on whether to run the tape is Tim's; scope it at Phase 1 kickoff if it feels urgent.

### What Phase 1 is NOT

- Not a tenant-specific build — that's Phase 2 (Wayward) and Phase 3 (Rocky Ridge).
- Not a push-target replacement — Chatwoot routing, Twenty CRM sync, Drive exports all ship in Phase 2 as part of Wayward's full round-trip.
- Not a second-tenant proof — Phase 3.
- Not a chatbot, REST, or MCP surface — Phase 4 (MCP + REST), Phase 5 (Chatbot).
- Not cross-tenant grants schema — moved to Phase 3 alongside the runtime, so the schema and the runtime ship together and the multi-tenant harness exercises them together.
- Not observability maturity — `cip_sync_runs` audit and RLS + SET LOCAL enforcement are the entire governance footprint. Full maturity is Phase 8.

### Primary consumer

**The fixture tenant.** Phase 1 has no human consumer on the acceptance path — the acceptance test is Tim (or any engineer) opening Metabase against the fixture tenant, switching lenses, and seeing the fixture data resolve correctly under both lenses. Ali (Wayward/EcomLever ops) is the Phase 2 acceptance consumer; she does not evaluate Phase 1.

---

## SOLVE FOR — The Plain-Jane Product

The product shipping at Phase 1 exit is a tenant-agnostic CIP platform that a competent engineer could, armed with the ten-doc suite, onboard any reasonable tenant onto without Atlas or Tim intervening. That engineer can:

1. Provision a new tenant via the **Tenant Onboarding Checklist** (one-command-or-close).
2. Register a new connector via the **Connector Authoring Guide** (subclass CIPConnector + CIPMapper, drop into Integration Mesh, pass the connector-conformance test harness).
3. Define a new lens via the **Lens Authoring Guide** (write a `cip_views` row with `filter_config` JSONB, verify it composes correctly with RLS).
4. Add a new structured column via the **Migration Runbook** (new `cip_N+1` migration following the naming + RLS + history-table + CSS-tag convention).
5. Debug a tenant leak via the **RLS & SET LOCAL Operator Guide**.
6. Monitor sync health via the **Sync Orchestrator Operator Guide**.
7. Understand which retrieval path returns what via the **Four Access Paths Reference**.
8. Stand up or reset a fixture for local dev via the **Fixture Tenant Handbook**.
9. Know which Kind/Domain tags a new `cip_*` file needs via the **CIP CSS Classification Contract**.
10. Hand the product off to the next phase via the **Phase 1 → Phase 2 Handoff Doc**.

Those ten artifacts are the product alongside the code. A product that ships without them is half a product.

### Why FixtureConnector exists

FixtureConnector is the Phase 1 implementation of the `CIPConnector` Protocol. Its job is to stand in for any real connector so that the framework, the Lens Engine, Metabase, the registry, and the four access paths can all be exercised end-to-end without depending on external APIs or real tenant data.

Fixture data is deterministic: seeding the fixture DB produces identical row IDs, identical chunk content, identical graph entities every time. Two lenses applied to the fixture yield known-good row sets that the lens-test harness checks against golden-file expectations.

The fixture tenant's `cip_clients` are mock companies with mock contacts, mock tickets, mock deals, and mock documents. The fixture mimics a "CS support" shape generically — it has a single region dimension (so Lens-B can filter by region) and a single language dimension (so agents can test graph-hop queries that cut across dimensions). It does not mimic Wayward's actual data.

### What the plain jane solves for

- **Connector framework proof.** If FixtureConnector can be subclassed into a real connector by following the Connector Authoring Guide alone, Phase 2 onboarding is a mechanical build. If it can't, Phase 1 has a Protocol bug that Phase 2 would have paid for.
- **Lens Engine proof.** Two lenses on fixture data proves the resolver composes filter_config + RLS + lens without per-consumer SQL forks.
- **Documentation proof.** The fixture build exercises every doc by using it during the build. Docs that don't match the code get updated before Phase 2.
- **Discoverability proof.** Every Phase 1 artifact is queryable through registries — `cip_connector_property_registry`, `cip_views`, `cip_sync_runs`, `cip_files`, `knowledge_sources`, `graph_templates`. If an agent or analyst needs CIP-specific tooling to find something, that's a registry gap, not a feature.
- **Four-access-paths proof.** A cold-start Cowork or Claude Code session, holding only generic `foundry_mcp_*` tools, can light up all four access paths (Structured, Derived-Knowledge-vector+BM25, Derived-Knowledge-graph, Originals) against the fixture tenant.

---

## WDGLL — What Done Looks Like

Phase 1 exits when **all** of the following are observable:

### Code deliverables

1. **Migrations cip_01 through cip_08** applied to dev DB. Schema matches `architecture/ARCHITECTURE.md` §2–§12 exactly. RLS policies active from cip_01. No `cip_09` in Phase 1 — cross-tenant grants schema ships in Phase 3.
2. **`CIPConnector` and `CIPMapper` Protocols** live in `platform/integration-mesh/src/connectors/cip/`. Protocols carry no Wayward-specific hints.
3. **Ingestion pipeline orchestrator** wraps connector + mapper + DB writer + SCD differ + `cip_sync_runs` audit. One entry point: `run_sync(connector_id, tenant_id, client_id, db)`.
4. **`FixtureConnector` + `FixtureMapper`** implement the Protocols against synthetic deterministic data. Fixture schema covers companies, contacts, tickets, deals, documents with region + language dimensions.
5. **Fixture DB seeder** — `scripts/seed_fixture_tenant.py` produces a repeatable fixture tenant with known row IDs. Reset by running the seeder again (idempotent).
6. **`cip_connector_property_registry`** table exists (migration cip_08 or adjacent), populated by `FixtureConnector` at setup.
7. **Two `cip_views` rows** on the fixture tenant: `Lens-A Full View` (empty filter) and `Lens-B Region-EMEA View` (filter: `region='EMEA'`). Any region value works; EMEA is the convention.
8. **Metabase deployed as a platform service** (not tenant-specific) against the fixture tenant. Two dashboards, one per lens. Lens switcher wired via parameter.
9. **`cip_sync_runs`** written on every fixture sync. Row counts, started_at, ended_at, status.
10. **Knowledge + Graph integration** — fixture document/ticket/note text flows through `knowledge_ingester_service.ingest_text_content()`. Chunks land in Pinecone under the fixture tenant's namespace. Graph extraction runs via the non-fatal post-vector hook (D-067). New node/edge types registered in `graph_templates` for the fixture tenant.
11. **RLS + SET LOCAL** verified on every `cip_*` table via smoke test (set wrong tenant, expect zero rows).
12. **Four-access-paths validation report** committed at `validation/M7-discoverability-report.md` with pass/fail per path against the fixture tenant.

### Documentation suite (the 10 artifacts)

All ten exist, exercised against the fixture build, reviewed by Tim before Phase 1 exit:

1. **Tenant Onboarding Checklist** — `docs/cip/TENANT-ONBOARDING-CHECKLIST.md`. Step-by-step from "tenant row insert" through "first sync succeeds" through "first dashboard loads."
2. **Connector Authoring Guide** — `docs/cip/CONNECTOR-AUTHORING-GUIDE.md`. Protocol surface, incremental-sync contract, cursor management, property-registry registration, error handling, rate limiting, SCD-2 history pattern, pytest harness. FixtureConnector is the reference implementation.
3. **Lens Authoring Guide** — `docs/cip/LENS-AUTHORING-GUIDE.md`. `filter_config` JSONB shape, RLS interaction, audience scoping, Metabase wiring, fixture-based lens test pattern.
4. **Migration Runbook** — `docs/cip/MIGRATION-RUNBOOK.md`. Naming convention, RLS attachment, history-table pattern, rollback posture, CSS classification, Alembic vs raw-SQL posture.
5. **RLS & SET LOCAL Operator Guide** — `docs/cip/RLS-SET-LOCAL-OPERATOR-GUIDE.md`. How tenant isolation works, how to verify at runtime, how to debug a suspected leak, session-initialization pattern for every cip_* request handler.
6. **Sync Orchestrator Operator Guide** — `docs/cip/SYNC-ORCHESTRATOR-GUIDE.md`. How `cip_sync_runs` works, how to monitor, how to debug stuck/failed syncs, retry semantics.
7. **Four Access Paths Reference** — `docs/cip/FOUR-ACCESS-PATHS.md`. What each path returns, which lens applies, expected latency, sample queries. Reference for Phase 4 (MCP+REST) builders and Phase 5 (Chatbot) builders.
8. **Fixture Tenant Handbook** — `docs/cip/FIXTURE-TENANT-HANDBOOK.md`. How FixtureConnector works, how to extend fixtures, how to reset the fixture DB, what the access-paths validation exercises.
9. **CIP CSS Classification Contract** — `docs/cip/CSS-CLASSIFICATION-CONTRACT.md`. Kind/Domain tags for new `cip_*` files (migrations, connector code, lens code, push code). Extends `docs/subsystems/meta/classification-contract.md`.
10. **Phase 1 → Phase 2 Handoff Doc** — `docs/cip/PHASE-1-TO-PHASE-2-HANDOFF.md`. What Phase 2 inherits, what it must author, what it's allowed to change vs. what it must leave alone. Prevents scope creep in Phase 2.

### Non-criteria (intentional)

- **No real connectors (HubSpot, Zendesk, anything).** Phase 2.
- **No push targets (Chatwoot, Twenty, Drive).** Phase 2.
- **No second tenant.** Phase 3.
- **No cross-tenant grants** (neither schema nor runtime). Phase 3.
- **No REST API, chatbot, or MCP tools.** Phase 4 / Phase 5.
- **No freshness decay surfacing in Metabase.** Freshness is computed and stored per Phase 0; visualization is Phase 6.
- **No anomaly detection.** Phase 6.
- **No dedicated CIP database.** Phase 8.

### Exit gate

Phase 1 exits when:
- Tim (or any engineer) opens Metabase against the fixture tenant, switches between Lens-A and Lens-B, and sees the fixture data resolve correctly under both lenses.
- The four-access-paths validation report is green (all four paths light up against the fixture tenant).
- All ten doc artifacts are committed and reviewed.
- Claude Code or another agent, acting on PHASE-1-PLAIN-SPEC.md (the SPEC handoff doc) with no additional context, produces a passing validation run — proof the doc suite is self-sufficient.

---

## SPEC — Technical Requirements

### S1. Database migrations (cip_01 → cip_08)

Each migration is a single Alembic file under `migrations/versions/`. All tables carry the 9 provenance columns and a matching `_history` table for SCD Type 2. DDL is authoritative in `architecture/ARCHITECTURE.md` §2–§12.

- **cip_01** — `cip_clients` + `cip_clients_history` (subjects-of-intelligence; separate from `tenants`).
- **cip_02** — `cip_views` + `cip_views_history` (lens config rows with `filter_config` JSONB).
- **cip_03** — `cip_sync_runs` (append-only audit, no history table).
- **cip_04** — `cip_files` + `cip_files_history` (metadata registry linking R2 originals → derived chunks).
- **cip_05** — `cip_contacts` + `cip_contacts_history` (generic contact shape; Phase 2 maps HubSpot contacts here).
- **cip_06** — `cip_companies` + `cip_companies_history` (generic company shape).
- **cip_07** — `cip_deals` + `cip_deals_history` (generic deal shape).
- **cip_08** — `cip_tickets` + `cip_tickets_history` **+ `cip_connector_property_registry`** (discoverability table, see S8).

Migrations ship with RLS policies enabled from cip_01. No table exists without tenant scoping.

**cip_09 (`cip_cross_tenant_grants`) does not ship in Phase 1.** It moves to Phase 3 where schema and runtime light up together under the multi-tenant proof harness.

### S2. Ingestion & Connectors — generic framework inside Integration Mesh (D-118)

**Location:** `platform/integration-mesh/src/connectors/cip/`. The connector framework is a platform capability hosted in Integration Mesh; CIP's first instance is FixtureConnector.

**Framework deliverables:**

- **`CIPConnector` Protocol** — abstract interface with methods: `authenticate()`, `stream_records(cursor, batch_size)`, `describe_schema()`, `rate_limit_policy`, `incremental_key()`. Implementations are swappable. No Wayward-specific hints.
- **`CIPMapper` Protocol** — abstract interface that transforms source records into `cip_*` rows. Methods: `map(record) -> Iterable[CIPRow]`, `overflow_fields() -> list[str]`, `authority() -> str`.
- **Ingestion pipeline orchestrator** — wraps connector + mapper + DB writer + SCD differ + `cip_sync_runs` audit. One entry point: `run_sync(connector_id, tenant_id, client_id, db)`.
- **Graph/Knowledge post-hook** — after structured writes land, the orchestrator calls `knowledge_ingester_service.ingest_text_content()` for any text fields marked `ingest_as_knowledge=True` in the mapper. Graph extraction runs via the existing non-fatal post-vector hook (D-067).
- **Connector-conformance test harness** — generic pytest fixtures that any `CIPConnector` subclass can use to verify Protocol compliance (incremental sync works, property registry populates, SCD diffs produce `_history` rows, `cip_sync_runs` writes are well-formed). Phase 2 HubSpot/Zendesk connectors get this harness for free.

**Phase 1 connector instance:** `FixtureConnector` only. Real-world connectors are Phase 2+.

### S3. FixtureConnector — synthetic deterministic data

**Purpose:** stand in for any real connector so the framework, lenses, Metabase, registry, and four access paths can all be exercised end-to-end without external dependencies.

**Location:** `platform/integration-mesh/src/connectors/cip/fixture/`.

**Fixture data shape** (tenant-agnostic but structurally complete):

- ~50 mock **companies**, each with `region` ∈ {EMEA, AMER, APAC, LATAM}, `language` ∈ {en, zh, es, fr, de, pt, ja}, `industry` ∈ {retail, saas, manufacturing, services}.
- ~200 mock **contacts** linked to companies via `associated_company_id`.
- ~300 mock **deals** linked to contacts and companies.
- ~500 mock **tickets** with subjects/bodies generated from a small deterministic template set (so Knowledge chunks have real-looking text).
- ~100 mock **documents** as small text files uploaded to R2 under the fixture tenant namespace.
- ~50 mock **notes** attached to companies/deals/tickets with body text.

**Determinism:** Seeded by a single random seed declared in `scripts/seed_fixture_tenant.py`. Re-seeding produces byte-identical fixture state. Row IDs are derived from hash of (entity_type, sequence_index, seed) so they're stable across re-seeds.

**`cip_clients` population:** one `cip_clients` row per fixture company. Mirrors the Phase 2 Wayward pattern of "one company = one subject of intelligence" without locking any tenant into that pattern — the Connector Authoring Guide explicitly notes that other tenants may define `cip_clients` differently (e.g., Rocky Ridge in Phase 3 might use members or visitors).

**Schema introspection:** `FixtureConnector.describe_schema()` returns a well-formed schema used to populate `cip_connector_property_registry` automatically at connector setup — no manual registry authoring required.

**Fixture reset:** `python scripts/seed_fixture_tenant.py --reset` wipes the fixture tenant and re-seeds. Documented in the Fixture Tenant Handbook.

### S4. Unstructured Store — Knowledge + Graph consumption (D-119)

**No new subsystem work.** CIP consumes the existing Knowledge Subsystem and Graph Subsystem.

**Knowledge integration:**

- Add three `source_type` values to `knowledge_sources` table: `cip_fixture_ticket`, `cip_fixture_note`, `cip_fixture_document`. Phase 2 adds the real-connector analogues (`cip_zendesk_ticket`, `cip_hubspot_note`, `cip_client_document`).
- For each fixture `cip_client`, one `knowledge_sources` row per source_type with `tenant_id=fixture_tenant_id` and ingestion_config JSONB capturing chunking defaults (D-055: 512 tokens ± 25%, 125 overlap).
- Ingestion flows through `knowledge_ingester_service.ingest_text_content(content, source_id, tenant_id, db)`. No changes to the ingester.
- Authority on ingested chunks: `ingested`.

**Graph integration:**

- Fixture tenant's `graph_templates` row has node types: `Client`, `Ticket`, `Deal`, `Contact`, `Document`, `Note`. Edge types: `SUPPORTS` (Client–Ticket), `PURCHASED` (Contact–Deal), `EMPLOYS` (Company–Contact), `ABOUT` (Note–any entity).
- Extraction runs via the existing `graph_extractor_service.extract_and_upsert(chunk_id, content, tenant_id, db)` post-vector hook. Non-fatal per D-067.

**`cip_files` glue:**

- Every fixture document creates one `cip_files` row. `cip_files.linked_chunk_ids` is a UUID[] column pointing to the `knowledge_chunks` rows derived from that file. R2 path in `cip_files.r2_path`.

### S5. Lens Engine — two lenses on fixture data (P-21 canonical example)

**Two `cip_views` rows** on the fixture tenant:

- **`Lens-A Full View`**
  - `view_id` = generated UUID (recorded in the seeder for deterministic lookup)
  - `view_name` = "Lens-A Full View"
  - `filter_config` = `{}` (empty — unfiltered)

- **`Lens-B Region-EMEA View`**
  - `view_id` = generated UUID (recorded in the seeder)
  - `view_name` = "Lens-B Region-EMEA View"
  - `filter_config` = `{"region": "EMEA"}` (single-dimension filter)

**Filter resolution:** at query time, the lens resolver applies `filter_config` as a WHERE predicate composed onto the base RLS-scoped query. No per-consumer SQL forks. No hardcoded "admin sees all" branches.

**Lens test harness:** for each lens, compare the returned row set to a golden-file expectation. Lens-A returns all fixture rows; Lens-B returns only rows where the underlying company's `region='EMEA'`. Golden files live in `tests/fixtures/lens/`.

### S6. Consumption Surfaces — Metabase only, deployed as a platform service

**Sole Phase 1 surface is Metabase.** REST API, chatbots, and MCP tools are Phase 4 / Phase 5.

- Deploy Metabase **as a platform service** (not tenant-specific; future tenants plug into the same Metabase instance). Connect to Foundry's shared PostgreSQL. Credentials scoped read-only to `cip_*` tables.
- One Metabase collection for the fixture tenant.
- Two dashboards backing the two lenses: `Lens-A Full View` dashboard and `Lens-B Region-EMEA View` dashboard.
- Lens switcher: parameterized SQL question resolving `view_id` at runtime. Switching lenses is a parameter change, not a query rewrite.
- Dashboards show: ticket volume, ticket aging, contact/company counts, deal pipeline, recent activity. Exact tile layouts sharpened during build.

### S7. Access & Operations — minimum viable

**Phase 1 ships the bare minimum to avoid tenant leaks; full maturity is Phase 8.**

- RLS policies on every `cip_*` table scoped by `tenant_id`. Migrations install them.
- `SET LOCAL app.current_tenant = '<uuid>'` middleware applied to every request that touches CIP tables. Metabase connection uses a service account with RLS bypass disabled.
- `cip_sync_runs` audit table — every connector run writes a row with `started_at`, `ended_at`, `status`, `rows_ingested`, `rows_history`, `error_detail` (JSONB).
- **Not in Phase 1:** retention policies, observability dashboards, per-connector health alerts, slow-query monitoring, backup/restore rehearsal. All deferred to Phase 8.

### S8. Discoverability (D-121)

Every Phase 1 artifact must be queryable by agents and scripts per NN-01 + STD-08:

- **Connectors:** Integration Mesh connector registry has a row for `cip_fixture_v1`.
- **Views:** `cip_views` has both Phase 1 rows on the fixture tenant.
- **Sync runs:** `cip_sync_runs` is the registry for itself.
- **Files:** `cip_files` is the registry for itself.
- **Chunks:** `knowledge_chunks.source_id` FK to `knowledge_sources` provides the join.
- **Source types:** new `source_type` values registered as described in S4.
- **Graph entities:** FalkorDB self-registers via Cypher; `graph_templates` documents the schema.
- **Connector properties:** `cip_connector_property_registry` table (Phase 1, in migration cip_08) — authoritative map of where every ingested field lives.

If any of these is not queryable by `foundry_mcp_db_query` or equivalent at Phase 1 exit, D-121 is violated and it's a Phase 1 bug.

#### `cip_connector_property_registry`

**Schema:**

| column | type | meaning |
|---|---|---|
| `registry_id` | uuid PK | row id |
| `tenant_id` | uuid FK | scope (RLS) |
| `connector` | text | `'fixture'`, later `'hubspot'`, `'zendesk'`, etc. |
| `object_type` | text | `'companies'`, `'contacts'`, `'deals'`, `'tickets'`, `'notes'`, `'documents'` |
| `property_name` | text | source system's property key |
| `property_type` | text | `string` / `number` / `datetime` / `enumeration` / ... |
| `storage_location` | text | `'column'` or `'overflow'` |
| `column_name` | text nullable | if `storage_location='column'`, the CIP column name |
| `cip_table` | text | target CIP table |
| `description` | text nullable | from source system's field metadata |
| `is_custom` | boolean | true if tenant-custom |
| `first_seen_at` | timestamptz | |
| `last_synced_schema_at` | timestamptz | |

**Populated at connector setup** by `FixtureConnector.describe_schema()` introspection. Phase 2 HubSpot/Zendesk connectors populate via their own introspection following the Connector Authoring Guide.

### S9. Documentation Suite (the 10 artifacts)

All ten doc artifacts listed in WDGLL are Phase 1 deliverables. Doc-build discipline:

- **M0**: author doc **skeletons** (section headers, TODO markers, required-sections list). No content yet. Skeletons live in `docs/cip/` from M0 forward.
- **M1–M6**: fill in each doc as the milestone that produces its subject matter completes. The Migration Runbook fills in during M1. The Connector Authoring Guide fills in during M2–M3 (framework + FixtureConnector). The Lens Authoring Guide fills in during M4. The Fixture Tenant Handbook fills in during M3. The Sync Orchestrator Guide fills in during M2. The RLS & SET LOCAL Operator Guide fills in during M1. Etc.
- **M7**: doc suite hardening pass. Every doc is read end-to-end by Tim (or a fresh reviewer) and any gap that would block a second engineer from onboarding a tenant using the doc alone becomes an M7 fix.
- **M8**: doc suite locked at Phase 1 exit. Phase 2 Wayward Onboarding hardens them further as they meet real data for the first time.

**Doc best-practices-first:** all ten docs follow the same skeleton (Purpose / Audience / When to use / Step-by-step / Common pitfalls / Where to get help). Enforced by a template doc at `docs/cip/_TEMPLATE.md`.

### S10. Claude Code Handoff

Phase 1 execution assumes Claude Code (or equivalent agent) does the actual code writing, supervised by Tim + Atlas. The handoff mechanism:

- Atlas authors **`PHASE-1-PLAIN-SPEC.md`** — a single SPEC doc containing everything Claude Code needs: acceptance criteria, file-path conventions, FixtureConnector shape, RLS patterns, fixture DB seed layout, forbidden imports (raw LLM SDKs per D-018/D-031/D-077), CSS tag requirements, test-harness conventions.
- Claude Code (architect subagent) reads `PHASE-1-PLAIN-SPEC.md` and summarizes its understanding before writing a single line of code.
- Atlas reviews the architect's summary. Any mismatch = Atlas corrects the SPEC (preferred) or explains the gap to Tim (if the mismatch exposes a plan hole).
- Iterate until alignment is tight. Then Claude Code builder subagent begins implementation, milestone by milestone.
- Claude Code reviewer subagent validates each milestone against the SPEC before marking it done.

This closes the "Atlas can't write code" loop: Atlas authors the SPEC; Claude Code writes the code; Atlas and Tim validate the output against the SPEC.

### S11. Non-negotiables

Enforced throughout Phase 1:

- **D-026** — every query scoped by `tenant_id`. No exceptions.
- **D-017** — no hardcoded tenant, client, or connector names in code. All behavior from config.
- **D-018 / D-031 / D-077** — no direct LLM SDK imports. All model calls through LLM Roster.
- **CSS classification** — every new file has `# foundry: kind=X domain=Y`.
- **Timestamps UTC, UUIDs v4.**
- **Master branch only.** No feature branches, no PRs.

---

## PLAN — Execution Sequence

Milestones are ordered by dependency. No week-based appetites: Phase 1 is session-bounded and paced by what actually produces output. If a milestone wraps in one session, start the next. If it takes three, take three.

### Milestone 0 — Vision Lock + Doc Skeletons

**Goal:** Phase 1 plain-jane scope is locked, all ten doc skeletons exist.

- Confirm scope matches this plan (Tim + Atlas).
- Create `docs/cip/_TEMPLATE.md` skeleton.
- Create all ten doc skeletons in `docs/cip/` (headers + TODO markers only — no content).
- Author `PHASE-1-PLAIN-SPEC.md` (the Claude Code handoff doc).

**Exit:** doc skeletons exist, SPEC handoff doc exists, Claude Code architect confirms SPEC understanding back to Atlas.

### Milestone 1 — Foundation (migrations + RLS verify)

**Goal:** migrations apply cleanly, registry table exists, tenant isolation verified.

- Apply migrations cip_01 through cip_08 + `cip_connector_property_registry` (inside cip_08) to dev DB. Verify RLS policies trip correctly on cross-tenant queries.
- Create `fixture_tenant` row in `tenants` (Foundry-owned, type=`fixture`).
- Write smoke tests: insert a dummy `cip_clients` row under fixture tenant, `SET LOCAL` to wrong tenant, expect zero rows back.
- Fill in: **Migration Runbook** and **RLS & SET LOCAL Operator Guide**.

**Exit:** dev environment has full CIP schema (through cip_08), fixture tenant exists, RLS verified. Two docs drafted.

### Milestone 2 — Generic Connector Framework

**Goal:** `CIPConnector` and `CIPMapper` Protocols + ingestion pipeline orchestrator + connector-conformance test harness.

- Define Protocols in `platform/integration-mesh/src/connectors/cip/base.py`. No tenant-specific hints.
- Implement ingestion pipeline orchestrator with SCD differ and `cip_sync_runs` audit.
- Scaffold connector registry hooks.
- Build connector-conformance test harness (pytest fixtures any subclass can use).
- Fill in: **Connector Authoring Guide** and **Sync Orchestrator Operator Guide** (using the framework itself as the reference implementation).

**Exit:** framework passes its own tests against mock Protocol implementations. Two more docs drafted.

### Milestone 3 — FixtureConnector + Fixture DB Seeder

**Goal:** deterministic synthetic data flowing through the framework end-to-end.

- Implement `FixtureConnector` + `FixtureMapper` against the fixture shape in S3.
- Implement `scripts/seed_fixture_tenant.py` (idempotent re-seeder with `--reset` flag).
- Run first fixture sync. Verify row counts, provenance columns, `cip_sync_runs` row, SCD history on second sync (after seeder modifies a known field).
- Trigger post-vector hook against fixture ticket/note/document bodies → Knowledge ingestion → Graph extraction. Confirm chunks in Pinecone with `source_type='cip_fixture_*'`.
- Populate `cip_connector_property_registry` via `FixtureConnector.describe_schema()`.
- Fill in: **Fixture Tenant Handbook** and **CIP CSS Classification Contract**.

**Exit:** fixture tenant has populated `cip_*` tables, history captured on second sync, chunks in Pinecone, graph entities in FalkorDB, registry populated. Two more docs drafted.

### Milestone 4 — Lens Engine on Fixture Data

**Goal:** two lenses registered, filter resolver working, lens-test harness green.

- Seeder inserts both `cip_views` rows on the fixture tenant.
- Implement lens resolver — given a `view_id` and a base query, returns the filtered query. RLS-composed.
- Write lens-test harness with golden-file expectations.
- Verify: same underlying fixture data, two queries via two views, different row counts matching golden files, no per-consumer branching.
- Fill in: **Lens Authoring Guide**.

**Exit:** `SELECT * FROM cip_tickets` via Lens-A returns all fixture rows; via Lens-B returns only EMEA-region rows, matching golden files. One more doc drafted.

### Milestone 5 — Metabase Platform Service on Fixture

**Goal:** Metabase deployed as a platform service, two dashboards live, lens switcher working.

- Deploy Metabase as a platform service (not tenant-scoped — future tenants plug in).
- Create fixture-tenant collection. Build two dashboards (one per lens).
- Wire lens switcher (parameter-based at dashboard level).
- Verify tiles render correctly under both lenses against fixture data.
- Load test: full fixture dataset, verify response times are reasonable (< 5s per tile is the Phase 1 target; optimization is Phase 8).

**Exit:** Tim opens Metabase, switches between lenses, fixture data resolves correctly under both.

### Milestone 6 — Discoverability Registry Completeness Pass

**Goal:** every Phase 1 artifact is queryable through registries. No "dark" data.

- Verify `cip_connector_property_registry` has rows for every fixture property (populated in M3, but double-check no gaps).
- Verify `cip_views` has both lenses.
- Verify `cip_sync_runs` has rows for every fixture sync.
- Verify `cip_files` has rows for every fixture document.
- Verify `knowledge_sources` has rows for all three fixture source types.
- Verify `graph_templates` has the fixture tenant's row.
- Fill in: **Four Access Paths Reference**.

**Exit:** cold-start agent (no CIP-specific context) can enumerate every Phase 1 artifact via generic registries alone. One more doc drafted.

### Milestone 7 — Four Access Paths Validation + Doc Suite Harden

**Goal:** prove the four access paths light up against fixture; harden every doc against first-read review.

**Four-access-paths procedure.** Spin up a fresh Cowork or Claude Code session with no CIP-specific context. The agent must:

1. **Path 1 — Structured via `foundry_mcp_db_query`.**
   - Discover: query `cip_connector_property_registry` to enumerate fixture columns.
   - Read: `SET LOCAL app.current_tenant = '<fixture>'` then `SELECT cip_client_id, name FROM cip_clients LIMIT 5`.
   - Cross-check: same query without `SET LOCAL`, expect zero rows (RLS block).
2. **Path 2 — Derived Knowledge (vector + BM25).**
   - Discover: query `knowledge_sources WHERE tenant_id = '<fixture>'` to enumerate `source_type` values.
   - Retrieve: call Knowledge Subsystem retrieval with a test query tied to fixture content ("refund request ticket body" or similar). Confirm results carry `cip_fixture_*` source references.
3. **Path 3 — Derived Knowledge (graph).**
   - Discover: query `graph_templates` for fixture tenant node/edge types.
   - Retrieve: ask a graph-hop question ("which contacts at EMEA companies filed tickets?"). Confirm graph hops return entity-linked citations.
4. **Path 4 — Originals via Storage Service + `cip_files`.**
   - Discover: query `cip_files WHERE tenant_id = '<fixture>' LIMIT 5`.
   - Resolve: pass `cip_file_id` to Storage Service, get signed R2 URL, fetch bytes.

**Acceptance criteria (all four must pass):**
- Agent reaches data on each path without CIP-specific tooling or hard-coded table names.
- Registries cover what's queryable.
- Tenant scoping holds (wrong tenant returns empty; no `SET LOCAL` returns empty).

**Doc hardening:** Tim (or a fresh reviewer) reads all ten docs end-to-end. Any gap that would block a second engineer from onboarding a tenant using the doc alone becomes an M7 fix. Special attention to the **Tenant Onboarding Checklist** and **Phase 1 → Phase 2 Handoff Doc** since those are the artifacts Phase 2 consumes first.

**Exit:** four-access-paths validation report green at `validation/M7-discoverability-report.md`. All ten docs reviewed and gaps closed.

### Milestone 8 — Product-Ready Gate: Plain-Jane Lock

**Goal:** Phase 1 exit gate — plain jane is shippable.

- Tim (or any engineer) opens Metabase against the fixture tenant, switches lenses, confirms data resolves correctly under both.
- Claude Code architect, reading only `PHASE-1-PLAIN-SPEC.md` + the ten docs, confirms the product is buildable-and-onboardable as described (sanity check — a fresh architect should not have to ask Atlas or Tim "what does this mean?" for any doc).
- Phase 1 retrospective: what did the framework teach us? Did the Lens Engine abstraction survive first contact? What should Phase 2 Wayward Onboarding sharpen when it meets real connectors?

**Exit:** Phase 1 LOCKED DONE. ROADMAP.md updated with Phase 1 LIT status. PM scopes for the 6 lit pillars advance to "lit, producing ongoing work" status. Phase 2 Wayward Onboarding VISION/WDGLL/SPEC/PLAN authoring begins.

### Risks & contingencies

**R1. Protocol design doesn't survive first real connector (Phase 2).**
*Mitigation:* Phase 2 is allowed to extend the Protocol if a real connector (HubSpot, Zendesk) surfaces a legitimate missing method. What it's not allowed to do is hardcode a connector-specific branch in the framework. Phase 1 optimizes for Protocol generality; Phase 2 is the empirical test.

**R2. FixtureConnector proves too simple — missing a real-world complexity that only emerges against HubSpot.**
*Mitigation:* the fixture covers relationship joins (contact → company, deal → contact), property overflow (structured vs JSONB), incremental sync cursors, and schema introspection. These are the framework's load-bearing features. If HubSpot still breaks something, update the fixture in Phase 2 to exercise that thing too, so Phase 3 and future connectors inherit the coverage.

**R3. Docs drift from code during the build.**
*Mitigation:* M7 doc hardening pass is mandatory and blocking. Docs review by fresh reader closes drift before Phase 1 exits.

**R4. Claude Code confirm-loop overhead slows execution.**
*Mitigation:* the SPEC doc is the expensive part — once it's right, architect/builder/reviewer loops are short. Expect M0–M2 to be SPEC-heavy and slow; M3 onward is faster.

**R5. HubSpot 20-revision retention clock ticks during Phase 1.**
*Mitigation:* the "HubSpot backup tape" mini-project can run in parallel if Tim judges the gap between Phase 1 exit and Phase 2 HubSpot first-sync too long to tolerate. Tape decision is Tim's at Phase 1 kickoff.

### Dependencies

- Integration Mesh subsystem must remain in its current state or move forward. No refactors during Phase 1 work.
- Knowledge Subsystem must remain in its current state (LIVE per CONTRACT.md). No breaking changes during Phase 1.
- Graph Subsystem must remain in its current state (LIVE per CONTRACT.md). No breaking changes during Phase 1.
- Claude Code is available on tims-desktop for architect/builder/reviewer loops.
- Metabase deployment target (platform service) — Tim confirms hosting decision at M5 kickoff.

### What this plan does NOT commit to

- Specific Metabase tile layouts (decided during build, not locked here).
- Exact fixture row counts (rough guidance in S3; tunable during build).
- A Phase 2 start date (that's a Phase 2 authoring decision).
- Specific HubSpot or Zendesk behavior (that's Phase 2 scope).

---

## Cross-references

- `README.md` — plain-jane Phase 1 pin + 8-pillar table
- `ROADMAP.md` — pillar-aligned phase sequence (this is Phase 1 of that roadmap)
- `vision/VISION.md` — product vision
- `PHASE-1-PLAIN-SPEC.md` — Claude Code handoff doc (sibling to this plan)
- `architecture/ARCHITECTURE.md` — Phase 0 DDL + §13–§19 hardening layer
- `docs/DECISION-LOG.md` — D-117, D-118, D-119, D-120, D-121
- `docs/architecture/principles/DESIGN-PRINCIPLES.md` — P-21 (Multi-Lens by Default)
- `docs/subsystems/integration/CONTRACT.md` — framework host
- `docs/subsystems/knowledge/CONTRACT.md` — Knowledge consumer notes (D-119)
- `docs/subsystems/graph/CONTRACT.md` — Graph consumer notes (D-119)
- `docs/cip/` — the ten-doc suite (skeletons authored in M0, filled M1–M7, locked M8)

## Authoring note

This doc is the working plan for CIP Phase 1 plain-jane. When Phase 1 kicks off (M1), this doc becomes the execution reference. Milestones get tracked as PM tasks under the 6 lit pillar scopes. Status updates land as `pm_task_update` + `pm_comment`, not as edits to this doc. The doc itself updates only when scope changes — and scope changes require real-time Tim authorization (Tier 3).
