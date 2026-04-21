---
kind: doc
domain: client-intelligence-platform
status: skeleton
last_updated: 2026-04-20
milestone: Phase-1-M0
---

# Lens Authoring Guide

> **Status:** skeleton stub — authored Phase 1 M0, populated as Phase 1 milestones land.
> Once final, this guide explains how to define a new Lens — the transformation that turns raw structured records into a tenant-curated, agent-consumable view. Phase 1 validates against Lens-A and Lens-B on fixture data.

## Purpose

Teach an engineer how to author a new Lens against the `cip_*` structured store: lens config shape, target view naming, field selection, transformations, and the golden-file test pattern.

## Who reads this

- Engineers defining the first few tenant lenses (starts Phase 1 M4: Lens-A, Lens-B; extends in Phase 2 for Wayward-specific lenses).
- Reviewers validating Lens PRs against the golden-file test pattern.
- Downstream consumers of lens output (four-access-paths, consumption surfaces) who want to understand lens contract.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Creates this skeleton. |
| M4 — Lens engine + Lens-A / Lens-B | Defines the lens-config schema and reference implementations. |
| M7 — Four-access-paths validation | Uses lenses as Path 1 (Structured) and part of Path 2 (Derived Knowledge vector+BM25) validation. |

Cross-ref: [`PHASE-1-PLAIN-SPEC.md`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md), [`VISION.md §7g`](../../products/client-intelligence-platform/vision/VISION.md) for the Multi-Lens-by-Default principle (P-21).

## Outline

### 1. What a Lens is (and isn't)

TBD (M4) — Lens = tenant-configured transformation over `cip_*`; not an ETL pipeline, not a materialized product view.

### 2. Lens config schema

TBD (M4) — DB row shape in the lens config table; name, tenant_id, source tables, field selector, transforms, cache policy.

### 3. Source-table selection

TBD (M4) — which `cip_*` tables a lens may read; RLS scoping implications.

### 4. Field selection + renaming

TBD (M4) — picking columns/overflow keys, alias conventions, type coercion.

### 5. Row-level filters

TBD (M4) — tenant-specific filter expressions, safe-subset of SQL.

### 6. Transformations

TBD (M4) — allowed transform operations (enum normalization, date bucketing, derived flags), forbidden ones (joins across tenants, side effects).

### 7. Target view naming

TBD (M4) — naming convention (e.g. `lens_<tenant_alias>_<lens_name>`), RLS on the view.

### 8. Golden-file tests

TBD (M4) — `tests/fixtures/lens/golden_files/` expected row sets, diffing pattern.

### 9. Lens-A and Lens-B walkthrough

TBD (M4) — the two Phase-1 reference lenses; what each demonstrates.

### 10. Versioning + migrations

TBD (M4) — when a lens change is breaking, how to version, how to deprecate.
