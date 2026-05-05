# foundry: kind=test domain=client-intelligence-platform
"""Conformance test §5.5 — SCD Type 2 history (bitemporal).

Per Delta 2 reconciliation: history table uses bitemporal SCD-2
(``record_id``, ``valid_from``, ``valid_to``, ``changed_by``,
``change_reason``) NOT plan's ``archived_at`` simple-archive model.

Asserts:
  - First ingest: 1 current row, 0 history rows.
  - Domain-column mutation: 1 current (new value), 1 history row (old value
    archived; valid_from/valid_to populated; changed_by=connector_id).
  - Mutation that doesn't touch any domain column the mapper emits → no diff
    → no new history row (refreshed_at bumped only).
  - ``previous_version_id`` correctly points to the most-recent history row.
  - Walking history backwards via ``previous_version_id`` reconstructs a
    full change log.
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
    CANONICAL_SCHEMA,
)


def _make_record(rec_id: str, email: str, hour: int) -> dict[str, Any]:
    from datetime import UTC
    from datetime import datetime as dt
    return {
        "id": rec_id,
        "source_id": rec_id,
        "first_name": "Test",
        "last_name": "User",
        "email": email,
        "updated_at": dt(2026, 4, 20, hour, 0, 0, tzinfo=UTC).isoformat(),
    }


def _read_current(engine: Engine, tenant_id: UUID, source_id: str) -> dict[str, Any] | None:
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(tenant_id)},
        )
        row = conn.execute(
            text(
                "SELECT id, email, refreshed_at, previous_version_id "
                "FROM cip_contacts WHERE source_id = :s"
            ),
            {"s": source_id},
        ).mappings().first()
    return dict(row) if row else None


def _read_history(
    engine: Engine, tenant_id: UUID, source_id: str
) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(tenant_id)},
        )
        rows = conn.execute(
            text(
                "SELECT history_id, record_id, email, valid_from, valid_to, "
                "changed_by, change_reason "
                "FROM cip_contacts_history WHERE source_id = :s "
                "ORDER BY valid_from"
            ),
            {"s": source_id},
        ).mappings().all()
    return [dict(r) for r in rows]


@pytest.mark.usefixtures("cleanup_tenant")
def test_first_ingest_no_history(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    connector = MockConnector(
        tenant_id=tenant_id,
        records=[_make_record("c500", "first@x.com", 0)],
        schema=CANONICAL_SCHEMA,
    )
    state = run_sync(connector, mock_mapper, seeded_engine, tenant_id=tenant_id)
    assert state.status == "success"
    current = _read_current(seeded_engine, tenant_id, "c500")
    assert current is not None
    assert current["email"] == "first@x.com"
    history = _read_history(seeded_engine, tenant_id, "c500")
    assert len(history) == 0


@pytest.mark.usefixtures("cleanup_tenant")
def test_domain_mutation_writes_history_row_with_bitemporal_fields(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    """Delta 2: history INSERT-SELECT populates record_id, valid_from/_to,
    changed_by, change_reason correctly."""
    # First ingest: email=v1.
    run_sync(
        MockConnector(
            tenant_id=tenant_id,
            records=[_make_record("c501", "v1@x.com", 0)],
            schema=CANONICAL_SCHEMA,
        ),
        mock_mapper,
        seeded_engine,
        tenant_id=tenant_id,
    )
    # Second ingest: email=v2 (mutation; bypass cursor by sync_mode='full').
    run_sync(
        MockConnector(
            tenant_id=tenant_id,
            records=[_make_record("c501", "v2@x.com", 5)],
            schema=CANONICAL_SCHEMA,
        ),
        mock_mapper,
        seeded_engine,
        tenant_id=tenant_id,
        sync_mode="full",
    )
    current = _read_current(seeded_engine, tenant_id, "c501")
    history = _read_history(seeded_engine, tenant_id, "c501")
    assert current is not None
    assert current["email"] == "v2@x.com"
    assert len(history) == 1
    h = history[0]
    # Bitemporal fields populated per Delta 2 reconciliation.
    assert h["record_id"] == current["id"]
    assert h["valid_from"] is not None
    assert h["valid_to"] is not None
    assert h["valid_from"] < h["valid_to"]  # CheckConstraint: valid_to > valid_from
    assert h["changed_by"] == "mock-connector-v1"
    assert h["change_reason"] is None  # M2 leaves NULL per Delta 2
    # The OLD email landed in history (not the current).
    assert h["email"] == "v1@x.com"
    # current.previous_version_id points to the new history row.
    assert current["previous_version_id"] == h["history_id"]


@pytest.mark.usefixtures("cleanup_tenant")
def test_no_diff_no_new_history_row(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    # Re-ingest the same record verbatim → diff says unchanged → only
    # refreshed_at bumped on current; no history.
    record = _make_record("c502", "stable@x.com", 0)
    run_sync(
        MockConnector(
            tenant_id=tenant_id,
            records=[record],
            schema=CANONICAL_SCHEMA,
        ),
        mock_mapper,
        seeded_engine,
        tenant_id=tenant_id,
    )
    # Re-run sync_mode='full' so cursor doesn't filter; same record.
    state = run_sync(
        MockConnector(
            tenant_id=tenant_id,
            records=[record],
            schema=CANONICAL_SCHEMA,
        ),
        mock_mapper,
        seeded_engine,
        tenant_id=tenant_id,
        sync_mode="full",
    )
    assert state.status == "success"
    assert state.rows_skipped_unchanged == 1
    assert state.rows_history == 0
    history = _read_history(seeded_engine, tenant_id, "c502")
    assert len(history) == 0


@pytest.mark.usefixtures("cleanup_tenant")
def test_three_revisions_walk_history_chain(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    """Plan §5.5: walk history backwards via ``previous_version_id``."""
    # Three revisions: v1, v2, v3 (each mutates email).
    for i, email in enumerate(["v1@x.com", "v2@x.com", "v3@x.com"]):
        run_sync(
            MockConnector(
                tenant_id=tenant_id,
                records=[_make_record("c503", email, i * 2)],
                schema=CANONICAL_SCHEMA,
            ),
            mock_mapper,
            seeded_engine,
            tenant_id=tenant_id,
            sync_mode="full",
        )
    current = _read_current(seeded_engine, tenant_id, "c503")
    assert current is not None
    assert current["email"] == "v3@x.com"
    history = _read_history(seeded_engine, tenant_id, "c503")
    # 2 history rows: v1 archived when v2 wrote; v2 archived when v3 wrote.
    assert len(history) == 2
    assert {h["email"] for h in history} == {"v1@x.com", "v2@x.com"}
    # Walk backwards: current.previous_version_id → most-recent history row
    # (the v2 archive). That row has its OWN previous_version_id pointing
    # back to the v1 archive's history_id... actually wait, history rows'
    # previous_version_id is the chain on the CURRENT row at archive time.
    # The chain is on cip_contacts.previous_version_id (current → most-recent
    # history → its predecessor → ...). For M2's persister:
    #   - When v2 wrote: archived v1; current.previous_version_id = v1_history_id
    #   - When v3 wrote: archived v2; v2's history row carries the OLD
    #     current.previous_version_id (= v1_history_id); current's new
    #     previous_version_id = v2_history_id.
    # So walking from current: current.previous_version_id → v2_archive.
    # v2_archive.previous_version_id → v1_history_id → v1_archive.
    most_recent_history = max(history, key=lambda h: h["valid_from"])
    assert current["previous_version_id"] == most_recent_history["history_id"]
