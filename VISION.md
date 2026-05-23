---
doc_type: vision
elaborates_slot: lifecycle
declared_thing: foundry-cip
declared_thing_kind: product-internal
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
vision_horizon: "2027-05"
review_cadence: 180
audience: [strategist, stakeholder, leadership, agent]
diataxis_type: explanation
d_numbers: [D-117, D-118, D-119, D-120, D-121, P-21]
---

# Vision — Foundry Client Intelligence Platform (CIP)

> **JOS-canonical entry point for CIP's product vision.**
> Per JOS-D0054 + JOS-S28, this file elaborates the Lifecycle slot for the foundry-cip product root.
>
> **The authoritative vision is [`docs/vision/VISION.md`](docs/vision/VISION.md)** — 473-line product vision covering the problem, the three data layers, the eight pillars, the tenant model, and the 10-section deep dive. This root file is a JOS-shaped index pointing at it.

## North star

**By 2027-05, Foundry-Studio onboards a client's data once and serves it everywhere — dashboards, reports, chatbots, agents, partner portals.** The second tenant onboards in an hour; the tenth in minutes. CIP is the framework that makes "we know what's happening with this client" a structural property of every Foundry-Studio engagement, not a manual session.

## Horizon

**2027-05** (12 months out from 2026-05-21). Beyond that, the cross-tenant intelligence (Phase 7) opens new directional questions; vision will re-baseline then.

## What "full strength" looks like at the horizon (summary)

1. **Multi-tenant in production** — at least Wayward + Rocky Ridge + Foundry self-tenant operating concurrently, each with their own lenses, dashboards, chatbots, write-back surfaces.
2. **Connector inventory** — HubSpot + Zendesk shipped + battle-tested; Plaid (financial) + Chatwoot + Google Drive landing through Phase 2-2.5.
3. **All 8 pillars at silver-or-better** — Phase 6 lights up Intelligence & Alerts; Phase 7 turns on investigative agents and chatbot-initiated writes.
4. **Self-service onboarding** — `docs/DEPLOYING-FOUNDRY-CIP-FOR-A-NEW-VENTURE.md` is the canonical path; no Tim-in-the-loop required for tenants 2-N.

The 473-line [`docs/vision/VISION.md`](docs/vision/VISION.md) elaborates §6 (current stage), §7 (architecture sketch), §10 (10-phase roadmap), and the full solve-for surface.

## What we need to solve for (summary)

Per the full vision:
1. **Phase 2 first real-tenant proof** — Wayward Onboarding (HubSpot + Zendesk + push to Chatwoot/PS CRM/Drive) closes the round-trip loop.
2. **Authority model + write-back** — Phase 2.5 ships `cip_write()` across REST/MCP/Python surfaces with the three-tier authority model (`agent_discovered` / `ingested` / `validated`).
3. **Cross-tenant grants runtime** — Phase 3 ships `cip_09_cross_tenant_grants` schema + runtime together (deferred from Phase 1 explicitly so they ship as a unit).
4. **Agent access surface** — Phase 4 ships `foundry_mcp_cip_query` / `_search` / `_files` + REST parallels.
5. **Chatbot capability** — Phase 5 ships the internal chatbot pattern (grounded, lens-aware, grant-aware, citations mandatory).
6. **Intelligence & Alerts pillar** — Phase 6 lights up anomaly detection + freshness signals + scheduled analytical reports.

See [`docs/vision/VISION.md` §6-7](docs/vision/VISION.md) for the full problem surface.

## Locked decisions (append-only)

| Decision | What it locks for vision |
|---|---|
| **D-117** 8 CIP capability pillars locked as durable scopes | Pillar structure is durable; phase sequencing is what changes |
| **D-118** CIP connectors live inside Integration Mesh | Framework code shape; Zendesk/HubSpot are the first instances |
| **D-119** CIP Unstructured Store consumes FAS Knowledge + Graph subsystems | Vector/graph storage strategy; CIP doesn't own its own retrieval stack |
| **D-120** Three Data Layers (Originals + Derived Knowledge + Structured) | Data model is canonical across every venture; no per-tenant data-shape negotiation |
| **D-121** Discoverability — every CIP artifact gets a registry entry queryable by agents | Agent-readiness is structural, not aspirational |
| **D-146** foundry-cip is a separate repo; FAS consumes via pip | Library shape vs service; library publishing is the distribution model |
| **D-159** Mandatory historical backfill on every connector | First sync captures source history (HubSpot 20-rev window, Zendesk audit log) |
| **P-21** Multi-Lens by Default | Every data surface assumes N consumers with N filter configs |

## Non-goals (what we are NOT trying to become)

- **Not a general-purpose CDP.** Foundry-Studio is the only customer; selling CIP standalone is not on the horizon path.
- **Not a service.** CIP is a Python library + schema; consumers (FAS, future products) host the runtime.
- **Not a multi-vendor abstraction layer.** Pinecone + R2 + Postgres are pinned via FAS; cloud portability is not on the horizon.
- **Not a customer-facing product.** All consumption goes through Foundry-Studio venture surfaces (Wayward portal, partner portals); CIP itself is operator-internal.
- **Not the chatbot product.** Foundry Chatbot was spun out to `products/foundry-chatbot/` (separate product, blocked by CIP Phase 5).

## Origin

CIP began as the **Wayward engagement pattern**: pull external client data, centralize it, serve dashboards + chatbots + agent context. The April 2026 SQLite proof-of-concept (153,588 records from Zendesk + HubSpot in one Claude Code session) proved the pattern; CIP turns it into a product so the **second** client engagement doesn't start from zero.

Phase 0 (Data Model & Tenant Architecture) locked the foundation 2026-04-17 (8 architecture decisions). Phase 1 (Plain-Jane + Doc Suite) closed 2026-05-12 with M0-M8 milestones all green. Phase 2 (Wayward Onboarding — Full Round-Trip) is the current build-out.

## Connected JOS substrate

- **JOS-D0054** Doc-Types Elaborate Boundary Contract Slots
- **JOS-S28** VISION.md Doc Standard (the conformance shape)
- **JOS-D0050** Features as First-Class Discovery Layer (CIP's `features.yaml` implements this)

---

_This root-level file is a JOS-shaped index. Authoritative vision: [`docs/vision/VISION.md`](docs/vision/VISION.md)._


## Last reviewed

_TODO: author this section per the doc-standard._

