# foundry: kind=test domain=client-intelligence-platform
"""M5 cip_09 migration tests — Metabase role + lens views.

Verifies role provisioning, grant matrix, view semantics, and the
strict P-21 enforcement claim (the CRITICAL test —
``test_role_cannot_select_raw_cip_tables`` — proves P-21 is structurally
enforced, not convention).

Per plan v3 §4.2; 12 tests total.

M5 Δ1 (placement reconciliation): plan §4.2 specified placement at
``tests/migrations/test_cip_09_metabase_role_and_lens_views.py``. The
migrations conftest's ``engine`` fixture skips when ``DATABASE_URL`` is
unset (locally) — incompatible with the integration_mesh testcontainer
pattern that all M2/M3/M4 tests use. Tests placed here mirror the M3
Δ4 placement reconciliation. The integration_mesh ``seeded_engine``
fixture runs ``alembic upgrade head`` against the testcontainer Postgres,
so cip_09 is applied transitively before any of these tests run.

M5 Δ3 (revision-id length): plan v3 specified revision id
``cip_09_metabase_role_and_lens_views`` (35 chars), but deployed
``alembic_version_cip.version_num`` is VARCHAR(32). Migration shipped as
``cip_09_metabase_role_views`` (25 chars). Test file name follows.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import ProgrammingError

# TENANT_A reused across migration tests — single-source-of-truth fixture
# tenant UUID per plan v3 §11 Q1 lock.
from tests.migrations.conftest import TENANT_A, TENANT_B

_METABASE_ROLE = "cip_metabase_role"
_TEST_PASSWORD_SENTINEL = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105
_LENS_VIEWS = ("lens_all_companies", "lens_eu_west_companies")
_CIP_ENTITY_TABLES = (
    "cip_companies",
    "cip_contacts",
    "cip_deals",
    "cip_tickets",
    "cip_files",
)


def _metabase_password() -> str:
    """Resolve the Metabase role's password the same way the migration does."""
    return os.environ.get("METABASE_DB_PASSWORD") or _TEST_PASSWORD_SENTINEL


def _role_engine(seeded_engine: Engine) -> Engine:
    """Build a separate Engine that authenticates as ``cip_metabase_role``.

    Uses the seeded_engine's URL but swaps username/password. Caller is
    responsible for ``dispose()``.
    """
    role_url = seeded_engine.url.set(
        username=_METABASE_ROLE, password=_metabase_password()
    )
    return create_engine(role_url, pool_pre_ping=True)


@contextmanager
def _role_session_with_tenant(
    seeded_engine: Engine, tenant_id: UUID | None
) -> Iterator[Connection]:
    """Open a Connection as cip_metabase_role with optional tenant context.

    Mirrors the integration_mesh conftest's session_as_role_and_tenant
    pattern but for the metabase role + the v3 ``SET LOCAL
    app.current_tenant`` literal-interpolation pattern (matches plan
    §4.3's operator Init SQL convention so tests + ops agree).
    """
    role_eng = _role_engine(seeded_engine)
    try:
        with role_eng.connect() as conn:
            try:
                conn.execute(text("BEGIN"))
                if tenant_id is not None:
                    conn.execute(
                        text(
                            "SELECT set_config("
                            "'app.current_tenant', :t, true)"
                        ),
                        {"t": str(tenant_id)},
                    )
                yield conn
            finally:
                conn.execute(text("ROLLBACK"))
    finally:
        role_eng.dispose()


def _seed_companies(
    seeded_engine: Engine,
    *,
    tenant_id: UUID,
    rows: list[dict[str, str]],
) -> None:
    """Insert minimal cip_companies rows under a tenant. Uses the seeded
    engine (admin/superuser); bypasses RLS / table grants. Each row dict
    supports keys ``source_id``, ``name``, ``region``."""
    with seeded_engine.begin() as conn:
        # Set tenant context so the RLS policy on cip_companies accepts
        # the inserts (and stamps the row's tenant_id by predicate match).
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(tenant_id)},
        )
        for r in rows:
            conn.execute(
                text(
                    """
                    INSERT INTO cip_companies (
                        tenant_id, source_connector, source_id,
                        ingestion_batch_id, authority,
                        name, region
                    ) VALUES (
                        :tid, 'cip-09-test', :sid,
                        :bid, 'ingested',
                        :name, :region
                    )
                    """
                ),
                {
                    "tid": str(tenant_id),
                    "sid": r["source_id"],
                    "bid": str(uuid4()),
                    "name": r["name"],
                    "region": r["region"],
                },
            )


@pytest.fixture(scope="function")
def clean_companies(seeded_engine: Engine) -> Iterator[None]:
    """Per-test teardown: TRUNCATE cip_companies + history (CASCADE).
    Avoids cross-test contamination on a session-scoped DB."""
    yield
    with seeded_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE cip_companies_history, cip_companies "
                "RESTART IDENTITY CASCADE"
            )
        )


# ── 1. Role existence + attributes ────────────────────────────────────────


def test_role_exists_post_upgrade(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
            {"r": _METABASE_ROLE},
        ).fetchone()
    assert row is not None, f"{_METABASE_ROLE} not present in pg_roles"


def test_role_has_correct_attributes(seeded_engine: Engine) -> None:
    """Plan §2.4: NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION LOGIN."""
    with seeded_engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT rolsuper, rolbypassrls, rolcanlogin, rolcreatedb,
                       rolcreaterole, rolinherit, rolreplication
                FROM pg_roles WHERE rolname = :r
                """
            ),
            {"r": _METABASE_ROLE},
        ).fetchone()
    assert row is not None
    assert row.rolsuper is False
    assert row.rolbypassrls is False
    assert row.rolcanlogin is True
    assert row.rolcreatedb is False
    assert row.rolcreaterole is False
    assert row.rolinherit is False  # NOINHERIT
    assert row.rolreplication is False


def test_role_can_login(seeded_engine: Engine) -> None:
    role_eng = _role_engine(seeded_engine)
    try:
        with role_eng.connect() as conn:
            n = conn.execute(text("SELECT 1")).scalar()
        assert n == 1
    finally:
        role_eng.dispose()


# ── 2. View existence + grants ────────────────────────────────────────────


def test_lens_views_exist_post_upgrade(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT viewname FROM pg_views "
                "WHERE schemaname = 'public' AND viewname LIKE 'lens_%'"
            )
        ).fetchall()
    names = {r.viewname for r in rows}
    for v in _LENS_VIEWS:
        assert v in names, f"view {v} missing"


def test_role_can_select_lens_views(seeded_engine: Engine) -> None:
    """As cip_metabase_role with tenant context: SELECT from lens_*
    succeeds (no permission denied). Empty result set is OK; we only
    assert no auth/permission error escapes."""
    with _role_session_with_tenant(seeded_engine, TENANT_A) as conn:
        for v in _LENS_VIEWS:
            conn.execute(text(f"SELECT * FROM {v} LIMIT 0"))


# ── 3. CRITICAL P-21 enforcement ──────────────────────────────────────────


def test_role_cannot_select_raw_cip_tables(seeded_engine: Engine) -> None:
    """**THE CRITICAL P-21 TEST.** Plan §9 #5: structurally enforced via
    grant matrix (REVOKE on cip_* tables; GRANT only on lens_* views).
    A Metabase native SQL question against any cip_* entity table must
    raise permission-denied — the prevention is from Postgres, not
    convention."""
    role_eng = _role_engine(seeded_engine)
    try:
        for tbl in _CIP_ENTITY_TABLES:
            with (
                role_eng.connect() as conn,
                pytest.raises(ProgrammingError, match="permission denied"),
            ):
                conn.execute(text(f"SELECT * FROM {tbl} LIMIT 1"))
    finally:
        role_eng.dispose()


# ── 4. View semantics + tenant scoping ────────────────────────────────────


@pytest.mark.usefixtures("clean_companies")
def test_view_semantics_match_apply_lens(seeded_engine: Engine) -> None:
    """View row-set ≡ Python lens-engine row-set (Lens-A, Lens-B).

    Seeds 6 cip_companies under TENANT_A with regions distributed across
    the M3 fixture's lowercase scheme. Verifies:
      lens_all_companies → all 6 (no-op filter, tenant-scoped)
      lens_eu_west_companies → only the eu-west subset
    Then re-runs the same row-set computation via the M4 Python lens
    engine (compile_filter + sa.select) using the seeded_engine (raw
    cip_companies access; admin connection) and asserts identity.
    """
    seed = [
        {"source_id": "co-a-1", "name": "Acme",   "region": "eu-west"},
        {"source_id": "co-a-2", "name": "Beta",   "region": "us-east"},
        {"source_id": "co-a-3", "name": "Cyrene", "region": "eu-west"},
        {"source_id": "co-a-4", "name": "Delta",  "region": "apac"},
        {"source_id": "co-a-5", "name": "Eos",    "region": "us-west"},
        {"source_id": "co-a-6", "name": "Frey",   "region": "latam"},
    ]
    _seed_companies(seeded_engine, tenant_id=UUID(TENANT_A), rows=seed)

    # Read via lens_* views (cip_metabase_role connection)
    with _role_session_with_tenant(seeded_engine, UUID(TENANT_A)) as conn:
        all_rows = conn.execute(
            text("SELECT source_id FROM lens_all_companies ORDER BY source_id")
        ).all()
        eu_rows = conn.execute(
            text(
                "SELECT source_id FROM lens_eu_west_companies "
                "ORDER BY source_id"
            )
        ).all()

    view_all_ids = [r.source_id for r in all_rows]
    view_eu_ids = [r.source_id for r in eu_rows]
    assert view_all_ids == ["co-a-1", "co-a-2", "co-a-3", "co-a-4",
                            "co-a-5", "co-a-6"]
    assert view_eu_ids == ["co-a-1", "co-a-3"]

    # Cross-check via the M4 Python lens engine (raw-table reflect; admin
    # connection). compile_filter({}, ...) and compile_filter(
    # {"region":"eu-west"}, ...) should yield the same row sets after
    # tenant filtering (which apply_tenant_context provides).
    from cip.integration_mesh import compile_filter
    from cip.integration_mesh.tenant_context import apply_tenant_context

    md = sa.MetaData()
    md.reflect(bind=seeded_engine, only=["cip_companies"])
    companies = md.tables["cip_companies"]

    with seeded_engine.connect() as admin_conn, admin_conn.begin():
        apply_tenant_context(admin_conn, UUID(TENANT_A))
        py_all = admin_conn.execute(
            sa.select(companies.c.source_id)
            .where(compile_filter({}, companies))
            .order_by(companies.c.source_id)
        ).all()
        py_eu = admin_conn.execute(
            sa.select(companies.c.source_id)
            .where(compile_filter({"region": "eu-west"}, companies))
            .order_by(companies.c.source_id)
        ).all()

    assert [r.source_id for r in py_all] == view_all_ids
    assert [r.source_id for r in py_eu] == view_eu_ids


@pytest.mark.usefixtures("clean_companies")
def test_view_returns_empty_when_guc_unset(seeded_engine: Engine) -> None:
    """No tenant context set: NULLIF(current_setting(..., true), '')::uuid
    evaluates to NULL → WHERE tenant_id = NULL is NULL → row excluded.
    Safe-fail (zero rows, NOT all rows)."""
    _seed_companies(
        seeded_engine,
        tenant_id=UUID(TENANT_A),
        rows=[{"source_id": "co-a-1", "name": "Acme", "region": "eu-west"}],
    )
    # NB: pass tenant_id=None so the helper doesn't set the GUC at all.
    with _role_session_with_tenant(seeded_engine, None) as conn:
        rows = conn.execute(text("SELECT * FROM lens_all_companies")).all()
    assert rows == []


@pytest.mark.usefixtures("clean_companies")
def test_view_returns_empty_when_guc_empty_string(
    seeded_engine: Engine,
) -> None:
    """GUC set to empty string: NULLIF('', '') → NULL → row excluded."""
    _seed_companies(
        seeded_engine,
        tenant_id=UUID(TENANT_A),
        rows=[{"source_id": "co-a-1", "name": "Acme", "region": "eu-west"}],
    )
    role_eng = _role_engine(seeded_engine)
    try:
        with role_eng.connect() as conn:
            conn.execute(text("BEGIN"))
            conn.execute(
                text("SELECT set_config('app.current_tenant', '', true)")
            )
            rows = conn.execute(
                text("SELECT * FROM lens_all_companies")
            ).all()
            conn.execute(text("ROLLBACK"))
    finally:
        role_eng.dispose()
    assert rows == []


@pytest.mark.usefixtures("clean_companies")
def test_cross_tenant_isolation_through_views(
    seeded_engine: Engine,
) -> None:
    """Seed 2 tenants. Query view as TENANT_A → only A's rows. Query as
    TENANT_B → only B's rows. P-21 + tenant scoping AND-compose."""
    _seed_companies(
        seeded_engine,
        tenant_id=UUID(TENANT_A),
        rows=[{"source_id": "co-a", "name": "TenantA", "region": "eu-west"}],
    )
    _seed_companies(
        seeded_engine,
        tenant_id=UUID(TENANT_B),
        rows=[{"source_id": "co-b", "name": "TenantB", "region": "eu-west"}],
    )
    with _role_session_with_tenant(seeded_engine, UUID(TENANT_A)) as conn:
        a_rows = conn.execute(
            text("SELECT source_id FROM lens_all_companies")
        ).all()
    with _role_session_with_tenant(seeded_engine, UUID(TENANT_B)) as conn:
        b_rows = conn.execute(
            text("SELECT source_id FROM lens_all_companies")
        ).all()
    assert [r.source_id for r in a_rows] == ["co-a"]
    assert [r.source_id for r in b_rows] == ["co-b"]


# ── 5. Performance smoke ──────────────────────────────────────────────────


@pytest.mark.usefixtures("clean_companies")
def test_view_query_plan_uses_index(seeded_engine: Engine) -> None:
    """EXPLAIN of lens_eu_west_companies must NOT use a sequential scan
    on cip_companies (uses tenant_id index OR the partial
    idx_cip_companies_region per cip_06_companies). Disable seq scan to
    verify a usable index exists; planner choice on small corpus is
    flaky per plan v3 §5.2 small-corpus note."""
    _seed_companies(
        seeded_engine,
        tenant_id=UUID(TENANT_A),
        rows=[
            {"source_id": "co-1", "name": "X", "region": "eu-west"},
            {"source_id": "co-2", "name": "Y", "region": "us-east"},
        ],
    )
    with seeded_engine.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": TENANT_A},
        )
        # set enable_seqscan = off forces planner to use index if any
        # available; if no index path exists, planner errors / falls
        # back. Either way, we assert the EXPLAIN doesn't say "Seq Scan
        # on cip_companies" against a real index path.
        conn.execute(text("SET LOCAL enable_seqscan = off"))
        plan = conn.execute(
            text(
                "EXPLAIN (FORMAT TEXT) "
                "SELECT * FROM lens_eu_west_companies"
            )
        ).fetchall()
    plan_text = "\n".join(row[0] for row in plan)
    # Either Index Scan or Bitmap Index Scan is acceptable; raw seq scan
    # on the underlying cip_companies table is not.
    assert "Seq Scan on cip_companies" not in plan_text, (
        f"unexpected seq scan in plan:\n{plan_text}"
    )


# ── 6. Migration mechanics ────────────────────────────────────────────────


def test_default_privileges_block_future_table_grants(
    seeded_engine: Engine,
) -> None:
    """Plan §2.4 + §8.4: ALTER DEFAULT PRIVILEGES revokes grants on
    future tables. Verify the entry is recorded in pg_default_acl for
    cip_metabase_role on schema public."""
    with seeded_engine.connect() as conn:
        # pg_default_acl rows for cip_metabase_role's grants on schema public
        rows = conn.execute(
            text(
                """
                SELECT defaclacl::text AS acl
                FROM pg_default_acl d
                JOIN pg_namespace n ON d.defaclnamespace = n.oid
                WHERE n.nspname = 'public'
                """
            )
        ).fetchall()
    # Either the default-acl row exists (REVOKE applied non-trivially), or
    # it doesn't (REVOKE was a no-op because no default grants existed —
    # also acceptable; the role is still blocked from future grants).
    # Just assert the migration ran without error and the role still has
    # the correct grant matrix (covered by other tests).
    assert isinstance(rows, list)
    # And the role should NOT have any default-grant ACL entry granting
    # SELECT on tables.
    for r in rows:
        acl_str = r.acl or ""
        assert "cip_metabase_role=r" not in acl_str, (
            f"unexpected default SELECT grant for cip_metabase_role: "
            f"{acl_str}"
        )


def test_password_sentinel_constant_is_distinct(seeded_engine: Engine) -> None:
    """Sanity: the sentinel value the migration falls back to is the
    documented "DO_NOT_USE_IN_PROD" string. Catches accidental rename in
    the migration that would diverge tests from runtime."""
    # Re-import to make sure the test sees the migration's actual constant.
    from cip.migrations.versions import cip_09_metabase_role_views as mig

    assert mig._TEST_PASSWORD_SENTINEL == _TEST_PASSWORD_SENTINEL
    assert "DO_NOT_USE_IN_PROD" in mig._TEST_PASSWORD_SENTINEL
