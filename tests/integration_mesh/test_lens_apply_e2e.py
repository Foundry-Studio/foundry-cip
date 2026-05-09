# foundry: kind=test domain=client-intelligence-platform
"""M4 lens-application e2e tests (M4 §5.3 binding).

End-to-end: real Postgres testcontainer + FixtureConnector STANDARD sync
(1150 rows, including 50 cip_companies records distributed across 5 region
values per M4 Δ1). Lenses applied, row counts asserted, P-21 falsifiability
demonstrated, RLS-composition verified.

Acceptance coverage:
- #6 Lens-A all 50 companies (#13).
- #6 Lens-B eu-west subset (#14, deterministic count, 0 < n < 50).
- #6 row-count delta proof (Lens-A − Lens-B = non-eu-west count).
- #15 P-21 falsifiability — third lens via INSERT only, no code change.
- #16 RLS composes with lens application — verified under
  ``cip_rls_test_role`` (NOSUPERUSER NOBYPASSRLS) per M4 Δ3.

Each test uses a fresh ``tenant_id`` and runs its own FixtureConnector
STANDARD sync. Per-test isolation eliminates ordering-dependent assertions
and survives test reordering / parallelization. Cost: ~5s per sync, ~30s
total file runtime.
"""
from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cip.integration_mesh import (
    CorpusSize,
    FixtureConnector,
    FixtureMapper,
    apply_lens,
    lens_query_for_table,
    load_lens,
    run_sync,
)
from cip.integration_mesh.tenant_context import apply_tenant_context
from tests.integration_mesh.conftest import (
    LENS_A_FILTER_CONFIG,
    LENS_B_FILTER_CONFIG,
    seed_lens,
    session_as_role_and_tenant,
)


def _reflect_companies(engine: Engine) -> sa.Table:
    """Reflect cip_companies from the live schema. Cheap; no need to cache."""
    md = sa.MetaData()
    md.reflect(bind=engine, only=["cip_companies"])
    return md.tables["cip_companies"]


# ── §5.3.1 — Lens-A returns all 50 companies (acceptance #13) ─────────────


def test_lens_a_returns_all_50_companies(
    seeded_engine: Engine, database_url: str
) -> None:
    """Lens-A ``filter_config={}`` → no-op filter → all 50 STANDARD companies."""
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
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        seed_lens(
            db,
            tenant_id=tenant_id,
            view_name="lens_a_all_companies",
            filter_config=LENS_A_FILTER_CONFIG,
            target_table="cip_companies",
        )

    companies = _reflect_companies(seeded_engine)
    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        query = lens_query_for_table(
            conn,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            view_name="lens_a_all_companies",
            target_table=companies,
        )
        rows = conn.execute(query).all()
    assert len(rows) == 50


# ── §5.3.2 — Lens-B eu-west subset (acceptance #14) ───────────────────────


def test_lens_b_returns_eu_west_subset(
    seeded_engine: Engine, database_url: str
) -> None:
    """Lens-B ``filter_config={"region": "eu-west"}`` → deterministic subset.
    With 5-value region distribution + seed=42, expected count is non-zero
    and less than 50 (M4 Δ1: lowercase regions; ~10 of 50 expected)."""
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
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        seed_lens(
            db,
            tenant_id=tenant_id,
            view_name="lens_b_eu_west",
            filter_config=LENS_B_FILTER_CONFIG,
            target_table="cip_companies",
        )

    companies = _reflect_companies(seeded_engine)
    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        query = lens_query_for_table(
            conn,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            view_name="lens_b_eu_west",
            target_table=companies,
        )
        rows = conn.execute(query).all()
    n = len(rows)
    assert 0 < n < 50, (
        f"Lens-B should return a strict subset (0 < n < 50), got {n}"
    )
    assert all(row.region == "eu-west" for row in rows)


# ── §5.3.3 — Row-count delta proof ────────────────────────────────────────


def test_lens_a_minus_lens_b_equals_non_eu_west_count(
    seeded_engine: Engine, database_url: str
) -> None:
    """``len(Lens-A) - len(Lens-B) == count of non-eu-west companies``.
    Confirms Lens-A is the universe + Lens-B is a proper subset of it.

    M4 Δ2: each ``seed_lens`` call gets a distinct ``source_connector``
    (defaulted from ``view_name``) so the deployed UNIQUE constraint
    ``(tenant_id, source_connector, source_id)`` doesn't collide."""
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
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        seed_lens(
            db,
            tenant_id=tenant_id,
            view_name="lens_a_delta",
            filter_config=LENS_A_FILTER_CONFIG,
        )
        seed_lens(
            db,
            tenant_id=tenant_id,
            view_name="lens_b_delta",
            filter_config=LENS_B_FILTER_CONFIG,
        )

    companies = _reflect_companies(seeded_engine)
    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        rows_a = conn.execute(
            lens_query_for_table(
                conn,  # type: ignore[arg-type]
                tenant_id=tenant_id,
                view_name="lens_a_delta",
                target_table=companies,
            )
        ).all()
        rows_b = conn.execute(
            lens_query_for_table(
                conn,  # type: ignore[arg-type]
                tenant_id=tenant_id,
                view_name="lens_b_delta",
                target_table=companies,
            )
        ).all()
        non_eu_west = conn.execute(
            sa.select(sa.func.count())
            .select_from(companies)
            .where(companies.c.region != "eu-west")
        ).scalar()

    assert len(rows_a) - len(rows_b) == non_eu_west


# ── §5.3.4 — P-21 falsifiability (acceptance #15) ─────────────────────────


def test_third_lens_added_via_row_only_no_code_change(
    seeded_engine: Engine, database_url: str
) -> None:
    """Acceptance #15 — P-21 falsifiability. A third lens (different filter,
    same target table, same engine code) is authored by INSERT alone. The
    engine resolves it without any schema or framework code change. Within
    the deployed ``_VALID_TARGET_TABLES`` whitelist (per v2 Stress [5]
    reframe — adding a NEW table requires a deliberate compile-time edit)."""
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

    third_filter = {"region": "us-east"}
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        seed_lens(
            db,
            tenant_id=tenant_id,
            view_name="lens_third_us_east",
            filter_config=third_filter,
        )

    companies = _reflect_companies(seeded_engine)
    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        rows = conn.execute(
            lens_query_for_table(
                conn,  # type: ignore[arg-type]
                tenant_id=tenant_id,
                view_name="lens_third_us_east",
                target_table=companies,
            )
        ).all()

    n = len(rows)
    assert 0 < n < 50, (
        f"third lens should return a non-empty proper subset of 50, got {n}"
    )
    assert all(row.region == "us-east" for row in rows)


# ── §5.3.5 — RLS-bound composition under lens application (acceptance #16) ─


def test_lens_query_compose_with_tenant_rls(
    seeded_engine: Engine, database_url: str
) -> None:
    """Two tenants, both populated with FixtureConnector STANDARD (identical
    deterministic data per seed=42). Both seed Lens-B (``region="eu-west"``).
    Query under tenant-A's RLS-enforcing role context → returns ONLY
    tenant-A's rows. Same query under tenant-B's role context → returns
    ONLY tenant-B's rows. Counts equal (deterministic data); no row leaks.

    M4 Δ3: this test runs under ``cip_rls_test_role`` because the
    testcontainer's default user has BYPASSRLS — under superuser, both
    tenants' rows would leak through and the assertion would fail spuriously.
    """
    tenant_a = uuid4()
    tenant_b = uuid4()

    for tid in (tenant_a, tenant_b):
        run_sync(
            FixtureConnector(tenant_id=tid, seed=42, size=CorpusSize.STANDARD),
            FixtureMapper(),
            seeded_engine,
            tenant_id=tid,
            database_url=database_url,
        )

    for tid in (tenant_a, tenant_b):
        with Session(seeded_engine, autoflush=False) as db, db.begin():
            apply_tenant_context(db, tid)
            seed_lens(
                db,
                tenant_id=tid,
                view_name="rls_compose_lens",
                filter_config=LENS_B_FILTER_CONFIG,
            )

    companies = _reflect_companies(seeded_engine)
    # Query under tenant-A's role-enforced context.
    with session_as_role_and_tenant(seeded_engine, tenant_a) as conn:
        rows_a = conn.execute(
            lens_query_for_table(
                conn,  # type: ignore[arg-type]
                tenant_id=tenant_a,
                view_name="rls_compose_lens",
                target_table=companies,
            )
        ).all()

    assert all(row.tenant_id == tenant_a for row in rows_a)
    assert all(row.region == "eu-west" for row in rows_a)

    # Query under tenant-B's role-enforced context.
    with session_as_role_and_tenant(seeded_engine, tenant_b) as conn:
        rows_b = conn.execute(
            lens_query_for_table(
                conn,  # type: ignore[arg-type]
                tenant_id=tenant_b,
                view_name="rls_compose_lens",
                target_table=companies,
            )
        ).all()
    assert all(row.tenant_id == tenant_b for row in rows_b)
    # Identical data → identical eu-west count per tenant.
    assert len(rows_a) == len(rows_b)


# Quiet the unused-import warnings (these are imported for future test use).
_ = (apply_lens, load_lens)
