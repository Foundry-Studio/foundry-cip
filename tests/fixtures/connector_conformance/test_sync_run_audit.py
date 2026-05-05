# foundry: kind=test domain=client-intelligence-platform
"""Conformance test §5.6 — cip_sync_runs audit row lifecycle.

Asserts the recorder's status transitions land in the deployed row:
  - success path: status='success', rows counters correct, error_detail NULL
  - partial path: a batch fails but consecutive_batch_failures < 3 →
    status='partial', error_detail populated
  - batch_id is unique per run (UUIDv4)

Per Delta 1 (counter mapping): rows_ingested = rows_created + rows_updated;
rows_skipped = unchanged + drift + duplicate.
"""
from __future__ import annotations

from datetime import UTC, datetime
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
)


def _read_runs(engine: Engine, tenant_id: UUID) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(tenant_id)},
        )
        rows = conn.execute(
            text(
                "SELECT id, batch_id, status, sync_mode, "
                "rows_ingested, rows_created, rows_updated, "
                "rows_skipped, rows_history, error_detail, "
                "started_at, ended_at "
                "FROM cip_sync_runs ORDER BY started_at"
            ),
        ).mappings().all()
    return [dict(r) for r in rows]


@pytest.mark.usefixtures("cleanup_tenant")
def test_success_path_audit_row(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    state = run_sync(
        MockConnector(
            tenant_id=tenant_id,
            records=CANONICAL_CONTACTS[:5],
            schema=CANONICAL_SCHEMA,
        ),
        mock_mapper,
        seeded_engine,
        tenant_id=tenant_id,
    )
    assert state.status == "success"

    runs = _read_runs(seeded_engine, tenant_id)
    assert len(runs) == 1
    r = runs[0]
    assert r["status"] == "success"
    assert r["sync_mode"] == "incremental"
    # Delta 1 mapping.
    assert r["rows_ingested"] == 5  # rows_created + rows_updated = 5 + 0
    assert r["rows_created"] == 5
    assert r["rows_updated"] == 0
    assert r["rows_skipped"] == 0
    assert r["rows_history"] == 0
    assert r["error_detail"] is None
    assert r["started_at"] < r["ended_at"]
    # batch_id is a UUID4 (per recorder); verify shape.
    assert isinstance(r["batch_id"], UUID)


@pytest.mark.usefixtures("cleanup_tenant")
def test_partial_path_persistence_failure_records_error_detail(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    """Force a PersistenceError-class violation by emitting an unsafe domain
    column name. The persister's identifier validator rejects → batch txn
    rolls back → consecutive_batch_failures=1 → not yet abort threshold (3),
    so run continues; status='partial' if at least one batch wrote
    error_detail and no exception escapes.

    NOTE: with batch_size=1 and the bad-column failure on the FIRST record,
    the orchestrator records error_detail and moves to the next batch.
    Subsequent batches succeed → status ends as 'partial' (error_detail set,
    no exception escaped, consecutive_batch_failures < 3).
    """
    # Use a custom mapper that emits an unsafe column name on records ending in -BAD.
    from cip.integration_mesh import CIPMapperBase, CIPRow

    class BadEmitter(CIPMapperBase):
        object_type = "contact"
        target_table = "cip_contacts"

        def map(self, record: dict[str, object]) -> Any:
            rec_id = str(record["id"])
            if rec_id.endswith("-BAD"):
                # Unsafe column name — persister identifier validator rejects.
                yield CIPRow(
                    target_table="cip_contacts",
                    source_id=rec_id,
                    fields={"email; DROP TABLE--": "evil"},
                )
            else:
                yield CIPRow(
                    target_table="cip_contacts",
                    source_id=rec_id,
                    fields={"email": str(record.get("email", ""))},
                )

        def overflow_fields(self) -> list[str]:
            return []

        def authority(self) -> Any:
            return "ingested"

        def ingest_as_knowledge(self, record: dict[str, object]) -> Any:
            return []

    # 3 records: one bad, two good.
    records: list[dict[str, Any]] = [
        {
            "id": "rec-001-BAD",
            "source_id": "rec-001-BAD",
            "email": "doesnt@matter.com",
            "updated_at": datetime(2026, 4, 20, 0, tzinfo=UTC).isoformat(),
        },
        {
            "id": "rec-002",
            "source_id": "rec-002",
            "email": "good1@x.com",
            "updated_at": datetime(2026, 4, 20, 1, tzinfo=UTC).isoformat(),
        },
        {
            "id": "rec-003",
            "source_id": "rec-003",
            "email": "good2@x.com",
            "updated_at": datetime(2026, 4, 20, 2, tzinfo=UTC).isoformat(),
        },
    ]
    state = run_sync(
        MockConnector(
            tenant_id=tenant_id,
            records=records,
            schema=CANONICAL_SCHEMA,
        ),
        BadEmitter(),
        seeded_engine,
        tenant_id=tenant_id,
        batch_size=1,
    )
    # error_detail set → status='partial' (not failed; no exception out).
    assert state.status == "partial"
    assert state.error_detail is not None
    assert state.error_detail.get("type") == "PersistenceError"

    runs = _read_runs(seeded_engine, tenant_id)
    assert len(runs) == 1
    r = runs[0]
    assert r["status"] == "partial"
    assert r["error_detail"] is not None
    # JSONB returned as dict by psycopg.
    assert r["error_detail"]["type"] == "PersistenceError"


@pytest.mark.usefixtures("cleanup_tenants")
def test_batch_id_unique_across_runs(
    seeded_engine: Engine,
    cleanup_tenants: list[UUID],
    mock_mapper: MockMapper,
) -> None:
    """Per recorder: each run has a fresh UUID4 batch_id."""
    from uuid import uuid4

    tids = [uuid4(), uuid4(), uuid4()]
    cleanup_tenants.extend(tids)
    batch_ids: list[UUID] = []
    for tid in tids:
        state = run_sync(
            MockConnector(
                tenant_id=tid,
                records=CANONICAL_CONTACTS[:2],
                schema=CANONICAL_SCHEMA,
            ),
            mock_mapper,
            seeded_engine,
            tenant_id=tid,
        )
        assert state.status == "success"
        batch_ids.append(state.batch_id)
    # 3 distinct UUIDs.
    assert len(set(batch_ids)) == 3
