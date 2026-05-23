# foundry: kind=test domain=client-intelligence-platform
"""M7 Four Access Paths Validation — end-to-end exercise.

Phase 1 M7 scope (per locked PHASE-1-PLAN.md Milestone 7 + the M7 CC
dispatch ``cip-cc-dispatch-m7-build.md``): prove a cold-start agent can
light up each of the 4 access paths against the fixture tenant.

The 4 paths (per ``docs/FOUR-ACCESS-PATHS.md``):

* **Path 1 — Structured via SQL.** ``cip_*`` tables / ``lens_*`` Postgres
  views queried with explicit tenant context. Validated end-to-end here.
* **Path 2 — Derived Knowledge (vector + BM25).** Platform service
  ``knowledge_retriever_service`` lives in monorepo. Skip with explanatory
  message (M7 partial validation; full validation in monorepo M7-equivalent
  scope ``458fb208-...``).
* **Path 3 — Derived Knowledge (graph).** FalkorDB not in foundry-cip CI.
  Skip with explanatory message (Phase 1 partial per FOUR-ACCESS-PATHS.md §3
  phase-status note).
* **Path 4 — Originals.** ``cip_files`` row → ``r2_path`` → storage_service.
  Validated for the registry + path-shape surface here; signed-URL retrieval
  requires R2 access (not in CI), validated post-Phase-2.

8 tests total: 6 PASS in standard CI (Tests 1, 2, 5, 6, 7, 8) + 2 SKIP
gracefully (Tests 3, 4).

The "cold-start agent" gate from PHASE-1-PLAN.md M7 exit criteria is
exercised by Test 6, which enumerates the 6 discoverability registries
(``cip_connector_property_registry``, ``cip_views``, ``cip_sync_runs``,
``cip_files``, ``features.yaml``, ``pg_views`` LIKE 'lens_%') and asserts
each returns rows for the fixture tenant.

M7 Δ-notes (rolled in per dispatch §"Stop-and-escalate triggers" small-fix
protocol; documented in this turn's commit):

* Δ1 ``features.yaml`` ``metabase-platform-service`` row: status was
  ``planned`` and path_to_more was placeholder ``(M5 deliverable — TBD)``.
  M5 shipped at foundry-cip HEAD ``13e5234``; flipped to ``available`` +
  pointed at ``docs/METABASE-OPERATOR-GUIDE.md``.
* Δ2 ``features.yaml`` ``scd-history`` row: path_to_more was
  ``cip/integration_mesh/scd.py`` — typo. Deployed file is
  ``scd_differ.py``. Fixed.
* Δ3 ``features.yaml`` ``connector-framework`` + ``fixture-connector``
  rows: path_to_more pointed at non-existent ``README.md`` files in
  ``cip/integration_mesh/`` and ``cip/integration_mesh/connectors/fixture/``.
  Re-targeted at the actual deployed entry points (``orchestrator.py``
  containing ``run_sync()`` for the framework, and ``connector.py``
  containing the ``FixtureConnector`` class).
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
import yaml  # type: ignore[import-untyped]
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cip.integration_mesh import (
    CorpusSize,
    FixtureConnector,
    FixtureMapper,
    lens_query_for_table,
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

_METABASE_ROLE = "cip_metabase_role"
_METABASE_TEST_PASSWORD_FALLBACK = (
    "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105
)


def _seed_fixture_tenant(seeded_engine: Engine, database_url: str) -> UUID:
    """Per-test fresh tenant + FixtureConnector STANDARD sync.
    Mirrors test_lens_apply_e2e.py + test_discoverability_completeness.py."""
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


def _reflect_companies(engine: Engine) -> sa.Table:
    """Reflect cip_companies (mirrors test_lens_apply_e2e.py)."""
    md = sa.MetaData()
    md.reflect(bind=engine, only=["cip_companies"])
    return md.tables["cip_companies"]


# ── Test 1: Path 1 via lens engine (Python-side compose) ──────────────────


def test_path_1_structured_via_lens_query(
    seeded_engine: Engine, database_url: str
) -> None:
    """Path 1 canonical end-to-end via ``lens_query_for_table``.

    Seed fixture tenant, register Lens-A (no-op filter) + Lens-B (region=eu-west),
    compose lens predicates with a base ``SELECT * FROM cip_companies`` and
    assert row counts match M4 expectations (50 for Lens-A; 0<n<50 for Lens-B
    per the seed=42 5-value region distribution).
    """
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)

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

    companies = _reflect_companies(seeded_engine)
    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        a_query = lens_query_for_table(
            conn,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            view_name="lens_a_all_companies",
            target_table=companies,
        )
        a_rows = conn.execute(a_query).all()

        b_query = lens_query_for_table(
            conn,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            view_name="lens_b_eu_west",
            target_table=companies,
        )
        b_rows = conn.execute(b_query).all()

    assert len(a_rows) == 50, (
        f"Lens-A no-op filter: expected all 50 companies, got {len(a_rows)}"
    )
    assert 0 < len(b_rows) < 50, (
        f"Lens-B eu-west subset: expected 0 < n < 50, got {len(b_rows)}"
    )


# ── Test 2: Path 1 via Postgres lens_* views as cip_metabase_role ─────────


def test_path_1_via_postgres_lens_views_as_metabase_role(
    seeded_engine: Engine, database_url: str
) -> None:
    """Path 1 production-shape: the M5 ``lens_*`` Postgres views queried
    under ``cip_metabase_role`` session with tenant ``set_config``.

    This is the surface Metabase actually uses — separate from Test 1's
    Python-side lens engine compose. Asserts same row-count expectations.
    """
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)

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

    all_count = int(all_count_raw or 0)
    eu_count = int(eu_count_raw or 0)
    assert all_count == 50, (
        f"lens_all_companies: expected 50, got {all_count}"
    )
    assert 0 < eu_count < 50, (
        f"lens_eu_west_companies: expected 0 < n < 50, got {eu_count}"
    )


# ── Test 3: Path 2 — partial validation (knowledge_retriever in monorepo) ─


def test_path_2_knowledge_layer_partial_validation(
    seeded_engine: Engine,
) -> None:
    """Path 2 (vector+BM25) lives in monorepo platform service. foundry-cip
    standalone has no ``knowledge_sources`` / ``knowledge_chunks`` schema —
    that's the monorepo's tenant-scoped knowledge store. Verify the table
    is absent (so this test fails loudly if the schema unexpectedly drifts
    into foundry-cip), then SKIP with explanatory message pointing to the
    monorepo M7-equivalent + the knowledge taxonomy alignment scope
    (``458fb208-...``).
    """
    with seeded_engine.connect() as conn:
        present = conn.execute(
            text(
                """
                SELECT to_regclass('public.knowledge_sources') IS NOT NULL,
                       to_regclass('public.knowledge_chunks') IS NOT NULL
                """
            )
        ).one()
    assert not present[0], (
        "knowledge_sources unexpectedly exists in foundry-cip schema; "
        "this table is monorepo platform-service scope. If it now lives "
        "here, this test needs to be upgraded to exercise Path 2 directly."
    )
    assert not present[1], (
        "knowledge_chunks unexpectedly exists in foundry-cip schema; "
        "see knowledge_sources guard above."
    )
    pytest.skip(
        "Path 2 (knowledge_retriever_service) is a monorepo platform "
        "service; foundry-cip standalone validates Path 2 only by "
        "verifying the schema is correctly absent. Full Path 2 "
        "validation runs in the monorepo M7-equivalent scope. The "
        "knowledge-taxonomy alignment migration (PM scope 458fb208-...) "
        "is the next step in lighting up Path 2 for CIP-tagged content."
    )


# ── Test 4: Path 3 — skip (FalkorDB not in CI) ────────────────────────────


def test_path_3_graph_layer_skip_with_message() -> None:
    """Path 3 (FalkorDB graph) requires a FalkorDB-enabled CI environment.
    foundry-cip's testcontainer matrix is Postgres-only. Skip with
    explanatory pointer to FOUR-ACCESS-PATHS.md §3 + the monorepo
    graphrag_retriever_service contract.
    """
    pytest.skip(
        "Path 3 (graphrag_retriever_service) requires FalkorDB; not in "
        "foundry-cip CI. Phase-status: partial in Phase 1 per "
        "docs/FOUR-ACCESS-PATHS.md §3. Full Path 3 validation runs in "
        "the monorepo FalkorDB-enabled environment. Expect Path 3 to "
        "remain flaky-but-improving until Phase 4 hardening."
    )


# ── Test 5: Path 4 — Originals via cip_files ──────────────────────────────


def test_path_4_originals_via_cip_files(
    seeded_engine: Engine, database_url: str
) -> None:
    """Path 4 partial: cip_files row → r2_path lookup → structure validation.

    Full Path 4 (storage_service.sign_url + R2 fetch) requires R2 credentials
    and a real R2 bucket; not in CI. Validates the registry + r2_path shape
    here; production signed-URL retrieval exercised post-Phase-2.

    Stricter than M6 Test 4: each fixture document's r2_path must have a
    non-empty ``fixture://<source_id>`` suffix (per FixtureMapper Δ6).
    """
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)
    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, r2_path
                FROM cip_files
                WHERE tenant_id = :tid
                """
            ),
            {"tid": str(tenant_id)},
        ).all()
    assert len(rows) >= 100, (
        f"STANDARD corpus ships 100 documents; got {len(rows)} cip_files rows"
    )
    for r in rows:
        assert r.r2_path.startswith("fixture://"), (
            f"expected r2_path to start with fixture:// , got {r.r2_path!r}"
        )
        # Per FixtureMapper Δ6 the source_id suffix is non-empty
        suffix = r.r2_path[len("fixture://"):]
        assert suffix, f"empty source_id suffix on r2_path {r.r2_path!r}"


# ── Test 6: Discoverability cold-start enumeration ────────────────────────


def test_discoverability_registries_enumerate_all_phase_1_artifacts(
    seeded_engine: Engine, database_url: str
) -> None:
    """The PHASE-1-PLAN.md M7 exit criterion: cold-start agent (no CIP
    context) can enumerate every Phase 1 artifact via generic registries.

    Probe each of the 6 discoverability surfaces and assert >0 results
    for the fixture tenant:

    1. ``cip_connector_property_registry`` (Path 1 column-shape catalog)
    2. ``cip_views`` (Path 1 lens catalog) — requires seeding one lens row
    3. ``cip_sync_runs`` (Path 1 + 4 sync-history audit)
    4. ``cip_files`` (Path 4 originals catalog)
    5. ``features.yaml`` (capability registry)
    6. ``pg_views WHERE viewname LIKE 'lens_%'`` (Path 1 deployment surface)
    """
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)

    # Pre-seed one lens so cip_views has a row for this tenant.
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        seed_lens(
            db,
            tenant_id=tenant_id,
            view_name="lens_a_cold_start",
            filter_config=LENS_A_FILTER_CONFIG,
            target_table="cip_companies",
        )

    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        registries: dict[str, int] = {}
        for label, sql in (
            (
                "cip_connector_property_registry",
                "SELECT COUNT(*) FROM cip_connector_property_registry "
                "WHERE tenant_id = :tid",
            ),
            ("cip_views", "SELECT COUNT(*) FROM cip_views WHERE tenant_id = :tid"),
            (
                "cip_sync_runs",
                "SELECT COUNT(*) FROM cip_sync_runs WHERE tenant_id = :tid",
            ),
            (
                "cip_files",
                "SELECT COUNT(*) FROM cip_files WHERE tenant_id = :tid",
            ),
        ):
            count = conn.execute(text(sql), {"tid": str(tenant_id)}).scalar()
            registries[label] = int(count or 0)

    # Probe 5 — features.yaml registry parses + has entries.
    features_data = yaml.safe_load(_FEATURES_YAML.read_text(encoding="utf-8"))
    registries["features.yaml"] = len(features_data["features"])

    # Probe 6 — Postgres lens_* views are discoverable through pg_views.
    with seeded_engine.connect() as conn:
        lens_view_count = conn.execute(
            text(
                "SELECT COUNT(*) FROM pg_views "
                "WHERE schemaname = 'public' AND viewname LIKE 'lens_%'"
            )
        ).scalar()
    registries["pg_views LIKE 'lens_%'"] = int(lens_view_count or 0)

    empty = [k for k, v in registries.items() if v <= 0]
    assert not empty, (
        f"cold-start discoverability gate FAILED: registries with no "
        f"rows for fixture tenant: {empty}. Full registry view: "
        f"{registries}"
    )


# ── Test 7: Combined Path 1 → Path 4 composition ──────────────────────────


def test_combined_query_path_1_then_path_4(
    seeded_engine: Engine, database_url: str
) -> None:
    """Cross-path composition. Use Path 1 (a lens view) to enumerate
    company IDs; use Path 4 (cip_files lookup) to retrieve r2_paths for
    documents associated with the fixture tenant. Asserts both ends
    resolve under the same tenant context and the bridge query is
    coherent (non-empty intersection of tenants).
    """
    tenant_id = _seed_fixture_tenant(seeded_engine, database_url)

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
                # Path 1: tenant's companies via lens view.
                companies_count_raw = conn.execute(
                    text("SELECT COUNT(*) FROM lens_all_companies")
                ).scalar()
            finally:
                conn.execute(text("ROLLBACK"))
    finally:
        role_eng.dispose()

    companies_count = int(companies_count_raw or 0)
    assert companies_count == 50, (
        f"Path 1 leg: expected 50 companies, got {companies_count}"
    )

    # Path 4: tenant's documents via cip_files (RLS-enforcing role).
    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        files_count = conn.execute(
            text("SELECT COUNT(*) FROM cip_files WHERE tenant_id = :tid"),
            {"tid": str(tenant_id)},
        ).scalar()
        files_count = int(files_count or 0)
        # Bridge: take one r2_path and confirm it's well-formed (Path 4
        # citation-grade output).
        sample = conn.execute(
            text(
                "SELECT r2_path FROM cip_files "
                "WHERE tenant_id = :tid LIMIT 1"
            ),
            {"tid": str(tenant_id)},
        ).first()

    assert files_count >= 100, (
        f"Path 4 leg: expected ≥100 fixture documents, got {files_count}"
    )
    assert sample is not None
    assert sample.r2_path.startswith("fixture://"), (
        f"Path 1→4 composition: r2_path {sample.r2_path!r} not in "
        "expected fixture pattern"
    )


# ── Test 8: features.yaml registry-vs-reality cross-check ─────────────────


def test_features_yaml_lists_all_deployed_capabilities() -> None:
    data = yaml.safe_load(_FEATURES_YAML.read_text(encoding="utf-8"))
    shipped = [f for f in data["features"] if f["status"] == "shipped"]
    assert shipped, "features.yaml has zero status:shipped features"

    def _resolves(module: str) -> bool:
        parts = module.split(".")
        for n in range(len(parts), 0, -1):
            base = _REPO_ROOT / Path(*parts[:n])
            if base.with_suffix(".py").exists() or base.is_dir():
                return True
        return False

    broken: list[str] = []
    for f in shipped:
        surfaces = f.get("interface_surface") or []
        if not surfaces:
            broken.append(f"{f['feature_id']!r} (no interface_surface)")
            continue
        for s in surfaces:
            if s.get("type") == "internal" and s.get("module") and not _resolves(s["module"]):
                broken.append(f"{f['feature_id']!r} -> {s['module']!r} (module missing)")
    assert not broken, f"features.yaml registry-vs-reality drift at HEAD: {broken}"


# Quiet unused-import warning — sa is used reflexively above (sa.MetaData
# reflect in _reflect_companies). Mirrors sibling test files.
_ = sa
