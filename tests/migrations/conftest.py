# foundry: kind=test domain=client-intelligence-platform
"""Shared fixtures for CIP M1 RLS smoke tests.

These tests require a live PostgreSQL database with the cip_01 through
cip_08 migrations applied. They do NOT use mocks — RLS is a database-layer
guarantee that cannot be validated without a real Postgres connection.

Run prerequisite:
    alembic upgrade head          # applies all migrations including cip_01-cip_08
    pytest tests/migrations/ -v   # runs all RLS smoke tests

Environment:
    DATABASE_URL must be set (same as used by alembic env.py).

Two fixture tenants used across all tests:
    TENANT_A = "a0000000-0000-0000-0000-000000000001"
    TENANT_B = "b0000000-0000-0000-0000-000000000002"

RLS contract (SPEC §7):
    After SET LOCAL app.current_tenant = TENANT_A, a SELECT on any cip_*
    table must return ZERO rows belonging to TENANT_B.
    Without any SET LOCAL, the current_setting() call raises or returns
    empty string, causing the policy USING expression to evaluate to NULL
    which PostgreSQL treats as a block (no rows).

Implementation note — BYPASSRLS on the superuser role:
    The Railway PostgreSQL `postgres` user has rolbypassrls=True, which means
    even FORCE ROW LEVEL SECURITY does not apply to it. To test RLS we use
    `SET LOCAL ROLE cip_rls_test_role` — a non-superuser role created in the
    DB that has SELECT/INSERT on all tables but no BYPASSRLS privilege.
    Data setup sessions run as `postgres` (no role switch) so we can insert
    rows for both tenants without RLS filtering. Query sessions use the
    restricted role so RLS policy enforcement is active.
"""

import os
import uuid
from collections.abc import Generator
from contextlib import contextmanager, suppress

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from tests._helpers.rls import (
    _RLS_TEST_ROLE,
    provision_cip_rls_test_role,
)

# ── Constants ────────────────────────────────────────────────────────────────

TENANT_A = "a0000000-0000-0000-0000-000000000001"
TENANT_B = "b0000000-0000-0000-0000-000000000002"

FIXTURE_BATCH_A = str(uuid.uuid4())
FIXTURE_BATCH_B = str(uuid.uuid4())


# ── Engine setup ─────────────────────────────────────────────────────────────


def _get_engine():
    """Build a SQLAlchemy engine from DATABASE_URL (same source as alembic)."""
    try:
        from src.db.session import get_sqlalchemy_url
        url = get_sqlalchemy_url()
    except Exception:
        url = os.environ.get("DATABASE_URL")

    if not url:
        pytest.skip("DATABASE_URL not set — skipping RLS smoke tests (no live DB)")

    # Normalize URL to psycopg3 dialect (sync). foundry-cip ships only
    # psycopg[binary]>=3 (no psycopg2). psycopg3 sync supports SET LOCAL with
    # explicit BEGIN/COMMIT exactly like psycopg2 did, so transaction shape is
    # unchanged. Forward-conversion: bare postgresql:// + +asyncpg → +psycopg.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return create_engine(url, pool_pre_ping=True, isolation_level="AUTOCOMMIT")


# ``_ensure_rls_test_role`` was extracted to ``tests/_helpers/rls.py`` as
# ``provision_cip_rls_test_role`` (post-M4 hygiene pass). Callers below
# call the shared function. Note: this conftest's session helpers
# (``session_as_tenant`` / ``session_no_tenant``) intentionally stay
# inline — they yield ``Session`` objects (not ``Connection``) and use
# ``SET LOCAL app.current_tenant = '{literal}'`` rather than the post-v5.4
# ``set_config()`` pattern. The tests/migrations/test_rls_*.py callers
# depend on the Session-typed API; converging is out of scope for the
# RLS-helper extraction. See ``tests/_helpers/rls.py`` module docstring
# for the full rationale.


def _purge_cip_test_data(engine) -> None:
    """Delete all rows inserted by our test fixtures.

    All fixture inserts use source_connector='test' or connector_id='fixture_v1'
    or changed_by='test', providing a safe delete key that won't touch real data.
    cip_clients uses slug patterns 'rls*' or 'client-*' that are fixture-only.
    cip_views uses view_name patterns with ' Test' or 'Lens-'.
    Registry uses property_name patterns starting with 'rls_'.
    """
    session_factory = sessionmaker(bind=engine)
    s = session_factory()
    try:
        s.execute(text("BEGIN"))
        s.execute(text("DELETE FROM cip_clients_history WHERE changed_by = 'test'"))
        s.execute(text("DELETE FROM cip_clients WHERE source_connector = 'test'"))
        s.execute(text("DELETE FROM cip_views_history WHERE changed_by = 'test'"))
        s.execute(text("DELETE FROM cip_views WHERE source_connector = 'test'"))
        s.execute(text("DELETE FROM cip_sync_runs WHERE connector_id = 'fixture_v1'"))
        s.execute(text("DELETE FROM cip_files_history WHERE changed_by = 'test'"))
        s.execute(text("DELETE FROM cip_files WHERE source_connector = 'test'"))
        s.execute(text("DELETE FROM cip_contacts_history WHERE changed_by = 'test'"))
        s.execute(text("DELETE FROM cip_contacts WHERE source_connector = 'test'"))
        s.execute(text("DELETE FROM cip_companies_history WHERE changed_by = 'test'"))
        s.execute(text("DELETE FROM cip_companies WHERE source_connector = 'test'"))
        s.execute(text("DELETE FROM cip_deals_history WHERE changed_by = 'test'"))
        s.execute(text("DELETE FROM cip_deals WHERE source_connector = 'test'"))
        s.execute(text("DELETE FROM cip_tickets_history WHERE changed_by = 'test'"))
        s.execute(text("DELETE FROM cip_tickets WHERE source_connector = 'test'"))
        s.execute(text("DELETE FROM cip_connector_property_registry WHERE connector = 'fixture'"))
        s.execute(text("COMMIT"))
    except Exception:
        with suppress(Exception):
            s.execute(text("ROLLBACK"))
        raise
    finally:
        s.close()


@pytest.fixture(scope="module")
def engine():
    """Module-scoped engine — one connection pool per test module.

    Purges CIP test-fixture data before and after the module to ensure
    tests run clean even after a previous interrupted run left committed rows.
    """
    eng = _get_engine()
    provision_cip_rls_test_role(eng)
    _purge_cip_test_data(eng)  # clean up any leftover data from previous run
    yield eng
    _purge_cip_test_data(eng)  # clean up after this run
    eng.dispose()


# ── Session helpers ───────────────────────────────────────────────────────────


@contextmanager
def session_as_tenant(engine, tenant_id: str) -> Generator[Session, None, None]:
    """Open a session as the restricted role with SET LOCAL tenant context.

    Uses SET LOCAL ROLE cip_rls_test_role so PostgreSQL enforces RLS policies
    (the postgres superuser has BYPASSRLS and would not be filtered otherwise).
    SET LOCAL app.current_tenant scopes all reads to the given tenant.
    Both role and tenant are transaction-local — auto-reset on ROLLBACK.
    """
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        session.execute(text("BEGIN"))
        # SET LOCAL does not accept parameters — embed values directly.
        # _RLS_TEST_ROLE is a known constant (not user input); tenant_id is
        # a UUID validated by the uuid module before being passed here.
        session.execute(text(f"SET LOCAL ROLE {_RLS_TEST_ROLE}"))
        session.execute(text(f"SET LOCAL app.current_tenant = '{tenant_id}'"))
        yield session
        session.execute(text("ROLLBACK"))
    except Exception:
        with suppress(Exception):
            session.execute(text("ROLLBACK"))
        raise
    finally:
        session.close()


@contextmanager
def session_no_tenant(engine, *, commit: bool = False) -> Generator[Session, None, None]:
    """Open a session WITHOUT setting app.current_tenant.

    Two use-cases:
    1. commit=True  (setup): runs as postgres superuser so inserts bypass RLS.
       Rows are committed and visible to subsequent query sessions.
    2. commit=False (verify): switches to cip_rls_test_role so RLS is active,
       then confirms that without a tenant context no rows are visible.

    Per SPEC §7: without SET LOCAL, current_setting('app.current_tenant')
    raises UndefinedObject — PostgreSQL's RLS evaluates the USING expression
    to NULL and blocks all rows (for non-BYPASSRLS roles).
    """
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        session.execute(text("BEGIN"))
        if not commit:
            # Switch to restricted role so RLS is enforced
            session.execute(text(f"SET LOCAL ROLE {_RLS_TEST_ROLE}"))
        yield session
        if commit:
            session.execute(text("COMMIT"))
        else:
            session.execute(text("ROLLBACK"))
    except Exception:
        with suppress(Exception):
            session.execute(text("ROLLBACK"))
        raise
    finally:
        session.close()
