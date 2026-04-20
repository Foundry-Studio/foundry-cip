---
doc_type: product_root
product: client-intelligence-platform
pm_project_id: 596825db-61bc-4899-bc6c-e207489ca35d
taxonomy: product
stage: 1
status: planning
owner: tim
created: 2026-04-17
last_updated: 2026-04-17
---

# Client Intelligence Platform (CIP)

Per-client unified data layer (structured + unstructured + originals) with multi-lens views over partner relationships. Product #6 in `FOUNDRY-TAXONOMY.md`.

## Orient

1. **Read `README.md`** — product overview, 8 capability pillars, locked architecture decisions (D-117 through D-121, P-21), PM scope IDs, Phase 1 Shape D lock.
2. **Read `vision/ROADMAP.md`** — pillar-aligned phase sequence. Phase 0 COMPLETE, Phase 1 LOCKED, Phases 2–6 provisional.
3. **Read `vision/PHASE-1-PLAN.md`** — active execution plan (VISION + WDGLL + SPEC + PLAN) for Phase 1 Shape D.
4. **Read `architecture/ARCHITECTURE.md`** — Phase 0 DDL + §13–§19 hardening layer (capability pillars, Integration Mesh connector framework, RAG + GraphRAG consumption, three data layers, discoverability registry, multi-lens, platform services map).
5. **Read `vision/VISION.md`** — longer-form product vision, original intent.

## Structure

```
client-intelligence-platform/
├── CLAUDE.md               ← This file (product root pointer)
├── README.md               ← Product overview + scope IDs + architecture locks
├── vision/
│   ├── VISION.md           ← Product vision (canonical source of truth)
│   ├── ROADMAP.md          ← Pillar-aligned phase sequence
│   └── PHASE-1-PLAN.md     ← Phase 1 Shape D: VISION/WDGLL/SPEC/PLAN (active)
├── architecture/
│   └── ARCHITECTURE.md     ← Phase 0 DDL + §13–§19 hardening layer
├── research/
│   └── industry-landscape.md
├── notes/                  ← Historical braindumps (pre-Phase-0)
│   ├── 01-initial-braindump.md
│   ├── 02-vision-discussion-outline.md
│   └── 03-vision-conversation-log.md
└── stages/                 ← Historical pre-pillar phase stubs (superseded by ROADMAP.md)
```

## Where CIP code lives

CIP is a product *folder* with planning docs. The code itself ships to **governed platform paths**:

- **Migrations** — `migrations/versions/cip_*.py` (repo root)
- **Connector framework + CIP connectors** — `platform/integration-mesh/src/connectors/cip/` (per D-118, framework lives inside Integration Mesh platform service)
- **Application code** — `src/` (repo root, following existing conventions)
- **Tests** — `tests/`

CIP does not own a `src/` subfolder of its own. Its code is distributed across platform services and the main application tree per D-118 and D-119 (CIP consumes Knowledge Subsystem + Graph Subsystem + Storage Service).

## Locked decisions (beyond Phase 0)

| D-# | Decision |
|-----|----------|
| D-117 | 8 capability pillars locked as durable PM scopes |
| D-118 | CIP connectors live inside Integration Mesh platform service |
| D-119 | CIP Unstructured Store consumes Knowledge Subsystem (RAG) + Graph Subsystem (GraphRAG), NOT Memory Service |
| D-120 | Three data layers: Originals (R2) + Derived Knowledge (chunks+vectors+graph) + Structured Data (Postgres) |
| D-121 | Every CIP artifact gets registry row/table/namespace (NN-01 + STD-08 compliance) |
| P-21  | Multi-Lens by Default (platform-wide principle, not CIP-specific) |

All in `docs/DECISION-LOG.md` and `docs/architecture/principles/DESIGN-PRINCIPLES.md`.

## Relevant subsystem contracts

- `docs/subsystems/integration/CONTRACT.md` — hosts CIP connector framework (D-118)
- `docs/subsystems/knowledge/CONTRACT.md` — provides RAG layer for CIP Unstructured Store (D-119)
- `docs/subsystems/graph/CONTRACT.md` — provides GraphRAG layer for CIP Unstructured Store (D-119)
- `docs/subsystems/storage/CONTRACT.md` — provides R2 Originals layer for CIP (D-120)

## Governance tier

CIP is a governed product (Tier 3 for repo-path / taxonomy / vision changes; Tier 2a for architecture doc edits; Tier 1 for working notes inside `research/` and `notes/`).

Promoted from WORKBENCH to `products/` on 2026-04-17 after Phase 0 completion, Phase 1 Shape D lock, and PHASE-1-PLAN.md authoring. Tier 3 promotion authorized by Tim in-session.
