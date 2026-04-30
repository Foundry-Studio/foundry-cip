# Client Intelligence Platform (CIP) — Product

> **Location:** `products/client-intelligence-platform/` (governed — promoted from WORKBENCH 2026-04-17)
> **PM Project:** CIP (596825db-61bc-4899-bc6c-e207489ca35d)
> **Product #:** 6 in `FOUNDRY-TAXONOMY.md`
> **Status:** Planning — Phase 0 COMPLETE, Phase 1 LOCKED (Plain-Jane reshape), PHASE-1-PLAN.md + PHASE-1-PLAIN-SPEC.md + PHASE-2.5-PLAN.md authored
> **Owner:** Tim
> **Last Updated:** 2026-04-20 (Plain-Jane reshape: Phase 1 rewired to fixture-tenant-only + 10 doc artifacts; Wayward onboarding pulled into Phase 2; Phase 2.5 trimmed to write-back only; cip_09 moved to Phase 3; week-based appetites dropped)

## What's Here

```
client-intelligence-platform/
├── vision/
│   ├── VISION.md                    ← Product vision doc (THE source of truth)
│   ├── ROADMAP.md                   ← Pillar-aligned phase sequence (Phase 0 COMPLETE, Phase 1 LOCKED Plain-Jane)
│   ├── PHASE-1-PLAN.md              ← Phase 1 VISION/WDGLL/SPEC/PLAN — Plain Jane, reshaped 2026-04-20
│   ├── PHASE-1-PLAIN-SPEC.md        ← Claude Code handoff — binding spec for Phase 1 implementation
│   └── PHASE-2.5-PLAN.md            ← Phase 2.5 VISION/WDGLL/SPEC/PLAN — Foundry Self-Tenant + Write-Back
├── architecture/
│   └── ARCHITECTURE.md              ← Phase 0 output — schemas, tenant model, all DDL
├── stages/
│   ├── phase-0-data-model.md        ← (from prior Claude Code session)
│   ├── phase-1-connector-framework.md
│   ├── phase-2-wayward-pipeline.md
│   ├── phase-3-knowledge-access.md
│   ├── phase-4-dashboards-reports.md
│   ├── phase-5-web-chatbot.md
│   ├── phase-6-anomaly-detection.md
│   └── phase-7-intelligence-layer.md
├── research/
│   └── industry-landscape.md        ← CDP, RAG, multi-tenant, consulting platform analysis
├── notes/
│   ├── 01-initial-braindump.md      ← First braindump (Wayward lessons, arch questions)
│   ├── 02-vision-discussion-outline.md ← Questions to resolve (most now answered)
│   └── 03-vision-conversation-log.md   ← Tim's decisions from the vision session
└── README.md                        ← This file
```

## Current State

- Vision drafted, discussed, and stable
- PM project has 8 capability-pillar scopes (D-117)
- Phased ROADMAP.md written — 9 phases (Phase 0 COMPLETE; Phase 1 LOCKED Plain Jane; Phase 2, 2.5, 3 shapes committed; Phase 4+ provisional)
- **Phase 0 (Data Model & Tenant Architecture) COMPLETE** — all decisions locked 2026-04-17
- **Phase 1 (Plain-Jane CIP + Doc Suite) UP NEXT** — fixture-tenant-only, 12 code deliverables + 10 doc artifacts, reshaped 2026-04-20
- Wayward onboarding pulled into Phase 2 (full round-trip: Zendesk/HubSpot + push)
- Rocky Ridge onboarding pulled into Phase 3 (alongside cross-tenant grants runtime)
- HubSpot retains only 20 property revisions — Phase 2 begins history capture from first sync (delay = permanent loss)

## Phase 0 Decisions — LOCKED

All approved by Tim during Cowork session 2026-04-17. Full details in `architecture/ARCHITECTURE.md`.

| # | Decision | Resolution |
|---|----------|-----------|
| 1 | DB Location | Shared Foundry PostgreSQL, `cip_` prefixed tables. Extract to dedicated DB at Stage 3. |
| 2 | Client Table | Own `cip_clients` table, separate from PM tenants. Ventures = owners, clients = subjects. |
| 3 | Tenant Model | `tenant_id` + `client_id` + `cip_views` (filter configs). RLS + middleware enforcement. |
| 4 | Provenance | 9 columns on every table: tenant_id, client_id, source_connector, source_id, ingested_at, refreshed_at, previous_version_id, ingestion_batch_id, authority |
| 5 | Versioning | SCD Type 2 with `_history` tables, active from Phase 1 (not deferred). |
| 6 | Freshness | Exponential decay, configurable half-life per entity type, computed at query time. |
| 7 | Naming | `cip_` prefix on all tables. |
| 8 | Credentials | Railway disk encryption for Stage 1. App-level AES-256 deferred to Stage 2/3. |
| 9 | JSONB Overflow | Keep `properties` column. Real columns for dashboardable fields, JSONB for the rest. |
| 10 | Authority Enum | 5 levels, manual entries = `validated`. source_connector tracks origin, authority tracks trust. |

## Phase 1 Scope — LOCKED 2026-04-20 (Plain-Jane Reshape)

**Framing:** Session-bound, milestone-ordered — no week-based appetite. **Primary tenant:** none — fixture tenant only. **Pillar coverage:** 6 of 8 at minimum viable state (Ingestion, Structured, Unstructured, Lens, Consumption, Access). Two deferred (Push & Sync, Intelligence & Alerts).

**IN (code, 12 deliverables):**
1. Database migrations — `cip_01` through `cip_08` (Structured Store pillar). **`cip_09` cross_tenant_grants is NOT in Phase 1** — moved to Phase 3 so schema + runtime ship together.
2. Connector framework inside Integration Mesh — `CIPConnector` Protocol + `CIPMapper` Protocol + ingestion pipeline orchestrator (Ingestion pillar — D-118)
3. **FixtureConnector** — deterministic synthetic data source (no external API) producing ~50 companies / ~200 contacts / ~300 deals / ~500 tickets / ~100 documents / ~50 notes from one fixed random seed for byte-identical repeatability
4. `cip_connector_property_registry` populated by `FixtureConnector.describe_schema()` (D-121 discoverability minimum)
5. Unstructured Store wiring — CIP → Knowledge Subsystem via `knowledge_ingester_service.ingest_text_content()`; `source_type` values `cip_fixture_ticket`, `cip_fixture_note`, `cip_fixture_doc`; graph extraction via post-vector hook (D-067 non-fatal)
6. Lens Engine — `resolve_lens()` resolver with two lenses on the fixture dataset (**Lens-A** empty filter, **Lens-B** `region=EMEA`)
7. Metabase dashboard with lens switcher (Consumption Surfaces minimum — sole surface in Phase 1)
8. SCD Type 2 history active from first sync (already mandatory per Phase 0)
9. RLS + `SET LOCAL app.current_tenant` enforcement (Access & Operations minimum)
10. Four agent access paths validated against fixture data (Structured, Derived Knowledge vector+BM25, Derived Knowledge graph, Originals)
11. Connector-conformance test harness (every future `CIPConnector` runs the same harness and passes before its migration lands)
12. CSS classification tags (`# foundry: kind=X domain=Y`) on every new file

**IN (documentation, 10 artifacts):**

1. Tenant Onboarding Checklist
2. Connector Authoring Guide
3. Lens Authoring Guide
4. Migration Runbook (`cip_01`–`cip_08`)
5. RLS & `SET LOCAL` Operator Guide
6. Sync Orchestrator Guide
7. Four Access Paths Reference
8. Fixture Tenant Handbook
9. CIP CSS Classification Contract
10. Phase 1 → Phase 2 Handoff Doc

**OUT (deferred to later phases):**
- Zendesk connector → Phase 2 (Wayward onboarding)
- HubSpot connector → Phase 2 (Wayward onboarding; HubSpot 20-revision retention clock starts at Phase 2 kickoff, not Phase 1)
- Any real-tenant data (Wayward, Rocky Ridge, Foundry) → Phases 2, 3, 2.5 respectively
- `cip_09` cross_tenant_grants schema + runtime → Phase 3
- Push & Sync pillar (Chatwoot, PS CRM, Drive) → Phase 2
- Foundry self-tenant + write-back → Phase 2.5
- Second tenant / multi-tenant proof → Phase 3
- REST API, chatbots, agent MCP tools → Phases 4, 5
- Intelligence & Alerts pillar → Phase 6
- Investigative agents + advanced write-back → Phase 7

**Why this shape:** (1) Forcing the plain-jane product against FixtureConnector *before* any real venture proves the interfaces are connector-agnostic, not back-fit to Wayward's shape. (2) Shipping 10 doc artifacts alongside the code turns Phase 1 into a package an outside engineer can onboard from — not tribal knowledge. (3) Moving Wayward into its own dedicated Phase 2 ("Wayward Onboarding — Full Round-Trip") makes Wayward a single coherent proof instead of an ingredient scattered across Phase 1 ingest + Phase 2 push. (4) Holding `cip_09` until Phase 3 lets schema + runtime ship together — no orphan migration sitting unused for two phases.

**Phase 1 exit gate:** Plain-jane product works against fixture data + all 10 doc artifacts exist + `PHASE-1-PLAIN-SPEC.md` marked complete by the Claude Code reviewer subagent.

## PM Scopes — 8 CAPABILITY PILLARS (LOCKED 2026-04-17)

These are durable work slices — what CIP *is* as a product, forever. Phases (what ships *when*) are tracked separately.

| # | Scope | scope_id | What it owns |
|---|-------|----------|-------------|
| 1 | **Ingestion & Connectors** | `bd946c35-3dbc-4377-9ac8-3b97cf6a9498` | External source pulls, connector framework (built inside Integration Mesh platform service), auth, rate limits, incremental sync |
| 2 | **Structured Store** | `4eecc1af-9e04-4a41-b8df-58214f7294ee` | Postgres schema (cip_* tables), SCD history, 9 provenance columns, freshness computation, `cip_files` metadata registry |
| 3 | **Unstructured Store** | `42e1398b-db37-4e4b-8ec0-119779ff7afc` | Derived knowledge (chunks + vectors via Knowledge Subsystem RAG, entities + relationships via Graph Subsystem GraphRAG) |
| 4 | **Lens Engine** | `c8108c8a-a554-470f-9c93-b5920830ebf5` | Multi-view filtering — `cip_views`, `filter_config` JSONB, lens resolution, RLS enforcement |
| 5 | **Consumption Surfaces** | `13a71cca-640c-47d9-81a6-0656379eeb9a` | Dashboards (Metabase), REST API, chatbots, agent MCP tools, scheduled reports |
| 6 | **Push & Sync** | `0147539c-5558-47c0-aefb-4f81b4512ed4` | Outbound delivery to Chatwoot, partner CRMs, client Google Drive folders, partner portals |
| 7 | **Intelligence & Alerts** | `beddc8fc-0975-44bb-bb4f-5d59105c5011` | Anomaly detection, freshness scoring, proactive signals, investigative agents |
| 8 | **Access & Operations** | `9412faf5-6788-4978-898e-06ed9dc741c5` | Tenant isolation (RLS + SET LOCAL), access control, sync-run health, observability, technical-health budget |

**Previous 8 scopes (superseded 2026-04-17):** Vision & Architecture Lock (`8d6fc0f9-b9d7-4101-bfd8-aebb5433f9e0` — Phase 0 done), Connector Framework (`f9211f0f-c760-476b-b009-0c0aa2615151`), Structured Data Layer (`d67ed3db-b6d0-4729-bcea-1e503e7e9846`), Unstructured Knowledge Layer (`56abc1b0-a7ea-4e50-af15-8952304d1d58`), Consumption Interfaces (`26a3ce24-d014-49bb-b4ab-0c2cedd38b26`), Push & Sync (`f7a073dd-92bc-41b9-a7eb-46f6a23a309b`), Anomaly Detection & Alerts (`7bcd8b3a-d82e-40e1-a76b-04a2397030cd`), Wayward v1 (`da6a0110-ef55-4ce1-b1d9-0b7a2a2548e4`). Each has a SUPERSEDED comment pinned per D-117.

## Locked Architecture Decisions (beyond Phase 0)

| D-# | Decision | Impact |
|-----|----------|--------|
| D-117 | 8 CIP capability pillars locked as durable scopes (this table) | PM scope structure |
| D-118 | CIP connectors live INSIDE Integration Mesh platform service (CIP Phase 1 builds the general connector framework; CIP's Zendesk/HubSpot connectors are the first instances) | Code location, reuse across products |
| D-119 | CIP Unstructured Store consumes **Knowledge Subsystem** (RAG) **and Graph Subsystem** (GraphRAG) — NOT Memory Service. New `source_type` values added to `knowledge_sources`; new node/edge types added per-venture in `graph_templates` | Vector/graph storage strategy |
| D-120 | CIP has three data layers: **Originals** (R2 via Storage Service) + **Derived Knowledge** (chunks/vectors + graph entities) + **Structured Data** (Postgres). `cip_files` metadata table in Structured Store links originals → chunks | Data model |
| D-121 | CIP discoverability — every CIP artifact (files, clients, views, connectors, sync runs, chunks, graph entities, source_types) gets a registry row/table/namespace queryable by agents and scripts. Complies with NN-01 + STD-08. | Registry tables required in schema |
| P-21 | Multi-Lens by Default (platform-wide principle) — every data surface assumes N consumers with N filter configs | Architectural guardrail across Foundry |

## Post-Phase-1 Roadmap (9-Phase Shape, reshaped 2026-04-20)

Pillar-aligned. Each phase lights up a pillar's abstraction against real data; once lit, the pillar keeps producing work forever. Full detail in `vision/ROADMAP.md`. Week-based appetites have been dropped — phases are session-bound and milestone-ordered.

| Phase | Ships | Pillars Upgraded |
|-------|-------|------------------|
| **Phase 2** — Wayward Onboarding (Full Round-Trip) | Zendesk + HubSpot connectors (HubSpot history capture begins at Phase 2 kickoff) · Wayward as primary tenant in EcomLever · Two lenses on Wayward data · Push to Chatwoot · Push to PS Twenty CRM · Push to client Google Drive · First-light REST API | **Ingestion & Connectors** (Zendesk + HubSpot) · **Push & Sync** (first light) · **Consumption Surfaces** (REST added) |
| **Phase 2.5** — Foundry Self-Tenant + Write-Back | Foundry provisioned as a peer tenant · `cip_10`/`cip_11`/`cip_12` migrations · `cip_write` API on three surfaces (REST / MCP / Python) converging on one `write_service.cip_write()` · Authority model live (`agent_discovered` / `ingested` / `validated` with TSP thresholds) · Minimal CLI promotion queue · First producer: Foundry internal research agent | **Access & Operations** · **Ingestion & Connectors** (producer side) |
| **Phase 3** — Rocky Ridge + Multi-Tenant + Grants Runtime | `cip_09` cross_tenant_grants migration + runtime together · Rocky Ridge onboards as tenant #2 · PS grant-in to Wayward goes live · Cross-tenant lens validation · Access-layer observability | **Access & Operations** (dual-tenant proof + grant runtime) |
| **Phase 4** — Agent Access Surfaces (MCP + REST) | `foundry_mcp_cip_query` · `foundry_mcp_cip_search` · `foundry_mcp_cip_files` · REST parallel at `/cip/query`, `/cip/search`, `/cip/files` · Discoverability endpoints (`/cip/registries/*`) · **Chatbot explicitly excluded** | **Consumption Surfaces** (agents-as-first-class-consumer) |
| **Phase 5** — Chatbot Capability (Internal) | **5A** `vision/CHATBOT-VISION.md` · **5B** `architecture/CHATBOT-ARCHITECTURE.md` · **5C** Implementation against Rocky Ridge first, then Wayward. Grounded, lens-aware, grant-aware, read-only, citations mandatory | **Consumption Surfaces** (conversational light) |
| **Phase 6** — Intelligence & Alerts | Anomaly detection (ticket spikes, overdue payments, freshness crossings) · Slack alert channel · Freshness signals in Metabase · Scheduled analytical reports | **Intelligence & Alerts** (first light — 7 of 8 pillars active) |
| **Phase 7** — Investigative Agents + Advanced Write-Back | Long-running investigative agents · Rich validated-promotion UX · Cross-tenant anonymized pattern detection · Temporal point-in-time query API · Self-service embedded analytics (white-label) · First phase chatbot-initiated writes are allowed | **Intelligence & Alerts** (full light) |
| **Phase 8** — Scale & Extract | Extract `cip_*` tables from shared Foundry PostgreSQL → dedicated Railway PostgreSQL (per Phase 0 decision #1) · Retention policies active · Observability upgrade · Performance tuning · Backup & restore tested quarterly | **Access & Operations** (full maturity) · **Structured Store** (dedicated instance) |

Phase 2, Phase 2.5, and Phase 3 shapes are the current commit. Phase 4+ remain provisional shapes, not commitments — each Phase gets its own VISION/WDGLL/SPEC/PLAN doc before execution. The pillars are the durable frame; phases decide which pillar gets attention when.

## Governed Location — Promoted 2026-04-17

CIP now lives at `products/client-intelligence-platform/` (Product #6 in `FOUNDRY-TAXONOMY.md`). Tier 3 promotion authorized by Tim in-session on 2026-04-17 after Phase 0 completion + Phase 1 Shape D lock + PHASE-1-PLAN.md authoring. Product root pointer lives at `CLAUDE.md`.

Prior WORKBENCH location (`WORKBENCH/tim/research/client-intelligence-platform/`) is deprecated — historical references may persist but all active work happens at the governed path.
