# Changelog

All notable changes to foundry-cip are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and SemVer.

## Versioning policy

- **MAJOR** (e.g., 1.0.0 → 2.0.0): Breaking change to the Protocol contract (`CIPConnector` / `CIPMapper` shape), a deletion of an existing `cip_*` migration semantic, or a removal of public API.
- **MINOR** (e.g., 0.1.0 → 0.2.0): Backward-compatible addition — new optional Protocol method, new migration appended to the chain, new public-API function.
- **PATCH** (e.g., 0.1.0 → 0.1.1): Backward-compatible bug fix or doc update.

Pre-1.0.0 (current): minor versions may include breaking changes per SemVer pre-release rules. Treat 0.x.0 as potentially-breaking; 0.x.y as bugfix-only. Pin to a specific git SHA in production until 1.0.0.

## [Unreleased]

### Added
- M2 framework code (executes in foundry-cip per `docs/vision/PHASE-1-PLAN.md` after M2 plan v4 hand-off).
- **M5 (Pillar 5 — Consumption Surfaces lights up, 2026-05-09):** `cip_09_metabase_role_views` migration provisioning `cip_metabase_role` (NOSUPERUSER NOBYPASSRLS LOGIN) + two hardcoded fixture lens views (`lens_all_companies`, `lens_eu_west_companies`) matching the M4 Lens-A and Lens-B filter configs. P-21 Multi-Lens-by-Default is structurally enforced via Postgres grant matrix (REVOKE on `cip_*` tables; GRANT only on `lens_*` views). Tenant scoping in views via explicit `WHERE tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid`. 13 tests at `tests/integration_mesh/test_cip_09_metabase_role_views.py` (12 from M5 plan v3 §4.2 + 1 sentinel-sanity bonus). MINOR bump per SemVer policy.
- **M6 (Discoverability registry completeness pass, 2026-05-10):** verification tests covering `cip_connector_property_registry` (≥22 rows + 5 active object_types), `cip_views` (M4 lens row shape + M4 Δ2 sub-namespaced source_connector pattern), `cip_sync_runs` (success status + non-zero counters), `cip_files` (FixtureMapper r2_path pattern), M5 `lens_*` Postgres views (existence + per-tenant isolation through cip_metabase_role), `features.yaml` (JOS-PM v0 schema conformance), and cross-tenant isolation through `cip_views` (RLS enforcement). 7 tests at `tests/integration_mesh/test_discoverability_completeness.py`.
- **M6:** `docs/FOUR-ACCESS-PATHS.md` promoted skeleton → draft (M0 → M6). §§1-9 populated per `docs/_TEMPLATE.md` schema: each Path section includes definition, working SQL/pseudocode, fixture row counts/patterns, error modes, downstream service mapping (Phase 1 raw → Phase 4 wrapped), and cross-links.
- **M7 (Four Access Paths Validation + Doc Suite Harden, 2026-05-11):** 8 end-to-end Path-validation tests at `tests/integration_mesh/test_four_access_paths_validation.py` (6 PASS + 2 SKIP-with-explanatory-message). Path 1 covered via two complementary surfaces (Python-side lens engine `lens_query_for_table` AND production-shape Postgres `lens_*` views queried as `cip_metabase_role`). Path 4 covered via `cip_files` r2_path-pattern + cross-path composition. Path 2 (knowledge vector+BM25) and Path 3 (graph) are monorepo platform-service scope; SKIP with pointers. PHASE-1-PLAN.md M7 exit criterion "cold-start agent enumerates Phase 1 artifacts via generic registries" exercised by `test_discoverability_registries_enumerate_all_phase_1_artifacts`. New registry-vs-reality check (`test_features_yaml_lists_all_deployed_capabilities`) asserts every `status: available` feature's `path_to_more` resolves at HEAD.
- **M7:** `docs/PHASE-1-TO-PHASE-2-HANDOFF.md` promoted skeleton → draft (M0 → M7). 10 sections populated: code final-state, what's-green evidence map, docs state-by-doc, PM state, known-unknowns carried into Phase 2, Phase 2 entry criteria, Phase 1 calibration insights (drafts-against-memory pattern, Option Y dispatch pattern, test placement reconciliation, library-shape FND-S13, stop-and-escalate discipline), Phase 2 M1 first-action brief, delta against connector-authoring guide, non-goals. Atlas finalizes on M8.
- **M7:** Targeted factual corrections in 6 draft docs across the doc-suite read-through (CONNECTOR-AUTHORING-GUIDE.md §6 + §9 M5/M6 markers; MIGRATION-RUNBOOK.md §1 + §8 cip_09 placement; RLS-SET-LOCAL-OPERATOR-GUIDE.md §6 cross-tenant probe populated + §7 cip_09→cip_10 renumber; LENS-AUTHORING-GUIDE.md §Related M6 row + §7 operator-extensibility forward-ref; METABASE-OPERATOR-GUIDE.md §Related M6 row + §3 forward note + §9 commit-watcher attribution; SYNC-ORCHESTRATOR-GUIDE.md §Related M5 row + §7 knowledge-hook status). All corrections reflect that M5 was the Metabase platform service (not Knowledge+Graph wiring) and M6 was discoverability-verification (not auto-generator commit-watcher / operator extensibility).

### Changed
- pyproject.toml: added `pyyaml>=6.0` to dev extras (M6 verification dependency for `features.yaml` shape check via `yaml.safe_load`).
- requirements-dev.txt: regenerated via `uv pip compile pyproject.toml --extra dev --extra fixture --universal --python-version 3.12 -o requirements-dev.txt` (FND-S13 lockfile-freshness gate).
- **M7 Δ1 — features.yaml fixes** (rolled into M7 per dispatch's small-fix protocol; ≤300 LOC, single-purpose): `metabase-platform-service` row flipped from `status: planned` + placeholder path_to_more to `status: available` pointing at `docs/METABASE-OPERATOR-GUIDE.md` (M5 shipped 2026-05-09); `scd-history` path_to_more typo `cip/integration_mesh/scd.py` → `cip/integration_mesh/scd_differ.py`; `connector-framework` and `fixture-connector` path_to_more re-targeted from non-existent README files to actual deployed entry points (`orchestrator.py` and `connector.py` respectively).
- **M7 Δ2 — FOUR-ACCESS-PATHS.md correction:** §4 Path 4 example SQL used non-existent column `cip_file_id`; fixed to `id` (the actual PK column on `cip_files` per `cip_04_files.py` migration). M6-introduced typo caught by M7's M7 stricter Path 4 test.

## [0.1.0] - 2026-04-XX

### Added
- Initial release after extraction from Foundry-Agent-System monorepo.
- 8 Alembic migrations (`cip_01_clients` through `cip_08_tickets_and_registry`) creating the CIP schema with RLS policies.
- 9 RLS smoke tests (`tests/migrations/test_rls_cip_*.py`) and their CIP-specific `conftest.py`.
- Vision, architecture, and 10 Phase-1 runbooks under `docs/`.
- 4 venture-onboarding stub runbooks (DEPLOYING, EXPORTING, STANDALONE, TROUBLESHOOTING).
- Apache 2.0 LICENSE.
- pyproject.toml declaring `foundry-cip` as the importable package.
- `migrations/env.py` with `version_table = "alembic_version_cip"` (per D-146 multi-repo Alembic model).
- GitHub Actions CI: pytest + mypy + ruff against postgres:16-alpine.
- Repo metadata: CODEOWNERS, dependabot.yml, SECURITY.md, CodeQL workflow.

### Notes
- Per D-146, foundry-cip is the code repo; the data layer (cip_* tables) continues to live in Foundry's shared Postgres until Phase 8 ("Scale & Extract").
- Pre-extraction history (commits before 2026-04-20 when CIP code lived under `WORKBENCH/tim/research/client-intelligence-platform/`) is not preserved in foundry-cip. The cip-extraction-point tag in Foundry-Agent-System marks the split point.
