---
status: stub
purpose: "Bare-minimum integration guide for an external developer using foundry-cip without Foundry's runtime."
owner: tim
created: 2026-04-27
fill_when: "First external (non-Foundry) consumer expresses interest, OR foundry-cip's first PyPI release (whichever first)."
---

# Standalone Integration Guide

> **Status: stub.** This document fills out once foundry-cip has been adopted by at least one external (non-Foundry) deployment.

## Scope

You're a developer outside Foundry. You want to use foundry-cip's connector framework + schema in your own deployment, against your own Postgres, with your own LLM provider.

## Outline (TBD)

1. **Install** — `pip install foundry-cip`, set DATABASE_URL, run alembic.
2. **Tenant model** — choosing how `tenant_id` maps to your domain.
3. **First connector** — copy a generic connector (HubSpot or fixture) and adapt.
4. **Knowledge ingestion (optional)** — wire `ingest_as_knowledge` to your own embedding store.
5. **Consumption** — query the cip_* tables directly via SQL or layer your own API.
