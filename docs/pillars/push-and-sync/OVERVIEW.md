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
declared_thing: foundry-cip-push-and-sync
declared_thing_kind: subsystem
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
audience: [dev, product]
diataxis_type: explanation
---

# Overview — CIP Pillar 6: Push & Sync

## What this is

The other half of the data loop — outbound write-back from CIP to external systems. Where Pillar 1 (Ingestion) brings client data IN, Pillar 6 ships it OUT. Phase 2 lights up the first push surfaces (Chatwoot for support tickets, PS Twenty CRM for lead nurture, Google Drive for client artifacts). Phase 2.5 adds the authority model (`agent_discovered` / `ingested` / `validated`) so write-back is governed, not free-fire.

## What's inside

| Feature | Status |
|---|---|
| `outbound-push` | planned (Phase 2-2.5) |

1 feature tagged `pillar:push-and-sync`. Will fan out as Phase 2 lands push surfaces.

## Status

- **Lifecycle:** building (planning)
- **Maturity:** bronze — Phase 2 entry criterion + Phase 2.5 authority model both still to land
- **Active concern:** the authority model design — Phase 2.5 will lock how `agent_discovered` promotes to `ingested` to `validated` with TSP thresholds
- **Last reviewed:** 2026-05-21

## What's NOT here

- **The sources we're writing back to** → external (Chatwoot, PS Twenty CRM, Google Drive)
- **The connector framework that reads from those sources** → [Pillar 1 — Ingestion & Connectors](../ingestion-and-connectors/) (different direction)
- **The Foundry self-tenant write-back producer** → Phase 2.5 will provision Foundry as a peer tenant; write-back is one of its uses
- **Cross-tenant write-back governance** → [Pillar 8 — Access & Operations](../access-and-operations/) (cross-tenant grants runtime Phase 3)

## Relationships

- **Parent:** [`foundry-cip`](../../../)
- **Siblings:** Pillars 1-5, 7-8
- **Cross-references:** depends on Pillars 2 + 8; tightly coupled to Pillar 1's connector framework (push uses the same auth + rate-limit primitives)

## Where to go next

| Doc | When to open it |
|---|---|
| [`docs/vision/PHASE-2.5-PLAN.md`](../../vision/PHASE-2.5-PLAN.md) | Phase 2.5 write-back + authority model VISION/WDGLL/SPEC/PLAN |
| [`docs/vision/ROADMAP.md`](../../vision/ROADMAP.md) | Phase 2 + Phase 2.5 shape |
| `cip/integration_mesh/` | Where the push framework will land |
