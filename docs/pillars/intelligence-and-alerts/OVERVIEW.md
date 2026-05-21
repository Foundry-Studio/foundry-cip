<!-- OVERVIEW.md per JOS-S19 -->
---
doc_type: overview
declared_thing: foundry-cip-intelligence-and-alerts
declared_thing_kind: subsystem
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
audience: [dev, product, client]
diataxis_type: explanation
---

# Overview — CIP Pillar 7: Intelligence & Alerts

## What this is

The pillar that turns CIP from a passive data warehouse into a proactive operational signal. Anomaly detection on tenant data (ticket spikes, overdue payments, freshness crossings). Slack alert channel + Metabase freshness signals + scheduled analytical reports. Phase 6 lights this up; Phase 7 adds investigative agents that drill down on signals.

## What's inside

| Feature | Status |
|---|---|
| `anomaly-detection` | planned (Phase 6+) |

1 feature tagged `pillar:intelligence-and-alerts`. Will fan out as Phase 6-7 deliverables land.

## Status

- **Lifecycle:** building (planning only)
- **Maturity:** bronze — Phase 6 hasn't started
- **Health summary:** N/A — nothing shipped yet
- **Last reviewed:** 2026-05-21

## What's NOT here

- **The data the intelligence runs on** → Pillars 2 + 3 (Structured + Unstructured stores)
- **Anomaly visualization** → [Pillar 5 — Consumption Surfaces](../consumption-surfaces/) (Metabase freshness signals)
- **The Slack alert channel itself** → FAS Integration Mesh (Slack is FAS-side)
- **Investigative agents** → Phase 7 deliverable; will live in FAS Agents system, not CIP

## Relationships

- **Parent:** [`foundry-cip`](../../../)
- **Siblings:** Pillars 1-6, 8
- **Cross-references:** depends on Pillars 2 + 3 (data sources); will integrate with FAS Slack alerting

## Where to go next

| Doc | When to open it |
|---|---|
| [`docs/vision/ROADMAP.md`](../../vision/ROADMAP.md) | Phase 6 + Phase 7 shapes |
| [`docs/vision/VISION.md`](../../vision/VISION.md) | §6/§7 — solve-fors for the intelligence pillar |
