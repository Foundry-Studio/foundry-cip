---
kind: doc
domain: client-intelligence-platform
status: archived
archived_on: 2026-04-20
archived_by: atlas (Tim-authorized hardening sweep)
supersedes: ../../stages/
replaced_by:
  - ../../vision/ROADMAP.md
  - ../../vision/PHASE-1-PLAN.md
---

# Archived: `stages/` Folder (Superseded 2026-04-20)

The original CIP `stages/` folder contained 8 empty scaffold files (`phase-0-data-model.md` through `phase-7-intelligence-layer.md`). Each was a bare template with the same structure (Status / Decisions for Tim / Implementation Plan / Acceptance Criteria / Notes) — all sections empty.

## Why archived

1. **Phase numbering drift.** The old stubs assumed a phase shape that doesn't match the current roadmap. The 2026-04-20 rescope (Tim's "base product first, then per-tenant onboarding") restructured phases entirely: Phase 1 is now a tenant-neutral Base Product build, Phase 2 is Wayward Onboarding, Phase 3 is Rocky Ridge Onboarding, and Phase 5 is now a dedicated Chatbot Capability phase (rather than the old `phase-5-web-chatbot.md` stub). Keeping the old stubs around would confuse anyone reading the product folder about which numbering is authoritative.

2. **Superseded by per-phase plans.** When a phase is worked, it gets its own VISION / WDGLL / SPEC / PLAN document alongside `ROADMAP.md` (e.g., `vision/PHASE-1-PLAN.md`). The per-phase stubs were never populated — they were placeholders from Phase 0 planning, before we landed on the "plan each phase as its turn comes" model.

3. **No content loss.** Every stub was empty. Any content they contained is zero.

## Source of truth going forward

- **Phase structure and scope:** `products/client-intelligence-platform/vision/ROADMAP.md`
- **Active phase plan (currently Phase 1):** `products/client-intelligence-platform/vision/PHASE-1-PLAN.md`
- **Future phases:** get their own `PHASE-N-PLAN.md` authored at kickoff, not pre-scaffolded.

## If you're looking for the old file

They're still here, one level down in `stages/`. They exist for historical traceability only. Do not edit them — edit the current roadmap and per-phase plans instead.
