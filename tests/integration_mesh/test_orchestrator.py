# foundry: kind=test domain=client-intelligence-platform
"""Unit tests for ``run_sync`` (M2 §4.8 binding).

DB-roundtrip orchestrator behavior against a real Postgres testcontainer
lives in the conformance harness (§5). These tests cover non-DB control
flow:
  - validate_connector_shape entry guard (C-5)
  - authenticate failure → AuthenticationError
  - happy-path counter increments matching reconciliation #2
  - SchemaDriftError → rows_skipped_drift increment, continue
  - PersistenceError + 3-consecutive-failure abort
  - RateLimitExceeded retry budget exhaustion
  - tz-naive incremental_key → TimezoneNaiveError run-fatal
  - tz-naive stored cursor → TimezoneNaiveError
  - metadata-finalize: setdefault for 3 mapper-may-know-better keys;
    detect-then-assign for tenant_id + ingestion_batch_id (Delta 8)
  - extracted_at hoisted outside per-text loop (Delta 9)
  - empty stream → success
  - _dedupe_by_source_id + rows_skipped_duplicate counter
  - knowledge-hook generic exception → log + continue (D-067)
  - _utcnow private helper (Delta 7)
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Literal, cast
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from cip.integration_mesh import orchestrator as orch_module
from cip.integration_mesh.base import (
    DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS,
    DEFAULT_RATE_LIMIT,
    CIPRow,
    KnowledgeText,
    KnowledgeTextMetadata,
    PropertyDescriptor,
    RateLimitPolicy,
)
from cip.integration_mesh.exceptions import (
    AuthenticationError,
    KnowledgeMetadataValidationError,
    PersistenceError,
    RateLimitExceeded,
    SchemaDriftError,
    TimezoneNaiveError,
)
from cip.integration_mesh.orchestrator import (
    _apply_safety_window,
    _dedupe_by_source_id,
    _utcnow,
    run_sync,
)
from cip.integration_mesh.persister import PersistResult

# ── Mock connector / mapper ────────────────────────────────────────────────


class MockConnector:
    """Minimal Protocol-conformant connector for orchestrator tests."""

    connector_id = "mock-connector"
    version = "1.2.3"

    def __init__(
        self,
        records: list[dict[str, object]] | None = None,
        *,
        schema: list[PropertyDescriptor] | None = None,
        rate_limit_policy: RateLimitPolicy | None = None,
        stream_exceptions: list[Exception] | None = None,
    ) -> None:
        self.tenant_id: UUID = uuid4()
        self._records = records or []
        self._schema = schema or []
        self._rl_policy = rate_limit_policy or DEFAULT_RATE_LIMIT
        self._stream_exceptions = stream_exceptions or []
        self.authenticated = False
        self.stream_records_call_count = 0

    @property
    def rate_limit_policy(self) -> RateLimitPolicy:
        return self._rl_policy

    @property
    def cursor_safety_window_seconds(self) -> int:
        return DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS

    def authenticate(self) -> None:
        self.authenticated = True

    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        self.stream_records_call_count += 1
        for ex in self._stream_exceptions:
            raise ex
        yield from self._records

    def describe_schema(self) -> list[PropertyDescriptor]:
        return self._schema

    def incremental_key(self, record: dict[str, object]) -> datetime:
        ts = record.get("updated_at")
        if isinstance(ts, datetime):
            return ts
        return datetime.fromisoformat(str(ts))


class MockMapper:
    object_type = "contact"
    target_table = "cip_contacts"

    def __init__(
        self,
        *,
        rows_per_record: int = 1,
        knowledge_metadata_factory: (
            Any | None
        ) = None,
        map_raises: type[Exception] | None = None,
        ingest_raises: type[Exception] | None = None,
    ) -> None:
        self.rows_per_record = rows_per_record
        self._knowledge_metadata_factory = knowledge_metadata_factory
        self._map_raises = map_raises
        self._ingest_raises = ingest_raises

    def map(self, record: dict[str, object]) -> Iterator[CIPRow]:
        if self._map_raises is not None:
            raise self._map_raises(f"drift on {record.get('id')!r}")
        for i in range(self.rows_per_record):
            yield CIPRow(
                target_table="cip_contacts",
                source_id=str(record["id"]) + (f"-{i}" if i else ""),
                fields={"email": record.get("email", "x@y.com")},
            )

    def overflow_fields(self) -> list[str]:
        return []

    def authority(
        self,
    ) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        if self._ingest_raises is not None:
            raise self._ingest_raises("ingest failed")
        if self._knowledge_metadata_factory is None:
            # Plan-correct default mock: emit ONLY source_id (no "lying mock"
            # placeholders for orchestrator-finalized keys).
            md: dict[str, object] = {"source_id": str(record["id"])}
        else:
            md = self._knowledge_metadata_factory(record)
        return [
            KnowledgeText(
                text=str(record.get("email", "")),
                metadata=cast(KnowledgeTextMetadata, md),
            )
        ]


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def engine() -> MagicMock:
    return MagicMock()


def _stub_session_and_persister(
    monkeypatch: pytest.MonkeyPatch,
    *,
    persist_result: PersistResult | list[PersistResult] | None = None,
    persist_raises: list[Exception | None] | None = None,
) -> MagicMock:
    """Patch ``Session`` + ``CIPRowPersister`` + the M3 advisory-lock helpers
    at the orchestrator module level so per-batch DB ops are no-ops AND the
    lock-acquire entry guard is bypassed. Returns the persister instance
    mock so tests can inspect call args.

    M3 NOTE: ``run_sync`` now wraps body in ``_AdvisoryLockHeld`` against a
    NullPool engine constructed via ``_make_lock_holder_engine``. With a
    MagicMock engine, both helpers must be stubbed for the body to execute.
    Real-DB advisory-lock behaviour is exercised in
    ``test_advisory_lock.py`` (mocked Connection) and
    ``tests/fixtures/connector_conformance/test_concurrent_sync_advisory_lock.py``
    (real Postgres testcontainer + multi-process race).
    """
    # M3 lock-helper stubs.
    monkeypatch.setattr(
        orch_module, "_make_lock_holder_engine", lambda url: MagicMock()
    )

    @contextlib.contextmanager
    def _noop_lock(lock_engine: object, tenant_id: object, connector_id: object):  # type: ignore[no-untyped-def]
        yield MagicMock()

    monkeypatch.setattr(orch_module, "_AdvisoryLockHeld", _noop_lock)

    fake_session_cls = MagicMock()
    fake_session_instance = MagicMock()
    fake_session_cls.return_value.__enter__.return_value = fake_session_instance
    monkeypatch.setattr(orch_module, "Session", fake_session_cls)

    fake_persister_cls = MagicMock()
    fake_persister_instance = MagicMock()
    if persist_raises is not None:
        fake_persister_instance.persist.side_effect = persist_raises
    elif isinstance(persist_result, list):
        fake_persister_instance.persist.side_effect = persist_result
    else:
        fake_persister_instance.persist.return_value = (
            persist_result or PersistResult(created=1)
        )
    fake_persister_cls.return_value = fake_persister_instance
    monkeypatch.setattr(orch_module, "CIPRowPersister", fake_persister_cls)

    return fake_persister_instance


def _connector_with(records: list[dict[str, object]]) -> MockConnector:
    return MockConnector(records=records)


def _baseline_records(n: int) -> list[dict[str, object]]:
    return [
        {
            "id": f"rec-{i:03d}",
            "email": f"u{i}@example.com",
            "updated_at": datetime(2026, 4, 20, i, 0, 0, tzinfo=UTC),
        }
        for i in range(n)
    ]


# ── _utcnow helper (Delta 7) ─────────────────────────────────────────────


class TestUtcnow:
    def test_returns_tz_aware_utc(self) -> None:
        ts = _utcnow()
        assert ts.tzinfo is not None
        assert ts.utcoffset() is not None


# ── Pure helpers ─────────────────────────────────────────────────────────


class TestApplySafetyWindow:
    def test_none_cursor_returns_none(self) -> None:
        assert _apply_safety_window(None, 300) is None

    def test_window_zero_passes_through(self) -> None:
        c: dict[str, object] = {"last_incremental_key": "2026-04-20T00:00:00+00:00"}
        assert _apply_safety_window(c, 0) is c

    def test_rewinds_by_window(self) -> None:
        c: dict[str, object] = {"last_incremental_key": "2026-04-20T01:00:00+00:00"}
        adjusted = _apply_safety_window(c, 300)
        assert adjusted is not None
        assert adjusted["last_incremental_key"] == "2026-04-20T00:55:00+00:00"

    def test_tz_naive_stored_cursor_raises(self) -> None:
        c: dict[str, object] = {"last_incremental_key": "2026-04-20T01:00:00"}  # naive
        with pytest.raises(TimezoneNaiveError):
            _apply_safety_window(c, 300)


class TestDedupeBySourceId:
    def test_no_duplicates(self) -> None:
        batch: list[dict[str, object]] = [
            {"source_id": "a"},
            {"source_id": "b"},
        ]
        assert _dedupe_by_source_id(batch) == batch

    def test_keeps_last_occurrence(self) -> None:
        batch: list[dict[str, object]] = [
            {"source_id": "a", "v": 1},
            {"source_id": "b", "v": 1},
            {"source_id": "a", "v": 2},  # last "a" wins
        ]
        out = _dedupe_by_source_id(batch)
        assert len(out) == 2
        a = next(r for r in out if r["source_id"] == "a")
        assert a["v"] == 2

    def test_empty_batch(self) -> None:
        assert _dedupe_by_source_id([]) == []

    def test_records_without_source_id_or_id_passed_through(self) -> None:
        batch: list[dict[str, object]] = [{"foo": 1}, {"bar": 2}]
        # No dedupe key → original list returned.
        assert _dedupe_by_source_id(batch) == batch


# ── Entry-shape validation (C-5) ─────────────────────────────────────────


class TestEntryShapeValidation:
    def test_invalid_connector_shape_propagates(
        self, engine: MagicMock
    ) -> None:
        # GoodMapper but BadConnector (missing methods) → ProtocolShapeError.
        from cip.integration_mesh.validation import ProtocolShapeError

        bad_connector: Any = object()
        with pytest.raises(ProtocolShapeError):
            run_sync(bad_connector, MockMapper(), engine, tenant_id=uuid4())


# ── Authentication ──────────────────────────────────────────────────────


class TestAuthentication:
    def test_authenticate_failure_raises_authentication_error(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_session_and_persister(monkeypatch)

        class FailingAuthConnector(MockConnector):
            def authenticate(self) -> None:
                raise RuntimeError("bad creds")

        with pytest.raises(AuthenticationError, match="bad creds"):
            run_sync(
                FailingAuthConnector(),
                MockMapper(),
                engine,
                tenant_id=uuid4(),
            )


# ── Happy path ──────────────────────────────────────────────────────────


class TestHappyPath:
    def test_single_batch_success(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_session_and_persister(
            monkeypatch, persist_result=PersistResult(created=1)
        )
        records = _baseline_records(3)
        connector = _connector_with(records)
        state = run_sync(
            connector, MockMapper(), engine, tenant_id=uuid4()
        )
        assert state.status == "success"
        assert state.rows_received == 3
        assert state.rows_created == 3
        assert state.rows_updated == 0
        assert state.rows_skipped_unchanged == 0
        assert state.rows_skipped_drift == 0
        assert state.rows_skipped_duplicate == 0
        assert connector.authenticated is True
        # H-10: stream_records called EXACTLY ONCE per run.
        assert connector.stream_records_call_count == 1

    def test_empty_stream_success(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_session_and_persister(monkeypatch)
        state = run_sync(
            _connector_with([]),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
        )
        assert state.status == "success"
        assert state.rows_received == 0
        assert state.rows_created == 0


# ── SchemaDriftError ────────────────────────────────────────────────────


class TestSchemaDriftError:
    def test_drift_increments_counter_and_continues(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Mapper raises drift on EVERY record → all 3 records skipped.
        _stub_session_and_persister(monkeypatch)
        state = run_sync(
            _connector_with(_baseline_records(3)),
            MockMapper(map_raises=SchemaDriftError),
            engine,
            tenant_id=uuid4(),
        )
        assert state.status == "success"  # drift is per-record, not per-run
        assert state.rows_skipped_drift == 3
        assert state.rows_created == 0
        assert state.rows_received == 3  # all 3 yielded by stream


# ── PersistenceError + abort ────────────────────────────────────────────


class TestPersistenceError:
    def test_three_consecutive_batch_failures_aborts(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Each batch fails → after 3 consecutive, abort with status='partial'.
        _stub_session_and_persister(
            monkeypatch,
            persist_raises=[
                PersistenceError("fail1"),
                PersistenceError("fail2"),
                PersistenceError("fail3"),
                PersistenceError("fail4"),  # extra to ensure abort kicks in
            ],
        )
        # 4 records, batch_size=1 → 4 batches each with one persist call.
        records = _baseline_records(4)
        state = run_sync(
            _connector_with(records),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
            batch_size=1,
        )
        assert state.status == "partial"
        assert state.error_detail is not None
        assert state.error_detail["type"] == "PersistenceError"


# ── RateLimitExceeded ──────────────────────────────────────────────────


class TestRateLimitExceeded:
    def test_rate_limit_retry_budget_exhaustion_increments_failure(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Each persist call raises RateLimitExceeded → after 3 retries on
        # the SAME batch the orchestrator counts 1 consecutive batch failure.
        # Need 3 such batch failures to abort.
        # Patch time.sleep to no-op so the test runs fast.
        monkeypatch.setattr("time.sleep", lambda _: None)
        _stub_session_and_persister(
            monkeypatch,
            persist_raises=[RateLimitExceeded(0.01) for _ in range(20)],
        )
        records = _baseline_records(3)
        state = run_sync(
            _connector_with(records),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
            batch_size=1,
        )
        assert state.status == "partial"
        assert state.error_detail is not None
        assert state.error_detail["type"] == "RateLimitExhaustion"


# ── tz-naive incremental_key (H-12) ─────────────────────────────────────


class TestTzNaiveGuards:
    def test_tz_naive_incremental_key_run_fatal(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_session_and_persister(monkeypatch)

        class TzNaiveConnector(MockConnector):
            def incremental_key(
                self, record: dict[str, object]
            ) -> datetime:
                # Naive datetime — should trigger run-fatal.
                return datetime(2026, 4, 20, 0, 0, 0)

        with pytest.raises(TimezoneNaiveError):
            run_sync(
                TzNaiveConnector(records=_baseline_records(1)),
                MockMapper(),
                engine,
                tenant_id=uuid4(),
            )

    def test_tz_naive_stored_cursor_run_fatal(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_session_and_persister(monkeypatch)
        with pytest.raises(TimezoneNaiveError):
            run_sync(
                _connector_with([]),
                MockMapper(),
                engine,
                tenant_id=uuid4(),
                initial_cursor={
                    "last_incremental_key": "2026-04-20T01:00:00"
                },  # naive
            )


# ── Knowledge-hook metadata-finalize ─────────────────────────────────────


class TestKnowledgeHookFinalize:
    def test_default_mock_only_emits_source_id_and_validates_after_finalize(
        self,
        engine: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # MockMapper default: metadata={"source_id": rec_id}; orchestrator
        # finalizes the other 4 required keys + ingestion_batch_id.
        _stub_session_and_persister(monkeypatch)
        captured: list[Any] = []
        monkeypatch.setattr(
            orch_module, "ingest_texts_noop", lambda texts: captured.append(texts)
        )
        state = run_sync(
            _connector_with(_baseline_records(2)),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
        )
        assert state.status == "success"
        # ingest_texts_noop called once per record (2 records → 2 calls).
        assert len(captured) == 2
        # Each captured list has 1 KnowledgeText.
        first_text = captured[0][0]
        md = first_text.metadata
        # All 5 required keys present after finalize.
        assert "source_id" in md
        assert "source_system" in md
        assert "extracted_at" in md
        assert "tenant_id" in md
        assert "connector_version" in md
        # Orchestrator-owned keys assigned, not setdefault'd.
        assert md["ingestion_batch_id"] is not None
        # connector_version pulled from MockConnector.version.
        assert md["connector_version"] == "1.2.3"
        # source_system fallback to connector_id (mapper didn't emit).
        assert md["source_system"] == "mock-connector"

    def test_setdefault_preserves_mapper_emitted_source_system(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If the mapper KNOWS a more specific source_system, setdefault
        # preserves it (mapper-may-know-better).
        _stub_session_and_persister(monkeypatch)
        captured: list[Any] = []
        monkeypatch.setattr(
            orch_module, "ingest_texts_noop", lambda texts: captured.append(texts)
        )
        run_sync(
            _connector_with(_baseline_records(1)),
            MockMapper(
                knowledge_metadata_factory=lambda rec: {
                    "source_id": str(rec["id"]),
                    "source_system": "hubspot-sub-system-v3",
                    "connector_version": "9.9.9",
                }
            ),
            engine,
            tenant_id=uuid4(),
        )
        md = captured[0][0].metadata
        # Mapper-emitted values WIN.
        assert md["source_system"] == "hubspot-sub-system-v3"
        assert md["connector_version"] == "9.9.9"

    def test_extracted_at_hoisted_one_per_record(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Delta 9: extracted_at is computed once per record, not per text.
        _stub_session_and_persister(monkeypatch)
        captured: list[Any] = []
        monkeypatch.setattr(
            orch_module, "ingest_texts_noop", lambda texts: captured.append(texts)
        )

        class MultiTextMapper(MockMapper):
            def ingest_as_knowledge(
                self, record: dict[str, object]
            ) -> list[KnowledgeText]:
                # Emit 3 texts for a single record.
                return [
                    KnowledgeText(
                        text=f"text-{i}",
                        metadata={"source_id": str(record["id"])},
                    )
                    for i in range(3)
                ]

        run_sync(
            _connector_with(_baseline_records(1)),
            MultiTextMapper(),
            engine,
            tenant_id=uuid4(),
        )
        # All 3 texts share the SAME extracted_at value (per-record granularity).
        texts = captured[0]
        assert len(texts) == 3
        ts0 = texts[0].metadata["extracted_at"]
        for t in texts[1:]:
            assert t.metadata["extracted_at"] == ts0


class TestKnowledgeHookFatalErrors:
    def test_missing_source_id_run_fatal(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_session_and_persister(monkeypatch)

        class BadMapper(MockMapper):
            def ingest_as_knowledge(
                self, record: dict[str, object]
            ) -> list[KnowledgeText]:
                # Missing source_id → validator raises after finalize.
                return [KnowledgeText(text="t", metadata={})]

        with pytest.raises(KnowledgeMetadataValidationError, match="source_id"):
            run_sync(
                _connector_with(_baseline_records(1)),
                BadMapper(),
                engine,
                tenant_id=uuid4(),
            )

    def test_tenant_id_override_detected_run_fatal(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Delta 8 detect-then-assign: a buggy mapper emitting tenant_id
        # different from the run's bound tenant_id MUST fail loud.
        _stub_session_and_persister(monkeypatch)
        attacker_tid = uuid4()

        class TenantOverrideMapper(MockMapper):
            def ingest_as_knowledge(
                self, record: dict[str, object]
            ) -> list[KnowledgeText]:
                return [
                    KnowledgeText(
                        text="t",
                        metadata={
                            "source_id": str(record["id"]),
                            "tenant_id": attacker_tid,
                        },
                    )
                ]

        with pytest.raises(
            KnowledgeMetadataValidationError, match="tenant_id"
        ):
            run_sync(
                _connector_with(_baseline_records(1)),
                TenantOverrideMapper(),
                engine,
                tenant_id=uuid4(),
            )

    def test_ingestion_batch_id_override_detected_run_fatal(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Delta 8 detect-then-assign: same fail-loud guard for ingestion_batch_id.
        _stub_session_and_persister(monkeypatch)
        attacker_bid = uuid4()

        class BatchOverrideMapper(MockMapper):
            def ingest_as_knowledge(
                self, record: dict[str, object]
            ) -> list[KnowledgeText]:
                return [
                    KnowledgeText(
                        text="t",
                        metadata={
                            "source_id": str(record["id"]),
                            "ingestion_batch_id": attacker_bid,
                        },
                    )
                ]

        with pytest.raises(
            KnowledgeMetadataValidationError, match="ingestion_batch_id"
        ):
            run_sync(
                _connector_with(_baseline_records(1)),
                BatchOverrideMapper(),
                engine,
                tenant_id=uuid4(),
            )

    def test_mapper_emitting_correct_tenant_id_passes(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Sanity: a mapper that emits the SAME tenant_id as the run's
        # binding doesn't raise (no detection trip).
        _stub_session_and_persister(monkeypatch)
        run_tid = uuid4()

        class HonestEchoMapper(MockMapper):
            def ingest_as_knowledge(
                self, record: dict[str, object]
            ) -> list[KnowledgeText]:
                return [
                    KnowledgeText(
                        text="t",
                        metadata={
                            "source_id": str(record["id"]),
                            "tenant_id": run_tid,  # same as binding
                        },
                    )
                ]

        state = run_sync(
            _connector_with(_baseline_records(1)),
            HonestEchoMapper(),
            engine,
            tenant_id=run_tid,
        )
        assert state.status == "success"


class TestKnowledgeHookNonFatalErrors:
    def test_generic_hook_exception_logged_continues(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # D-067: knowledge-extraction failures are non-fatal.
        _stub_session_and_persister(monkeypatch)
        state = run_sync(
            _connector_with(_baseline_records(2)),
            MockMapper(ingest_raises=RuntimeError),
            engine,
            tenant_id=uuid4(),
        )
        # Run completes successfully despite hook exceptions.
        assert state.status == "success"
        assert state.rows_received == 2

    def test_ingest_texts_noop_failure_non_fatal(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The downstream noop / M5-real-ingest raising an exception is
        # treated as non-fatal (the M2 stub never raises, but M5 might).
        _stub_session_and_persister(monkeypatch)

        def boom(texts: object) -> None:
            raise RuntimeError("pinecone 503")

        monkeypatch.setattr(orch_module, "ingest_texts_noop", boom)
        state = run_sync(
            _connector_with(_baseline_records(1)),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
        )
        assert state.status == "success"


# ── Counter mapping consistency with reconciliation #2 ──────────────────


class TestCounterMappingDelta1:
    def test_recorder_collapses_internal_seven_to_deployed_five(
        self,
        engine: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Build a run with mixed counter outcomes; verify the recorder's
        # __exit__ UPDATE collapses the 7 in-memory counters → 5 deployed
        # column values per Delta 1.
        # Persister returns mix of created/updated/skipped/history per call.
        _stub_session_and_persister(
            monkeypatch,
            persist_raises=None,
            persist_result=[
                PersistResult(created=1),
                PersistResult(updated=1, history=1),
                PersistResult(skipped=1),
            ],
        )
        records = _baseline_records(3)
        state = run_sync(
            _connector_with(records),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
        )
        assert state.rows_created == 1
        assert state.rows_updated == 1
        assert state.rows_skipped_unchanged == 1
        assert state.rows_history == 1

        # Inspect the recorder's __exit__ UPDATE call to verify collapsed
        # 5-counter shape (Delta 1 reconciliation):
        #   rows_ingested = rows_created + rows_updated = 2
        #   rows_skipped  = unchanged + drift + duplicate = 1
        engine_begin_calls = engine.begin.return_value.__enter__.return_value
        update_call = engine_begin_calls.execute.call_args_list[-1]
        params = update_call[0][1]
        assert params["rows_ingested"] == 2
        assert params["rows_skipped"] == 1
        assert params["rows_created"] == 1
        assert params["rows_updated"] == 1
        assert params["rows_history"] == 1


# ── Intra-batch dedupe counter ───────────────────────────────────────────


class TestIntraBatchDedupe:
    def test_duplicate_source_ids_increment_skipped_duplicate(
        self,
        engine: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Build a batch with 3 records where 2 share a source_id; dedupe
        # drops 1; rows_skipped_duplicate increments.
        _stub_session_and_persister(monkeypatch)
        records: list[dict[str, object]] = [
            {
                "id": "r1",
                "source_id": "r1",
                "email": "a@x.com",
                "updated_at": datetime(2026, 4, 20, 0, tzinfo=UTC),
            },
            {
                "id": "r2",
                "source_id": "r2",
                "email": "b@x.com",
                "updated_at": datetime(2026, 4, 20, 1, tzinfo=UTC),
            },
            {
                "id": "r1",
                "source_id": "r1",
                "email": "a-v2@x.com",
                "updated_at": datetime(2026, 4, 20, 2, tzinfo=UTC),
            },
        ]
        state = run_sync(
            _connector_with(records),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
            batch_size=10,
        )
        assert state.status == "success"
        assert state.rows_skipped_duplicate == 1


# ── stream_records called exactly once (H-10) ───────────────────────────


class TestStreamRecordsCalledOnce:
    def test_h10_single_call(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_session_and_persister(monkeypatch)
        connector = _connector_with(_baseline_records(7))
        run_sync(
            connector,
            MockMapper(),
            engine,
            tenant_id=uuid4(),
            batch_size=2,
        )
        # Even with multiple batches, stream_records is invoked exactly once.
        assert connector.stream_records_call_count == 1


# ── Cursor advance written per-batch ────────────────────────────────────


class TestCursorAdvance:
    def test_cursor_state_written_in_batch_txn(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The orchestrator writes UPDATE cip_sync_runs SET cursor_state ...
        # within the per-batch Session. Verify by inspecting the patched
        # session's execute calls.
        # M3: also stub the advisory-lock helpers (run_sync now wraps body
        # in _AdvisoryLockHeld against a NullPool engine).
        monkeypatch.setattr(
            orch_module, "_make_lock_holder_engine", lambda url: MagicMock()
        )

        @contextlib.contextmanager
        def _noop_lock(*args: object, **kwargs: object) -> Iterator[MagicMock]:
            yield MagicMock()

        monkeypatch.setattr(orch_module, "_AdvisoryLockHeld", _noop_lock)

        fake_session_cls = MagicMock()
        fake_session_instance = MagicMock()
        fake_session_cls.return_value.__enter__.return_value = fake_session_instance
        monkeypatch.setattr(orch_module, "Session", fake_session_cls)

        fake_persister_cls = MagicMock()
        fake_persister_cls.return_value.persist.return_value = PersistResult(created=1)
        monkeypatch.setattr(orch_module, "CIPRowPersister", fake_persister_cls)

        records = _baseline_records(2)
        state = run_sync(
            _connector_with(records),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
        )
        assert state.cursor_state is not None
        assert "last_incremental_key" in state.cursor_state

        # Verify the UPDATE cursor_state SQL was executed inside the
        # per-batch session (not via engine.begin).
        cursor_update_calls = [
            c
            for c in fake_session_instance.execute.call_args_list
            if "cursor_state" in str(c[0][0])
        ]
        assert len(cursor_update_calls) >= 1


# ── PersistenceError translation passthrough (sanity) ─────────────────


class TestPersistenceErrorPassthrough:
    def test_integrity_error_via_persister_routes_to_persistence_error(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If the persister raises PersistenceError directly, the orchestrator
        # treats it as a batch failure (not run-fatal). One record × one
        # PersistenceError → consecutive_batch_failures=1, run completes
        # with status=partial since error_detail was set even though the
        # next batches succeed. (Single record + single PersistenceError +
        # batch_size=1 means only one batch ever runs.)
        _stub_session_and_persister(
            monkeypatch,
            persist_raises=[PersistenceError("dup key")],
        )
        records = _baseline_records(1)
        state = run_sync(
            _connector_with(records),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
            batch_size=1,
        )
        # error_detail set → status='partial' (not failed; no exception
        # propagated out of run_sync).
        assert state.status == "partial"
        assert state.error_detail is not None


# ── M3 §4.8 advisory-lock entry-guard behavior ───────────────────────────


class TestAdvisoryLockEntryGuard:
    """run_sync acquires the advisory lock AFTER validate_connector_shape
    and BEFORE recorder construction, with a database_url override path."""

    def test_validate_shape_failure_does_not_burn_lock_acquire(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Plan §4.8 critical-ordering: shape validation runs before lock acquire.
        # If shape fails, _make_lock_holder_engine should NEVER be called.
        from cip.integration_mesh.validation import ProtocolShapeError

        called = {"lock_engine": False, "lock_held": False}

        def _spy_make(url: str) -> MagicMock:
            called["lock_engine"] = True
            return MagicMock()

        @contextlib.contextmanager
        def _spy_lock(*args: object, **kwargs: object) -> Iterator[MagicMock]:
            called["lock_held"] = True
            yield MagicMock()

        monkeypatch.setattr(orch_module, "_make_lock_holder_engine", _spy_make)
        monkeypatch.setattr(orch_module, "_AdvisoryLockHeld", _spy_lock)

        bad_connector: Any = object()
        with pytest.raises(ProtocolShapeError):
            run_sync(bad_connector, MockMapper(), engine, tenant_id=uuid4())
        assert called["lock_engine"] is False
        assert called["lock_held"] is False

    def test_acquires_advisory_lock_after_validate_shape(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Order verification: validate_connector_shape called BEFORE lock acquire.
        order: list[str] = []
        from cip.integration_mesh import validation as validation_module

        original_validate = validation_module.validate_connector_shape

        def _spy_validate(connector: Any, mapper: Any) -> None:
            order.append("validate")
            original_validate(connector, mapper)

        def _spy_make(url: str) -> MagicMock:
            order.append("make_lock_engine")
            return MagicMock()

        @contextlib.contextmanager
        def _spy_lock(*args: object, **kwargs: object) -> Iterator[MagicMock]:
            order.append("lock_held")
            yield MagicMock()

        # Stub Session + persister FIRST (helper installs its own lock stubs);
        # then OVERRIDE the lock stubs with our spies so monkeypatch's
        # last-write-wins keeps our spies active.
        _stub_session_and_persister(monkeypatch)
        monkeypatch.setattr(
            orch_module, "validate_connector_shape", _spy_validate
        )
        monkeypatch.setattr(orch_module, "_make_lock_holder_engine", _spy_make)
        monkeypatch.setattr(orch_module, "_AdvisoryLockHeld", _spy_lock)

        run_sync(
            _connector_with(_baseline_records(1)),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
        )
        assert order[0] == "validate"
        assert order.index("make_lock_engine") > order.index("validate")
        assert order.index("lock_held") > order.index("make_lock_engine")

    def test_disposes_lock_engine_on_normal_exit(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The lock-holder engine MUST be disposed when run_sync returns
        # (lifecycle hygiene; a fresh engine per run avoids accidental reuse).
        # Stub helper installs its own lock stubs; override AFTER so our
        # custom mock is the active one.
        _stub_session_and_persister(monkeypatch)
        lock_engine_mock = MagicMock()
        monkeypatch.setattr(
            orch_module, "_make_lock_holder_engine", lambda url: lock_engine_mock
        )

        run_sync(
            _connector_with(_baseline_records(1)),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
        )
        lock_engine_mock.dispose.assert_called_once()

    def test_disposes_lock_engine_on_exception(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Even when run_sync raises (e.g., SyncAlreadyRunningError), the
        # lock-holder engine MUST be disposed — try/finally guarantees this.
        from cip.integration_mesh.exceptions import SyncAlreadyRunningError

        lock_engine_mock = MagicMock()
        monkeypatch.setattr(
            orch_module, "_make_lock_holder_engine", lambda url: lock_engine_mock
        )

        def _blocking_lock(
            *args: object, **kwargs: object
        ) -> Any:
            raise SyncAlreadyRunningError("simulated concurrent run")

        monkeypatch.setattr(orch_module, "_AdvisoryLockHeld", _blocking_lock)

        with pytest.raises(SyncAlreadyRunningError):
            run_sync(
                _connector_with(_baseline_records(1)),
                MockMapper(),
                engine,
                tenant_id=uuid4(),
            )
        lock_engine_mock.dispose.assert_called_once()

    def test_database_url_override_passed_to_make_lock_engine(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Plan §4.8: explicit database_url kwarg overrides str(engine.url).
        # Stub-helper installs default lock stubs FIRST; override after.
        _stub_session_and_persister(monkeypatch)
        captured_urls: list[str] = []

        def _capture_make(url: str) -> MagicMock:
            captured_urls.append(url)
            return MagicMock()

        monkeypatch.setattr(orch_module, "_make_lock_holder_engine", _capture_make)

        explicit_url = "postgresql+psycopg://u:p@direct:5432/db"
        run_sync(
            _connector_with(_baseline_records(1)),
            MockMapper(),
            engine,
            tenant_id=uuid4(),
            database_url=explicit_url,
        )
        assert captured_urls == [explicit_url]


# ── Sequential runs same-process (Senior #13 / Acceptance #27) ───────────


class TestSequentialRunsSameProcess:
    def test_sequential_runs_on_same_engine_both_succeed(
        self, engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Acceptance #27: two sequential run_sync calls on same (tenant, connector)
        # both succeed. Advisory lock is released between runs (auto on conn close);
        # the second acquire succeeds.
        _stub_session_and_persister(monkeypatch)
        tid = uuid4()
        records = _baseline_records(2)

        state1 = run_sync(
            _connector_with(records),
            MockMapper(),
            engine,
            tenant_id=tid,
        )
        state2 = run_sync(
            _connector_with(records),
            MockMapper(),
            engine,
            tenant_id=tid,
        )
        assert state1.status == "success"
        assert state2.status == "success"
        # Distinct run_ids prove these were separate runs.
        assert state1.run_id != state2.run_id

