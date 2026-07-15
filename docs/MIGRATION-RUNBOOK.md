---
id: CIP-SOP-002
uuid: 25c18b2b-3299-4dfa-a8e5-3cd5d845c473
title: Migration Runbook
type: sop
owner: tim
solve_for: Operator procedure for applying CIP Alembic migrations safely against dev
  and prod.
stage_label: adopt
domain: eng
version: '1.0'
created: '2026-04-21'
last_modified: '2026-05-15'
last_reviewed: '2026-05-19'
review_cadence: 90
milestone: Phase-1-M7
---

# Migration Runbook

> **Status:** draft — M1 migrations applied 2026-04-21; cip_09 (Metabase platform service) added 2026-05-09 in M5; cip_10 (history lens views) added 2026-05-11; cip_11 (sync_mode_backfill — D-159 hotfix) added 2026-05-15 during the Wayward Phase 2 incident response. M7 read-through 2026-05-11 corrected the cip_09 / Phase 3 misattribution in §8. **2026-05-15 reconciliation:** Phase 2.5 write-back migrations renumbered from cip_10/cip_11/cip_12 → cip_12/cip_13/cip_14, and Phase 3 cross-tenant grants slot moves from cip_10 → cip_15 (next-free at Phase 3 kickoff).
> This runbook is the authoritative sequence for applying `cip_*` migrations to any CIP-enabled environment. Phase 1 covers cip_01 → cip_11 (with cip_09–cip_11 added incrementally for M5 + the D-159 backfill hotfix); cip_12/13/14 are Phase 2.5 write-back; cross-tenant grants (Phase 3) chain at cip_15+.

## Purpose

Step-by-step runbook for applying CIP migrations (cip_01–cip_08 in Phase 1) to local/dev/prod: ordering, verification, rollback, and common failure modes.

## Who reads this

- Any operator running CIP migrations (first onboard, re-seed, prod deploy).
- Reviewers validating new `cip_*` migrations against the contract.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Created this skeleton. |
| M1 — Migrations cip_01–cip_08 | Populated this runbook. Migrations applied 2026-04-21. |

Cross-ref: [`PHASE-1-PLAIN-SPEC.md §3`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md) for the binding migration file paths.

---

### 1. Migration inventory (Phase 1)

All 8 migrations land in a single linear chain. Each subsequent revision's `down_revision` points to the previous.

| Revision ID | File | Table(s) created | History table |
|-------------|------|------------------|---------------|
| `cip_01_clients` | `migrations/versions/cip_01_clients.py` | `cip_clients` | `cip_clients_history` |
| `cip_02_views` | `migrations/versions/cip_02_views.py` | `cip_views` | `cip_views_history` |
| `cip_03_sync_runs` | `migrations/versions/cip_03_sync_runs.py` | `cip_sync_runs` | none (IS the audit log) |
| `cip_04_files` | `migrations/versions/cip_04_files.py` | `cip_files` | `cip_files_history` |
| `cip_05_contacts` | `migrations/versions/cip_05_contacts.py` | `cip_contacts` | `cip_contacts_history` |
| `cip_06_companies` | `migrations/versions/cip_06_companies.py` | `cip_companies` | `cip_companies_history` |
| `cip_07_deals` | `migrations/versions/cip_07_deals.py` | `cip_deals` | `cip_deals_history` |
| `cip_08_tickets_and_registry` | `migrations/versions/cip_08_tickets_and_registry.py` | `cip_tickets`, `cip_connector_property_registry` | `cip_tickets_history` |
| `cip_09_metabase_role_views` | `migrations/versions/cip_09_metabase_role_views.py` | `cip_metabase_role` (Postgres LOGIN role) + `lens_all_companies` + `lens_eu_west_companies` views | none |

The chain base: `cip_01_clients.down_revision = "async_03_agents_cols"` (the production DB head before CIP was introduced).

Total new objects: 16 tables + 1 registry table + 2 lens views + 1 Postgres role = 17 tables + 2 views, 40+ indexes, 17 RLS policies, plus the M5 grant matrix (REVOKE on `cip_*`, GRANT only on `lens_*`).

---

### 2. Pre-flight checks

Before running `alembic upgrade head`:

```bash
# 1. Confirm DATABASE_URL is set and points to the target DB
echo $DATABASE_URL  # must be non-empty

# 2. Check reachability
python -c "
import sys; sys.path.insert(0,'.')
from src.db.session import get_sqlalchemy_url
from sqlalchemy import create_engine, text
url = get_sqlalchemy_url()
e = create_engine(url.replace('postgresql+psycopg://','postgresql://'))
with e.connect() as c: print('OK:', c.execute(text('SELECT version()')).scalar()[:40])
"

# 3. Check current alembic head
alembic current

# 4. Confirm expected base is present
# Output should include "async_03_agents_cols" before cip_01 is applied.
# Once cip_01–cip_08 are applied, output should be:
# cip_08_tickets_and_registry (head)
```

Required environment variable: `DATABASE_URL` — same URL used by the application. Format: `postgresql+psycopg://user:pass@host:port/dbname`.

---

### 3. Apply order

Strict linear chain: `cip_01` → `cip_02` → ... → `cip_08`. Never skip.

```bash
alembic upgrade head
```

Alembic resolves the chain automatically. Each migration must complete before the next runs (transactional DDL). The D-123 advisory lock (`pg_advisory_xact_lock(4042024118)`) serializes concurrent `alembic upgrade` calls — safe for rolling Railway deploys.

**Do not** apply individual revisions out of order (e.g., `alembic upgrade cip_05`) unless intentional partial apply for debugging.

**Expected terminal output:**

```
INFO  Running upgrade async_03_agents_cols -> cip_01_clients, ...
INFO  Running upgrade cip_01_clients -> cip_02_views, ...
INFO  Running upgrade cip_02_views -> cip_03_sync_runs, ...
INFO  Running upgrade cip_03_sync_runs -> cip_04_files, ...
INFO  Running upgrade cip_04_files -> cip_05_contacts, ...
INFO  Running upgrade cip_05_contacts -> cip_06_companies, ...
INFO  Running upgrade cip_06_companies -> cip_07_deals, ...
INFO  Running upgrade cip_07_deals -> cip_08_tickets_and_registry, ...
```

---

### 4. Per-migration verification queries

After `alembic upgrade head`, verify each table has RLS attached and tenant isolation holds.

**Quick verification — all tables:**

```sql
-- Check all CIP tables exist with RLS + FORCE enabled
SELECT relname, relrowsecurity AS rls, relforcerowsecurity AS force
FROM pg_class
WHERE relname LIKE 'cip_%' AND relkind = 'r'
ORDER BY relname;
-- All rows should show rls=true, force=true
```

**Tenant isolation spot-check (run as non-superuser or via SET ROLE):**

```sql
BEGIN;
SET LOCAL ROLE <app_role>;  -- must be a role without BYPASSRLS

-- Tenant A context: should see only Tenant A rows
SET LOCAL app.current_tenant = 'a0000000-0000-0000-0000-000000000001';
SELECT count(*) FROM cip_clients;  -- 0 if no data for this tenant

-- No-tenant context: should raise or return 0
SET LOCAL app.current_tenant = '';
SELECT count(*) FROM cip_clients;  -- 0 (NULLIF policy blocks empty string)
ROLLBACK;
```

**Per-table RLS smoke test (automated):**

```bash
pytest tests/migrations/ -v
# All 36 tests must pass
```

---

### 5. History-table conventions

Every `cip_<table>_history` table (except `cip_sync_runs`, which has no history) follows SCD Type 2:

- `history_id` UUID PK — unique row identifier in the history table.
- `record_id` UUID — FK to the main table's `id`. Multiple history rows per `record_id`.
- `valid_from` / `valid_to` — temporal range. `valid_to IS NULL` means the row was superseded at time `valid_to`, or is the current snapshot.
- `changed_by` TEXT — who/what triggered the change (e.g., connector name, user email).
- `change_reason` TEXT — optional human label (e.g., "sync", "manual edit").
- All provenance and domain columns are duplicated from the main table as a snapshot.
- CHECK constraint: `valid_to IS NULL OR valid_to > valid_from`.
- RLS: same policy as main table (`cip_tenant_scope`), tenant_id required.

**Authority column:** `authority TEXT NOT NULL DEFAULT 'validated'`. Valid values (per SPEC §6): `'validated'` (source of truth), `'inferred'` (derived by CIP), `'overridden'` (human override). The history table preserves the authority value at the time of the snapshot.

---

### 6. Rollback

**When safe to downgrade:**

- No application code is reading/writing `cip_*` tables yet (pre-activation).
- The entire cip_01–cip_08 chain is idempotent in terms of external schema impact.

**How to downgrade all 8 migrations:**

```bash
alembic downgrade async_03_agents_cols
```

This runs `downgrade()` in each migration in reverse order (cip_08 → cip_01), dropping tables, indexes, policies, and RLS in the correct sequence.

**When NOT to downgrade:**

- Any application component is writing to `cip_*` tables — rollback would destroy data.
- `cip_clients` has tenant rows that feed other systems.
- After Phase 1 M3 or later (fixture data loaded).

**Partial failure recovery:**

If `alembic upgrade head` fails mid-chain (e.g., cip_05 fails after cip_04 applied):

1. Check `SELECT version_num FROM alembic_version` to confirm current head.
2. Downgrade to the last clean revision: `alembic downgrade cip_04_files`.
3. Fix the failing migration.
4. Re-run `alembic upgrade head`.

All CIP migrations use transactional DDL — if a migration fails mid-execution, PostgreSQL rolls back that individual migration's DDL. The `alembic_version` table will not be updated for the failed migration.

---

### 7. Common failure modes

**`current setting is not SET LOCAL aware (transaction not started)`**

Symptom: `alembic upgrade head` logs "Running upgrade" but `alembic_version` does not update. Cause: `SET statement_timeout` / `SET lock_timeout` executed outside `context.begin_transaction()`, triggering SQLAlchemy autobegin which starts an implicit transaction that `context.begin_transaction()` sees as already-active, causing it to not COMMIT.

Fix: ensure `SET` statements are inside `context.begin_transaction()` in `migrations/env.py`.

**RLS bypassed by superuser connection**

Symptom: queries return cross-tenant rows despite `SET LOCAL app.current_tenant`. Cause: the connection user is a PostgreSQL superuser (`rolsuper=True`) or has `BYPASSRLS=True`. `FORCE ROW LEVEL SECURITY` does NOT override `BYPASSRLS`.

Fix: application connections must use a non-superuser role without `BYPASSRLS`. Test with `SET LOCAL ROLE <app_role>` before issuing queries. The smoke tests use `cip_rls_test_role` (a restricted role created by `tests/migrations/conftest.py`).

**`invalid input syntax for type uuid: ""`**

Symptom: error when querying without `SET LOCAL app.current_tenant`. Cause: `current_setting('app.current_tenant')::uuid` with empty string. Policy now uses `NULLIF(..., '')::uuid` which returns NULL (blocking the row) instead of raising.

**`unrecognized configuration parameter "app.current_tenant"`**

Symptom: `current_setting('app.current_tenant')` raises UndefinedObject. This is expected when the GUC has never been set in the session. The policy uses `current_setting(..., true)` (missing_ok) and `NULLIF` to return NULL → block rows.

**Alembic branching / multiple heads**

Symptom: `alembic upgrade head` errors with "Multiple head revisions". Cause: a new migration was created with incorrect `down_revision`. Check that `cip_01_clients.down_revision = "async_03_agents_cols"` (single string, not a tuple).

**`uq_cip_clients_tenant_slug` violation during tests**

Symptom: test setup fails with unique constraint on `(tenant_id, slug)`. Cause: test data from a previous run was committed and not cleaned up. The conftest `engine` fixture calls `_purge_cip_test_data()` before and after each module — if a run was killed mid-flight, run `pytest tests/migrations/ -v` again (the fixture purges on startup).

**`cip_test_trace` — historical artifact, not a supported table**

Debug table `cip_test_trace` created during M1 env.py troubleshooting; had no migration backing it (artifact only). **Formally dropped by `cip_98` (2026-07-15)** along with `ps_classification_rules` — see the P1 schema audit.

---

### 8. Phase 2.5 and Phase 3 migrations (preview)

**Do not apply these in Phase 1 ventures.** (Updated 2026-05-15 — see top-of-doc reconciliation note for the renumbering history.)

| Revision (planned) | Phase | Purpose |
|--------------------|-------|---------|
| `cip_12_cip_pending_writes` | Phase 2.5 | Write-back: mutation queue + `_history` SCD-2. |
| `cip_13_cip_write_authorities` | Phase 2.5 | Write-back: per-lens authority floors keyed by source_agent_id. |
| `cip_14_cip_write_decisions` | Phase 2.5 | Write-back: append-only audit of approve/reject decisions. |
| `cip_15_cross_tenant_grants` | Phase 3 | Cross-tenant visibility grants — extends RLS model without breaking D-026 default isolation. (Was earlier sketched as `cip_09`, then `cip_10` after the 2026-05-11 read-through; renumbered to `cip_15` 2026-05-15 because cip_10 and cip_11 are now occupied.) |

These revisions chain off `cip_11_sync_mode_backfill` when authored. The actual slot numbers may shift again if additional hotfix migrations land between now and Phase 2.5/3 kickoff — confirm at kickoff against the deployed alembic chain.
