---
kind: doc
domain: client-intelligence-platform
status: skeleton
last_updated: 2026-04-20
milestone: Phase-1-M0
---

# Phase 1 → Phase 2 Handoff

> **Status:** skeleton stub — authored Phase 1 M0, populated at Phase 1 M8 (the handoff gate itself).
> Once final, this doc is the bridge from "plain-jane CIP green against the fixture tenant" to "Wayward Onboarding — full round-trip." It is the deliverable that closes Phase 1.

## Purpose

Enumerate the state at the end of Phase 1 (code, data, docs, tests, PM status) and the explicit Phase 2 entry criteria — so that a fresh engineer can pick up Phase 2 (Wayward Zendesk + HubSpot ingestion, then outbound to Chatwoot/Twenty/Drive, then REST first-light) without re-reading Phase 1 history.

## Who reads this

- The engineer running Phase 2 M1–M9.
- Tim / Atlas at the Phase-1 product-ready gate.
- Future phase leads who need a reference for "what 'product-ready' means" as a pattern.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Creates this skeleton. |
| M7 — Four-access-paths validation | Populates §2 "What's green" evidence block. |
| M8 — Phase 1 product-ready gate | Populates the bulk of this doc; flips `status: final`. |

Cross-ref: [`PHASE-1-PLAIN-SPEC.md §2`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md) acceptance criteria, [`ROADMAP.md`](../../products/client-intelligence-platform/vision/ROADMAP.md) Phase 2 block, CIPWAY project in PM.

## Outline

### 1. Phase 1 final state — code

TBD (M8) — migrations cip_01–cip_08 applied, connector framework + FixtureConnector live, orchestrator live, Lens-A/Lens-B configured, discoverability registry populated, four access paths green.

### 2. What's green (evidence)

TBD (M7, M8) — link to `validation/M7-discoverability-report.md`, test pass counts, fixture byte-identical hash.

### 3. Phase 1 final state — docs

TBD (M8) — this folder (`docs/cip/`) all `status: final`; cross-refs verified; `_TEMPLATE.md` retained for future docs.

### 4. Phase 1 final state — PM

TBD (M8) — CIP main project scopes closed; CIPWAY M1 ready to start; CIPRR still queued behind Phase 2.

### 5. Known-unknowns carried into Phase 2

TBD (M8) — items intentionally deferred (real-credential auth flows, pagination quirks in Zendesk/HubSpot, history-clock semantics for HubSpot).

### 6. Phase 2 entry criteria

TBD (M8) — fixture regression still passes, Wayward tenant provisionable, Zendesk + HubSpot credentials available, Chatwoot/Twenty/Drive target endpoints identified.

### 7. Phase 2 M1 first-action brief

TBD (M8) — the 1-paragraph brief for the Phase-2-M1 engineer: what to read, what to build first (Zendesk connector), what conformance harness to run.

### 8. Delta against `CONNECTOR-AUTHORING-GUIDE.md`

TBD (M8) — anything Phase 2 discovers that requires updating the guide (fed back into `docs/cip/` when learned).

### 9. Non-goals of this handoff

TBD (M8) — this doc does not design Phase 2; it only hands off Phase 1. Phase 2 design lives in `PHASE-2-PLAN.md` (CIPWAY M0).
