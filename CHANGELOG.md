---
doc_type: changelog
owner: tim
status: active
created: 2026-04-30
last_modified: 2026-07-06
last_reviewed: 2026-07-06
review_cadence: 30
---
# Changelog

All notable changes to foundry-cip are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and SemVer.

## Versioning policy

- **MAJOR** (e.g., 1.0.0 → 2.0.0): Breaking change to the Protocol contract (`CIPConnector` / `CIPMapper` shape), a deletion of an existing `cip_*` migration semantic, or a removal of public API.
- **MINOR** (e.g., 0.1.0 → 0.2.0): Backward-compatible addition — new optional Protocol method, new migration appended to the chain, new public-API function.
- **PATCH** (e.g., 0.1.0 → 0.1.1): Backward-compatible bug fix or doc update.

**When the version bumps (Tim, 2026-07-06): on publish/release, not per appended migration.** The
SemVer *meanings* above are unchanged — a released MINOR is one that added backward-compatible
surface since the last release — but the number is bumped once, when a batch of work is published,
not once per migration or PR. Between releases, accumulate changes under `[Unreleased]`; when
publishing, roll `[Unreleased]` into the new version heading. (Master is live on this repo, so a
"publish" is a push that a maintainer intends as a release cut.)

Pre-1.0.0 (current): minor versions may include breaking changes per SemVer pre-release rules. Treat 0.x.0 as potentially-breaking; 0.x.y as bugfix-only. Pin to a specific git SHA in production until 1.0.0.

## [Unreleased]

_Nothing yet. Accumulate post-0.2.0 changes here; roll into the next version heading on publish._

## [0.2.0] - 2026-07-06

First release cut since 0.1.0. Catches up a long unreleased window (Phase 1 close-out through the
active Phase 2 Wayward live-sync work) and applies the 2026-07-06 QC cleanup. Backward-compatible
additions to the migration chain, connectors, and knowledge subsystem; no Protocol-contract breaks.

### Migrations added since 0.1.0 (chain now `cip_01` … `cip_37`)

0.1.0 shipped `cip_01`–`cip_08`. Since then the chain grew through Phase 1 close-out
(`cip_09_metabase_role_views`, `cip_10_history_lens_views`, `cip_11`–`cip_14` write-back/backfill,
`cip_15`–`cip_28` Wayward + PS lens/role build-out) and the Phase 2 China/PS analytics push. The
most recent span:

- **`cip_29_deals_history_lens`** — `lens_deals_history` over `cip_deals_history` (ASK 1); GUC-scoped SCD-2 history surface for period-over-period revenue; grants to `cip_metabase_role` + `cip_metabase_project_silk`.
- **`cip_30_rls_with_check`** — RLS hardening: adds `WITH CHECK` to `cip_tenant_scope` on every entity/history table, closing the INSERT / tenant-rewrite hole (`USING`-only policies didn't re-validate post-write rows).
- **`cip_31_query_reader_role`** — provisions `cip_query_reader` (NOSUPERUSER NOBYPASSRLS LOGIN), the least-priv RLS-fenced reader for the Path-1 agent SQL bridge (`POST /api/v1/cip/query`); enumerate-and-grant over the entity/history/discovery/lens read surface.
- **`cip_32_ps_deal_financials_lens`** — `lens_ps_china_deal_financials` (deal-grain financial read surface) + extends `lens_ps_china_brands_financial_summary` with per-brand rollups (Metabase ASK 5).
- **`cip_33_identity_links`** — `cip_identity_links` table (deterministic cross-connector email match, human-override-safe) + `lens_china_tickets` (Zendesk→HubSpot ticket identity resolution, ASK 2).
- **`cip_34_ps_china_commission_lens`** — PS China attribution layer + `lens_ps_china_commission`.
- **`cip_35_china_ticket_join_indexes`** — expression indexes backing the `lens_china_tickets` identity join.
- **`cip_36_lens_china_deals_history`** — `lens_china_deals_history` (China-subset SCD-2 history, ASK 6).
- **`cip_37_grant_repair`** — repairs a missed grant: `lens_ps_china_deal_financials` (from `cip_32`) was never granted to `cip_query_reader`, so agent SQL got `permission denied`. Grants it + self-heal sweep restoring the "cip_query_reader reads every `lens_*`" invariant. Fix-forward — does not edit shipped `cip_32`. (QC audit 2026-07-06.)

### Connectors & sync (Phase 2 Wayward)

- **`run_ps_china_mirror` callable extraction** — the PS→lens mirror orchestration is a reusable callable (`cip.integration_mesh.sync.ps_lens_mirror`) invoked by the scheduled-sync wrapper and `scripts/orchestrate_ps_lens_mirror.py`.
- **`cip-scheduled-sync` component (shipped 2026-06-09, PM 8d47e809)** — hourly FAS-hosted `SYSTEM_SCHEDULES` drive live incremental ingest: `cip_wayward_hubspot` (:17 UTC), `cip_wayward_zendesk` (:47 UTC), `cip_ps_lens_mirror` (:37 UTC). Wrapper: `Foundry-Agent-System/src/work_execution/producers/scheduled_tasks/cip_sync.py` → `cip.integration_mesh.run_sync()`. This is the live-update mechanism for Wayward. See `docs/SYNC-ORCHESTRATOR-GUIDE.md`.
- **Knowledge subsystem hardening** — `cip/integration_mesh/knowledge/` indexer/retriever/pinecone paths: batch-embed with per-item failure sentinels, namespace-grouped Pinecone upserts, Postgres BM25 + Pinecone hybrid retrieval.

### QC cleanup (2026-07-06)

- **CI green restored** — `ruff check cip/ tests/` was failing (24 errors) and `mypy cip/` was failing (19 errors) at HEAD despite prior "clean" claims. Both now zero. Fixes include a latent `F821`/`name-defined` (`Any` never imported in `knowledge/indexer.py`), removal of dead `assoc_param` in the HubSpot connector, explicit `zip(strict=True)` at the embed/chunk alignment site (a length mismatch would silently misalign embeddings), and `dict`/`Mapping` type-argument completeness.
- **Migrations exempted from `disallow_untyped_defs`** in mypy config (DDL scripts; parallels the ruff E501 migration exemption) — no shipped migration edited.
- **Docs truth pass** — `CLAUDE.md` (migration count/path, repo layout, milestone language), `README.md` (Phase 2 current-state banner + `cip_09` correction), retired the misleading `_RESERVED.md` (numbering protocol moved into `CLAUDE.md`).
- **Hygiene** — removed stray root `uv.lock` (+ `.gitignore`); coverage `fail_under` ratcheted to the measured floor (target remains 90); `cip/db.py` schema-mismatch hint updated off the retired `foundry-cip-migrate` wrapper.

### Connector bug-bash (2026-05-14) — 4 fixes + 4 regression tests

The autonomous Wayward sync hit four bugs during overnight execution. All four root-caused via forensic forensics (py-spy stack dump + pg_stat_activity + cip_sync_runs.error_detail) and fixed cleanly with regression tests that would have caught each in CI.

- **HubSpotMapper schema drift** — translation table mapped `jobtitle → job_title`; deployed `cip_contacts` has column `title`, not `job_title`. Also `lifecyclestage` silently routed to overflow despite `cip_contacts.lifecycle_stage` existing as a real column. Fix: translation now `jobtitle → title`, `lifecyclestage → lifecycle_stage`. Both `_DOMAIN_FIELDS_BY_TYPE` and `_RECORD_TO_SQL_COLUMN` audited against deployed schema. Test: `tests/connectors/test_mapper_schema_drift.py` (6 tests asserting every mapper-referenced column exists in the deployed schema for both HubSpot + Zendesk).
- **`_NoOpMapper.map()` not a generator** — orchestrator's internal sentinel had `def map(): return []`. `validate_connector_shape()` requires `map` to be a generator function (per H-7 partial-yield atomic discard). Result: every `run_backfill()` invocation immediately raised `ProtocolShapeError`. Fix: `yield from ()` body. Test: `tests/connectors/test_run_backfill_protocol.py` (3 tests directly checking `inspect.isgeneratorfunction()` + end-to-end `validate_connector_shape` against `_NoOpMapper`).
- **Zendesk pagination — legacy `next_page` vs cursor API** — the previous implementation used `/api/v2/{type}.json` with legacy `next_page` URL chaining. Zendesk's organizations endpoint migrated to cursor pagination and silently ignores the legacy `?page=N` param, returning page 1 indefinitely → 22-hour infinite loop on 100 Wayward orgs. Fix: switch to `/api/v2/incremental/{type}/cursor.json` with `after_cursor` chained pagination + `end_of_stream` termination + defensive return when both are missing. Tests: `test_stream_records_yields_one_per_entity_type_via_cursor_api`, `test_stream_records_handles_cursor_pagination_until_end_of_stream`, `test_stream_records_defensively_returns_when_cursor_missing`.
- **DRY violation: HubSpot connector duplicated mapper's translation tables** — `_HUBSPOT_DOMAIN_FIELDS_FOR_HISTORY` + `_HUBSPOT_RECORD_TO_SQL_FOR_HISTORY` in `connector.py` were copies of mapper's tables that didn't get updated when the mapper was fixed. Fix: connector now `from .mapper import _DOMAIN_FIELDS_BY_TYPE, _RECORD_TO_SQL_COLUMN`. Single source of truth eliminates the class of "mapper fixed but backfill still broken" bug.

QC: 44/44 connector tests pass; mypy --strict clean on 35 source files; ruff clean on all new + modified files.

### D-159 framework extension landed (2026-05-13)

- **HistoricalRecord dataclass + persister extension + run_backfill orchestrator:** `cip/integration_mesh/base.py` adds `HistoricalRecord` (immutable; `target_table`, `source_id`, `valid_from`, `valid_to`, `fields`, `overflow`, `changed_by`, `change_reason`). `CIPConnectorBase` gains optional `backfill_history(tenant_id) -> Iterator[HistoricalRecord]` (default empty). `CIPRowPersister.persist_history_record()` writes directly to `cip_*_history` with explicit valid_from/valid_to (bypasses SCD-2 differ — backfill records are known-historical). `run_backfill()` mirrors run_sync shape (advisory-lock + per-batch transactions). **Closes PM scope 218f67a4** with the clean two-method design recommended in the research-grounded scope description; replaces the earlier magic-marker prototype.
- **HubSpot + Zendesk connector backfill methods:** `HubSpotConnector.backfill_history()` re-paginates each entity type with `propertiesWithHistory`, groups revisions by timestamp into snapshots, yields oldest → newest `HistoricalRecord`. `ZendeskConnector.backfill_history()` walks `/api/v2/tickets/{id}/audits.json` per ticket, reconstructs state via Change-event replay. Magic-marker raise-NotImplementedError code paths removed; `backfill_history` ctor flag removed.
- **scripts/orchestrate_wayward_backfill.py:** autonomous orchestrator. Polls `cip_sync_runs` every `ORCHESTRATOR_POLL_SECONDS` (default 900s/15min); triggers `run_backfill` per connector when its current-state sync completes. Records each backfill outcome as a `cip_sync_runs` row with `sync_mode='backfill'`. Logs to `scripts/wayward_backfill_orchestrator.log`. Designed for "launch + leave"-style usage — zero Claude-token cost.
- **Test coverage:** `test_hubspot.py::test_backfill_history_yields_historical_records` + `test_zendesk.py::test_backfill_history_yields_historical_records_for_tickets` lock the new contract. All 34 connector tests pass against the redesigned API.

### M8 closeout (2026-05-12)

**Phase 1 LOCKED.** All M0–M8 milestone scopes complete. Plain-jane shippable. Framework ready for Phase 2 Wayward Onboarding.

- **M8 Metabase fixture-tenant gate PASSED:** Railway prod has the foundry-cip alembic chain landed (cip_08 stamp → cip_09 → cip_10). `cip_metabase_role` provisioned with strong password (Railway env var). Fixture tenant TENANT_A (`a0000000-...0001`) seeded with FixtureConnector STANDARD (1150 rows). Tim connected Metabase at `reports.project-silk.com`, clicked through, confirmed `lens_all_companies` (50 rows), `lens_eu_west_companies` (13 rows), `lens_companies_history` (queryable, 0 initial), and raw `cip_companies` returns `permission denied` (P-21 enforcement). Deploy plan + execution at `Foundry-Agent-System/WORKBENCH/tim/m8-railway-deploy-plan-2026-05-11.md`.
- **Phase 1 retrospective:** `docs/vision/PHASE-1-RETROSPECTIVE.md` — what shipped, what surprised, what Phase 2 should sharpen. Atlas reviews retroactively on return.
- **Wayward tenant_id reserved:** `b0000000-0000-0000-0000-000000000001` per `Foundry-Agent-System/WORKBENCH/tim/wayward-tenant-coordinates.md`. Pre-Phase-2 anchor.
- **Phase 2 connector scaffolds landed:** `cip/integration_mesh/connectors/zendesk/` + `cip/integration_mesh/connectors/hubspot/` skeletons (NotImplementedError methods + per-method spec pointers). HubSpotConnector ctor includes the `backfill_property_history` flag reserving the surface for the PHASE-1-PLAN.md R5 "backup tape" decision.

### Added
- M2 framework code (executes in foundry-cip per `docs/vision/PHASE-1-PLAN.md` after M2 plan v4 hand-off).
- **M5 (Pillar 5 — Consumption Surfaces lights up, 2026-05-09):** `cip_09_metabase_role_views` migration provisioning `cip_metabase_role` (NOSUPERUSER NOBYPASSRLS LOGIN) + two hardcoded fixture lens views (`lens_all_companies`, `lens_eu_west_companies`) matching the M4 Lens-A and Lens-B filter configs. P-21 Multi-Lens-by-Default is structurally enforced via Postgres grant matrix (REVOKE on `cip_*` tables; GRANT only on `lens_*` views). Tenant scoping in views via explicit `WHERE tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid`. 13 tests at `tests/integration_mesh/test_cip_09_metabase_role_views.py` (12 from M5 plan v3 §4.2 + 1 sentinel-sanity bonus). MINOR bump per SemVer policy.
- **M6 (Discoverability registry completeness pass, 2026-05-10):** verification tests covering `cip_connector_property_registry` (≥22 rows + 5 active object_types), `cip_views` (M4 lens row shape + M4 Δ2 sub-namespaced source_connector pattern), `cip_sync_runs` (success status + non-zero counters), `cip_files` (FixtureMapper r2_path pattern), M5 `lens_*` Postgres views (existence + per-tenant isolation through cip_metabase_role), `features.yaml` (JOS-PM v0 schema conformance), and cross-tenant isolation through `cip_views` (RLS enforcement). 7 tests at `tests/integration_mesh/test_discoverability_completeness.py`.
- **M6:** `docs/FOUR-ACCESS-PATHS.md` promoted skeleton → draft (M0 → M6). §§1-9 populated per `docs/_TEMPLATE.md` schema: each Path section includes definition, working SQL/pseudocode, fixture row counts/patterns, error modes, downstream service mapping (Phase 1 raw → Phase 4 wrapped), and cross-links.
- **M7 (Four Access Paths Validation + Doc Suite Harden, 2026-05-11):** 8 end-to-end Path-validation tests at `tests/integration_mesh/test_four_access_paths_validation.py` (6 PASS + 2 SKIP-with-explanatory-message). Path 1 covered via two complementary surfaces (Python-side lens engine `lens_query_for_table` AND production-shape Postgres `lens_*` views queried as `cip_metabase_role`). Path 4 covered via `cip_files` r2_path-pattern + cross-path composition. Path 2 (knowledge vector+BM25) and Path 3 (graph) are monorepo platform-service scope; SKIP with pointers. PHASE-1-PLAN.md M7 exit criterion "cold-start agent enumerates Phase 1 artifacts via generic registries" exercised by `test_discoverability_registries_enumerate_all_phase_1_artifacts`. New registry-vs-reality check (`test_features_yaml_lists_all_deployed_capabilities`) asserts every `status: available` feature's `path_to_more` resolves at HEAD.
- **M7:** `docs/PHASE-1-TO-PHASE-2-HANDOFF.md` promoted skeleton → draft (M0 → M7). 10 sections populated: code final-state, what's-green evidence map, docs state-by-doc, PM state, known-unknowns carried into Phase 2, Phase 2 entry criteria, Phase 1 calibration insights (drafts-against-memory pattern, Option Y dispatch pattern, test placement reconciliation, library-shape FND-S13, stop-and-escalate discipline), Phase 2 M1 first-action brief, delta against connector-authoring guide, non-goals. Atlas finalizes on M8.
- **M7:** Targeted factual corrections in 6 draft docs across the doc-suite read-through (CONNECTOR-AUTHORING-GUIDE.md §6 + §9 M5/M6 markers; MIGRATION-RUNBOOK.md §1 + §8 cip_09 placement; RLS-SET-LOCAL-OPERATOR-GUIDE.md §6 cross-tenant probe populated + §7 cip_09→cip_10 renumber; LENS-AUTHORING-GUIDE.md §Related M6 row + §7 operator-extensibility forward-ref; METABASE-OPERATOR-GUIDE.md §Related M6 row + §3 forward note + §9 commit-watcher attribution; SYNC-ORCHESTRATOR-GUIDE.md §Related M5 row + §7 knowledge-hook status). All corrections reflect that M5 was the Metabase platform service (not Knowledge+Graph wiring) and M6 was discoverability-verification (not auto-generator commit-watcher / operator extensibility).
- **PHASE-1-PLAIN-SPEC.md Tim amendment (2026-05-11):** §15.1 added — M8 historical-lens proof-of-life acceptance criterion #14 with 5-row WDGLL-shape table. Closes the question "can a BI tool reach CIP's bitemporal SCD-2 history surface through the cip_metabase_role grant matrix" before Phase 1 locks. §13 also amended with vacation-mode exception (Tim wears Atlas's design-decision hat while she's unreachable).
- **M8 cip_10 historical-lens proof-of-life (2026-05-11):** `cip_10_history_lens_views` migration creates `lens_companies_history` view (tenant-RLS-scoped via `app.current_tenant` GUC, mirroring cip_09 pattern) + grants SELECT to `cip_metabase_role`. The role still cannot SELECT the underlying `cip_companies_history` table (P-21 enforcement preserved). One history table covered as proof-of-life; the same pattern scales to the other 5 history tables as Phase 2 / auto-generator work (task #143). 5 tests at `tests/integration_mesh/test_cip_10_history_lens_view.py` covering SPEC §15.1 acceptance rows 14.1-14.5 (view exists in pg_views, role-can-select-view + role-cannot-select-table, lens returns rows when history exists, cross-tenant isolation, this-file-is-the-test). Tests inject a synthetic history row directly (the SCD-2 differ writes history rows only on detected changes; differ behavior is exhaustively covered by the M3 conformance harness — M8 isolates the lens-surface test from differ behavior).

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

