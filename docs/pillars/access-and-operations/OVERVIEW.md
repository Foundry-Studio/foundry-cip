<!-- OVERVIEW.md per JOS-S19 -->
---
doc_type: overview
declared_thing: foundry-cip-access-and-operations
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

# Overview — CIP Pillar 8: Access & Operations

## What this is

The foundation pillar. **Every** other pillar depends on this one. Multi-tenant isolation is structural: PostgreSQL Row-Level Security on every `cip_*` table keyed on the `app.current_tenant` GUC, plus explicit `tenant_id` predicates in lens views (defense-in-depth), plus the `SET LOCAL app.current_tenant` middleware that scopes every session. Tenant scoping is enforced by construction (D-026); no class of "leaked across tenants" bug is possible at the data layer.

Phase 3 adds the cross-tenant grants runtime — `cip_09_cross_tenant_grants` schema + runtime ship together, deferred from Phase 1 explicitly so they ship as a unit. Phase 8 extracts `cip_*` tables to a dedicated Postgres for scale.

## What's inside

| Feature | Status | Code |
|---|---|---|
| `tenant-isolation-rls` | shipped (gold; cross-cuts Pillar 2) | `cip.integration_mesh.tenant_context` + RLS in migrations |
| `cross-tenant-grants` | planned (Phase 3 — schema + runtime ship together) | `cip_09_cross_tenant_grants` migration + runtime TBD |

2 features tagged `pillar:access-and-operations`. Plus `tenant-isolation-rls` is also tagged `pillar:structured-store` (it's cross-cutting).

9 RLS smoke tests at `tests/migrations/test_rls_cip_*.py` enforce isolation. M8 cross-tenant probe confirms `cip_metabase_role` querying as wrong tenant returns 0 rows.

## Status

- **Lifecycle:** operating
- **Maturity:** gold for RLS + SET LOCAL; planned for cross-tenant grants
- **Health summary:** 9/9 RLS smoke tests pass; M8 cross-tenant probe green
- **Last reviewed:** 2026-05-21

## What's NOT here

- **Postgres schema definition itself** → [Pillar 2 — Structured Store](../structured-store/) (Pillar 8 enforces; Pillar 2 declares)
- **The lens grant matrix** → [Pillar 5 — Consumption Surfaces](../consumption-surfaces/) (`cip_metabase_role` + lens grants — REVOKE on cip_*, GRANT on lens_*)
- **The FAS-side actor identity** → FAS Governance system (D-129; OAuth pass-through)
- **Authorization / RBAC** → out of scope today; tenant scoping is the primary access control. Future write-back authority model (Phase 2.5) adds an authority layer above tenant scoping

## Relationships

- **Parent:** [`foundry-cip`](../../../)
- **Siblings:** Pillars 1-7
- **Cross-references:** referenced by every other pillar; depends on FAS Governance for actor identity

## Where to go next

| Doc | When to open it |
|---|---|
| [`docs/RLS-SET-LOCAL-OPERATOR-GUIDE.md`](../../RLS-SET-LOCAL-OPERATOR-GUIDE.md) | Tenant isolation enforcement |
| [`docs/architecture/ARCHITECTURE.md`](../../architecture/ARCHITECTURE.md) | Phase 0 tenant model + RLS pattern (§3 Tenant Model) |
| `tests/migrations/test_rls_cip_*.py` | The 9 RLS smoke tests |
| `cip/integration_mesh/tenant_context.py` | The SET LOCAL middleware |
