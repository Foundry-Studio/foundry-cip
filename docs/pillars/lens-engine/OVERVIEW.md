---
doc_type: overview
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
---
<!-- OVERVIEW.md per JOS-S19 -->
---
doc_type: overview
declared_thing: foundry-cip-lens-engine
declared_thing_kind: subsystem
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
audience: [dev, product, agent]
diataxis_type: explanation
---

# Overview — CIP Pillar 4: Lens Engine

## What this is

Multi-tenant filtered views per P-21. A lens is a row in `cip_views` with a JSONB `filter_config` — query-time the engine compiles the JSON predicate into a SQLAlchemy WHERE clause and AND-composes it with tenant RLS. The falsifiability test for P-21 (Multi-Lens by Default): adding a lens is **INSERT-only into cip_views** — no schema or code change required.

Today: equality-only operators (v1). Operator extensibility deferred to v2.

Determinism is locked by a golden-file snapshot harness — canonicalized JSON of corpus + lens applications SHA-256-pinned. Drift fails loud.

## What's inside

| Feature | Status | Code |
|---|---|---|
| `lens-engine` | shipped | `cip.integration_mesh.lens_engine` |
| `lens-authoring` | shipped | doc-only — [`docs/LENS-AUTHORING-GUIDE.md`](../../LENS-AUTHORING-GUIDE.md) |
| `golden-file-snapshot-harness` | shipped | `tests/integration_mesh/test_lens_golden_snapshots.py` |

3 features tagged `pillar:lens-engine`.

Production lenses today: `lens_all_companies` (50 rows), `lens_eu_west_companies` (13 rows), `lens_companies_history` (bitemporal SCD-2 history surface, M8).

## Status

- **Lifecycle:** operating
- **Maturity:** silver — equality operators only; operator extensibility deferred
- **Health summary:** snapshot harness green; Metabase deployment confirms lens behavior 2026-05-12
- **Last reviewed:** 2026-05-21

## What's NOT here

- **The underlying tables** → [Pillar 2 — Structured Store](../structured-store/)
- **The Postgres grant matrix that enforces P-21 structurally** → [Pillar 5 — Consumption Surfaces](../consumption-surfaces/) (REVOKE on cip_*, GRANT on lens_*)
- **Tenant RLS itself** → [Pillar 8 — Access & Operations](../access-and-operations/)
- **Operator extensibility (v2 — gt/lt/IN/contains)** → deferred; capture in Phase 4+ when the need surfaces

## Relationships

- **Parent:** [`foundry-cip`](../../../)
- **Siblings:** Pillars 1-3, 5-8
- **Cross-references:** depends on Pillars 2 + 8; referenced by Pillar 5

## Where to go next

| Doc | When to open it |
|---|---|
| [`docs/LENS-AUTHORING-GUIDE.md`](../../LENS-AUTHORING-GUIDE.md) | How to add a new lens |
| `cip/integration_mesh/lens_engine/` | The compilation source |
| [`tests/integration_mesh/test_lens_golden_snapshots.py`](../../../tests/integration_mesh/test_lens_golden_snapshots.py) | The determinism harness |
