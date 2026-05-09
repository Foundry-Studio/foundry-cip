---
kind: doc
domain: client-intelligence-platform
status: draft
last_updated: 2026-05-05
milestone: Phase-1-M2
---

# Connector Authoring Guide

> **Status:** draft — M2 framework live 2026-05-05. Sections §§1–5, 7–8, 10–12 populated; §6 (`describe_schema()` → registry full semantics) deferred to M6; §9 (`ingest_as_knowledge` real Knowledge+Graph wiring) deferred to M5. Both deferred sections include forward-pointers to the M2-implemented surface.
> Once final, this guide is the authoritative reference for writing any new `CIPConnector` + `CIPMapper` pair (Zendesk, HubSpot, Chatwoot, Twenty, Drive, etc.). M2 validates the framework against `MockConnector + MockMapper` in the conformance harness; M3 lands the `FixtureConnector` reference implementation.

## Purpose

Define the minimum surface area an engineer must implement to bring a new data source onto CIP — `CIPConnector` Protocol, `CIPMapper` Protocol, overflow vs. column decisions, authority flagging, rate-limit policy, and how to pass the connector-conformance test harness.

## Who reads this

- Any engineer writing a new connector (Phase 2 Zendesk / HubSpot / Chatwoot / Twenty / Drive, later phases).
- Reviewers validating connector PRs against the binding Protocol shape.
- M5 / M6 maintainers extending the deferred sections (§6 registry, §9 knowledge ingestion).

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Created the original skeleton. |
| M2 — Connector framework + conformance harness | Populates this guide §§1–5, 7–8, 10–12 (current). |
| M3 — FixtureConnector reference implementation | Populates §12 with copy-and-adapt walkthrough. |
| M5 — Knowledge + Graph wiring | Populates §9 with real Pinecone+FalkorDB ingestion semantics. |
| M6 — Discoverability registry | Populates §6 `describe_schema()` → `cip_connector_property_registry` flow. |

Cross-ref: [`PHASE-1-PLAIN-SPEC.md §4`](vision/PHASE-1-PLAIN-SPEC.md) for the binding Protocol shapes; [`SYNC-ORCHESTRATOR-GUIDE.md`](SYNC-ORCHESTRATOR-GUIDE.md) for the run-loop side of the contract.

---

### 1. Protocol contract

Two Protocols comprise the connector contract. Both are `@runtime_checkable` so `isinstance(x, CIPConnector)` and `isinstance(x, CIPMapper)` work for method-existence guards. Signature-level + generator-function validation runs at orchestrator entry via `validate_connector_shape()` ([`cip/integration_mesh/validation.py`](../cip/integration_mesh/validation.py)).

**`CIPConnector`** — your connector MUST implement:

```python
@runtime_checkable
class CIPConnector(Protocol):
    connector_id: str
    tenant_id: UUID

    def authenticate(self) -> None: ...
    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]: ...
    def describe_schema(self) -> list[PropertyDescriptor]: ...
    def incremental_key(self, record: dict[str, object]) -> datetime: ...

    @property
    def rate_limit_policy(self) -> RateLimitPolicy: ...

    @property
    def cursor_safety_window_seconds(self) -> int: ...
```

**`CIPMapper`** — your mapper MUST implement:

```python
@runtime_checkable
class CIPMapper(Protocol):
    object_type: str
    target_table: str

    def map(self, record: dict[str, object]) -> Iterable[CIPRow]: ...
    def overflow_fields(self) -> list[str]: ...
    def authority(
        self,
    ) -> Literal["agent_discovered", "ingested", "validated"]: ...
    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]: ...
```

**Optional convenience:** inherit from `CIPConnectorBase` / `CIPMapperBase` ([`cip/integration_mesh/base.py`](../cip/integration_mesh/base.py)) for default `rate_limit_policy`, default `cursor_safety_window_seconds`, default `overflow_fields()`, and helpful `NotImplementedError` messages on unimplemented methods. Inheritance is **not required** — structural compatibility via the Protocol is sufficient. Most authors will inherit; the plain-Protocol path is for connectors that already extend a foreign base class.

---

### 2. File layout

A connector lives in its own folder under `cip/integration_mesh/connectors/<connector>/`:

```
cip/integration_mesh/connectors/<connector>/
├── __init__.py                Exports the connector + mapper classes.
├── connector.py               CIPConnector implementation.
├── mapper.py                  CIPMapper implementation.
└── fixtures/
    ├── records.py             Canonical sample records for tests.
    └── schema.py              PropertyDescriptor list for tests.
```

Connectors authored in separate venture repos (Wayward, Rocky Ridge, Project Silk) follow the same layout under their own package root and consume `foundry-cip` via pip-install (per D-152). Structural Protocol compatibility lets connectors live anywhere.

**Tests:** every new connector adds `tests/connectors/<connector>/` plus contributes to the conformance harness via parametrization (see §11).

---

### 3. `authenticate()`

Called once per `run_sync` invocation, before any `stream_records()` call. Raises `AuthenticationError` on credential failure — this is **run-fatal**; the orchestrator does NOT retry.

**Credential resolution order** (your connector decides, but the convention is):

1. Explicit kwarg passed to the connector's `__init__` (test scenarios).
2. Environment variable named `{CONNECTOR}_API_KEY` (or similar `_TOKEN`, `_CLIENT_SECRET` per source-system convention).
3. Future: vault / secrets-manager integration (M6).

**Env-var convention:** `UPPERCASE_CONNECTOR_NAME_API_KEY`. Examples: `HUBSPOT_API_KEY`, `ZENDESK_OAUTH_TOKEN`, `CHATWOOT_ACCESS_TOKEN`. Document the exact env-var names in your connector's `__init__.py` docstring so operators can configure tenant deployments without reading source.

**`AuthenticationError` semantics:**

- Raised by `authenticate()` on bad creds, expired token, network unreachable.
- Run-fatal: orchestrator records `cip_sync_runs.status='failed'` with `error_detail.type='AuthenticationError'`, then re-raises to the caller.
- M2 does NOT auto-refresh tokens — Phase 2 may add an OAuth refresh path.
- Token-expired-mid-sync: connector MUST raise `AuthenticationError` again from the next `stream_records()` call. Orchestrator treats as run-fatal (same as initial failure).

---

### 4. `stream_records(cursor, batch_size)`

The orchestrator invokes `stream_records()` **exactly once per run** (H-10 — confirmed by `test_stream_records_called_once`). Your generator yields one record at a time; the orchestrator chunks records into batches of `batch_size` locally. Do not pre-batch.

**Cursor shape:**

```python
{"last_incremental_key": "2026-04-20T09:00:00+00:00"}  # ISO-8601 tz-aware
```

When `cursor is None`, do a full pull. When `cursor` is provided, yield only records with `incremental_key(record) > cursor["last_incremental_key"]`. The orchestrator pre-applies `cursor_safety_window_seconds` (default 300s) to the stored cursor before passing it to you, so you don't need to handle clock-skew compensation yourself.

**`batch_size` policy:**

- **Respect the caller's value** as a target. The orchestrator chunks at this granularity; cursor advances per batch.
- You MAY cap `batch_size` at your source system's per-page maximum (e.g., HubSpot caps at 100 per request — your connector requests pages of 100 from HubSpot but yields each record one-at-a-time so the orchestrator chunks at the caller's `batch_size`).
- Pagination is your responsibility — yield records across pages transparently.

**Generator pattern:**

```python
def stream_records(
    self,
    cursor: dict[str, object] | None,
    batch_size: int,
) -> Iterator[dict[str, object]]:
    last_key = None
    if cursor and "last_incremental_key" in cursor:
        last_key = datetime.fromisoformat(str(cursor["last_incremental_key"]))
    next_page_token: str | None = None
    while True:
        page = self._fetch_page(after=next_page_token, page_size=min(batch_size, 100))
        for record in page.records:
            rec_ts = self.incremental_key(record)
            if last_key and rec_ts <= last_key:
                continue
            yield record
        if not page.has_next:
            return
        next_page_token = page.next_token
```

**`@functools.wraps`-correct decorators (PATCH-Q3):** if you wrap `stream_records` in a decorator (logging, tracing, etc.), the decorator MUST preserve `__wrapped__` via `@functools.wraps(fn)`. The framework's `validate_connector_shape()` calls `inspect.unwrap(connector.stream_records)` to walk the wrapper chain — without `@functools.wraps`, `inspect.isgeneratorfunction()` returns `False` and your connector is rejected at orchestrator entry with a clear error message.

---

### 5. `incremental_key(record)`

Return the timestamp the orchestrator uses to advance the cursor. **MUST return a tz-aware `datetime`.**

```python
def incremental_key(self, record: dict[str, object]) -> datetime:
    return datetime.fromisoformat(str(record["updated_at"]))  # tz-aware ISO-8601
```

**tz-naive datetimes are run-fatal.** The framework calls `_assert_tz_aware()` (see [`cip/integration_mesh/base.py`](../cip/integration_mesh/base.py)) on every datetime that crosses the framework boundary. A tz-naive return raises `TimezoneNaiveError`, which propagates out of `run_sync()` and aborts the run with `status='failed'`. This is intentional — silently coercing a naive timestamp to UTC corrupts the cursor on DST transitions and cross-region replays.

**Source records that have ambiguous timestamps:** if the source system's payload has no clean update timestamp, raise `TimezoneNaiveError` (or any subclass of `ConnectorError`) with a clear message. The orchestrator records the failure; the operator decides whether to use `sync_mode="full"` (cursor-less) or to fix the source mapping.

**Future-stamp guard:** the orchestrator handles future-dated cursors gracefully (returns no records, logs a warning). Your `incremental_key()` does not need to clip clock-skewed source timestamps — return them as-is.

---

### 6. `describe_schema()` → property registry

**TBD (M6).** The full discoverability-registry semantics — connector authors emitting per-tenant property catalogs that downstream agents and operators query — land with M6.

**M2 forward-pointer (what's already wired):**

`describe_schema()` returns a `list[PropertyDescriptor]`. The orchestrator calls it once per run as part of `_register_properties_best_effort()` and upserts each descriptor into `cip_connector_property_registry`. Failures here are **non-fatal** (log + continue) — registry write errors do NOT abort the sync.

`PropertyDescriptor` shape:

```python
@dataclass(frozen=True)
class PropertyDescriptor:
    connector: str          # your connector_id
    object_type: str        # "ticket", "contact", "deal", ...
    property_name: str      # canonical name
    data_type: str          # see deployed CHECK enum below
    storage_location: Literal["column", "overflow"]
    column_name: str | None # required if storage_location == "column"
    cip_table: str          # "cip_tickets", "cip_contacts", ...
    description: str | None = None
    is_custom: bool = False # True = tenant-defined custom field
```

**Deployed `data_type` value enum** (per [`cip/migrations/versions/cip_08_tickets_and_registry.py`](../cip/migrations/versions/cip_08_tickets_and_registry.py)):

```
'string', 'number', 'datetime', 'enumeration', 'reference', 'boolean', 'array', 'object'
```

Values outside this set will violate the CHECK constraint and the registry insert will fail (logged non-fatally; sync continues). Map your source-system property types to one of these eight values.

**`is_custom = True` once-true-stays-true:** the orchestrator's upsert preserves `is_custom = True` even if a later sync emits the same property with `is_custom = False`. Treat this as the trust contract — don't downgrade custom flags via re-emit.

M6 expands this section with: tenant-aware property discovery, downstream query patterns, custom-field operator UX, schema drift between source-system property changes and existing registry rows.

---

### 7. `CIPMapper.map(record)`

Yields one or more `CIPRow` instances per source record. The orchestrator persists each row to its `target_table` via the SCD-2 persister.

**`CIPRow` shape:**

```python
@dataclass(frozen=True)
class CIPRow:
    target_table: str               # MUST be in ALLOWED_CIP_TABLES
    source_id: str                  # stable ID from source system
    fields: dict[str, object]       # domain columns (email, status, ...)
    overflow: dict[str, object] = field(default_factory=dict)
    client_id: UUID | None = None
    authority: Literal["agent_discovered", "ingested", "validated"] = "ingested"
```

**Multiple rows per record:** legitimate. Example — a Zendesk ticket with N comments could map to 1 ticket row + N comment rows (if comments live in their own `cip_*` table). Yield each row as a separate `CIPRow`.

**`SchemaDriftError`:** raise when the source record carries a field your mapper doesn't know how to handle AND that field is required for correct output. The orchestrator increments `rows_skipped_drift`, logs the failure, and continues to the next record. **Drift is not run-fatal** — partial sync is the M2 default for unknown fields.

**Per-table extras column reality (Delta 4 / 5 reconciliation):** the deployed `cip_*` schema has heterogeneous "overflow" column names. The framework abstracts this via `EXTRAS_COLUMN_BY_TABLE` in [`cip/integration_mesh/persister.py`](../cip/integration_mesh/persister.py):

| target_table | Deployed extras column |
|---|---|
| `cip_clients` | `metadata` |
| `cip_views` | (none) |
| `cip_files` | `properties` |
| `cip_contacts` | `properties` |
| `cip_companies` | `properties` |
| `cip_deals` | `properties` |
| `cip_tickets` | `properties` |

Your mapper emits `CIPRow.overflow={...}` regardless — the persister translates to the deployed column name automatically. **Exception:** mappers targeting `cip_views` MUST emit `overflow={}` (empty); a non-empty overflow on `cip_views` raises `PersistenceError` because the table has no JSONB extras column.

**Nullable `source_id` (Delta 6):** `cip_files.source_id` is nullable in the deployed schema (R2-uploaded blobs without source provenance). The persister's SCD lookup uses `IS NOT DISTINCT FROM` so NULL `source_id` matches correctly. Your `cip_files` mapper MAY emit `source_id=""` (empty string) or any sentinel; the persister treats them as the lookup key.

**`map()` is a generator function** — use `yield`, not `return [...]`. Decorators on `map()` MUST preserve `__wrapped__` via `@functools.wraps` (same PATCH-Q3 rule as §4).

---

### 8. Authority selection

Each `CIPRow.authority` flags the trust level of the row. Phase 1 uses only `"ingested"`; the other two values are reserved for later phases.

| Value | Meaning | When |
|---|---|---|
| `"ingested"` | Connector-sourced data, taken at face value. | Default for all Phase 1 connectors. |
| `"agent_discovered"` | An LLM agent inferred this field (no source confirmation). | Phase 3+ when D-024 lands. |
| `"validated"` | A human or trusted agent has confirmed this row. | Phase 3+ for compliance-sensitive data. |

For M2 / M3 / Phase 2 connectors: emit `authority="ingested"` on every row. The default in `CIPRow.__init__` is `"ingested"` — you can omit the kwarg.

---

### 9. `ingest_as_knowledge(record)`

**TBD (M5).** The full Knowledge+Graph wiring (real Pinecone embedding + FalkorDB ingestion) lands with M5.

**M2 forward-pointer (what's already wired + the contract you must respect):**

`ingest_as_knowledge(record)` returns `list[KnowledgeText]` — text chunks the framework will hand off to the Knowledge+Graph layer. Per D-067, **knowledge-extraction failures are non-fatal**: any exception your method raises (other than `KnowledgeMetadataValidationError` or `TimezoneNaiveError`) is logged at WARNING and the run continues.

**`KnowledgeText` + `KnowledgeTextMetadata` shape:**

```python
@dataclass(frozen=True)
class KnowledgeText:
    text: str
    metadata: KnowledgeTextMetadata  # TypedDict, total=False

class KnowledgeTextMetadata(TypedDict, total=False):
    source_id: str           # required at boundary; mapper MUST emit
    source_system: str       # required at boundary; orchestrator-finalized fallback
    extracted_at: datetime   # required at boundary; tz-aware UTC
    tenant_id: UUID          # required at boundary; orchestrator-OWNED (do not emit)
    connector_version: str   # required at boundary; orchestrator-finalized fallback
    authority: Literal[...]
    record_updated_at: datetime
    ingestion_batch_id: UUID # orchestrator-OWNED (do not emit)
```

**Mapper-emit semantics (per Round-6 Call A "honest mock" + Delta 8):**

| Key | Mapper emits? | Orchestrator behavior |
|---|---|---|
| `source_id` | **YES — mandatory** | Validator raises `KnowledgeMetadataValidationError` if absent |
| `source_system` | OPTIONAL | `setdefault` to `connector.connector_id` — mapper-emit wins |
| `connector_version` | OPTIONAL | `setdefault` to `getattr(connector, "version", "0.0.0")` — mapper-emit wins |
| `extracted_at` | OPTIONAL | `setdefault` to `_utcnow()` (one timestamp per record, hoisted) — mapper-emit wins |
| `tenant_id` | **NO — orchestrator-owned** | Detect-then-assign: if mapper emits a different tenant_id than the run's binding, raise `KnowledgeMetadataValidationError` (run-fatal) |
| `ingestion_batch_id` | **NO — orchestrator-owned** | Same detect-then-assign as `tenant_id` |

**The "honest mock" pattern.** Your mapper SHOULD emit ONLY what it genuinely knows — typically just `source_id`. Don't emit placeholder values for keys you don't have ground truth for; the orchestrator fills `source_system`, `connector_version`, and `extracted_at` from its own state. Emitting `tenant_id` or `ingestion_batch_id` is a contract violation that fails loud.

**Empty-list return:** legal. Means "no knowledge to ingest from this record" (e.g., a record with no email or text body). Orchestrator skips the hook for that record.

M5 replaces the `ingest_texts_noop` body in [`cip/integration_mesh/knowledge_hook.py`](../cip/integration_mesh/knowledge_hook.py) with real Pinecone+FalkorDB writes. The Protocol shape — your `ingest_as_knowledge` return type and the `KnowledgeTextMetadata` contract — does NOT change. Your M5-era code path stays valid.

---

### 10. Rate-limit policy

Expose via the `rate_limit_policy` property on your connector:

```python
@property
def rate_limit_policy(self) -> RateLimitPolicy:
    return RateLimitPolicy(requests_per_second=10.0, burst=5)
```

**`RateLimitPolicy` shape:**

```python
@dataclass(frozen=True)
class RateLimitPolicy:
    requests_per_second: float  # > 0
    burst: int = 1              # >= 1
```

**Default:** `DEFAULT_RATE_LIMIT = RateLimitPolicy(requests_per_second=10.0, burst=5)`. `CIPConnectorBase`'s default `rate_limit_policy` returns this constant — most connectors inherit and skip overriding.

**Orchestrator behavior:**

- Per-instance in-process `TokenBucket` (thread-safe, sleep-based; not distributed).
- Orchestrator calls `bucket.acquire()` before each batch — pacing is automatic.
- If your `stream_records()` raises `RateLimitExceeded(retry_after_seconds=N)`, the orchestrator sleeps `min(N, MAX_RATE_LIMIT_SLEEP_SECONDS)` and retries the same batch. **`MAX_RATE_LIMIT_SLEEP_SECONDS = 300`** caps any single backoff at 5 minutes — sources demanding longer waits get logged + capped (not honored verbatim).
- After `MAX_BATCH_RATE_LIMIT_RETRIES = 3` retries on the same batch, the batch is counted as one consecutive failure. After `MAX_CONSECUTIVE_BATCH_FAILURES = 3` consecutive failures, the run aborts with `status='partial'`.

**Source-specific quirks:**

- HubSpot: 100 req/10s burst → `RateLimitPolicy(requests_per_second=10.0, burst=10)` gives a safe margin.
- Zendesk: 700 req/min → `RateLimitPolicy(requests_per_second=11.0, burst=20)`.
- Phase-2 connectors: tune from real-world 429s during the first week of operation; check `cip_sync_runs.error_detail` for `RateLimitExhaustion` events.

---

### 11. Passing the conformance harness

Every new connector MUST pass `tests/fixtures/connector_conformance/` before merge. **Seven tests** exercise the full Protocol contract end-to-end against a Postgres testcontainer:

| Test file | What it asserts |
|---|---|
| `test_protocol_compliance.py` | `isinstance` + `validate_connector_shape` + `describe_schema` invariants |
| `test_incremental_sync.py` | full sync, delta + bitemporal SCD-2 archive, multi-batch cursor advancement |
| `test_property_registry.py` | 5-descriptor seed, idempotent upsert, `is_custom`-OR preservation |
| `test_scd_history.py` | bitemporal SCD-2 verification + multi-revision history walk |
| `test_sync_run_audit.py` | success/partial transitions + `error_detail` JSONB roundtrip + `batch_id` uniqueness |
| `test_tenant_scoping.py` | A/B/C tenant isolation under `cip_rls_test_role` |
| `test_post_commit_rls_isolation.py` | PATCH-NR-1 GUC clearing invariant + back-to-back tenants + run-fatal exception path |

**Note:** plan §SPEC §11 originally specified six tests; PATCH-NR-1 (Round-3 panel) added `test_post_commit_rls_isolation.py` as Test 7, making the binding count seven. (Atlas v5.4 TODO: update plan §9 acceptance #4 wording from "6 PASSED" to "7 PASSED.")

**Parametrization:** the harness uses `MockConnector + MockMapper` fixtures. To wire your connector, parametrize over a `connector_under_test` fixture so the same seven tests run against your implementation with zero rewrites.

**Passing locally:**

```bash
pip install -e ".[dev]"            # installs testcontainers + pytest + mypy + ruff
docker info                         # Postgres testcontainer requires a Docker daemon
pytest tests/fixtures/connector_conformance/ -v
```

CI runs the harness on every push across Python 3.11–3.14 with a Postgres 16 service container.

---

### 12. Reference implementation

**M2:** `tests/fixtures/connector_conformance/conftest.py` defines `MockConnector + MockMapper` — minimum-conformant Protocol implementations that pass all seven harness tests. Read these as the reference shape. Canonical fixture data lives in `tests/fixtures/connector_conformance/fixtures/records.py`.

**M3 (landed 2026-05-08):** `FixtureConnector` + `FixtureMapper` ship as the first non-mock reference implementation under `cip/integration_mesh/connectors/fixture/`. They demonstrate:

- **Folder layout:** `connector.py`, `mapper.py`, `corpus.py`, `records.py`, `__init__.py` — copy this as your starting template for a new connector.
- **Deterministic synthetic corpus:** `corpus.py` generates records via `Faker.seed_instance(int)` + a separate `random.Random(seed)` for selection draws (two-RNG split avoids state-coupling between shape and selection). `PYTHONHASHSEED=0` + pinned `faker==X.Y.Z` ⇒ byte-identical corpus across two same-seed runs (snapshot SHA in `tests/integration_mesh/test_fixture_corpus_determinism.py` is the regression guard).
- **Three corpus presets (`CorpusSize`):** `STANDARD` (50/200/300/500/100/0 = 1150 rows across 6 object types), `COMPACT` (10× smaller for fast unit tests), `SMOKE` (10 contacts only — MockConnector-equivalent for e2e\_smoke).
- **30 `PropertyDescriptor`s across 6 object types** (5 active + `note` forward-compat) covering `data_type` values `string`, `number`, `enumeration`, `datetime` (4 of the 8 deployed enum members; `reference`, `boolean`, `array`, `object` exercise paths a future connector should add).
- **Advisory-lock dual-run prevention** (M3 §4.8): `run_sync` acquires a session-level Postgres advisory lock keyed on `(tenant_id, connector_id)` via a NullPool lock-holder engine; concurrent runs raise `SyncAlreadyRunningError`. Tested in `tests/fixtures/connector_conformance/test_concurrent_sync_advisory_lock.py` (8 sub-tests).
- **End-to-end harness:** `test_fixture_connector_e2e_smoke.py` and `test_fixture_connector_e2e_standard.py` exercise the full chain (orchestrator → persister → SCD differ → recorder → knowledge-hook) against a real Postgres testcontainer, including 1150-row volume + ~600 KnowledgeText emissions + the validation contract for orchestrator-owned metadata keys.

**Mapper-side translation contract (M3 Δ5):** `CIPRow.fields` keys are SQL column names, NOT record-side names. Where the deployed migration's column name differs from the natural record field name, the mapper translates via a static `_RECORD_TO_SQL_COLUMN` map. In FixtureMapper this affects `ticket` (`body→description`, `assignee→assignee_name`) and `document` (`title→filename`, `file_size_bytes→size_bytes`). When authoring a new connector, build the equivalent mapping from your source-system field names to the deployed `cip_*` SQL columns; the mismatch is silent at INSERT time and surfaces as `UndefinedColumn` only when the table is first written to.

**Deployed-only NOT NULL columns (M3 Δ6):** Some `cip_*` tables have NOT NULL columns that aren't in the connector's `describe_schema()` (they're infrastructure columns, not source fields). `cip_files.r2_path` is the current example — FixtureMapper synthesizes a stable `r2_path = "fixture://{source_id}"`. Real connectors fill it from their actual storage upload.

**Numeric round-trip discipline (M3 Δ7):** Postgres NUMERIC columns return as `Decimal`; Python typically emits `float`. The SCD differ canonicalizes both via `Decimal(str(v))` so re-syncs don't spuriously archive every row. If you add a new connector with NUMERIC domain columns, test idempotency on a second run — the differ should report `rows_skipped_unchanged == row_count`.

When authoring a new connector (Phase 2 onward), copy `cip/integration_mesh/connectors/fixture/` as the starting template, replace the corpus generator with your source-system API client (preserve the Protocol shape — `stream_records`, `incremental_key`, `describe_schema`, `authenticate`, `rate_limit_policy`, `cursor_safety_window_seconds`), and run the conformance harness against your connector instance.

---

## v5.4 plan-hygiene TODOs surfaced by this guide

Captured for the next plan-hygiene pass:

- §SPEC §11 / §9 acceptance #4: count is 7 conformance tests, not 6 (PATCH-NR-1 added `test_post_commit_rls_isolation.py`).
- `PropertyDescriptor.data_type` docstring should enumerate the deployed CHECK constraint values (Delta 12 follow-up).
- §10.1 §10 should mention `MAX_RATE_LIMIT_SLEEP_SECONDS = 300` cap explicitly.
- §10.1 §7 should document `EXTRAS_COLUMN_BY_TABLE` reality + `cip_views` no-extras case (Deltas 4 + 5).
