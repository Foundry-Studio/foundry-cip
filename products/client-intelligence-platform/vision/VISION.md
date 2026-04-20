---
doc_type: vision
project_id: client-intelligence-platform
pm_project_id: 596825db-61bc-4899-bc6c-e207489ca35d
status: draft
owner: tim
created: 2026-04-06
---

# Foundry Client Intelligence Platform — Product Vision

> **One sentence:** A multi-tenant platform that turns any client's scattered external data into a live, queryable, agent-accessible intelligence layer — serving dashboards, reports, chatbots, filtered team views, and white-label partner portals.

---

## 1. The Problem

Every venture client engagement starts the same way: pull data from their systems, centralize it, analyze it, generate insights, deliver reports. Today this is done by hand — custom scripts, one-off SQLite files, manual analysis in Claude sessions. Each new client starts from zero.

The Wayward engagement proved the pattern:
- **Day 1:** Pull Zendesk (1,281 tickets, 18,709 users, 5,214 comments) + HubSpot (45,687 contacts, 65,029 companies, 2,934 deals, 4,734 notes including 1,662 Firefly call transcripts)
- **Day 1:** Build unified SQLite knowledge base (153,588 records, 139MB)
- **Day 1:** Generate CEO briefing with operational audit, gap analysis, 7 proposals
- **Ongoing need:** Live dashboards, scheduled reports, filtered team views, agent context

This took a full Claude Code session to build manually. The second client should take an hour. The tenth should take minutes. That requires a product, not scripts.

---

## 2. What This Product Is

A **Client Intelligence Platform** with two data layers and multiple consumption interfaces, scoped per venture and per client.

### Two Data Layers

| Layer | Stores | Queries Via | Use Cases |
|-------|--------|-------------|-----------|
| **Structured** (relational) | Contacts, companies, tickets, deals, call notes, invoices, financial data | SQL, API, dashboards, reports | "All Chinese brands with overdue payments," "ticket volume by month," "$3M pipeline breakdown" |
| **Unstructured** (vector/RAG) | PDFs, documents, SOPs, transcripts, research articles, email bodies | Semantic search, chatbot, agent RAG context | "What's our commission overlap policy?" "Summarize the last 3 calls with AEEZO" |

Both layers are optional per deployment. A client who just wants dashboards gets structured only. A client who wants document Q&A gets both. Mix and match.

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
                                    │  TENANT SCOPING: venture → client │
                                    └───────────────────────────────────┘
```

### Tenant Model

```
Foundry (super-tenant, sees everything)
├── Shatcher Ventures
│   ├── Project Silk (venture tenant)
│   │   ├── Wayward (client sub-tenant)  ← PS staff sees Chinese subset
│   │   ├── Next PS client
│   │   └── ...
│   ├── EcomLever (venture tenant)
│   │   ├── Wayward (same data, full view) ← Tim sees everything
│   │   └── Next consulting client
│   ├── Rocky Ridge (venture tenant)
│   │   └── Land management data
│   └── Stock Venture (venture tenant)
│       └── Financial data
└── Foundry Internal
    └── AI Research Pipeline (self-feeding KB)
```

**Key:** Wayward data exists ONCE but is visible through TWO lenses (Project Silk filtered view + EcomLever full view). Not duplicated.

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

**~70% of the infrastructure already exists.** What's missing: connector framework, structured data normalization, consumption interfaces, filtered views, scheduled reports, anomaly detection, white-label.

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

**Current stage:** Between 0 and 1. Wayward SQLite proof-of-concept exists. Existing infrastructure covers ~70%. Need to build the product layer on top.

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

**Implementation:** Standard connector contract: `authenticate()`, `discover_schema()`, `pull_full()`, `pull_incremental(since_timestamp)`, `normalize(raw_record) → standard_record`, `get_rate_limits()`. Every connector implements this interface. The marketplace is just a registry of available connectors with their configs.

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

## 8. Name

**Foundry Client Intelligence Platform (CIP)**

Alternatives considered:
- Foundry Knowledge Base — too narrow (implies docs only, not structured data)
- Foundry Data Bridge — emphasizes connectors but misses intelligence/analysis
- Foundry Insight Engine — good but sounds like a BI tool only
- Client Intelligence Platform — captures the full scope: data + intelligence + multi-client + multi-interface

---

## 10. Roadmap

### Phase 1: Foundation (Wayward as first tenant)
1. Architecture design — data model with provenance fields, connector interface contract, tenant scoping schema (venture → client → view)
2. Connector framework — standard contract with `authenticate/discover_schema/pull_full/pull_incremental/normalize/rate_limits`. Evolve Zendesk + HubSpot scripts.
3. Structured data layer — PostgreSQL tables with tenant_id, provenance columns, freshness timestamps
4. Wayward migration — SQLite → production PostgreSQL + Pinecone. First live tenant.
5. Dashboard — Metabase connected to structured layer with tenant-filtered views
6. Filtered views — PS staff sees Chinese only, EcomLever sees all, Ali sees dashboards

### Phase 2: Product Layer
7. Scheduled reports — automated weekly/monthly email delivery per tenant
8. Chatbot — RAG interface over both structured + unstructured layers
9. Agent MCP tools — `cip_query`, `cip_search`, `cip_write` for agent access
10. Anomaly detection — ticket volume spikes, billing gaps, engagement drops → Slack/email alerts
11. White-label — per-client branding on dashboards and reports
12. Connector marketplace — self-service provisioning, connector registry, one-click setup

### Phase 3: Intelligence Layer
13. Cross-client pattern detection — portfolio-level anonymized aggregation across tenants
14. Agent write-back loop — agents as knowledge producers with authority levels
15. Self-service embedded analytics — clients build their own reports
16. Temporal versioning — point-in-time knowledge snapshots (critical for stock venture)
17. Second and third tenants — prove multi-tenancy works beyond Wayward

---

## Origin

This vision emerged from the Wayward CS Overhaul project (April 2026). Tim built a one-off centralized knowledge base for Wayward by pulling Zendesk + HubSpot into SQLite. The moment it worked, three things became clear:
1. Every venture client needs this
2. The pattern is venture-agnostic
3. This is a product, not a script

The industry calls this a Client Intelligence Platform or Customer Data Platform. Nobody combines structured data + unstructured RAG + multi-tenant isolation + agent-native access into one product for venture studios. That's the gap.
