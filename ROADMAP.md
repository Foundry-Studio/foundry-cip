---
doc_type: roadmap
elaborates_slot: lifecycle
declared_thing: foundry-cip
declared_thing_kind: product-internal
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
audience: [strategist, stakeholder, leadership, agent]
diataxis_type: explanation
---

# Roadmap — Foundry Client Intelligence Platform (CIP)

> **JOS-canonical entry point for CIP's roadmap.**
> Per JOS-D0054 + JOS-S29, this file elaborates the Lifecycle slot (Roadmap component) for the foundry-cip product root.
>
> **The authoritative roadmap is [`docs/vision/ROADMAP.md`](docs/vision/ROADMAP.md)** — 457-line pillar-aligned phase sequence with full per-phase plans, exit criteria, and rationale. This root file is a JOS-shaped index pointing at it.

## TL;DR

Phase 0 (Data Model) COMPLETE. Phase 1 (Plain-Jane + Doc Suite) LOCKED 2026-05-12 with M0-M8 all green. **Active phase: Phase 2 — Wayward Onboarding (Full Round-Trip).** Phases 3-8 mapped at varying commitment levels. Horizon: 2027-05.

## Active phase

### Phase 2 — Wayward Onboarding (Full Round-Trip)

**Horizon:** 2026-Q3

**What "done" looks like:**
- Zendesk + HubSpot connectors run live against Wayward; HubSpot historical-property backfill captures up to 20 revisions per property (D-159; clock started Phase 2 kickoff)
- Wayward operates as primary tenant; ≥2 lenses live; cross-tenant probes prove RLS isolation
- Push surfaces light up first time: Chatwoot push (support tickets), PS Twenty CRM push (lead nurture), client Google Drive push (artifacts)
- First-light REST API at `/cip/query`, `/cip/search` + lens-respecting auth

**PM project / scope:** Foundry-Agent-System JOS Compliance project; "CIP MVP — Agent Readiness" scope tracks the JOS-side; CIP-side work tracked under the CIP project (`596825db-61bc-4899-bc6c-e207489ca35d`) Phase 2 scope.

## Next phase (planned, not started)

### Phase 2.5 — Foundry Self-Tenant + Write-Back

**Horizon:** 2026-Q3 → 2026-Q4

**What "done" looks like:**
- Foundry provisioned as a peer tenant
- `cip_12` / `cip_13` / `cip_14` migrations land (Phase 0's planned `cip_10`/`cip_11`/`cip_12` numbers shifted because `cip_09`/`cip_10`/`cip_11` were occupied by the M5/M8 + sync-mode-backfill migrations)
- `cip_write()` API on three surfaces (REST / MCP / Python) converging on one `write_service.cip_write()`
- Authority model live (`agent_discovered` / `ingested` / `validated` with TSP thresholds)
- Minimal CLI promotion queue
- First producer: Foundry internal research agent

## Future phases (rough)

### Phase 3 — Rocky Ridge + Multi-Tenant + Grants Runtime
**Horizon:** 2026-Q4. `cip_09_cross_tenant_grants` schema + runtime ship together. Rocky Ridge onboards as tenant #2. Cross-tenant lens validation lands. Access-layer observability matures.

### Phase 4 — Agent Access Surfaces (MCP + REST)
**Horizon:** 2027-Q1. `foundry_mcp_cip_query` / `_search` / `_files` + REST parallels at `/cip/*`. Discoverability endpoints `/cip/registries/*`. **Chatbot explicitly excluded** (Phase 5).

### Phase 5 — Chatbot Capability (Internal)
**Horizon:** 2027-Q1 → 2027-Q2. 5A vision doc, 5B architecture doc, 5C implementation against Rocky Ridge first then Wayward. Grounded, lens-aware, grant-aware, read-only, citations mandatory.

### Phase 6 — Intelligence & Alerts
**Horizon:** 2027-Q2. Anomaly detection (ticket spikes, overdue payments, freshness crossings); Slack alert channel; freshness signals in Metabase; scheduled analytical reports.

### Phase 7 — Investigative Agents + Advanced Write-Back
**Horizon:** 2027-Q3. Long-running investigative agents; rich validated-promotion UX; cross-tenant anonymized pattern detection; temporal point-in-time query API; self-service embedded analytics (white-label); first phase chatbot-initiated writes are allowed.

### Phase 8 — Scale & Extract
**Horizon:** 2027-Q4 → 2028-Q1. Extract `cip_*` tables from shared Foundry PostgreSQL → dedicated Railway PostgreSQL (per Phase 0 decision #1). Retention policies active. Observability upgrade. Performance tuning. Backup & restore tested quarterly.

## Recently completed phases (history)

### Phase 1 — Plain-Jane + Doc Suite — COMPLETE 2026-05-12

**Outcome:** Framework shipped. M0-M8 all green. Plain-jane product works against FixtureConnector with byte-identical reproducibility. All 10 doc artifacts live. M8 fixture-tenant gate PASSED — Railway Metabase deployment confirmed `lens_all_companies` (50 rows) + `lens_eu_west_companies` (13 rows) + cross-tenant probe fails as designed.

**Lessons:**
- Library-shape FND-S13 worked (ranges in pyproject + lockfile in requirements-dev.txt)
- Drafts-against-memory pattern accelerated doc authoring
- Connector bug-bash 2026-05-14 caught HubSpot/Zendesk schema-drift class issues before Wayward run

### Phase 0 — Data Model & Tenant Architecture — COMPLETE 2026-04-17

**Outcome:** All 10 Phase 0 decisions LOCKED (DB location, client table, tenant model, provenance, versioning, freshness, naming, credentials, JSONB overflow, authority enum). Full detail in [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md).

## Linked to PM

Tactical work for CIP lives in the PM substrate. Key entry points:

- **CIP project:** PM project ID `596825db-61bc-4899-bc6c-e207489ca35d` (CIP — Phase 2 active)
- **JOS-compliance scope:** "CIP MVP — Agent Readiness" inside FAS-JOS project (`6ee61291-7041-41a4-9700-9cf280ed3700`; scope `b4fb4ea3-0b79-4e1c-98b1-db6b255547df`)
- **For "what's blocked this week"** — query PM via `foundry_mcp_pm_my_tasks` / `foundry_mcp_pm_project_status`

This doc does NOT carry weekly status.

## Health snapshot

- **Active phase health:** on-track. Phase 1 close-out clean; Phase 2 starts with HubSpot + Zendesk connectors already shipped + tested + bug-bashed.
- **At-risk indicator:** none currently. Phase 2 kickoff is the next dependency on Tim's "go for Wayward live ingestion."
- **Stalled phase indicator:** none.

## Last reviewed

2026-05-21.

---

_This root-level file is a JOS-shaped index. Authoritative roadmap: [`docs/vision/ROADMAP.md`](docs/vision/ROADMAP.md)._
