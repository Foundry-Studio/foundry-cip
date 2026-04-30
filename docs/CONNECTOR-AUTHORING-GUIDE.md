---
kind: doc
domain: client-intelligence-platform
status: skeleton
last_updated: 2026-04-20
milestone: Phase-1-M0
---

# Connector Authoring Guide

> **Status:** skeleton stub — authored Phase 1 M0, populated as Phase 1 milestones land.
> Once final, this guide is the authoritative reference for writing any new `CIPConnector` + `CIPMapper` pair (Zendesk, HubSpot, Chatwoot, Twenty, Drive, etc.). Phase 1 validates it against FixtureConnector only.

## Purpose

Define the minimum surface area an engineer must implement to bring a new data source onto CIP — `CIPConnector` Protocol, `CIPMapper` Protocol, overflow vs. column decisions, authority flagging, and how to pass the connector-conformance test harness.

## Who reads this

- Any engineer writing a new connector (Phase 2 Zendesk/HubSpot, Phase 2 Chatwoot/Twenty/Drive push, later phases).
- Reviewers validating connector PRs against the binding Protocol shape.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Creates this skeleton. |
| M2 — Connector framework + FixtureConnector | Defines the Protocol and the reference implementation that the guide documents. |
| M6 — Discoverability registry | Populates §6 `describe_schema()` → `cip_connector_property_registry` flow. |

Cross-ref: [`PHASE-1-PLAIN-SPEC.md §4`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md) for the binding Protocol shapes.

## Outline

### 1. Protocol contract

TBD (M2) — signatures of `CIPConnector` and `CIPMapper`; what every connector MUST implement vs. what the orchestrator owns.

### 2. File layout

TBD (M2) — `platform/integration-mesh/src/connectors/cip/<connector>/` subfolder shape, required files.

### 3. `authenticate()`

TBD (M2) — credential resolution, env-var conventions, failure modes.

### 4. `stream_records(cursor, batch_size)`

TBD (M2) — incremental cursor semantics, batch-size policy, rate-limit handling.

### 5. `incremental_key(record)`

TBD (M2) — per-record timestamp extraction, how it feeds the next `cursor`.

### 6. `describe_schema()` → property registry

TBD (M6) — emitting `PropertyDescriptor` rows, column vs. overflow decisions, custom-property flag.

### 7. `CIPMapper.map(record)`

TBD (M2) — record → `CIPRow` emission, multiple rows per record, history-row generation.

### 8. Authority selection

TBD (M2) — when to use `ingested` (default for connector-sourced data) vs. `agent_discovered` vs. `validated`.

### 9. `ingest_as_knowledge(record)`

TBD (M5) — which text fields flow into Knowledge ingestion, chunking implications.

### 10. Rate-limit policy

TBD (M2) — `RateLimitPolicy` shape, backoff, connector-specific quirks.

### 11. Passing the conformance harness

TBD (M2) — `tests/fixtures/connector_conformance/` protocol tests every connector must pass before merge.

### 12. Reference implementation: FixtureConnector

TBD (M2) — walkthrough of the reference connector, how to copy-and-adapt for real sources.
