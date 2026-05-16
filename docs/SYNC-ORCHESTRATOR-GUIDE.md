---
kind: doc
domain: client-intelligence-platform
status: draft
last_updated: 2026-05-16
milestone: Phase-1-M7
---

# Sync Orchestrator Guide

> **Status:** draft — M2 orchestrator live 2026-05-05; M7 read-through 2026-05-11 corrected the §Related M5 row (M5 was Metabase platform service, NOT Knowledge+Graph wiring — wiring lives in the monorepo platform service per `docs/FOUR-ACCESS-PATHS.md` §§2-3). Sections §§1–6, 8–10 populated; §7 documents the M2 stub contract that foundry-cip owns. **2026-05-16: backfill flush path rewired to use batched persister INSERT (one round trip per ~200-record flush instead of ~400 per flush); per-record SAVEPOINT fallback retained for cascade safety. See §11.**
> This guide explains the CIP ingestion pipeline orchestrator — the component that drives a connector through `authenticate → stream_records → map → persist → ingest_as_knowledge` and records the run in `cip_sync_runs`.

## Purpose

Describe the orchestrator's responsibilities, control flow, transaction boundaries, failure modes, and observability hooks — so an engineer can (a) invoke `run_sync()` for a new connector, (b) reason about transaction-rollback / cursor-advance / counter-mapping behavior, and (c) debug a failed `cip_sync_runs` row.

## Who reads this

- Engineers invoking `run_sync()` during tenant onboarding or scheduled re-sync.
- Engineers adding new connectors (per [`CONNECTOR-AUTHORING-GUIDE.md`](CONNECTOR-AUTHORING-GUIDE.md)).
- Operators debugging `cip_sync_runs` failures from `error_detail` JSONB and structured logs.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Created the original skeleton. |
| M2 — Connector framework + orchestrator + harness | Populates this guide §§1–6, 8–10 (current). |
| M5 — Metabase platform service | Read-side consumption; orthogonal to the orchestrator. Knowledge+Graph wiring (the original §7 deferral target) is a monorepo platform-service concern, NOT a foundry-cip milestone. The orchestrator's `ingest_texts_noop` hook stays a no-op in foundry-cip; the monorepo service replaces it. |
| M7 — Four Access Paths Validation + Doc Suite Harden | M5 row correction in this guide. |

Cross-ref: [`PHASE-1-PLAIN-SPEC.md §3`](vision/PHASE-1-PLAIN-SPEC.md) for the orchestrator contract; [`CONNECTOR-AUTHORING-GUIDE.md`](CONNECTOR-AUTHORING-GUIDE.md) for the connector side; [`RLS-SET-LOCAL-OPERATOR-GUIDE.md`](RLS-SET-LOCAL-OPERATOR-GUIDE.md) for the tenant-scoping contract the orchestrator depends on.

---

### 1. Responsibilities

The orchestrator is a single function (`run_sync`, [`cip/integration_mesh/orchestrator.py`](../cip/integration_mesh/orchestrator.py)) plus internal helpers. It is **stateless across calls** — every invocation builds fresh `TokenBucket`, `SCDDiffer`, and `SyncRunRecorder` instances.

**The orchestrator OWNS:**

- Iteration over `connector.stream_records()` (called exactly once per run, per H-10).
- Local chunking of yielded records into batches of `batch_size`.
- Per-batch transaction boundaries (one txn per batch via `with Session(engine, …) as db, db.begin():`).
- Tenant-context application via `apply_tenant_context()` at every txn start.
- SCD-2 diff decision via `SCDDiffer` (delegated, not in `run_sync` itself).
- Cursor advancement — written inside the same transaction as the batch's row writes (atomic).
- `cip_sync_runs` audit row lifecycle via `SyncRunRecorder` (INSERT at `__enter__`, UPDATE at `__exit__`).
- Knowledge-hook metadata finalization + boundary validation + dispatch to `ingest_texts_noop`.
- Rate-limit pacing (`bucket.acquire()` before each batch) + retry budget (`MAX_BATCH_RATE_LIMIT_RETRIES`).
- Consecutive-failure abort (`MAX_CONSECUTIVE_BATCH_FAILURES = 3`).
- Run-fatal exception routing (AuthenticationError, TimezoneNaiveError, KnowledgeMetadataValidationError → propagate).

**The connector OWNS:**

- Source-API interaction (HTTP, OAuth, pagination tokens).
- Record shape (the dict yielded from `stream_records`).
- `incremental_key()` extraction.
- `RateLimitPolicy` declaration.
- `cursor_safety_window_seconds` declaration.

**The mapper OWNS:**

- Record → `CIPRow` shape (which columns, which overflow).
- `SchemaDriftError` raises for unknown source fields.
- `KnowledgeText` extraction (with the `source_id` mandatory contract).

The contract is narrow: orchestrator depends on **exactly seven** Protocol members across the two Protocols (`authenticate`, `stream_records`, `describe_schema`, `incremental_key`, `rate_limit_policy`, `cursor_safety_window_seconds`, plus mapper's four methods). Anything else a connector or mapper does is connector-private.

---

### 2. Orchestrator ↔ connector boundary

The seven members the orchestrator depends on:

```
CIPConnector:
  - connector_id: str                                    # attribute
  - tenant_id: UUID                                      # attribute
  - authenticate() -> None
  - stream_records(cursor, batch_size) -> Iterator[dict]
  - describe_schema() -> list[PropertyDescriptor]
  - incremental_key(record) -> datetime                  # tz-aware
  - rate_limit_policy: RateLimitPolicy                   # @property
  - cursor_safety_window_seconds: int                    # @property

CIPMapper:
  - object_type: str                                     # attribute
  - target_table: str                                    # attribute
  - map(record) -> Iterable[CIPRow]
  - overflow_fields() -> list[str]
  - authority() -> Literal["agent_discovered","ingested","validated"]
  - ingest_as_knowledge(record) -> list[KnowledgeText]
```

`validate_connector_shape()` ([`cip/integration_mesh/validation.py`](../cip/integration_mesh/validation.py)) checks all of these at orchestrator entry. Failures raise `ProtocolShapeError` (subclass of `TypeError`) — entry-shape failures propagate to the caller with **zero DB rows touched** (no `cip_sync_runs` row written). This is intentional: an entry-shape failure is a caller bug, not a run failure.

---

### 3. Control flow

```
run_sync(connector, mapper, engine, *, tenant_id, ...) -> SyncRunState
  │
  ├─ validate_connector_shape(connector, mapper)        # ProtocolShapeError on failure
  ├─ bucket = TokenBucket(connector.rate_limit_policy)
  ├─ differ = SCDDiffer()
  ├─ recorder = SyncRunRecorder(engine, tenant_id, ...)
  │
  └─ with recorder as run:                              # INSERT cip_sync_runs status='running'
       ├─ connector.authenticate()                      # AuthenticationError on failure
       ├─ _register_properties_best_effort(...)         # non-fatal
       ├─ adjusted_cursor = _apply_safety_window(cursor, window)
       │
       └─ with contextlib.closing(record_iter):         # PATCH-NR-2 generator close
            for raw_batch in _chunked(stream_records(...), batch_size):
              while not batch_committed:               # H-6 retry loop
                bucket.acquire()                       # rate-limit pace
                batch = _dedupe_by_source_id(raw_batch)
                with Session(engine, autoflush=False) as db, db.begin():
                  apply_tenant_context(db, tenant_id)  # SET LOCAL via set_config
                  persister = CIPRowPersister(db, differ)
                  for rec in batch:
                    rows = list(mapper.map(rec))       # SchemaDriftError → skip
                    for row in rows:
                      persister.persist(row, ...)      # PersistenceError → batch rollback
                    _run_knowledge_hook(connector, mapper, run, rec, tenant_id)
                    incremental_key advance for batch_latest_key
                  cursor_state UPDATE inside same txn  # C-4 atomic
                # db.begin() commits on normal exit
              consecutive_batch_failures handling (3-strike abort)
  │
  └─ with recorder: exited                             # UPDATE cip_sync_runs status + counters
  return _finalize(recorder)                           # SyncRunState built post-exit
```

**Key orderings:**

- `validate_connector_shape` runs BEFORE recorder enter. Entry-shape failures don't write a sync_run row.
- `authenticate()` runs INSIDE the `with recorder:` block. Auth failures DO write a sync_run row with `status='failed'` and `error_detail.type='AuthenticationError'`.
- `_register_properties_best_effort` is a separate Session (not the per-batch one) so a registry write failure can't poison later batches.
- `stream_records()` is called **once** (per H-10). The orchestrator chunks; the connector pages.
- Per-batch: dedupe → persist domain rows → knowledge hook → advance cursor. All in one txn.
- `_finalize()` runs AFTER `with recorder:` exits (per v3 R2-A2) so it reads `recorder.final_status` and `recorder.final_ended_at` set by `__exit__`.

---

### 4. `cip_sync_runs` row lifecycle

The `SyncRunRecorder` ([`cip/integration_mesh/sync_run_recorder.py`](../cip/integration_mesh/sync_run_recorder.py)) owns the row.

**`__enter__`:** opens its own short-lived `engine.begin()` connection, applies tenant context, INSERTs the row with `status='running'`. The row is **immediately observable** — operators can `SELECT … WHERE status='running'` to watch a sync in progress.

**`__exit__`:** opens a fresh `engine.begin()` connection, applies tenant context, UPDATEs status + counters + `ended_at`. **Status transitions:**

- `success` → no exception, no `error_detail` set during the run.
- `partial` → no exception, but at least one batch wrote `error_detail` (e.g., a `PersistenceError` that didn't trip the 3-consecutive abort).
- `failed` → an exception escaped the `with recorder:` block (AuthenticationError, TimezoneNaiveError, KnowledgeMetadataValidationError).

The recorder NEVER shares a connection with the orchestrator's per-batch `Session` — both write paths are independent. This is intentional (v3 R2-A1): a recorder write failure can't roll back persister writes, and vice versa.

**Deployed-row counter columns (Delta 1 reconciliation):** the recorder collapses the in-memory granular 7-counter set to the deployed 5-column set at write time:

| Deployed column | Source (in-memory granular) |
|---|---|
| `rows_ingested` | `rows_created + rows_updated` |
| `rows_history` | `rows_history` (1:1) |
| `rows_created` | `rows_created` (1:1) |
| `rows_updated` | `rows_updated` (1:1) |
| `rows_skipped` | `rows_skipped_unchanged + rows_skipped_drift + rows_skipped_duplicate` |

The granular 7 stay available in-memory for structured logging — the `SyncRunState` dataclass returned from `run_sync()` exposes all seven. M3+ may add a migration to expose the split if telemetry needs it.

**`cursor_state` is OWNED by the orchestrator, not the recorder** (PATCH-Q4). The recorder's `__exit__` UPDATE explicitly EXCLUDES `cursor_state` from its SET clause. The orchestrator writes `cursor_state` per batch inside the batch transaction (§5 below).

**Other row fields:**

- `id` (PK), `batch_id` (UUID4, UNIQUE per run).
- `tenant_id`, `client_id`, `connector_id`, `connector_name`, `sync_mode`.
- `started_at` (set at `__enter__`), `ended_at` (set at `__exit__`).
- `error_detail` JSONB (PII-redacted via `_redact()`; emails masked).
- `metadata` JSONB (defaults to `'{}'`; reserved for future Phase 2 telemetry).

---

### 5. Batching + pagination

**Default `batch_size = 500`**. Caller can override; the orchestrator chunks at this granularity.

**Cursor advancement:** the orchestrator computes the maximum `incremental_key` seen across all records in a batch, then writes:

```sql
UPDATE cip_sync_runs
SET cursor_state = CAST(:c AS jsonb)
WHERE id = :run_id
```

inside the **same transaction** as the batch's row writes. If the batch txn rolls back (e.g., `PersistenceError`), cursor advancement rolls back with it. Either the entire batch is committed (rows + cursor advance) or nothing is. This is the C-4 atomicity guarantee.

**Cursor shape:** `{"last_incremental_key": "<ISO-8601 tz-aware>"}`. The orchestrator stores it as JSONB; the connector reads it from the `cursor` arg to `stream_records()`.

**Cursor safety window (H-13 / Delta-aware):** before passing the stored cursor to `connector.stream_records()`, the orchestrator rewinds it by `cursor_safety_window_seconds` (default 300s). This absorbs clock skew + replica lag at the source — records written to the source DB just before our previous cursor's instant but only visible after our previous sync completed get re-emitted on the next run. The persister's SCD-2 diff catches duplicates (`rows_skipped_unchanged += 1`); no double-write risk.

**Full vs. incremental mode:**

- `sync_mode="incremental"` (default): cursor passed to connector; only post-cursor records flow.
- `sync_mode="full"`: cursor forced to `None` regardless of caller's `initial_cursor`. Connector does a full pull. Useful for bootstrap, drift-recovery, or operator-initiated rebuilds.

---

### 6. Transaction boundaries

**One Postgres transaction per batch.** Pattern:

```python
with Session(engine, autoflush=False, expire_on_commit=False) as db, db.begin():
    apply_tenant_context(db, tenant_id)
    # ... persister + knowledge-hook + cursor advance ...
# db.begin() context commits on normal exit, rolls back on exception
```

**Why per-batch (not per-record, not per-run):**

- Per-record: too many round trips; transaction overhead dominates throughput.
- Per-run: massive transactions, WAL pressure, no partial-progress recovery.
- Per-batch: industry standard. On batch failure, the batch rolls back and earlier batches persist; orchestrator records `status='partial'` and the next run resumes from the last successful batch's cursor.

**Tenant context inside the txn:** `apply_tenant_context()` sets `app.current_tenant` GUC via `SELECT set_config('app.current_tenant', :t, true)` (Delta 14: NOT `SET LOCAL` — Postgres doesn't accept bind parameters there; `set_config(..., true)` is the parameter-safe transaction-local equivalent). Every `cip_*` table's RLS policy `cip_tenant_scope` reads this GUC; without the call, no rows are visible.

**`autoflush=False, expire_on_commit=False`** (v4 Round-3 panel HIGH): per-batch Session is short-lived; autoflush adds surprise mid-batch implicit-flush deadlock risk for no benefit; `expire_on_commit=False` avoids touching ORM cache on commit.

**`FOR UPDATE` row-locks + `ORDER BY source_id`** (v4 CRIT-2): the persister's SCD lookup uses `SELECT … FOR UPDATE` to prevent lost-update races between concurrent batches. The orchestrator's `_dedupe_by_source_id` keeps records sorted; combined with persister's `ORDER BY source_id`, concurrent batches acquire row locks in the same order — preventing the deadlock class entirely. (Advisory-lock dual-run prevention is deferred to M3.)

**RLS connection-checkout listener (PATCH-NR-1):** every Engine in M2+ deployments SHOULD register a `event.listens_for(engine, "checkout")` listener that issues `SELECT set_config('app.current_tenant', '', false)` on every checkout. Belt-and-suspenders to the explicit `apply_tenant_context()` calls — even if a future code path forgets to set tenant context, the GUC is empty (RLS denies all rows) rather than carrying stale state from a prior caller. The conformance harness's `seeded_engine` fixture (`tests/fixtures/connector_conformance/conftest.py`) demonstrates the pattern.

---

### 7. Knowledge-ingest hook

**Status (M7 read-through):** Real Pinecone + FalkorDB ingestion is a **monorepo platform-service concern**, NOT a foundry-cip milestone (earlier-draft pointer attributed this to M5; M5 was the Metabase platform service). foundry-cip's `ingest_texts_noop` stays a no-op stub; downstream consumers wire the real ingestion in the monorepo. Read `docs/FOUR-ACCESS-PATHS.md` §§2-3 for the consumer-side surface.

**Deployed contract (what foundry-cip owns):**

For every record processed in a batch, AFTER the persister has written domain rows AND BEFORE the next record begins, the orchestrator runs the knowledge-hook flow:

1. `mapper.ingest_as_knowledge(record)` returns `list[KnowledgeText]`.
2. Orchestrator finalizes metadata for each text:
   - **Detect-then-assign** for orchestrator-owned keys (`tenant_id`, `ingestion_batch_id`): if the mapper emits a value that doesn't match the run's binding, raise `KnowledgeMetadataValidationError` (run-fatal).
   - **`setdefault`** for mapper-may-know-better keys (`source_system`, `connector_version`, `extracted_at`): mapper-emit wins; orchestrator falls back to defaults if absent.
   - `extracted_at` is **hoisted** outside the per-text loop — all texts from one record share one `extracted_at` timestamp (cleaner semantic; per-record granularity).
3. `validate_knowledge_text_metadata(md, where=...)` runs at the boundary. Raises `KnowledgeMetadataValidationError` (missing required key) or `TimezoneNaiveError` (tz-naive datetime).
4. `ingest_texts_noop(finalized_texts)` runs once per record (M2 stub; M5 wires the real call).

**Fatal vs. non-fatal:**

- `KnowledgeMetadataValidationError` and `TimezoneNaiveError` are **run-fatal**. Re-raised; batch txn rolls back; recorder records `status='failed'`; exception propagates to caller.
- Any other Exception from `ingest_texts_noop` (or, in M5, the real ingest) is **non-fatal** per D-067. Logged at WARNING; the run continues; the record's domain row was already persisted (or skipped) by the persister BEFORE the knowledge hook ran, so domain ingestion is unaffected.

**M5 swap-in:** the body of `ingest_texts_noop` becomes the real Knowledge+Graph write path. The Protocol shape (`list[KnowledgeText]` in, `None` out, non-fatal exceptions allowed) does NOT change. The validator + finalize logic in the orchestrator does NOT change. M5 work is purely the hook body.

---

### 8. Failure modes + partial sync

| Failure | Where | Orchestrator behavior |
|---|---|---|
| Invalid Protocol shape | `validate_connector_shape` at entry | `ProtocolShapeError` propagates; **no `cip_sync_runs` row written** |
| Bad credentials | `connector.authenticate()` | `AuthenticationError` re-raised; recorder writes `status='failed'`; run-fatal |
| Source rate limit (429) | `connector.stream_records()` raises `RateLimitExceeded` | Sleep `min(retry_after, 300s)`; retry same batch (up to 3 retries); after 3 failed retries, count as 1 consecutive batch failure |
| 3 consecutive batch failures | rate-limit-exhaustion or persister | `aborted=True`; recorder writes `status='partial'` with `error_detail` |
| `SchemaDriftError` from `mapper.map(rec)` | per record | `rows_skipped_drift += 1`; log WARNING; continue to next record |
| `PersistenceError` from persister | per batch | Batch txn rolls back; `consecutive_batch_failures += 1`; `error_detail` updated; if 3 consecutive, abort with `status='partial'` |
| `TimezoneNaiveError` from `incremental_key()` or stored cursor | per record / at safety-window | Re-raised; recorder writes `status='failed'`; run-fatal |
| `KnowledgeMetadataValidationError` from validator | per record (knowledge hook) | Re-raised; batch txn rolls back; recorder writes `status='failed'`; run-fatal |
| Non-validation knowledge-hook exception | per record (knowledge hook) | Logged WARNING; batch continues; **non-fatal per D-067** |
| Recorder finalize UPDATE fails | `__exit__` UPDATE itself raises | Logged ERROR; cip_sync_runs row stays `status='running'` (operator triage); original exception (if any) NOT swallowed |

**Partial sync semantics:** records that were successfully persisted in earlier (committed) batches stay durably written even when a later batch fails. The cursor advanced for those batches stays advanced — the next run picks up from the last successful batch. Operators can re-run with the same `tenant_id` to resume.

**Observability of failures:** `cip_sync_runs.error_detail` JSONB carries `{"type": "<ExceptionClass>", "message": "<redacted>"}`. PII redaction (emails) is applied via `_redact()`. Long messages are truncated at 2000 chars.

---

### 9. Observability

**Structured logs** (Python `logging` module, logger name `cip.integration_mesh.orchestrator`):

| Level | When |
|---|---|
| DEBUG | Per-batch: dedupe drops, persister diff results, cursor advance value |
| INFO | Authentication success, run start/end |
| WARNING | SchemaDriftError (per record), RateLimitExceeded retries, knowledge-hook non-fatal exceptions, registry write failures, stream-records `incremental_key` extraction failures |
| ERROR | PersistenceError, 3-consecutive-failure abort, recorder finalize UPDATE failures |

Configure your application's logging level on `cip.integration_mesh.*` to control verbosity. Production deployments typically filter at INFO; debugging a stuck sync runs at DEBUG.

**Primary operational artifact: `cip_sync_runs`.** Every run produces exactly one row. Operators query:

```sql
-- Recent run summary for a tenant
SELECT id, started_at, ended_at, status,
       rows_ingested, rows_skipped, rows_history,
       error_detail
FROM cip_sync_runs
WHERE tenant_id = :tenant_id
ORDER BY started_at DESC
LIMIT 10;

-- In-flight runs (sit at status='running' if not yet finalized)
SELECT id, connector_id, started_at, batch_id
FROM cip_sync_runs
WHERE tenant_id = :tenant_id
  AND status = 'running'
ORDER BY started_at;

-- Most recent failures
SELECT id, started_at, status, error_detail->>'type' AS err_type,
       error_detail->>'message' AS err_msg
FROM cip_sync_runs
WHERE tenant_id = :tenant_id
  AND status IN ('failed', 'partial')
ORDER BY started_at DESC
LIMIT 25;
```

**Cursor advance audit:** `cip_sync_runs.cursor_state` JSONB. Inspecting `cursor_state->>'last_incremental_key'` shows where the next incremental run will resume.

**M2 does NOT export to Grafana / OTel / Prometheus.** Phase 2 may add an exporter; the structured-logs + `cip_sync_runs` SELECT pattern is the M2 observability surface.

---

### 10. Idempotency

**Re-running the same sync MUST NOT produce duplicate rows.** The framework guarantees this via:

1. **Source-id uniqueness:** every `cip_*` domain table has a UNIQUE constraint on `(tenant_id, client_id, source_connector, source_id)`. `client_id` may be NULL; `source_id` may be NULL on `cip_files` (handled via `IS NOT DISTINCT FROM` lookup — Delta 6).
2. **SCD-2 lookup-then-update:** the persister's `SELECT FOR UPDATE` on `(tenant_id, source_connector, source_id IS NOT DISTINCT FROM :sid)` finds the existing row; if the diff says unchanged, only `refreshed_at` is bumped (`rows_skipped_unchanged`); if changed, the old state is archived to history and the current row is UPDATEd in place.
3. **Cursor + safety window:** records re-emitted by the cursor safety window (records that were already persisted in a prior run) hit the SCD-2 lookup, get diffed identical, and are correctly counted as `rows_skipped_unchanged` — no domain mutation, no duplicate row.
4. **Intra-batch dedupe** (`_dedupe_by_source_id`): if the same `source_id` appears multiple times in one batch (legitimate at API page boundaries), only the LAST occurrence is persisted (last-write-wins for SCD-2). Earlier occurrences are counted as `rows_skipped_duplicate`.

**History tables are intentionally non-idempotent.** Each genuine domain mutation creates one new history row. Re-running a sync against unchanged source data produces zero new history rows. Re-running after a real source mutation produces one history row per mutation. This is correct: history is the audit trail of changes, not a deduplicated set.

**`batch_id` is unique per run** (UUIDv4). The orchestrator does NOT dedupe against prior `batch_id`s — concurrent runs on different processes get different batch_ids by construction. Phase 3's advisory-lock dual-run prevention will close the at-most-one-concurrent-run-per-(tenant,connector) gap; M2 relies on caller-side coordination.

---

### 11. Backfill flush — batched insert with per-record SAVEPOINT fallback (added 2026-05-16)

`run_backfill()` consumes `connector.backfill_history(tenant_id)` lazily and chunks emitted `HistoricalRecord` instances into in-memory batches of `batch_size` (default 200, configurable per call). When `pending` reaches `batch_size`, `_flush()` is called.

**The flush path has two tiers:**

**Primary — batched insert (fast path):**

1. Open a `Session` + outer `db.begin()`.
2. `apply_tenant_context(db, tenant_id)`.
3. Wrap a SAVEPOINT around `persister.persist_history_records_batch(records)`. The persister:
   - Groups records by `target_table`.
   - Executes ONE `SELECT id, source_id FROM cip_<table> WHERE source_id = ANY(:source_ids)` to look up all current-row ids in a single roundtrip.
   - Computes the union of domain columns present across the batch.
   - Builds an `INSERT INTO cip_<table>_history (...) VALUES (...)` template with NULL for record-level missing fields.
   - Executes via SQLAlchemy `executemany` (psycopg3 pipelines this efficiently).
4. On success: counters merge, return.

**Fallback — per-record SAVEPOINTs (cascade-safe path):**

5. If the batched insert raises `PersistenceError` or `SQLAlchemyError`: SAVEPOINT rolls back. Log a warning.
6. Iterate the same records one by one, each wrapped in its own `db.begin_nested()` and call `persist_history_record()` (the single-record path). One bad record fails alone; the rest still commit.

**Why two-tier:**

- Single-record path is ~2 DB roundtrips per HistoricalRecord. For Wayward contacts with ~65 history snapshots per contact, that was 130 roundtrips per contact ≈ 4 contacts/min sustained on Railway prod. Untenable for any backfill of millions of records.
- Batched path is ~2 roundtrips per FLUSH (typically 200 records). 100-200x improvement when the batch succeeds.
- Fallback path preserves the 2026-05-15 cascade-safety guarantee (one bad record can never poison the rest of the batch).

**Defensive guards already in place** (so the batched path rarely falls back):

- `ck_*_history_valid_range` (strict valid_to > valid_from) — connectors defensively skip records where `valid_to <= valid_from` BEFORE yielding (HubSpot + Zendesk both apply this).
- `NOT NULL` violations — mappers apply fallback values for required fields (e.g., HubSpot company `name` defaults to `"(unnamed hubspot company #<source_id>)"`).
- Mismatched-precision timestamps — HubSpot connector groups property-history revisions by parsed datetime, sorts semantically.

When a fallback DOES fire, the warning log line names the offending error type and the flush size; the per-record retry isolates the bad record and continues.

**Idempotency note:** like the current-state path, re-running backfill against unchanged source data produces zero new history rows IF the source's audit/history endpoint returns the same set of events. The history table doesn't have a UNIQUE on `(record_id, valid_from, valid_to)`, so a buggy connector that re-emits the same audit event TWICE would create duplicate rows. The earlier Zendesk `next_page` infinite-loop bug (2026-05-15) was exactly this — the bug was on the connector side, not the persister. Solution lives in the connector (cursor pagination + `COUNT(DISTINCT source_id)` monitoring), not in the persister.

---

## v5.4 plan-hygiene TODOs surfaced by this guide

Captured for the next plan-hygiene pass:

- §10.2 §4 should document the deployed 5-counter mapping explicitly (Delta 1).
- §10.2 §6 should document the `set_config(..., true)` SQL (Delta 14), not the plan's `SET LOCAL = :tid` shape.
- §10.2 §6 should mention `autoflush=False, expire_on_commit=False` rationale.
- §10.2 §7 forward-pointer should mention the detect-then-assign pattern for `tenant_id` / `ingestion_batch_id` (Delta 8).
