# Client Intelligence Platform (CIP) — Product

> **Location:** `products/client-intelligence-platform/` (governed — promoted from WORKBENCH 2026-04-17)
> **PM Project:** CIP (596825db-61bc-4899-bc6c-e207489ca35d)
> **Product #:** 6 in `FOUNDRY-TAXONOMY.md`
> **Status:** Planning — Phase 0 COMPLETE, Phase 1 LOCKED Shape D, PHASE-1-PLAN.md authored
> **Owner:** Tim
> **Last Updated:** 2026-04-17 (repo-move to products/ + PHASE-1-PLAN.md Shape D + Wayward SOLVE FOR articulated)

## What's Here

```
client-intelligence-platform/
├── vision/
│   ├── VISION.md                    ← Product vision doc (THE source of truth)
│   ├── ROADMAP.md                   ← Pillar-aligned phase sequence (Phase 0 COMPLETE, Phase 1 LOCKED)
│   └── PHASE-1-PLAN.md              ← Phase 1 VISION/WDGLL/SPEC/PLAN — Shape D, authored 2026-04-17
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
- PM project created with 8 scopes
- Phased ROADMAP.md written (Phases 0-7, dependency chain documented)
- **Phase 0 (Data Model & Tenant Architecture) COMPLETE** — all decisions locked 2026-04-17
- **Phase 1 (Connector Framework + History Tables) UP NEXT**
- Wayward is first planned tenant (data already staged in wayward-cs-overhaul/)
- HubSpot retains only 20 property revisions — CIP must own history from first sync

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

## Phase 1 Scope — LOCKED 2026-04-17 (Shape D)

**Appetite:** ~8 weeks. **Pillar coverage:** 6 of 8 at minimum viable state (Ingestion, Structured, Unstructured, Lens, Consumption, Access). Two deferred (Push & Sync, Intelligence & Alerts).

**IN:**
1. Database migrations — cip_01 through cip_08 (Structured Store pillar)
2. Connector framework inside Integration Mesh — CIPConnector Protocol + CIPMapper Protocol + ingestion pipeline orchestrator (Ingestion pillar — D-118)
3. **Zendesk connector** — tickets, users, organizations
4. **HubSpot connector** — contacts, companies, deals, notes (urgent: HubSpot only retains 20 property revisions — every day without sync = permanent history loss)
5. Wayward as sole tenant, sole client (one client picked at Phase 1 kickoff)
6. **Two lenses** on same data: EcomLever Full View + PS China View (Lens Engine pillar validation — P-21's canonical example)
7. Metabase read dashboard with lens switcher (Consumption Surfaces minimum — sole surface in Phase 1)
8. SCD Type 2 history active from first sync (already mandatory per Phase 0)
9. RLS + SET LOCAL enforcement (Access & Operations minimum)

**OUT (deferred to Phase 2+):**
- Push & Sync pillar entirely (Chatwoot, PS CRM, client Drive)
- Second tenant / dual-tenant proof
- Intelligence & Alerts pillar (anomaly detection, freshness signals, investigative agents)
- REST API, chatbots, agent MCP tools (Metabase is Phase 1's sole surface)

**Why this shape:** (1) HubSpot's 20-revision retention makes delayed HubSpot sync = permanent data loss, so HubSpot is mandatory IN. (2) Lens Engine is the novel abstraction with highest retrofit cost — two lenses on same data is the minimum validation of P-21. (3) Push & Sync has well-understood problem shape and is additive — safe to defer to Phase 2. (4) Connector framework stress-tests itself better with HubSpot's 4-object topology than Zendesk alone.

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

## Post-Phase-1 Roadmap (Provisional — Committed Direction, Not Locked)

Pillar-aligned. Each phase lights up a pillar's abstraction against real data; once lit, the pillar keeps producing work forever.

| Phase | Ships | Pillars Upgraded |
|-------|-------|------------------|
| **Phase 2** — Push & Sync goes live | Push to Chatwoot (ticket routing — replaces current `zendesk_to_chatwoot.py`) · Push to PS CRM (HubSpot→Twenty CRM sync) · Push to client Google Drive (scheduled report delivery) | **Push & Sync** (first light) · **Consumption Surfaces** (expand from Metabase-only to REST API + scheduled reports) |
| **Phase 3** — Multi-tenant + agent access | Rocky Ridge or Bob onboards as tenant #2 · `foundry_mcp_cip_query` + `foundry_mcp_cip_search` MCP tools · Web chatbot for Rocky Ridge staff · Cross-tenant lens validation | **Consumption Surfaces** (chatbots, agent MCP tools) · **Access & Operations** (dual-tenant proof) |
| **Phase 4** — Intelligence & Alerts | Anomaly detection (ticket volume spikes, overdue payment proofs) · Freshness signals surfaced in Metabase · Scheduled analytical reports · Slack alert integration | **Intelligence & Alerts** (first light — 7 of 8 pillars now active) |
| **Phase 5** — Investigative agents + write-back | Agents write discoveries back to CIP (authority=`agent_discovered`→`validated` workflow) · Cross-tenant pattern detection (anonymized) · Temporal point-in-time queries beyond SCD | **Intelligence & Alerts** (full light — proactive + investigative) |
| **Phase 6** — Scale & extract | Extract CIP tables from shared Foundry PostgreSQL to dedicated CIP DB (per Phase 0 decision: "extract at Stage 3") · Retention policies operational · Observability upgrade · Performance tuning | **Access & Operations** (full maturity) · **Structured Store** (dedicated instance) |

Phases are provisional shapes, not commitments — each Phase gets its own VISION/WDGLL/SPEC/PLAN doc before execution. The pillars are the durable frame; phases decide which pillar gets attention when.

## Governed Location — Promoted 2026-04-17

CIP now lives at `products/client-intelligence-platform/` (Product #6 in `FOUNDRY-TAXONOMY.md`). Tier 3 promotion authorized by Tim in-session on 2026-04-17 after Phase 0 completion + Phase 1 Shape D lock + PHASE-1-PLAN.md authoring. Product root pointer lives at `CLAUDE.md`.

Prior WORKBENCH location (`WORKBENCH/tim/research/client-intelligence-platform/`) is deprecated — historical references may persist but all active work happens at the governed path.
