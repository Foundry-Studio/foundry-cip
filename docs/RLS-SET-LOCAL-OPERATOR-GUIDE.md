---
kind: doc
domain: client-intelligence-platform
status: draft
last_updated: 2026-04-21
milestone: Phase-1-M1
---

# RLS + `SET LOCAL` Operator Guide

> **Status:** draft — M1 policies live 2026-04-21. All TBD(M1) sections populated.
> Once final, this guide is the authoritative reference for tenant scoping in CIP — how RLS policies and `SET LOCAL app.current_tenant` combine to guarantee D-026 isolation.

## Purpose

Explain the tenant-scoping contract: how Row-Level Security policies on every `cip_*` table, combined with `SET LOCAL app.current_tenant = '<uuid>'` at the start of every session/transaction, enforce strict per-tenant isolation — and how to verify, debug, and extend it.

## Who reads this

- Every engineer writing code that queries `cip_*` tables.
- Operators debugging "why did this query return zero rows / too many rows?"
- Phase 3 engineers extending the model to support cross-tenant grants (cip_09).

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Created this skeleton. |
| M1 — Migrations cip_01–cip_08 | Populated §2 RLS policy template and §4 per-table verification. |
| M7 — Four-access-paths validation | Populates §6 cross-tenant probe (must return zero rows). |

Cross-ref: `CLAUDE.md` Rule D-026 ("Every database query MUST include tenant_id scoping"), [`PHASE-1-PLAIN-SPEC.md §2`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md) acceptance item 10.

---

### 1. The contract

CIP enforces per-tenant isolation with two cooperating layers:

1. **Row-Level Security (RLS):** every `cip_*` table has `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + a `cip_tenant_scope` policy. The policy blocks all rows whose `tenant_id` does not match the session's `app.current_tenant` GUC.

2. **`SET LOCAL app.current_tenant`:** application code sets this GUC at the start of every transaction. `SET LOCAL` is transaction-scoped — the value is automatically cleared on COMMIT or ROLLBACK, preventing cross-request tenant leakage.

**Neither layer alone is sufficient:**

- RLS without `SET LOCAL`: all queries see zero rows (or raise), blocking legitimate access.
- `SET LOCAL` without RLS: a bug or missing WHERE clause could expose cross-tenant data.
- Together: even if a SELECT is missing `WHERE tenant_id = :t`, RLS enforces the filter at the database level.

**D-026 compliance:** every CIP query path must call `SET LOCAL app.current_tenant = '<uuid>'` before issuing any `cip_*` table access. This is a hard rule (CLAUDE.md D-026). The RLS policy is the database-enforced backstop.

---

### 2. RLS policy template

Every `cip_*` table ships with the following policy (applied in the migration):

```sql
ALTER TABLE cip_<table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE cip_<table> FORCE ROW LEVEL SECURITY;
CREATE POLICY cip_tenant_scope ON cip_<table>
  USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
```

**Policy breakdown:**

- `USING (...)` — applies to SELECT, UPDATE, DELETE. Rows not matching the expression are invisible/blocked.
- `current_setting('app.current_tenant', true)` — reads the transaction-local GUC. The `true` flag (missing_ok) returns `''` instead of raising if the GUC is not set.
- `NULLIF(..., '')` — converts `''` (empty string) to NULL. `NULL::uuid` is NULL, and `tenant_id = NULL` is always false — blocking all rows when no tenant is set.
- `FORCE ROW LEVEL SECURITY` — applies the policy even to table owners and superusers. **Exception: roles with `rolbypassrls=TRUE` (e.g., the `postgres` superuser on Railway) are still excluded.** Application connections must use a role without `BYPASSRLS`.

**All 17 CIP tables use the identical policy name `cip_tenant_scope`.** History tables have their own copy of the policy (identical USING expression) because they carry their own `tenant_id` column.

---

### 3. Setting `app.current_tenant`

**When to call `SET LOCAL`:**

At the start of every database transaction that touches any `cip_*` table. Typically in a request middleware or context manager.

**Correct pattern:**

```python
from sqlalchemy import text

async def with_tenant_context(conn, tenant_id: str):
    # SET LOCAL is transaction-scoped — clears on COMMIT/ROLLBACK.
    # Must NOT use parameterized binding ($1 / %(t)s) — SET does not
    # support server-side parameters.  tenant_id must be a validated UUID.
    await conn.execute(text(f"SET LOCAL app.current_tenant = '{tenant_id}'"))
```

**SQLAlchemy async pattern (production):**

```python
async with async_session() as session:
    async with session.begin():
        await session.execute(
            text(f"SET LOCAL app.current_tenant = '{tenant_id}'")
        )
        result = await session.execute(
            text("SELECT * FROM cip_clients")
        )
```

**Important:** `SET` (including `SET LOCAL`) does not accept parameterized values (`$1`, `%s`, `:name`). The tenant UUID must be embedded directly in the SQL string. Always validate `tenant_id` is a valid UUID before embedding.

**`SET LOCAL` vs `SET`:**

- `SET LOCAL` — transaction-scoped. Cleared on COMMIT or ROLLBACK. **Always use this.**
- `SET` — session-scoped. Persists for the life of the connection. Never use this in application code — pool connections are reused, and a stale tenant context from a previous request would be inherited.

**Alembic migrations:** `env.py` uses `SET LOCAL statement_timeout` / `SET LOCAL lock_timeout` inside `context.begin_transaction()`. Placing `SET LOCAL` outside `begin_transaction()` causes SQLAlchemy autobegin to start an implicit transaction that `begin_transaction()` sees as already-active, preventing the migration from committing. See `MIGRATION-RUNBOOK.md §7`.

---

### 4. Per-table verification

After applying cip_01–cip_08, verify RLS is working:

**Step 1: Confirm RLS and FORCE are enabled.**

```sql
SELECT relname, relrowsecurity AS rls, relforcerowsecurity AS force
FROM pg_class
WHERE relname LIKE 'cip_%' AND relkind = 'r'
ORDER BY relname;
```

All 17 CIP tables must show `rls=true, force=true`.

**Step 2: Confirm policy exists on each table.**

```sql
SELECT tablename, policyname, qual
FROM pg_policies
WHERE tablename LIKE 'cip_%'
ORDER BY tablename;
```

Each table must have exactly one policy: `cip_tenant_scope` with qual containing `NULLIF(current_setting('app.current_tenant', true), '')::uuid`.

**Step 3: Insert-as-A / query-as-B isolation test.**

```sql
-- Insert a row for Tenant A (bypass RLS as superuser)
INSERT INTO cip_clients (id, tenant_id, source_connector, source_id,
  ingestion_batch_id, authority, name, slug)
VALUES (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000001'::uuid,
        'verify', 'verify-1', gen_random_uuid(), 'validated',
        'Verify Corp', 'verify-corp');

-- Query as Tenant B (must return 0 rows)
BEGIN;
SET LOCAL ROLE cip_rls_test_role;  -- restricted role (no BYPASSRLS)
SET LOCAL app.current_tenant = 'b0000000-0000-0000-0000-000000000002';
SELECT count(*) FROM cip_clients WHERE slug = 'verify-corp';
-- Expected: 0
ROLLBACK;

-- Cleanup
DELETE FROM cip_clients WHERE slug = 'verify-corp';
```

**Automated verification:**

```bash
pytest tests/migrations/ -v
# 36 tests, all must pass
```

---

### 5. Common failure modes

**"All queries return zero rows" after adding a new worker/thread**

Cause: `SET LOCAL app.current_tenant` was not called before querying. `NULLIF` + `NULL::uuid` causes the policy to block all rows. Solution: ensure every code path that queries `cip_*` tables calls `SET LOCAL` at the start of the transaction.

**"Pool contamination — wrong tenant visible"**

Cause: `SET` (session-scoped) was used instead of `SET LOCAL`. The connection pool reused a connection where `app.current_tenant` was set to a previous request's tenant. Solution: always use `SET LOCAL`. If the issue is suspected in production, audit all code for `SET app.current_tenant` (without LOCAL).

**"Cross-tenant rows visible despite SET LOCAL"**

Cause 1: the connection user has `rolbypassrls=TRUE` (e.g., `postgres` superuser). `FORCE ROW LEVEL SECURITY` does NOT override `BYPASSRLS`. Solution: application must use a restricted role. Verify with `SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user`.

Cause 2: `SET LOCAL` is inside an explicit `BEGIN` issued by psycopg2/psycopg3, but the engine was configured with `AUTOCOMMIT` isolation. In `AUTOCOMMIT` mode, an explicit `BEGIN` starts a real transaction and `SET LOCAL` works — but only if the `SET LOCAL` statement executes after the `BEGIN`. Verify the execution order.

**"RLS policy missing after downgrade + re-upgrade"**

Cause: downgrade dropped the policy but re-upgrade created it with different wording (e.g., old version without NULLIF). Run `SELECT qual FROM pg_policies WHERE tablename = 'cip_clients'` to confirm the live policy text matches the migration file.

**"`invalid input syntax for type uuid: ""`**

Cause: old policy without NULLIF — `current_setting('app.current_tenant', true)::uuid` where `current_setting` returns `''`. Policy must use `NULLIF(current_setting('app.current_tenant', true), '')::uuid`. Re-apply with `DROP POLICY / CREATE POLICY`.

---

### 6. Cross-tenant probe

> **TBD (M7)** — The four-access-paths validation milestone will add the full cross-tenant probe script here, covering all 4 access paths (GraphRAG, direct SQL, REST API, Lens Engine) and asserting zero cross-tenant rows in each path.

Placeholder — M1 partial coverage:

The RLS smoke tests at `tests/migrations/` cover the database-layer isolation for all 17 CIP tables. Run them with `pytest tests/migrations/ -v` to confirm zero cross-tenant rows in all 36 test cases.

---

### 7. Phase 3 preview — cross-tenant grants

> **TBD (M1)** — This section will be populated when Phase 3 (cip_09) is scoped.

Planned `cip_09_cross_tenant_grants` table will allow Tenant A to explicitly grant read access to specific `client_id` rows to Tenant B. The RLS policy will be extended to also permit rows where `tenant_id = <granting_tenant>` AND a grant row exists for the requesting tenant. Default isolation (D-026) is maintained — grants are opt-in.

---

### 8. Debugging RLS

**Useful psql/SQLAlchemy commands:**

```sql
-- Check current tenant context
SELECT current_setting('app.current_tenant', true);

-- Check current role and bypass status
SELECT current_user, (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user);

-- Show all policies on CIP tables
\d+ cip_clients   -- psql: shows table definition including RLS
SELECT * FROM pg_policies WHERE tablename LIKE 'cip_%';

-- Show RLS enforcement state
SELECT relname, relrowsecurity, relforcerowsecurity
FROM pg_class WHERE relname LIKE 'cip_%' AND relkind = 'r';

-- Test policy manually (EXPLAIN shows if filter is applied)
BEGIN;
SET LOCAL ROLE cip_rls_test_role;
SET LOCAL app.current_tenant = 'a0000000-0000-0000-0000-000000000001';
EXPLAIN SELECT * FROM cip_clients;
-- Plan should show: Filter: (tenant_id = ...)
ROLLBACK;
```

**Typical misdiagnoses:**

- "RLS isn't working" → actually the connection user is the superuser with BYPASSRLS. Use `SET LOCAL ROLE`.
- "My query returns nothing" → `SET LOCAL` was not called, or was called in the wrong transaction scope. Check `current_setting('app.current_tenant', true)`.
- "Tests pass but prod fails" → test uses `cip_rls_test_role` (no BYPASSRLS); prod app may be using a superuser connection. Verify prod role with `SELECT current_user` from the running app.

**Reproducing in a test:**

```python
# In tests/migrations/conftest.py pattern:
with session_as_tenant(engine, TENANT_B) as s:
    rows = s.execute(text("SELECT count(*) FROM cip_clients")).scalar()
    assert rows == 0  # must always be 0 for cross-tenant query
```

#### `cip_rls_test_role` — test-infrastructure role provenance

This role exists to make RLS testable against a Postgres whose default connection user has `BYPASSRLS` (as Railway's `postgres` user does). It is **conftest-managed, not migration-managed** — per Atlas Q1 ruling of 2026-04-21 during the CIP Phase 1 M1 exit review.

**Why conftest, not a migration:** the role is test infrastructure, not product schema. CIP migrations (`cip_01`–`cip_08`) describe the product's data model; adding a test-only role to them would pollute every environment where migrations run (including production deploys that have no business carrying a test role). Keeping provisioning inside `tests/migrations/conftest.py` confines the role to contexts that actually run pytest.

**Provisioning SQL** (executed idempotently by `_ensure_rls_test_role()` in `tests/migrations/conftest.py`):

```sql
-- Create if absent (NOSUPERUSER NOBYPASSRLS is the whole point — RLS must apply)
CREATE ROLE cip_rls_test_role NOSUPERUSER NOBYPASSRLS
    NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;

-- Idempotent grants — re-applied on every module load so new tables are covered
GRANT USAGE ON SCHEMA public TO cip_rls_test_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
    TO cip_rls_test_role;
```

**DO NOT create this role in production.** Its reason to exist is "a role that PostgreSQL will actually enforce RLS against under pytest." In production, the CIP application MUST connect as a non-superuser role without `BYPASSRLS` — that role is a separate concern (tracked as an open question against M3 kickoff, not a responsibility of this test role). If `cip_rls_test_role` ends up in prod by accident, revoke its grants and `DROP ROLE cip_rls_test_role` immediately.

**Lifecycle:** created once per test environment on first pytest run against a fresh DB; grants re-applied every module load so new tables added by later migrations are covered automatically. No migration, no deploy hook, no config flag toggles it — presence is a side effect of running `pytest tests/migrations/`.
