---
id: CIP-FW-001
uuid: c9076719-808e-45df-8260-c2ed499a9e80
title: Foundry Client Intelligence Platform — Product Vision
type: framework
owner: tim
solve_for: Top-level CIP product vision — what it is, why it exists, who consumes
  it, two-layer architecture, ten roadmap phases.
stage_label: adopt
domain: meta
version: '1.0'
created: '2026-04-06'
last_modified: '2026-05-15'
last_reviewed: '2026-05-19'
review_cadence: 180
project_id: client-intelligence-platform
pm_project_id: 596825db-61bc-4899-bc6c-e207489ca35d
supersedes: 'Original §2 Two Data Layers simplified the storage model — superseded
  2026-04-20 by D-120 Three Data Layers (Structured / Derived Knowledge / Originals).
  Original §4 Tenant Model showed a nested super-tenant → venture → client shape —
  superseded 2026-04-20 by flat peer-tenant model with first-class `cip_cross_tenant_grants`.
  Original §10 Roadmap was a 3-phase Wayward-scoped list — superseded 2026-04-20 to
  point at `ROADMAP.md` as authoritative source; this section is now a hand-synced
  summary. 2026-05-15 accuracy sweep: §6 "Current stage" updated from "between 0 and
  1" to "end of Phase 1 / Wayward Phase 2 onboarding underway"; §4 "what''s missing"
  list trimmed because M1-M5 are now done (connector framework + structured store
  + lens engine + Metabase platform service all built); §7d connector-contract sketch
  corrected to match the shipped Protocol (`stream_records` + `backfill_history`,
  not `pull_full` + `pull_incremental`); §1 Wayward baseline numbers explicitly labeled
  as the original April 2026 SQLite proof-of-concept (not current Railway prod state);
  §10 Phase 2.5 migration numbering shifted to `cip_12`/`cip_13`/`cip_14` because
  `cip_09`/`cip_10`/`cip_11` are already occupied by deployed migrations (metabase
  role views, history lens views, sync_mode_backfill respectively).

  '
open_revision_items:
- M0 Vision Revisit 2026-04-20 evening — six Tim directives applied (never-defer ethos,
  Plaid/financial planned connector [updated 2026-05-09 from QBO; Bob rebuild will
  use Plaid], peer-tenant model, early write-back pulled to Phase 2.5, per-client
  siloing inside venture tenant, Foundry Chatbot spinoff).
- 2026-05-09 connector posture refresh — QBO removed from connector inventory; Plaid
  replaces it as the planned financial connector. Reflected in §3, §4 connector inventory,
  §7g registry mention. Bob (current app) defunct; new Bob will be Plaid-based and
  treated as a separate product. CIP framework still connector-agnostic.
- Cross-tenant grant placement — Phase 1 schema or Phase 2+ addition? Leaning Phase
  1 schema-only (table + RLS-aware view) with runtime behavior arriving Phase 3+.
  Confirm before Phase 1 M1 kickoff.
- Personal tenant not yet provisioned in `tenants` table — provisioning deferred until
  Tim has a concrete first use case.
- Foundry Chatbot spun out as separate product at `products/foundry-chatbot/` (stubbed,
  blocked by CIP Phase 5). Retrieval stack will be shared; consumer + branding + per-recipient
  scoping are the separation reasons. See `products/foundry-chatbot/README.md`.
doc_type: vision
status: active
---
# Foundry Client Intelligence Platform — Product Vision

> **One sentence:** A multi-tenant platform that turns any client's scattered external data into a live, queryable, agent-accessible intelligence layer — serving dashboards, reports, chatbots, filtered team views, and white-label partner portals.

---

## 1. The Problem

Every venture client engagement starts the same way: pull data from their systems, centralize it, analyze it, generate insights, deliver reports. Today this is done by hand — custom scripts, one-off SQLite files, manual analysis in Claude sessions. Each new client starts from zero.

The Wayward engagement proved the pattern (numbers below are from the **April 2026 SQLite proof-of-concept**, NOT current Railway prod ingestion — those moved as live ingestion has run; the POC numbers preserved as the motivating-moment evidence):
- **Day 1:** Pull Zendesk (1,281 tickets, 18,709 users, 5,214 comments) + HubSpot (45,687 contacts, 65,029 companies, 2,934 deals, 4,734 notes including 1,662 Firefly call transcripts)
- **Day 1:** Build unified SQLite knowledge base (153,588 records, 139MB)
- **Day 1:** Generate CEO briefing with operational audit, gap analysis, 7 proposals
- **Ongoing need:** Live dashboards, scheduled reports, filtered team views, agent context

This took a full Claude Code session to build manually. The second client should take an hour. The tenth should take minutes. That requires a product, not scripts.

---

## 2. What This Product Is

A **Client Intelligence Platform** organized into three canonical data layers (D-120) and multiple consumption interfaces, scoped per tenant and per client.

### Three Data Layers (D-120)

| Layer | Stores | Queries Via | Use Cases |
|-------|--------|-------------|-----------|
| **Structured** (PostgreSQL `cip_*`) | Contacts, companies, tickets, deals, call notes, invoices, financial records (Plaid etc.), client-siloed records per `cip_clients` | SQL with RLS + `SET LOCAL app.current_tenant`, Metabase, `foundry_mcp_cip_query` | "All Chinese brands with overdue payments," "ticket volume by month," "Q1 revenue by client," "pipeline breakdown by lens." |
| **Derived Knowledge** (Pinecone + FalkorDB) | Embeddings of ticket bodies, call transcripts, notes, docs, SOPs, research; graph nodes + edges for entity relationships | BM25 + vector retrieval (Knowledge Subsystem), GraphRAG (Graph Subsystem), `foundry_mcp_cip_search` | "What's our commission overlap policy?" "Summarize the last 3 calls with AEEZO," "Who else at this company has raised billing issues?" |
| **Originals** (Cloudflare R2) | Raw source files (PDFs, Firefly transcripts, HubSpot note HTML, Plaid exports, client uploads), indexed by `cip_files` | Storage Service; citations resolve through `cip_files` → signed R2 URL | "Open the PDF that sentence came from," "replay the original ticket payload," auditability, legal/compliance retrieval. |

All three layers are wired from Phase 1. Consumers pick which they need — a dashboard-only deployment queries Structured; a chatbot needs all three (Structured for facts, Derived Knowledge for retrieval, Originals for citations).

> **The CIP Hard Split (D-d83c7e1d, locked 2026-05-19).** All three data layers are **CIP-owned, not shared**. CIP runs its own dedicated Pinecone index (`foundry-cip`, 2,560-dim), its own R2 prefix (`cip-originals/` under the shared Foundry bucket; graduates to a dedicated bucket at Stage 3), and its own embedding pipeline. Foundry-Knowledge / per-venture knowledge stacks serve only non-CIP data (Foundry agent memory, venture-internal R&D notes, etc.) and must never write CIP-shaped content (tenant client/ticket/contact/deal/note material) — those route through CIP. See [ARCHITECTURE-SPLIT.md (CIP-SPEC-010)](../ARCHITECTURE-SPLIT.md) for the data classification rule, namespace pattern, bridge MCP tool, and Stage 1/2/3 graduation plan.

### Consumption Interfaces

| Interface | Who Uses It | What It Does |
|-----------|------------|-------------|
| **Live Dashboard** | Client CEO, venture team, Tim | Real-time metrics: ticket volume, resolution time, billing %, pipeline value. Auto-refreshing. |
| **Scheduled Reports** | Ali, team leads | Weekly/monthly automated email: "47 new tickets, 23 resolved, billing % dropped to 48%." |
| **Filtered Team Views** | PS China team, US team | Same data, different lens. Rhea sees Chinese tickets only. Rebecca sees everything. Tim sees all across both roles. |
| **Chatbot** | Tim, consultants, team | "Which brands had the most Creator Connections issues last month?" — synthesized answer from both layers. |
| **Agent RAG Context** | Foundry agents | Agent helping draft a response to a brand automatically has their ticket history, HubSpot profile, deal value, last call notes. |
| **White-Label Partner Portal** | Client's clients, partners | Branded dashboard for the end client (e.g., Wayward sees their own CS metrics with Wayward branding). |
| **Anomaly Alerts** | Tim, venture teams | "AEEZO ticket volume spiked 300% this week." "5 brands submitted payment proof but none confirmed." Slack/email. |
| **Push/Sync** | CRM, Chatwoot, Metabase | Subsets pushed to downstream systems: CRM gets contacts, Chatwoot gets tickets, dashboards get metrics. |

---

## 3. Use Cases (Proven and Planned)

### Proven: Wayward (Project Silk + EcomLever)

**What we built:** Centralized Zendesk + HubSpot + CS docs + Firefly call transcripts into 153K-record queryable database. Generated CEO briefing. Identified 7 operational gaps with data. Two roles served from one dataset (Project Silk China CS + EcomLever global consultant).

**What's needed next:**
- Live dashboard for Ali (auto-refreshing, white-labeled)
- Scheduled weekly reports
- Filtered view: Project Silk staff sees Chinese tickets only
- EcomLever view: Tim sees everything
- Chatbot for Tim: "What were the main billing complaints in February?"
- Anomaly alerts on ticket volume spikes

### Planned: Rocky Ridge

**What exists:** PDFs and documents ingested into RAG (Pinecone + R2). Chatbot interface needed for Q&A over the document corpus. Also needs client data storage (contacts, property records, etc.) and report generation.

**What CIP provides:** The unstructured layer is already built (existing knowledge ingestion pipeline). Add structured layer for client data. Chatbot interface. Report templates.

### Planned: Project Silk Client Intelligence

**What's needed:** For each Project Silk client, pull competitor data, campaign history (PPC reports), best practices for their vertical. Store as both structured (performance metrics) and unstructured (competitor analysis docs, strategy docs).

**What CIP provides:** Per-client tenant within the Project Silk venture. Connector for whatever data source the client uses. Dashboard per client. Agent context for when PS team is working on that client's account.

### Planned: AI Research Pipeline

**What's needed:** Agents continuously scan news feeds, arXiv, model releases, industry announcements. Synthesize and store. Other agents query this knowledge base for current information.

**What CIP provides:** Connectors for news/RSS feeds. Agents write TO the knowledge base (the "educate the system" loop). Other agents read FROM it via RAG. This is a WRITE pipeline, not just read — agents are both producers and consumers.

### Planned: Stock/Investment Venture

**What's needed:** Pull SEC filings, earnings call transcripts, financial data. Detect anomalies in quarterly reporting. Generate investment theses.

**What CIP provides:** Connectors for SEC EDGAR, financial data APIs. Structured layer stores the numbers. Unstructured layer stores transcripts and analyst reports. Anomaly detection on structured data. Agent-generated thesis documents.

### Planned: Financial Intelligence (Plaid + future financial sources)

**What's needed:** Every venture and personal business needs accessible financial data. Pull accounts, transactions, balances, and (where available) categorized expenses from Plaid per tenant. Generate reports on demand ("show me Q1 margin by service line for Project Silk"), surface anomalies (unusual expense patterns, large transfers, low-balance alerts), and give agents financial context when they're working on planning, pricing, or cash-flow questions.

**What CIP provides:** A Plaid connector that obeys the same `CIPConnector`/`CIPMapper` Protocol contract as every other connector (D-118) — no bespoke financial-data pillar, just another source feeding the three data layers. Structured layer gains financial tables (`cip_accounts`, `cip_invoices`, `cip_transactions`, `cip_expenses` — schema locked during Phase 2 or later when Plaid goes on the connector queue). Derived Knowledge layer embeds transaction memos and category descriptions for semantic search. Originals layer preserves raw Plaid JSON exports and any uploaded financial PDFs. Scoping: each business is typically its own tenant (Project Silk, EcomLever, Rocky Ridge, Personal, Foundry all have separate financial accounts), so financial data stays inside each tenant — cross-tenant aggregation is explicit via `cip_cross_tenant_grants` (see §4), not implicit.

**Posture:** CIP is connector-agnostic. Plaid is a named planned connector, not an elevated pillar. The connector framework must absorb it the same way it absorbs Zendesk, HubSpot, Stripe, Shopify, SEC EDGAR, news/RSS, and WhatsApp/WeChat — a new `CIPConnector` subclass, a new `CIPMapper`, a schema migration for new `cip_*` tables, registered in the connector registry. No financial-specific code paths outside the connector's mapper.

**Note on Bob (related Foundry app, NOT a CIP tenant):** the current Bob app (household finance concierge) integrated QuickBooks Online directly. That app is being rebuilt by Tim against Plaid; the rebuilt Bob is its own product line, NOT a CIP tenant. CIP's Plaid connector serves *venture/personal-tenant* financial data; Bob serves *household-app* financial data. Different products, similar source.

---

## 4. Architecture (High-Level)

```
EXTERNAL SOURCES                    CLIENT INTELLIGENCE PLATFORM                     CONSUMERS
──────────────────                  ────────────────────────────                     ─────────
                                    ┌─────────────────────────┐
Zendesk API ──────┐                 │   CONNECTOR FRAMEWORK   │
HubSpot API ──────┤                 │  (auth, paginate, rate  │
Shopify API ──────┤  ──────────→    │   limit, normalize,     │
SEC EDGAR ────────┤                 │   incremental sync)     │
News feeds ───────┤                 └───────────┬─────────────┘
WeChat logs ──────┤                             │
Manual upload ────┘                             ▼
                                    ┌───────────────────────────────────┐
                                    │         PROCESSING LAYER          │
                                    │  normalize → chunk → embed →      │
                                    │  extract entities → deduplicate   │
                                    └───────────┬───────────────────────┘
                                                │
                                    ┌───────────▼───────────────────────┐
                                    │         STORAGE LAYER             │
                                    │                                   │
                                    │  ┌─────────────┐ ┌─────────────┐ │
                                    │  │ PostgreSQL   │ │  Pinecone   │ │     Dashboards ────→ Ali, teams
                                    │  │ (structured) │ │  (vectors)  │ │     Reports ────────→ email
                                    │  │ contacts,    │ │  docs, SOPs │ │     Team Views ────→ PS staff
                                    │  │ tickets,     │ │  transcripts│ │──→  Chatbot ────────→ Tim
                                    │  │ deals, notes │ │  research   │ │     Agent RAG ──────→ agents
                                    │  └─────────────┘ └─────────────┘ │     White-Label ───→ partners
                                    │  ┌─────────────┐ ┌─────────────┐ │     Anomaly Alerts → Slack
                                    │  │     R2       │ │  FalkorDB   │ │     Push/Sync ─────→ CRM, Chatwoot
                                    │  │ (raw files)  │ │  (graph)    │ │
                                    │  └─────────────┘ └─────────────┘ │
                                    │                                   │
                                    │  TENANT SCOPING: tenant + client  │
                                    │  + cross-tenant grants + lens     │
                                    └───────────────────────────────────┘
```

### Tenant Model — Peer Tenants with Cross-Tenant Grants (updated 2026-04-20)

The tenant model is flatter than the original sketch. **Foundry operates the platform but is itself a tenant.** All primary tenants are peers — there is no "super-tenant" that implicitly sees all data. Cross-tenant visibility is explicit, auditable, and first-class via `cip_cross_tenant_grants`.

```
Foundry (platform operator — owns the hosting, schema, governance)
│
└── Peer tenants in CIP (each fully isolated by RLS + `SET LOCAL app.current_tenant`):

    ├── EcomLever        ── Clients: Wayward (primary data lives here), future consulting clients
    │                        ↓
    │                        cross-tenant grant ───→ Project Silk
    │                                                 (read-only, filtered to Wayward rows
    │                                                  relevant to PS China engagement)
    │
    ├── Project Silk      ── Clients: PS Client A, PS Client B, PS Client C …
    │                        each siloed inside PS tenant via `cip_clients`
    │                        (+ grant-in from EcomLever for Wayward)
    │
    ├── Rocky Ridge       ── Clients: Rocky Ridge land-mgmt data + document corpus
    │
    ├── Personal          ── Tim's personal businesses, finances, research
    │                        (not yet provisioned — future)
    │
    └── Foundry (self)    ── Foundry's own operational data: agent-written research,
                             cross-venture pattern discoveries, internal KB —
                             what agents USE to improve themselves.
```

**Three scoping concepts, explicitly separated:**

1. **Tenant** — top-level isolation boundary. An `EcomLever` row is invisible to `Project Silk` unless an explicit grant exists. Every query runs inside `SET LOCAL app.current_tenant = '<tenant_id>'`; RLS enforces that nothing else slips through.
2. **Client** (`cip_clients`) — the siloed unit *inside* a tenant. A Project Silk tenant has multiple `cip_client` rows (PS Client A, B, C), each owning its own deliverables, company info, contacts, notes. PS staff working on Client A don't see Client B's records — filtered by `cip_client_id` predicates in views and lens filters.
3. **Lens** (`cip_views`) — the filtered perspective *on top of* tenant + client scope. E.g., "PS China View" is a lens inside Project Silk tenant that filters by region/language; "EcomLever Full View" is a lens inside EcomLever tenant with no filters. Lenses don't cross tenants — they're always scoped inside one tenant (or on top of one grant).

**Cross-tenant grants (`cip_cross_tenant_grants` — first-class, not a workaround):**

When tenant A needs tenant B to see a specific slice of its data, Tim (or a Foundry admin in the future) creates a grant row. Shape:

- `grant_id`
- `source_tenant_id` (who owns the data)
- `target_tenant_id` (who gets to read it)
- `client_scope` (which `cip_client_id` — typically a single client like Wayward, not the whole tenant)
- `filter` (optional JSONB predicate — e.g., "region=China")
- `permissions` (enum: `read` only at first; `read+comment` later; never `write` cross-tenant)
- `authority_floor` (e.g., "validated only" — grants don't expose `agent_discovered` records unless explicitly opted in)
- `grant_window` (start / end / indefinite)
- `audit_fields` (`granted_by`, `granted_at`, `last_accessed`, `access_count`)

Runtime: when a Project Silk session queries Wayward data, the access layer walks `cip_cross_tenant_grants` for a live grant matching `source=EcomLever, target=ProjectSilk, client=Wayward`, applies its `filter` + `authority_floor`, and then runs the underlying query with both the granted tenant's RLS context *and* the local tenant's lens filter composed on top. Every cross-tenant read is logged.

**Implications for Wayward specifically (the motivating case):**

- Wayward's primary record lives in **EcomLever tenant** (EcomLever owns the consulting relationship and the historical data).
- Project Silk gets a **cross-tenant grant** from EcomLever to read the Wayward slice PS needs for its China CS work.
- Not duplicated. Not copied. The data is in one place; two tenants read it with different filters and different lenses.
- If tomorrow EcomLever decides to end the PS grant, one row flips and Project Silk loses visibility — without touching any records.

**Why this is P-21 in full force:** Lenses alone couldn't express "EcomLever owns the data but Project Silk can see a slice." Bolting cross-tenant grants onto a venture→client hierarchy would have been a hack. Modeling them first-class from Phase 1 is the only structural choice that keeps CIP defensible as more tenants come online.

### What Already Exists (Foundry Infrastructure)

| Component | State | What It Does | CIP Uses It For |
|-----------|-------|-------------|----------------|
| Pinecone client | ACTIVE | Vector upsert/query with tenant namespacing | Unstructured layer storage + retrieval |
| Qwen3-Embedding-4B | ACTIVE | 1024-d embeddings, local + cloud fallback | Embedding documents and queries |
| R2 storage | ACTIVE | S3-compatible object storage with tenant paths | Raw file storage (PDFs, JSON exports) |
| FalkorDB | ACTIVE | Knowledge graph with entity extraction | Entity relationships, graph-augmented retrieval |
| Knowledge ingester | ACTIVE | Chunk → embed → upsert pipeline | Processing unstructured documents |
| Knowledge retriever | ACTIVE | Hybrid BM25 + vector search with RRF | RAG queries over unstructured layer |
| GraphRAG retriever | ACTIVE | Graph-augmented retrieval | Entity-aware queries |
| Embedding backfill | ACTIVE | Gap detection + batch embedding | Backfilling missing vectors |
| PostgreSQL | ACTIVE | Relational DB on Railway | Structured layer storage |
| Metabase | DEPLOYED | Analytics/dashboard tool | Dashboard interface (already running at reports.project-silk.com) |

**~90% of the platform infrastructure now exists (M1–M5 of Phase 1 shipped 2026-04 → 2026-05).** Built since the original "70%" snapshot: connector framework (M2, `CIPConnector` + `CIPMapper` Protocols inside the Integration Mesh), structured-data normalization (M1 migrations `cip_01`–`cip_08` with full provenance + SCD-2 history tables), lens engine (M4, with golden-file harness), Metabase platform service with `cip_metabase_role` grant matrix + history-lens view (M5, `cip_09`/`cip_10`). What still needs to ship for CIP to be truly product-ready (per the ROADMAP backlog): scheduled-sync worker / push-and-sync pillar productization (Phase 2 + dedicated PM scope), anomaly detection + freshness alerts (Phase 6), white-label embedding controls (Phase 7), and the hardening milestones M6–M8 (registry completeness, four-access-paths validation, plain-jane lock).

### Connector Inventory (Planned)

CIP is **connector-agnostic by posture**. No connector gets pillar status; every connector implements the same `CIPConnector` + `CIPMapper` Protocol contract inside the Integration Mesh (D-118). The inventory below is the committed intent — specific phase assignments tighten as each phase locks.

| Connector | Source | Planned phase | Notes |
|-----------|--------|---------------|-------|
| **Zendesk** | Tickets, users, orgs, comments | **Phase 1 (LOCKED)** | First instance; validates the connector framework. |
| **HubSpot** | Contacts, companies, deals, notes (incl. call transcripts) | **Phase 1 (LOCKED)** | 20-revision retention = history-capture urgency; validates JSONB overflow pattern. |
| Plaid | Accounts, transactions, balances, categorized expenses | Phase 2+ (per tenant) | Financial intelligence — see §3. Connector-agnostic implementation. Replaces earlier QBO-based plan (2026-05-09). |
| Stripe | Payments, customers, subscriptions, invoices | Phase 2+ | Overlaps with Plaid for some flows — dedupe via `source_connector` + provenance. |
| Shopify | Orders, products, customers, carts | Phase 2+ | Needed when an ecom-venture client uses Shopify as system of record. |
| SEC EDGAR | Filings, earnings transcripts, financial data | Phase 2+ (Stock venture) | Read-only public data; no auth. |
| News / RSS | Industry news, competitor announcements | Phase 2+ (AI Research Pipeline) | Agents-as-producers tenant (Foundry self-tenant); writes to Derived Knowledge layer. |
| WeChat / WhatsApp | Conversation logs, media | Phase 3+ | Partner-portal + PS China relevance; auth + compliance review needed. |
| Chatwoot | Outbound ticket routing | Phase 2 (push) | Downstream consumer, not an inbound source — writes via Push & Sync pillar. |
| Gmail / Google Drive | Email threads, document corpora | Phase 3+ | Source-of-truth for some ventures; MS365 parallel TBD. |
| Manual Upload | Ad-hoc PDFs, CSVs, founder-provided docs | **Phase 1 (LOCKED)** | Always the fallback; required for Rocky Ridge and for any tenant where a connector doesn't yet exist. |

**Explicitly not a pillar:** no "Financial Connector Pillar," no "Social Connector Pillar," no per-source elevation. New connectors are scope-as-you-need-them inside Pillar 1 (Ingestion & Connectors). The connector registry (`cip_connectors`) tracks which are deployed per tenant.

---

## 5. What Makes This a Product (Not Just Infrastructure)

The existing services (pinecone_client, knowledge_ingester, knowledge_retriever) are plumbing. The PRODUCT wraps them with:

1. **Connector marketplace** — Zendesk, HubSpot, Shopify, Stripe, SEC, news feeds. Each follows a standard interface contract. New connectors are plug-and-play.

2. **One-command provisioning** — "Create a new client KB for Wayward under Project Silk" → tenant created, connectors configured, dashboard provisioned, team access set.

3. **Consumption templates** — Pre-built dashboard layouts (CS metrics, sales pipeline, billing health). Pre-built report templates (weekly CS summary, monthly pipeline review). Chatbot with both-layer access.

4. **The agent write-back loop** — Agents don't just READ from the KB. They WRITE discoveries, synthesis, and analysis back into it. The AI research pipeline is agents continuously enriching the knowledge base.

5. **White-label** — Partner-branded dashboards and reports. Wayward sees Wayward branding. Each client sees their own brand.

---

## 6. Product Lifecycle (per PRODUCT-STANDARD.md)

**Stage 1 (Internal Tool):** Works for Wayward. Tim can query it. Dashboards for Ali. Foundry uses it internally.

**Stage 2 (Platform Product):** Multi-tenant, API, connectors. Other ventures use it for their clients. Tenant isolation enforced.

**Stage 3 (Deployable):** Own service, own CI/CD. External customers could buy this. "Plug in your CRM and ticketing credentials, get a client intelligence dashboard in 24 hours."

**Current stage:** End of Phase 1 / start of Phase 2. Plain-jane CIP (Phase 1 M1–M5) is built and deployed on Railway prod. Wayward onboarding (Phase 2) is live as of 2026-05-14 — first real-tenant ingestion in progress, validating the connectors + lens + Metabase stack against real production data for the first time. Multi-tenant + cross-tenant grants (Phase 3, Rocky Ridge) and write-back (Phase 2.5, Foundry self-tenant) remain ahead; together they bring CIP to Stage 2 (multi-tenant platform product).

---

## 7. Platform Capabilities (Industry-Hardened)

Six capabilities identified from industry research. First two are Day 1 requirements. Remaining four are designed into the architecture from the start with phased implementation.

### 7a. Provenance & Audit Trail (Day 1)

Every record carries: source connector, source API call ID, ingestion timestamp, last refresh timestamp, what it replaced (previous version ID). Not metadata bolted on later — core schema fields.

**Why Day 1:** When a CEO asks "where did that number come from?" the answer must be traceable to a specific API call at a specific time. When an agent makes a recommendation, you need to know what it "knew" at decision time. The EU AI Act (Articles 12-13, enforcement Aug 2026) requires this for high-risk AI systems. Building it in from the start is free — retrofitting is weeks of migration.

**Implementation:** Every structured table gets `source_connector`, `source_id`, `ingested_at`, `refreshed_at`, `previous_version_id` columns. Every vector in Pinecone gets source metadata in the payload. The knowledge ingestion engine already tracks source IDs — extend this pattern to the structured layer.

Sources: [Atlan AI Agent Memory Governance](https://atlan.com/know/ai-agent-memory-governance/), [MemOS: A Memory OS for AI](https://statics.memtensor.com.cn/files/MemOS_0707.pdf)

### 7b. Time Decay & Freshness Scoring (Day 1)

Not all data ages equally. A ticket from yesterday is urgent. A ticket from 6 months ago is historical context. A contact's email is probably still valid. A deal stage from 3 months ago is probably stale.

**Why Day 1:** RAG retrievers and agent context must weight by freshness, not just semantic relevance. "Current billing issues" should prioritize last-30-day tickets even if older ones are more similar. Without freshness scoring, agents give stale answers confidently.

**Implementation:** Freshness score = function of (record age, record type, last interaction date). Structured queries get `ORDER BY refreshed_at DESC` by default. Unstructured retrieval gets a freshness boost in the RRF fusion scoring. The existing memory service already has decay scoring — CIP inherits that pattern.

Sources: [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026), [NStarX RAG Evolution 2026-2030](https://nstarxinc.com/blog/the-next-frontier-of-rag-how-enterprise-knowledge-systems-will-evolve-2026-2030/)

### 7c. Cross-Client Pattern Detection — Portfolio View (Phase 2+)

The venture studio superpower: aggregate anonymized patterns ACROSS tenants. "Billing confusion is the #1 CS issue for 4 of 7 clients." "Creator Connections setup problems appear in 60% of similar engagements."

**Why plan now:** The tenant model must support this from day one — a Foundry super-tenant view that aggregates patterns WITHOUT exposing client-specific data. If tenant isolation is too rigid, you can never build this. If it's too loose, you leak data.

**Implementation:** Design tenant scoping so that aggregate queries (counts, percentages, category distributions) can run across tenants at the Foundry level. Individual records stay isolated. Think: "what percentage of our clients have billing as their #1 issue?" without revealing which clients or their actual data.

Source: [Multi-Tenant Analytics Architecture Guide](https://www.usedatabrain.com/blog/multi-tenant-analytics)

### 7d. Connector Marketplace — Self-Service Provisioning (Phase 2+)

Treat connectors as managed product capabilities, not bespoke integrations. Browse available connectors (Zendesk, HubSpot, Shopify, Stripe, Amazon, SEC EDGAR, news feeds), provision with one click, credentials entered once, sync starts automatically.

**Why plan now:** The connector interface contract must be clean enough that a new connector is a weekend project, not a week-long effort. If the first two connectors (Zendesk, HubSpot) have bespoke patterns, every future connector reinvents the wheel.

**Implementation:** Standard connector contract (shipped in M2 as `CIPConnector` + `CIPMapper` Protocols inside the Integration Mesh per D-118): `authenticate()`, `describe_schema() → list[PropertyDescriptor]`, `stream_records(cursor, batch_size) → Iterator[dict]` (current-state pull, cursor-resumable), `backfill_history(tenant_id) → Iterator[HistoricalRecord]` (D-159 historical pull, per-tenant, mandatory by default), `incremental_key(record) → datetime`, `rate_limit_policy → RateLimitPolicy`, plus the `CIPMapper` side (`map(record) → Iterator[mapped]`). Every connector implements this Protocol pair; `validate_connector_shape()` enforces conformance at orchestrator startup. The marketplace is just a registry of available connectors with their configs (`cip_connector_property_registry` + `cip_connectors` tables).

Source: [CData 2026 Multi-Tenant Integration Playbook](https://www.cdata.com/blog/multi-tenant-data-integration-platform-scalable-saas-2026)

### 7e. Embedded Self-Service Analytics (Phase 2+)

Beyond pre-built dashboards: the client's own team can build custom reports, create their own filters, explore their own data. Self-service, not just pre-built views.

**Why plan now:** The data model must be Metabase-friendly from the start — clean table names, proper relationships, tenant filtering via row-level security. If the schema is designed for programmatic access only, bolting on self-service analytics later requires a compatibility layer.

**Implementation:** Metabase already supports embedded dashboards with row-level security and is already deployed at reports.project-silk.com. Design PostgreSQL tables so Metabase can connect directly with `WHERE tenant_id = :current_tenant` filtering. White-label via Metabase's embedding API with custom CSS per client.

Source: [Workhuman Multi-Tenant QuickSight](https://aws.amazon.com/blogs/machine-learning/how-workhuman-built-multi-tenant-self-service-reporting-using-amazon-quick-sight-embedded-dashboards/), [Qrvey Multi-Tenant Embedded Analytics](https://qrvey.com/blog/multi-tenant-databases-and-embedded-analytics/)

### 7f. Agent Write-Back Loop — Knowledge as a Living System (Phase 2+)

Agents are not just consumers of the KB — they're producers. The AI research pipeline feeds discoveries back into the KB. Stock analysis agents write investment theses. CS agents write synthesized summaries of common issues.

**Why plan now:** The authority model must distinguish human-validated knowledge from agent-discovered knowledge from the start. The existing knowledge contract has authority levels: `validated`, `agent_discovered`, `pending_review`, `retracted`, `superseded`. CIP inherits this — agent-written content starts at `agent_discovered` and gets promoted after review.

**Implementation:** Write API alongside the read API. Agents call `cip_write(tenant_id, content, source="agent", authority="agent_discovered")`. Temporal versioning so you can see what was believed true at any past point — critical for the stock venture (financial knowledge decays fast).

Sources: [Oracle AI Agent Memory](https://blogs.oracle.com/database/introducing-oracle-ai-agent-memory-a-unified-memory-core-for-enterprise-ai-systems), [Temporal Knowledge Graphs as Long-Term Memory](https://medium.com/@bijit211987/agents-that-remember-temporal-knowledge-graphs-as-long-term-memory-2405377f4d51)

### 7g. Agent Discoverability — The Four Access Paths (Phase 1 + Phase 4)

D-121 mandates registries exist so agents can discover CIP data. This subsection names the **four access paths** an agent needs to light up end-to-end against any tenant. Phase 1 M7 validates the paths work against the **fixture tenant** (plain-jane reshape 2026-04-20 — no real venture data in Phase 1); Phase 2 re-validates the same paths against Wayward; Phase 4 ships the MCP tool wrappers that make these paths ergonomic.

| # | Path | What it reaches | How an agent invokes it | Phase |
|---|------|-----------------|-------------------------|-------|
| 1 | **Structured** — direct SQL with tenant scope | `cip_*` Postgres tables (contacts, companies, tickets, deals, financial, grants registry) | `foundry_mcp_db_query` with RLS + `SET LOCAL app.current_tenant` enforced by the access layer | Phase 1 (raw), Phase 4 (wrapped as `foundry_mcp_cip_query`) |
| 2 | **Derived Knowledge — vector + BM25** | Pinecone chunks and payloads for a tenant, keyed by `knowledge_sources.source_type IN (cip_ticket, cip_note, cip_doc, …)` | Knowledge Subsystem retrieval (`knowledge_retriever_service`) | Phase 1 (raw), Phase 4 (wrapped as `foundry_mcp_cip_search`) |
| 3 | **Derived Knowledge — graph** | FalkorDB nodes/edges for a tenant (entity relationships, mention graph) | Graph Subsystem retrieval (`graphrag_retriever_service`) | Phase 1 (raw), Phase 4 (wrapped into `foundry_mcp_cip_search` when graph boost is requested) |
| 4 | **Originals** — signed R2 URLs | `cip_files` rows → R2 object paths → signed URL | Storage Service (starts from `cip_files.cip_file_id`) | Phase 1 (raw), Phase 4 (wrapped as `foundry_mcp_cip_files`) |

**Discoverability registries (D-121):** Every path above is backed by a registry so an agent with only generic `foundry_mcp_*` tools can discover what exists without hard-coded table names. Examples: `cip_connector_property_registry` (names every HubSpot/Zendesk/Plaid property and which column or JSONB path it lives at), `knowledge_sources` (names every `source_type` with its row shape), `graph_templates` (names every node/edge type + relationship pattern), `cip_files` metadata (names every file with its original connector + content-type). If an agent can't find a property/source/entity/file through these registries, it shouldn't exist.

**Phase 1 M7 (Agent Discoverability Validation)** — the acceptance gate that proves all four paths light up against the **fixture tenant**. See `vision/PHASE-1-PLAN.md` Milestone 7 for the concrete validation procedure. Phase 2 re-validates the paths against Wayward as part of the full round-trip. **Phase 4 (Agent Access Surfaces)** ships the MCP tool wrappers referenced in the table.

### 7h. Conversational Access — Who Uses the Chatbot (Phase 5)

Phase 5 lights up a **chatbot capability inside CIP**. Its scope is **internal / staff-facing**. Intended consumers:

- **Tim** — asking questions across all tenants he has access to (including cross-tenant via grants).
- **Foundry agents** — pulling conversational context via `foundry_mcp_cip_*` tools rather than a UI.
- **Rocky Ridge staff** — Q&A over Rocky Ridge's document corpus and records (first non-Tim tenant for this surface; likely the Phase 5C first-tenant pilot per the Task #14 kickoff).
- **Project Silk staff** — Q&A over PS-internal client deliverables + the grant-in view of Wayward.
- **EcomLever staff** — Q&A over EcomLever's consulting clients.

All five consumer types share: lens-aware, grant-aware, citations mandatory (Structured row IDs + R2 paths), refusal on low-grounding queries, read-only in Phase 5 (write-back is Phase 2.5 / Phase 7, separate surface).

**Explicitly out of scope for Phase 5:** client-facing chatbots — a tenant's *end clients* (e.g., Wayward's customers asking about their own orders) are served by a separate product, **Foundry Chatbot**, which is stubbed at `products/foundry-chatbot/` and is blocked by this CIP chatbot shipping first. Foundry Chatbot reuses the CIP retrieval stack but adds per-recipient permission scoping, tenant-branded embed widgets, end-customer auth, and tighter governance. See `products/foundry-chatbot/README.md` for the separation rationale.

---

## 8. Relationship to Existing Foundry Products (unchanged)

| Product/Service | Relationship |
|----------------|-------------|
| **CRM** (products/crm/) | CIP is a DATA SOURCE for CRM (pushes contacts/companies). CRM is a CONSUMER. They're peers. |
| **Knowledge System** (products/knowledge-system/) | Different scope. KS = Foundry's organizational knowledge. CIP = client/customer data intelligence. Could share the retrieval layer. |
| **Memory Service** (platform/memory-service/) | CIP USES memory service infrastructure (Pinecone, FalkorDB). Memory service is plumbing; CIP is application. |
| **Agent Platform** | Agents CONSUME CIP via MCP tools for RAG context. Agents WRITE to CIP in the research/discovery pipeline. |
| **PM System** | PM tracks the PROJECT of building CIP. CIP tracks CLIENT data for venture engagements. Different domains. |

---

## 9. Name

**Foundry Client Intelligence Platform (CIP)**

Alternatives considered:
- Foundry Knowledge Base — too narrow (implies docs only, not structured data)
- Foundry Data Bridge — emphasizes connectors but misses intelligence/analysis
- Foundry Insight Engine — good but sounds like a BI tool only
- Client Intelligence Platform — captures the full scope: data + intelligence + multi-client + multi-interface

---

## 10. Roadmap (Summary — Authoritative Source is `ROADMAP.md`)

**Authoritative:** `products/client-intelligence-platform/vision/ROADMAP.md`. This section is a hand-synced summary. If the two disagree, `ROADMAP.md` wins.

The original §10 (Wayward-scoped 3-phase "Foundation / Product Layer / Intelligence Layer") has been superseded since 2026-04-17 by the pillar-aligned multi-phase ROADMAP. The 2026-04-20 M0 Vision Revisit inserted **Phase 2.5 — Foundry Self-Tenant + Early Write-Back** between Phase 2 and Phase 3 to pull write-back forward. The 2026-04-20 **Plain-Jane Reshape** rewired Phase 1 to fixture-tenant-only + 10 doc artifacts, pulled Wayward onboarding into its own dedicated Phase 2 (full round-trip inbound + push), trimmed Phase 2.5 to write-back only, moved `cip_09` cross_tenant_grants to Phase 3, and dropped all week-based appetites in favor of session-bound milestone-ordered execution.

Phase structure at a glance (provisional beyond Phase 1):

- **Phase 0 — Data Model & Tenant Architecture.** COMPLETE 2026-04-17. Locked 10 decisions (DB, tenant model, provenance, SCD, auth).
- **Phase 1 — Plain-Jane CIP + Documentation Suite.** LOCKED 2026-04-20 (reshape). Session-bound, milestone-ordered — no calendar appetite. **No real tenant** — validated against a synthetic FixtureConnector producing deterministic test data. 12 code deliverables + 10 documentation artifacts. Two lenses (Lens-A empty / Lens-B `region=EMEA`) on the fixture dataset. Metabase sole consumer. **`cip_09` cross_tenant_grants is NOT in Phase 1** — held until Phase 3 so schema + runtime ship together.
- **Phase 2 — Wayward Onboarding (Full Round-Trip).** Inbound (Zendesk + HubSpot connectors — HubSpot 20-revision retention clock starts here) + two lenses on real Wayward data + outbound push (Chatwoot, PS Twenty CRM, client Google Drive) + first-light REST API. Primary tenant in EcomLever; PS grant-in deferred to Phase 3.
- **Phase 2.5 — Foundry Self-Tenant + Write-Back.** NEW per 2026-04-20 M0, trimmed 2026-04-20 plain-jane reshape (push was in scope; now pure write-back). Foundry provisioned as a tenant. Migrations `cip_12`/`cip_13`/`cip_14` (renumbered 2026-05-15 — the originally reserved `cip_10`/`cip_11` slots were consumed by M5 history-lens-views and the 2026-05-15 sync_mode_backfill hotfix; see ROADMAP.md and PHASE-2.5-PLAN.md). `cip_write` API exposed on REST, MCP, and Python — all converging on one `write_service.cip_write()`. Authority model with TSP thresholds (auto-promote ≥ 0.9, allow ≥ 0.5).
- **Phase 3 — Rocky Ridge + Multi-Tenant + Cross-Tenant Grants Runtime.** `cip_09` migration + runtime together. Rocky Ridge onboards as tenant #2. PS grant-in to Wayward lights up. Cross-tenant lens validation. Access-layer observability.
- **Phase 4 — Agent Access Surfaces (REST + MCP).** Provisional. Chatbot explicitly excluded.
- **Phase 5 — Chatbot Capability (Internal / Staff-Facing).** Provisional. Three stages: 5A Vision, 5B Architecture, 5C Implementation. First tenant Rocky Ridge, then Wayward via grant. Intended consumers listed in §7g.
- **Phase 6 — Intelligence & Alerts.** Provisional. Anomaly detection, freshness alerts, scheduled analytical reports.
- **Phase 7 — Investigative Agents + Advanced Write-Back.** Provisional. Rich validated-promotion UX, cross-tenant anonymized patterns, temporal snapshot API, self-service embedded analytics.
- **Phase 8 — Scale & Extract.** Provisional. Extract `cip_*` to dedicated PostgreSQL instance per Phase 0 decision #1.

**Related products, tracked separately:**

- `products/foundry-chatbot/` — client-facing chatbot product (stubbed, blocked by CIP Phase 5). Reuses CIP retrieval stack; separate consumer model, separate branding, separate governance. See its README for what's different.

---

## Origin

This vision emerged from the Wayward CS Overhaul project (April 2026). Tim built a one-off centralized knowledge base for Wayward by pulling Zendesk + HubSpot into SQLite. The moment it worked, three things became clear:
1. Every venture client needs this
2. The pattern is venture-agnostic
3. This is a product, not a script

The industry calls this a Client Intelligence Platform or Customer Data Platform. Nobody combines structured data + unstructured RAG + multi-tenant isolation + agent-native access into one product for venture studios. That's the gap.


## North star

_TODO: author this section per the doc-standard._

## Horizon

_TODO: author this section per the doc-standard._

## What "full strength" looks like

_TODO: author this section per the doc-standard._

## What we need to solve for

_TODO: author this section per the doc-standard._

## Locked decisions

_TODO: author this section per the doc-standard._

## Non-goals

_TODO: author this section per the doc-standard._

## Last reviewed

_TODO: author this section per the doc-standard._

