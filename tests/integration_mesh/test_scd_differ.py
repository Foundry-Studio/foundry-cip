# foundry: kind=test domain=client-intelligence-platform
"""Tests for SCDDiffer (M2 §4.6 binding).

Plan §4.6 acceptance: ≥8 cases — unchanged, one domain col changed,
overflow changed, metadata-only no diff, registry no history, missing
keys treated as no change, type/canonical normalisation, list value.
"""
from __future__ import annotations

import pytest

from cip.integration_mesh.scd_differ import (
    METADATA_COLUMNS,
    NO_HISTORY_TABLES,
    SCDDiffer,
)


@pytest.fixture
def differ() -> SCDDiffer:
    return SCDDiffer()


class TestShouldWriteHistory:
    def test_domain_table_writes_history(self, differ: SCDDiffer) -> None:
        assert differ.should_write_history("cip_contacts") is True

    def test_property_registry_no_history(self, differ: SCDDiffer) -> None:
        assert (
            differ.should_write_history("cip_connector_property_registry")
            is False
        )

    def test_sync_runs_no_history(self, differ: SCDDiffer) -> None:
        assert differ.should_write_history("cip_sync_runs") is False


class TestDiff:
    def test_unchanged(self, differ: SCDDiffer) -> None:
        result = differ.diff(
            target_table="cip_contacts",
            current_row={"email": "a@x.com", "overflow": {}},
            new_fields={"email": "a@x.com"},
            new_overflow={},
        )
        assert result.changed is False
        assert result.changed_columns == []
        assert result.write_history is False

    def test_one_domain_column_changed(self, differ: SCDDiffer) -> None:
        result = differ.diff(
            target_table="cip_contacts",
            current_row={"email": "a@x.com", "overflow": {}},
            new_fields={"email": "b@x.com"},
            new_overflow={},
        )
        assert result.changed is True
        assert result.changed_columns == ["email"]
        assert result.write_history is True

    def test_overflow_changed(self, differ: SCDDiffer) -> None:
        result = differ.diff(
            target_table="cip_contacts",
            current_row={"email": "a@x.com", "overflow": {"x": 1}},
            new_fields={"email": "a@x.com"},
            new_overflow={"x": 2},
        )
        assert result.changed is True
        assert "overflow" in result.changed_columns

    def test_metadata_only_change_no_diff(self, differ: SCDDiffer) -> None:
        # Provenance / SCD metadata columns never count as changes.
        result = differ.diff(
            target_table="cip_contacts",
            current_row={
                "id": "old-id",
                "ingested_at": "2026-01-01",
                "ingestion_batch_id": "old-batch",
                "email": "a@x.com",
                "overflow": {},
            },
            new_fields={
                "id": "new-id",
                "ingested_at": "2026-04-20",
                "ingestion_batch_id": "new-batch",
                "email": "a@x.com",
            },
            new_overflow={},
        )
        assert result.changed is False

    def test_registry_table_changed_no_history(
        self, differ: SCDDiffer
    ) -> None:
        result = differ.diff(
            target_table="cip_connector_property_registry",
            current_row={"description": "old", "overflow": {}},
            new_fields={"description": "new"},
            new_overflow={},
        )
        assert result.changed is True
        assert result.write_history is False

    def test_missing_keys_in_new_treated_as_no_change(
        self, differ: SCDDiffer
    ) -> None:
        # Plan §4.5 edge case: row.fields omitting a column is "no change".
        result = differ.diff(
            target_table="cip_contacts",
            current_row={
                "email": "a@x.com",
                "phone": "555",
                "overflow": {},
            },
            new_fields={"email": "a@x.com"},  # phone omitted
            new_overflow={},
        )
        assert result.changed is False

    def test_overflow_canonical_dodges_key_order(
        self, differ: SCDDiffer
    ) -> None:
        result = differ.diff(
            target_table="cip_contacts",
            current_row={"overflow": {"a": 1, "b": 2}},
            new_fields={},
            new_overflow={"b": 2, "a": 1},
        )
        assert result.changed is False

    def test_list_values_normalised(self, differ: SCDDiffer) -> None:
        # JSON canonical normalisation makes list comparison key-stable.
        result = differ.diff(
            target_table="cip_contacts",
            current_row={"tags": ["a", "b"], "overflow": {}},
            new_fields={"tags": ["a", "b"]},
            new_overflow={},
        )
        assert result.changed is False

    def test_changed_columns_list_complete(self, differ: SCDDiffer) -> None:
        # If multiple cols change, all are reported.
        result = differ.diff(
            target_table="cip_contacts",
            current_row={
                "email": "a@x.com",
                "phone": "555",
                "overflow": {"x": 1},
            },
            new_fields={"email": "b@x.com", "phone": "999"},
            new_overflow={"x": 2},
        )
        assert result.changed is True
        assert set(result.changed_columns) == {"email", "phone", "overflow"}


def test_metadata_columns_constant_shape() -> None:
    assert "id" in METADATA_COLUMNS
    assert "ingested_at" in METADATA_COLUMNS
    assert "ingestion_batch_id" in METADATA_COLUMNS
    assert "previous_version_id" in METADATA_COLUMNS
    assert "refreshed_at" in METADATA_COLUMNS


def test_no_history_tables_constant_shape() -> None:
    assert "cip_connector_property_registry" in NO_HISTORY_TABLES
    assert "cip_sync_runs" in NO_HISTORY_TABLES
