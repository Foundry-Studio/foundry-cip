---
id: CIP-SOP-012
uuid: e8fbd279-c6b2-472b-9718-604a0ece37ae
title: Deploying foundry-cip for a New Venture
type: sop
owner: tim
solve_for: 'Procedure for deploying foundry-cip as a library into a new venture''s
  monorepo. Stub; fill_when: Phase 2 M3.'
stage_label: assess
domain: ops
version: '1.0'
created: '2026-04-27'
last_modified: '2026-05-16'
last_reviewed: '2026-05-19'
review_cadence: 180
purpose: Start-to-finish playbook for deploying foundry-cip on behalf of a new venture
  tenant.
fill_when: Phase 2 M3 (Wayward Tenant Provisioning) — the first non-fixture venture
  provisioning IS the trial run; document as it happens.
---

# Deploying foundry-cip for a New Venture

> **Status: stub.** This document fills out at Phase 2 M3 when the first non-fixture venture (Wayward) provisions end-to-end.

## Scope

This runbook covers the operator playbook for taking a venture from "we want CIP for them" → "their data is queryable, dashboards work, alerts fire."

## Outline (TBD — populate as Wayward onboarding is observed)

1. **Pre-deployment checklist** — venture confirmed as a tenant, source-system credentials in hand, target Postgres ready.
2. **Tenant provisioning** — create venture in `tenants` table, run TENANT-ONBOARDING-CHECKLIST.md.
3. **Connector decision** — which connectors does this venture need? Map to existing connectors (HubSpot, Zendesk, Plaid, etc.) or scope a new connector per CONNECTOR-AUTHORING-GUIDE.md.
4. **Initial sync** — first run, expect ramp-up, document any surprises.
5. **Lens definition** — what slices of the data does each consumer team see?
6. **Dashboards + reports** — Metabase setup per consumer.
7. **Sign-off** — venture confirms data quality, dashboards, scheduled reports.
