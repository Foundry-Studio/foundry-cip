# foundry: kind=test domain=client-intelligence-platform
"""RLS smoke test — cip_connector_property_registry.

Validates SPEC §7: registry rows are tenant-scoped; cross-tenant queries
return zero rows. The registry has no history table.
"""

import uuid

import pytest
from sqlalchemy import text

from tests.migrations.conftest import (
    TENANT_A,
    TENANT_B,
    session_as_tenant,
    session_no_tenant,
)


def _insert_registry_row(
    session,
    tenant_id: str,
    connector: str,
    object_type: str,
    property_name: str,
) -> str:
    row_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO cip_connector_property_registry "
            "(registry_id, tenant_id, connector, object_type, property_name, "
            " property_type, storage_location, cip_table) "
            "VALUES (:rid, :tid, :conn, :ot, :pn, 'string', 'column', :ct)"
        ),
        {
            "rid": row_id,
            "tid": tenant_id,
            "conn": connector,
            "ot": object_type,
            "pn": property_name,
            "ct": f"cip_{object_type}",
        },
    )
    return row_id


def test_rls_cip_registry_cross_tenant_returns_zero(engine):
    """Tenant B context sees zero registry rows from Tenant A."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_registry_row(setup, TENANT_A, "fixture", "companies", "rls_test_region")

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text(
                "SELECT count(*) FROM cip_connector_property_registry "
                "WHERE property_name = 'rls_test_region'"
            )
        ).scalar()
        assert rows == 0, f"Cross-tenant must return 0 rows, got {rows}"


def test_rls_cip_registry_tenant_a_sees_own_rows(engine):
    """Tenant A context sees its own registry rows."""
    with session_no_tenant(engine, commit=True) as setup:
        rid_a = _insert_registry_row(
            setup, TENANT_A, "fixture", "companies", "rls_own_region"
        )
        _insert_registry_row(setup, TENANT_B, "fixture", "companies", "rls_own_language")

    with session_as_tenant(engine, TENANT_A) as s:
        row = s.execute(
            text(
                "SELECT registry_id FROM cip_connector_property_registry "
                "WHERE property_name = 'rls_own_region'"
            )
        ).fetchone()
        assert row is not None, "Tenant A should see its own registry row"

        count_b = s.execute(
            text(
                "SELECT count(*) FROM cip_connector_property_registry "
                "WHERE property_name = 'rls_own_language'"
            )
        ).scalar()
        assert count_b == 0, f"Tenant A must not see Tenant B registry, got {count_b}"


def test_rls_cip_registry_no_set_local_returns_zero(engine):
    """Without SET LOCAL, no registry rows visible."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_registry_row(setup, TENANT_A, "fixture", "contacts", "rls_no_ctx_test")

    with session_no_tenant(engine) as s:
        rows = s.execute(
            text(
                "SELECT count(*) FROM cip_connector_property_registry "
                "WHERE property_name = 'rls_no_ctx_test'"
            )
        ).scalar()
        assert rows == 0, f"No-context query must return 0 rows, got {rows}"


def test_rls_cip_registry_fixture_schema_columns_present(engine):
    """Verify registry table has all columns defined in SPEC S8 schema."""
    with session_as_tenant(engine, TENANT_A) as s:
        required_cols = {
            "registry_id", "tenant_id", "connector", "object_type",
            "property_name", "property_type", "storage_location",
            "column_name", "cip_table", "description", "is_custom",
            "first_seen_at", "last_synced_schema_at",
        }
        rows = s.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'cip_connector_property_registry'"
            )
        ).fetchall()
        actual_cols = {r[0] for r in rows}
        missing = required_cols - actual_cols
        assert not missing, f"Registry table missing columns: {missing}"
