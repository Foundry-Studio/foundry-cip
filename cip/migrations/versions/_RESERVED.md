# Reserved Migration Slots

This file documents migration slot numbers reserved for future Phase 3 work in this `migrations/versions/` directory. Do not author migrations with these names — they are pre-allocated to avoid renumbering when Phase 3 work lands.

## Reserved slots

| Slot | Reserved for | Phase | Status |
|---|---|---|---|
| `cip_09_cross_tenant_grants.py` | `cip_cross_tenant_grants` table — schema for `cip_cross_tenant_grants` per CIP M2 v4 plan §A | Phase 3 | RESERVED |
| `cip_10_<tbd>.py` | TBD — adjacent reservation per Tim's Q1 directive 2026-04-27. Likely a Phase 3 cross-tenant grant runtime table or RLS policy expansion. | Phase 3 | RESERVED |

## Why this file exists

CIP Phase 1 ships migrations `cip_01` through `cip_08`. CIP M2 (now in foundry-cip) added two more migrations `cip_11_rename_sync_runs_metadata` and `cip_12_sync_runs_counter_split` — chosen because Phase 3 (Rocky Ridge cross-tenant grants) wanted `cip_09` and `cip_10` adjacent in the chain.

Skipping `cip_09` and `cip_10` in Phase 1's chain creates a numerical gap. Without this RESERVED.md, a future contributor might:

1. See no `cip_09_*.py` and assume the next available number is 9.
2. Author `cip_09_<their_thing>.py` with `down_revision = "cip_08_tickets_and_registry"`.
3. Phase 3 later wants to land its `cip_09_cross_tenant_grants.py` — collision.

This file is the loud, discoverable signal that 9/10 are reserved. Phase 1/M2 contributors who need a new migration should use `cip_13_<descriptive>.py` or higher.

## Authority

Reservation locked by the M2 v4 plan's renumber decision (cip_11 + cip_12). See:
- `docs/vision/PHASE-1-PLAN.md` (M2 milestone)
- The CIP M2 deep plan (referenced in `docs/archive/cip-m2-deep-plan.md` post-M2-execution)
- D-146 (the extraction itself) does not address this reservation — it predates D-146.

To change the reservation, propose via Foundry-Agent-System's `docs/DECISION-LOG.md` (governance authority remains with the monorepo per D-146).
