# foundry: kind=test domain=client-intelligence-platform
"""M3 unit tests for advisory-lock helpers (M3 §6 / plan §4.8).

Mock-based tests of ``_advisory_lock_key`` + ``_AdvisoryLockHeld`` +
``_make_lock_holder_engine``. Real-DB advisory-lock behaviour (concurrent
race, mid-run hold, NullPool guarantee) lives in
``tests/fixtures/connector_conformance/test_concurrent_sync_advisory_lock.py``.
"""
from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from cip.integration_mesh.exceptions import (
    SyncAlreadyRunningError,
    SyncLockUnavailableError,
)
from cip.integration_mesh.orchestrator import (
    _advisory_lock_key,
    _AdvisoryLockHeld,
    _make_lock_holder_engine,
)

# ── _advisory_lock_key ──────────────────────────────────────────────────


class TestAdvisoryLockKey:
    def test_lock_key_is_stable(self) -> None:
        # Same input → same output (across runs, processes, machines).
        tid = uuid4()
        cid = "fixture-connector-v1"
        a = _advisory_lock_key(tid, cid)
        b = _advisory_lock_key(tid, cid)
        assert a == b

    def test_lock_key_is_signed_bigint_range(self) -> None:
        # Postgres pg_try_advisory_lock(BIGINT) is signed 8-byte int range.
        tid = uuid4()
        key = _advisory_lock_key(tid, "fixture-connector-v1")
        assert -(2**63) <= key <= (2**63) - 1

    def test_different_inputs_yield_different_keys(self) -> None:
        tid = uuid4()
        a = _advisory_lock_key(tid, "x")
        b = _advisory_lock_key(tid, "y")
        c = _advisory_lock_key(uuid4(), "x")
        assert a != b
        assert a != c

    def test_different_tenants_same_connector_different_keys(self) -> None:
        # Acceptance #19: different tenants don't share a lock.
        tid_a = uuid4()
        tid_b = uuid4()
        cid = "fixture-connector-v1"
        assert _advisory_lock_key(tid_a, cid) != _advisory_lock_key(tid_b, cid)


# ── _make_lock_holder_engine ────────────────────────────────────────────


class TestMakeLockHolderEngine:
    def test_uses_nullpool(self) -> None:
        # Plan §2.4: lock-holder MUST use NullPool to bypass any pool /
        # PgBouncer routing. This is a mandatory M3 invariant.
        eng = _make_lock_holder_engine(
            "postgresql+psycopg://u:p@localhost:5432/test"
        )
        try:
            assert isinstance(eng.pool, NullPool)
        finally:
            eng.dispose()

    def test_keepalive_args_passed_to_create_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Plan §2.4: TCP keepalives defeat cloud-Postgres idle reaping.
        # Verify by intercepting sa.create_engine and capturing kwargs.
        captured: dict[str, object] = {}

        def _fake_create_engine(url: object, **kwargs: object) -> MagicMock:
            captured["url"] = url
            captured.update(kwargs)
            return MagicMock(spec=sa.Engine)

        monkeypatch.setattr(
            "cip.integration_mesh.orchestrator.sa.create_engine",
            _fake_create_engine,
        )
        _make_lock_holder_engine("postgresql+psycopg://u:p@localhost/db")
        assert captured.get("poolclass") is NullPool
        connect_args = captured.get("connect_args")
        assert connect_args == {
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        }


# ── _AdvisoryLockHeld ────────────────────────────────────────────────────


def _make_lock_engine_mock(
    *,
    pg_try_returns: object = True,
    connect_raises: Exception | None = None,
    unlock_raises: Exception | None = None,
) -> MagicMock:
    """Build a MagicMock 'engine' whose ``connect()`` returns a Connection
    whose ``execute(text, ...).scalar()`` returns ``pg_try_returns`` for
    ``pg_try_advisory_lock`` and raises ``unlock_raises`` for
    ``pg_advisory_unlock`` (or None to no-op)."""
    eng = MagicMock(spec=sa.Engine)
    if connect_raises is not None:
        eng.connect.side_effect = connect_raises
        return eng

    conn = MagicMock()

    def _execute(stmt: Any, params: Any = None) -> Any:
        sql_str = str(stmt)
        result = MagicMock()
        if "pg_try_advisory_lock" in sql_str:
            result.scalar.return_value = pg_try_returns
        elif "pg_advisory_unlock" in sql_str:
            if unlock_raises is not None:
                raise unlock_raises
            result.scalar.return_value = True
        return result

    conn.execute.side_effect = _execute
    eng.connect.return_value = conn
    return eng


class TestAdvisoryLockHeld:
    def test_acquires_and_releases_happy_path(self) -> None:
        eng = _make_lock_engine_mock(pg_try_returns=True)
        with _AdvisoryLockHeld(eng, uuid4(), "fixture-connector-v1") as conn:
            assert conn is not None
        # conn.close() called.
        eng.connect.return_value.close.assert_called()

    def test_raises_sync_already_running_on_failed_acquire(self) -> None:
        eng = _make_lock_engine_mock(pg_try_returns=False)
        with pytest.raises(
            SyncAlreadyRunningError, match="already in flight"
        ), _AdvisoryLockHeld(eng, uuid4(), "fixture-connector-v1"):
            pytest.fail("should not reach body")

    def test_raises_sync_lock_unavailable_on_null_result(self) -> None:
        # Postgres misconfiguration (extension shadowed, etc.).
        eng = _make_lock_engine_mock(pg_try_returns=None)
        with pytest.raises(
            SyncLockUnavailableError, match="returned NULL"
        ), _AdvisoryLockHeld(eng, uuid4(), "fixture-connector-v1"):
            pytest.fail("should not reach body")

    def test_raises_sync_lock_unavailable_on_connect_failure(self) -> None:
        # Pool exhaustion / network blip / Postgres unreachable.
        eng = _make_lock_engine_mock(
            connect_raises=sa.exc.OperationalError("stmt", {}, Exception("boom"))
        )
        with pytest.raises(
            SyncLockUnavailableError, match="failed to open lock-holder"
        ), _AdvisoryLockHeld(eng, uuid4(), "fixture-connector-v1"):
            pytest.fail("should not reach body")

    def test_releases_lock_on_exception_in_body(self) -> None:
        # Plan §4.8: lock auto-releases on body exception via finally.
        eng = _make_lock_engine_mock(pg_try_returns=True)
        with pytest.raises(
            RuntimeError, match="boom"
        ), _AdvisoryLockHeld(eng, uuid4(), "fixture-connector-v1"):
            raise RuntimeError("boom")
        # conn.close() still called.
        eng.connect.return_value.close.assert_called()
        # pg_advisory_unlock still attempted on the way out.
        execute_calls = eng.connect.return_value.execute.call_args_list
        unlock_calls = [
            c for c in execute_calls if "pg_advisory_unlock" in str(c[0][0])
        ]
        assert len(unlock_calls) >= 1

    def test_swallows_unlock_errors_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Unlock failure is non-fatal — Postgres GCs the lock on conn close.
        eng = _make_lock_engine_mock(
            pg_try_returns=True,
            unlock_raises=RuntimeError("unlock blew up"),
        )
        with caplog.at_level(logging.WARNING), _AdvisoryLockHeld(
            eng, uuid4(), "fixture-connector-v1"
        ):
            pass
        assert any(
            "advisory unlock failed" in record.message for record in caplog.records
        )


# ── _AdvisoryLockHeld key derivation invariant ──────────────────────────


class TestLockKeyConsistency:
    def test_lock_uses_advisory_lock_key_for_key_derivation(self) -> None:
        # Verify the key bound to pg_try_advisory_lock equals the helper output.
        tid = uuid4()
        cid = "fixture-connector-v1"
        eng = _make_lock_engine_mock(pg_try_returns=True)
        with _AdvisoryLockHeld(eng, tid, cid):
            pass
        # Inspect the bind params on the pg_try_advisory_lock call.
        execute_calls = eng.connect.return_value.execute.call_args_list
        lock_calls = [
            c for c in execute_calls if "pg_try_advisory_lock" in str(c[0][0])
        ]
        assert len(lock_calls) == 1
        bound_params = lock_calls[0][0][1]
        assert bound_params == {"key": _advisory_lock_key(tid, cid)}


