---
doc_type: overview
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
---
<!-- OVERVIEW.md per JOS-S19 -->
---
doc_type: overview
declared_thing: foundry-cip-ingestion-and-connectors
declared_thing_kind: subsystem
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
audience: [dev, product, agent]
diataxis_type: explanation
connects_to:
  - _manifest.yaml
  - ../../../features.yaml
  - ../../../OVERVIEW.md
  - ../../CONNECTOR-AUTHORING-GUIDE.md
---

# Overview — CIP Pillar 1: Ingestion & Connectors

## What this is

The framework that lets CIP pull a client's data from any external source — CRM, support, financial, documents — into the structured store. Connectors implement two Protocols (`CIPConnector` for streaming records, `CIPMapper` for translating to the cip_* schema). The sync orchestrator wraps them with advisory-lock dual-run prevention, batched transactions, and post-commit RLS assertions.

Mandatory historical backfill per D-159: every connector pulls source-system history (HubSpot 20-rev window, Zendesk audit log, etc.) on first sync and synthesizes `cip_*_history` rows. Delay = permanent loss.

## What's inside

| Feature | Status | Code |
|---|---|---|
| `connector-framework` | shipped | `cip.integration_mesh.orchestrator` |
| `fixture-connector` | shipped (gold) | `cip.integration_mesh.connectors.fixture` |
| `hubspot-connector` | shipped | `cip.integration_mesh.connectors.hubspot` |
| `zendesk-connector` | shipped | `cip.integration_mesh.connectors.zendesk` |
| `plaid-connector` | planned | (Phase 2+) |
| `historical-backfill` | shipped | `cip.integration_mesh.base.HistoricalRecord` |
| `connector-conformance-harness` | shipped (gold) | `tests/fixtures/connector_conformance/` |

7 features tagged `pillar:ingestion-and-connectors` in [`features.yaml`](../../../features.yaml).

## Status

- **Lifecycle:** operating
- **Maturity:** silver-to-gold — framework + harness gold; HubSpot/Zendesk silver awaiting Wayward real-tenant run
- **Health summary:** 44/44 connector tests pass; mypy --strict clean; ruff clean
- **Last bug-bash:** 2026-05-14 (4 fixes + 4 regression tests after HubSpot/Zendesk overnight run)
- **Last reviewed:** 2026-05-21

## What's NOT here

- **The Postgres tables** → [Pillar 2 — Structured Store](../structured-store/)
- **The KnowledgeText emission to FAS** → [Pillar 3 — Unstructured Store](../unstructured-store/)
- **The lens views over ingested data** → [Pillar 4 — Lens Engine](../lens-engine/)
- **Consumption surfaces** → [Pillar 5 — Consumption Surfaces](../consumption-surfaces/)
- **Outbound push (write-back)** → [Pillar 6 — Push & Sync](../push-and-sync/)

## Relationships

- **Parent:** [`foundry-cip`](../../../)
- **Siblings:** Pillars 2-8
- **Children:** none (concrete connectors live as features, not subsystems)
- **Cross-references:** depends on Structured Store + Access & Operations; referenced by Unstructured Store

## Where to go next

| Doc | When to open it |
|---|---|
| [`docs/CONNECTOR-AUTHORING-GUIDE.md`](../../CONNECTOR-AUTHORING-GUIDE.md) | How to add a new CIP connector |
| [`docs/HUBSPOT-CONNECTOR-GUIDE.md`](../../HUBSPOT-CONNECTOR-GUIDE.md) | HubSpot connector specifics |
| [`docs/ZENDESK-CONNECTOR-GUIDE.md`](../../ZENDESK-CONNECTOR-GUIDE.md) | Zendesk connector specifics |
| [`docs/PROPERTY-GLOSSARY-PATTERN.md`](../../PROPERTY-GLOSSARY-PATTERN.md) | Per-connector property registry pattern |
