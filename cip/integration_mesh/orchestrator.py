# foundry: kind=service domain=client-intelligence-platform touches=integration
"""CIP sync orchestrator (M2 §4.8 binding).

Drives one connector through:
  authenticate → register properties (best-effort) → loop(stream → map → persist
  → knowledge-hook → cursor advance) → recorder finalize.

Top-level function: ``run_sync()``. Helpers below are private.

Key v3/v4/v5 fixes baked in:
  - R2-A1: takes ``Engine`` (not ``Session``); per-batch Session via
    ``with Session(engine, ...) as db, db.begin():``.
  - R2-A2: ``_finalize()`` runs AFTER the ``with recorder:`` block.
  - R2-C7: ``cursor_state`` written via ``CAST(:c AS jsonb)``.
  - C-4: ``cursor_state`` written in the SAME txn as the batch's row writes.
  - C-5: ``validate_connector_shape()`` at entry; entry-shape failures
    propagate to caller with zero DB rows touched.
  - H-6: per-batch rate-limit retry budget.
  - H-7: ``mapper.map`` return materialised via ``list()`` so partial yields
    on ``SchemaDriftError`` are atomic-discarded.
  - H-8: batch in ``try / except / finally`` around ``db.begin()`` so a
    post-commit knowledge-hook exception leaves no half-open transaction.
  - H-9: ``batch_latest_key`` scoped to the batch.
  - H-10: ONE ``stream_records`` call per run; orchestrator chunks locally.
  - H-11: intra-batch dedupe on ``source_id``.
  - H-12: tz-naive ``incremental_key`` raises ``TimezoneNaiveError`` (run-fatal).
  - H-13: cursor safety window — rewind stored cursor before stream call.
  - M-21: ``RateLimitExceeded.retry_after_seconds`` capped at 300s.
  - PATCH-NR-2: generator close propagation via ``contextlib.closing``.
  - PATCH-Q4 + R2-A2: recorder doesn't touch ``cursor_state`` on ``__exit__``.
  - Round-7 Verifier HIGH-A: orchestrator CALLS ``validate_knowledge_text_metadata()``
    (was dead code in v4).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from .base import (
    DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS,  # noqa: F401  # reference-import for documentation
    MAX_BATCH_RATE_LIMIT_RETRIES,
    MAX_CONSECUTIVE_BATCH_FAILURES,
    MAX_RATE_LIMIT_SLEEP_SECONDS,
    CIPConnector,
    CIPMapper,
    KnowledgeText,
    KnowledgeTextMetadata,
    SyncRunState,
    validate_knowledge_text_metadata,
)
from .exceptions import (
    AuthenticationError,
    KnowledgeMetadataValidationError,
    PersistenceError,
    RateLimitExceeded,
    SchemaDriftError,
    SyncAlreadyRunningError,
    SyncLockUnavailableError,
    TimezoneNaiveError,
)
from .knowledge_hook import ingest_texts_noop
from .persister import CIPRowPersister
from .rate_limit import TokenBucket
from .scd_differ import SCDDiffer
from .sync_run_recorder import SyncRunRecorder
from .tenant_context import apply_tenant_context
from .validation import validate_connector_shape

log = logging.getLogger(__name__)


# ── Module-private helpers ────────────────────────────────────────────────


# v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 7, 2026-04-29)
# Plan §4.8 uses ``_utcnow()`` but never defines it.
# Reconciliation: orchestrator-private helper. Tests can monkeypatch
# ``cip.integration_mesh.orchestrator._utcnow`` for deterministic time.
# Rationale: trivial omission in plan; obvious fix.
# Atlas v5.4 TODO: plan §4.8 should define ``_utcnow()`` as orchestrator-private.
def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_id(rec: dict[str, object]) -> str:
    """Best-effort record identifier for log/error messages."""
    sid = rec.get("source_id") or rec.get("id") or "?"
    return str(sid)


def _redact(d: dict[str, object]) -> dict[str, object]:
    """Best-effort PII scrub of error_detail JSONB before persist.

    Keeps in sync with ``sync_run_recorder._redact``. Conservative: only
    scrubs string values that look like emails.
    """
    import re

    email_re = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

    def _scrub(v: object) -> object:
        if isinstance(v, str):
            return email_re.sub("<redacted:email>", v)
        if isinstance(v, dict):
            return {k: _scrub(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_scrub(x) for x in v]
        return v

    return cast(dict[str, object], _scrub(d))


# ── Advisory-lock helpers (M3 §4.8) ──────────────────────────────────────


def _advisory_lock_key(tenant_id: UUID, connector_id: str) -> int:
    """Stable signed bigint key for ``pg_try_advisory_lock`` (M3 §2.5).

    SHA-256 of ``"{tenant_id}:{connector_id}"``, first 8 bytes, big-endian,
    signed. Postgres advisory locks accept BIGINT (signed 8-byte int).

    Stability: same input always produces same key. Different code paths
    that need to take the same lock use this same helper.
    """
    h = hashlib.sha256(f"{tenant_id}:{connector_id}".encode()).digest()
    return int.from_bytes(h[:8], byteorder="big", signed=True)


def _make_lock_holder_engine(database_url: str) -> Engine:
    """Construct the dedicated NullPool lock-holder engine (M3 §2.4 / §4.8).

    NullPool: each connection is fresh + closed when released. No pool reuse.
    This bypasses any pool / PgBouncer routing — the lock acquisition + release
    happen on the same physical Postgres backend. Critical: PgBouncer in
    transaction-pooling mode silently breaks session-scoped advisory locks
    because pgbouncer multiplexes sessions across backends; NullPool with a
    direct Postgres URL eliminates this class of bug.

    TCP keepalive params defeat cloud-Postgres idle-disconnect reaping
    (Railway, RDS Proxy, Aurora, Cloud SQL — most reap idle conns after
    5-10 min). Without these, a long sync (>5 min) could see its lock-holder
    connection silently dropped, releasing the lock mid-run.

    Tests can monkeypatch ``cip.integration_mesh.orchestrator._make_lock_holder_engine``
    to return a stub when DB-less unit-testing the orchestrator entry path.
    """
    return sa.create_engine(
        database_url,
        poolclass=NullPool,
        connect_args={
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        },
    )


@contextmanager
def _AdvisoryLockHeld(  # noqa: N802  # Plan §4.8 names this with PascalCase to read as a class-like ctxmgr.
    lock_engine: Engine,
    tenant_id: UUID,
    connector_id: str,
) -> Iterator[Connection]:
    """Session-scoped advisory lock for the duration of one ``run_sync``
    (M3 §4.8).

    Uses ``pg_try_advisory_lock(key)`` on a dedicated short-lived connection
    from the NullPool ``lock_engine`` (constructed via
    ``_make_lock_holder_engine``). Lock auto-releases when the connection
    closes (orphan-safe under crash).

    Raises:
        SyncAlreadyRunningError: ``pg_try_advisory_lock`` returned ``false``
            (another sync holds the lock). Run-fatal; caller should NOT retry.
        SyncLockUnavailableError: ``lock_engine.connect()`` failed (pool
            exhaustion, network, Postgres unreachable) OR
            ``pg_try_advisory_lock`` returned NULL (Postgres misconfiguration).
            Caller MAY retry on this transient condition.
    """
    key = _advisory_lock_key(tenant_id, connector_id)
    try:
        conn = lock_engine.connect()
    except sa.exc.SQLAlchemyError as connect_err:
        raise SyncLockUnavailableError(
            f"failed to open lock-holder connection for tenant_id={tenant_id} "
            f"connector_id={connector_id!r}: {connect_err}"
        ) from connect_err

    try:
        result = conn.execute(
            sa.text("SELECT pg_try_advisory_lock(:key) AS got"),
            {"key": key},
        ).scalar()
        if result is None:
            raise SyncLockUnavailableError(
                f"pg_try_advisory_lock returned NULL for tenant_id={tenant_id} "
                f"connector_id={connector_id!r} — Postgres misconfiguration"
            )
        if not result:
            raise SyncAlreadyRunningError(
                f"sync for tenant_id={tenant_id} connector_id={connector_id!r} "
                f"is already in flight (advisory lock held); refusing to run a "
                f"second concurrent instance"
            )
        try:
            yield conn
        finally:
            # Explicit unlock for hygiene; Postgres also auto-releases on close.
            try:
                conn.execute(
                    sa.text("SELECT pg_advisory_unlock(:key)"),
                    {"key": key},
                )
            except Exception as unlock_err:
                log.warning(
                    "advisory unlock failed (non-fatal; conn close will GC): %s",
                    unlock_err,
                )
    finally:
        conn.close()


# ── Top-level entry point ─────────────────────────────────────────────────


def run_sync(
    connector: CIPConnector,
    mapper: CIPMapper,
    engine: sa.Engine,
    *,
    tenant_id: UUID,
    client_id: UUID | None = None,
    sync_mode: Literal["full", "incremental"] = "incremental",
    batch_size: int = 500,
    initial_cursor: dict[str, object] | None = None,
    cursor_safety_window_seconds: int | None = None,
    database_url: str | None = None,
) -> SyncRunState:
    """Drive one connector end-to-end.

    See module docstring for full v3/v4/v5 fix lineage.

    Args:
        connector: A ``CIPConnector`` Protocol-compliant instance.
        mapper: A ``CIPMapper`` Protocol-compliant instance.
        engine: SQLAlchemy ``Engine``. The orchestrator opens a fresh per-batch
            ``Session`` and the recorder opens its own short-lived
            ``engine.begin()`` connections (R2-A1 + §4.7).
        tenant_id: Run is bound to this tenant; RLS enforces scoping
            (D-026 + D-127).
        client_id: Optional client scope.
        sync_mode: ``"full"`` clears the cursor; ``"incremental"`` honors it.
        batch_size: Records per batch + cursor-write granularity. Default 500.
        initial_cursor: Resume token from a prior run's ``cip_sync_runs``
            cursor_state. None = full pull regardless of sync_mode.
        cursor_safety_window_seconds: Per-call override for the connector's
            ``cursor_safety_window_seconds`` property. None = use connector default.

    Returns:
        ``SyncRunState`` populated from the recorder's post-``__exit__`` fields.

    Raises:
        ProtocolShapeError: Connector / mapper shape invalid (entry-time guard).
        AuthenticationError: Connector ``authenticate()`` failed.
        TimezoneNaiveError: Connector returned a tz-naive datetime, or stored
            cursor is tz-naive. Run-fatal.
        KnowledgeMetadataValidationError: Mapper-emitted KnowledgeText metadata
            violates the boundary contract (missing required key, or a buggy
            mapper attempted to override an orchestrator-owned key like
            ``tenant_id`` / ``ingestion_batch_id``). Run-fatal.

    M3 §4.8 additions:
        database_url: Optional explicit URL for the lock-holder engine. If
            None, extracted from ``engine.url``. Pass an explicit URL ONLY if
            ``engine`` routes through PgBouncer and you need to point the
            lock-holder at a direct Postgres URL (NullPool bypass).

    M3 acquires a session-level Postgres advisory lock keyed on
    ``(tenant_id, connector_id)`` AFTER ``validate_connector_shape`` and
    BEFORE any other state. Lock is held for the entire run; auto-releases
    on connection close (orphan-safe under crash). Raises
    ``SyncAlreadyRunningError`` if a concurrent run is already in flight;
    raises ``SyncLockUnavailableError`` if the lock-holder engine cannot
    connect.

    Does NOT raise on partial failures — those are recorded as
    ``cip_sync_runs.status='partial'``.
    """
    # ── 0. Validate connector shape (C-5). Fails fast before we burn a
    #    lock-acquire round-trip on caller-bug input.
    validate_connector_shape(connector, mapper)

    # ── 0.1 (M3 §4.8). Acquire session-level advisory lock around the
    #    entire run. NullPool lock-holder engine bypasses any PgBouncer
    #    transaction-pooling that would silently break session locks.
    lock_db_url = (
        database_url if database_url is not None else str(engine.url)
    )
    lock_engine = _make_lock_holder_engine(lock_db_url)
    try:
        with _AdvisoryLockHeld(lock_engine, tenant_id, connector.connector_id):
            return _run_sync_body(
                connector=connector,
                mapper=mapper,
                engine=engine,
                tenant_id=tenant_id,
                client_id=client_id,
                sync_mode=sync_mode,
                batch_size=batch_size,
                initial_cursor=initial_cursor,
                cursor_safety_window_seconds=cursor_safety_window_seconds,
            )
    finally:
        lock_engine.dispose()


def _run_sync_body(  # noqa: C901, PLR0912, PLR0915  # Orchestrator main loop is intentionally one function per plan §4.8.
    *,
    connector: CIPConnector,
    mapper: CIPMapper,
    engine: sa.Engine,
    tenant_id: UUID,
    client_id: UUID | None,
    sync_mode: Literal["full", "incremental"],
    batch_size: int,
    initial_cursor: dict[str, object] | None,
    cursor_safety_window_seconds: int | None,
) -> SyncRunState:
    """M2 ``run_sync`` body, hoisted into a private helper so the M3
    advisory-lock context wraps cleanly.

    Why a separate function vs. inlined within ``run_sync`` (Tim-approved
    deviation, M3 build 2026-05-08):
    - Behaviour is identical to the M2-era body; only the call site moved.
    - Wrapping the entire ~150-line body in another ``with`` block would
      require re-indenting the whole thing — a noisy diff that obscures
      the semantic change (lock acquisition).
    - All M2 unit tests in ``test_orchestrator.py`` patch module-level
      names (``Session``, ``CIPRowPersister``, ``ingest_texts_noop``,
      ``time.sleep``, etc.). Extracting the body into a sibling function
      that resolves those same names from module scope at call time
      preserves every existing monkeypatch surface — no test rewrites
      needed when the lock wrapper landed in M3.
    - Private (single leading underscore) signals "internal helper, not
      a stable public seam"; callers must use ``run_sync`` which guarantees
      the lock + lock-engine lifecycle.

    Atlas v3.1 plan-hygiene at M3 close will note this as an Atlas-approved
    enhancement (not a plan-vs-reality reconciliation).
    """
    bucket = TokenBucket(connector.rate_limit_policy)
    differ = SCDDiffer()

    recorder = SyncRunRecorder(
        engine=engine,
        tenant_id=tenant_id,
        client_id=client_id,
        connector_id=connector.connector_id,
        connector_name=connector.__class__.__name__,
        sync_mode=sync_mode,
    )

    consecutive_batch_failures = 0
    aborted = False  # v3 R2-A2: early-exit flag; with-block exits normally.

    with recorder as run:
        # ── 1. Authenticate (outside any batch txn).
        try:
            connector.authenticate()
        except Exception as e:
            raise AuthenticationError(str(e)) from e

        # ── 2. Register properties (best-effort; M6 hardens this).
        _register_properties_best_effort(engine, connector, tenant_id)

        # ── 3. Compute safety-window-adjusted cursor (H-13).
        cursor: dict[str, object] | None = (
            initial_cursor if sync_mode == "incremental" else None
        )
        # v4 (Round-3 panel): kwarg overrides; None falls back to connector's property.
        effective_window = (
            cursor_safety_window_seconds
            if cursor_safety_window_seconds is not None
            else connector.cursor_safety_window_seconds
        )
        adjusted_cursor = _apply_safety_window(cursor, effective_window)

        # ── 4. ONE stream_records call per run (H-10). PATCH-NR-2: wrap in
        #    contextlib.closing so .close() fires on ANY exit path
        #    (normal completion, exception, KeyboardInterrupt). The inner
        #    _chunked() also propagates close to the underlying generator.
        record_iter = _chunked(
            connector.stream_records(adjusted_cursor, batch_size),
            batch_size,
        )
        with contextlib.closing(record_iter):
            for raw_batch in record_iter:
                if aborted:
                    break
                batch_rl_retries = 0
                batch_committed = False

                while not batch_committed:
                    try:
                        bucket.acquire()  # paces normal calls

                        # ── 4a. Dedupe on source_id within the batch (H-11).
                        batch = _dedupe_by_source_id(raw_batch)
                        run.counters.rows_skipped_duplicate += (
                            len(raw_batch) - len(batch)
                        )

                        try:
                            consecutive_batch_failures = _process_batch(
                                engine=engine,
                                connector=connector,
                                mapper=mapper,
                                differ=differ,
                                tenant_id=tenant_id,
                                run=run,
                                batch=batch,
                            )
                            batch_committed = True
                            consecutive_batch_failures = 0

                        except PersistenceError as pe:
                            # `with db.begin():` rolled the batch back.
                            consecutive_batch_failures += 1
                            log.error(
                                "batch failed: %s (consecutive=%d)",
                                pe,
                                consecutive_batch_failures,
                            )
                            run.counters.error_detail = _redact(
                                {
                                    "type": "PersistenceError",
                                    "message": str(pe),
                                    "consecutive_failures": consecutive_batch_failures,
                                }
                            )
                            if (
                                consecutive_batch_failures
                                >= MAX_CONSECUTIVE_BATCH_FAILURES
                            ):
                                log.error(
                                    "%d consecutive batch failures, aborting run",
                                    MAX_CONSECUTIVE_BATCH_FAILURES,
                                )
                                aborted = True  # v3 R2-A2: exit `with` cleanly
                                break
                            break  # break out of the rl-retry while; next batch

                    except RateLimitExceeded as rl:
                        batch_rl_retries += 1
                        sleep_s = min(
                            rl.retry_after_seconds,
                            MAX_RATE_LIMIT_SLEEP_SECONDS,
                        )
                        if sleep_s < rl.retry_after_seconds:
                            log.warning(
                                "RateLimitExceeded asked for %ss, "
                                "capped at %ss (M-21)",
                                rl.retry_after_seconds,
                                MAX_RATE_LIMIT_SLEEP_SECONDS,
                            )
                        if batch_rl_retries > MAX_BATCH_RATE_LIMIT_RETRIES:
                            # H-6: rate-limit exhaustion = batch failure.
                            consecutive_batch_failures += 1
                            log.error(
                                "rate-limit retries exhausted on batch "
                                "(retries=%d, consecutive_failures=%d)",
                                batch_rl_retries,
                                consecutive_batch_failures,
                            )
                            run.counters.error_detail = _redact(
                                {
                                    "type": "RateLimitExhaustion",
                                    "batch_retries": batch_rl_retries,
                                    "consecutive_failures": consecutive_batch_failures,
                                }
                            )
                            if (
                                consecutive_batch_failures
                                >= MAX_CONSECUTIVE_BATCH_FAILURES
                            ):
                                aborted = True  # v3 R2-A2
                                break
                            break
                        log.warning(
                            "rate limited (retry %d/%d), sleeping %ss",
                            batch_rl_retries,
                            MAX_BATCH_RATE_LIMIT_RETRIES,
                            sleep_s,
                        )
                        time.sleep(sleep_s)
                        continue  # retry same batch

    # v3 R2-A2: `with recorder:` has exited. recorder.final_status and
    # recorder.final_ended_at are populated by __exit__. Build SyncRunState here.
    return _finalize(recorder)


# ── Per-batch processing ─────────────────────────────────────────────────


def _process_batch(  # noqa: C901, PLR0912, PLR0915  # Single per-batch transaction; intentionally one function.
    *,
    engine: sa.Engine,
    connector: CIPConnector,
    mapper: CIPMapper,
    differ: SCDDiffer,
    tenant_id: UUID,
    run: SyncRunRecorder,
    batch: list[dict[str, object]],
) -> int:
    """Process one (already-deduped) batch of records inside one txn.

    Per v3 R2-A1: SQLAlchemy 2.x idiomatic
    ``with Session(engine, ...) as db, db.begin():`` pattern. Session
    auto-begins on first DB op; outer ``db.begin()`` commits on normal
    exit, rolls back on exception.

    Returns the orchestrator's running ``consecutive_batch_failures`` count
    (caller resets to 0 on success).

    Raises:
        PersistenceError: from the persister; caller increments the
            consecutive-failure counter and decides whether to abort.
        TimezoneNaiveError: tz-naive ``incremental_key()``; run-fatal.
        KnowledgeMetadataValidationError: mapper-emitted metadata violates
            boundary contract; run-fatal.
    """
    batch_latest_key: datetime | None = None  # H-9 (batch-scoped)

    # v4 (Round-3 panel HIGH): autoflush=False + expire_on_commit=False
    # prevents subtle mid-batch implicit-flush deadlocks.
    with Session(
        engine, autoflush=False, expire_on_commit=False
    ) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        persister = CIPRowPersister(db, differ)

        for rec in batch:
            # ── (i) mapper.map → CIPRows → persister
            # H-7: list() wraps the generator so a mid-yield drift error
            # discards any partial rows.
            try:
                rows = list(mapper.map(rec))
            except SchemaDriftError as sd:
                log.warning(
                    "schema drift on record %s: %s", _safe_id(rec), sd
                )
                run.counters.rows_skipped_drift += 1
                continue

            for row in rows:
                result = persister.persist(
                    row,
                    tenant_id=tenant_id,
                    connector_id=connector.connector_id,
                    batch_id=run.batch_id,
                )
                run.counters.rows_created += result.created
                run.counters.rows_updated += result.updated
                run.counters.rows_skipped_unchanged += result.skipped
                run.counters.rows_history += result.history

            # ── (ii) Knowledge-hook: finalize → validate → noop.
            # Per Round-6 Call A + §4.8 restate sign-off:
            #   - mapper.ingest_as_knowledge() → list[KnowledgeText]
            #   - orchestrator finalizes the 5 required core keys + ingestion_batch_id
            #   - validator runs at boundary
            #   - ingest_texts_noop runs ONCE per record (after all texts validate)
            # v5.3 §4.8: validation failure is batch-fatal — domain rows in
            # flight roll back via db.begin() exception path.
            _run_knowledge_hook(
                connector=connector,
                mapper=mapper,
                run=run,
                rec=rec,
                tenant_id=tenant_id,
            )

            # ── (iii) Cursor advance (H-12 + H-9).
            try:
                k = connector.incremental_key(rec)
            except Exception as e:
                log.warning(
                    "incremental_key failed on %s: %s", _safe_id(rec), e
                )
                k = None
            if k is not None:
                # H-12: tz-naive datetimes are silent correctness bugs.
                if k.tzinfo is None or k.utcoffset() is None:
                    raise TimezoneNaiveError(
                        f"incremental_key returned tz-naive datetime for "
                        f"record {_safe_id(rec)}: {k!r}"
                    )
                if batch_latest_key is None or k > batch_latest_key:
                    batch_latest_key = k

        run.counters.rows_received += len(batch)

        # ── 4c. Write cursor_state INSIDE the same transaction (C-4).
        # v3 R2-C7: bind value is a JSON string; CAST to jsonb at SQL.
        if batch_latest_key is not None:
            new_cursor: dict[str, object] = {
                "last_incremental_key": batch_latest_key.isoformat()
            }
            db.execute(
                sa.text(
                    "UPDATE cip_sync_runs "
                    "SET cursor_state = CAST(:c AS jsonb) "
                    "WHERE id = :id"
                ),
                {
                    "c": json.dumps(new_cursor, default=str),
                    "id": str(run.run_id),
                },
            )
            run.counters.cursor_state = new_cursor

        # `with db.begin():` commits on normal exit.

    return 0  # caller resets consecutive_batch_failures on success.


# ── Knowledge-hook (metadata finalize → validate → noop) ─────────────────


def _run_knowledge_hook(
    *,
    connector: CIPConnector,
    mapper: CIPMapper,
    run: SyncRunRecorder,
    rec: dict[str, object],
    tenant_id: UUID,
) -> None:
    """Finalize + validate + dispatch a record's KnowledgeTexts.

    Per §4.8 restate sign-off (2026-04-29):
      - 3 keys ``setdefault`` (mapper-may-know-better):
        ``source_system``, ``connector_version``, ``extracted_at``.
      - 2 keys detect-then-assign (orchestrator-owned, fail-loud):
        ``tenant_id``, ``ingestion_batch_id``.
      - 1 key mapper MUST emit: ``source_id`` (validator catches absence).
      - ``extracted_at`` hoisted outside the per-text loop — one timestamp
        per record, not per text.

    Validation errors propagate (run-fatal); other exceptions are logged
    and swallowed (D-067 non-fatal).
    """
    try:
        raw_texts = mapper.ingest_as_knowledge(rec)
        if not raw_texts:
            return

        # v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 9, 2026-04-29)
        # Plan §4.8: ``_utcnow()`` called inside the per-text loop; gives
        # N microsecond-different timestamps per record.
        # Reconciliation: hoist outside — one ``extracted_at`` per record.
        # Rationale: clearer semantic; identical-event records share one ts.
        # Atlas v5.4 TODO: plan §4.8 should hoist ``_utcnow()`` outside the
        # inner for-text loop.
        extraction_ts = _utcnow()
        # ``str()`` coerces non-str connector.version values defensively
        # (Protocol membership is loose per §4.8 restate item (b)).
        connector_version = str(getattr(connector, "version", "0.0.0"))
        finalized_texts: list[KnowledgeText] = []

        for t in raw_texts:
            md: dict[str, object] = dict(t.metadata)

            # v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 8, 2026-04-29)
            # Plan §4.8: setdefault for all 5 required keys + ingestion_batch_id.
            # Reconciliation: 3-keys setdefault + 2-keys detect-then-assign
            # split (Tim's call γ on §4.8 restate). tenant_id and
            # ingestion_batch_id are orchestrator-owned; a buggy mapper
            # emitting them is a contract violation that must fail loud.
            # Rationale: silent overwrite means the bug never gets caught.
            # Atlas v5.4 TODO: plan §4.8 should split setdefault semantics
            # for orchestrator-owned vs mapper-may-know-better keys.

            # Detect-then-assign: tenant_id (orchestrator-owned, fail-loud).
            mapper_tenant_id = md.get("tenant_id")
            if (
                mapper_tenant_id is not None
                and mapper_tenant_id != tenant_id
            ):
                raise KnowledgeMetadataValidationError(
                    f"mapper emitted tenant_id={mapper_tenant_id!r} but run "
                    f"is bound to tenant_id={tenant_id!r} — orchestrator-owned "
                    f"key cannot be overridden (where=ingest_as_knowledge for "
                    f"record {_safe_id(rec)})"
                )
            md["tenant_id"] = tenant_id

            # Detect-then-assign: ingestion_batch_id (orchestrator-owned).
            mapper_batch_id = md.get("ingestion_batch_id")
            if (
                mapper_batch_id is not None
                and mapper_batch_id != run.batch_id
            ):
                raise KnowledgeMetadataValidationError(
                    f"mapper emitted ingestion_batch_id={mapper_batch_id!r} "
                    f"but run batch_id={run.batch_id!r} — orchestrator-owned "
                    f"key cannot be overridden (where=ingest_as_knowledge "
                    f"for record {_safe_id(rec)})"
                )
            md["ingestion_batch_id"] = run.batch_id

            # setdefault for the 3 mapper-may-know-better keys.
            md.setdefault("source_system", connector.connector_id)
            md.setdefault("connector_version", connector_version)
            md.setdefault("extracted_at", extraction_ts)

            # Boundary validation — raises KnowledgeMetadataValidationError
            # or TimezoneNaiveError on contract violation.
            validate_knowledge_text_metadata(
                cast(KnowledgeTextMetadata, md),
                where=f"ingest_as_knowledge for record {_safe_id(rec)}",
            )
            finalized_texts.append(
                KnowledgeText(
                    text=t.text, metadata=cast(KnowledgeTextMetadata, md)
                )
            )

        ingest_texts_noop(finalized_texts)
    except (KnowledgeMetadataValidationError, TimezoneNaiveError):
        # Validation errors are FATAL — re-raise. The contract was violated;
        # do NOT swallow as "non-fatal."
        raise
    except Exception as ke:
        log.warning("knowledge-ingest failed (non-fatal): %s", ke)


# ── Property-registry best-effort upsert ─────────────────────────────────


def _register_properties_best_effort(
    engine: sa.Engine, connector: CIPConnector, tenant_id: UUID
) -> None:
    """Upsert connector property descriptors. Best-effort: log + continue
    on any failure; never aborts the sync.

    v3 R2-A1: takes Engine; opens its own short-lived Session. Isolated
    from per-batch Sessions so a registry write failure can't poison
    later batches.

    M-16: real ``INSERT ... ON CONFLICT DO UPDATE`` with ``is_custom``
    once-true-stays-true preservation.

    v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 10 + 11, 2026-04-29)
    Plan §4.8 SQL: writes columns ``connector_id`` and ``data_type``; ON
    CONFLICT key ``(tenant_id, connector_id, ...)``.
    Deployed schema (cip_08): SQL columns are ``connector`` and
    ``property_type``; ON CONFLICT key ``(tenant_id, connector, ...)``.
    PropertyDescriptor.data_type Python attribute → SQL ``property_type``
    column at the bind layer; PropertyDescriptor.connector → SQL
    ``connector`` column (already aligned).
    Rationale: P-22 / D-123 — migrations are authoritative.
    Atlas v5.4 TODO: plan §4.8 SQL should use ``connector`` +
    ``property_type`` + matching ON CONFLICT key.
    """
    try:
        props = connector.describe_schema()
    except Exception as e:
        log.warning("describe_schema failed (non-fatal): %s", e)
        return

    try:
        with Session(
            engine, autoflush=False, expire_on_commit=False
        ) as db, db.begin():
            apply_tenant_context(db, tenant_id)
            for p in props:
                db.execute(
                    sa.text(
                        """
                        INSERT INTO cip_connector_property_registry (
                            tenant_id, connector, object_type, property_name,
                            property_type, is_custom, storage_location,
                            column_name, cip_table, description
                        ) VALUES (
                            :tenant_id, :connector, :object_type, :property_name,
                            :property_type, :is_custom, :storage_location,
                            :column_name, :cip_table, :description
                        )
                        ON CONFLICT (tenant_id, connector, object_type, property_name)
                        DO UPDATE SET
                            property_type    = EXCLUDED.property_type,
                            storage_location = EXCLUDED.storage_location,
                            column_name      = EXCLUDED.column_name,
                            cip_table        = EXCLUDED.cip_table,
                            description      = EXCLUDED.description,
                            is_custom = (
                                cip_connector_property_registry.is_custom
                                OR EXCLUDED.is_custom
                            )
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        # PropertyDescriptor.connector → SQL connector
                        "connector": p.connector,
                        "object_type": p.object_type,
                        "property_name": p.property_name,
                        # PropertyDescriptor.data_type → SQL property_type
                        "property_type": p.data_type,
                        "is_custom": p.is_custom,
                        "storage_location": p.storage_location,
                        "column_name": p.column_name,
                        "cip_table": p.cip_table,
                        "description": p.description,
                    },
                )
    except Exception as e:
        log.warning("property registry write failed (non-fatal): %s", e)


# ── Pure helpers ─────────────────────────────────────────────────────────


def _apply_safety_window(
    cursor: dict[str, object] | None, window_seconds: int
) -> dict[str, object] | None:
    """H-13: rewind ``cursor['last_incremental_key']`` by ``window_seconds``.

    Absorbs clock skew + replica lag — records written to the source DB
    just before our previous cursor's instant but only visible after our
    previous sync completed. Pure function; ``window_seconds <= 0`` disables.

    Raises:
        TimezoneNaiveError: stored cursor is tz-naive (we wrote it, so this
            is a regression we want to see).
    """
    if cursor is None or window_seconds <= 0:
        return cursor
    key_iso = cursor.get("last_incremental_key")
    if not isinstance(key_iso, str) or not key_iso:
        return cursor
    parsed = datetime.fromisoformat(key_iso)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TimezoneNaiveError(
            f"stored cursor last_incremental_key is tz-naive: {key_iso!r}"
        )
    adjusted = parsed - timedelta(seconds=window_seconds)
    return {**cursor, "last_incremental_key": adjusted.isoformat()}


def _chunked(
    gen: Iterator[dict[str, object]], size: int
) -> Generator[list[dict[str, object]], None, None]:
    """Chunk a generator of records into lists of ``size``.

    Final chunk may be smaller. Does NOT re-invoke the producer; consumes
    its generator exactly once. PATCH-NR-2: ``finally`` propagates
    ``.close()`` to the inner generator on any exit path.
    """
    batch: list[dict[str, object]] = []
    try:
        for rec in gen:
            batch.append(rec)
            if len(batch) >= size:
                yield batch
                batch = []
        if batch:
            yield batch
    finally:
        # Defensive close: at runtime ``stream_records`` is validated as a
        # generator function (PATCH-Q3) so it has ``.close()``; the
        # ``CIPConnector`` Protocol types it as ``Iterator`` (no close()).
        close = getattr(gen, "close", None)
        if close is not None:
            close()


def _dedupe_by_source_id(
    batch: list[dict[str, object]],
) -> list[dict[str, object]]:
    """H-11 + v4 (Round-3 CRIT-2): keep only the LAST occurrence of each
    source_id within the batch (last-write-wins for SCD-2). Output preserves
    ascending original-position order (source_id ordering for FOR UPDATE).
    """
    seen_idx: dict[str, int] = {}
    for i, rec in enumerate(batch):
        sid_obj = rec.get("source_id") or rec.get("id") or ""
        sid = str(sid_obj)
        if not sid:
            continue
        seen_idx[sid] = i  # last occurrence wins
    if not seen_idx:
        return list(batch)
    return [batch[i] for i in sorted(seen_idx.values())]


def _finalize(recorder: SyncRunRecorder) -> SyncRunState:
    """Build SyncRunState after the ``with recorder:`` block has exited.

    v3 R2-A2: MUST run AFTER ``__exit__``; reads ``recorder.final_status``
    and ``recorder.final_ended_at``, which are only set inside ``__exit__``.
    """
    return SyncRunState(
        run_id=recorder.run_id,
        batch_id=recorder.batch_id,
        status=cast(
            Literal["success", "partial", "failed"], recorder.final_status
        ),
        rows_received=recorder.counters.rows_received,
        rows_created=recorder.counters.rows_created,
        rows_updated=recorder.counters.rows_updated,
        rows_skipped_unchanged=recorder.counters.rows_skipped_unchanged,
        rows_skipped_drift=recorder.counters.rows_skipped_drift,
        rows_skipped_duplicate=recorder.counters.rows_skipped_duplicate,
        rows_history=recorder.counters.rows_history,
        started_at=recorder.started_at,
        ended_at=recorder.final_ended_at or _utcnow(),
        error_detail=recorder.counters.error_detail,
        cursor_state=recorder.counters.cursor_state,
    )
