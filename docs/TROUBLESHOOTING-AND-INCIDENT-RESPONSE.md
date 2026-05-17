---
id: CIP-SOP-015
uuid: 4f5516dc-921d-49a6-93f9-703995c4d16e
title: Troubleshooting and Incident Response
type: sop
owner: tim
solve_for: Operator playbook for diagnosing and resolving CIP incidents. Filled incrementally
  as incidents occur.
stage_label: assess
domain: ops
version: '1.0'
created: '2026-04-27'
last_modified: '2026-05-16'
last_reviewed: '2026-05-16'
review_cadence: 90
purpose: 'Incident-response playbook: what fails, how it surfaces, how to recover.'
fill_when: First Phase 2 production incident OR Phase 6 (Intelligence & Alerts), whichever
  first. Stub is updated incrementally as incidents accumulate.
---

# Troubleshooting and Incident Response

> **Status: stub.** This document fills out as real incidents accumulate.

## Scope

Reference for an on-call engineer facing a CIP-related incident. Symptoms → likely causes → recovery procedure.

## Outline (TBD — populated incrementally as incidents happen)

1. **Sync failures** — `cip_sync_runs.status = 'failed'`. Reading `error_detail` JSONB. Re-running.
2. **Schema drift** — connector emits a record the mapper can't handle.
3. **RLS issues** — "I see no rows" surprise. Tracking `app.current_tenant`.
4. **Connection-pool exhaustion** — under multi-tenant load.
5. **Authority bug** — a record landed with `authority='ingested'` when it should be `agent_discovered`.
6. **Knowledge-ingest failures** — Pinecone/FalkorDB write rejected.
7. **Migration rollback** — when to `alembic downgrade`, when to forward-fix.
8. **Multi-repo Alembic chain skew** — foundry-cip and Foundry-Agent-System out of sync.
