---
kind: doc
domain: client-intelligence-platform
status: note
created: 2026-04-06
---

# Vision Discussion Outline — Foundry Knowledge Base Product

> **Purpose:** Structure the conversation between Tim and Claude to lock the product vision before architecture design.

---

## Questions to Resolve (in order)

### 1. Scope — What is this product?

Options (not mutually exclusive):
- **A. Data ingestion platform** — pull from external systems, normalize, store
- **B. Knowledge base** — queryable repository with search, browse, explore
- **C. AI context layer** — RAG provider for Foundry agents
- **D. Client intelligence platform** — all of the above + analytics, reports, dashboards
- **E. Something else?**

Current instinct from Tim's direction: "LOTS of use cases can be used as products" → leaning toward D.

### 2. Name

Options from braindump:
- Foundry Knowledge Base
- Foundry Intelligence Hub
- Foundry Client Intelligence
- Foundry Data Bridge
- Foundry Insight Engine
- Something else?

### 3. Who are the consumers?

| Consumer | What they need | Example |
|----------|---------------|---------|
| Human consultant (Tim) | Full dataset query, report generation | Ali meeting briefing |
| Venture CS team (Project Silk China) | Filtered subset, KB articles, playbooks | Chinese client billing guide |
| Foundry agents | RAG context for reasoning | Agent answering "what's the billing status of brand X?" |
| Client CEO (Ali) | Reports, dashboards, metrics | Monthly CS health report |
| Venture CRM (Twenty) | Contact/company sync | Chinese contacts pushed to CRM |
| Ticketing system (Chatwoot) | Ticket migration + context | Zendesk tickets moved with history |

### 4. What connectors are needed?

**Built (proven):**
- Zendesk (tickets, users, orgs, comments)
- HubSpot (contacts, companies, deals, notes/Firefly)

**Next priority:**
- Shopify? Stripe? Amazon Seller Central? Intercom?
- WeChat? (huge for China CS)
- Google Workspace? (docs, sheets)

### 5. Tenant model

- One tenant per venture client? (Wayward = tenant, next client = tenant)
- One tenant per venture? (Project Silk = tenant, all PS clients inside)
- Hierarchical? (Foundry → Shatcher → Project Silk → Wayward)

### 6. Relationship to existing products

This product sits next to (not inside) CRM, Knowledge System, and Memory Service.

### 7. Stage and roadmap

- Stage 1 (internal tool): works for Wayward, Tim can query it
- Stage 2 (platform product): multi-tenant, API, other ventures use it
- Stage 3 (deployable): own service, own CI/CD, external customers

### 8. Build vs buy components

| Component | Build or Use Existing? |
|-----------|----------------------|
| Ingestion/connectors | Build (our connector scripts, evolved) |
| Structured storage | Use existing (PostgreSQL on Railway) |
| Vector storage | Use existing (Pinecone, already in stack) |
| Object storage | Use existing (R2, already in stack) |
| Embedding | Use existing (Qwen3-Embedding-4B local, or cloud) |
| Query API | Build (REST + MCP tools) |
| Natural language query | Build (LLM + RAG pipeline) |
| Dashboard | Use existing (Metabase, already deployed) |
| Tenant isolation | Use existing (D-026 pattern) |

---

## After Vision: Architecture To-Do

Once vision is locked, we design:
1. Data model (tables, schemas, tenant scoping)
2. Connector interface contract (standard every connector follows)
3. Ingestion pipeline (bulk + incremental + webhook)
4. Storage layer (what goes where — PG vs Pinecone vs R2)
5. Query API (REST endpoints + MCP tools)
6. Push/sync model (how subsets get sent to consumers)
7. v1 implementation plan (Wayward as first tenant)
