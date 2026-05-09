---
kind: doc
domain: client-intelligence-platform
status: note
created: 2026-04-06
---

# Industry Research — Knowledge Base / Client Intelligence Products

> Collected 2026-04-06. Sources linked.

---

## Category 1: Customer Data Platforms (CDPs)

**What they are:** Centralized customer data from all touchpoints → unified profiles → real-time personalization.

**Key players:** Segment (Twilio), mParticle, Lytics, Tealium, BlueConic, ActionIQ

**Architecture pattern:**
- Ingest from 100+ sources (APIs, webhooks, SDKs, file uploads)
- Identity resolution (merge duplicates across sources)
- Unified profile per customer
- Audience segmentation and activation (push to downstream tools)
- Real-time event streaming + batch processing

**2026 trends:**
- "Composable CDP" — modular components, not monolithic. Pick the ingestion layer, identity layer, segmentation layer separately.
- AI-native — behavioral prediction, next-best-action, churn scoring built in.
- Privacy-first — consent management, first-party data stewardship, auditable decisions.

**Relevant to us:** The ingestion → normalize → segment → push pattern is exactly what we need. But CDPs are $50K-500K/year enterprise tools. We're building this as a capability, not buying it.

Source: [Luxid Group 2026](https://www.luxidgroup.com/blog/what-to-watch-in-2026-building-a-shared-understanding-of-customer-data-platforms)

---

## Category 2: RAG-Powered Knowledge Bases

**What they are:** Ingest documents → chunk → embed → vector store → retrieve at query time → LLM generates answer.

**Key players:** Guru, Slite, Notion AI, Glean, Dashworks, Kapa.ai (for developer docs)

**Architecture pattern:**
```
Docs/PDFs/Wikis/Tickets → Chunking → Embedding → Vector DB
                                                       ↓
User query → Embed query → Similarity search → Top K chunks → LLM → Answer
```

**Performance data:**
- 40-60% faster resolution times with semantic KB access (vs keyword search)
- Agentic AI (agent + RAG + tools) resolves 70-85% autonomously vs 40-60% RAG-only vs 20-40% chatbot-only

**Relevant to us:** The RAG layer is how agents query the KB. But our product is broader — it's the ingestion + normalization + multi-tenant layer BELOW the RAG, not just the RAG itself.

Sources: [SingleStore RAG guide](https://www.singlestore.com/blog/how-to-build-a-rag-knowledge-base-in-python-for-customer-support/), [Astera KB for RAG](https://wp.astera.com/type/blog/building-a-knowledge-base-rag/), [Parloa enterprise AI](https://www.parloa.com/knowledge-hub/enterprise-ai-customer-support-platforms/)

---

## Category 3: Multi-Tenant Knowledge Management

**What they are:** One platform serves multiple clients/brands with isolated data and branded portals.

**Key players:** Docsie, Document360, Helpjuice, KnowMax, Tettra

**Architecture pattern:**
- Shared infrastructure, per-tenant data isolation
- Branded portals per client
- Role-based access (admin, editor, viewer per tenant)
- Version control and approval workflows
- Analytics per tenant (what articles are most viewed, what's missing)

**Multi-tenant isolation models:**
1. Shared DB, shared schema + tenant_id column (cheapest, D-026 pattern)
2. Shared DB, separate schema per tenant (medium isolation)
3. Separate database per tenant (maximum isolation, most expensive)

**Relevant to us:** The multi-tenant pattern maps directly to our venture model. Each venture client = one tenant. Foundry = super-tenant with cross-tenant visibility.

Source: [Docsie 2026 multi-tenant KB](https://www.docsie.io/blog/articles/multi-tenant-knowledge-base-2026/)

---

## Category 4: Consulting Intelligence Platforms

**What they are:** Tools consultants use to centralize client data, generate insights, and produce deliverables.

**Key players:** Palantir (enterprise), ThoughtSpot (self-service BI), Dataiku (data science), Hex (analytics notebooks)

**Architecture pattern:**
- Pull data from client systems (with their permission/credentials)
- Centralize into a workspace per engagement
- Run analyses (SQL, Python, visual)
- Generate reports and dashboards
- Share insights with client

**Relevant to us:** This is the EcomLever consulting use case. Tim pulls Wayward's data, analyzes it, produces the Ali briefing. The tool should make this repeatable for any consulting client.

---

## What Nobody Does (Our Opportunity)

**Nobody combines all four categories:**
1. CDP-style ingestion from multiple sources
2. RAG-powered semantic query layer
3. Multi-tenant isolation per venture/client
4. Agent-accessible tools (MCP) for AI-powered analysis

The industry has CDPs (expensive, enterprise), RAG KBs (focused on docs, not structured data), multi-tenant KB tools (focused on documentation portals), and consulting platforms (focused on analytics).

**Nobody builds a platform where:**
- An agent can pull a client's Zendesk + HubSpot + Shopify data in one command
- The data is automatically normalized, embedded, and queryable
- Multiple ventures share the platform but see only their clients' data
- A consultant can generate a full operational audit from the centralized KB
- The KB feeds both human dashboards AND agent context (RAG)

**That's the product.**

---

## Comparable Products & Pricing (for positioning)

| Product | What It Does | Pricing | Weakness |
|---------|-------------|---------|----------|
| Segment (CDP) | Customer data ingestion + routing | $120/mo → custom enterprise | Doesn't do RAG or knowledge management |
| Guru | Internal knowledge base + AI search | $15/user/mo | Single-tenant, no multi-source ingestion |
| Glean | Enterprise search across all tools | $10-25/user/mo | Read-only search, no data centralization |
| Document360 | Multi-tenant KB + help portals | $149/mo → custom | Documentation only, no CRM/ticket data |
| Notion AI | Workspace + AI Q&A | $10/user/mo | Not multi-tenant, no external source ingestion |
| Palantir Foundry | Enterprise data platform | $millions | Overkill for venture studio scale |

**Our positioning:** We're not competing with any of these directly. We're building the infrastructure layer that a venture studio needs to serve multiple clients across multiple ventures, with AI agent access built in from day one.
