# foundry: kind=test domain=client-intelligence-platform
"""Conformance test §5.3 — Incremental sync end-to-end.

This is the SQL-binding-heavy dry-run test. Exercises:
  - persister INSERT/UPDATE with EXTRAS_COLUMN_BY_TABLE (Delta 4)
  - bitemporal SCD-2 archive INSERT...SELECT with reflected column order (Delta 2)
  - source_id IS NOT DISTINCT FROM (Delta 6)
  - JSONB roundtrip on properties column
  - cursor write atomicity within per-batch txn (C-4)
  - SyncRunRecorder INSERT-then-UPDATE with the 5-counter mapping (Delta 1)
  - run_sync return value matches deployed cip_sync_runs row state

Scenarios:
  1. First run with 10 baseline contacts → all 10 ingested, cursor advanced to T9.
  2. Second run with delta corpus (2 new + 1 mutated dup) → 2 created, 1 updated,
     1 history row written, cursor advanced to T12.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from cip.integration_mesh import run_sync
from tests.fixtures.connector_conformance.conftest import (
    MockConnector,
    MockMapper,
)
from tests.fixtures.connector_conformance.fixtures.records import (
    CANONICAL_CONTACTS,
    CANONICAL_SCHEMA,
    DELTA_CONTACTS,
)


def _count_rows(
    engine: Engine, table: str, tenant_id: UUID
) -> int:
    """Tenant-scoped row count via tenant context."""
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(tenant_id)},
        )
        result = conn.execute(
            text(f"SELECT COUNT(*) FROM {table}"),
        ).scalar()
    return int(result or 0)


def _read_cip_sync_runs(
    engine: Engine, tenant_id: UUID
) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(tenant_id)},
        )
        result = conn.execute(
            text(
                "SELECT id, status, sync_mode, rows_ingested, rows_history, "
                "rows_created, rows_updated, rows_skipped, "
                "cursor_state, started_at, ended_at "
                "FROM cip_sync_runs ORDER BY started_at"
            ),
        ).mappings().all()
    return [dict(r) for r in result]


@pytest.mark.usefixtures("cleanup_tenant")
def test_first_run_full_sync_baseline_corpus(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    """First run: 10 baseline contacts, no prior cursor.

    Asserts:
    - All 10 contacts persisted to cip_contacts
    - 0 history rows (no prior versions to archive)
    - cip_sync_runs row created with status='success', rows_ingested=10
    - cursor_state advanced to T9 (last canonical record)
    - Property registry seeded with 5 descriptors
    """
    connector = MockConnector(
        tenant_id=tenant_id,
        records=CANONICAL_CONTACTS,
        schema=CANONICAL_SCHEMA,
    )
    state = run_sync(
        connector,
        mock_mapper,
        seeded_engine,
        tenant_id=tenant_id,
        sync_mode="incremental",
        initial_cursor=None,
    )

    # SyncRunState assertions.
    assert state.status == "success", f"got {state.status}: {state.error_detail}"
    assert state.rows_received == 10
    assert state.rows_created == 10
    assert state.rows_updated == 0
    assert state.rows_skipped_unchanged == 0
    assert state.rows_skipped_drift == 0
    assert state.rows_skipped_duplicate == 0
    assert state.rows_history == 0
    assert state.cursor_state is not None
    assert "last_incremental_key" in state.cursor_state
    # Cursor should be the latest record's incremental_key (T9 = 09:00:00 UTC).
    assert "2026-04-20T09:00:00" in str(state.cursor_state["last_incremental_key"])

    # Domain table assertions.
    assert _count_rows(seeded_engine, "cip_contacts", tenant_id) == 10
    assert _count_rows(seeded_engine, "cip_contacts_history", tenant_id) == 0

    # Property registry: 5 descriptors written via best-effort upsert.
    assert (
        _count_rows(
            seeded_engine, "cip_connector_property_registry", tenant_id
        )
        == 5
    )

    # cip_sync_runs row.
    runs = _read_cip_sync_runs(seeded_engine, tenant_id)
    assert len(runs) == 1
    r = runs[0]
    assert r["status"] == "success"
    assert r["sync_mode"] == "incremental"
    # Delta 1 mapping: rows_ingested = rows_created + rows_updated = 10 + 0
    assert r["rows_ingested"] == 10
    assert r["rows_created"] == 10
    assert r["rows_updated"] == 0
    assert r["rows_skipped"] == 0
    assert r["rows_history"] == 0


@pytest.mark.usefixtures("cleanup_tenant")
def test_second_run_delta_with_scd2_archive(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    """First run baseline, then delta run with 2 new + 1 mutated record.

    Delta corpus: c011 (new), c012 (new), c003 (mutated email).

    Asserts after delta run:
    - 12 contacts in cip_contacts (10 baseline + 2 new; c003 updated in place)
    - 1 history row in cip_contacts_history (the old c003 archived)
    - History row has bitemporal SCD-2 fields populated:
      record_id=current.id, valid_from=old.refreshed_at, valid_to=now(),
      changed_by=connector_id, change_reason=NULL
    - cip_sync_runs has 2 rows (one per run)
    - Second run's cursor advanced to T12
    """
    # First run: baseline.
    connector1 = MockConnector(
        tenant_id=tenant_id,
        records=CANONICAL_CONTACTS,
        schema=CANONICAL_SCHEMA,
    )
    state1 = run_sync(
        connector1,
        mock_mapper,
        seeded_engine,
        tenant_id=tenant_id,
        sync_mode="incremental",
        initial_cursor=None,
    )
    assert state1.status == "success"

    # Second run: delta. Pass cursor from first run.
    connector2 = MockConnector(
        tenant_id=tenant_id,
        records=CANONICAL_CONTACTS + DELTA_CONTACTS,  # full corpus
        schema=CANONICAL_SCHEMA,
    )
    state2 = run_sync(
        connector2,
        mock_mapper,
        seeded_engine,
        tenant_id=tenant_id,
        sync_mode="incremental",
        initial_cursor=state1.cursor_state,
    )

    # SyncRunState second run assertions.
    assert state2.status == "success", f"got {state2.status}: {state2.error_detail}"
    # Cursor T9 with default 300s safety window → adjusted cursor T8:55.
    # Connector emits any record with updated_at > T8:55:
    #   c010 (T9) — re-emits (within safety window) → diff says no change → skipped
    #   c011 (T10), c012 (T11) — new
    #   c003-mutated (T12) — updated; old archived to history
    # = 4 records yielded; 2 created, 1 updated, 1 skipped_unchanged, 1 history.
    assert state2.rows_received == 4
    assert state2.rows_created == 2  # c011, c012
    assert state2.rows_updated == 1  # c003 (mutated email)
    assert state2.rows_skipped_unchanged == 1  # c010 re-emitted by safety window, no change
    assert state2.rows_history == 1  # old c003 archived

    # Domain table: 12 contacts (10 baseline + 2 new); c003 mutated in place.
    assert _count_rows(seeded_engine, "cip_contacts", tenant_id) == 12
    # History: 1 row (the old c003).
    assert _count_rows(seeded_engine, "cip_contacts_history", tenant_id) == 1

    # Inspect the archived history row to verify bitemporal SCD-2 fields (Delta 2).
    with seeded_engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(tenant_id)},
        )
        hist = conn.execute(
            text(
                "SELECT history_id, record_id, valid_from, valid_to, "
                "changed_by, change_reason, email "
                "FROM cip_contacts_history WHERE source_id = 'c003'"
            ),
        ).mappings().first()
    assert hist is not None
    assert hist["record_id"] is not None  # FK to current cip_contacts.id
    assert hist["valid_from"] is not None
    assert hist["valid_to"] is not None
    # changed_by populated with connector_id (per Delta 2 reconciliation).
    assert hist["changed_by"] == "mock-connector-v1"
    # change_reason: M2 leaves NULL (Phase 3+ may populate).
    assert hist["change_reason"] is None
    # Archived row carries the OLD email (c003's first ingest had carlos@ex.com).
    assert hist["email"] == "carlos@ex.com"

    # Cursor advanced to T12.
    assert state2.cursor_state is not None
    assert "2026-04-20T12:00:00" in str(state2.cursor_state["last_incremental_key"])

    # cip_sync_runs has 2 rows.
    runs = _read_cip_sync_runs(seeded_engine, tenant_id)
    assert len(runs) == 2
    # Second run's deployed-5 counter mapping.
    r2 = runs[1]
    assert r2["status"] == "success"
    # Delta 1: rows_ingested = rows_created + rows_updated = 2 + 1 = 3
    assert r2["rows_ingested"] == 3
    # rows_skipped = unchanged + drift + duplicate = 1 + 0 + 0 = 1 (c010 re-emit)
    assert r2["rows_skipped"] == 1
    assert r2["rows_created"] == 2
    assert r2["rows_updated"] == 1
    assert r2["rows_history"] == 1


@pytest.mark.usefixtures("cleanup_tenant")
def test_multi_batch_cursor_advances_per_batch(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    """batch_size=3 against the 10-record corpus → 4 batches.

    Forces the per-batch cursor-write path to fire multiple times in one
    run. Verifies:
      - All 10 records persisted
      - Final cursor = T9 (last record's incremental_key)
      - cip_sync_runs has ONE row (one run, multiple batches inside)
    """
    state = run_sync(
        MockConnector(
            tenant_id=tenant_id,
            records=CANONICAL_CONTACTS,
            schema=CANONICAL_SCHEMA,
        ),
        mock_mapper,
        seeded_engine,
        tenant_id=tenant_id,
        batch_size=3,
    )
    assert state.status == "success"
    assert state.rows_received == 10
    assert state.rows_created == 10
    assert state.cursor_state is not None
    # Final cursor advance hits T9 (last canonical record's hour).
    assert "2026-04-20T09:00:00" in str(state.cursor_state["last_incremental_key"])

    # Domain table check.
    assert _count_rows(seeded_engine, "cip_contacts", tenant_id) == 10

    # Single sync run row (multiple batches are internal to the orchestrator).
    runs = _read_cip_sync_runs(seeded_engine, tenant_id)
    assert len(runs) == 1
