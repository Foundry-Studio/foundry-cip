# foundry: kind=test domain=client-intelligence-platform
"""Shared fixtures for the M4 lens-engine test suite (per M4 v2 Gap [1] + [17]).

Houses:
- ``seed_lens()`` — INSERT helper for ``cip_views`` rows under tenant context.
- ``LENS_A_FILTER_CONFIG`` / ``LENS_B_FILTER_CONFIG`` constants — the two demo
  lenses used across compiler / loading / e2e / snapshot suites.
- The Postgres testcontainer fixtures (``postgres_container``, ``database_url``,
  ``seeded_engine``) re-exported from the conformance harness so the
  integration-mesh e2e tests get them via standard pytest fixture-resolution
  (parent dir conftests don't reach into sibling dirs).

Existing M2/M3 unit tests under this directory don't request DB fixtures, so
the testcontainer doesn't spin up unless a lens-engine test asks for it.
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
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

    yield eng
    eng.dispose()


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
    db: Session,
    *,
    tenant_id: UUID,
    view_name: str,
    filter_config: dict[str, Any],
    target_table: str = "cip_companies",
    description: str | None = None,
    is_default: bool = False,
) -> UUID:
    """INSERT a row into ``cip_views`` under the active tenant context.

    Caller MUST have applied tenant context (``apply_tenant_context``) on
    ``db`` BEFORE calling — otherwise RLS will reject the INSERT.

    Returns the new row's ``id`` UUID.
    """
    new_id = uuid4()
    batch_id = uuid4()
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
            "source_connector": "cip_engine_v1",
            "source_id": target_table,
            "batch_id": str(batch_id),
            "view_name": view_name,
            "description": description,
            "filter_config": _json_dumps(filter_config),
            "is_default": is_default,
        },
    )
    return new_id


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
