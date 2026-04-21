# foundry: kind=test domain=client-intelligence-platform
"""RLS smoke test — cip_contacts and cip_contacts_history.

Validates SPEC §7: cross-tenant queries return zero rows.
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


def _insert_contact(session, tenant_id: str, email: str) -> str:
    row_id = str(uuid.uuid4())
    bid = FIXTURE_BATCH_A if tenant_id == TENANT_A else FIXTURE_BATCH_B
    session.execute(
        text(
            "INSERT INTO cip_contacts "
            "(id, tenant_id, source_connector, source_id, ingestion_batch_id, "
            " authority, email) "
            "VALUES (:id, :tid, 'test', :sid, :bid, 'validated', :email)"
        ),
        {"id": row_id, "tid": tenant_id, "sid": email, "bid": bid, "email": email},
    )
    return row_id


def _insert_contact_history(session, tenant_id: str, record_id: str) -> str:
    hist_id = str(uuid.uuid4())
    bid = FIXTURE_BATCH_A if tenant_id == TENANT_A else FIXTURE_BATCH_B
    session.execute(
        text(
            "INSERT INTO cip_contacts_history "
            "(history_id, record_id, tenant_id, valid_from, changed_by, "
            " source_connector, source_id, ingested_at, refreshed_at, "
            " ingestion_batch_id, authority) "
            "VALUES (:hid, :rid, :tid, now(), 'test', 'test', :sid, "
            "        now(), now(), :bid, 'validated')"
        ),
        {"hid": hist_id, "rid": record_id, "tid": tenant_id,
         "sid": f"h-{record_id[:8]}", "bid": bid},
    )
    return hist_id


def test_rls_cip_contacts_cross_tenant_returns_zero(engine):
    """Tenant B context sees zero cip_contacts rows from Tenant A."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_contact(setup, TENANT_A, "alice@tenant-a.test")

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text("SELECT count(*) FROM cip_contacts WHERE email = 'alice@tenant-a.test'")
        ).scalar()
        assert rows == 0, f"Cross-tenant must return 0 rows, got {rows}"


def test_rls_cip_contacts_tenant_a_sees_own_rows(engine):
    """Tenant A context sees its own cip_contacts rows."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_contact(setup, TENANT_A, "bob@tenant-a.test")
        _insert_contact(setup, TENANT_B, "carol@tenant-b.test")

    with session_as_tenant(engine, TENANT_A) as s:
        row = s.execute(
            text("SELECT id FROM cip_contacts WHERE email = 'bob@tenant-a.test'")
        ).fetchone()
        assert row is not None, "Tenant A should see its own contact"
        count_b = s.execute(
            text("SELECT count(*) FROM cip_contacts WHERE email = 'carol@tenant-b.test'")
        ).scalar()
        assert count_b == 0, f"Tenant A must not see Tenant B contact, got {count_b}"


def test_rls_cip_contacts_history_cross_tenant_returns_zero(engine):
    """cip_contacts_history: Tenant B context returns zero Tenant A history rows."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_contact(setup, TENANT_A, "hist-alice@tenant-a.test")
        _insert_contact_history(setup, TENANT_A, id_a)

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text(
                "SELECT count(*) FROM cip_contacts_history "
                "WHERE tenant_id = CAST(:ta AS uuid)"
            ),
            {"ta": TENANT_A},
        ).scalar()
        assert rows == 0, f"Cross-tenant history must return 0 rows, got {rows}"


def test_rls_cip_contacts_history_tenant_a_sees_own_history(engine):
    """Tenant A context sees its own cip_contacts_history rows."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_contact(setup, TENANT_A, "own-hist@tenant-a.test")
        hist_id = _insert_contact_history(setup, TENANT_A, id_a)

    with session_as_tenant(engine, TENANT_A) as s:
        row = s.execute(
            text(
                "SELECT history_id FROM cip_contacts_history "
                "WHERE history_id = CAST(:hid AS uuid)"
            ),
            {"hid": hist_id},
        ).fetchone()
        assert row is not None, "Tenant A should see its own contact history row"
