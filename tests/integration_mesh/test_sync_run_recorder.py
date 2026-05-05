# foundry: kind=test domain=client-intelligence-platform
"""Unit tests for ``SyncRunRecorder`` (mock-based control flow).

DB-roundtrip behaviour against a real ``cip_sync_runs`` testcontainer
lives in the conformance harness (§5 ``test_sync_run_audit.py``).

These tests cover non-DB control flow:
  - status transition logic (success / partial / failed)
  - PATCH-Q4: ``__exit__`` UPDATE EXCLUDES ``cursor_state``
  - Delta 1: counter mapping (7 in-memory → 5 deployed)
  - own-connection guarantee (recorder uses ``engine.begin()``,
    never the caller's Session — §9 acceptance criterion #20)
  - finalize-failure does not swallow the original exception
  - ``_redact`` strips email PII
"""
from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import Engine

from cip.integration_mesh.sync_run_recorder import (
    SyncRunRecorder,
    _MutableCounters,
    _redact,
)


@pytest.fixture
def engine() -> MagicMock:
    return MagicMock()


def _make_recorder(engine: MagicMock) -> SyncRunRecorder:
    return SyncRunRecorder(
        cast(Engine, engine),
        tenant_id=uuid4(),
        client_id=None,
        connector_id="mock",
        connector_name="MockConnector",
        sync_mode="incremental",
    )


# ── __enter__ INSERT row with status='running' ───────────────────────────


class TestEnterInsert:
    def test_enter_inserts_running_row(self, engine: MagicMock) -> None:
        recorder = _make_recorder(engine)
        with recorder:
            pass
        # engine.begin() called twice: once at __enter__, once at __exit__.
        assert engine.begin.call_count == 2
        conn = engine.begin.return_value.__enter__.return_value
        # __enter__: SET LOCAL + INSERT = 2 execute calls
        # __exit__:  SET LOCAL + UPDATE = 2 execute calls
        # Total: 4 execute calls.
        assert conn.execute.call_count == 4
        insert_sql = str(conn.execute.call_args_list[1][0][0])
        assert "INSERT INTO cip_sync_runs" in insert_sql
        assert "'running'" in insert_sql
        # Delta 1 reconciliation: deployed schema uses `metadata`, not `run_metadata`.
        assert "metadata" in insert_sql
        assert "run_metadata" not in insert_sql


# ── status transitions on __exit__ ───────────────────────────────────────


class TestExitStatusTransitions:
    def test_no_exception_no_error_detail_success(
        self, engine: MagicMock
    ) -> None:
        recorder = _make_recorder(engine)
        with recorder:
            pass
        assert recorder.final_status == "success"
        assert recorder.final_ended_at is not None
        assert recorder.counters.error_detail is None

    def test_exception_failed(self, engine: MagicMock) -> None:
        recorder = _make_recorder(engine)
        with pytest.raises(RuntimeError), recorder:
            raise RuntimeError("boom")
        assert recorder.final_status == "failed"
        assert recorder.counters.error_detail is not None
        assert recorder.counters.error_detail["type"] == "RuntimeError"
        assert "boom" in str(recorder.counters.error_detail["message"])

    def test_error_detail_set_partial(self, engine: MagicMock) -> None:
        recorder = _make_recorder(engine)
        with recorder:
            recorder.counters.error_detail = {
                "type": "PersistenceError",
                "message": "batch 3 failed",
            }
        assert recorder.final_status == "partial"


# ── PATCH-Q4: __exit__ UPDATE excludes cursor_state ──────────────────────


class TestPatchQ4ExcludesCursorState:
    def test_exit_update_does_not_touch_cursor_state(
        self, engine: MagicMock
    ) -> None:
        # v5 PATCH-Q4 (Round-4 panel SEV-5): recorder must NOT clobber
        # cursor_state on __exit__. The orchestrator main loop owns
        # cursor_state writes per-batch.
        recorder = _make_recorder(engine)
        with recorder:
            pass
        conn = engine.begin.return_value.__enter__.return_value
        # __exit__'s UPDATE is the LAST execute call.
        update_sql = str(conn.execute.call_args_list[-1][0][0])
        assert "UPDATE cip_sync_runs" in update_sql
        # Critical: the SET clause must NOT touch cursor_state.
        assert "cursor_state" not in update_sql


# ── Delta 1: counter mapping (7 in-memory → 5 deployed) ──────────────────


class TestDelta1CounterMapping:
    def test_internal_seven_collapse_to_deployed_five(
        self, engine: MagicMock
    ) -> None:
        # Mapping per Delta 1 reconciliation:
        #   rows_ingested = rows_created + rows_updated
        #   rows_skipped  = rows_skipped_unchanged + drift + duplicate
        #   rows_created/rows_updated/rows_history = 1:1
        recorder = _make_recorder(engine)
        with recorder:
            recorder.counters.rows_received = 99  # in-memory only
            recorder.counters.rows_created = 5
            recorder.counters.rows_updated = 3
            recorder.counters.rows_skipped_unchanged = 2
            recorder.counters.rows_skipped_drift = 1
            recorder.counters.rows_skipped_duplicate = 4
            recorder.counters.rows_history = 3

        conn = engine.begin.return_value.__enter__.return_value
        update_call = conn.execute.call_args_list[-1]
        params = update_call[0][1]
        # Mapped counters
        assert params["rows_ingested"] == 8  # 5 + 3
        assert params["rows_skipped"] == 7  # 2 + 1 + 4
        assert params["rows_created"] == 5
        assert params["rows_updated"] == 3
        assert params["rows_history"] == 3
        # Granular counters NOT in the deployed schema → not in params.
        assert "rows_received" not in params
        assert "rows_skipped_unchanged" not in params
        assert "rows_skipped_drift" not in params
        assert "rows_skipped_duplicate" not in params


# ── Own-connection guarantee (§9 acceptance #20) ─────────────────────────


class TestOwnConnection:
    def test_recorder_uses_engine_begin(self, engine: MagicMock) -> None:
        recorder = _make_recorder(engine)
        with recorder:
            pass
        # Each begin() opens a fresh short-lived connection.
        assert engine.begin.call_count == 2  # __enter__ + __exit__
        # No bypass paths — recorder must NOT call engine.connect() etc.
        assert not engine.connect.called

    def test_run_id_and_batch_id_distinct_uuids(
        self, engine: MagicMock
    ) -> None:
        # batch_id has UNIQUE constraint on cip_sync_runs; run_id is the PK.
        recorder1 = _make_recorder(engine)
        recorder2 = _make_recorder(engine)
        assert isinstance(recorder1.run_id, UUID)
        assert isinstance(recorder1.batch_id, UUID)
        assert recorder1.run_id != recorder2.run_id
        assert recorder1.batch_id != recorder2.batch_id


# ── Finalize-failure does not swallow original exception ─────────────────


class TestFinalizeFailureNonSwallowing:
    def test_finalize_failure_logged_original_propagates(
        self, engine: MagicMock
    ) -> None:
        # If the __exit__ UPDATE itself raises, we log it but don't suppress
        # the original exception that was being raised through the with-block.
        # H-15 guard.
        # Make begin() succeed for __enter__ but fail for __exit__.
        call_count = {"n": 0}

        class FakeBegin:
            def __enter__(self) -> MagicMock:
                call_count["n"] += 1
                if call_count["n"] == 2:
                    raise RuntimeError("finalize-update-failed")
                return MagicMock()

            def __exit__(self, *a: object) -> None:
                pass

        engine.begin.side_effect = lambda: FakeBegin()

        recorder = _make_recorder(engine)
        with pytest.raises(ValueError, match="original"), recorder:
            raise ValueError("original")
        # The original exception propagated; recorder swallowed only the
        # finalize failure.


# ── _redact ──────────────────────────────────────────────────────────────


class TestRedact:
    def test_email_redacted(self) -> None:
        msg = "contact alice@example.com failed"
        redacted = _redact(msg)
        assert "<email-redacted>" in redacted
        assert "alice@example.com" not in redacted

    def test_truncates_long(self) -> None:
        long_msg = "x" * 5000
        assert len(_redact(long_msg)) == 2000

    def test_no_email_unchanged(self) -> None:
        assert _redact("simple message") == "simple message"


def test_mutable_counters_dataclass_defaults() -> None:
    c = _MutableCounters()
    assert c.rows_received == 0
    assert c.rows_created == 0
    assert c.rows_updated == 0
    assert c.rows_skipped_unchanged == 0
    assert c.rows_skipped_drift == 0
    assert c.rows_skipped_duplicate == 0
    assert c.rows_history == 0
    assert c.error_detail is None
    assert c.cursor_state is None
