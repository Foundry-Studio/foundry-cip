---
id: CIP-SPEC-011
uuid: a5c8e3d2-7f4b-4e9a-b1d6-9c2e8f3a4b5d
title: Cross-Tenant Access Patterns — Mirror vs Grant (picking rule + worked examples)
type: spec
owner: tim
solve_for: Canonical decision rule for how one CIP tenant accesses another
  tenant's data — mirror (own-and-enrich) vs grant (read-only). Establishes
  the picking rule, the worked examples, and the trade-offs.
stage_label: adopt
domain: meta
version: '1.0'
created: '2026-05-22'
last_modified: '2026-05-22'
last_reviewed: '2026-05-22'
review_cadence: 180
authority_decisions:
- 306008ec
references:
- CIP-SPEC-010
- CIP-FW-003
---

# Cross-Tenant Access Patterns — Mirror vs Grant

CIP has **two distinct patterns** for one tenant to access another's data. They coexist. The picking rule is sharp; once you pick the wrong one for a use case the cost of switching is real.

This doc establishes the rule. Authored 2026-05-22 from Atlas's locked deep plan ([CIP-FW-003](vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md)) for PM scope `306008ec`.

## The picking rule

> **Need to OWN and ENRICH (companion fields, own workflows, own lens recut)?** → **Mirror**.
> **Only need to READ without owning?** → **Grant**.

Apply it like this. Walk the candidate use case through these questions:

1. **Will the consumer tenant need to write data back?** (Add notes, alias names, local-language context, lifecycle stage in *their* workflow?)
   - **Yes → mirror.** Grant is read-only by design; writing back would violate the grant contract.
   - **No → continue.**
2. **Will the consumer tenant need to reshape the data for their mental model?** (Different lens organization — by their reps, their pipeline stages, their client status?)
   - **Yes → mirror.** Lens recut is destination-tenant-private; grant exposes the SOURCE tenant's lenses.
   - **No → continue.**
3. **Should the access survive if the source tenant revokes it?** (Compliance retention; the consumer's records of historical relationships must persist?)
   - **Yes → mirror.** Grants vanish when revoked; mirrored data is the consumer's own physical copy.
   - **No → grant.** The consumer has no business outlasting source consent.

If steps 1 + 2 + 3 all say "no" → grant.
If any one says "yes" → mirror.

## The two patterns side-by-side

| Dimension | **Grant** (Phase 3) | **Mirror** (Phase 2.6) |
|---|---|---|
| Where the data lives | Once, in the source tenant's `cip_*` tables | Twice: source's `cip_*` AND consumer's `cip_*` |
| Consumer can READ? | Yes — through source's lens views, scoped by the grant filter | Yes — from consumer's own tables |
| Consumer can WRITE? | **No.** Grant model is read-only by design. | Yes, to a designated **companion** layer (sidecar JSONB column `companion_data`). NOT to the source-mirrored columns. |
| Consumer owns records? | No. Records belong to source. | Yes, **for the companion layer only.** Source-mirrored columns are owned by the source; the mirror overwrites them on every sync. |
| Lens reorganization? | Limited — consumer sees source's lenses | Yes — consumer authors its own destination-side lenses (Phase 2.7 work for PS) |
| Survives source access revoke? | No — `cip_cross_tenant_grants` row gone, access gone | Yes — consumer's physical copy persists |
| Tenant isolation at query time | RLS + grant-filter composition | RLS only — each tenant's queries scope to its own `tenant_id` GUC |
| Sync orchestration | None — every query reads live source state | Required — mirror connector + scheduled re-sync + post-sync `initial_intake_route` backfill |
| Storage cost | Single | Double (negligible at current scale) |
| Implementation surface | `cip_15_cross_tenant_grants` migration + grant-runtime in Phase 3 | `LensMirrorConnector` + per-entity mapper + two-pass orchestrator |
| Authority field model | Per-row (Phase 2.5 existing enum) | Per-row authority enum **plus** per-column companion separation via JSONB (Atlas Q1) |

## Worked example: mirror (Phase 2.6 — Project Silk + Wayward)

**Why mirror was picked:** PS uses Twenty CRM, and Twenty needs to write back companion fields — local-language aliases for Chinese brands, PS-team notes, lead status from PS's pipeline. A grant model couldn't allow these writes.

**Mechanics:**
- Source tenant: EcomLever (`dec814db-…`), which owns Wayward's `cip_companies`/`_contacts`/`_deals` rows
- Destination tenant: Project Silk (`078a37d6-…`)
- Source-side lenses define the subset: `lens_china_clients` (deals) + `lens_china_companies` + `lens_china_contacts` (entity lenses from cip_24)
- Mirror connector reads each lens under EcomLever's GUC, materializes rows, yields back to the orchestrator running under PS's GUC for writes
- PS `cip_clients` ids are deterministic: `uuid5(PS_TENANT, f"wayward-china:{hubspot_company_id}")`
- Two-pass orchestration: Pass 1 dedupes upstream company_ids → PS `cip_clients`; Pass 2 mirrors the entity rows with resolved client_id FKs
- **Twenty's writes go to `companion_data` JSONB only**, enforced by column-level GRANT on the `cip_twenty_project_silk` role
- **The mirror never writes `companion_data`** because it's not in the mapper's emitted fields — structural enforcement on the writer side
- Sync runs every 30 min + event-triggered on EcomLever Wayward sync completions

**Why this matters as a precedent:** the pattern Atlas locked here is the canonical mirror pattern for ALL future cross-tenant own-and-enrich relationships. The `companion_data` column + column-level GRANT + Pass-1-creates-clients pattern repeats verbatim for the next consumer venture.

## Worked example: grant (Phase 3 — Foundry self-tenant + research synthesis)

**Why grant was picked:** Foundry's self-tenant aggregates research/observations from multiple venture tenants. It needs to read across them — not own their records. Adding a Twenty-style write-back layer would muddy provenance (whose authoritative view is this?). The data stays with the source.

**Mechanics:**
- Source tenants: any venture with a `cip_cross_tenant_grants` row pointing at Foundry-self
- The grant carries a `filter JSONB` (which subset of the source tenant's data is visible) and an `authority_floor` (minimum trust level — e.g., only `validated`, not `agent_discovered`)
- A `grant_window` activates/expires the grant for compliance retention
- Foundry-self's queries pass through a grant-aware access layer that composes (grant filter ∧ lens filter ∧ tenant GUC) at query time
- Every cross-tenant read writes to an audit log keyed by grant_id

**Why this isn't done with a mirror:** the Foundry-self use case is reading-many-tenants synthesis. Mirroring every venture's full content into Foundry-self would multiply storage AND require Foundry-self to maintain a re-embed pipeline for every tenant's content. Grant is the right shape — read live, scope tightly, audit every access.

## Concrete consequences of picking wrong

If you pick **grant** when **mirror** is right:
- Consumer wants to write back; can't. Either accept the limitation forever, or do a full mirror migration later (which means rebuilding consumer-side lenses on the new data plane). Cost: meaningful refactor.

If you pick **mirror** when **grant** is right:
- Storage doubles unnecessarily.
- Sync orchestration runs on a schedule the consumer doesn't actually need.
- Every source change has a propagation delay (~30 min from the schedule).
- The consumer's mirrored data drifts from the source between syncs — and if the consumer never writes companion data, that drift serves no purpose.

## What this doc does NOT cover

- The implementation of either pattern. See:
  - [`docs/CONNECTOR-AUTHORING-GUIDE.md`](CONNECTOR-AUTHORING-GUIDE.md) for `LensMirrorConnector` as a worked example
  - Phase 3 plan + `cip_15_cross_tenant_grants` migration (when authored) for the grant pattern
- The authority/companion field model. See [`CIP-FW-003`](vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md) §Q1.
- The exact source vs destination column-set responsibility. See `cip_23_phase26_schema` (and cip_25's column-level GRANT).
- Stage 1 / 2 / 3 graduation. See [`CIP-SPEC-010`](ARCHITECTURE-SPLIT.md) §5.

## Cross-references

- [`docs/ARCHITECTURE-SPLIT.md`](ARCHITECTURE-SPLIT.md) (CIP-SPEC-010) — the CIP Hard Split, which is *intra-CIP* data-plane isolation. This doc is *inter-CIP-tenant*. Different axis; both apply.
- [`docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md`](vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md) (CIP-FW-003) — the locked design behind mirror.
- [`docs/vision/ROADMAP.md`](vision/ROADMAP.md) — phase ordering. Phase 2.6 ships mirror; Phase 3 ships grant runtime; both coexist.

---

_Resolves PM scope `306008ec`'s "deliverable for §5.2 picking rule" + `7bde40e3`'s new-doc requirement._
