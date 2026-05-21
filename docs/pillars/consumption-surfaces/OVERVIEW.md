<!-- OVERVIEW.md per JOS-S19 -->
---
doc_type: overview
declared_thing: foundry-cip-consumption-surfaces
declared_thing_kind: subsystem
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
audience: [dev, product, client, agent]
diataxis_type: explanation
---

# Overview — CIP Pillar 5: Consumption Surfaces

## What this is

The many ways CIP's data is consumed — dashboards (humans), REST API (systems), MCP tools (agents), chatbot (conversational), scheduled reports (notifications). M5 shipped Metabase via `cip_metabase_role` + `lens_*` Postgres views — P-21 structurally enforced through the grant matrix: REVOKE on `cip_*` tables, GRANT only on `lens_*` views. M8 fixture-tenant gate PASSED 2026-05-12.

Phase 4 brings the REST API (`/cip/query`, `/cip/search`, `/cip/files`) + MCP tools (`foundry_mcp_cip_*`). Phase 5 brings the chatbot. All of those code surfaces live in **Foundry-Agent-System**, not CIP — CIP exposes the Postgres views + Python query API; FAS wraps them for external consumption.

## What's inside

| Feature | Status | Where |
|---|---|---|
| `metabase-platform-service` | shipped | `cip_metabase_role` + `lens_all_companies` + `lens_eu_west_companies` + `lens_companies_history`; Metabase at `reports.project-silk.com` |
| `rest-api-endpoints` | planned (Phase 4) | FAS-side |
| `mcp-tool-surface` | planned (Phase 4) | FAS-side |

3 features tagged `pillar:consumption-surfaces`.

## Status

- **Lifecycle:** building
- **Maturity:** Metabase silver; REST + MCP + chatbot planned
- **Health summary:** Metabase deployment confirmed working 2026-05-12; awaiting Phase 4 to light up the rest
- **Last reviewed:** 2026-05-21

## What's NOT here

- **The lens definitions** → [Pillar 4 — Lens Engine](../lens-engine/)
- **The underlying tables** → [Pillar 2 — Structured Store](../structured-store/)
- **The REST + MCP code surface** → Foundry-Agent-System (Phase 4 deliverable; CIP exposes the views, FAS wraps the API)
- **The chatbot** → Foundry Chatbot (separate product at `products/foundry-chatbot/`; shares retrieval stack with CIP Phase 5)
- **The auth + tenant routing** → FAS API gateway + actor-identity middleware

## Relationships

- **Parent:** [`foundry-cip`](../../../)
- **Siblings:** Pillars 1-4, 6-8
- **External dependencies:** Foundry-Agent-System for REST, MCP, chatbot deployment surfaces

## Where to go next

| Doc | When to open it |
|---|---|
| [`docs/METABASE-OPERATOR-GUIDE.md`](../../METABASE-OPERATOR-GUIDE.md) | Operator guide for Metabase + cip_metabase_role |
| [`docs/FOUR-ACCESS-PATHS.md`](../../FOUR-ACCESS-PATHS.md) | The 4 read paths CIP exposes |
| FAS `docs/systems/integration-mesh/` | Where the Phase 4 REST + MCP code lands |
