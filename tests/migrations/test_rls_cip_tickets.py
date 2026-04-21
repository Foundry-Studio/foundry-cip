# foundry: kind=test domain=client-intelligence-platform
"""RLS smoke test — cip_tickets and cip_tickets_history.

Validates SPEC §7: cross-tenant queries return zero rows.
cip_tickets is the primary fixture data table — the SPEC requires 500 tickets.
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


def _insert_ticket(session, tenant_id: str, subject: str) -> str:
    row_id = str(uuid.uuid4())
    bid = FIXTURE_BATCH_A if tenant_id == TENANT_A else FIXTURE_BATCH_B
    session.execute(
        text(
            "INSERT INTO cip_tickets "
            "(id, tenant_id, source_connector, source_id, ingestion_batch_id, "
            " authority, subject) "
            "VALUES (:id, :tid, 'test', :sid, :bid, 'validated', :subj)"
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "sid": f"tkt-{subject[:12]}",
            "bid": bid,
            "subj": subject,
        },
    )
    return row_id


def _insert_ticket_history(session, tenant_id: str, record_id: str) -> str:
    hist_id = str(uuid.uuid4())
    bid = FIXTURE_BATCH_A if tenant_id == TENANT_A else FIXTURE_BATCH_B
    session.execute(
        text(
            "INSERT INTO cip_tickets_history "
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


def test_rls_cip_tickets_cross_tenant_returns_zero(engine):
    """Tenant B context sees zero cip_tickets rows from Tenant A."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_ticket(setup, TENANT_A, "Refund request from EMEA")

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text(
                "SELECT count(*) FROM cip_tickets "
                "WHERE subject = 'Refund request from EMEA'"
            )
        ).scalar()
        assert rows == 0, f"Cross-tenant must return 0 rows, got {rows}"


def test_rls_cip_tickets_tenant_a_sees_own_rows(engine):
    """Tenant A context sees its own cip_tickets rows, not Tenant B's."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_ticket(setup, TENANT_A, "Password reset A")
        _insert_ticket(setup, TENANT_B, "Password reset B")

    with session_as_tenant(engine, TENANT_A) as s:
        row = s.execute(
            text("SELECT id FROM cip_tickets WHERE subject = 'Password reset A'")
        ).fetchone()
        assert row is not None, "Tenant A should see its own ticket"
        count_b = s.execute(
            text("SELECT count(*) FROM cip_tickets WHERE subject = 'Password reset B'")
        ).scalar()
        assert count_b == 0, f"Tenant A must not see Tenant B ticket, got {count_b}"


def test_rls_cip_tickets_no_set_local_returns_zero(engine):
    """Without SET LOCAL, no tickets visible."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_ticket(setup, TENANT_A, "No ctx ticket")

    with session_no_tenant(engine) as s:
        rows = s.execute(
            text("SELECT count(*) FROM cip_tickets WHERE subject = 'No ctx ticket'")
        ).scalar()
        assert rows == 0, f"No-context query must return 0 rows, got {rows}"


def test_rls_cip_tickets_history_cross_tenant_returns_zero(engine):
    """cip_tickets_history: Tenant B context returns zero Tenant A history rows."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_ticket(setup, TENANT_A, "Hist Ticket A")
        _insert_ticket_history(setup, TENANT_A, id_a)

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text(
                "SELECT count(*) FROM cip_tickets_history "
                "WHERE tenant_id = CAST(:ta AS uuid)"
            ),
            {"ta": TENANT_A},
        ).scalar()
        assert rows == 0, f"Cross-tenant history must return 0 rows, got {rows}"


def test_rls_cip_tickets_history_tenant_a_sees_own_history(engine):
    """Tenant A context sees its own cip_tickets_history rows."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_ticket(setup, TENANT_A, "Own Hist Ticket A")
        hist_id = _insert_ticket_history(setup, TENANT_A, id_a)

    with session_as_tenant(engine, TENANT_A) as s:
        row = s.execute(
            text(
                "SELECT history_id FROM cip_tickets_history "
                "WHERE history_id = CAST(:hid AS uuid)"
            ),
            {"hid": hist_id},
        ).fetchone()
        assert row is not None, "Tenant A should see its own ticket history row"
