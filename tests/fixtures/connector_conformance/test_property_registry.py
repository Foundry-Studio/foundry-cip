# foundry: kind=test domain=client-intelligence-platform
"""Conformance test §5.4 — Property registry upsert.

Asserts:
  - 5 PropertyDescriptors land as 5 rows on first sync (3 column + 2 overflow)
  - Re-running the sync with a 6th descriptor → 6 rows (no duplicates)
  - is_custom=True PRESERVED across re-upsert with is_custom=False (M-16 OR-semantics)

Per Delta 10 + 11: writes use deployed-schema column names ``connector``
and ``property_type`` (NOT plan's ``connector_id`` / ``data_type``).
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
)


def _read_registry_rows(
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
                "column_name, is_custom, cip_table "
                "FROM cip_connector_property_registry "
                "WHERE connector = 'mock-connector-v1' "
                "ORDER BY property_name"
            ),
        ).mappings().all()
    return [dict(r) for r in rows]


@pytest.mark.usefixtures("cleanup_tenant")
def test_first_sync_seeds_five_descriptors(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
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
    )
    assert state.status == "success"

    rows = _read_registry_rows(seeded_engine, tenant_id)
    assert len(rows) == 5
    names = {r["property_name"] for r in rows}
    assert names == {"first_name", "last_name", "email", "mock_extra_1", "mock_extra_2"}
    # Storage-location split: 3 column + 2 overflow.
    column_count = sum(1 for r in rows if r["storage_location"] == "column")
    overflow_count = sum(1 for r in rows if r["storage_location"] == "overflow")
    assert column_count == 3
    assert overflow_count == 2
    # Delta 11: SQL column is ``property_type`` (PropertyDescriptor.data_type
    # binds here). All canonical schema entries declare ``data_type="string"``.
    assert all(r["property_type"] == "string" for r in rows)


@pytest.mark.usefixtures("cleanup_tenant")
def test_resync_with_extra_descriptor_upserts_idempotently(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    # First sync: 5 descriptors.
    connector1 = MockConnector(
        tenant_id=tenant_id,
        records=CANONICAL_CONTACTS,
        schema=CANONICAL_SCHEMA,
    )
    run_sync(connector1, mock_mapper, seeded_engine, tenant_id=tenant_id)
    assert len(_read_registry_rows(seeded_engine, tenant_id)) == 5

    # Second sync: 6 descriptors (added "mock_extra_3").
    extended_schema = list(CANONICAL_SCHEMA) + [
        {
            "object_type": "contact",
            "property_name": "mock_extra_3",
            "data_type": "string",
            "is_custom": True,
            "storage_location": "overflow",
            "column_name": None,
            "description": "Tenant-defined custom property 3.",
        }
    ]
    connector2 = MockConnector(
        tenant_id=tenant_id,
        records=CANONICAL_CONTACTS,
        schema=extended_schema,
    )
    run_sync(connector2, mock_mapper, seeded_engine, tenant_id=tenant_id)

    rows = _read_registry_rows(seeded_engine, tenant_id)
    assert len(rows) == 6  # ON CONFLICT DO UPDATE — no duplicates
    names = {r["property_name"] for r in rows}
    assert "mock_extra_3" in names


@pytest.mark.usefixtures("cleanup_tenant")
def test_is_custom_preserved_across_upsert(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    """M-16 / §9 acceptance #22: ``is_custom`` is once-true-stays-true via
    ``is_custom = old OR new``."""
    # First sync: schema entry with is_custom=True.
    schema_custom = [
        {
            "object_type": "contact",
            "property_name": "tenant_custom_field",
            "data_type": "string",
            "is_custom": True,  # initially TRUE
            "storage_location": "column",
            "column_name": "tenant_custom_field",
            "description": "Was custom on first sync.",
        }
    ]
    # Use minimal records (no contacts mapped) — we only care about registry.
    connector1 = MockConnector(
        tenant_id=tenant_id, records=[], schema=schema_custom
    )
    run_sync(connector1, mock_mapper, seeded_engine, tenant_id=tenant_id)
    rows = _read_registry_rows(seeded_engine, tenant_id)
    assert len(rows) == 1
    assert rows[0]["is_custom"] is True

    # Second sync: same property_name but is_custom=False.
    schema_not_custom = [
        {
            "object_type": "contact",
            "property_name": "tenant_custom_field",
            "data_type": "string",
            "is_custom": False,  # downgraded
            "storage_location": "column",
            "column_name": "tenant_custom_field",
            "description": "Re-emit downgraded.",
        }
    ]
    connector2 = MockConnector(
        tenant_id=tenant_id, records=[], schema=schema_not_custom
    )
    run_sync(connector2, mock_mapper, seeded_engine, tenant_id=tenant_id)

    rows = _read_registry_rows(seeded_engine, tenant_id)
    assert len(rows) == 1
    # M-16 invariant: TRUE persists despite re-emit with FALSE.
    assert rows[0]["is_custom"] is True
