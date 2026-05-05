# foundry: kind=test domain=client-intelligence-platform
"""Unit tests for ``CIPRowPersister`` (mock-based control flow).

DB-roundtrip behaviour tests live in the conformance harness (§5):
  - ``test_scd_history.py`` exercises the bitemporal SCD-2 path against
    a real Postgres testcontainer.
  - ``test_property_registry.py`` exercises the registry upsert path.

These tests cover non-DB control flow:
  - allowlist guard (§9 acceptance criterion #21)
  - identifier safety (column-name validator)
  - SQLAlchemyError → PersistenceError translation
  - tz-naive field rejection (PATCH-NR-7)
  - extras column mapping (Delta 4)
  - cip_views overflow guard (Delta 5)
  - source_id IS NOT DISTINCT FROM in SELECT SQL (Delta 6)
  - bitemporal SCD-2 archive SQL shape (Delta 2)
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from cip.integration_mesh.base import CIPRow
from cip.integration_mesh.exceptions import (
    PersistenceError,
    TimezoneNaiveError,
)
from cip.integration_mesh.persister import (
    EXTRAS_COLUMN_BY_TABLE,
    CIPRowPersister,
    PersistResult,
    _safe_column_name,
)
from cip.integration_mesh.scd_differ import SCDDiffer

# ── Stub schemas (avoid DB reflection in unit tests) ──────────────────────

_CONTACTS_COLS = [
    "id", "tenant_id", "client_id", "source_connector", "source_id",
    "ingested_at", "refreshed_at", "previous_version_id",
    "ingestion_batch_id", "authority",
    "email", "phone", "first_name", "last_name", "company_name",
    "company_id", "title", "country", "city", "tags",
    "lifecycle_stage", "properties", "created_at", "updated_at",
]
_CONTACTS_HISTORY_COLS = [
    "history_id", "record_id", "tenant_id",
    "valid_from", "valid_to", "changed_by", "change_reason",
    "source_connector", "source_id", "ingested_at", "refreshed_at",
    "previous_version_id", "ingestion_batch_id", "authority",
    "email", "phone", "first_name", "last_name", "company_name",
    "company_id", "title", "country", "city", "tags",
    "lifecycle_stage", "properties",
]


@pytest.fixture
def differ() -> SCDDiffer:
    return SCDDiffer()


@pytest.fixture
def db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def persister(db: MagicMock, differ: SCDDiffer) -> CIPRowPersister:
    p = CIPRowPersister(db, differ)
    p._col_cache["cip_contacts"] = list(_CONTACTS_COLS)
    p._col_cache["cip_contacts_history"] = list(_CONTACTS_HISTORY_COLS)
    return p


def _stub_select_returns(db: MagicMock, value: object) -> None:
    """Stub: db.execute(...).mappings().first() → value."""
    db.execute.return_value.mappings.return_value.first.return_value = value


# ── Allowlist + Delta 5 (cip_views) ───────────────────────────────────────


class TestAllowlistGuard:
    def test_unknown_table_rejected(
        self, persister: CIPRowPersister
    ) -> None:
        # §9 acceptance criterion #21.
        row = CIPRow(target_table="cip_arbitrary_evil", source_id="x", fields={})
        with pytest.raises(PersistenceError, match="Unknown target_table"):
            persister.persist(
                row, tenant_id=uuid4(), connector_id="x", batch_id=uuid4()
            )


class TestExtrasColumnMapping:
    def test_clients_uses_metadata(self) -> None:
        # Delta 4: cip_clients extras column is `metadata`, not `properties`.
        assert EXTRAS_COLUMN_BY_TABLE["cip_clients"] == "metadata"

    def test_views_has_no_extras(self) -> None:
        assert EXTRAS_COLUMN_BY_TABLE["cip_views"] is None

    def test_five_tables_use_properties(self) -> None:
        for t in (
            "cip_files",
            "cip_contacts",
            "cip_companies",
            "cip_deals",
            "cip_tickets",
        ):
            assert EXTRAS_COLUMN_BY_TABLE[t] == "properties"


class TestViewsOverflowGuard:
    def test_views_with_overflow_rejected(
        self, persister: CIPRowPersister
    ) -> None:
        # Delta 5: cip_views has no extras column → mapper-emitting overflow
        # must fail loud.
        persister._col_cache["cip_views"] = [
            "id", "tenant_id", "view_name",
        ]
        row = CIPRow(
            target_table="cip_views",
            source_id="v1",
            fields={"view_name": "x"},
            overflow={"will_fail": True},
        )
        with pytest.raises(PersistenceError, match="no overflow column"):
            persister.persist(
                row, tenant_id=uuid4(), connector_id="x", batch_id=uuid4()
            )

    def test_views_with_empty_overflow_ok(
        self, persister: CIPRowPersister, db: MagicMock
    ) -> None:
        # Empty overflow is fine for cip_views.
        persister._col_cache["cip_views"] = [
            "id", "tenant_id", "client_id", "source_connector", "source_id",
            "ingested_at", "refreshed_at", "previous_version_id",
            "ingestion_batch_id", "authority", "view_name",
        ]
        _stub_select_returns(db, None)  # → INSERT path
        row = CIPRow(
            target_table="cip_views",
            source_id="v1",
            fields={"view_name": "x"},
            overflow={},
        )
        result = persister.persist(
            row, tenant_id=uuid4(), connector_id="x", batch_id=uuid4()
        )
        assert result == PersistResult(created=1)


# ── Identifier safety ────────────────────────────────────────────────────


class TestIdentifierSafety:
    def test_safe_column_name_rejects_injection(self) -> None:
        with pytest.raises(PersistenceError, match="Unsafe column name"):
            _safe_column_name("email; DROP TABLE--")

    def test_safe_column_name_rejects_uppercase(self) -> None:
        # Postgres lowercases unquoted identifiers; we reject mixed case
        # to keep the contract simple (snake_case only).
        with pytest.raises(PersistenceError, match="Unsafe column name"):
            _safe_column_name("Email")

    def test_safe_column_name_accepts_snake(self) -> None:
        assert _safe_column_name("first_name") == "first_name"
        assert _safe_column_name("_internal") == "_internal"
        assert _safe_column_name("col_42") == "col_42"

    def test_persist_rejects_unsafe_field_key(
        self, persister: CIPRowPersister
    ) -> None:
        row = CIPRow(
            target_table="cip_contacts",
            source_id="c001",
            fields={"email; DROP TABLE--": "evil"},
        )
        with pytest.raises(PersistenceError, match="Unsafe column name"):
            persister.persist(
                row, tenant_id=uuid4(), connector_id="x", batch_id=uuid4()
            )


# ── tz-naive guard (PATCH-NR-7) ──────────────────────────────────────────


class TestTzNaiveGuard:
    def test_tz_naive_field_rejected(
        self, persister: CIPRowPersister
    ) -> None:
        row = CIPRow(
            target_table="cip_contacts",
            source_id="c001",
            fields={"created_at": datetime(2026, 4, 20)},  # tz-naive
        )
        with pytest.raises(TimezoneNaiveError, match="created_at"):
            persister.persist(
                row, tenant_id=uuid4(), connector_id="x", batch_id=uuid4()
            )

    def test_tz_aware_field_passes(
        self, persister: CIPRowPersister, db: MagicMock
    ) -> None:
        _stub_select_returns(db, None)  # → INSERT path
        row = CIPRow(
            target_table="cip_contacts",
            source_id="c001",
            fields={
                "email": "a@x.com",
                "created_at": datetime(2026, 4, 20, tzinfo=UTC),
            },
        )
        result = persister.persist(
            row, tenant_id=uuid4(), connector_id="mock", batch_id=uuid4()
        )
        assert result == PersistResult(created=1)


# ── SQLAlchemy error translation ─────────────────────────────────────────


class TestSQLAlchemyErrorTranslation:
    def test_integrity_error_becomes_persistence_error(
        self, persister: CIPRowPersister, db: MagicMock
    ) -> None:
        db.execute.side_effect = IntegrityError(
            "stmt", {}, Exception("dup")
        )
        row = CIPRow(
            target_table="cip_contacts",
            source_id="c001",
            fields={"email": "a@x.com"},
        )
        with pytest.raises(PersistenceError):
            persister.persist(
                row, tenant_id=uuid4(), connector_id="x", batch_id=uuid4()
            )


# ── Delta 6: IS NOT DISTINCT FROM in SELECT SQL ──────────────────────────


class TestDelta6NullableSourceId:
    def test_select_uses_is_not_distinct_from(
        self, persister: CIPRowPersister, db: MagicMock
    ) -> None:
        # Uniform IS NOT DISTINCT FROM across all 7 tables — standard
        # Postgres idiom for SCD lookups against nullable natural keys.
        _stub_select_returns(db, None)  # → INSERT path; we only inspect SELECT
        row = CIPRow(
            target_table="cip_contacts",
            source_id="c001",
            fields={"email": "a@x.com"},
        )
        persister.persist(
            row, tenant_id=uuid4(), connector_id="mock", batch_id=uuid4()
        )
        # First db.execute call = SELECT FOR UPDATE.
        first_sql = str(db.execute.call_args_list[0][0][0])
        assert "IS NOT DISTINCT FROM" in first_sql
        assert "FOR UPDATE" in first_sql
        assert "ORDER BY source_id" in first_sql


# ── Delta 2: bitemporal SCD-2 archive SQL shape ──────────────────────────


class TestDelta2BitemporalArchive:
    def test_archive_sql_uses_record_id_valid_from_valid_to_changed_by(
        self, persister: CIPRowPersister, db: MagicMock
    ) -> None:
        # Setup: SELECT returns a current row → diff says changed →
        # archive to history triggers.
        existing: dict[str, object] = {
            "id": str(uuid4()),
            "email": "a@x.com",
            "phone": None,
            "first_name": None,
            "last_name": None,
            "company_name": None,
            "company_id": None,
            "title": None,
            "country": None,
            "city": None,
            "tags": None,
            "lifecycle_stage": None,
            "properties": {},
            "tenant_id": str(uuid4()),
            "client_id": None,
            "source_connector": "mock",
            "source_id": "c001",
            "ingested_at": datetime(2026, 4, 1, tzinfo=UTC),
            "refreshed_at": datetime(2026, 4, 1, tzinfo=UTC),
            "previous_version_id": None,
            "ingestion_batch_id": str(uuid4()),
            "authority": "ingested",
            "created_at": datetime(2026, 4, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 4, 1, tzinfo=UTC),
        }
        _stub_select_returns(db, existing)
        # Archive INSERT-SELECT returns the new history_id via scalar_one().
        new_history_id = uuid4()
        db.execute.return_value.scalar_one.return_value = new_history_id

        row = CIPRow(
            target_table="cip_contacts",
            source_id="c001",
            fields={"email": "b@x.com"},  # changed
        )
        result = persister.persist(
            row,
            tenant_id=uuid4(),
            connector_id="mock-connector",
            batch_id=uuid4(),
        )
        assert result.updated == 1
        assert result.history == 1

        # The archive INSERT-SELECT is the second db.execute call (after SELECT).
        archive_sql = str(db.execute.call_args_list[1][0][0])
        # Verify bitemporal SCD-2 columns are in INSERT clause:
        assert "history_id" in archive_sql
        assert "record_id" in archive_sql
        assert "valid_from" in archive_sql
        assert "valid_to" in archive_sql
        assert "changed_by" in archive_sql
        assert "change_reason" in archive_sql
        # Verify SELECT expressions:
        assert "gen_random_uuid()" in archive_sql
        assert "now()" in archive_sql
        # The connector_id is bound as :changed_by; verify the param.
        archive_params = db.execute.call_args_list[1][0][1]
        assert archive_params["changed_by"] == "mock-connector"

    def test_unchanged_row_emits_refresh_only_update(
        self, persister: CIPRowPersister, db: MagicMock
    ) -> None:
        existing = {
            "id": str(uuid4()),
            "email": "a@x.com",
            "properties": {},
            "tenant_id": str(uuid4()),
        }
        _stub_select_returns(db, existing)
        row = CIPRow(
            target_table="cip_contacts",
            source_id="c001",
            fields={"email": "a@x.com"},  # unchanged
        )
        result = persister.persist(
            row, tenant_id=uuid4(), connector_id="mock", batch_id=uuid4()
        )
        assert result == PersistResult(skipped=1)
        # Only 2 calls: SELECT + UPDATE refreshed_at.
        assert db.execute.call_count == 2
        update_sql = str(db.execute.call_args_list[1][0][0])
        assert "SET refreshed_at = now()" in update_sql


# ── Delta 4: extras column mapping in INSERT path ────────────────────────


class TestExtrasColumnInsert:
    def test_insert_uses_per_table_extras_column_name(
        self, persister: CIPRowPersister, db: MagicMock
    ) -> None:
        # cip_contacts → extras column "properties".
        _stub_select_returns(db, None)
        row = CIPRow(
            target_table="cip_contacts",
            source_id="c001",
            fields={"email": "a@x.com"},
            overflow={"x": 1},
        )
        persister.persist(
            row, tenant_id=uuid4(), connector_id="mock", batch_id=uuid4()
        )
        # Second execute = INSERT.
        insert_sql = str(db.execute.call_args_list[1][0][0])
        assert "properties" in insert_sql
        assert "CAST(:_extras AS jsonb)" in insert_sql

    def test_clients_insert_uses_metadata_column_name(
        self, persister: CIPRowPersister, db: MagicMock
    ) -> None:
        # Delta 4: cip_clients extras column is `metadata`.
        persister._col_cache["cip_clients"] = [
            "id", "tenant_id", "client_id", "source_connector", "source_id",
            "ingested_at", "refreshed_at", "previous_version_id",
            "ingestion_batch_id", "authority",
            "name", "slug", "industry", "metadata",
            "created_at", "updated_at",
        ]
        _stub_select_returns(db, None)
        row = CIPRow(
            target_table="cip_clients",
            source_id="cl-1",
            fields={"name": "Acme", "slug": "acme"},
            overflow={"region": "us"},
        )
        persister.persist(
            row, tenant_id=uuid4(), connector_id="mock", batch_id=uuid4()
        )
        insert_sql = str(db.execute.call_args_list[1][0][0])
        # The extras column in the INSERT must be `metadata`, not `properties`.
        # The bind param name `:_extras` is generic; the column name varies.
        assert "metadata" in insert_sql
        assert "properties" not in insert_sql
