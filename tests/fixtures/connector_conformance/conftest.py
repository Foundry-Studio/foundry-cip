# foundry: kind=test domain=client-intelligence-platform
"""Conformance-harness fixtures (M2 §5.1).

Session-scoped Postgres testcontainer + alembic upgrade head + per-test
tenant_id + mock connector / mapper factories. RLS-isolation tests
(test_tenant_scoping, test_post_commit_rls_isolation — NOT in the M2
dry-run scope) would need a non-superuser role; those land later.

Container image pinned to ``postgres:16-alpine`` per plan §5.1.
"""
from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from cip.integration_mesh import (
    DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS,
    DEFAULT_RATE_LIMIT,
    CIPConnectorBase,
    CIPMapperBase,
    CIPRow,
    KnowledgeText,
    KnowledgeTextMetadata,
    PropertyDescriptor,
    RateLimitPolicy,
)
from tests._helpers.rls import (
    provision_cip_rls_test_role,
    session_as_role_and_tenant,  # noqa: F401  # re-exported for test_tenant_scoping.py
)

# ── Constants ─────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[3]

# Restricted non-superuser role used for RLS verification queries (§5.7, §5.8).
# Provisioning + session helper imported from ``tests/_helpers/rls.py`` per
# the post-M4 extraction (resolves the v5.4 TODO).


# ── Postgres testcontainer ────────────────────────────────────────────────


@pytest.fixture(scope="session")
def postgres_container() -> Generator[Any, None, None]:
    """Session-scoped Postgres testcontainer (postgres:16-alpine).

    Pinned image per plan §5.1. Container spins up once for the test
    session; teardown disposes.
    """
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def database_url(postgres_container: Any) -> str:
    """Normalize the testcontainer URL to psycopg3 dialect (matches the
    framework's pyproject pin: ``psycopg[binary]>=3``).
    """
    raw_url = str(postgres_container.get_connection_url())
    if raw_url.startswith("postgresql+psycopg2"):
        return raw_url.replace("postgresql+psycopg2", "postgresql+psycopg", 1)
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw_url


@pytest.fixture(scope="session")
def seeded_engine(
    database_url: str,
) -> Generator[Engine, None, None]:
    """Engine with all migrations applied and the v5 PATCH-NR-1 listener
    registered (RESET app.current_tenant on every checkout).
    """
    # Run alembic upgrade head against the testcontainer DB.
    # env.py reads DATABASE_URL from os.environ.
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

    # v5 PATCH-NR-1: reset app.current_tenant on every connection checkout.
    @event.listens_for(eng, "checkout")
    def _reset_tenant_context(
        dbapi_connection: Any, connection_record: Any, connection_proxy: Any
    ) -> None:
        cur = dbapi_connection.cursor()
        try:
            cur.execute("SELECT set_config('app.current_tenant', '', false)")
        finally:
            cur.close()

    # Provision the non-superuser role for §5.7 + §5.8 RLS verification queries.
    provision_cip_rls_test_role(eng)

    yield eng
    eng.dispose()


@pytest.fixture(scope="function")
def tenant_id() -> UUID:
    """Per-test fresh tenant_id — keeps tests cleanly isolated even when
    they share the session-scoped engine."""
    return uuid4()


@pytest.fixture(scope="function")
def cleanup_tenant(
    seeded_engine: Engine, tenant_id: UUID
) -> Generator[None, None, None]:
    """Per-test teardown: delete rows for this tenant from every cip_*
    table the framework writes to. Safe across all conformance tests
    sharing the session-scoped engine.

    Also accepts ``tenant_ids`` (plural) on the request scope for tests that
    seed multiple tenants — see ``cleanup_tenants`` fixture below.
    """
    yield
    with seeded_engine.begin() as conn:
        for tbl in (
            "cip_contacts_history",
            "cip_contacts",
            "cip_sync_runs",
            "cip_connector_property_registry",
        ):
            conn.execute(
                text(f"DELETE FROM {tbl} WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )


@pytest.fixture(scope="function", autouse=True)
def truncate_cip_tables(
    seeded_engine: Engine,
) -> Generator[None, None, None]:
    """M3 §5.1 / v2 #11: autouse function-scope cleanup for cross-test
    isolation in the 8th conformance test (``test_concurrent_sync_advisory_lock``).

    The 8th test's 4 base + 4 lock-property sub-tests share the
    session-scoped Postgres testcontainer; without TRUNCATE between
    sub-tests, state from earlier sub-tests cascades into later ones
    (rows persist; sync-runs accumulate; advisory locks unwind cleanly
    but committed data does not).

    Runs at TEARDOWN (yield → TRUNCATE) so the test itself sees whatever
    initial state the test author seeded. Subsequent tests see a clean
    DB. Idempotent + cheap: TRUNCATE on empty tables is near-instant;
    the 22 existing conformance tests pay <1s of cumulative overhead.

    TRUNCATE … CASCADE handles the cip_*_history → cip_* FK chains.
    """
    yield
    with seeded_engine.begin() as conn:
        # Order intentional: history tables first (FK children), then current,
        # then independent audit/registry tables. CASCADE on the current
        # tables would also handle history; explicit list keeps it readable.
        conn.execute(
            text(
                "TRUNCATE TABLE "
                "cip_clients_history, cip_views_history, cip_files_history, "
                "cip_contacts_history, cip_companies_history, "
                "cip_deals_history, cip_tickets_history, "
                "cip_clients, cip_views, cip_files, cip_contacts, "
                "cip_companies, cip_deals, cip_tickets, "
                "cip_sync_runs, cip_connector_property_registry "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture(scope="function")
def cleanup_tenants(
    seeded_engine: Engine,
) -> Generator[list[UUID], None, None]:
    """Multi-tenant cleanup helper — for tests that seed >1 tenant.

    Tests append UUIDs to the yielded list during execution; teardown
    deletes rows for each.
    """
    tenant_ids: list[UUID] = []
    yield tenant_ids
    if not tenant_ids:
        return
    with seeded_engine.begin() as conn:
        for tid in tenant_ids:
            for tbl in (
                "cip_contacts_history",
                "cip_contacts",
                "cip_sync_runs",
                "cip_connector_property_registry",
            ):
                conn.execute(
                    text(f"DELETE FROM {tbl} WHERE tenant_id = :t"),
                    {"t": str(tid)},
                )


# ``session_as_role_and_tenant`` imported from ``tests/_helpers/rls.py``
# (post-M4 extraction; resolves the v5.4 TODO).


# ── Mock connector / mapper (plan §5.1) ───────────────────────────────────


class MockConnector(CIPConnectorBase):
    """Plan §5.1 connector. Stream-records honors cursor's
    last_incremental_key for incremental sync."""

    connector_id = "mock-connector-v1"
    version = "1.0.0"

    def __init__(
        self,
        tenant_id: UUID,
        records: list[dict[str, Any]],
        schema: list[dict[str, Any]],
    ) -> None:
        self.tenant_id = tenant_id
        self._records = list(records)
        # Plan §5.1 schema dicts omit ``connector`` and ``cip_table``;
        # add them here when constructing PropertyDescriptor.
        self._schema = [
            PropertyDescriptor(
                connector=self.connector_id,
                cip_table="cip_contacts",
                object_type=s["object_type"],
                property_name=s["property_name"],
                data_type=s["data_type"],
                storage_location=s["storage_location"],
                column_name=s.get("column_name"),
                description=s.get("description"),
                is_custom=s.get("is_custom", False),
            )
            for s in schema
        ]
        self.authenticated = False

    @property
    def rate_limit_policy(self) -> RateLimitPolicy:
        return DEFAULT_RATE_LIMIT

    @property
    def cursor_safety_window_seconds(self) -> int:
        return DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS

    def authenticate(self) -> None:
        self.authenticated = True

    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        last_key: datetime | None = None
        if cursor and "last_incremental_key" in cursor:
            last_key_val = cursor["last_incremental_key"]
            last_key = datetime.fromisoformat(str(last_key_val))
        for rec in self._records:
            ts_obj = rec["updated_at"]
            rec_ts = (
                ts_obj
                if isinstance(ts_obj, datetime)
                else datetime.fromisoformat(str(ts_obj))
            )
            if last_key is not None and rec_ts <= last_key:
                continue
            yield cast(dict[str, object], rec)

    def describe_schema(self) -> list[PropertyDescriptor]:
        return self._schema

    def incremental_key(self, record: dict[str, object]) -> datetime:
        ts_obj = record["updated_at"]
        if isinstance(ts_obj, datetime):
            return ts_obj
        return datetime.fromisoformat(str(ts_obj))


class MockMapper(CIPMapperBase):
    """Plan §5.1 mapper. Maps to cip_contacts; emits source_id-only
    KnowledgeText (the orchestrator finalizes the rest)."""

    object_type = "contact"
    target_table = "cip_contacts"

    def map(self, record: dict[str, object]) -> Iterator[CIPRow]:
        # Domain columns (3 of the 5 schema entries are column-stored).
        fields: dict[str, object] = {
            "first_name": record.get("first_name"),
            "last_name": record.get("last_name"),
            "email": record.get("email"),
        }
        # Overflow = anything not in domain or provenance/metadata fields.
        excluded = {
            "id",
            "source_id",
            "first_name",
            "last_name",
            "email",
            "updated_at",
        }
        overflow = {k: v for k, v in record.items() if k not in excluded}
        yield CIPRow(
            target_table="cip_contacts",
            source_id=str(record["id"]),
            fields=fields,
            overflow=overflow,
            authority="ingested",
        )

    def overflow_fields(self) -> list[str]:
        return ["mock_extra_1", "mock_extra_2"]

    def authority(
        self,
    ) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        # v5.2 Round-6 Call A: emit only source_id (mapper-knows-this);
        # orchestrator finalizes the other 4 required keys.
        email_obj = record.get("email")
        if not email_obj:
            return []
        md: dict[str, object] = {"source_id": str(record["id"])}
        return [
            KnowledgeText(
                text=str(email_obj),
                metadata=cast(KnowledgeTextMetadata, md),
            )
        ]


# ── Factory fixtures ──────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def mock_connector_factory() -> Any:
    """Factory: returns a MockConnector with caller-controlled records + schema."""

    def _factory(
        tenant_id: UUID,
        records: list[dict[str, Any]],
        schema: list[dict[str, Any]],
    ) -> MockConnector:
        return MockConnector(
            tenant_id=tenant_id, records=records, schema=schema
        )

    return _factory


@pytest.fixture(scope="function")
def mock_mapper() -> MockMapper:
    """Default mock mapper (cip_contacts)."""
    return MockMapper()
