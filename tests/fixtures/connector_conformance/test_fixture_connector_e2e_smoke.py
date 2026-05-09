# foundry: kind=test domain=client-intelligence-platform
"""M3 e2e SMOKE — FixtureConnector + FixtureMapper round-trip on the 10-contact
SMOKE corpus through the full sync path against real Postgres.

Lower-risk capstone validation per M3 §7 dispatch — verifies the deployed
chain (run_sync → orchestrator → persister → SCD differ → recorder →
knowledge-hook) end-to-end with FixtureConnector before STANDARD's
1150-row volume hits the same path.

M3 Δ4 (placement reconciliation, 2026-05-08): plan §7 calls for these e2e
tests under ``tests/integration_mesh/``; the testcontainer + seeded_engine
fixtures live in ``tests/fixtures/connector_conformance/conftest.py``.
Co-locating the e2e tests here avoids hoisting the fixtures up the conftest
tree (which would risk regressing 30+ existing conformance tests). Atlas
v3.1 plan-hygiene TODO: either update plan §7 placement OR refactor the
testcontainer fixtures to ``tests/conftest.py`` for cross-suite access.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from cip.integration_mesh import (
    CorpusSize,
    FixtureConnector,
    FixtureMapper,
    run_sync,
)


def _count(engine: Engine, tenant_id: UUID, table: str) -> int:
    with engine.connect() as conn:
        n = conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        ).scalar()
    return int(n or 0)


def _registry_rows(
    engine: Engine, tenant_id: UUID
) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(tenant_id)},
        )
        rows = conn.execute(
            text(
                "SELECT property_name, property_type, storage_location, "
                "column_name, is_custom, cip_table, object_type "
                "FROM cip_connector_property_registry "
                "WHERE connector = 'fixture-connector-v1' "
                "ORDER BY object_type, property_name"
            ),
        ).mappings().all()
    return [dict(r) for r in rows]


# ── Sub-test 1: first run persists 10 contacts ──────────────────────────


def test_smoke_first_run_persists_10_contacts(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """First run on a fresh tenant: 10 SMOKE contacts → 10 rows in
    cip_contacts; counters reflect 10 received + 10 created."""
    tenant_id = uuid4()
    state = run_sync(
        FixtureConnector(tenant_id=tenant_id, seed=42, size=CorpusSize.SMOKE),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    assert state.status == "success", (
        f"got {state.status}: {state.error_detail}"
    )
    assert state.rows_received == 10
    assert state.rows_created == 10
    assert state.rows_updated == 0
    assert state.rows_skipped_unchanged == 0
    assert state.rows_skipped_drift == 0
    assert state.rows_skipped_duplicate == 0
    assert state.rows_history == 0

    assert _count(seeded_engine, tenant_id, "cip_contacts") == 10
    # SMOKE has 0 of every other table — verify clean isolation.
    assert _count(seeded_engine, tenant_id, "cip_companies") == 0
    assert _count(seeded_engine, tenant_id, "cip_deals") == 0
    assert _count(seeded_engine, tenant_id, "cip_tickets") == 0
    assert _count(seeded_engine, tenant_id, "cip_files") == 0


# ── Sub-test 2: second run is a no-op (acceptance #13 at SMOKE) ─────────


def test_smoke_second_run_is_no_op(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """Re-running run_sync without fixture changes is a no-op:
    rows_skipped_unchanged matches row count; created/updated/history
    all zero. This is acceptance #13 verified at SMOKE volume."""
    tenant_id = uuid4()
    run_sync(
        FixtureConnector(tenant_id=tenant_id, seed=42, size=CorpusSize.SMOKE),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    state2 = run_sync(
        FixtureConnector(tenant_id=tenant_id, seed=42, size=CorpusSize.SMOKE),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    assert state2.status == "success"
    assert state2.rows_received == 10
    assert state2.rows_created == 0
    assert state2.rows_updated == 0
    assert state2.rows_skipped_unchanged == 10
    assert state2.rows_history == 0
    # Final row count unchanged.
    assert _count(seeded_engine, tenant_id, "cip_contacts") == 10


# ── Sub-test 3: property registry populated (≥6 contact descriptors) ────


def test_smoke_property_registry_populated(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """Property registry is populated from ``connector.describe_schema()``
    independently of records emitted. Even though SMOKE only emits
    contacts, the full FixtureConnector schema (30 descriptors across
    6 object types) lands in the registry."""
    tenant_id = uuid4()
    run_sync(
        FixtureConnector(tenant_id=tenant_id, seed=42, size=CorpusSize.SMOKE),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    rows = _registry_rows(seeded_engine, tenant_id)
    # FixtureConnector ships 30 descriptors. Registry-write is best-effort
    # but should land all of them under normal conditions.
    assert len(rows) == 30, f"expected 30 descriptors, got {len(rows)}"
    object_types = {r["object_type"] for r in rows}
    assert object_types == {
        "company",
        "contact",
        "deal",
        "ticket",
        "document",
        "note",  # forward-compat descriptor (note records=0; descriptor present)
    }, f"unexpected object_types: {object_types}"
    # Custom-flag preservation: company.custom_field_1/2 declared is_custom=True.
    custom_rows = [r for r in rows if r["is_custom"] is True]
    custom_names = {r["property_name"] for r in custom_rows}
    assert {"custom_field_1", "custom_field_2"}.issubset(custom_names)


# ── Sub-test 4: no knowledge emissions on SMOKE ─────────────────────────


def test_smoke_no_knowledge_emissions(
    seeded_engine: Engine,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SMOKE has 0 tickets + 0 documents; FixtureMapper only emits
    KnowledgeText for those types. Verify ``ingest_texts_noop`` is
    never invoked. Confirms the Δ8 detect-then-assign machinery doesn't
    spin up unnecessarily on contact-only corpora."""
    spy = MagicMock()
    monkeypatch.setattr(
        "cip.integration_mesh.orchestrator.ingest_texts_noop", spy
    )

    tenant_id = uuid4()
    run_sync(
        FixtureConnector(tenant_id=tenant_id, seed=42, size=CorpusSize.SMOKE),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    assert spy.call_count == 0, (
        f"ingest_texts_noop should not fire on SMOKE (no ticket/doc records); "
        f"got {spy.call_count} calls"
    )
