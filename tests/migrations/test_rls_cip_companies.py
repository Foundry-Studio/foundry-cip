# foundry: kind=test domain=client-intelligence-platform
"""RLS smoke test — cip_companies and cip_companies_history.

Validates SPEC §7: cross-tenant queries return zero rows.
Also validates the region column used by Lens-B is present and RLS-scoped.
"""

import uuid

import pytest
from sqlalchemy import text

from tests.migrations.conftest import (
    FIXTURE_BATCH_A,
    FIXTURE_BATCH_B,
    TENANT_A,
    TENANT_B,
    session_as_tenant,
    session_no_tenant,
)


def _insert_company(session, tenant_id: str, name: str, region: str = "EMEA") -> str:
    row_id = str(uuid.uuid4())
    bid = FIXTURE_BATCH_A if tenant_id == TENANT_A else FIXTURE_BATCH_B
    session.execute(
        text(
            "INSERT INTO cip_companies "
            "(id, tenant_id, source_connector, source_id, ingestion_batch_id, "
            " authority, name, region) "
            "VALUES (:id, :tid, 'test', :sid, :bid, 'validated', :name, :region)"
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "sid": f"co-{name[:8]}",
            "bid": bid,
            "name": name,
            "region": region,
        },
    )
    return row_id


def _insert_company_history(session, tenant_id: str, record_id: str) -> str:
    hist_id = str(uuid.uuid4())
    bid = FIXTURE_BATCH_A if tenant_id == TENANT_A else FIXTURE_BATCH_B
    session.execute(
        text(
            "INSERT INTO cip_companies_history "
            "(history_id, record_id, tenant_id, valid_from, changed_by, "
            " source_connector, source_id, ingested_at, refreshed_at, "
            " ingestion_batch_id, authority, name) "
            "VALUES (:hid, :rid, :tid, now(), 'test', 'test', :sid, "
            "        now(), now(), :bid, 'validated', 'hist-co')"
        ),
        {"hid": hist_id, "rid": record_id, "tid": tenant_id,
         "sid": f"h-{record_id[:8]}", "bid": bid},
    )
    return hist_id


def test_rls_cip_companies_cross_tenant_returns_zero(engine):
    """Tenant B context sees zero cip_companies rows from Tenant A."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_company(setup, TENANT_A, "Acme Corp A")

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text("SELECT count(*) FROM cip_companies WHERE name = 'Acme Corp A'")
        ).scalar()
        assert rows == 0, f"Cross-tenant must return 0 rows, got {rows}"


def test_rls_cip_companies_tenant_a_sees_own_rows(engine):
    """Tenant A context sees its own company rows (with region dimension)."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_company(setup, TENANT_A, "EMEA Corp A", region="EMEA")
        _insert_company(setup, TENANT_B, "AMER Corp B", region="AMER")

    with session_as_tenant(engine, TENANT_A) as s:
        row = s.execute(
            text("SELECT id, region FROM cip_companies WHERE name = 'EMEA Corp A'")
        ).fetchone()
        assert row is not None, "Tenant A should see its own company"
        assert row[1] == "EMEA", f"region should be EMEA, got {row[1]}"

        absent = s.execute(
            text("SELECT count(*) FROM cip_companies WHERE name = 'AMER Corp B'")
        ).scalar()
        assert absent == 0, f"Tenant A must not see Tenant B company, got {absent}"


def test_rls_cip_companies_history_cross_tenant_returns_zero(engine):
    """cip_companies_history: Tenant B context returns zero Tenant A rows."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_company(setup, TENANT_A, "Hist Corp A")
        _insert_company_history(setup, TENANT_A, id_a)

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text(
                "SELECT count(*) FROM cip_companies_history "
                "WHERE tenant_id = CAST(:ta AS uuid)"
            ),
            {"ta": TENANT_A},
        ).scalar()
        assert rows == 0, f"Cross-tenant history must return 0 rows, got {rows}"


def test_rls_cip_companies_history_tenant_a_sees_own_history(engine):
    """Tenant A context sees its own cip_companies_history rows."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_company(setup, TENANT_A, "Own Hist Corp A")
        hist_id = _insert_company_history(setup, TENANT_A, id_a)

    with session_as_tenant(engine, TENANT_A) as s:
        row = s.execute(
            text(
                "SELECT history_id FROM cip_companies_history "
                "WHERE history_id = CAST(:hid AS uuid)"
            ),
            {"hid": hist_id},
        ).fetchone()
        assert row is not None, "Tenant A should see its own company history row"
