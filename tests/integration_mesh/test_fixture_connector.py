# foundry: kind=test domain=client-intelligence-platform
"""M3 unit tests for FixtureConnector (M3 §6).

Covers Protocol shape (isinstance + validate_connector_shape), corpus
counts per CorpusSize, stream ordering, cursor filtering, tz-naive guard,
describe_schema descriptor counts + categories, eager corpus init.

DB-roundtrip behavior lives in the e2e tests (smoke + standard).
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from cip.integration_mesh import (
    CIPConnector,
    CIPMapper,
    validate_connector_shape,
)
from cip.integration_mesh.connectors.fixture import (
    CorpusSize,
    FixtureConnector,
    FixtureMapper,
)
from cip.integration_mesh.exceptions import TimezoneNaiveError


def test_public_api() -> None:
    """Acceptance #10: package-level exports importable."""
    assert FixtureConnector is not None
    assert FixtureMapper is not None
    assert CorpusSize is not None
    assert CorpusSize.STANDARD is not None
    assert CorpusSize.COMPACT is not None
    assert CorpusSize.SMOKE is not None


class TestProtocolShape:
    def test_fixture_connector_isinstance_protocol(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.SMOKE)
        assert isinstance(c, CIPConnector)

    def test_fixture_mapper_isinstance_protocol(self) -> None:
        assert isinstance(FixtureMapper(), CIPMapper)

    def test_validate_connector_shape_passes(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.SMOKE)
        validate_connector_shape(c, FixtureMapper())

    def test_required_attrs(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.SMOKE)
        assert c.connector_id == "fixture-connector-v1"
        assert c.cursor_safety_window_seconds == 0
        assert c.version == "1.0.0"
        # rate_limit_policy is a property → resolved attribute access.
        from cip.integration_mesh import DEFAULT_RATE_LIMIT
        assert c.rate_limit_policy == DEFAULT_RATE_LIMIT


class TestCorpusInit:
    def test_eager_init(self) -> None:
        # v2 #7: corpus generated eagerly in __init__, not lazily on first
        # attribute access. Verify the attribute is populated immediately.
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.COMPACT)
        assert c.corpus is not None
        assert isinstance(c.corpus, dict)
        # COMPACT: 5/20/30/50/10/0 = 115.
        assert sum(len(v) for v in c.corpus.values()) == 115

    def test_size_preset_smoke(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.SMOKE)
        assert sum(len(v) for v in c.corpus.values()) == 10
        assert len(c.corpus["contacts"]) == 10

    def test_size_preset_standard(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.STANDARD)
        assert sum(len(v) for v in c.corpus.values()) == 1150


class TestStreamRecords:
    def test_smoke_yields_10_contacts(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.SMOKE)
        c.authenticate()
        records = list(c.stream_records(None, batch_size=500))
        assert len(records) == 10
        assert all(r["record_type"] == "contact" for r in records)

    def test_standard_yields_1150(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.STANDARD)
        records = list(c.stream_records(None, batch_size=500))
        assert len(records) == 1150

    def test_cursor_filters_records(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.COMPACT)
        all_records = list(c.stream_records(None, batch_size=500))
        # Use the first record's updated_at as the cursor; should skip itself.
        first_ts = all_records[0]["updated_at"]
        filtered = list(
            c.stream_records(
                {"last_incremental_key": first_ts}, batch_size=500
            )
        )
        # All records with updated_at <= first_ts skipped — at minimum the first.
        assert len(filtered) < len(all_records)

    def test_tz_naive_cursor_raises(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.SMOKE)
        with pytest.raises(TimezoneNaiveError):
            list(
                c.stream_records(
                    {"last_incremental_key": "2026-01-01T00:00:00"},  # naive
                    batch_size=500,
                )
            )

    def test_called_once_yields_full_eligible_stream(self) -> None:
        # H-10: stream_records called once per run; orchestrator chunks.
        # Verify the connector itself doesn't pre-batch.
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.COMPACT)
        records1 = list(c.stream_records(None, batch_size=10))
        records2 = list(c.stream_records(None, batch_size=500))
        assert len(records1) == len(records2)  # batch_size doesn't shape output


class TestIncrementalKey:
    def test_returns_tz_aware_datetime(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.SMOKE)
        rec = c.corpus["contacts"][0]
        ts = c.incremental_key(rec)
        assert isinstance(ts, datetime)
        assert ts.tzinfo is not None

    def test_tz_naive_record_raises(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.SMOKE)
        bad: dict[str, object] = {
            "source_id": "x",
            "updated_at": "2026-01-01T00:00:00",
        }
        with pytest.raises(TimezoneNaiveError):
            c.incremental_key(bad)


class TestDescribeSchema:
    def test_yields_at_least_22_descriptors(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.STANDARD)
        descriptors = c.describe_schema()
        # M3 §4.5 acceptance: ≥22.
        assert len(descriptors) >= 22

    def test_covers_all_object_types(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.STANDARD)
        descriptors = c.describe_schema()
        types = {d.object_type for d in descriptors}
        assert {"company", "contact", "deal", "ticket", "document"} <= types

    def test_has_at_least_two_is_custom(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.STANDARD)
        descriptors = c.describe_schema()
        custom_count = sum(1 for d in descriptors if d.is_custom)
        assert custom_count >= 2

    def test_data_type_values_within_deployed_check_enum(self) -> None:
        # v5.4 Δ12: data_type values constrained by deployed CHECK enum.
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.STANDARD)
        valid_types = {
            "string", "number", "datetime", "enumeration",
            "reference", "boolean", "array", "object",
        }
        for d in c.describe_schema():
            assert d.data_type in valid_types, (
                f"{d.object_type}.{d.property_name} has data_type "
                f"{d.data_type!r} not in deployed CHECK enum {valid_types}"
            )


class TestSeedDeterminism:
    def test_same_seed_same_corpus(self) -> None:
        c1 = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.COMPACT)
        c2 = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.COMPACT)
        assert c1.corpus == c2.corpus

    def test_different_seed_different_corpus(self) -> None:
        c1 = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.COMPACT)
        c2 = FixtureConnector(tenant_id=uuid4(), seed=43, size=CorpusSize.COMPACT)
        assert c1.corpus != c2.corpus


class TestCursorSafetyWindowZero:
    """Gap #14: ``cursor_safety_window_seconds=0`` means exact cutoff."""

    def test_zero_window_exact_cutoff(self) -> None:
        c = FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.SMOKE)
        assert c.cursor_safety_window_seconds == 0
        # With window=0, any record whose ts == cursor.last_incremental_key is
        # excluded (strict >). Verify by feeding the last record's ts back in.
        records = list(c.stream_records(None, batch_size=500))
        last_ts = records[-1]["updated_at"]
        filtered = list(
            c.stream_records(
                {"last_incremental_key": last_ts}, batch_size=500
            )
        )
        assert len(filtered) == 0
