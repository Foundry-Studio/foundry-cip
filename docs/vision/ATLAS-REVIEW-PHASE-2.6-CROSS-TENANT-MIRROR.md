---
id: CIP-FW-002
uuid: 5e8c2a91-7b3f-4d6e-9c8a-1f4d3a5b7c9e
title: Atlas Review Request — Phase 2.6 Cross-Tenant Lens-Mirror Architecture
type: framework
owner: tim
solve_for: One-shot copy-paste prompt for Atlas's architecture review of
  the Project Silk cross-tenant lens-mirror design (PM scope 306008ec /
  Phase 2.6 §3.2 authority-companion mechanism + 4 related open questions).
stage_label: trial
domain: meta
version: '1.0'
created: '2026-05-22'
last_modified: '2026-05-22'
last_reviewed: '2026-05-22'
review_cadence: 30
---

# Atlas Review — Phase 2.6 Cross-Tenant Lens-Mirror Architecture

> **For Tim to copy-paste:** everything below the `===` line is the prompt to send Atlas. The intro is just orientation for the operator.

This is the architecture-review unblocker for PM scope `306008ec` (sort_order 210 on CIP project `596825db`). Atlas's deep plan output here unlocks scopes 220 (schema), 230 (LensMirrorConnector), 240 (PS tenant provisioning), and 260 (docs). Until Atlas decides §3.2's authority/companion mechanism, the LensMirrorConnector cannot be written.

The handoff that generated this review request lives at:
`Foundry-Agent-System/WORKBENCH/handoffs/cip-handoff-2026-05-22-project-silk-cross-tenant-mirror.md`

The locked design decisions from Tim's 2026-05-22 conversation are listed inline below — Atlas should NOT relitigate them, only build on them.

---

=====================================================================
COPY EVERYTHING BELOW THIS LINE TO ATLAS
=====================================================================

# Atlas Architecture Review — Phase 2.6 Cross-Tenant Lens-Mirror (foundry-cip)

You are Atlas. You have full architectural authority over foundry-cip. The Tim has filed an architecture-review scope (PM scope `306008ec` on CIP project `596825db-61bc-4899-bc6c-e207489ca35d`) and downstream implementation work is blocked until you produce a v5.x-style deep plan answering the five open questions below.

## Read this first

The originating handoff document is at:
`Foundry-Agent-System/WORKBENCH/handoffs/cip-handoff-2026-05-22-project-silk-cross-tenant-mirror.md`

It defines the full ask. Read it end-to-end before answering.

Key existing references you will need to ground against:
- `foundry-cip/docs/ARCHITECTURE-SPLIT.md` (CIP-SPEC-010, the Hard Split decision locked 2026-05-19)
- `foundry-cip/cip/migrations/versions/cip_09_metabase_role_views.py` (Postgres role + lens-view pattern; cip_21 just shipped using this pattern)
- `foundry-cip/cip/migrations/versions/cip_18_wayward_attr_lenses.py` (the existing `lens_china_*` lenses the mirror will read from)
- `foundry-cip/cip/integration_mesh/base.py` (`CIPConnector` / `CIPMapper` / `CIPRow` Protocols the new `LensMirrorConnector` must conform to)
- `foundry-cip/cip/migrations/versions/cip_12_seed_wayward_client.py` and `foundry-cip/scripts/migrate_b0_to_ecomlever.py` (cautionary tale: the b0000000-... UUID-placeholder incident cost a 1.26M-row migration to fix; Phase 2.6 PS-tenant provisioning must use a real UUIDv4)
- `foundry-cip/docs/vision/ROADMAP.md` (current phase shape — Phase 2 Wayward closed, Phase 2.5 Hard Split closed 2026-05-22, Phase 3 cross-tenant grants ORIGINAL design awaiting re-evaluation in light of Tim's mirror choice for PS)
- `foundry-cip/docs/vision/PHASE-2.5-PLAN.md` (the original Phase 2.5 authority enum design — `agent_discovered` / `ingested` / `validated`, per-row, NOT per-field)

## Locked decisions (do NOT relitigate)

These came from Tim's 2026-05-22 conversation and the handoff §3. Build your plan on them; don't second-guess them.

1. **Mirror-based, NOT grant-based**, for the PS↔Wayward data flow. PS gets its own physical CIP tenant with its own cip_* rows, populated by mirroring from EcomLever's `lens_china_*`. Reasoning behind Tim's choice: Twenty CRM needs to write back companion fields (impossible under read-only grant); PS-team enrichments must not pollute Wayward's source-of-truth; tenant isolation stays clean at read time.
2. **PS is a multi-product venture**. Wayward is one product PS uses. PS's `cip_clients` rows are PS's own end-brand clients (Chinese brands), NOT Wayward itself. Do not collapse this conceptually.
3. **Dedup rule**: 1 PS `cip_clients` row per upstream HubSpot company_id, regardless of how many deals link to it.
4. **`initial_intake_route` field** is new on `cip_clients`: set on INSERT only by the mirror (preserves first-touch provenance), never overwritten. First wave value: `'wayward'`. Future values: `'twenty'`, `'direct'`, `'referral'`, `'manual'`, extensible.
5. **CIP stays source-of-truth.** Twenty CRM may cache for UI speed but flows write back to CIP, not vice versa.
6. **Sync cadence**: event-triggered on EcomLever's Wayward sync completion + scheduled every 30 minutes. Both invokers call the same orchestrator with the same connector.
7. **`cip_21` grant role migration** has already shipped (2026-05-22) as the read-only interim while you review this. The foundry-metabase side is provisioning a Stage 1 PS Metabase tenant against EcomLever's `lens_china_*` via that role. Stage 2 (this work) replaces the binding with a real PS CIP tenant — lens names preserved, dashboards survive.

## The five questions to answer

### Q1 (BLOCKER for §230 LensMirrorConnector): Authority / companion field mechanism

Every PS `cip_*` entity row will have two field classes:
- **Source fields** = populated and exclusively writable by the mirror from EcomLever
- **Companion fields** = PS-owned, writable by Twenty CRM + PS staff, NOT touchable by the mirror

Three candidate mechanisms (handoff §3.2):
- **(a) Per-field authority tag**: extend Phase 2.5's authority enum to per-field. Every field carries a `lens-mirror` / `twenty` / `manual` provenance tag. Persister enforces "mirror can only write fields tagged `lens-mirror` or NULL".
- **(b) Sidecar JSONB column**: every `cip_*` table gets a `companion_data JSONB NOT NULL DEFAULT '{}'::jsonb`. Source fields stay in their existing typed columns (mirror writes them); companion fields live in `companion_data` (Twenty / manual writes). Loses typed columns for companion data.
- **(c) Sidecar tables**: separate `cip_companies_companion`, `cip_contacts_companion`, etc., 1:1 joined to primaries. Most explicit; most schema churn.

**Handoff author's recommendation: (b) sidecar JSONB.** Reasoning: lowest blast radius, doesn't refactor existing cip_* tables, ergonomically clear ("anything in `companion_data` is PS-owned"). Promotion path: if a companion field gets heavy query use, normal future migration adds a typed column. The Phase 2.5 per-field authority pattern can be layered on later — not mutually exclusive.

**Your job:** bless (b), override with one of (a)/(c), or propose a fourth shape with clear reasoning. If you bless (b), specify exact schema (column name, default, index strategy, JSONB key conventions) so the cip_22 schema migration in scope 220 can be written deterministically.

### Q2: Relationship to Phase 3 (cross-tenant grants)

Phase 3 was originally planned as a grant-based cross-tenant access model (`cip_15` migration shipping schema + runtime together, per ROADMAP). Tim's choice of mirror-based for PS pulled that work forward into Phase 2.6.

Three options for Phase 3's revised shape:
- **(A) Phase 3 becomes mirror-first.** All future inter-tenant flow uses the LensMirrorConnector pattern from Phase 2.6. Grant-based access deprecated.
- **(B) Both patterns coexist.** Mirror for cases where write-back is needed; grant for pure read-only flows (e.g., observational dashboards). State the decision rule for picking.
- **(C) Phase 3 stays grant-based as planned**, and Phase 2.6's mirror is treated as a one-off for the PS-specific need.

State your call + reasoning + decision rule (for option B).

### Q3: Relationship to Phase 2.5 (Foundry self-tenant + write-back authority enum)

Phase 2.5's authority enum (`agent_discovered` / `ingested` / `validated`) was designed as **per-row** provenance, originally for Foundry's self-tenant write-back loop. The companion-layer design here is **per-field**.

Two options:
- **(A) Extend authority enum to per-field.** All Phase 2.5 work becomes a foundation for the per-field model; Q1's option (a) becomes the natural fit.
- **(B) Authority enum stays per-row** (for its original Foundry self-tenant purpose); companion layer uses a different mechanism (sidecar JSONB per Q1 option b).

If you bless Q1 option (b), Q3 option (B) is the natural pairing. If you override Q1 to option (a), Q3 likely flips to option (A). Make the dependency explicit.

### Q4: RLS + GUC safety across tenants in one connector session

The `LensMirrorConnector` needs to:
1. `SET LOCAL app.current_tenant = '<source_tenant_id>'` (EcomLever) to read source `lens_china_*` views
2. `SET LOCAL app.current_tenant = '<dest_tenant_id>'` (PS) to write to PS's `cip_*` tables

Within the **same Postgres session**. Two GUC swaps per row-batch.

**The question:** is this safe with the existing M2 advisory-lock + RLS pattern? Specific concerns to address:
- RLS policy caching at the session level — does swapping `app.current_tenant` mid-session cause Postgres to re-plan the policy or apply a stale plan to in-flight transactions?
- Advisory-lock semantics — the existing orchestrator uses session-level advisory locks; do those interact badly with the GUC swap?
- Connection pooling — if SQLAlchemy hands back a pooled connection that previously had a different `app.current_tenant`, is the GUC always reset before reuse?
- Failure mode at GUC swap — if the swap itself raises, where does the transaction stand? Is the connection still safe to return to the pool?

If any concern is non-trivial, propose either: (1) a defensive pattern (e.g., open a fresh connection per mirror run, never reuse), or (2) explicit DBA-level guardrails (e.g., postgres-level event triggers asserting tenant changes are logged).

### Q5: PS lens recut — Phase 2.6 atomic, or Phase 2.7 follow-up?

PS's lenses are NOT 1:1 with EcomLever's. EcomLever's `lens_china_*` are organized by Wayward attribution source (Eric/Tim/Adina referrals). PS's lenses will be organized by PS's mental model (PS rep, PS pipeline stage, PS-side client status).

Handoff author's lean: **Phase 2.7 follow-up** — mirror data is queryable via the existing `cip_views` registry before PS-specific lenses are recut. Mirror lands first.

Tim's input is needed on the actual PS lens taxonomy. Your call: should the lens recut be inside Phase 2.6 (one atomic shippable unit), or split out to Phase 2.7 (mirror ships first, lenses second)?

## Expected output format

Deliver a deep plan in the v5.x format prior CIP plans have used. Sections:

1. **Decision summary** — one-line answer for each of Q1–Q5
2. **Q1 mechanism deep-dive** — exact schema, JSONB key conventions (if applicable), persister-enforcement strategy, test plan
3. **Q2 Phase 3 reshape** — what changes in the ROADMAP, what migrations get renumbered, what tests get updated
4. **Q3 authority enum dependency** — explicit, with file/line pointers into existing Phase 2.5 code if relevant
5. **Q4 RLS/GUC safety analysis** — concrete checks the implementer must pass, plus the defensive pattern if you flag the risk as non-trivial
6. **Q5 phase split** — final shape of Phase 2.6 vs Phase 2.7 if you split them
7. **Concerns / counter-cases** — anything the handoff author missed that should be raised before code lands
8. **Implementation pointers** — file paths in foundry-cip where the changes go, migration numbers, test placement

Constraint: the deep plan must be ship-implementable by an agent working solo against the codebase, with no further architectural questions to Tim. If there's an open question Tim must answer, isolate it and tag it `[BLOCKING: Tim decision required]` so he can resolve before the implementation scope unblocks.

## Boundary conditions

- Do NOT propose new connectors beyond LensMirrorConnector
- Do NOT propose schema changes outside the scope of the 5 questions (e.g., don't redesign `cip_files` or touch `cip_knowledge_chunks` — those are out of scope)
- Do NOT propose changes to Phase 1 (Plain Jane) — it's closed
- Phase 2.5 Foundry self-tenant write-back is parked; you may reshape its authority enum design but cannot retire it
- The Hard Split (CIP-SPEC-010) is binding — no recommendation that crosses CIP-Pinecone with Foundry-Pinecone, or that puts CIP-shaped data into Foundry-Knowledge

When you're done, output the deep plan as a single markdown response. Tim will paste it back as the response to this review.
