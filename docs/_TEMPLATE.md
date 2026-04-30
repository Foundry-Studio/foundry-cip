---
kind: doc
domain: client-intelligence-platform
status: skeleton
last_updated: 2026-04-20
milestone: Phase-1-M0
---

# {DOC TITLE}

> **Status:** skeleton stub — authored Phase 1 M0, populated as Phase 1 milestones land.
> Each outlined section below carries a `TBD (M<n>)` marker indicating which Phase 1 milestone is expected to fill it in. Do not consume this doc as normative until `status: final`.

## Purpose

{ONE SENTENCE: what question this doc answers and why it exists.}

## Who reads this

{BULLETED LIST: primary audience — e.g. "A second engineer onboarding a new tenant without Atlas/Tim in the room."}

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M<n> — {name} | {why this milestone populates this doc} |

Cross-ref: [`PHASE-1-PLAN.md`](../../products/client-intelligence-platform/vision/PHASE-1-PLAN.md), [`PHASE-1-PLAIN-SPEC.md`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md).

## Outline

### 1. {Section name}

TBD (M<n>)

### 2. {Section name}

TBD (M<n>)

### 3. {Section name}

TBD (M<n>)

## Template conventions

- **Frontmatter fields** are mandatory. `kind`, `domain`, `status`, `last_updated`, `milestone`.
  - `kind: doc` for all CIP docs in this folder.
  - `domain: client-intelligence-platform` until a finer-grained CSS domain is locked.
  - `status: skeleton | draft | final`. Flip to `draft` when any section is populated; flip to `final` only at the M9 Phase-1 gate.
  - `last_updated` UTC date.
  - `milestone` = the milestone that last touched this file (`Phase-1-M0` until first content lands).
- **TBD markers:** every un-populated section ends with `TBD (M<n>)` naming the milestone expected to populate it.
- **Cross-refs:** every skeleton links back to `PHASE-1-PLAN.md` + `PHASE-1-PLAIN-SPEC.md` so a reader can find the authoritative source.
- **Normative tone:** once populated, docs speak in imperative voice ("Run X", "Verify Y"), not descriptive voice.
