---
doc_type: roadmap
project_id: client-intelligence-platform
pm_project_id: 596825db-61bc-4899-bc6c-e207489ca35d
status: active
owner: tim
created: 2026-04-13
last_updated: 2026-04-17
supersedes: Previous 8-phase release-shaped roadmap (pre-pillar-restructure). Superseded 2026-04-17 per D-117 + Shape D lock.
---

# CIP Roadmap — Pillar-Aligned Phases

> **Frame:** CIP is structured as 8 durable **capability pillars** (D-117). Pillars never retire — they keep producing work as long as the product lives. **Phases** are release stages that light up pillars against real data. Each phase gets its own VISION/WDGLL/SPEC/PLAN doc before execution.
>
> **Authority:** This roadmap is the committed direction. Phase 0 and Phase 1 scopes are LOCKED. Phase 2+ shapes are provisional — they'll sharpen as Phase 1 ships.

---

## The 8 Pillars

| # | Pillar | Status After Phase 1 (Shape D) |
|---|--------|-------------------------------|
| 1 | Ingestion & Connectors | LIT (Zendesk + HubSpot, connector framework inside Integration Mesh) |
| 2 | Structured Store | LIT (cip_01–08 migrations, SCD history, 9 provenance cols, `cip_files`) |
| 3 | Unstructured Store | LIT (Knowledge RAG + Graph GraphRAG consuming CIP content) |
| 4 | Lens Engine | LIT (two lenses on same dataset — P-21 canonical example) |
| 5 | Consumption Surfaces | PARTIAL (Metabase only; REST/chatbot/MCP tools in Phase 2–3) |
| 6 | Push & Sync | DARK (lights up in Phase 2) |
| 7 | Intelligence & Alerts | DARK (lights up in Phase 4–5) |
| 8 | Access & Operations | MINIMUM (RLS + SET LOCAL; dual-tenant in Phase 3; full maturity in Phase 6) |

---

## Phase 0 — Data Model & Tenant Architecture (COMPLETE 2026-04-17)

Locked 10 decisions covering DB location, client table shape, tenant model, provenance columns, SCD Type 2, freshness decay, naming (`cip_` prefix), credential handling, JSONB overflow, and authority enum. All documented in `architecture/ARCHITECTURE.md`. Subsequent hardening session (2026-04-17) added D-117 through D-121 and P-21.

---

## Phase 1 — Shape D: Inbound + Lens Validation + Minimum Consumption (LOCKED 2026-04-17 · NEXT)

**Appetite:** ~8 weeks. **Owner:** Tim + Atlas. **Primary tenant:** Wayward.

### What ships

- **Structured Store (pillar 2):** Alembic migrations cip_01 through cip_08 create the full CIP schema — `cip_clients`, `cip_views`, `cip_sync_runs`, `cip_files`, `cip_contacts`, `cip_companies`, `cip_deals`, `cip_tickets`, plus `_history` tables for SCD Type 2, plus all 9 provenance columns.
- **Ingestion & Connectors (pillar 1):** `CIPConnector` Protocol + `CIPMapper` Protocol + ingestion pipeline orchestrator live inside `platform/integration-mesh/` (D-118). First instances:
  - **Zendesk connector** — streams tickets, users, organizations
  - **HubSpot connector** — streams contacts, companies, deals, notes. Begins history capture from first sync (urgent: HubSpot's 20-revision retention = permanent data loss for every day of delay)
- **Unstructured Store (pillar 3):** CIP ingestion calls `knowledge_ingester_service.ingest_text_content()` for ticket bodies, note content, document attachments. Graph extraction via post-vector hook (D-067 non-fatal). New `source_type` values on `knowledge_sources`; new node/edge types in `graph_templates`.
- **Lens Engine (pillar 4):** Two lenses on same Wayward data:
  - **EcomLever Full View** — unfiltered consumer lens (Ali, EcomLever ops)
  - **PS China View** — filtered for Project Silk's China-facing workflow (language/region/org filters)
- **Consumption Surfaces (pillar 5 — partial):** Metabase dashboard with lens switcher. REST API, chatbots, agent MCP tools OUT of Phase 1.
- **Access & Operations (pillar 8 — minimum):** RLS policies + `SET LOCAL` tenant scoping. `cip_sync_runs` audit table. Retention policies, full observability → Phase 6.

### What does NOT ship

- Push & Sync pillar (Chatwoot, PS CRM, client Drive) — Phase 2
- Second tenant / multi-tenant proof — Phase 3
- Intelligence & Alerts pillar — Phase 4–5
- REST API, chatbots, agent MCP tools — Phase 2–3

### Decisions still open for Phase 1 kickoff

- Which specific Wayward client is the first `cip_client` row? (Tim decides at kickoff.)
- Exactly which HubSpot properties are captured as structured columns vs. JSONB overflow?
- Concrete filter_config JSONB schema for PS China View (language fields? org IDs? request tags?)

### Deliverable at Phase 1 end

Ali can open Metabase, switch between EcomLever Full View and PS China View, and see live Wayward data from Zendesk and HubSpot — with history captured from day 1 and queryable across time.

---

## Phase 2 — Push & Sync Goes Live (Provisional)

**Primary pillar:** Push & Sync (first light). **Appetite:** TBD at Phase 1 end, probably ~6 weeks.

Outbound delivery becomes real. Ships:
- Push to Chatwoot — ticket routing per lens (PS China View → PS inbox; full view → EcomLever inbox). Replaces the current one-off `zendesk_to_chatwoot.py` script.
- Push to PS CRM — HubSpot contacts/companies sync to Twenty (PS CRM) with lens-filtered views.
- Push to client Google Drive — scheduled report exports into per-client folders.
- REST API for consumption (adds to Consumption Surfaces pillar).

Depends on: Phase 1 LIT.

---

## Phase 3 — Multi-Tenant + Agent Access (Provisional)

**Primary pillars:** Access & Operations (dual-tenant proof) + Consumption Surfaces (chatbots, MCP tools). **Appetite:** ~6 weeks.

Second tenant onboards (Rocky Ridge is likely — has staged RAG data already). Ships:
- Rocky Ridge (or Bob) as tenant #2 — validates tenant isolation under real conditions.
- `foundry_mcp_cip_query` + `foundry_mcp_cip_search` MCP tools — agents can query CIP from Cowork / Claude Code.
- Web chatbot for Rocky Ridge staff — deployed to Railway with tenant-scoped auth.
- Cross-tenant lens validation (do filters work cleanly when two tenants share storage?).

Depends on: Phase 1 + Phase 2 LIT.

---

## Phase 4 — Intelligence & Alerts (Provisional)

**Primary pillar:** Intelligence & Alerts (first light). **Appetite:** ~6 weeks.

Proactive signals surface. Ships:
- Anomaly detection rules — ticket volume spikes, overdue payment proofs, freshness decay crossings.
- Alert channel integration — Slack (primary), email fallback.
- Freshness scoring visible in Metabase dashboards.
- Scheduled analytical reports.

Depends on: Phase 1 + Phase 2 data flowing.

---

## Phase 5 — Investigative Agents + Write-Back (Provisional)

**Primary pillar:** Intelligence & Alerts (full light). **Appetite:** ~6–8 weeks.

CIP becomes bidirectional. Ships:
- Agent write-back — agents commit discoveries to CIP with `authority=agent_discovered`, escalate to `validated` via review workflow.
- Cross-tenant pattern detection — anonymized aggregation (e.g., "customer support response time trends across all client CRMs").
- Temporal point-in-time queries beyond SCD (snapshot API).
- Self-service embedded analytics (Metabase embedding with client white-label).

Depends on: Phases 1–4 stable.

---

## Phase 6 — Scale & Extract (Provisional)

**Primary pillars:** Structured Store (dedicated instance) + Access & Operations (full maturity). **Appetite:** ~4–6 weeks.

Per Phase 0 decision #1: "Extract to dedicated DB at Stage 3." Ships:
- CIP tables extracted from shared Foundry PostgreSQL → dedicated Railway PostgreSQL service.
- Retention policies active (per-tenant configurable, default soft-delete after 90 days, hard-delete on offboarding).
- Observability upgrade — per-connector sync health dashboards, slow-query alerts, disk monitoring.
- Performance tuning — indices on hot query paths, materialized views for dashboard acceleration.
- Backup & restore tested quarterly.

Depends on: load that justifies extraction (when shared DB contention becomes measurable).

---

## Phase Order

```
Phase 0: Data Model & Tenant Architecture        [COMPLETE 2026-04-17]
    ↓
Phase 1: Shape D — Inbound + Lens + Metabase    [NEXT — ~8 weeks]
    ↓
Phase 2: Push & Sync Goes Live                   [~6 weeks]
    ↓
Phase 3: Multi-Tenant + Agent Access             [~6 weeks]
    ↓
Phase 4: Intelligence & Alerts                   [~6 weeks]
    ↓
Phase 5: Investigative Agents + Write-Back       [~6–8 weeks]
    ↓
Phase 6: Scale & Extract                         [when load justifies]
```

Phases 0 and 1 are LOCKED. Phase 2+ shapes are provisional — they'll sharpen as Phase 1 ships and as real usage informs priorities.

---

## Cross-References

- `README.md` — project overview, 8 pillars table, locked architecture decisions
- `architecture/ARCHITECTURE.md` — Phase 0 DDL, §13-19 hardening layer
- `docs/DECISION-LOG.md` — D-117 through D-121 (CIP-specific locks)
- `docs/architecture/principles/DESIGN-PRINCIPLES.md` — P-21 (Multi-Lens by Default)
- `docs/subsystems/integration/CONTRACT.md` — Integration Mesh, connector framework
- `docs/subsystems/knowledge/CONTRACT.md` — Knowledge Subsystem (consumer: CIP)
- `docs/subsystems/graph/CONTRACT.md` — Graph Subsystem (consumer: CIP)

## Supersedes

Previous 8-phase roadmap (2026-04-13 draft) was release-shaped rather than pillar-aligned. Superseded by this version 2026-04-17 after the pillar restructure (D-117). Specific mappings of old→new phases:

| Old | New |
|-----|-----|
| Phase 0 (Data Model & Tenant Arch) | Phase 0 — unchanged, COMPLETE |
| Phase 1 (Connector Framework) | Absorbed into Phase 1 (builds framework inside Integration Mesh per D-118) |
| Phase 2 (Wayward Pipeline) | Split: ingest side → Phase 1; push side → Phase 2 |
| Phase 3 (Knowledge Access — MCP) | Moved to Phase 3 (multi-tenant + agent access) |
| Phase 4 (Dashboards & Reports) | Metabase → Phase 1; scheduled reports → Phase 2 |
| Phase 5 (Web Chatbot) | Moved to Phase 3 |
| Phase 6 (Anomaly Detection) | Moved to Phase 4 |
| Phase 7 (Intelligence Layer) | Moved to Phase 5 |
| (new) | Phase 6 (Scale & Extract) |
