---
id: CIP-SOP-014
uuid: 390d7cc9-a473-494d-9c83-6757955d8bff
title: Standalone Integration Guide
type: sop
owner: tim
solve_for: 'Guide for consuming foundry-cip from a non-Foundry codebase. Stub; fill_when:
  external consumer / PyPI.'
stage_label: assess
domain: eng
version: '1.0'
created: '2026-04-27'
last_modified: '2026-05-16'
last_reviewed: '2026-05-16'
review_cadence: 180
purpose: Bare-minimum integration guide for an external developer using foundry-cip
  without Foundry's runtime.
fill_when: First external (non-Foundry) consumer expresses interest, OR foundry-cip's
  first PyPI release (whichever first).
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
