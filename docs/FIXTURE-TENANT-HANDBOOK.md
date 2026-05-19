---
id: CIP-SOP-011
uuid: 964ccc7c-b38d-411a-a90f-46b1da6b428d
title: Fixture Tenant Handbook
type: sop
owner: tim
solve_for: Authoritative reference for CIP's deterministic fixture tenant — what it
  is, how it's seeded, byte-identical determinism contract, when to regenerate.
stage_label: adopt
domain: eng
version: '1.0'
created: '2026-04-21'
last_modified: '2026-05-16'
last_reviewed: '2026-05-19'
review_cadence: 90
milestone: Phase-1-M8
---

# Fixture Tenant Handbook

> Canonical reference for the synthetic **fixture tenant** that Phase 1 validates CIP against. Schema, seed, determinism contract, regeneration procedure, and gotchas.

## When to use the fixture tenant

The fixture tenant is the deterministic synthetic data CIP's Phase 1 test surface runs against. Use it whenever you need:

- A reproducible "tenant" without committing real production data to test fixtures.
- A regression target for golden-snapshot tests (lens output, persister output).
- A scaffold for developing a new connector against a known shape before pointing it at real source-system data.
- A CI-friendly seed that doesn't require external credentials.

**Do not use it as a placeholder for a real tenant.** Per PM decision `c575c81c` (canonical-UUID rule), real tenants get real UUIDs registered via [`CIP-SOP-010 TENANT-ONBOARDING-CHECKLIST`](TENANT-ONBOARDING-CHECKLIST.md).

## Identity

- **Tenant UUID:** `a0000000-0000-0000-0000-000000000001` (reserved; constant `TENANT_A`)
  - Defined in: `scripts/seed_railway_prod_fixture.py`, `tests/migrations/conftest.py`
  - Distinct from any production tenant; clearly synthetic by shape
- **No clients inside this tenant.** Fixture rows have `client_id` NULL by design — the fixture tests the tenant-level scoping path, not the client sub-scoping path.

## What gets seeded

`FixtureConnector` + `FixtureMapper` produce a synthetic corpus across 6 record types. Three preset corpus sizes exist:

| Size | companies | contacts | deals | tickets | documents | notes | Total rows | Use for |
|------|-----------|----------|-------|---------|-----------|-------|------------|---------|
| **STANDARD** | 50 | 200 | 300 | 500 | 100 | 0 | **1,150** | Phase 1 regression target; default for `seed_railway_prod_fixture.py` |
| **COMPACT** | 5 | 20 | 30 | 50 | 10 | 0 | 115 | Fast unit tests (10× smaller); local TDD loop |
| **SMOKE** | 0 | 10 | 0 | 0 | 0 | 0 | 10 | MockConnector-equivalent; bare-minimum sanity check |

The `notes` bucket exists for forward-compat with a future `cip_notes` migration but is empty in all three presets (per M3 v2 §2 reconciliation).

## Where rows land

| Record type | `cip_*` table | History sibling |
|-------------|---------------|------------------|
| company     | `cip_companies` | `cip_companies_history` (SCD-2) |
| contact     | `cip_contacts`  | `cip_contacts_history` |
| deal        | `cip_deals` (+ `cip_deal_contact_links`) | `cip_deals_history` |
| ticket      | `cip_tickets`   | `cip_tickets_history` |
| document    | `cip_files`     | (no history) |
| note        | (not persisted; bucket reserved) | — |

Plus one row in `cip_sync_runs` per seed (status `success`, with row counters).

## Determinism contract

> Same Python version + same Faker pin + `PYTHONHASHSEED=0` ⇒ byte-identical corpus across two same-seed instances.

The contract holds **only when all four of the following match**:

1. **Python version.** Different Python versions produce different ordered iteration in some places. The CI matrix runs against Python 3.11/3.12/3.13/3.14; golden snapshots are locked to Python 3.12.
2. **Faker version.** Pinned exact (`faker==X.Y.Z`) in `pyproject.toml`'s `[fixture]` extra. Bumping Faker requires regenerating golden snapshots — handle as a Tier B change per [`CLAUDE.md`](../CLAUDE.md) FND-S14.
3. **`PYTHONHASHSEED=0`.** Set in CI and by the conformance harness. Without it, dict/set iteration order can introduce variance in selection RNG.
4. **Seed value.** Default `seed=42`. The conformance harness `test_fixture_corpus_determinism.py` runs the seeder twice and asserts byte-identical row hashes.

**Two RNGs are used intentionally:** `Faker.seed_instance(int)` for shape generation (names, emails, addresses), and a separate stdlib `random.Random(seed)` for *selection* (FK picks, weighted-choice draws). Splitting them means adding a Faker call upstream doesn't shift downstream selection state, which is critical for byte-identical regression detection.

## Seeding procedure

### Local dev (Postgres at localhost or testcontainers)

```bash
DATABASE_URL=postgresql+psycopg://user:pw@localhost:5432/db \
    python scripts/seed_railway_prod_fixture.py
```

Expected output:
- `cip_companies` for `a0000000-...` has 50 rows
- `cip_contacts` 200, `cip_deals` 300, `cip_tickets` 500, `cip_files` 100
- `cip_sync_runs` has one row with `status='success'`
- SCD-2 history tables have **0 rows on initial seed** (history is written only on detected changes; idempotent re-runs produce no diff)

### Railway prod (requires explicit confirmation)

```bash
DATABASE_URL=$DATABASE_PUBLIC_URL \
    SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \
    python scripts/seed_railway_prod_fixture.py
```

The script aborts unless `SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD` is set when pointed at any non-localhost DB. **This is a safety gate; do not remove it.**

### Idempotency

Re-running against the same tenant detects no changes (SCD-2 differ produces empty diff) and writes no new rows. Safe to re-run; the only side effect is one additional `cip_sync_runs` row with `rows_changed=0`.

## How tests consume the fixture

Three primary entry points:

1. **`tests/integration_mesh/test_fixture_corpus_determinism.py`** — regression guard. Runs the seeder twice into separate testcontainer databases and asserts identical row hashes. Fails if any RNG drift slips in.
2. **`tests/integration_mesh/test_lens_golden_snapshots.py`** — pulls the fixture corpus through `compile_filter` + `apply_lens` and asserts SHA-256 of the output matches the locked golden hash.
3. **`tests/fixtures/connector_conformance/`** — 8 tests every connector must pass; uses `FixtureConnector` + `FixtureMapper` as the reference implementation for the harness.

## When to regenerate golden snapshots

Regenerate **only** when one of these changes intentionally:

| Trigger | Action |
|--------|--------|
| Faker version bump | Update `pyproject.toml` `[fixture]` extra, regenerate snapshots, commit lockfile + snapshots in the same PR/commit |
| Corpus shape change (count, fields) | Update `_COUNTS_BY_SIZE` in `cip/integration_mesh/connectors/fixture/corpus.py`, regenerate snapshots, file a PM decision documenting the shape change |
| Persister output schema change | Coordinate with a `cip_NN_*` migration; regenerate snapshots after the migration applies |

Regeneration command (once decision is filed):

```bash
PYTHONHASHSEED=0 pytest tests/integration_mesh/test_lens_golden_snapshots.py --snapshot-update
git diff tests/integration_mesh/test_lens_golden_snapshots.py
# Review the diff carefully — any unexpected change is a determinism leak
git add tests/integration_mesh/test_lens_golden_snapshots.py
```

**Never regenerate snapshots casually.** A surprise diff almost always indicates a determinism contract violation (Faker bump not noticed, dict ordering leak, etc.).

## Common gotchas

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Snapshot mismatch on a clean checkout | `PYTHONHASHSEED` not set in shell | `export PYTHONHASHSEED=0` (CI sets it automatically) |
| Snapshot mismatch only on Python ≠ 3.12 | Snapshots are locked to 3.12; this is expected | Run 3.12 locally to match CI; or update snapshots only for 3.12 |
| Row counts off by 1–2 from STANDARD | A Faker bump or seed change | Diff `corpus.py`; revert any unintentional changes |
| `cip_sync_runs` has rows but no entity rows | Seed ran but encountered an error after sync_run START | Check `cip_sync_runs.error_detail`; reseed after fixing |
| Re-running the seeder produces SCD-2 history rows | Differ detected a real change | Either a bug or an intentional source change — `git log corpus.py` should explain |

## Related files

- [`cip/integration_mesh/connectors/fixture/connector.py`](../cip/integration_mesh/connectors/fixture/connector.py) — `FixtureConnector` implementation
- [`cip/integration_mesh/connectors/fixture/mapper.py`](../cip/integration_mesh/connectors/fixture/mapper.py) — `FixtureMapper` implementation
- [`cip/integration_mesh/connectors/fixture/corpus.py`](../cip/integration_mesh/connectors/fixture/corpus.py) — corpus shape + RNG split
- [`cip/integration_mesh/connectors/fixture/records.py`](../cip/integration_mesh/connectors/fixture/records.py) — record-type dataclasses
- [`scripts/seed_railway_prod_fixture.py`](../scripts/seed_railway_prod_fixture.py) — the seed entry point
- [`tests/fixtures/connector_conformance/`](../tests/fixtures/connector_conformance/) — 8-test conformance harness
- [`tests/integration_mesh/test_fixture_corpus_determinism.py`](../tests/integration_mesh/test_fixture_corpus_determinism.py) — regression guard
- [`tests/integration_mesh/test_lens_golden_snapshots.py`](../tests/integration_mesh/test_lens_golden_snapshots.py) — golden-snapshot test

## Cross-references

- [`CIP-SOP-001 CONNECTOR-AUTHORING-GUIDE.md`](CONNECTOR-AUTHORING-GUIDE.md) — uses fixture connector as reference implementation
- [`CIP-SOP-003 LENS-AUTHORING-GUIDE.md`](LENS-AUTHORING-GUIDE.md) — references fixture corpus for golden snapshots
- [`CIP-SOP-006 SYNC-ORCHESTRATOR-GUIDE.md`](SYNC-ORCHESTRATOR-GUIDE.md) — the `run_sync` entry point fixture seeding invokes
- [`CIP-SPEC-004 PHASE-1-PLAIN-SPEC.md`](vision/PHASE-1-PLAIN-SPEC.md) §5 + §7 — the spec the fixture tenant validates against
- [`CIP-SOP-004 METABASE-OPERATOR-GUIDE.md`](METABASE-OPERATOR-GUIDE.md) §2 Step 10 — reserved tenant UUID provenance
