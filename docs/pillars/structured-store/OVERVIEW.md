<!-- OVERVIEW.md per JOS-S19 -->
---
doc_type: overview
declared_thing: foundry-cip-structured-store
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

# Overview — CIP Pillar 2: Structured Store

## What this is

The Postgres home for every tenant's structured client data. 8 `cip_*` tables (companies, contacts, deals, tickets, files-metadata) carry tenant-scoped RLS, 9 provenance columns, JSONB overflow for non-canonical fields, and per-entity `*_history` tables for bitemporal SCD-2 history (valid-time + transaction-time). Driven by the SCD differ (app-layer SCD-2 per D-135), populated by the persister, and described by the per-connector property registry.

## What's inside

| Feature | Status | Code |
|---|---|---|
| `structured-store` | shipped (gold) | `cip/migrations/` |
| `property-registry` | shipped | `cip.integration_mesh.persister` |
| `scd-history` | shipped (gold) | `cip.integration_mesh.scd_differ` |
| `tenant-isolation-rls` | shipped (gold) | `cip.integration_mesh.tenant_context` (cross-cuts Pillar 8) |

4 features tagged `pillar:structured-store`.

11 Alembic migrations deployed: `cip_01_clients` through `cip_11_sync_mode_backfill`.

## Status

- **Lifecycle:** operating
- **Maturity:** gold across the board
- **Health summary:** schema stable since 2026-04-17; M5/M8 migration adds (cip_09-cip_11) shipped cleanly
- **Last reviewed:** 2026-05-21

## What's NOT here

- **The connectors that write to these tables** → [Pillar 1 — Ingestion & Connectors](../ingestion-and-connectors/)
- **Derived knowledge (chunks/vectors/graph)** → [Pillar 3 — Unstructured Store](../unstructured-store/) (different storage entirely — Pinecone + FalkorDB)
- **Lens views over the tables** → [Pillar 4 — Lens Engine](../lens-engine/)
- **RLS policy enforcement** → [Pillar 8 — Access & Operations](../access-and-operations/) (cross-cuts here)

## Relationships

- **Parent:** [`foundry-cip`](../../../)
- **Siblings:** Pillars 1, 3-8
- **Children:** the 11 Alembic migrations (treated as files, not subsystems)
- **Cross-references:** depends on Pillar 8; referenced by Pillars 1, 4, 5

## Where to go next

| Doc | When to open it |
|---|---|
| [`docs/MIGRATION-RUNBOOK.md`](../../MIGRATION-RUNBOOK.md) | Alembic migration operating guide |
| [`docs/architecture/ARCHITECTURE.md`](../../architecture/ARCHITECTURE.md) | Phase 0 data-model lock (1124 lines) |
| `cip/migrations/versions/` | The actual migration source |
