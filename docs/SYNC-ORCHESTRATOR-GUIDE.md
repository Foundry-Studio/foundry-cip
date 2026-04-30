---
kind: doc
domain: client-intelligence-platform
status: skeleton
last_updated: 2026-04-20
milestone: Phase-1-M0
---

# Sync Orchestrator Guide

> **Status:** skeleton stub — authored Phase 1 M0, populated as Phase 1 milestones land.
> Once final, this guide explains the CIP ingestion pipeline orchestrator — the component that drives a connector through authenticate → stream_records → map → persist → ingest-as-knowledge, and records the run in `cip_sync_runs`.

## Purpose

Describe the orchestrator's responsibilities, control flow, failure modes, and observability hooks — so that an engineer can (a) invoke it for a new connector, (b) extend it for a new object type, and (c) debug a failed sync run.

## Who reads this

- Engineers invoking the orchestrator during tenant onboarding or re-sync.
- Engineers adding new connectors (per `CONNECTOR-AUTHORING-GUIDE.md`).
- Operators debugging `cip_sync_runs` failures.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Creates this skeleton. |
| M2 — Connector framework + FixtureConnector | Populates §2 orchestrator ↔ connector boundary. |
| M3 — Sync orchestrator | Populates the bulk of this guide (§3–§8). |
| M5 — Knowledge + Graph wiring | Populates §7 post-structured knowledge-ingest hook. |

Cross-ref: [`PHASE-1-PLAIN-SPEC.md §3`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md) — `platform/integration-mesh/src/connectors/cip/orchestrator.py`.

## Outline

### 1. Responsibilities

TBD (M3) — what the orchestrator owns (iteration, batching, transactions, sync-run records) vs. what the connector owns.

### 2. Orchestrator ↔ connector boundary

TBD (M2) — the five Protocol methods the orchestrator depends on; nothing else.

### 3. Control flow

TBD (M3) — begin run → authenticate → loop(stream_records → map → persist) → knowledge-ingest hook → end run.

### 4. `cip_sync_runs` row lifecycle

TBD (M3) — states (`started`, `succeeded`, `failed`, `partial`), fields, duration, row counts per object_type.

### 5. Batching + pagination

TBD (M3) — `batch_size`, cursor advancement, incremental vs. full-refresh mode.

### 6. Transaction boundaries

TBD (M3) — per-batch vs. per-record commits, RLS and SET LOCAL within the transaction, retry semantics.

### 7. Knowledge-ingest hook

TBD (M5) — post-persist, per-record invocation of `CIPMapper.ingest_as_knowledge()` and the path into Pinecone + FalkorDB (D-067 non-fatal extraction).

### 8. Failure modes + partial sync

TBD (M3) — connector-auth failure, rate-limit hit, mid-batch DB error, how the orchestrator records a `partial` run.

### 9. Observability

TBD (M3) — logs, metrics, tracing; what a healthy sync looks like vs. what to alert on.

### 10. Idempotency

TBD (M3) — re-running a sync must not duplicate rows; how history tables and `incremental_key` combine to achieve this.
