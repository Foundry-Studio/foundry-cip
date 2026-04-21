---
kind: doc
domain: client-intelligence-platform
status: skeleton
last_updated: 2026-04-20
milestone: Phase-1-M0
---

# RLS + `SET LOCAL` Operator Guide

> **Status:** skeleton stub — authored Phase 1 M0, populated as Phase 1 milestones land.
> Once final, this guide is the authoritative reference for tenant scoping in CIP — how RLS policies and `SET LOCAL app.current_tenant` combine to guarantee D-026 isolation.

## Purpose

Explain the tenant-scoping contract: how Row-Level Security policies on every `cip_*` table, combined with `SET LOCAL app.current_tenant = '<uuid>'` at the start of every session/transaction, enforce strict per-tenant isolation — and how to verify, debug, and extend it.

## Who reads this

- Every engineer writing code that queries `cip_*` tables.
- Operators debugging "why did this query return zero rows / too many rows?"
- Phase 3 engineers extending the model to support cross-tenant grants (cip_09).

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Creates this skeleton. |
| M1 — Migrations cip_01–cip_08 | Populates §2 RLS policy template and §4 per-table verification. |
| M7 — Four-access-paths validation | Populates §6 cross-tenant probe (must return zero rows). |

Cross-ref: `CLAUDE.md` Rule D-026 ("Every database query MUST include tenant_id scoping"), [`PHASE-1-PLAIN-SPEC.md §2`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md) acceptance item 10.

## Outline

### 1. The contract

TBD (M1) — RLS + SET LOCAL as the two-part lock; neither alone is sufficient.

### 2. RLS policy template

TBD (M1) — the standard policy every `cip_*` table ships with; the `current_setting('app.current_tenant')` expression.

### 3. Setting `app.current_tenant`

TBD (M1) — when and how to call `SET LOCAL`, session vs. transaction scope, SQLAlchemy integration point, Alembic integration point.

### 4. Per-table verification

TBD (M1) — how to prove the policy attached after a migration: insert-as-A / select-as-B / expect zero rows.

### 5. Common failure modes

TBD (M1) — forgetting SET LOCAL on a new worker thread, pool-leak leaving prior tenant context, RLS bypass via superuser connection.

### 6. Cross-tenant probe

TBD (M7) — the Phase-1 acceptance-gate probe: connect as tenant A, query `cip_*` tables, assert zero rows belong to tenant B.

### 7. Phase 3 preview — cross-tenant grants

TBD (M1) — how cip_09 `cross_tenant_grants` will extend this model without breaking D-026 default isolation.

### 8. Debugging RLS

TBD (M1) — useful psql commands (`\d+`, `SELECT current_setting`), typical misdiagnoses, how to reproduce in a test.
