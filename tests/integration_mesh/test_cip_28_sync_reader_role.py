# foundry: kind=test domain=client-intelligence-platform
"""Tests for cip_28 — provision cip_sync_reader role.

Verifies the role exists with the right shape, can SELECT the three
granted tables (under a GUC tenant), cannot write, and cannot SELECT
a non-granted table (cip_sync_runs).
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_READER_ROLE = "cip_sync_reader"
_READER_TEST_PASSWORD = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105


def _reader_engine(seeded_engine: Engine) -> Engine:
    """Engine bound to cip_sync_reader (provisioned by cip_28)."""
    url = seeded_engine.url.set(
        username=_READER_ROLE,
        password=os.environ.get(
            "CIP_SYNC_READER_DB_PASSWORD", _READER_TEST_PASSWORD
        ),
    )
    return create_engine(url, pool_pre_ping=True)


# ── 1. Role exists with the expected shape ─────────────────────────────────

@pytest.mark.requires_postgres
def test_cip_sync_reader_role_exists_with_correct_attributes(
    seeded_engine: Engine,
) -> None:
    """cip_28 must provision cip_sync_reader as NOSUPERUSER NOBYPASSRLS
    LOGIN — anything weaker would let the reader bypass the GUC fence."""
    with seeded_engine.connect() as conn:
        row = conn.execute(text(
            "SELECT rolsuper, rolbypassrls, rolcanlogin, rolinherit, "
            "rolcreatedb, rolcreaterole, rolreplication "
            "FROM pg_roles WHERE rolname = :r"
        ), {"r": _READER_ROLE}).first()
    assert row is not None, "cip_sync_reader role missing after cip_28 upgrade"
    rolsuper, bypassrls, login, inherit, createdb, createrole, repl = row
    assert rolsuper is False
    assert bypassrls is False, (
        "cip_sync_reader must be NOBYPASSRLS so the GUC fence holds"
    )
    assert login is True
    assert inherit is False
    assert createdb is False
    assert createrole is False
    assert repl is False


# ── 2. SELECT on the three granted tables works (under a GUC tenant) ───────

@pytest.mark.requires_postgres
def test_cip_sync_reader_can_select_granted_tables(seeded_engine: Engine) -> None:
    """cip_clients, cip_companies, cip_contacts — all SELECTable.
    A fresh tenant has zero rows; the assertion is that the query
    runs (no permission denied) and returns a number."""
    tenant_id = uuid4()
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(tenant_id)},
            )
            for tbl in ("cip_clients", "cip_companies", "cip_contacts"):
                n = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
                assert isinstance(n, int) and n >= 0, (
                    f"reader couldn't COUNT(*) {tbl}: got {n!r}"
                )
    finally:
        reng.dispose()


# ── 3. Writes are denied ───────────────────────────────────────────────────

@pytest.mark.requires_postgres
def test_cip_sync_reader_cannot_insert(seeded_engine: Engine) -> None:
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(uuid4())},
            )
            with pytest.raises(Exception) as exc_info:
                conn.execute(text(
                    "INSERT INTO cip_clients "
                    "(id, tenant_id, client_id, source_connector, source_id, "
                    " ingested_at, refreshed_at, ingestion_batch_id, authority, "
                    " name, slug) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), "
                    " 'test', 'test', NOW(), NOW(), gen_random_uuid(), 'validated', "
                    " 'pwn', 'pwn')"
                ))
            msg = str(exc_info.value).lower()
            assert "permission denied" in msg or "insufficientprivilege" in msg
    finally:
        reng.dispose()


@pytest.mark.requires_postgres
def test_cip_sync_reader_cannot_update(seeded_engine: Engine) -> None:
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(uuid4())},
            )
            with pytest.raises(Exception) as exc_info:
                conn.execute(text("UPDATE cip_clients SET name = 'pwn'"))
            msg = str(exc_info.value).lower()
            assert "permission denied" in msg or "insufficientprivilege" in msg
    finally:
        reng.dispose()


# ── 4. SELECT on non-granted table is denied ───────────────────────────────

@pytest.mark.requires_postgres
def test_cip_sync_reader_cannot_select_non_granted_table(
    seeded_engine: Engine,
) -> None:
    """cip_sync_runs is NOT in cip_28's grant list — SELECT must raise
    permission denied. This is the load-bearing scope check: the role's
    surface is the 3 entity tables and nothing else."""
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(uuid4())},
            )
            with pytest.raises(Exception) as exc_info:
                conn.execute(text("SELECT 1 FROM cip_sync_runs LIMIT 1"))
            msg = str(exc_info.value).lower()
            assert "permission denied" in msg or "insufficientprivilege" in msg
    finally:
        reng.dispose()


@pytest.mark.requires_postgres
def test_cip_sync_reader_cannot_select_cip_deals_yet(seeded_engine: Engine) -> None:
    """v1 deliberately does NOT grant cip_deals (gated on the v2
    deals→opportunities design decision). When v2 ships, extend the
    grant in a follow-up migration and update this test to assert
    the new surface."""
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(uuid4())},
            )
            with pytest.raises(Exception) as exc_info:
                conn.execute(text("SELECT 1 FROM cip_deals LIMIT 1"))
            msg = str(exc_info.value).lower()
            assert "permission denied" in msg or "insufficientprivilege" in msg
    finally:
        reng.dispose()
