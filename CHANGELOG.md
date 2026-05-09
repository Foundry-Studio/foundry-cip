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
