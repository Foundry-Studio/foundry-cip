# foundry: kind=test domain=client-intelligence-platform
"""Shared fixtures for the M4 lens-engine test suite (per M4 v2 Gap [1] + [17]).

Houses:
- ``seed_lens()`` — INSERT helper for ``cip_views`` rows under tenant context.
  Accepts a ``source_connector`` kwarg per M4 Δ2 (deployed UNIQUE constraint
  on ``(tenant_id, source_connector, source_id)`` requires distinct
  source_connector values when multiple lenses target the same entity table
  for the same tenant).
- ``LENS_A_FILTER_CONFIG`` / ``LENS_B_FILTER_CONFIG`` constants — the two demo
  lenses used across compiler / loading / e2e / snapshot suites.
- The Postgres testcontainer fixtures (``postgres_container``, ``database_url``,
  ``seeded_engine``) re-exported from the conformance harness so the
  integration-mesh e2e tests get them via standard pytest fixture-resolution
  (parent dir conftests don't reach into sibling dirs).
- ``session_as_role_and_tenant()`` — opens a Connection under
  ``cip_rls_test_role`` (NOSUPERUSER NOBYPASSRLS) with tenant context applied.
  Required for read-side queries that exercise RLS — the testcontainer's
  default user is a superuser with BYPASSRLS, so RLS is inert against it.
  Per M4 Δ3 (mirrors the conformance harness's role pattern).

Existing M2/M3 unit tests under this directory don't request DB fixtures, so
the testcontainer doesn't spin up unless a lens-engine test asks for it.
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

# ── Re-export Postgres testcontainer fixtures from the conformance conftest ──
# Pytest's fixture-resolution walks up parent dirs but not across siblings;
# the conformance conftest is at tests/fixtures/connector_conformance/conftest.py
# and the e2e tests live at tests/integration_mesh/. Re-import to make them
# visible here.
#
# Per M4 plan §3 + the Δ4 placement reconciliation context noted in M3 step 7:
# the canonical fixtures stay at the conformance conftest; we mirror them via
# pytest's standard fixture-import pattern.

REPO_ROOT = Path(__file__).resolve().parents[2]

# M4 Δ3: the testcontainer's default user is a Postgres superuser with
# BYPASSRLS — RLS policies are inert against it. To honestly exercise RLS
# (acceptance #16 cross-tenant blocking), we need a NOSUPERUSER NOBYPASSRLS
# role. Mirrors ``tests/fixtures/connector_conformance/conftest.py``'s pattern.
_RLS_TEST_ROLE = "cip_rls_test_role"


@pytest.fixture(scope="session")
def postgres_container() -> Generator[Any, None, None]:
    """Session-scoped Postgres testcontainer — mirrors the conformance fixture
    so M4 lens-engine tests under ``tests/integration_mesh/`` can use it."""
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def database_url(postgres_container: Any) -> str:
    """Normalize the testcontainer URL to psycopg3 dialect."""
    raw_url = str(postgres_container.get_connection_url())
    if raw_url.startswith("postgresql+psycopg2"):
        return raw_url.replace("postgresql+psycopg2", "postgresql+psycopg", 1)
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw_url


@pytest.fixture(scope="session")
def seeded_engine(database_url: str) -> Generator[Engine, None, None]:
    """Engine with ``alembic upgrade head`` applied + the M2 PATCH-NR-1 listener
    (RESET ``app.current_tenant`` on every connection checkout)."""
    import os

    from sqlalchemy import create_engine, event

    prev_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(cfg, "head")
    finally:
        if prev_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev_url

    eng = create_engine(database_url, pool_pre_ping=True)

    @event.listens_for(eng, "checkout")
    def _reset_tenant_context(
        dbapi_connection: Any, connection_record: Any, connection_proxy: Any
    ) -> None:
        cur = dbapi_connection.cursor()
        try:
            cur.execute("SELECT set_config('app.current_tenant', '', false)")
        finally:
            cur.close()

    # M4 Δ3: provision cip_rls_test_role for read-side RLS verification.
    _ensure_rls_test_role(eng)

    yield eng
    eng.dispose()


def _ensure_rls_test_role(engine: Engine) -> None:
    """Create ``cip_rls_test_role`` if it does not exist.

    NOSUPERUSER NOBYPASSRLS so PostgreSQL applies RLS policies to it. Idempotent.
    Mirrors ``tests/fixtures/connector_conformance/conftest.py::_ensure_rls_test_role``.
    """
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
            {"r": _RLS_TEST_ROLE},
        ).fetchone()
        if not existing:
            conn.execute(
                text(
                    f"CREATE ROLE {_RLS_TEST_ROLE} NOSUPERUSER NOBYPASSRLS "
                    f"NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION"
                )
            )
        conn.execute(
            text(f"GRANT USAGE ON SCHEMA public TO {_RLS_TEST_ROLE}")
        )
        conn.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN "
                f"SCHEMA public TO {_RLS_TEST_ROLE}"
            )
        )


# ── Demo lens filter-config constants (Gap [1] + Gap [17]) ─────────────────


# M4 Δ1 reconciliation (v2.1, 2026-05-09): deployed FixtureConnector uses
# lowercase region values (``us-east``, ``us-west``, ``eu-west``, ``apac``,
# ``latam``) — see ``cip/integration_mesh/connectors/fixture/corpus.py``.
# Lens-B targets ``eu-west`` (the EMEA-equivalent in deployed scheme).

LENS_A_FILTER_CONFIG: dict[str, Any] = {}
"""Lens-A: ``filter_config={}`` — no-op filter, returns all rows in target."""

LENS_B_FILTER_CONFIG: dict[str, Any] = {"region": "eu-west"}
"""Lens-B: equality filter on cip_companies.region == 'eu-west'."""


# ── seed_lens helper ────────────────────────────────────────────────────────


def seed_lens(
    db: Session | Connection,
    *,
    tenant_id: UUID,
    view_name: str,
    filter_config: dict[str, Any],
    target_table: str = "cip_companies",
    source_connector: str | None = None,
    description: str | None = None,
    is_default: bool = False,
) -> UUID:
    """INSERT a row into ``cip_views`` under the active tenant context.

    Caller MUST have applied tenant context (``apply_tenant_context``) on
    ``db`` BEFORE calling — otherwise RLS will reject the INSERT.

    M4 Δ2: deployed ``cip_views`` has ``UNIQUE(tenant_id, source_connector,
    source_id)``. To author multiple lenses on the same target_table for the
    same tenant, callers MUST pass distinct ``source_connector`` values.
    Default is derived from ``view_name`` (``f"cip_engine_v1.{view_name}"``)
    so each lens gets a unique sub-namespace identifier without the caller
    having to think about it. Plan §2.2's flat ``"cip_engine_v1"`` convention
    is a single-lens-per-table assumption that doesn't survive the deployed
    UNIQUE constraint.

    Returns the new row's ``id`` UUID.
    """
    new_id = uuid4()
    batch_id = uuid4()
    effective_source_connector = (
        source_connector
        if source_connector is not None
        else f"cip_engine_v1.{view_name}"
    )
    db.execute(
        text(
            """
            INSERT INTO cip_views (
                id, tenant_id, source_connector, source_id,
                ingestion_batch_id, authority,
                view_name, description, filter_config, is_default
            ) VALUES (
                :id, :tenant_id, :source_connector, :source_id,
                :batch_id, 'validated',
                :view_name, :description, CAST(:filter_config AS jsonb),
                :is_default
            )
            """
        ),
        {
            "id": str(new_id),
            "tenant_id": str(tenant_id),
            "source_connector": effective_source_connector,
            "source_id": target_table,
            "batch_id": str(batch_id),
            "view_name": view_name,
            "description": description,
            "filter_config": _json_dumps(filter_config),
            "is_default": is_default,
        },
    )
    return new_id


@contextmanager
def session_as_role_and_tenant(
    engine: Engine, tenant_id: UUID
) -> Generator[Connection, None, None]:
    """Open a Connection AS ``cip_rls_test_role`` (RLS-enforcing) with the
    given tenant context. Required for read-side queries that exercise RLS
    (acceptance #16) — the testcontainer's default user has BYPASSRLS, so
    RLS is inert against it.

    Per M4 Δ3 (mirrors conformance harness's pattern). Within this context
    the BYPASSRLS bit is gone, so RLS policies actually filter rows by
    ``app.current_tenant``.
    """
    with engine.connect() as conn:
        try:
            conn.execute(text("BEGIN"))
            conn.execute(text(f"SET LOCAL ROLE {_RLS_TEST_ROLE}"))
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, true)"),
                {"t": str(tenant_id)},
            )
            yield conn
        finally:
            conn.execute(text("ROLLBACK"))


def _json_dumps(obj: dict[str, Any]) -> str:
    """Compact JSON for JSONB cast — no whitespace, sorted keys for stability."""
    import json

    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


# ── Per-test cleanup ────────────────────────────────────────────────────────


@pytest.fixture(scope="function", autouse=False)
def clean_lens_tables(seeded_engine: Engine) -> Generator[None, None, None]:
    """Per-test teardown for tests that seed ``cip_views``. Opt-in (not autouse)
    so unit-only tests in the same dir don't pay the cost.

    Empties ``cip_views_history`` first (FK child), then ``cip_views``.
    """
    yield
    with seeded_engine.begin() as conn:
        conn.execute(
            text("TRUNCATE TABLE cip_views_history, cip_views CASCADE")
        )
