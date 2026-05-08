# foundry: kind=test domain=client-intelligence-platform
"""M3 8th conformance test — concurrent-sync advisory-lock dual-run prevention.

Eight sub-tests covering the full advisory-lock contract (M3 §4.8 + §9 #19):

  1. ``test_concurrent_sync_blocked_by_advisory_lock`` — load-bearing race:
     two run_sync processes on the same (tenant, connector) → exactly one
     blocks with ``SyncAlreadyRunningError``.
  2. ``test_serial_runs_on_same_tenant_connector_both_succeed`` — sanity:
     sequential runs on the same key both succeed (lock is session-scope
     and auto-released on connection close).
  3. ``test_concurrent_sync_different_tenant_succeeds`` — acceptance #19:
     different tenants don't share a lock; both runs succeed.
  4. ``test_concurrent_sync_different_connector_succeeds`` — connector_id
     is part of the key; different connectors run concurrently fine.
  5. ``test_lock_held_during_run`` — lock is held for the ENTIRE run, not
     just acquired+released momentarily. Uses a slow stream_records to
     widen the window, then probes pg_try_advisory_lock from a side
     connection.
  6. ``test_lock_release_on_exception`` — when run_sync's body raises,
     the finally block releases the lock; a subsequent run_sync on the
     same key succeeds.
  7. ``test_advisory_lock_released_after_run`` — after a clean run_sync,
     pg_try_advisory_lock on the same key from a fresh session succeeds
     (no orphan lock).
  8. ``test_lock_holder_engine_nullpool_no_reuse`` — NullPool guarantee:
     two ``connect()`` cycles on the lock-holder engine produce different
     backend PIDs (no connection pooling, every acquire is fresh).

Stdlib ``multiprocessing`` (NOT pytest-mp) for explicit process-spawn
control. ``mp.get_context("spawn")`` for cross-platform consistency.
``_child_run_sync`` is module-level (spawn pickles the target function;
nested closures crash with PicklingError before barrier fires — v2 #5 fix).
"""
from __future__ import annotations

import multiprocessing as mp
import threading
import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool


def _child_run_sync(
    result_queue: Any,  # mp.Queue[tuple[str, str]]
    barrier: Any,  # mp.Barrier
    db_url: str,
    tenant_id: str,
    connector_id_suffix: str,
    seed: int,
) -> None:
    """Module-level child entry-point for the spawn-context multiprocess race.

    MUST be module-level (not a nested closure) — ``spawn`` pickles the
    target callable; closures aren't picklable and would crash with
    ``PicklingError`` before the barrier fires (v2 #5).

    Each child opens its own engine + sessions (multiprocessing fixtures
    are per-process; cross-process connection sharing is unsafe).

    Reports outcome via ``result_queue.put((status, message))``:
      - ``("ok", "")`` on successful completion
      - ``("blocked", reason)`` on ``SyncAlreadyRunningError``
      - ``("error", "<ExceptionClass>: <message>")`` on any other failure
      - ``("barrier_timeout", reason)`` if barrier.wait raised
    """
    # Imports inside the child so ``spawn``-context children don't inherit
    # parent state; each child re-bootstraps the framework cleanly.
    from sqlalchemy import create_engine

    from cip.integration_mesh import (
        CorpusSize,
        FixtureConnector,
        FixtureMapper,
        run_sync,
    )
    from cip.integration_mesh.exceptions import SyncAlreadyRunningError

    try:
        barrier.wait(timeout=30)
    except Exception as barrier_err:
        result_queue.put(("barrier_timeout", str(barrier_err)))
        return

    engine = create_engine(db_url)
    try:
        connector = FixtureConnector(
            tenant_id=UUID(tenant_id),
            seed=seed,
            size=CorpusSize.SMOKE,
        )
        # Suffix lets the "different connector" sub-test vary connector_id.
        if connector_id_suffix:
            connector.connector_id = (
                f"fixture-connector-v1{connector_id_suffix}"
            )
        mapper = FixtureMapper()
        try:
            run_sync(
                connector,
                mapper,
                engine,
                tenant_id=UUID(tenant_id),
                database_url=db_url,
            )
            result_queue.put(("ok", ""))
        except SyncAlreadyRunningError as e:
            result_queue.put(("blocked", str(e)))
        except Exception as unexpected:
            result_queue.put(
                ("error", f"{type(unexpected).__name__}: {unexpected}")
            )
    finally:
        engine.dispose()


def _drain_queue(queue: Any) -> list[tuple[str, str]]:
    """Drain a multiprocessing.Queue into a list. Blocks until queue is
    empty (children have already joined by the time we drain)."""
    results: list[tuple[str, str]] = []
    while not queue.empty():
        results.append(queue.get_nowait())
    return results


def _spawn_race(
    db_url: str,
    *,
    tenant_id_a: str,
    tenant_id_b: str,
    suffix_a: str,
    suffix_b: str,
    seed_a: int = 42,
    seed_b: int = 42,
) -> list[tuple[str, str]]:
    """Spawn two children with caller-controlled (tenant_id, suffix, seed)
    pairs and run them through the shared barrier-synchronized race.
    Returns the drained result list. Used by sub-tests 3 + 4."""
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    queue: Any = ctx.Queue()
    p1 = ctx.Process(
        target=_child_run_sync,
        args=(queue, barrier, db_url, tenant_id_a, suffix_a, seed_a),
    )
    p2 = ctx.Process(
        target=_child_run_sync,
        args=(queue, barrier, db_url, tenant_id_b, suffix_b, seed_b),
    )
    p1.start()
    p2.start()
    p1.join(timeout=120)
    p2.join(timeout=120)
    for p in (p1, p2):
        if p.is_alive():
            p.terminate()
            p.join(5)
            if p.is_alive():
                p.kill()
    return _drain_queue(queue)


# ── Sub-test 1 (load-bearing race) ──────────────────────────────────────


def test_concurrent_sync_blocked_by_advisory_lock(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """Two run_sync processes race on the same (tenant_id, connector_id).
    Advisory lock serializes: exactly one succeeds, exactly one is blocked.
    """
    tenant_id = str(uuid4())
    results = _spawn_race(
        database_url,
        tenant_id_a=tenant_id,
        tenant_id_b=tenant_id,
        suffix_a="",
        suffix_b="",
    )
    statuses = sorted(r[0] for r in results)
    assert len(results) == 2, f"expected 2 results, got {results}"
    assert statuses == ["blocked", "ok"], (
        f"expected exactly one 'ok' + one 'blocked', got {results}"
    )


# ── Sub-test 2 (sequential sanity) ──────────────────────────────────────


def test_serial_runs_on_same_tenant_connector_both_succeed(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """Sanity: running two syncs SEQUENTIALLY on the same (tenant, connector)
    both succeed. Advisory lock blocks CONCURRENT only, not sequential —
    Postgres auto-releases the session-scoped lock when the connection
    closes (orphan-safe), so the second run's lock acquisition succeeds.
    """
    from cip.integration_mesh import (
        CorpusSize,
        FixtureConnector,
        FixtureMapper,
        run_sync,
    )

    tenant_id = uuid4()
    state1 = run_sync(
        FixtureConnector(tenant_id=tenant_id, seed=42, size=CorpusSize.SMOKE),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
    )
    state2 = run_sync(
        FixtureConnector(tenant_id=tenant_id, seed=42, size=CorpusSize.SMOKE),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
    )
    assert state1.status == "success"
    assert state2.status == "success"
    # Distinct run_ids prove two separate run_sync invocations.
    assert state1.run_id != state2.run_id


# ── Sub-test 3 (different tenants — acceptance #19) ─────────────────────


def test_concurrent_sync_different_tenant_succeeds(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """Acceptance #19: different tenants do NOT share an advisory lock.
    Two concurrent run_sync calls on the same connector but different
    tenant_ids both succeed (lock keys differ → no serialization).
    """
    tid_a = str(uuid4())
    tid_b = str(uuid4())
    results = _spawn_race(
        database_url,
        tenant_id_a=tid_a,
        tenant_id_b=tid_b,
        suffix_a="",
        suffix_b="",
    )
    statuses = sorted(r[0] for r in results)
    assert len(results) == 2, f"expected 2 results, got {results}"
    assert statuses == ["ok", "ok"], (
        f"different tenants must not share a lock; got {results}"
    )


# ── Sub-test 4 (different connectors — connector_id is part of the key) ─


def test_concurrent_sync_different_connector_succeeds(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """connector_id is part of the lock-key derivation. Two concurrent
    run_sync calls on the same tenant but different connector_ids both
    succeed — they hash to different advisory-lock keys.
    """
    tenant_id = str(uuid4())
    results = _spawn_race(
        database_url,
        tenant_id_a=tenant_id,
        tenant_id_b=tenant_id,
        suffix_a="-alpha",
        suffix_b="-beta",
    )
    statuses = sorted(r[0] for r in results)
    assert len(results) == 2, f"expected 2 results, got {results}"
    assert statuses == ["ok", "ok"], (
        f"different connector_ids must not share a lock; got {results}"
    )


# ── Sub-test 5 (mid-run hold — lock held for the entire run body) ───────


def test_lock_held_during_run(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """The lock is held for the ENTIRE run_sync body, not just briefly
    around acquire/release. We slow stream_records (single in-process
    thread), then probe pg_try_advisory_lock from a side connection
    while the run is mid-flight — must return False.
    """
    from cip.integration_mesh import (
        CorpusSize,
        FixtureConnector,
        FixtureMapper,
        run_sync,
    )
    from cip.integration_mesh.orchestrator import _advisory_lock_key

    class _SlowConnector(FixtureConnector):
        """Sleep before yielding so the run body holds the lock for ~3s."""

        def stream_records(
            self,
            cursor: dict[str, object] | None,
            batch_size: int,
        ) -> Iterator[dict[str, object]]:
            time.sleep(3.0)
            yield from super().stream_records(cursor, batch_size)

    tenant_id = uuid4()
    connector = _SlowConnector(
        tenant_id=tenant_id, seed=42, size=CorpusSize.SMOKE
    )

    completed = threading.Event()
    failure: list[BaseException] = []

    def _runner() -> None:
        try:
            run_sync(
                connector,
                FixtureMapper(),
                seeded_engine,
                tenant_id=tenant_id,
                database_url=database_url,
            )
        except BaseException as e:  # noqa: BLE001
            failure.append(e)
        finally:
            completed.set()

    t = threading.Thread(target=_runner, daemon=True)
    t.start()

    # Wait for the runner to enter the lock + reach the 3s sleep. 0.8s gives
    # a comfortable margin while the slow stream is still mid-flight.
    time.sleep(0.8)
    assert not completed.is_set(), (
        "runner finished too early; widen the slow-stream sleep"
    )

    # Probe pg_try_advisory_lock from a separate connection. If the lock
    # is held by the runner (correct behaviour), this returns False.
    key = _advisory_lock_key(tenant_id, connector.connector_id)
    side_engine = create_engine(database_url)
    try:
        with side_engine.connect() as conn:
            res = conn.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            ).scalar()
        assert res is False, (
            "advisory lock must be held during run_sync body, "
            f"but pg_try_advisory_lock returned {res}"
        )
    finally:
        side_engine.dispose()

    t.join(timeout=15)
    assert not t.is_alive(), "runner thread did not finish within 15s"
    assert not failure, f"runner raised: {failure[0]!r}"


# ── Sub-test 6 (lock release on body exception) ─────────────────────────


def test_lock_release_on_exception(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """Plan §4.8: when run_sync's body raises, the lock auto-releases via
    the context manager's finally. Verified end-to-end by running a
    second, normal run_sync on the same (tenant, connector) AFTER the
    raising run — the second run must succeed (lock was freed).
    """
    from cip.integration_mesh import (
        CorpusSize,
        FixtureConnector,
        FixtureMapper,
        run_sync,
    )

    class _RaisingConnector(FixtureConnector):
        """stream_records raises on first iteration, simulating a connector bug.

        ``yield from ()`` is the syntactic marker that makes this a real
        generator function (so ``validate_connector_shape``'s
        ``inspect.isgeneratorfunction`` check passes); the empty source
        yields nothing, then the raise fires — orchestrator sees the
        RuntimeError on its first ``next()`` call.
        """

        def stream_records(
            self,
            cursor: dict[str, object] | None,
            batch_size: int,
        ) -> Iterator[dict[str, object]]:
            yield from ()
            raise RuntimeError("simulated extract failure")

    tenant_id = uuid4()
    raising = _RaisingConnector(
        tenant_id=tenant_id, seed=42, size=CorpusSize.SMOKE
    )

    with pytest.raises(RuntimeError, match="simulated extract failure"):
        run_sync(
            raising,
            FixtureMapper(),
            seeded_engine,
            tenant_id=tenant_id,
            database_url=database_url,
        )

    # Second run on the same (tenant, connector) must succeed — proves the
    # lock was released by the prior run's finally block (otherwise this
    # call would block on the stale lock).
    state = run_sync(
        FixtureConnector(tenant_id=tenant_id, seed=42, size=CorpusSize.SMOKE),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    assert state.status == "success"


# ── Sub-test 7 (no orphan lock after a clean run) ───────────────────────


def test_advisory_lock_released_after_run(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """After a clean run_sync, the advisory lock is released. Verified
    by acquiring the same key from a fresh side session — pg_try_advisory_lock
    returns True (would return False if the lock was orphaned).
    """
    from cip.integration_mesh import (
        CorpusSize,
        FixtureConnector,
        FixtureMapper,
        run_sync,
    )
    from cip.integration_mesh.orchestrator import _advisory_lock_key

    tenant_id = uuid4()
    connector = FixtureConnector(
        tenant_id=tenant_id, seed=42, size=CorpusSize.SMOKE
    )
    state = run_sync(
        connector,
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    assert state.status == "success"

    key = _advisory_lock_key(tenant_id, connector.connector_id)
    side_engine = create_engine(database_url)
    try:
        with side_engine.connect() as conn:
            acquired = conn.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            ).scalar()
            assert acquired is True, (
                "advisory lock should be released after run_sync; "
                f"pg_try_advisory_lock returned {acquired}"
            )
            # Clean up the side-session lock so we leave Postgres in a
            # neutral state for subsequent tests.
            conn.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": key}
            )
    finally:
        side_engine.dispose()


# ── Sub-test 8 (NullPool guarantee — no connection reuse) ───────────────


def test_lock_holder_engine_nullpool_no_reuse(
    database_url: str,
) -> None:
    """Plan §2.4 + §4.8: lock-holder engine MUST use NullPool so each
    acquire opens a fresh physical connection (and dispose closes it,
    releasing the session-scope lock). Verified end-to-end against a
    real Postgres: two ``connect()`` cycles produce different
    ``pg_backend_pid()`` values. A pooled engine would reuse the same
    backend.
    """
    from cip.integration_mesh.orchestrator import _make_lock_holder_engine

    eng = _make_lock_holder_engine(database_url)
    try:
        assert isinstance(eng.pool, NullPool), (
            f"lock-holder engine must use NullPool, got {type(eng.pool).__name__}"
        )
        with eng.connect() as c1:
            pid1 = c1.execute(text("SELECT pg_backend_pid()")).scalar()
        with eng.connect() as c2:
            pid2 = c2.execute(text("SELECT pg_backend_pid()")).scalar()
        assert pid1 != pid2, (
            f"NullPool must NOT reuse connections; got pid1={pid1} pid2={pid2}"
        )
    finally:
        eng.dispose()
