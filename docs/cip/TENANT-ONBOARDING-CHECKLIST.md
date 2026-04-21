---
kind: doc
domain: client-intelligence-platform
status: skeleton
last_updated: 2026-04-20
milestone: Phase-1-M0
---

# Tenant Onboarding Checklist

> **Status:** skeleton stub — authored Phase 1 M0, populated as Phase 1 milestones land.
> Once final, this checklist is the canonical path for bringing any new tenant onto CIP. Phase 1 validates it against the fixture tenant only; Phase 2 validates it against Wayward; Phase 3 extends it for cross-tenant grants.

## Purpose

End-to-end, copy-pasteable checklist for standing up a new CIP tenant from empty DB to "all four access paths green," using only this document plus the other nine Phase-1 doc artifacts.

## Who reads this

- A second engineer onboarding a new tenant without Atlas or Tim in the room.
- Operators re-seeding the fixture tenant during development.
- Phase 2 / Phase 3 onboarding runners (Wayward, Rocky Ridge) who cross-reference this as baseline.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Plan authoring + doc skeletons | Creates this skeleton. |
| M1 — Migrations cip_01–cip_08 | Populates §3 DB provisioning. |
| M2 — Connector framework + FixtureConnector | Populates §4 connector registration. |
| M3 — Sync orchestrator | Populates §5 first-sync runbook. |
| M4 — Lens engine + Lens-A / Lens-B | Populates §6 lens configuration. |
| M5 — Knowledge + Graph wiring | Populates §7 derived-knowledge wiring. |
| M6 — Discoverability registry | Populates §8 registry verification. |
| M7 — Four-access-paths validation | Populates §9 green-light gate. |

Cross-ref: [`PHASE-1-PLAN.md`](../../products/client-intelligence-platform/vision/PHASE-1-PLAN.md), [`PHASE-1-PLAIN-SPEC.md`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md).

## Outline

### 1. Prerequisites

TBD (M1) — DB reachable, Roster credentials, Pinecone index, FalkorDB instance, R2 bucket, env vars.

### 2. Register the tenant

TBD (M1) — `tenants` row insert, tenant_id allocation, RLS policy attachment.

### 3. Run CIP migrations in order

TBD (M1) — cip_01 → cip_08 sequence, smoke-test `SET LOCAL app.current_tenant` after each.

### 4. Register a connector

TBD (M2) — declare in `integration-mesh` registry, wire credentials, confirm `authenticate()` passes.

### 5. Run first sync

TBD (M3) — invoke orchestrator, watch `cip_sync_runs`, verify row counts per `cip_*` table.

### 6. Configure lenses

TBD (M4) — seed Lens-A + Lens-B config rows, verify golden-file parity.

### 7. Wire derived-knowledge ingestion

TBD (M5) — enable per-connector `ingest_as_knowledge()` fields, verify Pinecone + FalkorDB writes.

### 8. Verify discoverability registry

TBD (M6) — `cip_connector_property_registry` populated for all object_types, no orphans.

### 9. Green-light gate

TBD (M7) — all four access paths return non-empty results, cross-tenant probe returns zero rows, validation report committed.

### 10. Rollback / teardown

TBD (M8) — DB teardown script, credential revocation, registry cleanup.
