---
id: CIP-BP-911
uuid: 4b7877c7-d0e5-4320-b0ab-827b5611a2b0
title: Foundry Knowledge Base — Product Braindump
type: best-practice
owner: tim
solve_for: Retired/archived artifact retained for audit and historical context — 01-initial-braindump.md.
stage_label: retire
domain: meta
version: '1.0'
created: '2026-04-06'
last_modified: '2026-05-16'
last_reviewed: '2026-05-19'
review_cadence: 9999
---

# Foundry Knowledge Base — Product Braindump

> **Status:** Pre-vision. Collecting patterns, research, and lessons before designing.
> **Date:** 2026-04-06
> **Owner:** Tim

---

## Where This Came From

We built a one-off centralized knowledge base for Wayward (Project Silk client) by pulling their Zendesk tickets, HubSpot contacts/companies/deals/notes, and internal CS documents into a single SQLite database. 153,588 records across 8 tables. Queryable in milliseconds. Took one session to build.

The moment it was done, three things became obvious:
1. Every venture client will need this same thing
2. The pattern (ingest → centralize → query → push subsets) is venture-agnostic
3. This is a product, not a one-off script

---

## The Pattern We Proved with Wayward

```
External Sources          Central KB              Consumers
─────────────────         ──────────              ─────────
Zendesk API ──────→       Unified                 Tim (EcomLever) → full dataset
HubSpot API ──────→       Knowledge    ──────→    Project Silk → Chinese subset
Internal docs ────→       Base                    Wayward team → reports
Call transcripts ─→       (queryable)             Agents → RAG context
WeChat logs ──────→                               Dashboards → live metrics
```

**What worked:**
- Pull scripts with caching (re-runnable, skip what's already downloaded)
- JSON → SQLite flattening (all fields, not a subset)
- Single .db file = portable, queryable, no server needed
- Property schemas saved = self-documenting (know every field name and type)
- Indexes on key columns = instant queries

**What's missing:**
- No auto-refresh (manual re-pull)
- No tenant isolation (one big DB)
- No access control (anyone with the file can see everything)
- No versioning (no history of what changed between pulls)
- No embeddings / semantic search (just SQL text search)
- No connection to Foundry's existing Memory Service or Knowledge System
- No UI (pure SQL queries or Python scripts)

---

## What the Industry Does

### Customer Data Platforms (CDPs)
Source: [Luxid Group 2026 CDP trends](https://www.luxidgroup.com/blog/what-to-watch-in-2026-building-a-shared-understanding-of-customer-data-platforms)

CDPs centralize customer data from all touchpoints into unified profiles. Moving toward real-time personalization with behavioral signals and predictive insights. Key trend: CDPs are becoming "composable" — modular components rather than monolithic platforms. Relevant to us: the ingestion layer, identity resolution, and audience segmentation concepts map directly.

### RAG Knowledge Bases
Sources: [SingleStore RAG guide](https://www.singlestore.com/blog/how-to-build-a-rag-knowledge-base-in-python-for-customer-support/), [Astera KB for RAG](https://wp.astera.com/type/blog/building-a-knowledge-base-rag/)

RAG (Retrieval-Augmented Generation) is the standard pattern for AI-powered knowledge bases: ingest docs → chunk → embed → store in vector DB → retrieve relevant chunks at query time → feed to LLM for answer generation. Companies report 40-60% faster resolution times with semantic KB access. Multi-source ingestion from CRM, Zendesk, Slack, PDFs, wikis.

### Multi-Tenant Knowledge Bases
Source: [Docsie 2026 guide](https://www.docsie.io/blog/articles/multi-tenant-knowledge-base-2026/)

Multi-tenant KB serves multiple clients from one platform with data isolation. Each client gets their own branded portal. Content managed from centralized dashboard. Key: access hierarchies, per-tenant config, branding, and permissions without security risks.

### Agentic AI for Support
Source: [Parloa enterprise AI](https://www.parloa.com/knowledge-hub/enterprise-ai-customer-support-platforms/)

2025-2026 trend: agentic AI (not just chatbots, not just RAG) autonomously resolves 70-85% of support queries vs 40-60% for RAG-only. Native integrations with Salesforce, Zendesk, Intercom, Stripe enable reads, updates, and workflow triggers. This is where our product could go — not just a KB, but an agent that uses the KB.

---

## Use Cases Beyond Wayward

| Client Type | Sources to Ingest | What They'd Query |
|-------------|------------------|-------------------|
| **E-commerce brand** (like Wayward) | Zendesk, HubSpot, Shopify, Amazon Seller Central | CS tickets, customer profiles, order history, product performance |
| **SaaS company** | Intercom, Stripe, GitHub Issues, internal wiki | Support tickets, billing, feature requests, deployment history |
| **Agency** (like Project Silk) | Client CRMs, client Zendesks, project management tools | Cross-client patterns, team utilization, deliverable tracking |
| **Venture portfolio** (like Shatcher) | All of the above, across multiple ventures | Portfolio-level intelligence, cross-venture patterns |
| **Consulting engagement** (like EcomLever) | Client's everything — full data audit | Operational gaps, efficiency opportunities, strategic insights |

---

## Architectural Questions (for vision discussion)

### 1. Storage Model
- **SQLite per client** (what we did) — simple, portable, no server. But no concurrent access, no real-time, no vector search.
- **PostgreSQL per tenant** — what we already have for the Foundry platform. Multi-tenant with D-026 scoping. Could add a `knowledge_chunks` approach.
- **Vector DB (Pinecone/Qdrant)** — for semantic search and RAG. We already have Pinecone in the stack.
- **Hybrid** — PostgreSQL for structured data (contacts, tickets, deals) + Pinecone for unstructured data (docs, transcripts, call notes). This is probably the right answer.

### 2. Ingestion Model
- **Pull-based** (what we did) — scripts that fetch from APIs on demand or schedule
- **Push-based** — webhooks from Zendesk/HubSpot/etc. that stream updates in real-time
- **Hybrid** — initial bulk pull, then webhooks for incremental updates. Industry standard for CDPs.

### 3. Tenant Isolation
- **Separate databases** — maximum isolation, expensive
- **Shared database, separate schemas** — good balance
- **Shared database, row-level isolation** (D-026 pattern) — what we already do. Each record has a tenant_id.

### 4. What Lives Where
- **Structured data** (contacts, companies, tickets, deals) → PostgreSQL with tenant_id
- **Unstructured data** (docs, call transcripts, email bodies) → chunked, embedded, stored in Pinecone with tenant namespace
- **Raw exports** (JSON, CSV) → R2 storage with lifecycle policies
- **Metadata/schemas** (property definitions, field mappings) → PostgreSQL config tables

### 5. Connector Architecture
Each external system needs a "connector" — a module that knows how to:
- Authenticate (API key, OAuth, token)
- Paginate (cursor-based, offset-based, incremental)
- Handle rate limits
- Map fields to a normalized schema
- Detect and sync incremental changes

We already have two connectors (Zendesk, HubSpot). Future connectors: Shopify, Stripe, Intercom, Slack, Amazon Seller Central, Google Workspace, Chatwoot, etc.

### 6. Query Layer
- **SQL** (what we did) — powerful but requires knowing the schema
- **Natural language** (via LLM + RAG) — "show me all Chinese clients with overdue invoices" → SQL or vector search
- **API** — REST endpoints for other systems to query
- **Dashboard** (Metabase or custom) — visual exploration
- **Agent tools** (MCP) — Foundry agents can query the KB directly

### 7. Output/Push Model
The KB isn't just a place to query — it pushes subsets to consumers:
- Project Silk CRM gets Chinese contacts synced automatically
- Chatwoot gets tickets migrated
- Dashboards get metrics updated
- Agents get RAG context at query time
- Reports get generated on schedule

---

## Relationship to Existing Foundry Architecture

| Existing System | Relationship to KB Product |
|----------------|---------------------------|
| **Memory Service** (`platform/memory-service/`) | KB product CONSUMES memory service for vector storage. Memory service provides the vector/graph store — KB product provides the ingestion, normalization, and tenant scoping on top. |
| **Knowledge System** (`products/knowledge-system/`) | KB product is DIFFERENT from Knowledge System. KS is about organizational knowledge (Foundry's own knowledge). KB product is about client/customer data intelligence. Could share retrieval patterns. |
| **Storage Service** (`platform/storage-service/`) | KB product uses storage service for R2 (raw exports), PostgreSQL (structured data), Pinecone (vectors). Storage service is the plumbing — KB product is the application. |
| **CRM** (`products/crm/`) | CRM is a CONSUMER of KB data. KB pushes contact/company data to CRM. CRM pushes interaction data back to KB. They're peers, not parent-child. |
| **Agent Platform** | Agents CONSUME KB via tools (MCP or native). KB provides RAG context for agent reasoning. This is the highest-leverage integration — agents that can query a client's full knowledge base. |

---

## Lessons from the Wayward Build

### What to Keep
1. **Property schema preservation** — saving the full field definitions means any future query knows what every column means
2. **Caching/idempotency on pull scripts** — re-runnable without duplicating data
3. **Flatten everything** — don't try to preserve nested JSON in the DB, flatten to columns
4. **Index aggressively** — the queries we ran were instant because of indexes on email, company, country, status, ticket_id
5. **Notes/call transcripts are gold** — the Firefly data was the most valuable discovery

### What to Fix
1. **Don't put 800MB JSON files in git** — R2 storage from the start
2. **Don't do one-shot pulls** — build for incremental sync from day one
3. **Text search is limited** — need vector embeddings for semantic queries ("find all tickets about brands confused by commission overlap" can't be done with LIKE '%commission%')
4. **No history** — when we re-pull, we overwrite. Need to track what changed between syncs
5. **Single-user** — SQLite file on one machine. Needs to be accessible to agents, dashboards, and multiple humans

---

## Proposed Product Name Options

- **Foundry Knowledge Base** (literal, clear)
- **Foundry Intelligence Hub** (broader, includes analytics)
- **Foundry Client Intelligence** (specific to client data)
- **Foundry Data Bridge** (emphasizes the connector/sync aspect)
- **Foundry Insight Engine** (emphasizes the query/analysis layer)

Tim to decide.

---

## Next Steps (for vision discussion)

1. **Agree on scope** — is this a data platform, a knowledge base, an AI agent context layer, or all three?
2. **Agree on architecture** — hybrid (PostgreSQL + Pinecone + R2) or simpler?
3. **Agree on first connectors** — Zendesk + HubSpot are built. What's next?
4. **Agree on tenant model** — D-026 row-level isolation or separate schemas?
5. **Agree on product name**
6. **Design the connector interface** — standard contract every connector follows
7. **Design the query layer** — SQL + natural language + API + MCP tools
8. **Design the push/sync model** — how subsets get pushed to consumers
9. **Build v1** — Wayward as the first tenant, prove it works in production
