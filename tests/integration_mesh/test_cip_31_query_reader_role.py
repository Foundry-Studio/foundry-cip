# foundry: kind=test domain=client-intelligence-platform
"""Tests for cip_31 — provision cip_query_reader role.

Verifies the role exists NOBYPASSRLS+LOGIN, can SELECT every relation
in the v1 grant surface (entity tables + history twins + discovery
tables + lens_* views), cannot write, and cannot SELECT a non-granted
table (cip_sync_runs). Plus the load-bearing RLS check: under
GUC=tenant_A, SELECT on cip_clients (no WHERE) returns ONLY tenant_A
rows — proves the reader-role + GUC fence works as Path 1's safety
guarantee.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_READER_ROLE = "cip_query_reader"
_READER_TEST_PASSWORD = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105


def _reader_engine(seeded_engine: Engine) -> Engine:
    url = seeded_engine.url.set(
        username=_READER_ROLE,
        password=os.environ.get("CIP_QUERY_READER_DB_PASSWORD", _READER_TEST_PASSWORD),
    )
    return create_engine(url, pool_pre_ping=True)


# ── 1. Role exists with the expected security attributes ─────────────────


@pytest.mark.requires_postgres
def test_role_exists_and_is_nobypassrls(seeded_engine: Engine) -> None:
    """The single most important property — bypassrls=False — is what
    makes Path 1's SQL surface safe to run agent queries through."""
    with seeded_engine.connect() as conn:
        row = conn.execute(text(
            "SELECT rolsuper, rolbypassrls, rolcanlogin, rolinherit, "
            "rolcreatedb, rolcreaterole, rolreplication "
            "FROM pg_roles WHERE rolname = :r"
        ), {"r": _READER_ROLE}).first()
    assert row is not None, "cip_query_reader role missing after cip_31"
    rolsuper, bypassrls, login, inherit, createdb, createrole, repl = row
    assert rolsuper is False
    assert bypassrls is False, (
        "cip_query_reader MUST be NOBYPASSRLS — this is the entire safety "
        "fence for /api/v1/cip/query"
    )
    assert login is True
    assert inherit is False
    assert createdb is False
    assert createrole is False
    assert repl is False


# ── 2. Grant surface — every relation the dispatch lists is SELECTable ────


@pytest.mark.requires_postgres
def test_reader_can_select_entity_tables(seeded_engine: Engine) -> None:
    """All 13 entity tables under GUC=<random tenant> read without error
    (zero rows OK; this only proves access)."""
    tenant_id = uuid.uuid4()
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(tenant_id)},
            )
            for tbl in (
                "cip_clients", "cip_companies", "cip_contacts",
                "cip_deals", "cip_tickets", "cip_ticket_comments",
                "cip_engagements", "cip_files", "cip_owners",
                "cip_pipeline_stages", "cip_marketing_emails",
                "cip_contact_lists", "cip_contact_list_memberships",
            ):
                n = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
                assert isinstance(n, int) and n >= 0
    finally:
        reng.dispose()


@pytest.mark.requires_postgres
def test_reader_can_select_history_twins(seeded_engine: Engine) -> None:
    tenant_id = uuid.uuid4()
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(tenant_id)},
            )
            for tbl in (
                "cip_clients_history", "cip_companies_history",
                "cip_contacts_history", "cip_deals_history",
                "cip_tickets_history", "cip_ticket_comments_history",
                "cip_engagements_history", "cip_files_history",
                "cip_views_history",
            ):
                n = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
                assert isinstance(n, int) and n >= 0
    finally:
        reng.dispose()


@pytest.mark.requires_postgres
def test_reader_can_select_discovery_tables(seeded_engine: Engine) -> None:
    tenant_id = uuid.uuid4()
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(tenant_id)},
            )
            for tbl in ("cip_views", "cip_connector_property_registry",
                        "cip_knowledge_chunks"):
                n = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
                assert isinstance(n, int) and n >= 0
    finally:
        reng.dispose()


@pytest.mark.requires_postgres
def test_reader_can_select_lens_views(seeded_engine: Engine) -> None:
    """The lens_* surface is granted programmatically — every lens
    that exists at migration time is selectable. Test pinned by
    sampling well-known lenses from cip_09/10/18/24/26/29."""
    tenant_id = uuid.uuid4()
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(tenant_id)},
            )
            for view in (
                "lens_all_companies",          # cip_09
                "lens_companies_history",      # cip_10
                "lens_deals_history",          # cip_29
                "lens_china_companies",        # cip_24
                "lens_ps_china_brands_all",    # cip_26
            ):
                n = conn.execute(text(f"SELECT COUNT(*) FROM {view}")).scalar()
                assert isinstance(n, int) and n >= 0
    finally:
        reng.dispose()


# ── 3. Writes are denied ─────────────────────────────────────────────────


@pytest.mark.requires_postgres
def test_reader_cannot_insert(seeded_engine: Engine) -> None:
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(uuid.uuid4())},
            )
            with pytest.raises(Exception) as exc_info:
                conn.execute(text(
                    "INSERT INTO cip_clients "
                    "(id, tenant_id, client_id, source_connector, source_id, "
                    " ingested_at, refreshed_at, ingestion_batch_id, authority, "
                    " name, slug) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), "
                    "'test', 'test', NOW(), NOW(), gen_random_uuid(), 'validated', "
                    "'pwn', 'pwn')"
                ))
            msg = str(exc_info.value).lower()
            assert "permission denied" in msg or "insufficientprivilege" in msg
    finally:
        reng.dispose()


@pytest.mark.requires_postgres
def test_reader_cannot_update(seeded_engine: Engine) -> None:
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(uuid.uuid4())},
            )
            with pytest.raises(Exception) as exc_info:
                conn.execute(text("UPDATE cip_clients SET name = 'pwn'"))
            msg = str(exc_info.value).lower()
            assert "permission denied" in msg or "insufficientprivilege" in msg
    finally:
        reng.dispose()


@pytest.mark.requires_postgres
def test_reader_cannot_delete(seeded_engine: Engine) -> None:
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(uuid.uuid4())},
            )
            with pytest.raises(Exception) as exc_info:
                conn.execute(text("DELETE FROM cip_clients"))
            msg = str(exc_info.value).lower()
            assert "permission denied" in msg or "insufficientprivilege" in msg
    finally:
        reng.dispose()


# ── 4. Non-granted table is denied (cip_sync_runs not in v1 surface) ─────


@pytest.mark.requires_postgres
def test_reader_cannot_select_cip_sync_runs(seeded_engine: Engine) -> None:
    """cip_sync_runs is operational metadata, deliberately excluded from
    the agent read surface. Locks the v1 grant set."""
    reng = _reader_engine(seeded_engine)
    try:
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(uuid.uuid4())},
            )
            with pytest.raises(Exception) as exc_info:
                conn.execute(text("SELECT 1 FROM cip_sync_runs LIMIT 1"))
            assert isinstance(
                exc_info.value.orig,  # type: ignore[attr-defined]
                psycopg.errors.InsufficientPrivilege,
            )
    finally:
        reng.dispose()


# ── 5. THE LOAD-BEARING TEST: cross-tenant isolation via RLS ─────────────


@pytest.mark.requires_postgres
def test_cross_tenant_isolation_via_guc(seeded_engine: Engine) -> None:
    """The whole point of NOBYPASSRLS: an agent SQL `SELECT * FROM cip_clients`
    (no WHERE) returns ONLY rows for the session GUC's tenant. Seed two
    tenants' rows under the postgres superuser (bypasses RLS), then read
    each under the reader role with GUC=A and GUC=B — must see only the
    matching tenant's rows.
    """
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    # Seed one row per tenant via the superuser engine (bypasses RLS for
    # this test-only setup).
    with seeded_engine.begin() as su:
        for tid in (tenant_a, tenant_b):
            su.execute(text(
                "INSERT INTO cip_clients "
                "(id, tenant_id, client_id, source_connector, source_id, "
                " ingested_at, refreshed_at, ingestion_batch_id, authority, "
                " name, slug) "
                "VALUES (gen_random_uuid(), :t, gen_random_uuid(), "
                "'test', :sid, NOW(), NOW(), gen_random_uuid(), 'validated', "
                ":n, :n)"
            ), {"t": str(tid), "sid": f"isolation-{tid}", "n": f"client-{tid}"})

    reng = _reader_engine(seeded_engine)
    try:
        # GUC = tenant A — sees only tenant A's row
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(tenant_a)},
            )
            rows = conn.execute(text(
                "SELECT tenant_id FROM cip_clients "
                "WHERE source_connector = 'test' AND source_id LIKE 'isolation-%'"
            )).fetchall()
            tenants_seen = {r[0] for r in rows}
            assert tenants_seen == {tenant_a}, (
                f"RLS fence broke — reader under GUC={tenant_a} saw: {tenants_seen}"
            )

        # GUC = tenant B — sees only tenant B's row
        with reng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(tenant_b)},
            )
            rows = conn.execute(text(
                "SELECT tenant_id FROM cip_clients "
                "WHERE source_connector = 'test' AND source_id LIKE 'isolation-%'"
            )).fetchall()
            tenants_seen = {r[0] for r in rows}
            assert tenants_seen == {tenant_b}

        # No GUC — RLS fails closed (NULL tenant_id GUC → zero rows)
        with reng.connect() as conn:
            n = conn.execute(text(
                "SELECT COUNT(*) FROM cip_clients "
                "WHERE source_connector = 'test' AND source_id LIKE 'isolation-%'"
            )).scalar()
            assert n == 0, f"expected 0 rows without GUC, got {n}"
    finally:
        reng.dispose()
        # Cleanup: remove the seeded rows so cross-test pollution doesn't
        # accumulate in the (session-scoped) testcontainer.
        with seeded_engine.begin() as su:
            su.execute(text(
                "DELETE FROM cip_clients WHERE source_connector = 'test' "
                "AND source_id LIKE 'isolation-%'"
            ))
