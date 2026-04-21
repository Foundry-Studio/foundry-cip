# foundry: kind=test domain=client-intelligence-platform
"""RLS smoke test — cip_clients and cip_clients_history.

Validates SPEC §7 guarantee:
  SET LOCAL app.current_tenant = TENANT_A  →  only TENANT_A rows visible.
  Cross-tenant query (TENANT_B context)    →  zero rows from TENANT_A.
  No SET LOCAL                             →  zero rows (policy blocks NULL).
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _insert_client(session, tenant_id: str, name: str, slug: str) -> str:
    row_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO cip_clients "
            "(id, tenant_id, source_connector, source_id, ingestion_batch_id, "
            " authority, name, slug) "
            "VALUES (:id, :tid, 'test', :sid, :bid, 'validated', :name, :slug)"
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "sid": f"test-{slug}",
            "bid": FIXTURE_BATCH_A if tenant_id == TENANT_A else FIXTURE_BATCH_B,
            "name": name,
            "slug": slug,
        },
    )
    return row_id


def _insert_client_history(session, tenant_id: str, record_id: str) -> str:
    hist_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO cip_clients_history "
            "(history_id, record_id, tenant_id, valid_from, changed_by, "
            " source_connector, source_id, ingested_at, refreshed_at, "
            " ingestion_batch_id, authority, name, slug) "
            "VALUES (:hid, :rid, :tid, now(), 'test', 'test', :sid, "
            "        now(), now(), :bid, 'validated', 'hist-name', 'hist-slug')"
        ),
        {
            "hid": hist_id,
            "rid": record_id,
            "tid": tenant_id,
            "sid": f"hist-{record_id[:8]}",
            "bid": FIXTURE_BATCH_A if tenant_id == TENANT_A else FIXTURE_BATCH_B,
        },
    )
    return hist_id


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_rls_cip_clients_tenant_a_sees_own_rows(engine):
    """Tenant A SET LOCAL returns only Tenant A rows."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_client(setup, TENANT_A, "Client A", "client-a-rls-test")
        _insert_client(setup, TENANT_B, "Client B", "client-b-rls-test")

    with session_as_tenant(engine, TENANT_A) as s:
        rows = s.execute(
            text(
                "SELECT id FROM cip_clients "
                "WHERE slug IN ('client-a-rls-test', 'client-b-rls-test')"
            )
        ).fetchall()
        ids = [str(r[0]) for r in rows]
        assert id_a in ids, "Tenant A should see its own row"
        assert len(ids) == 1, f"Expected 1 row, got {len(ids)}"


def test_rls_cip_clients_cross_tenant_returns_zero(engine):
    """Tenant B SET LOCAL returns zero rows inserted under Tenant A."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_client(setup, TENANT_A, "Only A Client", "only-a-rls-test")

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text("SELECT id FROM cip_clients WHERE slug = 'only-a-rls-test'")
        ).fetchall()
        assert rows == [], f"Cross-tenant query must return zero rows, got {rows}"


def test_rls_cip_clients_no_set_local_returns_zero(engine):
    """Without SET LOCAL, RLS policy blocks all rows (current_setting = NULL/unset)."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_client(setup, TENANT_A, "No Context Client", "no-ctx-rls-test")

    with session_no_tenant(engine) as s:
        rows = s.execute(
            text(
                "SELECT count(*) FROM cip_clients "
                "WHERE slug = 'no-ctx-rls-test'"
            )
        ).scalar()
        assert rows == 0, f"No-context query must return zero rows, got {rows}"


def test_rls_cip_clients_history_cross_tenant_returns_zero(engine):
    """cip_clients_history: Tenant B context returns zero rows owned by Tenant A."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_client(setup, TENANT_A, "History A Client", "hist-a-rls-test")
        _insert_client_history(setup, TENANT_A, id_a)

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text(
                "SELECT count(*) FROM cip_clients_history "
                "WHERE tenant_id = CAST(:ta AS uuid)"
            ),
            {"ta": TENANT_A},
        ).scalar()
        assert rows == 0, (
            f"Tenant B context must not see Tenant A history rows, got {rows}"
        )


def test_rls_cip_clients_history_tenant_a_sees_own_history(engine):
    """cip_clients_history: Tenant A context sees only its own history rows."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_client(setup, TENANT_A, "History Own", "hist-own-rls-test")
        hist_id = _insert_client_history(setup, TENANT_A, id_a)

    with session_as_tenant(engine, TENANT_A) as s:
        rows = s.execute(
            text(
                "SELECT history_id FROM cip_clients_history "
                "WHERE record_id = CAST(:rid AS uuid)"
            ),
            {"rid": id_a},
        ).fetchall()
        ids = [str(r[0]) for r in rows]
        assert hist_id in ids, "Tenant A should see its own history row"
