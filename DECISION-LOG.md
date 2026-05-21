---
doc_type: decision-log
status: active
owner: tim
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
domain: meta
---

# Decision Log — Foundry Client Intelligence Platform (CIP)

> **JOS-canonical entry point for CIP's decision history.**
> Per JOS-D0054 + JOS-S27 (Decision-Log Doc Standard), this file elaborates the Lifecycle slot for the foundry-cip product root.
>
> **CIP does not maintain its own DECISION-LOG.** Per CLAUDE.md: governance authority remains in [Foundry-Agent-System](../../code/Foundry-Agent-System/) — specifically [`docs/DECISION-LOG.md`](../../code/Foundry-Agent-System/docs/DECISION-LOG.md) (6200+ lines, D-001 through D-182+). The CIP-specific decisions cited in CIP's other docs (D-117, D-118, …) are all entries in that FAS-wide log.

## How to read CIP-relevant decisions

1. **Open the FAS DECISION-LOG.** Located at `Foundry-Agent-System/docs/DECISION-LOG.md`.
2. **Search by D-number** of any decision cited in CIP's CLAUDE.md / VISION.md / ARCHITECTURE.md / features.yaml / capabilities.yaml.
3. **Follow the rationale.** Each entry includes alternatives considered + why X was chosen.

## CIP-relevant decisions (index)

These are the decisions cited in CIP's product docs. Full text in FAS DECISION-LOG.md.

| ID | Title | Theme |
|---|---|---|
| **D-117** | 8 CIP capability pillars locked as durable scopes | PM scope structure |
| **D-118** | CIP connectors live INSIDE Integration Mesh platform service | Code location, framework reuse |
| **D-119** | CIP Unstructured Store consumes Knowledge + Graph subsystems (not Memory) | Retrieval strategy |
| **D-120** | Three Data Layers: Originals + Derived Knowledge + Structured Data | Canonical data model |
| **D-121** | CIP discoverability — every artifact gets a registry row queryable by agents/scripts | Agent-readiness requirement |
| **D-122** | CSS tag ownership | Component classification |
| **D-123** | Alembic schema authority | Schema migration control |
| **D-126** | Non-SQL schema governance | Per-connector property registry |
| **D-133** | KnowledgeText return type | Mapper contract |
| **D-134** | Protocol-based connector framework | Framework shape |
| **D-135** | App-layer SCD Type 2 | Bitemporal history strategy |
| **D-146** | foundry-cip is a separate repo; FAS consumes via pip; separate alembic_version tables | Distribution model |
| **D-159** | Mandatory historical backfill on every connector | First-sync source-history capture |
| **P-21** | Multi-Lens by Default (platform-wide principle) | Every data surface assumes N consumers with N filter configs |

## Phase 0 decisions (data-model lock, 2026-04-17)

The 10 Phase 0 decisions locked the foundation. Each carries a number internal to CIP Phase 0 (D-117 series cross-references where applicable). Full detail in [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md):

1. DB Location — Shared Foundry PostgreSQL, `cip_` prefixed tables (extract to dedicated DB at Phase 8)
2. Client Table — `cip_clients` separate from PM tenants
3. Tenant Model — `tenant_id` + `client_id` + `cip_views` (filter configs); RLS + middleware enforcement
4. Provenance — 9 columns on every table
5. Versioning — SCD Type 2 with `_history` tables, active from Phase 1
6. Freshness — Exponential decay, configurable half-life per entity type
7. Naming — `cip_` prefix on all tables
8. Credentials — Railway disk encryption Stage 1; app-level AES-256 Stage 2/3
9. JSONB Overflow — Keep `properties` column for non-dashboardable fields
10. Authority Enum — 5 levels, manual entries = `validated`

## Decision authoring discipline

CIP-relevant decisions are appended to the **FAS** DECISION-LOG per JOS-S38 (Decision Doc-Standard):
- Append-only. Never modified, only superseded.
- Each Decision states: the choice, alternatives considered, rationale, what it produces downstream.
- New CIP-impacting decisions get a sequential `D-XYZ` ID in the FAS log + reference back here when CIP-specific.

## Why CIP doesn't own its own log

Per [`CLAUDE.md` §"Decisions that govern this repo"](CLAUDE.md):

> "foundry-cip does not maintain its own DECISION-LOG; governance authority remains in Foundry-Agent-System."

The split-repo model (D-146) extracted **code** to foundry-cip while keeping **governance** with the FAS monorepo. This keeps the single authoritative decision history; agents reading either repo see the same log.

## Connected JOS substrate

- **[JOS-D0054]** Doc-Types Elaborate Boundary Contract Slots
- **[JOS-S27]** Decision-Log Doc Standard (the conformance shape)
- **[JOS-S38]** Decision Doc-Standard (per-decision authoring discipline)
- **[JOS-D0080]** Principle vs Standing Order vs Concept boundary

---

_This root-level file is a JOS-shaped index. Authoritative log:_ `Foundry-Agent-System/docs/DECISION-LOG.md` _(D-001 through D-182+)._
