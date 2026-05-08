# foundry: kind=service domain=client-intelligence-platform touches=integration
"""CIP Integration Mesh exception hierarchy (M2 binding).

Per plan v5.3 §4.2. Canonical home for ALL connector-framework exceptions —
``base.py`` imports lazily at use-site to avoid circular imports
(v5.2 Verifier HIGH fix: no duplicate class definitions).
"""
from __future__ import annotations


class ConnectorError(Exception):
    """Base class. Orchestrator catches this and routes by subtype."""


class AuthenticationError(ConnectorError):
    """Raised by ``connector.authenticate()`` on credential failure. Non-retryable."""


class RateLimitExceeded(ConnectorError):  # noqa: N818  # plan-binding name; "Error" suffix would break the public API
    """Raised by ``stream_records()`` when a source-system rate limit is hit.

    Orchestrator honors ``retry_after_seconds`` and backs off, capped at
    ``MAX_RATE_LIMIT_SLEEP_SECONDS`` (M-21).
    """

    def __init__(self, retry_after_seconds: float, *args: object) -> None:
        super().__init__(*args)
        self.retry_after_seconds = retry_after_seconds


class SchemaDriftError(ConnectorError):
    """Raised by ``mapper.map()`` when a record has a field the mapper doesn't understand.

    Orchestrator logs + skips the record (partial sync) instead of aborting the run.
    """


class PersistenceError(ConnectorError):
    """Raised by the row persister on DB errors.

    Orchestrator rolls back the batch transaction and increments
    ``consecutive_batch_failures`` (H-8). All ``SQLAlchemyError`` subclasses
    are translated into this single exception type at the persister boundary.
    """


class TimezoneNaiveError(ConnectorError):
    """v3 (R2-C1) / v5 PATCH-NR-7. tz-naive datetime crossed a framework boundary.

    Raised when a connector returns a tz-naive datetime from
    ``incremental_key()``, when a stored cursor's ``last_incremental_key``
    is tz-naive, or when ``KnowledgeText.metadata`` carries a tz-naive
    ``extracted_at`` / ``record_updated_at``.

    Silently coercing tz-naive timestamps to UTC (or to local) would corrupt
    the cursor on DST transitions and cross-region retries — we'd either
    re-process records we've already ingested or miss records. Fail fast,
    fail loud. Connector authors MUST return tz-aware datetimes. Non-retryable.
    """


class KnowledgeMetadataValidationError(ValueError):
    """v5.2 Round-6 Call A. KnowledgeText emitted to the boundary missing one
    of the 5 required core metadata keys (``source_id``, ``source_system``,
    ``extracted_at``, ``tenant_id``, ``connector_version``).

    Raised by ``base.validate_knowledge_text_metadata()``. Inherits from
    ``ValueError`` — NOT ``ConnectorError`` — because this is a CIP-internal
    contract violation, not a connector author's fault. Mappers typically
    only know ``source_id``; the orchestrator finalizes the rest at
    boundary-crossing time. Non-retryable.
    """


class SyncAlreadyRunningError(ConnectorError):
    """M3 §4.7 — A run_sync for the same ``(tenant_id, connector_id)`` is
    already in flight.

    Raised by ``run_sync`` at entry when ``pg_try_advisory_lock`` returns
    false. The error is **run-fatal** — the second process should NOT retry;
    the first process is already producing the output the second would have
    produced. Operators can decide to wait + retry or alert; the caller of
    ``run_sync`` surfaces this to its caller (e.g., a scheduler).

    The advisory lock is session-scoped on a dedicated lock-holder
    connection; Postgres auto-releases the lock when the connection closes
    (orphan-safe under crash). No explicit cleanup procedure is needed for
    stale locks under graceful exits; SIGKILL relies on TCP keepalive
    timeouts (M3 §8.9).
    """


class SyncLockUnavailableError(ConnectorError):
    """M3 §4.7 — The lock-holder engine couldn't acquire a connection.

    Raised by ``run_sync`` when ``engine.connect()`` on the dedicated
    NullPool lock-holder engine fails (pool exhaustion, network failure,
    Postgres unreachable). Distinct from ``SyncAlreadyRunningError`` —
    THIS error is a transient infrastructure condition; callers MAY retry.

    The wrapped exception is preserved as ``__cause__`` for diagnosis.
    """
