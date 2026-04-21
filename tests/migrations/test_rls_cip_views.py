# foundry: kind=test domain=client-intelligence-platform
"""RLS smoke test — cip_views and cip_views_history.

Validates SPEC §7: SET LOCAL scopes rows; cross-tenant returns zero.
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


def _insert_view(session, tenant_id: str, view_name: str) -> str:
    row_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO cip_views "
            "(id, tenant_id, source_connector, source_id, ingestion_batch_id, "
            " authority, view_name) "
            "VALUES (:id, :tid, 'test', :sid, :bid, 'validated', :vn)"
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "sid": f"test-{view_name}",
            "bid": FIXTURE_BATCH_A if tenant_id == TENANT_A else FIXTURE_BATCH_B,
            "vn": view_name,
        },
    )
    return row_id


def test_rls_cip_views_cross_tenant_returns_zero(engine):
    """Tenant B context sees zero cip_views rows owned by Tenant A."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_view(setup, TENANT_A, "Lens-A Test View")

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text("SELECT id FROM cip_views WHERE view_name = 'Lens-A Test View'")
        ).fetchall()
        assert rows == [], f"Cross-tenant must return zero rows, got {rows}"


def test_rls_cip_views_tenant_a_sees_own_rows(engine):
    """Tenant A sees its own cip_views row."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_view(setup, TENANT_A, "Lens-A Own Test")
        _insert_view(setup, TENANT_B, "Lens-B Own Test")

    with session_as_tenant(engine, TENANT_A) as s:
        rows = s.execute(
            text(
                "SELECT id FROM cip_views "
                "WHERE view_name IN ('Lens-A Own Test', 'Lens-B Own Test')"
            )
        ).fetchall()
        ids = [str(r[0]) for r in rows]
        assert id_a in ids
        assert len(ids) == 1, f"Expected 1 row for Tenant A, got {len(ids)}"


def test_rls_cip_views_history_cross_tenant_returns_zero(engine):
    """cip_views_history: Tenant B context returns zero rows from Tenant A."""
    with session_no_tenant(engine, commit=True) as setup:
        view_id = _insert_view(setup, TENANT_A, "Hist View Test")
        hist_id = str(uuid.uuid4())
        setup.execute(
            text(
                "INSERT INTO cip_views_history "
                "(history_id, record_id, tenant_id, valid_from, changed_by, "
                " source_connector, source_id, ingested_at, refreshed_at, "
                " ingestion_batch_id, authority, view_name) "
                "VALUES (:hid, :rid, :tid, now(), 'test', 'test', 'h1', "
                "        now(), now(), :bid, 'validated', 'Hist View Test')"
            ),
            {
                "hid": hist_id,
                "rid": view_id,
                "tid": TENANT_A,
                "bid": FIXTURE_BATCH_A,
            },
        )

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text(
                "SELECT count(*) FROM cip_views_history "
                "WHERE tenant_id = CAST(:ta AS uuid)"
            ),
            {"ta": TENANT_A},
        ).scalar()
        assert rows == 0, f"Tenant B must not see Tenant A history, got {rows}"
