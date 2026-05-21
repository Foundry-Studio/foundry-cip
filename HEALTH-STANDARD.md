---
doc_type: health-standard
elaborates_slot: capability
declared_thing: foundry-cip
declared_thing_kind: product-internal
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
audience: [dev, operator, agent]
diataxis_type: reference
connects_to:
  - GUARANTEES.md
  - capabilities.yaml
  - features.yaml
---

# Health Standard — Foundry Client Intelligence Platform (CIP)

> Per JOS-S23. Mechanical verification per `G-NN` in [GUARANTEES.md](GUARANTEES.md). Each `H-NN` is an executable test.

## Health checks (production-grade)

### H-01 — Conformance harness passes for every connector

**Verifies:** G-01 (Protocol contract).

**Check:** `pytest tests/fixtures/connector_conformance/` — runs the 8-test suite against every CIPConnector. Pass: 8/8.

**Where:** CI on every push.

### H-02 — RLS smoke tests pass + cross-tenant probe blocked

**Verifies:** G-02 (tenant isolation).

**Check 1:** `pytest tests/migrations/test_rls_cip_*.py` — 9 RLS smoke tests. Pass: 9/9.

**Check 2:** Query `lens_all_companies` as `cip_metabase_role` while `app.current_tenant` set to TENANT_B; while the data is TENANT_A's. Pass: 0 rows returned.

**Where:** CI on every push + manual M8 fixture-tenant gate probe.

### H-03 — SCD differ regression test

**Verifies:** G-03 (bitemporal SCD-2).

**Check:** `pytest tests/integration_mesh/test_scd_differ.py` — exercise insert/update/delete cycles and verify history rows have correct valid_from/valid_to + transaction_time.

**Where:** CI on every push.

### H-04 — Connector backfill_history test

**Verifies:** G-04 (mandatory historical backfill, D-159).

**Check:** `pytest tests/connectors/test_hubspot.py::test_backfill_history_yields_historical_records` + same for Zendesk. Pass: both connectors yield ≥1 HistoricalRecord per entity type.

**Where:** CI on every push.

### H-05 — Schema provenance audit

**Verifies:** G-05 (9-column provenance).

**Check:** SQL query against `information_schema.columns` — every `cip_*` table (non-history non-registry) carries all 9 provenance columns: tenant_id, client_id, source_connector, source_id, ingested_at, refreshed_at, previous_version_id, ingestion_batch_id, authority.

**Where:** Smoke test in `tests/migrations/test_schema_provenance.py` (to add if missing).

### H-06 — Lens authoring is INSERT-only

**Verifies:** G-06 (P-21 falsifiability).

**Check:** Add a new lens by INSERTing into `cip_views` only. Verify the lens returns expected rows without any code change. Pass: query succeeds without restart.

**Where:** Manual integration test; documented in `docs/LENS-AUTHORING-GUIDE.md`.

### H-07 — Metabase grant matrix enforces P-21

**Verifies:** G-07 (P-21 structural enforcement).

**Check:** `pytest tests/integration_mesh/test_cip_09_metabase_role_views.py` — 13 tests covering: grants exist, REVOKE on cip_* succeeds, lens_* SELECT works, raw cip_* SELECT raises `permission denied`.

**Where:** CI on every push.

### H-08 — Determinism harness golden-file match

**Verifies:** G-08 (corpus + lens determinism).

**Check:** `pytest tests/integration_mesh/test_fixture_corpus_determinism.py` + `test_lens_golden_snapshots.py`. SHA-256 over canonicalized JSON output. Pass: matches committed snapshot.

**Where:** CI on every push. Drift fails loud; intentional bumps require commit-explained intent.

### H-09 — CI matrix passes across Python versions

**Verifies:** G-09 (library shape).

**Check:** `.github/workflows/test.yml` matrix runs `pytest` against Python 3.11 + 3.12 + 3.13 + 3.14 with `requirements-dev.txt` constraints.

**Where:** CI on every push.

### H-10 — Trailer-check workflow blocks bad commits

**Verifies:** G-10 (Local-Verified discipline).

**Check:** `.github/workflows/test.yml::trailer-check` job inspects HEAD commit message. Fails if neither `Local-Verified:` nor `Local-Verify-Bypass:` present.

**Where:** CI on every push to master.

## Health checks (in-progress / future)

### H-11 — Wayward end-to-end round-trip

**Verifies:** G-11 (Phase 2).

**Check:** Once Wayward goes live: schedule a daily smoke that runs Zendesk + HubSpot pull, verifies cip_sync_runs success status, then verifies push to Chatwoot succeeded with expected row count.

**Status:** Pending Phase 2 kickoff (awaiting Tim's "go" for first real-tenant Wayward ingestion).

### H-12 — Authority model TSP thresholds

**Verifies:** G-12 (Phase 2.5).

**Check:** Authored alongside the cip_write API.

**Status:** Pending Phase 2.5.

### H-13 — Cross-tenant grants runtime test

**Verifies:** G-13 (Phase 3).

**Check:** Tenant A grants Tenant B access to specific lens views per cip_09 schema; verify B can query A's data through the grant; verify B cannot query A's data outside the grant.

**Status:** Pending Phase 3.

## Continuous health surfaces

| Surface | What it checks |
|---|---|
| **GitHub Actions matrix** | All H-## CI-bound checks on every push |
| **44/44 connector tests** | Current pass count (per CHANGELOG 2026-05-14 bug-bash) |
| **mypy --strict on cip/** | Type-safety regression |
| **ruff** | Style + lint |
| **uv pip compile --check** | Lockfile-freshness gate |
| **pre-commit hooks** | gitleaks (secrets) + ruff + mypy strict |

## What's NOT verified mechanically (yet)

- Whether a real-world tenant onboarding actually takes <1 hour (target per VISION; no SLO)
- Whether the connector authoring guide is sufficient for an external engineer (no calibration)
- Whether the chatbot (Phase 5) produces grounded + cited responses (no harness yet)

## Maintenance

- **Cadence:** review every 90 days alongside GUARANTEES.md.
- **When a check breaks:** open a CIP project PM task tagged `health-check-stale`.
- **When a guarantee changes:** the corresponding H-## must change with it; never let G-## and H-## drift.
