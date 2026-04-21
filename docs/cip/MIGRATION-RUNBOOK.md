---
kind: doc
domain: client-intelligence-platform
status: skeleton
last_updated: 2026-04-20
milestone: Phase-1-M0
---

# Migration Runbook

> **Status:** skeleton stub — authored Phase 1 M0, populated as Phase 1 milestones land.
> Once final, this runbook is the authoritative sequence for applying `cip_*` migrations to any CIP-enabled environment. Phase 1 covers cip_01 → cip_08; cip_09 is Phase 3; cip_10/11/12 are Phase 2.5.

## Purpose

Step-by-step runbook for applying CIP migrations (cip_01–cip_08 in Phase 1) to local/dev/prod: ordering, verification, rollback, and common failure modes.

## Who reads this

- Any operator running CIP migrations (first onboard, re-seed, prod deploy).
- Reviewers validating new `cip_*` migrations against the contract.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Creates this skeleton. |
| M1 — Migrations cip_01–cip_08 | Populates the runbook with the actual migration bodies, verification queries, rollback steps. |

Cross-ref: [`PHASE-1-PLAIN-SPEC.md §3`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md) for the binding migration file paths.

## Outline

### 1. Migration inventory (Phase 1)

TBD (M1) —

| File | Table(s) | History |
|------|----------|---------|
| `cip_01_*.py` | `cip_clients` | yes |
| `cip_02_*.py` | `cip_views` | yes |
| `cip_03_*.py` | `cip_sync_runs` | no |
| `cip_04_*.py` | `cip_files` | yes |
| `cip_05_*.py` | `cip_contacts` | yes |
| `cip_06_*.py` | `cip_companies` | yes |
| `cip_07_*.py` | `cip_deals` | yes |
| `cip_08_*.py` | `cip_tickets` + `cip_connector_property_registry` | yes (tickets) |

### 2. Pre-flight checks

TBD (M1) — DB reachable, env vars, prior migration state, Alembic head check.

### 3. Apply order

TBD (M1) — strict cip_01 → cip_08, no skipping; why each must land before the next.

### 4. Per-migration verification queries

TBD (M1) — after each migration, run a `SET LOCAL app.current_tenant = ...` + SELECT to prove RLS attaches correctly and tenant isolation holds.

### 5. History-table conventions

TBD (M1) — naming (`cip_<table>_history`), change-log rows, authority column propagation.

### 6. Rollback

TBD (M1) — when safe to downgrade, when not; what to do if partial apply fails mid-sequence.

### 7. Common failure modes

TBD (M1) — missing `tenants` row, RLS policy drift, Alembic branching, overlapping revision IDs.

### 8. Phase 2.5 and Phase 3 migrations (preview)

TBD (M1) — stubs for cip_09 (Phase 3, cross-tenant grants) and cip_10/11/12 (Phase 2.5, write-back). Do not apply in Phase 1.
