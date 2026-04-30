# foundry: kind=test domain=client-intelligence-platform
"""RLS smoke test — cip_files and cip_files_history.

Validates SPEC §7: cross-tenant queries return zero rows for both the
main cip_files table and its SCD-2 history table.
"""

import uuid

from sqlalchemy import text

from tests.migrations.conftest import (
    FIXTURE_BATCH_A,
    FIXTURE_BATCH_B,
    TENANT_A,
    TENANT_B,
    session_as_tenant,
    session_no_tenant,
)


def _insert_file(session, tenant_id: str, filename: str) -> str:
    row_id = str(uuid.uuid4())
    bid = FIXTURE_BATCH_A if tenant_id == TENANT_A else FIXTURE_BATCH_B
    session.execute(
        text(
            "INSERT INTO cip_files "
            "(id, tenant_id, source_connector, ingestion_batch_id, "
            " authority, r2_path, filename) "
            "VALUES (:id, :tid, 'test', :bid, 'validated', :r2, :fn)"
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "bid": bid,
            "r2": f"tenant_{tenant_id}/cip/files/{row_id}.txt",
            "fn": filename,
        },
    )
    return row_id


def _insert_file_history(session, tenant_id: str, record_id: str) -> str:
    hist_id = str(uuid.uuid4())
    bid = FIXTURE_BATCH_A if tenant_id == TENANT_A else FIXTURE_BATCH_B
    session.execute(
        text(
            "INSERT INTO cip_files_history "
            "(history_id, record_id, tenant_id, valid_from, changed_by, "
            " source_connector, ingested_at, refreshed_at, ingestion_batch_id, "
            " authority, r2_path, filename) "
            "VALUES (:hid, :rid, :tid, now(), 'test', 'test', now(), now(), "
            "        :bid, 'validated', '/r2/hist', 'hist.txt')"
        ),
        {"hid": hist_id, "rid": record_id, "tid": tenant_id, "bid": bid},
    )
    return hist_id


def test_rls_cip_files_cross_tenant_returns_zero(engine):
    """Tenant B context sees zero cip_files rows from Tenant A."""
    with session_no_tenant(engine, commit=True) as setup:
        _insert_file(setup, TENANT_A, "tenant-a-doc.pdf")

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text("SELECT count(*) FROM cip_files WHERE tenant_id = CAST(:ta AS uuid)"),
            {"ta": TENANT_A},
        ).scalar()
        assert rows == 0, f"Cross-tenant must return 0 rows, got {rows}"


def test_rls_cip_files_tenant_a_sees_own_rows(engine):
    """Tenant A context sees its own cip_files rows."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_file(setup, TENANT_A, "own-a-doc.pdf")

    with session_as_tenant(engine, TENANT_A) as s:
        row = s.execute(
            text("SELECT id FROM cip_files WHERE id = CAST(:id AS uuid)"),
            {"id": id_a},
        ).fetchone()
        assert row is not None, "Tenant A should see its own file row"


def test_rls_cip_files_history_cross_tenant_returns_zero(engine):
    """cip_files_history: Tenant B context returns zero rows from Tenant A."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_file(setup, TENANT_A, "hist-a-doc.pdf")
        _insert_file_history(setup, TENANT_A, id_a)

    with session_as_tenant(engine, TENANT_B) as s:
        rows = s.execute(
            text(
                "SELECT count(*) FROM cip_files_history WHERE tenant_id = CAST(:ta AS uuid)"
            ),
            {"ta": TENANT_A},
        ).scalar()
        assert rows == 0, f"Cross-tenant history must return 0 rows, got {rows}"


def test_rls_cip_files_history_tenant_a_sees_own_history(engine):
    """Tenant A context sees its own cip_files_history rows."""
    with session_no_tenant(engine, commit=True) as setup:
        id_a = _insert_file(setup, TENANT_A, "hist-own-doc.pdf")
        hist_id = _insert_file_history(setup, TENANT_A, id_a)

    with session_as_tenant(engine, TENANT_A) as s:
        row = s.execute(
            text("SELECT history_id FROM cip_files_history WHERE history_id = CAST(:hid AS uuid)"),
            {"hid": hist_id},
        ).fetchone()
        assert row is not None, "Tenant A should see its own file history row"
