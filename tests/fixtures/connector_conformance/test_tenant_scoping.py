# foundry: kind=test domain=client-intelligence-platform
"""Conformance test §5.7 — Tenant scoping (RLS).

Two tenants A and B; sync different record counts to each; verify that
queries under the non-superuser ``cip_rls_test_role`` see ONLY their own
tenant's rows. Superuser without context → all rows (BYPASSRLS).

Per Delta 14: ``apply_tenant_context`` uses ``set_config(...)`` (Postgres
idiom that accepts bind params) — RLS-equivalent to SET LOCAL.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from cip.integration_mesh import run_sync
from tests.fixtures.connector_conformance.conftest import (
    MockConnector,
    MockMapper,
    session_as_role_and_tenant,
)
from tests.fixtures.connector_conformance.fixtures.records import (
    CANONICAL_SCHEMA,
)


def _records_for(prefix: str, n: int) -> list[dict[str, Any]]:
    from datetime import UTC
    from datetime import datetime as dt
    return [
        {
            "id": f"{prefix}-{i:03d}",
            "source_id": f"{prefix}-{i:03d}",
            "email": f"{prefix}{i}@x.com",
            "updated_at": dt(2026, 4, 20, i, 0, 0, tzinfo=UTC).isoformat(),
        }
        for i in range(n)
    ]


@pytest.mark.usefixtures("cleanup_tenants")
def test_tenant_a_query_sees_only_a_rows(
    seeded_engine: Engine,
    cleanup_tenants: list[UUID],
    mock_mapper: MockMapper,
) -> None:
    from uuid import uuid4

    tid_a, tid_b, tid_c = uuid4(), uuid4(), uuid4()
    cleanup_tenants.extend([tid_a, tid_b, tid_c])

    # Seed A with 5 records, B with 3.
    run_sync(
        MockConnector(
            tenant_id=tid_a,
            records=_records_for("a", 5),
            schema=CANONICAL_SCHEMA,
        ),
        mock_mapper,
        seeded_engine,
        tenant_id=tid_a,
    )
    run_sync(
        MockConnector(
            tenant_id=tid_b,
            records=_records_for("b", 3),
            schema=CANONICAL_SCHEMA,
        ),
        mock_mapper,
        seeded_engine,
        tenant_id=tid_b,
    )

    # Query under non-superuser role with tenant A context.
    with session_as_role_and_tenant(seeded_engine, tid_a) as conn:
        a_count = conn.execute(
            text("SELECT COUNT(*) FROM cip_contacts")
        ).scalar()
    assert a_count == 5

    # Query as tenant B.
    with session_as_role_and_tenant(seeded_engine, tid_b) as conn:
        b_count = conn.execute(
            text("SELECT COUNT(*) FROM cip_contacts")
        ).scalar()
    assert b_count == 3

    # Query as tenant C (no rows seeded).
    with session_as_role_and_tenant(seeded_engine, tid_c) as conn:
        c_count = conn.execute(
            text("SELECT COUNT(*) FROM cip_contacts")
        ).scalar()
    assert c_count == 0

    # Query as RLS-role with NO tenant context → 0 (RLS denies all).
    with session_as_role_and_tenant(seeded_engine, None) as conn:
        no_context_count = conn.execute(
            text("SELECT COUNT(*) FROM cip_contacts")
        ).scalar()
    assert no_context_count == 0

    # Superuser bypass: scope by tenant_id explicitly to confirm both tenants
    # have rows in the DB (not RLS-filtered out).
    with seeded_engine.connect() as conn:
        for tid, expected in [(tid_a, 5), (tid_b, 3), (tid_c, 0)]:
            count = conn.execute(
                text("SELECT COUNT(*) FROM cip_contacts WHERE tenant_id = :t"),
                {"t": str(tid)},
            ).scalar()
            assert count == expected
