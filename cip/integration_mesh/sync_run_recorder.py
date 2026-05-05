# foundry: kind=service domain=client-intelligence-platform touches=integration
"""SyncRunRecorder context manager for the cip_sync_runs lifecycle (M2 §4.7 binding).

On ``__enter__`` INSERTs a ``cip_sync_runs`` row with ``status='running'``.
On ``__exit__`` UPDATEs ``status`` + counters + ``ended_at``.

The recorder owns its own short-lived connections (``engine.begin()``
auto-commits on exit) for both writes — does NOT share the orchestrator's
``Session``. Each connection applies tenant context inside its txn so RLS
on ``cip_sync_runs`` passes (D-026 + D-127).

v5 PATCH-Q4 (Round-4 panel SEV-5): ``__exit__`` UPDATE explicitly EXCLUDES
``cursor_state``. The orchestrator main loop writes ``cursor_state``
inside each per-batch transaction; recorder must not clobber the latest
cursor advance.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .tenant_context import apply_tenant_context

log = logging.getLogger(__name__)


@dataclass
class _MutableCounters:
    """Counter slots the orchestrator updates per record / batch.

    The orchestrator keeps the granular 7-counter set in memory for
    structured logging; the recorder collapses to the deployed 5 columns
    at write-time (Delta 1 reconciliation, see ``__exit__``).
    """

    rows_received: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    rows_skipped_unchanged: int = 0
    rows_skipped_drift: int = 0
    rows_skipped_duplicate: int = 0
    rows_history: int = 0
    error_detail: dict[str, object] | None = None
    # Mutable slot the orchestrator writes each time it advances the cursor
    # inside a batch txn. ``_finalize()`` reads this after the
    # ``with recorder:`` block exits to build the immutable ``SyncRunState``.
    cursor_state: dict[str, object] | None = None


# Best-effort PII redaction. Mirrors the orchestrator's _redact pattern
# (keep in sync if either changes).
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _redact(msg: str) -> str:
    """Best-effort redaction of email PII patterns + length cap."""
    return _EMAIL_RE.sub("<email-redacted>", msg)[:2000]


class SyncRunRecorder:
    """Context manager for the ``cip_sync_runs`` row lifecycle.

    Usage::

        with SyncRunRecorder(
            engine,
            tenant_id=...,
            client_id=...,
            connector_id=...,
            connector_name=...,
            sync_mode="incremental",
        ) as run:
            run.counters.rows_received += 1
            run.counters.cursor_state = {"last_incremental_key": "..."}

    On exception, ``__exit__`` records ``status='failed'`` with
    ``error_detail`` populated. If the caller manually sets
    ``run.counters.error_detail`` without raising, ``status='partial'``.
    Otherwise ``status='success'``.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        tenant_id: UUID,
        client_id: UUID | None,
        connector_id: str,
        connector_name: str,
        sync_mode: str,
    ) -> None:
        self.engine = engine
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.connector_id = connector_id
        self.connector_name = connector_name
        self.sync_mode = sync_mode
        self.run_id: UUID = uuid4()
        self.batch_id: UUID = uuid4()
        self.started_at: datetime = datetime.now(UTC)
        self.counters = _MutableCounters()
        # Set in __exit__; orchestrator reads them after ``with recorder:``.
        self.final_status: str = "running"
        self.final_ended_at: datetime | None = None

    def __enter__(self) -> Self:
        # v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 1, 2026-04-29)
        # Plan §4.7 R2-A3 specifies: `run_metadata` (after the cip_11 rename).
        # Deployed schema (cip_03_sync_runs): `metadata` column name.
        # Reconciliation: write `metadata` directly (R2-A3 fallback path —
        # the plan itself documents this as the no-rename alternative).
        # Rationale: P-22 / D-123 — migrations are authoritative.
        # Atlas v5.4 TODO: update plan §4.7 to keep `metadata` column name.
        with self.engine.begin() as conn:
            apply_tenant_context(conn, self.tenant_id)
            conn.execute(
                text(
                    """
                    INSERT INTO cip_sync_runs (
                        id, tenant_id, client_id, connector_id, connector_name,
                        batch_id, sync_mode, status, started_at, metadata
                    ) VALUES (
                        :id, :tenant_id, :client_id, :connector_id, :connector_name,
                        :batch_id, :sync_mode, 'running', :started_at,
                        CAST('{}' AS jsonb)
                    )
                    """
                ),
                {
                    "id": str(self.run_id),
                    "tenant_id": str(self.tenant_id),
                    "client_id": str(self.client_id) if self.client_id else None,
                    "connector_id": self.connector_id,
                    "connector_name": self.connector_name,
                    "batch_id": str(self.batch_id),
                    "sync_mode": self.sync_mode,
                    "started_at": self.started_at,
                },
            )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        ended_at = datetime.now(UTC)
        if exc_type is not None:
            status = "failed"
            # Sanitize: never write raw exception repr that could contain
            # record PII (QC Gap Cat 7).
            self.counters.error_detail = {
                "type": exc_type.__name__,
                "message": _redact(str(exc_val)),
            }
        elif self.counters.error_detail is not None:
            status = "partial"
        else:
            status = "success"

        self.final_status = status
        self.final_ended_at = ended_at

        # v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 1 — counter mapping)
        # Plan §4.7 expects 7 deployed counter columns (rows_received,
        # rows_created, rows_updated, rows_skipped_unchanged,
        # rows_skipped_drift, rows_skipped_duplicate, rows_history).
        # Deployed schema (cip_03_sync_runs): 5 columns (rows_ingested,
        # rows_history, rows_created, rows_updated, rows_skipped).
        # Reconciliation:
        #   rows_ingested = rows_created + rows_updated
        #   rows_skipped  = rows_skipped_unchanged + drift + duplicate
        #   rows_created / rows_updated / rows_history = 1:1
        # The granular 7 stay in-memory for orchestrator-side structured
        # logging; the SQL UPDATE collapses to the deployed 5.
        # Rationale: P-22 / D-123 — migrations are authoritative.
        # Atlas v5.4 TODO: update plan §4.7 to document deployed 5-counter shape.
        rows_ingested = (
            self.counters.rows_created + self.counters.rows_updated
        )
        rows_skipped = (
            self.counters.rows_skipped_unchanged
            + self.counters.rows_skipped_drift
            + self.counters.rows_skipped_duplicate
        )

        # v5 PATCH-Q4 (Round-4 panel SEV-5, mandatory): UPDATE explicitly
        # EXCLUDES cursor_state. The orchestrator main loop writes
        # cursor_state inside each batch's transaction (§4.8 per-batch cursor
        # write); recorder must not touch it. Recorder OWNS: status,
        # ended_at, error_detail, all rows_* counters. Recorder does NOT OWN:
        # cursor_state, batch_id (set at __enter__ INSERT and immutable).
        # Do not re-add cursor_state to the UPDATE column list on regression.
        try:
            with self.engine.begin() as conn:
                apply_tenant_context(conn, self.tenant_id)
                conn.execute(
                    text(
                        """
                        UPDATE cip_sync_runs
                        SET status = :status,
                            ended_at = :ended_at,
                            rows_ingested = :rows_ingested,
                            rows_history = :rows_history,
                            rows_created = :rows_created,
                            rows_updated = :rows_updated,
                            rows_skipped = :rows_skipped,
                            error_detail = CAST(:error_detail AS jsonb)
                        WHERE id = :id
                        """
                    ),
                    {
                        "status": status,
                        "ended_at": ended_at,
                        "rows_ingested": rows_ingested,
                        "rows_history": self.counters.rows_history,
                        "rows_created": self.counters.rows_created,
                        "rows_updated": self.counters.rows_updated,
                        "rows_skipped": rows_skipped,
                        "error_detail": (
                            None
                            if self.counters.error_detail is None
                            else json.dumps(
                                self.counters.error_detail, default=str
                            )
                        ),
                        "id": str(self.run_id),
                    },
                )
        except Exception as finalize_err:
            # H-15: never swallow the primary exception; log finalize failures
            # so the cip_sync_runs row stays 'running' for operator triage.
            log.error(
                "sync_run finalize UPDATE failed (cip_sync_runs row stays "
                "'running'): %s",
                finalize_err,
            )
        # Do NOT suppress original exception — return None implicitly.
