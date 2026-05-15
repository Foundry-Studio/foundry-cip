---
kind: doc
domain: client-intelligence-platform
project_id: client-intelligence-platform
pm_project_id: 596825db-61bc-4899-bc6c-e207489ca35d
phase: 2
shape: wayward-onboarding-wdgll
status: stub
owner: tim
authors: [tim, cc-session-2026-05-15]
created: 2026-05-15
last_updated: 2026-05-15
depends_on: [phase-1-plain-jane]
blocks: [phase-2.5-write-back, phase-3-rocky-ridge-and-grants-runtime]
---

# Phase 2 — Wayward Onboarding · What Does Good Look Like (WDGLL)

> Per the per-phase docs pattern declared at the top of `ROADMAP.md`: every phase gets its own VISION/WDGLL/SPEC/PLAN artifact. Phase 1 has `PHASE-1-PLAIN-SPEC.md` in that slot; Phase 2.5 has `PHASE-2.5-PLAN.md`. This file is Phase 2's WDGLL — the criteria the team will hold the Wayward onboarding to before declaring Phase 2 done.
>
> **Status — stub.** Authored 2026-05-15 during the active Wayward HubSpot historical backfill + Zendesk current-state sync. Sections below are placeholders to be filled in once the live run completes and we know what actually came back.

## Purpose

Phase 2 is **Wayward's full round-trip** — the first real tenant on CIP, validating inbound ingestion + outbound push + lens behavior + real-data observability. This doc captures **what "good" looks like** at the consumer/business level, not the implementation level. Pair it with `ROADMAP.md` (Phase 2 block) and any future `PHASE-2-PLAN.md` for the SPEC/PLAN side.

## What "good" looks like at Phase 2 end

### Data completeness (inbound)

- [ ] Wayward HubSpot current-state data is ingested for every entity available to the Wayward HubSpot token: companies, contacts, deals (tickets explicitly excluded — Wayward token lacks the HubSpot tickets scope; ticket data lives in Zendesk for this tenant)
- [ ] Wayward Zendesk current-state data is ingested for every entity: organizations, users, tickets
- [ ] Historical backfill (D-159) has run successfully for HubSpot companies/contacts/deals — `cip_*_history` tables contain one row per recorded HubSpot property revision per record per timestamp
- [ ] Historical backfill has run for Zendesk tickets via the ticket-audit API — `cip_tickets_history` contains audit-derived snapshots
- [ ] No silent gaps — `cip_sync_runs` shows status `success` or `partial` (with structured `error_detail`) for every connector × entity, never `failed` with the rest of the load incomplete

### Data fidelity

- [ ] Custom HubSpot properties relevant to Wayward's business (owner, market/region segmentation, referral/partner source — to be enumerated with Wayward admin) are actually fetched and queryable. The slim-property-set issue surfaced 2026-05-15 (PM scope `9c3d1393`) must be fixed before this gate
- [ ] Country-encoding normalization is in place — `cip_companies.country` queries work for both ISO codes (`CN`, `HK`, `TW`) and full names (`China`, `Hong Kong`, `Taiwan`); ideally via a lens view rather than ad-hoc query
- [ ] Source-of-truth resolution is documented — when both HubSpot and Zendesk represent the same company/contact, the authority + provenance columns tell the consumer which record won and why

### Lens behavior

- [ ] **EcomLever Full View** lens exists, applies no filters, and returns every Wayward row when the EcomLever tenant runs it
- [ ] **PS China Precursor View** lens exists, filters by region/language/country to the China-region slice, returns substantially fewer rows than Full View. The row-count delta is the P-21 proof
- [ ] Lens behavior is identical between Metabase, raw SQL via `foundry_mcp_db_query`, and (when shipped) the REST API surface

### Outbound (Push & Sync) — first light

- [ ] Push to Chatwoot — tickets routed per lens. Replaces the one-off `zendesk_to_chatwoot.py` script
- [ ] Push to PS Twenty CRM — HubSpot contacts/companies sync per the EcomLever→ProjectSilk grant (note: full grant runtime is Phase 3, but Phase 2 ships the push wiring against a hardcoded grant placeholder)
- [ ] Push to client Google Drive — at least one scheduled-report export lands as a PDF/CSV in a per-client folder
- [ ] First-light REST API — `/cip/query` and `/cip/search` answer at least one real Wayward question end-to-end (auth + tenant scoping + lens + JSON response)

### Observability & operability

- [ ] `cip_sync_runs` is the source of truth for "when did each connector last sync, what did it ingest, what did it skip" — every operator question answerable from this table without log-spelunking
- [ ] Each connector run records structured `error_detail` JSON when status ≠ `success` — not just a string, but an inspectable record of entities attempted/skipped/succeeded with reasons (per PM scope `d3311846` — connector resilience)
- [ ] At least one alert configuration is live (Slack or email) for "no successful Wayward sync in the last N hours" — the minimum observable health signal. Full Intelligence & Alerts pillar is Phase 6, but the heartbeat must exist by Phase 2 end
- [ ] Tenant Onboarding Checklist (Phase 1 deliverable) was followed for Wayward and any gaps from the synthetic-fixture-tenant version are captured for the next tenant

### Documentation gates

- [ ] `PHASE-1-TO-PHASE-2-HANDOFF.md` exists and was actually used (any gaps captured for v2)
- [ ] This WDGLL doc is filled in with concrete row counts, lens names, alert configs, and dashboard URLs
- [ ] A short "Wayward Phase 2 Retrospective" doc exists, parallel to `PHASE-1-RETROSPECTIVE.md`, capturing what was supposed to ship, what actually shipped, and what got deferred (with PM scope IDs)

## What "good" explicitly does NOT mean for Phase 2

These belong to later phases — declaring Phase 2 done does not require them:

- ❌ Cross-tenant grant runtime — Phase 3 (the EcomLever → Project Silk grant is hardcoded/placeholder in Phase 2; runtime composition is Phase 3)
- ❌ MCP tool wrappers (`foundry_mcp_cip_query`, `foundry_mcp_cip_search`, `foundry_mcp_cip_files`) — Phase 4
- ❌ Chatbot capability — Phase 5
- ❌ Write-back (`cip_write`) — Phase 2.5
- ❌ Anomaly detection / freshness scoring at a product level — Phase 6
- ❌ Self-service analytics / white-label embedding — Phase 7
- ❌ Per-tenant DB extraction — Phase 8

## Open items / TBD before this WDGLL hardens

- Concrete row counts for each `cip_*` table at Phase 2 end (placeholders until the active 2026-05-15 sync runs complete)
- The full list of Wayward custom HubSpot properties that need ingestion (depends on PM scope `9c3d1393` deep-plan + admin conversation)
- The exact PS Twenty CRM grant filter shape (region=China? plus org-allowlist? entire Wayward slice?)
- The push cadence for each outbound target (Chatwoot real-time? Drive nightly? CRM hourly?) — depends on Push & Sync productization (PM scopes `f7a073dd` / `0147539c`)
- The alert thresholds and channels (Slack channel ID? PagerDuty? email-only?)

## Cross-references

- `vision/ROADMAP.md` — Phase 2 block + supersession history
- `vision/VISION.md` §3 (Wayward use case) + §10 (Roadmap summary)
- `vision/PHASE-1-PLAIN-SPEC.md` — the Phase 1 WDGLL precedent this doc mirrors
- `vision/PHASE-2.5-PLAN.md` — what comes immediately after Phase 2
- PM scope `d3311846` — connector resilience (gates the "no silent failure" criterion)
- PM scope `9c3d1393` — HubSpot full-property-set fetch (gates the "custom properties queryable" criterion)
- PM scope `218f67a4` — persister extension for D-159 backfill marker recognition (gates the "historical backfill recorded" criterion)
- `docs/SYNC-ORCHESTRATOR-GUIDE.md` — operator guide that will need a Wayward-specific appendix at Phase 2 end
- `docs/TENANT-ONBOARDING-CHECKLIST.md` — the Phase 1 deliverable validated for the first time during Phase 2

## Origin

Authored 2026-05-15 during the CIP vision-doc accuracy sweep. Tim asked Claude Code to validate that VISION + ROADMAP were still solid given the live Wayward Phase 2 work. The vision review found that ROADMAP's docs-per-phase pattern ("VISION/WDGLL/SPEC/PLAN") had Phase 1 and Phase 2.5 artifacts but no Phase 2 WDGLL — even though Phase 2 is the active phase. This stub closes that gap; it will be filled in with concrete numbers once the active HubSpot backfill + Zendesk current-state sync complete (estimated 2.5–3.5 hours from kickoff at 11:55 UTC).
