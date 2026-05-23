---
doc_type: architecture
status: active
owner: tim
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
domain: eng
created: 2026-05-21
---
# Architecture — Foundry Client Intelligence Platform (CIP)

> **JOS-canonical entry point for CIP's architecture.**
> Per JOS-D0054 + JOS-S25, this file elaborates the Interface slot for the foundry-cip product root.
>
> **The authoritative architecture is [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md)** — 1124-line Phase 0 data-model + tenant-architecture spec. This root file is a JOS-shaped index pointing at it.

## System overview

CIP is shipped as a **Python library** (`pip install foundry-cip`) that Foundry-Agent-System (FAS) consumes. Three concrete artifacts:

1. **A Python package** — `cip/` (importable as `cip`). Main module `cip.integration_mesh` carries Protocol-based framework (CIPConnector + CIPMapper), orchestrator, persister, lens engine, SCD differ, tenant context.
2. **A schema definition** — 11 Alembic migrations (`cip_01_clients` through `cip_11_sync_mode_backfill`) creating `cip_*` tables in FAS's shared Postgres.
3. **A documentation set** — vision, architecture, runbooks (CONNECTOR-AUTHORING-GUIDE, MIGRATION-RUNBOOK, RLS-SET-LOCAL-OPERATOR-GUIDE, etc.).

CIP runs **in the caller's process** via the orchestrator's `run_sync` function. It is **not a service**; it is **not a deployment**. FAS handles deployment + consumption surfaces (Metabase, REST, MCP, chatbot).

## The 8 capability pillars (per D-117)

| # | Pillar | Code home | Status |
|---|---|---|---|
| 1 | Ingestion & Connectors | `cip.integration_mesh.connectors` | shipped (FixtureConnector / HubSpot / Zendesk) |
| 2 | Structured Store | `cip.migrations` + `cip.integration_mesh.persister` | shipped (8 cip_* tables + history) |
| 3 | Unstructured Store | `cip.integration_mesh.orchestrator` (knowledge hook) | in-progress |
| 4 | Lens Engine | `cip.integration_mesh.lens_engine` | shipped |
| 5 | Consumption Surfaces | Metabase grants (Postgres); REST + MCP in FAS | partial (Metabase shipped) |
| 6 | Push & Sync | (Phase 2-2.5) | planned |
| 7 | Intelligence & Alerts | (Phase 6+) | planned |
| 8 | Access & Operations | `cip.integration_mesh.tenant_context` + RLS policies | shipped |

Each pillar has its own `_manifest.yaml` + `OVERVIEW.md` at `docs/pillars/<pillar-slug>/`.

## The three data layers (per D-120)

| Layer | Storage | Carries |
|---|---|---|
| **Originals** | R2 (via FAS Storage service) | Raw files: documents, PDFs, audio, transcripts |
| **Derived Knowledge** | Pinecone (vectors) + FalkorDB (graph) — both in FAS | Chunks + embeddings + entity/relationship graph |
| **Structured Data** | Postgres `cip_*` tables in FAS's shared instance | Companies / contacts / deals / tickets / files-metadata + SCD-2 history |

## Tenant model

- **`tenants`** table (PM-substrate, FAS-owned) — the venture; one row per Foundry-Studio client engagement
- **`cip_clients`** — separate from PM tenants; ventures = owners, clients = subjects
- **`cip_views`** — per-tenant lens definitions (filter configs as JSONB)
- **Enforcement:** RLS policy on every `cip_*` table keyed on `app.current_tenant` GUC + explicit `tenant_id` predicates in lens views (defense-in-depth)

Detail: [`docs/RLS-SET-LOCAL-OPERATOR-GUIDE.md`](docs/RLS-SET-LOCAL-OPERATOR-GUIDE.md).

## Boundaries + interfaces

CIP exposes:

- **The Python API** — `from cip.integration_mesh import CIPConnector, CIPMapper, run_sync`
- **The Alembic migration chain** — applied via `alembic upgrade head` against the consumer's Postgres; uses `version_table = "alembic_version_cip"` per D-146 multi-repo Alembic model
- **The schema** — `cip_*` tables, `lens_*` views, `cip_metabase_role` grant matrix
- **The runbooks** — `docs/` Phase-1 doc suite (10 runbooks per Phase 1 deliverable list)

CIP consumes (from FAS):
- **PostgreSQL** — shared instance; `cip_*` tables live alongside PM + agents + knowledge
- **Knowledge subsystem** — for `KnowledgeText` ingestion (D-119)
- **Graph subsystem** — for entity/relationship extraction (D-119)
- **Storage subsystem** — for Originals (R2)

## Technology choices

- **Language:** Python 3.11+ (CI matrix: 3.11/3.12/3.13/3.14)
- **Database migration:** Alembic with `version_table = alembic_version_cip` (separate from FAS's `alembic_version`)
- **Database driver:** psycopg 3 (`postgresql+psycopg://`)
- **ORM:** SQLAlchemy
- **Testing:** pytest with testcontainers-python (`postgres:16-alpine`); RLS tests require real Postgres (SQLite not supported)
- **Type-checking:** mypy --strict on `cip/`
- **Linting:** ruff
- **Dependency discipline:** FND-S13 library-shape (ranges in pyproject.toml + lockfile in requirements-dev.txt via `uv pip compile --universal`)
- **Release discipline:** FND-S14 Local-Verified tier (A doc-only / B code / C migration; D N/A for library shape); every push carries `Local-Verified:` trailer enforced by `trailer-check` GH Actions job

## Key architectural decisions (link to FAS DECISION-LOG)

See [`DECISION-LOG.md`](DECISION-LOG.md) for the full index. Cross-cutting decisions:

| ID | What it locks |
|---|---|
| D-117 | 8 capability pillars as durable PM scopes |
| D-118 | Connector framework lives in Integration Mesh (general framework; Zendesk/HubSpot are first instances) |
| D-119 | Unstructured Store consumes FAS Knowledge + Graph subsystems |
| D-120 | Three Data Layers (canonical data model) |
| D-121 | Discoverability — every artifact gets a registry entry |
| D-134 | Protocol-based connector framework |
| D-135 | App-layer SCD Type 2 |
| D-146 | Separate repo; FAS consumes via pip; separate alembic_version tables |
| D-159 | Mandatory historical backfill on every connector |
| P-21 | Multi-Lens by Default |

## Anti-patterns

Per CIP's own architectural guardrails:

- **Library imports framework concerns into consumer.** CIP should not require FAS-specific imports beyond the Knowledge/Graph/Storage service contracts. Tested via the conformance harness.
- **Per-tenant code branching.** Tenant differences live in `cip_views` rows + connector configs — never in `if tenant_id == ...` code paths.
- **Lens added by schema change.** P-21 falsifiability test — adding a lens is INSERT-only into `cip_views`. Schema or code change = principle violated.
- **Skipping the conformance harness.** Every CIPConnector runs the 8-test harness before its migration lands.
- **Hand-rolled history.** SCD-2 history is mandatory + bitemporal + driven by the SCD differ — never authored manually.

## Connected JOS substrate

- **[JOS-D0054]** Doc-Types Elaborate Boundary Contract Slots
- **[JOS-S25]** ARCHITECTURE.md Doc Standard (conformance shape)
- **[JOS-SPEC-009]** Per-Thing Manifest (`_manifest.yaml` schema)
- **[JOS-D0066]** Doc-Type Matrix per Thing-Type

---

_This root-level file is a JOS-shaped index. Authoritative architecture detail: [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) (1124 lines)._


## Boundaries

_TODO: author this section per the doc-standard._

