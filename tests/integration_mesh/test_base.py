# foundry: kind=test domain=client-intelligence-platform
"""Smoke tests for ``cip.integration_mesh.base``.

Covers the M2 binding shapes + boundary validator (Round-6 Call A) +
tz-aware guards (PATCH-NR-7). Heavier orchestrator + harness tests live
in §5 and exercise these types end-to-end.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest

from cip.integration_mesh.base import (
    ALLOWED_CIP_TABLES,
    DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS,
    DEFAULT_RATE_LIMIT,
    HISTORY_TABLE_BY_CURRENT,
    KNOWLEDGE_TEXT_REQUIRED_KEYS,
    MAX_BATCH_RATE_LIMIT_RETRIES,
    MAX_CONSECUTIVE_BATCH_FAILURES,
    MAX_RATE_LIMIT_SLEEP_SECONDS,
    CIPRow,
    KnowledgeText,
    KnowledgeTextMetadata,
    PropertyDescriptor,
    RateLimitPolicy,
    SyncRunState,
    _assert_tz_aware,
    validate_knowledge_text_metadata,
)
from cip.integration_mesh.exceptions import (
    KnowledgeMetadataValidationError,
    TimezoneNaiveError,
)


def _full_metadata() -> dict[str, object]:
    return {
        "source_id": "rec-1",
        "source_system": "mock",
        "extracted_at": datetime(2026, 4, 20, tzinfo=UTC),
        "tenant_id": uuid4(),
        "connector_version": "0.0.1",
    }


class TestRateLimitPolicy:
    def test_valid(self) -> None:
        p = RateLimitPolicy(requests_per_second=5.0, burst=3)
        assert p.requests_per_second == 5.0
        assert p.burst == 3

    def test_zero_rps_rejected(self) -> None:
        with pytest.raises(ValueError, match="requests_per_second"):
            RateLimitPolicy(requests_per_second=0.0)

    def test_negative_rps_rejected(self) -> None:
        with pytest.raises(ValueError, match="requests_per_second"):
            RateLimitPolicy(requests_per_second=-1.0)

    def test_burst_below_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="burst"):
            RateLimitPolicy(requests_per_second=1.0, burst=0)

    def test_frozen(self) -> None:
        p = RateLimitPolicy(requests_per_second=1.0)
        with pytest.raises(FrozenInstanceError):
            p.requests_per_second = 2.0  # type: ignore[misc]


class TestDefaults:
    def test_default_rate_limit(self) -> None:
        assert DEFAULT_RATE_LIMIT.requests_per_second == 10.0
        assert DEFAULT_RATE_LIMIT.burst == 5

    def test_tsp_constants(self) -> None:
        # Locked starting points per §4.1.
        assert DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS == 300
        assert MAX_RATE_LIMIT_SLEEP_SECONDS == 300
        assert MAX_BATCH_RATE_LIMIT_RETRIES == 3
        assert MAX_CONSECUTIVE_BATCH_FAILURES == 3


class TestAllowedTables:
    def test_expected_tables_present(self) -> None:
        # cip_15 added cip_ticket_comments.
        # cip_16 added cip_engagements.
        # cip_17 added cip_owners + cip_pipeline_stages.
        # Update this assertion when ALLOWED_CIP_TABLES changes.
        assert len(ALLOWED_CIP_TABLES) == 12, sorted(ALLOWED_CIP_TABLES)
        for tbl in (
            "cip_contacts", "cip_ticket_comments", "cip_engagements",
            "cip_owners", "cip_pipeline_stages",
            "cip_connector_property_registry",
        ):
            assert tbl in ALLOWED_CIP_TABLES, tbl

    def test_history_map_covers_domain_tables(self) -> None:
        # registry, owners, pipeline_stages intentionally absent
        # (reference / operational tables, no temporal audit).
        assert len(HISTORY_TABLE_BY_CURRENT) == 9, sorted(HISTORY_TABLE_BY_CURRENT)
        for non_history in (
            "cip_connector_property_registry",
            "cip_owners",
            "cip_pipeline_stages",
        ):
            assert non_history not in HISTORY_TABLE_BY_CURRENT, non_history
        for current in HISTORY_TABLE_BY_CURRENT:
            assert current in ALLOWED_CIP_TABLES
            assert HISTORY_TABLE_BY_CURRENT[current] == f"{current}_history"


class TestValidateKnowledgeTextMetadata:
    def test_all_required_keys_passes(self) -> None:
        validate_knowledge_text_metadata(
            cast(KnowledgeTextMetadata, _full_metadata())
        )

    def test_missing_one_required_key_raises(self) -> None:
        md = _full_metadata()
        del md["source_id"]
        with pytest.raises(
            KnowledgeMetadataValidationError, match="source_id"
        ):
            validate_knowledge_text_metadata(cast(KnowledgeTextMetadata, md))

    def test_missing_all_required_keys_raises(self) -> None:
        with pytest.raises(KnowledgeMetadataValidationError) as exc:
            validate_knowledge_text_metadata(
                cast(KnowledgeTextMetadata, {})
            )
        for k in KNOWLEDGE_TEXT_REQUIRED_KEYS:
            assert k in str(exc.value)

    def test_tz_naive_extracted_at_raises(self) -> None:
        md = _full_metadata()
        md["extracted_at"] = datetime(2026, 4, 20)  # tz-naive
        with pytest.raises(TimezoneNaiveError, match="extracted_at"):
            validate_knowledge_text_metadata(cast(KnowledgeTextMetadata, md))

    def test_tz_naive_record_updated_at_raises(self) -> None:
        md = _full_metadata()
        md["record_updated_at"] = datetime(2026, 4, 20)  # tz-naive
        with pytest.raises(TimezoneNaiveError, match="record_updated_at"):
            validate_knowledge_text_metadata(cast(KnowledgeTextMetadata, md))

    def test_aware_record_updated_at_passes(self) -> None:
        md = _full_metadata()
        md["record_updated_at"] = datetime(2026, 4, 20, tzinfo=UTC)
        validate_knowledge_text_metadata(cast(KnowledgeTextMetadata, md))

    def test_where_string_in_error(self) -> None:
        with pytest.raises(
            KnowledgeMetadataValidationError, match="custom-spot"
        ):
            validate_knowledge_text_metadata(
                cast(KnowledgeTextMetadata, {}), where="custom-spot"
            )

    def test_value_error_inheritance(self) -> None:
        # v5.2 distinction: KnowledgeMetadataValidationError is a CIP-internal
        # contract violation, not connector-author fault — inherits ValueError.
        with pytest.raises(ValueError):
            validate_knowledge_text_metadata(
                cast(KnowledgeTextMetadata, {})
            )


class TestAssertTzAware:
    def test_aware_passes(self) -> None:
        _assert_tz_aware(datetime(2026, 4, 20, tzinfo=UTC), "f")

    def test_naive_raises(self) -> None:
        with pytest.raises(TimezoneNaiveError, match="myfield"):
            _assert_tz_aware(datetime(2026, 4, 20), "myfield")

    def test_non_datetime_no_op(self) -> None:
        # Helper only fires for datetimes; other types pass through.
        _assert_tz_aware("not a datetime", "field")
        _assert_tz_aware(42, "field")
        _assert_tz_aware(None, "field")


class TestKnowledgeText:
    def test_frozen_dataclass(self) -> None:
        kt = KnowledgeText(
            text="hello",
            metadata=cast(KnowledgeTextMetadata, {"source_id": "x"}),
        )
        with pytest.raises(FrozenInstanceError):
            kt.text = "world"  # type: ignore[misc]

    def test_metadata_total_false_allows_partial_at_construction(self) -> None:
        # Mapper-side: only source_id known. Validator runs at boundary,
        # not at construction. Construction must not raise.
        kt = KnowledgeText(
            text="t",
            metadata=cast(KnowledgeTextMetadata, {"source_id": "x"}),
        )
        assert kt.metadata.get("source_id") == "x"


class TestCIPRow:
    def test_default_authority(self) -> None:
        r = CIPRow(target_table="cip_contacts", source_id="x", fields={})
        assert r.authority == "ingested"

    def test_default_overflow_empty_dict(self) -> None:
        r = CIPRow(target_table="cip_contacts", source_id="x", fields={})
        assert r.overflow == {}


class TestPropertyDescriptor:
    def test_minimal_construction(self) -> None:
        p = PropertyDescriptor(
            connector="mock",
            object_type="contact",
            property_name="email",
            data_type="string",
            storage_location="column",
            column_name="email",
            cip_table="cip_contacts",
        )
        assert p.is_custom is False
        assert p.description is None


class TestSyncRunState:
    def test_rows_processed_property(self) -> None:
        s = SyncRunState(
            run_id=uuid4(),
            batch_id=uuid4(),
            status="success",
            rows_received=10,
            rows_created=5,
            rows_updated=3,
            rows_skipped_unchanged=2,
            rows_skipped_drift=0,
            rows_skipped_duplicate=0,
            rows_history=3,
            started_at=datetime(2026, 4, 20, tzinfo=UTC),
            ended_at=datetime(2026, 4, 20, 1, tzinfo=UTC),
        )
        assert s.rows_processed == 10  # 5 + 3 + 2

    def test_default_cursor_state_and_error_detail(self) -> None:
        s = SyncRunState(
            run_id=uuid4(),
            batch_id=uuid4(),
            status="success",
            rows_received=0,
            rows_created=0,
            rows_updated=0,
            rows_skipped_unchanged=0,
            rows_skipped_drift=0,
            rows_skipped_duplicate=0,
            rows_history=0,
            started_at=datetime(2026, 4, 20, tzinfo=UTC),
            ended_at=datetime(2026, 4, 20, 1, tzinfo=UTC),
        )
        assert s.cursor_state is None
        assert s.error_detail is None
