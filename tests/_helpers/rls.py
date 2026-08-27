# foundry: kind=test domain=client-intelligence-platform
"""Shared RLS test-harness helpers for foundry-cip.

Provisions the ``cip_rls_test_role`` role (NOSUPERUSER NOBYPASSRLS) used to
honestly exercise RLS policies in testcontainer Postgres (where the default
user is a superuser and would silently BYPASSRLS).

Consumers (call ``provision_cip_rls_test_role(engine)`` once per
session-scoped engine fixture):

- ``tests/fixtures/connector_conformance/conftest.py`` (M2 conformance —
  uses ``session_as_role_and_tenant`` from this module).
- ``tests/migrations/conftest.py`` (M2 migrations harness — uses ONLY the
  role provisioning; keeps its own ``session_as_tenant`` /
  ``session_no_tenant`` Session-typed helpers — see "Session-helper API
  divergence" below).
- ``tests/integration_mesh/conftest.py`` (M4 integration_mesh tests — uses
  ``session_as_role_and_tenant`` from this module).

Session-helper API divergence (intentionally NOT extracted):
    The conformance and integration_mesh harnesses use
    ``session_as_role_and_tenant(engine, tenant_id) -> Iterator[Connection]``
    with the ``set_config('app.current_tenant', :t, true)`` bind-parameter
    pattern (per M2 v5.4 Δ14: SET LOCAL doesn't accept bind parameters; the
    set_config function does, eliminating string-interpolation of UUIDs).
    The migrations harness predates the M2 v5.4 reconciliation and yields
    ``Session`` objects (not Connection) using the older
    ``SET LOCAL app.current_tenant = '{literal}'`` interpolation, plus a
    separate ``session_no_tenant`` companion. Its callers in
    ``tests/migrations/test_rls_*.py`` depend on the Session API, so
    converging the migrations harness to this module's Connection-typed
    helper is a non-trivial refactor — out of scope for this extraction.
    Atlas can decide whether a future hygiene pass should converge them.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

# Restricted non-superuser role used for RLS verification queries.
# Postgres superusers have BYPASSRLS so even FORCE ROW LEVEL SECURITY is
# inert against them; this role is NOSUPERUSER + NOBYPASSRLS so RLS
# policies actually enforce.
_RLS_TEST_ROLE = "cip_rls_test_role"


def provision_cip_rls_test_role(engine: Engine) -> None:
    """Idempotently create ``cip_rls_test_role`` + grant table/sequence access.

    NOSUPERUSER NOBYPASSRLS so PostgreSQL applies RLS policies. Safe to call
    repeatedly across sessions; the CREATE ROLE is gated on a ``pg_roles``
    existence check, and the GRANTs are themselves idempotent.

    Uses ``engine.begin()`` for a single-transaction round-trip. AUTOCOMMIT
    engines (e.g., ``tests/migrations/conftest.py``'s engine factory) treat
    ``begin()``'s implicit BEGIN/COMMIT as no-ops; each DDL/GRANT statement
    auto-commits independently. End state is identical either way: role
    exists with the expected flags + the expected grants.
    """
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
            {"r": _RLS_TEST_ROLE},
        ).fetchone()
        if not existing:
            # CREATE ROLE does not accept bind parameters; the role name is
            # a known module-private constant (not user input).
            conn.execute(
                text(
                    f"CREATE ROLE {_RLS_TEST_ROLE} NOSUPERUSER NOBYPASSRLS "
                    f"NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION"
                )
            )
        # Idempotent grants (re-applied each session).
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {_RLS_TEST_ROLE}"))
        conn.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN "
                f"SCHEMA public TO {_RLS_TEST_ROLE}"
            )
        )


# ── Reader roles the migration chain GRANTs to but never CREATEs ─────────────
# Every reader role has its own CREATE ROLE migration (cip_09/21/25/28/31/120)
# EXCEPT metabase_reader_foundry: it was added to the reader-role GRANT lists in
# cip_155+ with no companion CREATE ROLE migration. Prod (+ new tenants on the
# shared DB) has the role out-of-band, so those migrates are fine — but a
# from-scratch `alembic upgrade head` on a fresh DB (any testcontainer) dies at
# cip_155's GRANT. Provision it up front so the test suite can apply the full
# chain. The proper repo fix (create it before cip_155 in the shipped chain) is
# CIP-core and is flagged to Tim; this keeps tests green meanwhile.
_UNCREATED_READER_ROLES = ("metabase_reader_foundry",)


def provision_uncreated_reader_roles(database_url: str) -> None:
    """Idempotently CREATE reader roles the migration chain GRANTs to but never
    creates itself. Call BEFORE ``alembic upgrade head`` on a fresh DB."""
    eng = create_engine(database_url)
    try:
        with eng.begin() as conn:
            for role in _UNCREATED_READER_ROLES:
                exists = conn.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
                ).fetchone()
                if not exists:
                    # role name is a known module constant, not user input.
                    conn.execute(text(
                        f"CREATE ROLE {role} NOSUPERUSER NOBYPASSRLS NOCREATEDB "
                        f"NOCREATEROLE NOINHERIT NOREPLICATION NOLOGIN"
                    ))
    finally:
        eng.dispose()


@contextmanager
def session_as_role_and_tenant(
    engine: Engine, tenant_id: UUID | None
) -> Iterator[Connection]:
    """Open a Connection AS ``cip_rls_test_role`` with optional tenant context.

    SETs the role for the connection (so RLS enforces — the role is
    NOBYPASSRLS) and applies ``app.current_tenant`` GUC via
    ``set_config('app.current_tenant', :t, true)`` when ``tenant_id`` is
    supplied. ``tenant_id=None`` is useful for asserting the
    "no tenant context → zero rows" semantic.

    Yields a Connection; the surrounding transaction is rolled back on
    exit (read-only by convention; tests that need to write should use a
    different fixture).

    Usage::

        with session_as_role_and_tenant(engine, tenant_id) as conn:
            rows = conn.execute(sa.select(cip_companies)).all()
    """
    with engine.connect() as conn:
        try:
            conn.execute(text("BEGIN"))
            conn.execute(text(f"SET LOCAL ROLE {_RLS_TEST_ROLE}"))
            if tenant_id is not None:
                conn.execute(
                    text("SELECT set_config('app.current_tenant', :t, true)"),
                    {"t": str(tenant_id)},
                )
            yield conn
        finally:
            conn.execute(text("ROLLBACK"))
