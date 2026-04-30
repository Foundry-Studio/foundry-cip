# foundry: kind=test domain=client-intelligence-platform
"""RLS smoke test — cip_sync_runs.

cip_sync_runs has no history table (SPEC §3). Validates:
  - Tenant A SET LOCAL sees only its own sync run rows.
  - Tenant B context returns zero Tenant A rows.
  - No SET LOCAL returns zero rows.
"""

import uuid

from sqlalchemy import text

from tests.migrations.conftest import (
    TENANT_A,
    TENANT_B,
    session_as_tenant,
    session_no_tenant,
)


def _insert_sync_run(session, tenant_id: str) -> str:
    row_id = str(uuid.uuid4())
    batch = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO cip_sync_runs "
            "(id, tenant_id, connector_id, connector_name, batch_id, status) "
            "VALUES (:id, :tid, 'fixture_v1', 'fixture', :bid, 'success')"
        ),
        {"id": row_id, "tid": tenant_id, "bid": batch},
    )
    return row_id


def test_rls_cip_sync_runs_cross_tenant_returns_zero(engine):
    """Tenant B context returns zero rows for Tenant A sync runs."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_sync_run(setup, TENANT_A)

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text("SELECT count(*) FROM cip_sync_runs WHERE tenant_id = CAST(:ta AS uuid)"),
            {"ta": TENANT_A},
        ).scalar()
        assert rows == 0, f"Cross-tenant must return 0 rows, got {rows}"


def test_rls_cip_sync_runs_tenant_a_sees_own_rows(engine):
    """Tenant A context sees only its own sync run rows."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_sync_run(setup, TENANT_A)
        _insert_sync_run(setup, TENANT_B)

    with session_as_tenant(engine, TENANT_A) as s:
        count_b = s.execute(
            text("SELECT count(*) FROM cip_sync_runs WHERE tenant_id = CAST(:tb AS uuid)"),
            {"tb": TENANT_B},
        ).scalar()
        assert count_b == 0, (
            f"Tenant A context must not see Tenant B sync runs, got {count_b}"
        )


def test_rls_cip_sync_runs_no_set_local_returns_zero(engine):
    """Without SET LOCAL, no rows visible (RLS blocks unset tenant context)."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_sync_run(setup, TENANT_A)

    with session_no_tenant(engine) as s:
        rows = s.execute(
            text("SELECT count(*) FROM cip_sync_runs")
        ).scalar()
        assert rows == 0, f"No-context query must return 0 rows, got {rows}"
