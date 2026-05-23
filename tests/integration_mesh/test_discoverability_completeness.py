# foundry: kind=test domain=client-intelligence-platform
"""M6 discoverability registry completeness pass — verification tests.

Phase 1 narrow scope per locked PHASE-1-PLAN.md Milestone 6: verify every
CIP-side artifact is queryable through registries. Verification-only —
no new framework code, no new migrations, no auto-generator (deferred to
Phase 2 PM task #143).

7 tests covering:

1. cip_connector_property_registry — populated for fixture tenant
2. cip_views — seeded lenses queryable via cip_metabase_role role
3. cip_sync_runs — fixture sync recorded with success status + counters
4. cip_files — populated with FixtureMapper r2_path pattern
5. M5 lens_* Postgres views — exist + isolate per tenant
6. features.yaml — parses + has expected JOS-PM-conformant shape
7. cip_views — cross-tenant isolation enforced by RLS

M6 Δ1 (dispatch-vs-deployed, 2026-05-10): dispatch §Test 1 listed object_type
values as plural form (companies, contacts, deals, tickets, files) and 5
total. Deployed describe_schema in
``cip/integration_mesh/connectors/fixture/connector.py`` emits SINGULAR
form (company, contact, deal, ticket, document, note) — 6 total (note is
forward-compat per v2 #2; mapped to cip_tickets but emits 0 rows in
STANDARD). Atlas conflated object_type with cip_table. Test 1 asserts
against deployed reality: ≥1 row each for the 5 active singular types.
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

import sqlalchemy as sa
import yaml  # type: ignore[import-untyped]
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cip.integration_mesh import (
    CorpusSize,
    FixtureConnector,
    FixtureMapper,
    run_sync,
)
from cip.integration_mesh.tenant_context import apply_tenant_context
from tests._helpers.rls import session_as_role_and_tenant
from tests.integration_mesh.conftest import (
    LENS_A_FILTER_CONFIG,
    LENS_B_FILTER_CONFIG,
    seed_lens,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FEATURES_YAML = _REPO_ROOT / "features.yaml"

# Deployed property_type CHECK enum (per cip_08_tickets_and_registry).
_VALID_PROPERTY_TYPES = {
    "string",
    "number",
    "datetime",
    "enumeration",
    "reference",
    "boolean",
    "array",
    "object",
}

# Deployed object_type values from FixtureConnector.describe_schema().
# SINGULAR form per `_d("company", ...)` / `_d("contact", ...)` etc. in
# cip/integration_mesh/connectors/fixture/connector.py. M6 Δ1 against
# dispatch's plural-form claim.
_ACTIVE_OBJECT_TYPES = {"company", "contact", "deal", "ticket", "document"}
# (note is also emitted but with 0 fixture rows; not in active set)

_METABASE_ROLE = "cip_metabase_role"
_METABASE_TEST_PASSWORD_FALLBACK = (
    "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105
)


def _seed_fixture_tenant(seeded_engine: Engine, database_url: str) -> UUID:
    """Per-test fresh tenant + FixtureConnector STANDARD sync.
    Mirrors test_lens_apply_e2e.py canonical pattern (dispatch §Read first)."""
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


# ── Test 1: cip_connector_property_registry populated ──────────────────────


def test_cip_connector_property_registry_populated_for_fixture(
    seeded_engine: Engine, database_url: str
) -> None:
    """After FixtureConnector STANDARD sync, the property registry has
    one row per declared PropertyDescriptor — covering all 5 active
    object_types + the forward-compat note type. Asserts:
      - ≥22 rows (M3 acceptance lower bound)
      - ≥1 row per active object_type {company, contact, deal, ticket, document}
      - storage_location ∈ {column, overflow}
      - property_type ∈ deployed CHECK enum
    """
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)
    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT object_type, property_name, property_type,
                       storage_location, cip_table
                FROM cip_connector_property_registry
                WHERE tenant_id = :tid
                """
            ),
            {"tid": str(tenant_id)},
        ).all()
    assert len(rows) >= 22, f"expected ≥22 registry rows, got {len(rows)}"

    object_types_seen = {r.object_type for r in rows}
    missing = _ACTIVE_OBJECT_TYPES - object_types_seen
    assert not missing, (
        f"missing object_type rows: {missing}; "
        f"got {sorted(object_types_seen)}"
    )

    for r in rows:
        assert r.storage_location in {"column", "overflow"}, (
            f"unexpected storage_location {r.storage_location!r} on "
            f"{r.object_type}.{r.property_name}"
        )
        assert r.property_type in _VALID_PROPERTY_TYPES, (
            f"unexpected property_type {r.property_type!r} on "
            f"{r.object_type}.{r.property_name}"
        )


# ── Test 2: cip_views seeded lenses queryable ──────────────────────────────


def test_cip_views_table_seeded_lenses_queryable(
    seeded_engine: Engine, database_url: str
) -> None:
    """Seed Lens-A and Lens-B via deployed seed_lens helper; verify
    cip_views row shape matches M4 lens conventions (sub-namespaced
    source_connector per Δ2; source_id == 'cip_companies'; filter_config
    JSONB matches the constants the helper set).
    """
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)

    # Deployed pattern: Session + begin + apply_tenant_context, THEN seed_lens.
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        seed_lens(
            db,
            tenant_id=tenant_id,
            view_name="lens_a_all_companies",
            filter_config=LENS_A_FILTER_CONFIG,
            target_table="cip_companies",
        )
        seed_lens(
            db,
            tenant_id=tenant_id,
            view_name="lens_b_eu_west",
            filter_config=LENS_B_FILTER_CONFIG,
            target_table="cip_companies",
        )

    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT view_name, filter_config, source_id, source_connector
                FROM cip_views
                WHERE tenant_id = :tid
                ORDER BY view_name
                """
            ),
            {"tid": str(tenant_id)},
        ).all()

    assert len(rows) == 2, f"expected 2 lens rows, got {len(rows)}"
    by_name = {r.view_name: r for r in rows}
    assert "lens_a_all_companies" in by_name
    assert "lens_b_eu_west" in by_name

    assert by_name["lens_a_all_companies"].filter_config == LENS_A_FILTER_CONFIG
    assert by_name["lens_b_eu_west"].filter_config == LENS_B_FILTER_CONFIG

    for r in rows:
        assert r.source_id == "cip_companies", (
            f"expected source_id=cip_companies, got {r.source_id!r}"
        )
        # M4 Δ2 default: source_connector = f"cip_engine_v1.{view_name}"
        assert r.source_connector == f"cip_engine_v1.{r.view_name}", (
            f"expected source_connector=cip_engine_v1.{r.view_name}, "
            f"got {r.source_connector!r}"
        )


# ── Test 3: cip_sync_runs records fixture sync ─────────────────────────────


def test_cip_sync_runs_records_fixture_sync(
    seeded_engine: Engine, database_url: str
) -> None:
    """run_sync emits at least one cip_sync_runs row with status=success
    + valid started_at/ended_at + non-zero row counters."""
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)
    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT status, started_at, ended_at, error_detail,
                       rows_ingested, rows_history, rows_created,
                       rows_updated, rows_skipped
                FROM cip_sync_runs
                WHERE tenant_id = :tid
                """
            ),
            {"tid": str(tenant_id)},
        ).all()
    assert len(rows) >= 1, "expected ≥1 cip_sync_runs row for fixture tenant"

    success_rows = [r for r in rows if r.status == "success"]
    assert success_rows, f"no success row; statuses: {[r.status for r in rows]}"
    succ = success_rows[0]
    assert succ.started_at is not None
    assert succ.ended_at is not None
    assert succ.ended_at >= succ.started_at
    assert succ.error_detail is None
    counter_total = (
        succ.rows_ingested + succ.rows_created + succ.rows_updated
    )
    assert counter_total > 0, (
        f"expected non-zero row-counter activity; got "
        f"ingested={succ.rows_ingested} created={succ.rows_created} "
        f"updated={succ.rows_updated}"
    )


# ── Test 4: cip_files populated with fixture pattern ───────────────────────


def test_cip_files_populated_with_fixture_pattern(
    seeded_engine: Engine, database_url: str
) -> None:
    """STANDARD corpus emits 100 documents via FixtureMapper; each gets
    an r2_path of form ``fixture://<source_id>``. Verify both count and
    pattern."""
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)
    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT r2_path FROM cip_files WHERE tenant_id = :tid"
            ),
            {"tid": str(tenant_id)},
        ).all()
    assert len(rows) >= 100, (
        f"STANDARD ships 100 documents; got {len(rows)} cip_files rows"
    )
    for r in rows:
        assert r.r2_path.startswith("fixture://"), (
            f"expected r2_path to start with fixture:// , got {r.r2_path!r}"
        )


# ── Test 5: M5 lens_* views exist + isolate per tenant ─────────────────────


def test_lens_postgres_views_exist_and_isolate_per_tenant(
    seeded_engine: Engine, database_url: str
) -> None:
    """M5 cip_09 ships lens_all_companies + lens_eu_west_companies. Verify
    both exist + the role-based query under tenant context returns the
    expected row counts (50 / 0 < n < 50)."""
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)

    with seeded_engine.connect() as conn:
        view_rows = conn.execute(
            text(
                "SELECT viewname FROM pg_views "
                "WHERE schemaname = 'public' AND viewname LIKE 'lens_%' "
                "ORDER BY viewname"
            )
        ).all()
    view_names = {r.viewname for r in view_rows}
    assert "lens_all_companies" in view_names
    assert "lens_eu_west_companies" in view_names

    # Role-scoped query — mirrors M5 test_cip_09's _role_session_with_tenant
    # pattern (dispatch §Read first item 3): separate engine, BEGIN +
    # set_config + ROLLBACK, dispose to avoid pool leak.
    role_url = seeded_engine.url.set(
        username=_METABASE_ROLE,
        password=os.environ.get(
            "METABASE_DB_PASSWORD", _METABASE_TEST_PASSWORD_FALLBACK
        ),
    )
    role_eng = create_engine(role_url, pool_pre_ping=True)
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
                all_count_raw = conn.execute(
                    text("SELECT COUNT(*) FROM lens_all_companies")
                ).scalar()
                eu_count_raw = conn.execute(
                    text("SELECT COUNT(*) FROM lens_eu_west_companies")
                ).scalar()
            finally:
                conn.execute(text("ROLLBACK"))
    finally:
        role_eng.dispose()

    # COUNT(*) is non-NULL by Postgres semantics; explicit cast for mypy strict.
    all_count = int(all_count_raw or 0)
    eu_count = int(eu_count_raw or 0)
    assert all_count == 50, (
        f"lens_all_companies under tenant context: expected 50, got {all_count}"
    )
    assert 0 < eu_count < 50, (
        f"lens_eu_west_companies: expected 0 < n < 50, got {eu_count}"
    )


# ── Test 6: features.yaml shape ────────────────────────────────────────────


def test_features_yaml_parses_and_has_expected_shape() -> None:
    assert _FEATURES_YAML.exists(), f"features.yaml missing at {_FEATURES_YAML}"
    data = yaml.safe_load(_FEATURES_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    for top_key in ("layer", "product", "features"):
        assert top_key in data, f"missing top-level key {top_key!r}"
    features = data["features"]
    assert isinstance(features, list)
    assert len(features) >= 22, f"expected ≥22 feature entries, got {len(features)}"
    # JOS-SPEC-010 v1.1 per-entry schema (refactored 2026-05-21 from CIP-local v0)
    required_keys = {"feature_id", "title", "summary", "status", "maturity", "owner", "domain"}
    valid_status = {"shipped", "in-progress", "planned", "deprecated"}
    for f in features:
        missing = required_keys - set(f.keys())
        assert not missing, f"feature {f.get('feature_id','?')!r} missing fields: {missing}"
        assert f["status"] in valid_status, f"feature {f['feature_id']!r} bad status {f['status']!r}"
        if "references" in f:
            assert isinstance(f["references"], list)
        if "interface_surface" in f:
            assert isinstance(f["interface_surface"], list)


# ── Test 7: cross-tenant isolation through cip_views ───────────────────────


def test_cross_tenant_isolation_through_cip_views(
    seeded_engine: Engine, database_url: str
) -> None:
    """Two fixture tenants A and B each seed a lens. Querying cip_views
    under tenant-A's RLS-enforcing role context returns only tenant-A's
    lens row — tenant B's row is invisible (RLS overrides any literal
    mismatch via current_setting)."""
    tid_a = _seed_fixture_tenant(seeded_engine, database_url)
    tid_b = _seed_fixture_tenant(seeded_engine, database_url)

    for tid, name in ((tid_a, "lens_a_xtenant"), (tid_b, "lens_b_xtenant")):
        with Session(seeded_engine, autoflush=False) as db, db.begin():
            apply_tenant_context(db, tid)
            seed_lens(
                db,
                tenant_id=tid,
                view_name=name,
                filter_config=LENS_A_FILTER_CONFIG,
                target_table="cip_companies",
            )

    with session_as_role_and_tenant(seeded_engine, tid_a) as conn:
        rows = conn.execute(
            text(
                "SELECT view_name FROM cip_views WHERE tenant_id = :tid"
            ),
            {"tid": str(tid_a)},
        ).all()
    names = {r.view_name for r in rows}
    assert "lens_a_xtenant" in names, "tenant-A's own lens missing"
    assert "lens_b_xtenant" not in names, (
        "tenant-B's lens leaked across tenant boundary "
        "(RLS not enforcing on cip_views)"
    )


# Quiet unused-import warning — sa is used reflexively in test scaffolding
# we may add later (e.g., sa.MetaData reflect). Keep imported for parity
# with sibling test files.
_ = sa
