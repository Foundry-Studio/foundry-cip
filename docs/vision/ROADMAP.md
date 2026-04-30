---
doc_type: roadmap
project_id: client-intelligence-platform
pm_project_id: 596825db-61bc-4899-bc6c-e207489ca35d
status: active
owner: tim
created: 2026-04-13
last_updated: 2026-04-20
supersedes: >
  (1) Previous 8-phase release-shaped roadmap (pre-pillar-restructure) — superseded 2026-04-17 per D-117 + Shape D lock.
  (2) 2026-04-20 M0 Vision Revisit — inserted Phase 2.5 (Foundry Self-Tenant + Early Write-Back) between Phase 2 and Phase 3 per Tim's directive "sooner rather than later" on write-back readiness. Pillar 1 description extended with explicit connector-agnostic posture. Added Related-products pointer at `products/foundry-chatbot/`.
  (3) 2026-04-20 Plain-Jane Reshape — Phase 1 rewired to a blank-slate tenant-neutral product validated against a synthetic FixtureConnector, not Wayward. Wayward onboarding pulled into Phase 2 (now "Wayward Onboarding — Full Round-Trip") so Wayward is its own end-to-end proof instead of a Phase 1 ingredient. cip_09 (cross_tenant_grants) migration moved from Phase 1 to Phase 3 so schema + runtime ship together. Phase 2.5 trimmed to write-back only (push stays in Phase 2). All week-based appetites dropped — phases are session-bound and milestone-ordered, not calendar-bound. Phase 1 now explicitly ships 10 documentation artifacts alongside the plain-jane product.
---

# CIP Roadmap — Pillar-Aligned Phases

> **Frame:** CIP is structured as 8 durable **capability pillars** (D-117). Pillars never retire — they keep producing work as long as the product lives. **Phases** are release stages that light up pillars against real data. Each phase gets its own VISION/WDGLL/SPEC/PLAN doc before execution.
>
> **Authority:** This roadmap is the committed direction. Phase 0, Phase 1 (plain jane), and the Phase 2/2.5/3 shapes below are the current commit. Phase 4+ shapes remain provisional and will sharpen as the earlier phases ship.
>
> **Pacing note (2026-04-20):** Work is session-bound and milestone-ordered. Calendar appetites have been removed intentionally — Claude Code operates at AI speed, not human-sprint speed. Milestones are the unit of progress; time-to-ship is whatever it takes to land each milestone's acceptance criteria.

---

## The 8 Pillars

| # | Pillar | Status After Phase 1 (Plain Jane) |
|---|--------|-----------------------------------|
| 1 | Ingestion & Connectors | LIT (FixtureConnector only in Phase 1; framework inside Integration Mesh per D-118). **Connector-agnostic posture** — planned connectors queued (not elevated as pillars): Zendesk, HubSpot, QuickBooks Online, Stripe, Shopify, SEC EDGAR, news/RSS, WeChat/WhatsApp, Chatwoot (outbound), Gmail/Drive, manual upload. New connector = new `CIPConnector`/`CIPMapper` subclass + migration, not a new pillar. Zendesk + HubSpot ship in Phase 2 as part of Wayward onboarding. |
| 2 | Structured Store | LIT (cip_01–08 migrations, SCD history, 9 provenance cols, `cip_files`, `cip_connector_property_registry`) |
| 3 | Unstructured Store | LIT (Knowledge RAG + Graph GraphRAG consuming CIP content under `cip_fixture_*` source types) |
| 4 | Lens Engine | LIT (two lenses on same fixture dataset — P-21 canonical example) |
| 5 | Consumption Surfaces | PARTIAL (Metabase only in Phase 1; REST + MCP tools in Phase 4; Chatbot in Phase 5) |
| 6 | Push & Sync | DARK (lights up in Phase 2 alongside Wayward onboarding) |
| 7 | Intelligence & Alerts | DARK (lights up in Phase 6; advanced investigative work in Phase 7) |
| 8 | Access & Operations | MINIMUM (RLS + `SET LOCAL` for tenant isolation; cross-tenant grant schema + runtime together in Phase 3; full maturity in Phase 8) |

---

## Phase 0 — Data Model & Tenant Architecture (COMPLETE 2026-04-17)

Locked 10 decisions covering DB location, client table shape, tenant model, provenance columns, SCD Type 2, freshness decay, naming (`cip_` prefix), credential handling, JSONB overflow, and authority enum. All documented in `architecture/ARCHITECTURE.md`. Subsequent hardening session (2026-04-17) added D-117 through D-121 and P-21.

---

## Phase 1 — Plain-Jane CIP + Documentation Suite (LOCKED 2026-04-20 · NEXT)

**Owner:** Tim + Atlas (spec) → Claude Code (implementation). **Primary tenant:** none — fixture tenant only. **Authoritative plan:** `vision/PHASE-1-PLAN.md`. **Claude Code handoff:** `vision/PHASE-1-PLAIN-SPEC.md`.

### The bet

CIP ships as a **blank-slate, tenant-neutral, shrink-wrapped product** before any real venture data touches it. A **FixtureConnector** — deterministic synthetic data generator — stands in for a real source. Every assertion the product makes about connectors, lenses, access paths, and discoverability is proved against the fixture data first. This forces connector-agnostic interfaces and a documented onboarding surface; Wayward (Phase 2) and Rocky Ridge (Phase 3) then onboard as the first *external* proofs that the plain-jane product works.

### What ships — code

- **Structured Store (pillar 2):** Alembic migrations `cip_01` through `cip_08` creating the full CIP schema — `cip_clients`, `cip_views`, `cip_sync_runs`, `cip_files`, `cip_contacts`, `cip_companies`, `cip_deals`, `cip_tickets`, plus `_history` tables for SCD Type 2, plus all 9 provenance columns. **`cip_09` (cross_tenant_grants) is NOT in Phase 1** — moved to Phase 3 so schema + runtime ship together.
- **Ingestion & Connectors (pillar 1):** `CIPConnector` Protocol + `CIPMapper` Protocol + ingestion pipeline orchestrator live inside `platform/integration-mesh/` (D-118). First instance: **FixtureConnector** — deterministic synthetic source producing ~50 companies, ~200 contacts, ~300 deals, ~500 tickets, ~100 documents, ~50 notes, seeded from one fixed random seed for byte-identical repeatability. No external API. Zendesk and HubSpot connectors are out-of-scope for Phase 1 (they ship in Phase 2).
- **Property Registry (pillar 1 + 2 seam):** `cip_connector_property_registry` populated by FixtureConnector.`describe_schema()`. Every new connector declares its property shape here before ingestion.
- **Unstructured Store (pillar 3):** CIP ingestion calls `knowledge_ingester_service.ingest_text_content()` for fixture ticket bodies, note content, and document attachments. Graph extraction via post-vector hook (D-067 non-fatal). New `source_type` values on `knowledge_sources` (`cip_fixture_ticket`, `cip_fixture_note`, `cip_fixture_doc`). New node/edge types in `graph_templates`.
- **Lens Engine (pillar 4):** Two lenses on the same fixture dataset — **Lens-A (empty filter)** returning every fixture row and **Lens-B (`region=EMEA`)** returning the filtered slice. Row-count delta is the lens-validity proof.
- **Consumption Surfaces (pillar 5 — partial):** Metabase dashboard with lens switcher. REST API, chatbots, and agent MCP tools are NOT in Phase 1.
- **Access & Operations (pillar 8 — minimum):** RLS policies + `SET LOCAL app.current_tenant` scoping. `cip_sync_runs` audit table. Retention and full observability → Phase 6+.

### What ships — documentation (10 artifacts)

Phase 1 ships a documentation suite so the product is onboardable by someone who was not in the build sessions:

1. Tenant Onboarding Checklist
2. Connector Authoring Guide
3. Lens Authoring Guide
4. Migration Runbook (`cip_01`–`cip_08`)
5. RLS & `SET LOCAL` Operator Guide
6. Sync Orchestrator Guide
7. Four Access Paths Reference
8. Fixture Tenant Handbook
9. CIP CSS Classification Contract
10. Phase 1 → Phase 2 Handoff Doc

Each artifact is first-class — Phase 1 is not done until all ten exist, are reviewed, and are referenced from `products/client-intelligence-platform/README.md`.

### What does NOT ship in Phase 1

- Zendesk connector → Phase 2
- HubSpot connector → Phase 2
- Any real-tenant data (Wayward, Rocky Ridge, Foundry) → Phases 2, 3, 2.5 respectively
- Push & Sync pillar → Phase 2
- `cip_cross_tenant_grants` schema or runtime → Phase 3
- Second tenant / multi-tenant proof → Phase 3
- Foundry self-tenant + write-back → Phase 2.5
- REST API, chatbots, agent MCP tools → Phases 4, 5
- Intelligence & Alerts pillar → Phase 6
- Investigative agents + advanced write-back → Phase 7

### Consumer acceptance at Phase 1 end

An engineer opening the repo cold can: (a) run migrations, (b) register the fixture tenant, (c) seed fixture data via FixtureConnector, (d) switch between Lens-A and Lens-B in Metabase and see the row-count delta, (e) exercise all four agent access paths against fixture data, and (f) follow the Tenant Onboarding Checklist end-to-end for a second fake tenant — all from documentation alone, with no pointer to Wayward or any real venture.

### Phase 1 exit gate

Plain-jane product works against fixture data + all 10 documentation artifacts exist + `PHASE-1-PLAIN-SPEC.md` marked complete by the Claude Code reviewer subagent. Only then does Phase 2 kick off.

---

## Phase 2 — Wayward Onboarding (Full Round-Trip) (Provisional · reshaped 2026-04-20)

**Primary pillars:** Ingestion & Connectors (Zendesk + HubSpot ship here) + Push & Sync (first light). **Owner:** Tim + Atlas + Claude Code. **Depends on:** Phase 1 LIT.

Phase 2 is **Wayward's full round-trip** — inbound ingestion, lens validation against real data, and outbound push. Previously Wayward was distributed across Phases 1 (ingest) and 2 (push); the plain-jane reshape pulls the entire Wayward story into one phase so Wayward is a single coherent onboarding proof rather than an ingredient scattered across two phases.

**Inbound (ships in Phase 2):**

- **Zendesk connector** — streams tickets, users, organizations into `cip_tickets` / `cip_contacts` / `cip_companies`.
- **HubSpot connector** — streams contacts, companies, deals, notes. **Begins history capture from first sync** (HubSpot's 20-revision retention = permanent data loss for every day of delay). May be accompanied by an optional "HubSpot backup tape" mini-project if Tim decides the retention risk warrants the belt-and-suspenders approach.
- **Wayward as primary tenant** — primary record lives in EcomLever (EcomLever owns the consulting relationship). Project Silk's grant-in arrives in Phase 3 with the grants runtime; Phase 2 is EcomLever-only access.
- **Two lenses on Wayward data** — EcomLever Full View (unfiltered) and the precursor to PS China View (language / region / org filters). The PS grant wiring waits for Phase 3.
- **Metabase dashboard update** — points at real Wayward data instead of fixture data.

**Outbound (ships in Phase 2):**

- **Push to Chatwoot** — ticket routing per lens. Replaces the current one-off `zendesk_to_chatwoot.py` script.
- **Push to PS CRM (Twenty)** — HubSpot contacts/companies sync with lens-filtered views.
- **Push to client Google Drive** — scheduled report exports into per-client folders.
- **REST API (read side)** — first-light Consumption Surfaces expansion beyond Metabase; paves the runway for Phase 4 MCP tool wrappers.

**Depends on:** Phase 1 LIT. **Not in Phase 2:** cross-tenant grants runtime (Phase 3), MCP tools (Phase 4), chatbot (Phase 5), write-back (Phase 2.5).

**`CIPWAY` PM project** (`9553c778-357e-4290-bea5-2fd9160016ba`) tracks Phase 2 execution.

---

## Phase 2.5 — Foundry Self-Tenant + Write-Back (Provisional · trimmed 2026-04-20)

**Primary pillars:** Access & Operations + Ingestion & Connectors (producer side). **Owner:** Tim + Atlas. **Authoritative plan:** `vision/PHASE-2.5-PLAN.md`. **Depends on:** Phase 1 LIT + Phase 2 outbound shape understood. **Rationale (Tim, 2026-04-20):** "sooner rather than later. get it ready, and the foundry agents will use it when THEY are ready. we could also have claude co-work or other apps writing to it!"

Phase 2.5 pulls **write-back** capability forward from the original Phase 7 slot. The goal: CIP is **writable long before agents are consuming it at scale**, so by the time investigative-agent work (Phase 7) lands, the write path is battle-tested. Push & sync (outbound to Chatwoot, PS CRM, Drive) is **not** part of Phase 2.5 — that belongs to Phase 2's Wayward round-trip.

**Scope — what ships:**

- **Foundry self-tenant provisioning.** Foundry is added as a peer tenant in CIP (alongside EcomLever, Project Silk, Rocky Ridge, Personal). `cip_clients` under Foundry represent internal research topics, venture hypotheses, competitive intel threads. Provisioning is the first real test of the Tenant Onboarding Checklist shipped in Phase 1.
- **Write-back migrations.** `cip_10` (`cip_pending_writes`), `cip_11` (`cip_write_authorities`), `cip_12` (`cip_write_decisions`).
- **`cip_write` API (three surfaces, one service).** Exposed as:
  - A REST endpoint (`POST /cip/write`) for external apps.
  - An MCP tool (`foundry_mcp_cip_write`) for agent sessions including Claude Cowork.
  - Direct Python call from in-repo agent code.
  All three surfaces converge on a single `write_service.cip_write()` — there is one implementation, three entry points.
- **Authority model live.** Every write carries `authority ∈ {agent_discovered, ingested, validated}`. TSP thresholds: auto-promote ≥ 0.9, allow ≥ 0.5. Default for agent-originated writes: `agent_discovered`. Promotion to `validated` requires human review (surfaced in a minimal CLI promotion queue; optional Metabase view). Retraction via `disposition=retracted` without deletion.
- **First producer wired.** Default producer is **Option A — Foundry internal research agent** (writes synthesis from news/RSS scraping under the Foundry tenant). Cowork sessions with the Foundry MCP connector can also call `cip_write` with proper tenant scoping — deferred but unblocked.
- **Observability.** Every write logged with `source`, `source_session_id`, `authority`, `retract_url`. Per-tenant write rate metrics. Stale-write detection (flag `agent_discovered` rows older than N days with no review activity).
- **Cross-tenant writes forbidden.** A tenant can only write into its own tenant. Cross-tenant pattern synthesis (Foundry agents reading across tenants to produce Foundry-tenant insights) uses the Phase 3 grants runtime, but writes always land in the writer's own tenant.

**Scope — what does NOT ship in Phase 2.5:**

- Push & sync to external systems (Chatwoot, PS CRM, Drive) — that's **Phase 2**.
- Rich validated-promotion UX / review dashboards — Phase 7.
- Chatbot-initiated writes — Phase 7 (the Phase 5 chatbot is read-only).
- Cross-tenant write patterns — Phase 7 (stay read-only cross-tenant until the authority model is proven in-tenant).
- Temporal query API for "what did the system know at time T?" — Phase 7.

**Why insert at 2.5 rather than append at 3:** Phase 3 is already multi-tenant + grant-runtime-heavy. Bundling write-back into Phase 3 would double its appetite. Keeping Phase 2.5 as a focused phase means write-back ships on its own and Phase 3 stays tight on access-surfaces scope.

---

## Phase 3 — Rocky Ridge + Multi-Tenant + Cross-Tenant Grants Runtime (Provisional)

**Primary pillar:** Access & Operations (dual-tenant proof + grant runtime). **Owner:** Tim + Atlas + Claude Code. **Depends on:** Phase 1 + Phase 2 + Phase 2.5 LIT.

**Scope trimmed 2026-04-20 hardening sweep:** Agent MCP tools and chatbot were originally bundled here. Pulled into dedicated Phase 4 (MCP + REST) and Phase 5 (Chatbot) so Phase 3 stays focused on the multi-tenant + grant-runtime work.

Rocky Ridge onboards as tenant #2 — validates tenant isolation under real conditions against a tenant type very different from Wayward's CS workload (PDF-heavy, longer documents, fewer structured records). Ships:

- **`cip_09` (cross_tenant_grants) migration** — held back from Phase 1 so schema + runtime ship together. Creates `cip_cross_tenant_grants` with source/target tenant, client scope, filter JSONB, authority floor, grant window.
- **Cross-tenant grant runtime goes live.** Grant-lookup at access-layer, filter composition (grant filter + lens filter), authority_floor enforcement, audit logging on every cross-tenant read, grant-window activation/expiry checks, the minimal grant-admin surface Tim uses to create/revoke grants (likely a simple CLI or DB-seeded rows at first; richer admin UX in Phase 7).
- **Rocky Ridge as tenant #2** — PDF-Q&A-native use case. The Tenant Onboarding Checklist (Phase 1 deliverable) is validated a second time.
- **Project Silk grant-in to Wayward** — PS Twenty CRM consumer uses the live grant runtime instead of raw SQL joins, closing out the Wayward cross-tenant story that Phase 2 deferred.
- **Cross-tenant lens validation** — do filters work cleanly when two tenants share storage?
- **Observability hardening on the access layer** — per-tenant query counts, per-grant read counts, slow-query alerts distinguished by tenant vs grant-scoped.

**`CIPRR` PM project** (`bd706b3c-b63b-4c45-8424-01b262252d6d`) tracks Phase 3 execution.

---

## Phase 4 — Agent Access Surfaces (MCP + REST) (Provisional · NEW 2026-04-20 hardening)

**Primary pillar:** Consumption Surfaces (agents-as-first-class-consumer light). **Scope sharpened 2026-04-20:** carved out of the old Phase 3 so agent access gets dedicated shape. Chatbot is **explicitly excluded** — that's Phase 5.

Ships the tool surfaces that let Foundry agents consume CIP programmatically without hand-rolled SQL.

- **`foundry_mcp_cip_query`** — tenant-scoped SQL pass-through wrapping `foundry_mcp_db_query` with RLS + `SET LOCAL` enforced by the access layer. Thin wrapper; the registries (D-121) do the heavy lifting of telling agents what to query.
- **`foundry_mcp_cip_search`** — retrieval over Derived Knowledge (Pinecone + FalkorDB). Composes Knowledge Subsystem BM25+vector retrieval with optional GraphRAG boost, returns ranked chunks with `cip_*` source references + R2 paths for provenance.
- **`foundry_mcp_cip_files`** — signed-R2-URL resolver starting from `cip_files.cip_file_id`. Agents that need to cite or open an original (PDF, transcript JSON) go through this tool.
- **REST API** — parallel surface at `/cip/query`, `/cip/search`, `/cip/files` for external apps (Cowork sessions that don't have MCP, Claude in Chrome, future third-party consumers). Same auth + tenant scoping as the MCP path.
- **Discoverability endpoints** — `/cip/registries/connectors`, `/cip/registries/sources`, `/cip/registries/graph-templates`, `/cip/registries/files`. Agents enumerate what's queryable before issuing queries.

**Depends on:** Phase 1 + Phase 2 + Phase 2.5 + Phase 3 LIT (grants must work before tools expose cross-tenant data).

---

## Phase 5 — Chatbot Capability (Internal / Staff-Facing) (Provisional · NEW 2026-04-20 hardening)

**Primary pillar:** Consumption Surfaces (conversational light). **Intended consumers** (per VISION §7h): Tim, Foundry agents, Rocky Ridge staff, Project Silk staff, EcomLever staff.

The chatbot is its own phase because chatbot-specific constraints (grounding, refusal patterns, citation density, lens+grant awareness in a conversational surface) are heavier than a generic query tool — heavy enough to warrant a Vision → Architecture → Implementation split. Client-facing chatbots are a **separate product** (`products/foundry-chatbot/`), blocked until this phase ships.

### 5A — Chatbot Vision

Deliverable: `vision/CHATBOT-VISION.md` documenting consumer model, question patterns, refusal patterns, citation density floor, surface shape (embed? Slack bot? both?), branding considerations, lens-aware conversation state, grant-awareness.

### 5B — Chatbot Architecture

Deliverable: `architecture/CHATBOT-ARCHITECTURE.md` documenting: retrieval pipeline (GraphRAG-first + BM25 + vector fallback), routing via LLM Roster (D-018/D-031/D-077 — no direct SDK calls), grounding validation (refuse if < N citations), citation schema (`cip_*` row IDs + R2 paths in the payload), conversation state persistence, lens + grant composition at retrieval time, the shared-retrieval-service contract Foundry Chatbot will later call.

### 5C — Chatbot Implementation

First tenant Rocky Ridge (PDF-Q&A-native use case — original CIP braindump named this specifically). Second tenant Wayward, tested through both the EcomLever full-view lens and the Project Silk grant-in. Validates the multi-tenant, grant-aware, lens-aware chatbot behavior under real traffic before client-facing work starts in Foundry Chatbot.

**Constraints enforced across 5A/5B/5C:**
- Grounded only — no ungrounded generation
- Lens-aware + grant-aware
- **Read-only** — chatbot cannot invoke `cip_write` (write-back is Phase 2.5 API-level and Phase 7 advanced UX; chatbot-initiated writes never land in this phase)
- Citations mandatory — every factual claim carries a `cip_*` row ID or chunk-level R2 path

**Depends on:** Phase 4 LIT.

---

## Phase 6 — Intelligence & Alerts (Provisional · renumbered from old Phase 4)

**Primary pillar:** Intelligence & Alerts (first light).

Proactive signals surface. Ships:
- Anomaly detection rules — ticket volume spikes, overdue payment proofs, freshness decay crossings.
- Alert channel integration — Slack (primary), email fallback.
- Freshness scoring visible in Metabase dashboards.
- Scheduled analytical reports.

**Depends on:** Phase 1 + Phase 2 data flowing.

---

## Phase 7 — Investigative Agents + Advanced Write-Back (Provisional · renumbered from old Phase 5, renamed 2026-04-20 M0)

**Primary pillar:** Intelligence & Alerts (full light). **Scope update (2026-04-20 M0):** write-back infrastructure shipped in Phase 2.5 — this phase focuses on the **advanced** layer (rich validated-promotion UX, cross-tenant pattern synthesis, temporal API, self-service analytics).

CIP becomes fully bidirectional with rich review. Ships:
- **Investigative agents** — long-running agents that scan CIP data looking for patterns, write synthesis back with `authority=agent_discovered`, surface findings in a review queue.
- **Rich validated-promotion UX** — Tim (and delegated reviewers per tenant) review `agent_discovered` rows with inline context, approve or retract, promote to `validated`. Phase 2.5 had a minimal CLI queue; Phase 7 makes the review flow first-class.
- **Cross-tenant anonymized pattern detection** — aggregation across tenants that never exposes source rows (e.g., "CS response-time trends across all tenants," "billing-complaint distribution by venture vertical"). Uses a Foundry-self-tenant "patterns" table with `authority=agent_discovered` until a human validates each aggregate.
- **Temporal point-in-time query API** — beyond SCD history, a snapshot API ("show me what CIP knew about this company on 2026-03-15"). Critical for stock/investment use case where decisions need auditable knowledge-at-time.
- **Self-service embedded analytics** — Metabase embedding with white-label CSS per tenant, row-level security enforced via the same tenant/grant layer.
- **Chatbot-initiated writes** — per the Phase 5 constraint this is the first phase it's allowed, and only into the caller's own tenant.

**Depends on:** Phases 1–6 stable.

---

## Phase 8 — Scale & Extract (Provisional · renumbered from old Phase 6)

**Primary pillars:** Structured Store (dedicated instance) + Access & Operations (full maturity).

Per Phase 0 decision #1: "Extract to dedicated DB at Stage 3." Ships:
- CIP tables extracted from shared Foundry PostgreSQL → dedicated Railway PostgreSQL service.
- Retention policies active (per-tenant configurable, default soft-delete after 90 days, hard-delete on offboarding).
- Observability upgrade — per-connector sync health dashboards, slow-query alerts, disk monitoring.
- Performance tuning — indices on hot query paths, materialized views for dashboard acceleration.
- Backup & restore tested quarterly.

**Depends on:** load that justifies extraction (when shared DB contention becomes measurable).

---

## Phase Order

```
Phase 0:   Data Model & Tenant Architecture              [COMPLETE 2026-04-17]
    ↓
Phase 1:   Plain-Jane CIP + Doc Suite                    [NEXT · LOCKED 2026-04-20]
    ↓
Phase 2:   Wayward Onboarding — Full Round-Trip          [inbound + push]
    ↓
Phase 2.5: Foundry Self-Tenant + Write-Back              [write-back only]
    ↓
Phase 3:   Rocky Ridge + Multi-Tenant + Grants Runtime   [cip_09 + runtime]
    ↓
Phase 4:   Agent Access Surfaces (MCP + REST)
    ↓
Phase 5:   Chatbot Capability (Internal)                 [5A Vision / 5B Arch / 5C Impl]
    ↓
Phase 6:   Intelligence & Alerts
    ↓
Phase 7:   Investigative Agents + Advanced Write-Back
    ↓
Phase 8:   Scale & Extract                               [when load justifies]
```

Phases 0 and 1 are LOCKED. Phase 2, Phase 2.5, and Phase 3 shapes are the current commit (will sharpen at kickoff). Phase 4+ shapes remain provisional. No week-based appetites are committed — phases are session-bound and milestone-ordered. **Phase 5 is big enough that it gets its own internal Vision → Architecture → Implementation sequence** (stages 5A / 5B / 5C).

---

## Cross-References

- `README.md` — project overview, 8 pillars table, locked architecture decisions
- `vision/VISION.md` — product vision (the source of truth)
- `vision/PHASE-1-PLAN.md` — Phase 1 (plain jane) VISION/WDGLL/SPEC/PLAN
- `vision/PHASE-1-PLAIN-SPEC.md` — Claude Code handoff doc for Phase 1
- `vision/PHASE-2.5-PLAN.md` — Phase 2.5 (write-back) VISION/WDGLL/SPEC/PLAN
- `architecture/ARCHITECTURE.md` — Phase 0 DDL, §13–19 hardening layer
- `docs/DECISION-LOG.md` — D-117 through D-123 (CIP-specific locks)
- `docs/architecture/principles/DESIGN-PRINCIPLES.md` — P-21 (Multi-Lens by Default)
- `docs/subsystems/integration/CONTRACT.md` — Integration Mesh, connector framework
- `docs/subsystems/knowledge/CONTRACT.md` — Knowledge Subsystem (consumer: CIP)
- `docs/subsystems/graph/CONTRACT.md` — Graph Subsystem (consumer: CIP)

## Related Products, Tracked Separately

- **`products/foundry-chatbot/`** — Client-facing chatbot product (stubbed; blocked by CIP Phase 5). Reuses CIP's retrieval stack (GraphRAG + BM25 + vector), citation schema, Roster LLM routing (D-018/D-031/D-077), and authority levels. Adds on top: per-recipient permission scoping (sharper than CIP lens scoping), per-tenant branding (white-label), end-customer identity model, tighter guardrails, per-tenant analytics on chatbot usage. Separate PM project: `FCHAT — Foundry Chatbot` (`project_id=69a72685-9518-4ae7-b936-f9e17d449725`). See `products/foundry-chatbot/README.md`.

## Supersedes

Previous 8-phase roadmap (2026-04-13 draft) was release-shaped rather than pillar-aligned. Superseded 2026-04-17 after the pillar restructure (D-117). Specific mappings of old→new phases:

| Old | New |
|-----|-----|
| Phase 0 (Data Model & Tenant Arch) | Phase 0 — unchanged, COMPLETE |
| Phase 1 (Connector Framework) | Absorbed into Phase 1 (builds framework inside Integration Mesh per D-118) |
| Phase 2 (Wayward Pipeline) | Originally split (ingest→Phase 1, push→Phase 2); now reconsolidated into Phase 2 per the 2026-04-20 plain-jane reshape |
| Phase 3 (Knowledge Access — MCP) | Moved to Phase 3 (multi-tenant + agent access) |
| Phase 4 (Dashboards & Reports) | Metabase → Phase 1; scheduled reports → Phase 2 |
| Phase 5 (Web Chatbot) | Moved to Phase 3 |
| Phase 6 (Anomaly Detection) | Moved to Phase 4 |
| Phase 7 (Intelligence Layer) | Moved to Phase 5 |
| (new) | Phase 6 (Scale & Extract) |

### Incremental changes in the 2026-04-20 evening M0 Vision Revisit

| Change | From | To |
|--------|------|-----|
| Write-back timing | Phase 5 (write-back bundled with investigative agents) | **Phase 2.5** (pulled forward as a standalone short phase; Phase 7 retains investigative-agent scope, advanced UX stays at Phase 7) |
| Phase 3 depends-on | Phase 1 + Phase 2 | Phase 1 + Phase 2 + **Phase 2.5** |
| Cross-tenant grant runtime | Implicit (buried in Phase 3 multi-tenant work) | **Explicitly named in Phase 3**: `cip_09` schema + runtime ship together |
| Pillar 1 description | "Zendesk + HubSpot, connector framework" | Same + explicit **connector-agnostic posture** statement |
| Foundry Chatbot | (not present) | **New product**, stubbed at `products/foundry-chatbot/`, blocked by CIP Phase 5. Separate PM project. |
| Tenant model | Nested venture → client (from VISION.md §4 original sketch) | Flat **peer tenants** (EcomLever, Project Silk, Rocky Ridge, Personal, Foundry-self) with first-class `cip_cross_tenant_grants` |

### Incremental changes in the 2026-04-20 daytime hardening sweep

| Change | From | To |
|--------|------|-----|
| Phase 3 scope | Multi-tenant + Agent Access (MCP tools + chatbot bundled) | **Multi-tenant proof + grant runtime only.** MCP tools/REST → Phase 4. Chatbot → Phase 5. |
| Phase 4 | Intelligence & Alerts | **NEW: Agent Access Surfaces (MCP + REST)** — `foundry_mcp_cip_query`, `foundry_mcp_cip_search`, `foundry_mcp_cip_files`, REST parallel, discoverability endpoints. Chatbot excluded. Old Phase 4 → Phase 6. |
| Phase 5 | Investigative Agents + Write-Back | **NEW: Chatbot Capability (Internal / Staff-Facing)** with three sub-stages 5A / 5B / 5C. First tenant Rocky Ridge, then Wayward. Grounded, lens+grant-aware, read-only. Old Phase 5 → Phase 7. |
| Phase 6 | Scale & Extract | **Intelligence & Alerts** (renumbered from old Phase 4). |
| Phase 7 | (no Phase 7 previously) | **Investigative Agents + Advanced Write-Back** (renumbered + renamed — was old Phase 5; "advanced" reflects write-back infra already ships in Phase 2.5). |
| Phase 8 | (no Phase 8 previously) | **Scale & Extract** (renumbered from old Phase 6). |

### Incremental changes in the 2026-04-20 evening Plain-Jane Reshape

| Change | From | To |
|--------|------|-----|
| Phase 1 primary tenant | Wayward | **None — fixture tenant only.** FixtureConnector (deterministic synthetic data) stands in for all real sources. |
| Phase 1 connectors | Zendesk + HubSpot | **FixtureConnector only.** Zendesk + HubSpot move to Phase 2. |
| Phase 1 deliverables | Code only | **Code + 10 documentation artifacts** (Tenant Onboarding Checklist, Connector Authoring Guide, Lens Authoring Guide, Migration Runbook, RLS & SET LOCAL Operator Guide, Sync Orchestrator Guide, Four Access Paths Reference, Fixture Tenant Handbook, CIP CSS Classification Contract, Phase 1 → Phase 2 Handoff Doc). |
| Phase 1 exit gate | Metabase against Wayward | **Plain-jane product works against fixture data + all 10 doc artifacts exist + `PHASE-1-PLAIN-SPEC.md` marked complete by Claude Code reviewer subagent.** |
| `cip_09` (cross_tenant_grants) | Phase 1 (schema-only) | **Phase 3** (schema + runtime ship together). |
| Phase 2 scope | Push & Sync only | **Wayward Onboarding — Full Round-Trip.** Inbound (Zendesk + HubSpot) + outbound (Chatwoot, PS CRM, Drive) + first-light REST. Wayward is a single coherent onboarding proof instead of an ingredient across Phases 1 and 2. |
| Phase 2.5 scope | Foundry Self-Tenant + Write-Back (broad) | **Write-back only** (push stays in Phase 2). Three cip_write surfaces (REST / MCP / Python) converge on one `write_service.cip_write()`. Migrations `cip_10` / `cip_11` / `cip_12`. TSP thresholds auto-promote ≥ 0.9, allow ≥ 0.5. Default first producer is the Foundry internal research agent. |
| Week-based appetites | "~8 weeks" / "~6 weeks" / etc. on every phase | **Dropped.** Phases are session-bound and milestone-ordered. Claude Code operates at AI speed, not human-sprint speed. |
