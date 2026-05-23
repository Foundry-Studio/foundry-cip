---
doc_type: overview
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
---
<!--
This is an OVERVIEW.md. It exists to answer "what do we have to
work with here?" — features, capabilities, status, boundaries.

If your content is:
- "Why does this thing exist?" → write it in PURPOSE.md (not yet present)
- "Where is it going?" → write it in VISION.md (root shell → docs/vision/VISION.md)
- "How do I install/use it?" → write it in README.md
- "How is it built?" → write it in ARCHITECTURE.md (root shell → docs/architecture/ARCHITECTURE.md)

Standard: JOS-S19
-->
---
doc_type: overview
declared_thing: foundry-cip
declared_thing_kind: product-internal
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
audience: [dev, product, strategy, agent]
diataxis_type: explanation
connects_to:
  - README.md
  - CLAUDE.md
  - ARCHITECTURE.md
  - VISION.md
  - ROADMAP.md
  - DECISION-LOG.md
  - _manifest.yaml
  - features.yaml
  - capabilities.yaml
---

# Overview — Foundry Client Intelligence Platform (CIP)

## What this is

Foundry Client Intelligence Platform (CIP) is a **multi-tenant client-data platform** that turns any client's scattered external data — CRM, support, financial, documents — into a live, queryable, agent-accessible intelligence layer. CIP serves dashboards, scheduled reports, chatbots, filtered team views, and white-label partner portals from one canonical store per tenant.

CIP is shipped as a **Python library** (`pip install foundry-cip`), not a service. Foundry-Agent-System (the monorepo) imports `cip` and runs the migrations against its shared Postgres. CIP itself is connector-agnostic — Wayward's Zendesk + HubSpot data is the first real-tenant proof point, but the framework is built to onboard the second tenant in an hour and the tenth in minutes.

Phase 1 (Plain-Jane + Doc Suite) LOCKED 2026-05-12; M0-M8 milestones all green. Phase 2 (Wayward Onboarding — Full Round-Trip) is the active build-out.

## What's inside

### The 8 capability pillars (per D-117)

These are durable work slices — what CIP **is** as a product, forever. Phases (what ships **when**) are tracked separately in `docs/vision/ROADMAP.md`.

| # | Pillar | Status | What it owns |
|---|---|---|---|
| 1 | **Ingestion & Connectors** | shipped (FixtureConnector + HubSpot + Zendesk landed; Plaid planned) | External source pulls, connector framework, auth, rate limits, incremental sync, mandatory historical backfill (D-159) |
| 2 | **Structured Store** | shipped | Postgres `cip_*` tables, SCD-2 history (bitemporal), 9 provenance columns, freshness computation, `cip_files` metadata registry |
| 3 | **Unstructured Store** | partial (ingestion hook shipped; consumption read-paths pending) | Derived knowledge (chunks + vectors via FAS Knowledge subsystem, entities + relationships via FAS Graph subsystem) |
| 4 | **Lens Engine** | shipped | Multi-tenant filtered views — `cip_views`, JSONB filter_config, query-time predicate compilation, golden-file snapshot harness |
| 5 | **Consumption Surfaces** | partial (Metabase shipped M5/M8; REST + MCP planned Phase 4) | Dashboards (Metabase via `cip_metabase_role`), REST API, chatbots, agent MCP tools, scheduled reports |
| 6 | **Push & Sync** | planned (Phase 2+) | Outbound delivery to Chatwoot, partner CRMs, client Google Drive, partner portals; write-back authority model |
| 7 | **Intelligence & Alerts** | planned (Phase 6+) | Anomaly detection, freshness scoring, proactive signals, investigative agents |
| 8 | **Access & Operations** | shipped | RLS + `SET LOCAL app.current_tenant`, tenant isolation, sync-run health, observability, cross-tenant grants (Phase 3 runtime) |

### Three data layers (D-120)

| Layer | Storage | What it carries |
|---|---|---|
| **Originals** | R2 (via FAS Storage service) | Raw files: documents, audio, PDF, images |
| **Derived Knowledge** | Pinecone (vectors) + FalkorDB (graph) | Chunks + embeddings + entity/relationship graph |
| **Structured Data** | Postgres `cip_*` tables | Companies, contacts, deals, tickets, files-metadata, SCD-2 history, lens views |

### Features

22 features in [features.yaml](features.yaml) organized by pillar — see [capabilities.yaml](capabilities.yaml) for the stakeholder-grain rollup.

### Code layout

- `cip/` — Python package, importable as `cip`. Main module: `cip.integration_mesh` (orchestrator, connectors, persister, lens engine, SCD differ, tenant context).
- `cip/integration_mesh/connectors/` — FixtureConnector, HubSpot, Zendesk implementations.
- `migrations/versions/` — 11 Alembic migrations: `cip_01_clients` through `cip_11_sync_mode_backfill`.
- `tests/` — Unit tests (`integration_mesh/`), fixture conformance harness (`fixtures/`), 9 RLS smoke tests (`migrations/`).
- `docs/` — vision, architecture, runbooks (CONNECTOR-AUTHORING-GUIDE, MIGRATION-RUNBOOK, etc.).
- `.jos/` — charter, registry, awareness, onboarding-report.

### Key files

| File | What it carries |
|---|---|
| `README.md` | Phase status + 8 pillars table + 9-phase roadmap shape |
| `CLAUDE.md` | AI-agent operating instructions, FND-S13 dependency pinning, FND-S14 Local-Verified discipline |
| `CHANGELOG.md` | M0-M8 milestones, connector bug-bash, D-159 framework extension |
| `_manifest.yaml` | JOS-SPEC-009 product manifest (children = 8 pillars) |
| `features.yaml` | JOS-SPEC-010 v1.1 feature registry (22 features) |
| `capabilities.yaml` | JOS-SPEC-011 v1.1 capability rollup (8 pillars) |
| `ARCHITECTURE.md` | JOS-shaped index → [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) (1124-line Phase 0 data model) |
| `VISION.md` | JOS-shaped index → [`docs/vision/VISION.md`](docs/vision/VISION.md) (473 lines) |
| `ROADMAP.md` | JOS-shaped index → [`docs/vision/ROADMAP.md`](docs/vision/ROADMAP.md) (9-phase shape) |
| `DECISION-LOG.md` | JOS-shaped index (decisions D-117 through D-159 + P-21 live in Foundry-Agent-System per CLAUDE.md) |
| `.jos/charter.yaml` | JOS binding — tier=full, schema=1.9 |

## Status

- **Lifecycle:** operating (graduated 2026-05-12 per JOS-D0069; library published; Phase 1 LOCKED)
- **Maturity:** Silver-tier at framework + Pillars 1/2/4/8; Bronze at Pillar 5 (Metabase only) + Pillar 3 (ingestion hook only); planned at Pillars 6/7
- **Active phase:** Phase 2 — Wayward Onboarding (Full Round-Trip). HubSpot + Zendesk connectors shipped 2026-05-12; awaiting Tim's "go" for first real-tenant ingestion
- **Health summary:** 44/44 connector tests green (last connector bug-bash 2026-05-14); mypy --strict clean on 35 source files; CI matrix Python 3.11/3.12/3.13/3.14 with lockfile-pinned constraints
- **Last reviewed:** 2026-05-21

## What's NOT here

- **The consumption surfaces themselves** → live in Foundry-Agent-System (Metabase service, REST API, MCP tools). CIP exposes the Postgres views + Python query API; FAS wraps them for external consumption.
- **The deployment runtime** → Foundry-Agent-System hosts the Postgres + runs the migrations via `alembic upgrade head` + serves the consumption surfaces. CIP is a library, not a service.
- **The Pinecone + FalkorDB clients** → FAS Knowledge subsystem + Graph subsystem. CIP emits `KnowledgeText` objects; FAS does the embedding + storage.
- **Per-venture business logic** → CIP is connector-agnostic. Wayward-specific lenses live in Wayward's tenant rows; CIP only enforces the framework.
- **Cross-tenant analytics + agent investigation** → Phase 6-7; not yet in scope.
- **Chatbot (Foundry Chatbot product)** → spun out to `products/foundry-chatbot/` (separate product, shares retrieval stack with CIP Phase 5).
- **Customer billing / paid surfaces** → CIP is Foundry-Studio-internal; no external paid tier in scope.

## Relationships

- **Parent:** Foundry-Studio (organization); CIP is Product #6 in FOUNDRY-TAXONOMY.md
- **Siblings:** Foundry-Agent-System (FAS — the monorepo that consumes CIP), Foundry Chatbot (planned spinoff), Bob (rebuild planned around Plaid)
- **Children:** 8 capability pillars (per D-117) — each has its own `_manifest.yaml` + `OVERVIEW.md` at `docs/pillars/<pillar-slug>/`
- **Cross-references:**
  - **Foundry-Agent-System** — consumes `cip` package; runs migrations against shared Postgres; hosts Knowledge + Graph + Storage services that CIP integrates with
  - **JOS** — governance source; charter binds CIP to JOS substrate
  - **Wayward** — first real tenant (Phase 2)
  - **Rocky Ridge** — second tenant (Phase 3)
  - **Foundry self-tenant** — Phase 2.5 write-back consumer

## Where to go next

| Doc | When to open it |
|---|---|
| [README.md](README.md) | Phase status, pillar table, deploy commands |
| [CLAUDE.md](CLAUDE.md) | Agent operating instructions, FND-S13/S14 discipline |
| [_manifest.yaml](_manifest.yaml) | Structured frontmatter inventory |
| [features.yaml](features.yaml) | 22 feature entries grouped by pillar |
| [capabilities.yaml](capabilities.yaml) | 8 stakeholder-grain capabilities |
| [`docs/vision/VISION.md`](docs/vision/VISION.md) | The 473-line product vision |
| [`docs/vision/ROADMAP.md`](docs/vision/ROADMAP.md) | 9-phase shape (Phase 0 done, Phase 1 LOCKED, Phase 2-3 committed) |
| [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) | Phase 0 data model + tenant architecture (1124 lines) |
| [`docs/PHASE-1-TO-PHASE-2-HANDOFF.md`](docs/PHASE-1-TO-PHASE-2-HANDOFF.md) | Where Phase 1 left things + Phase 2 entry criteria |
| [`docs/CONNECTOR-AUTHORING-GUIDE.md`](docs/CONNECTOR-AUTHORING-GUIDE.md) | How to add a new CIP connector |
| [`docs/MIGRATION-RUNBOOK.md`](docs/MIGRATION-RUNBOOK.md) | Alembic migration operating guide |
| [`docs/RLS-SET-LOCAL-OPERATOR-GUIDE.md`](docs/RLS-SET-LOCAL-OPERATOR-GUIDE.md) | Tenant isolation enforcement |

## Quick mental model

CIP is **the framework that lets Foundry-Studio onboard a client's data once and serve it everywhere** — dashboards, reports, chatbots, agents, partner portals. Three data layers (Originals + Derived Knowledge + Structured), eight pillars, multi-tenant by default with RLS + lens engine. Phase 1 proved the framework against fixture data; Phase 2 proves it against Wayward; Phase 3 proves multi-tenant with Rocky Ridge. The horizon is "second tenant in an hour, tenth in minutes."
