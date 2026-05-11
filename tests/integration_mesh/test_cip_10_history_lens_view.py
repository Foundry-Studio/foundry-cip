# foundry: kind=test domain=client-intelligence-platform
"""M8 cip_10 history-lens proof-of-life — verification tests.

Per PHASE-1-PLAIN-SPEC.md §15.1 (Tim amendment 2026-05-11): close the
"can a BI tool reach CIP's history surface through cip_metabase_role"
question before locking Phase 1.

5 tests covering acceptance rows 14.1-14.5:

  14.1 — lens_companies_history view exists in pg_views
  14.2 — cip_metabase_role CAN SELECT the lens view; CANNOT SELECT the
         underlying cip_companies_history table (P-21 still enforced)
  14.3 — view returns >0 rows when history rows exist for the tenant
         (test injects a synthetic history row via direct SQL after the
         initial sync — the SCD differ produces history rows only on
         changes, and isolating the lens-view test from the differ's
         change-detection behavior is the cleanest proof of the lens
         surface itself; full differ behavior is exercised in the M3
         conformance harness's test_scd_history)
  14.4 — cross-tenant isolation holds on the history-lens view
  14.5 — (this file IS the test that satisfies 14.5)
"""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from cip.integration_mesh import (
    CorpusSize,
    FixtureConnector,
    FixtureMapper,
    run_sync,
)

_METABASE_ROLE = "cip_metabase_role"
_METABASE_TEST_PASSWORD_FALLBACK = (
    "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105
)


def _seed_fixture_tenant(seeded_engine: Engine, database_url: str) -> UUID:
    """Per-test fresh tenant + FixtureConnector STANDARD sync (writes
    cip_companies + cip_companies_history rows)."""
    tenant_id = uuid4()
    run_sync(
        FixtureConnector(
            tenant_id=tenant_id, seed=42, size=CorpusSize.STANDARD
        ),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    return tenant_id


def _role_engine(seeded_engine: Engine) -> Engine:
    """Return a fresh engine bound to cip_metabase_role. Caller MUST
    dispose() the engine after use to avoid pool leak."""
    role_url = seeded_engine.url.set(
        username=_METABASE_ROLE,
        password=os.environ.get(
            "METABASE_DB_PASSWORD", _METABASE_TEST_PASSWORD_FALLBACK
        ),
    )
    return create_engine(role_url, pool_pre_ping=True)


def _inject_history_row(
    seeded_engine: Engine, tenant_id: UUID
) -> int:
    """Pick one cip_companies row for this tenant and write a synthetic
    history row referencing it. Returns the number of history rows
    written (1 on success; 0 if no companies exist for the tenant).

    Uses direct SQL because the SCD differ only writes history rows on
    DETECTED CHANGES — initial inserts go straight to the main table.
    Mocking a change-event-then-resync is out of scope for the lens-
    surface test; differ behavior is covered exhaustively by the M3
    conformance harness.
    """
    with seeded_engine.begin() as conn:
        company = conn.execute(
            text(
                "SELECT id, source_connector, source_id, name, region "
                "FROM cip_companies WHERE tenant_id = :t LIMIT 1"
            ),
            {"t": str(tenant_id)},
        ).first()
        if company is None:
            return 0
        conn.execute(
            text(
                """
                INSERT INTO cip_companies_history (
                    record_id, tenant_id, valid_from, valid_to,
                    changed_by, change_reason,
                    source_connector, source_id,
                    ingested_at, refreshed_at,
                    ingestion_batch_id, authority,
                    name, region
                )
                VALUES (
                    :rid, :tid, NOW() - INTERVAL '1 hour', NOW(),
                    'test_history_lens_inject', 'm8 proof-of-life',
                    :sc, :sid,
                    NOW() - INTERVAL '1 hour', NOW() - INTERVAL '1 hour',
                    gen_random_uuid(), 'ingested',
                    :name, :region
                )
                """
            ),
            {
                "rid": company.id,
                "tid": str(tenant_id),
                "sc": company.source_connector,
                "sid": company.source_id,
                "name": company.name + " (historical snapshot)",
                "region": company.region,
            },
        )
    return 1


# ── 14.1: view exists in pg_views ─────────────────────────────────────────


def test_history_lens_view_exists_in_pg_views(
    seeded_engine: Engine,
) -> None:
    """cip_10 migration creates `lens_companies_history` in public schema.
    Verifiable via pg_views."""
    with seeded_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT viewname FROM pg_views "
                "WHERE schemaname = 'public' "
                "AND viewname = 'lens_companies_history'"
            )
        ).first()
    assert row is not None, (
        "lens_companies_history view not found in pg_views — cip_10 may "
        "not have run, or the view name drifted"
    )
    assert row.viewname == "lens_companies_history"


# ── 14.2: P-21 enforcement — view yes, underlying table no ────────────────


def test_metabase_role_can_select_history_lens_view(
    seeded_engine: Engine, database_url: str
) -> None:
    """cip_metabase_role MUST have SELECT on lens_companies_history."""
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)
    role_eng = _role_engine(seeded_engine)
    try:
        with role_eng.connect() as conn:
            try:
                conn.execute(text("BEGIN"))
                conn.execute(
                    text(
                        "SELECT set_config('app.current_tenant', :t, true)"
                    ),
                    {"t": str(tenant_id)},
                )
                # SELECT should succeed (zero or more rows are both OK; this
                # test ONLY proves access — count assertion lives in 14.3)
                conn.execute(
                    text("SELECT COUNT(*) FROM lens_companies_history")
                ).scalar()
            finally:
                conn.execute(text("ROLLBACK"))
    finally:
        role_eng.dispose()


def test_metabase_role_cannot_select_underlying_history_table(
    seeded_engine: Engine,
) -> None:
    """P-21 enforcement: cip_metabase_role must NOT have SELECT on the raw
    cip_companies_history table — only the lens view. Mirrors the M5
    falsifiability test for cip_companies."""
    role_eng = _role_engine(seeded_engine)
    try:
        with role_eng.connect() as conn:
            with pytest.raises(
                Exception,  # psycopg.errors.InsufficientPrivilege wrapped
            ) as exc_info:
                conn.execute(text("SELECT 1 FROM cip_companies_history LIMIT 1"))
            # The wrapped error MUST be psycopg's InsufficientPrivilege
            # (permission denied) — anything else would indicate the role
            # has unexpected access.
            assert isinstance(
                exc_info.value.orig,  # type: ignore[attr-defined]
                psycopg.errors.InsufficientPrivilege,
            ), (
                "expected permission denied on cip_companies_history; "
                f"got {type(exc_info.value.orig).__name__}"  # type: ignore[attr-defined]
            )
    finally:
        role_eng.dispose()


# ── 14.3: lens returns >0 rows after STANDARD sync ────────────────────────


def test_history_lens_returns_rows_when_history_exists(
    seeded_engine: Engine, database_url: str
) -> None:
    """Inject a synthetic history row for one of the seeded fixture
    companies; verify the lens view exposes it under cip_metabase_role +
    tenant context. The acceptance question this answers: "is the lens
    surface reachable to a BI tool when there ARE history rows for the
    tenant?" Yes.
    """
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)
    injected = _inject_history_row(seeded_engine, tenant_id)
    assert injected == 1, "test setup failed: no company available to inject history for"

    role_eng = _role_engine(seeded_engine)
    try:
        with role_eng.connect() as conn:
            try:
                conn.execute(text("BEGIN"))
                conn.execute(
                    text(
                        "SELECT set_config('app.current_tenant', :t, true)"
                    ),
                    {"t": str(tenant_id)},
                )
                count_raw = conn.execute(
                    text("SELECT COUNT(*) FROM lens_companies_history")
                ).scalar()
            finally:
                conn.execute(text("ROLLBACK"))
    finally:
        role_eng.dispose()

    count = int(count_raw or 0)
    assert count >= 1, (
        f"history lens returned {count} rows after injecting 1; expected "
        "the injected row to be visible to cip_metabase_role under the "
        "tenant's GUC. Either the lens view is missing the row, the role "
        "lacks SELECT, or the tenant-context GUC isn't filtering correctly."
    )


# ── 14.4: cross-tenant isolation on the history-lens view ─────────────────


def test_cross_tenant_isolation_on_history_lens(
    seeded_engine: Engine, database_url: str
) -> None:
    """Two tenants each get a STANDARD sync; querying the history lens as
    cip_metabase_role with tenant A's GUC returns only tenant A's rows.
    Tenant B's history is invisible to tenant A's session.

    Mirrors test_cross_tenant_isolation_through_cip_views (M6) for the
    historical surface.
    """
    tid_a = _seed_fixture_tenant(seeded_engine, database_url)
    tid_b = _seed_fixture_tenant(seeded_engine, database_url)
    # Inject one synthetic history row per tenant so both have history
    # for the cross-tenant comparison.
    assert _inject_history_row(seeded_engine, tid_a) == 1
    assert _inject_history_row(seeded_engine, tid_b) == 1

    # Snapshot the master-side count for each tenant via direct DB access
    # (testcontainer Postgres superuser bypasses RLS; we read both sides
    # to confirm both tenants have history rows in the underlying table).
    with seeded_engine.connect() as conn:
        a_master = conn.execute(
            text(
                "SELECT COUNT(*) FROM cip_companies_history "
                "WHERE tenant_id = :t"
            ),
            {"t": str(tid_a)},
        ).scalar()
        b_master = conn.execute(
            text(
                "SELECT COUNT(*) FROM cip_companies_history "
                "WHERE tenant_id = :t"
            ),
            {"t": str(tid_b)},
        ).scalar()
    assert int(a_master or 0) > 0
    assert int(b_master or 0) > 0

    # Now query as cip_metabase_role with tenant A's GUC — must return
    # exactly tenant A's count, NOT tenant A+B combined.
    role_eng = _role_engine(seeded_engine)
    try:
        with role_eng.connect() as conn:
            try:
                conn.execute(text("BEGIN"))
                conn.execute(
                    text(
                        "SELECT set_config('app.current_tenant', :t, true)"
                    ),
                    {"t": str(tid_a)},
                )
                lens_count_raw = conn.execute(
                    text("SELECT COUNT(*) FROM lens_companies_history")
                ).scalar()
            finally:
                conn.execute(text("ROLLBACK"))
    finally:
        role_eng.dispose()

    lens_count = int(lens_count_raw or 0)
    assert lens_count == int(a_master or 0), (
        f"history-lens view leaked across tenant boundary: lens returned "
        f"{lens_count} for tenant A, but tenant A's master count is "
        f"{a_master} (tenant B has {b_master} rows that should be invisible)"
    )
