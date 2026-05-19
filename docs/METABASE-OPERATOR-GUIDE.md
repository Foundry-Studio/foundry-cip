---
id: CIP-SOP-004
uuid: 06659bec-9863-4c7c-971a-b4759bb81bdd
title: Metabase Operator Guide
type: sop
owner: tim
solve_for: Operator guide for running Metabase against CIP under the cip_metabase_role
  grant pattern.
stage_label: adopt
domain: ops
version: '1.0'
created: '2026-05-09'
last_modified: '2026-05-11'
last_reviewed: '2026-05-19'
review_cadence: 90
milestone: Phase-1-M7
---

# Metabase Operator Guide

> **Status:** draft — created 2026-05-09 alongside M5's `cip_09_metabase_role_views` migration; M7 read-through 2026-05-11 corrected §Related M6 row + §3 forward note (M6 was discoverability verification, NOT an auto-generator commit-watcher — the auto-generator is deferred to Phase 2 per task #143). Reflects the deployed shape. Operator-side dashboard authoring is the actual M5 acceptance proof; this doc is the runbook.

## Purpose

Wire the existing Metabase deployment at `reports.project-silk.com` to the foundry-cip Postgres so a human operator can author dashboards over the fixture-tenant CIP data through the M5 lens views — without ever touching raw `cip_*` tables.

## Who reads this

- The operator (Tim) connecting Metabase to foundry-cip Postgres for the first time.
- Future operators onboarding additional CIP tenants to Metabase (Phase 2+; this guide stays valid for the connection-side conventions, but multi-tenant Collections is a separate Metabase-project concern).
- Engineers debugging "I see no rows in Metabase" — §6 + §7 cover the failure modes.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | (Skipped — this doc was created direct as `status: draft` in M5 because no M0 skeleton existed for it. M5 Δ in plan v3 §4.3.) |
| M4 — Lens Engine | Provides the Lens-A and Lens-B fixture lenses; M5 mirrors them as Postgres views. |
| **M5 — Metabase platform service** | **This guide ships alongside the cip_09 migration.** Two demo dashboards + a Lens Switcher are the M5 acceptance proof (operator-side, screenshot evidence in `WORKBENCH/tim/m5-acceptance-evidence/`). |
| M6 — Discoverability registry completeness pass | Verified `lens_*` Postgres views exist + per-tenant isolation through `cip_metabase_role` (`tests/integration_mesh/test_discoverability_completeness.py` Test 5). M5's hardcoded views remain hardcoded; the auto-generator commit-watcher (Phase 2 task #143) is what eventually unwires this. |
| M7 — Four Access Paths Validation + Doc Suite Harden | Cross-validated Path 1 production-shape (lens views as cip_metabase_role) against the Python-side lens engine in `tests/integration_mesh/test_four_access_paths_validation.py`. |
| Phase 2+ — multi-tenant Metabase + auto-generator | Per-tenant Collections / per-tenant DB connections + commit-watcher that regenerates `lens_*` views from `cip_views` row changes. This guide's single-tenant pin is Phase 1 only. |

Cross-ref: `cip/migrations/versions/cip_09_metabase_role_views.py`, `cip/integration_mesh/lens_engine/`, `docs/LENS-AUTHORING-GUIDE.md`, `docs/vision/VISION.md` §S6 (Consumption Surfaces) + §4 ("What Already Exists" — Metabase at reports.project-silk.com).

---

## 1. What is Metabase, and how does it relate to CIP?

**Metabase** is a self-hosted dashboarding tool at `reports.project-silk.com`. It connects to SQL databases and lets non-engineers author dashboards via point-and-click + a SQL escape hatch.

**CIP** is foundry-cip — Postgres tables (`cip_companies`, `cip_contacts`, `cip_deals`, `cip_tickets`, `cip_files`) holding tenant-scoped client intelligence, plus the M4 Lens Engine for filtered views.

**The connection between them is one-way:** Metabase reads from CIP through `lens_*` views. It does NOT write back. It does NOT touch raw `cip_*` tables. The data flow is:

```
        Metabase                 cip_metabase_role
        question        →        (Postgres LOGIN role)        →        lens_all_companies
        (SQL)                                                          (or lens_eu_west_companies)
                                          ↓                                       ↓
                                    GRANT SELECT                         underlying SELECT
                                    only on lens_*                       FROM cip_companies
                                    views                                WHERE tenant_id = GUC
```

**P-21 Multi-Lens-by-Default is structurally enforced:** if a Metabase user types `SELECT * FROM cip_companies` in a native SQL question, Postgres returns `permission denied for table cip_companies`. This is not convention — it's the role's grant matrix. See §6 for how to verify.

---

## 2. Connecting Metabase to CIP fixture DB

**When to use:** first-time setup, OR when re-pointing Metabase at a different CIP environment (Railway preview deploy, staging, etc.).

**Prerequisites:**
- Metabase admin access at `reports.project-silk.com`.
- The `METABASE_DB_PASSWORD` value from Railway (the foundry-cip service env). If not yet set, see §7 "Rotation procedure" for the initial-set workflow.
- The foundry-cip Postgres host/port/db (Railway dashboard → foundry-cip service → Postgres plugin).

**Step-by-step:**

1. In Metabase admin: `Settings` → `Admin Settings` → `Databases` → `Add database`.
2. Select **PostgreSQL**.
3. Display name: `CIP Fixture (Phase 1)`.
4. Host: `<from Railway Postgres plugin>`.
5. Port: `5432` (or whatever Railway exposes).
6. Database name: `<the foundry-cip Postgres database>`.
7. **Username:** `cip_metabase_role` (literal — NOT `postgres` and NOT a personal account).
8. **Password:** the `METABASE_DB_PASSWORD` value from Railway env.
9. Click **Show advanced options**. Find **Init SQL** (sometimes labeled "Connection setup script" depending on Metabase version).
10. **Init SQL:**
    ```sql
    SET app.current_tenant = 'a0000000-0000-0000-0000-000000000001';
    ```
    This is `TENANT_A` per `tests/migrations/conftest.py` — the stable fixture tenant UUID used across migration tests + M5 lens views. Reusing it for the operator pin keeps test + operator semantics consistent.
11. Click **Save**.
12. Verify connection: in the data-browser, you should see `lens_all_companies` and `lens_eu_west_companies`. You should NOT see `cip_*` tables (the role doesn't have permission to inspect them).

**Common pitfalls:**
- *"I see lens_* views but rows are empty"* — Init SQL didn't run, or ran with wrong tenant. The view's `WHERE tenant_id = NULLIF(current_setting(...), '')::uuid` evaluates to NULL when GUC unset → zero rows. Re-check Init SQL + reconnect.
- *"Metabase says authentication failed"* — `METABASE_DB_PASSWORD` mismatch between Metabase and Railway. Pull the Railway value fresh; copy-paste careful.
- *"I see cip_companies in the schema browser"* — the role has more permissions than expected. Run §6.4 verification; escalate if `SELECT * FROM cip_companies` succeeds.

---

## 3. The `lens_*` view convention

**When to use:** authoring any new dashboard or question against CIP data.

**The contract:** Metabase always queries `lens_*` views. Never `cip_*` tables. This is enforced by Postgres grants.

**Currently provisioned views (post-M5):**

| View | Filter | Equivalent M4 lens |
|------|--------|-----|
| `lens_all_companies` | (none — returns all rows for the active tenant) | Lens-A (`filter_config={}`) |
| `lens_eu_west_companies` | `region = 'eu-west'` | Lens-B (`filter_config={"region": "eu-west"}`) |

Both views target `cip_companies`. Phase 2+ will add lens views for other entity tables (cip_contacts, cip_deals, etc.) with appropriate filters.

**Forward note:** M5 ships hardcoded views in the `cip_09` migration. A future commit-watcher (deferred to Phase 2 — PM task #143) auto-generates a lens view whenever a row is written to `cip_views`. Until that lands, every new lens requires a new migration + manual `CREATE VIEW`. Document the rationale for any non-trivial lens addition in the migration commit so the future auto-generator has context.

---

## 4. Authoring the Lens-A dashboard

**When to use:** the first M5-acceptance dashboard. Surfaces the full company set for the active tenant.

**Step-by-step:**

1. In Metabase: `+ New` → `Dashboard` → name `CIP Lens-A — All Companies`.
2. Add 4 question tiles via `+ Add a question` → `Native SQL`:

   - **Tile 1 — Total companies:**
     ```sql
     SELECT count(*) AS total_companies FROM lens_all_companies;
     ```
     Display: scalar / single number.

   - **Tile 2 — Companies by industry:**
     ```sql
     SELECT industry, count(*) AS company_count
     FROM lens_all_companies
     GROUP BY industry
     ORDER BY company_count DESC;
     ```
     Display: bar chart.

   - **Tile 3 — Companies by region:**
     ```sql
     SELECT region, count(*) AS company_count
     FROM lens_all_companies
     GROUP BY region
     ORDER BY company_count DESC;
     ```
     Display: bar chart or pie.

   - **Tile 4 — Recent activity:**
     ```sql
     SELECT name, region, updated_at
     FROM lens_all_companies
     ORDER BY updated_at DESC
     LIMIT 10;
     ```
     Display: table.

3. Save the dashboard. Take a screenshot for `WORKBENCH/tim/m5-acceptance-evidence/`.

**Expected on FixtureConnector STANDARD seed=42:** Tile 1 reads 50; Tile 2 + 3 show non-trivial distribution; Tile 4 shows 10 recent rows.

---

## 5. Authoring the Lens-B dashboard

**When to use:** the second M5-acceptance dashboard. Surfaces the eu-west subset (the M4 Δ1 region values are lowercase per the deployed corpus).

**Step-by-step:** mirror §4 but query `lens_eu_west_companies` instead of `lens_all_companies`. Name the dashboard `CIP Lens-B — EU-West Companies`.

**Expected counts on FixtureConnector STANDARD seed=42:** ~10 of 50 companies (eu-west is one of 5 evenly-distributed region values; precise count depends on Faker draw under seed 42). The exact subset is locked in `tests/integration_mesh/test_lens_golden_snapshots.py`.

---

## 6. Lens Switcher dashboard pattern

**When to use:** demonstrating that switching lenses changes the row set without changing the question — the P-21 Multi-Lens-by-Default proof in operator-facing form.

**Step-by-step:**

1. New dashboard: `CIP Lens Switcher`.
2. Add a single question (Native SQL):
   ```sql
   SELECT count(*) AS row_count FROM {{lens_view}};
   ```
3. In the parameter panel: define `lens_view` as a text parameter with allowed values `lens_all_companies`, `lens_eu_west_companies`. Default: `lens_all_companies`.
4. Save. Switch the parameter at runtime; row count flips between ~50 and ~10.

**Why this matters:** the same SQL question, the same role, the same connection — different views give different data. P-21 in action: the lens shape decides the data surface; the question is shape-agnostic.

### 6.4 How to verify RLS isn't bypassed

This is the security-model regression check. Run before believing the dashboards.

1. Open Metabase `+ New` → `SQL question`. Pick the `CIP Fixture (Phase 1)` connection.
2. Type:
   ```sql
   SELECT * FROM cip_companies LIMIT 1;
   ```
3. Click `Run`. **Expected:** error from Postgres reading `permission denied for table cip_companies`.
4. If the query SUCCEEDS — the security model has drifted. STOP, escalate to Atlas + Tim. Do not proceed with dashboard authoring. The grant matrix is broken.
5. Bonus check — cross-tenant isolation:
   ```sql
   SET app.current_tenant = 'b0000000-0000-0000-0000-000000000002';
   SELECT count(*) FROM lens_all_companies;
   ```
   Expected: row count differs from the TENANT_A count (likely zero, since tenant B has no fixture data unless seeded). Both checks together prove the view's tenant predicate is doing the work.

---

## 7. Common pitfalls

- **GUC not set returns zero rows, not all rows.** The view's `WHERE tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid` evaluates to `WHERE tenant_id = NULL` when the GUC is unset, which excludes every row (NULL ≠ any tenant_id). This is intentional safe-fail behavior. Symptom: empty dashboards. Fix: ensure Init SQL is set on the database connection (§2 step 10).
- **Init SQL must be set per-CONNECTION, not per-question.** Metabase opens a connection pool; the Init SQL runs once per checkout. If you change the Init SQL, restart the connection (in Metabase admin: edit connection, save — this triggers a pool refresh).
- **`SET LOCAL` vs `SET` in Init SQL.** The migration's view uses `current_setting(..., true)` which works with either. Metabase's Init SQL convention is plain `SET` (session-level) — use that.
- **Superuser BYPASSRLS.** Not a concern here because `cip_metabase_role` is `NOSUPERUSER NOBYPASSRLS`. Documented for awareness if you ever connect Metabase as the postgres superuser (DON'T — but if you accidentally do, RLS would be bypassed and the view's WHERE would be the only safety).
- **`METABASE_DB_PASSWORD` rotation.** Out-of-band — not via alembic re-run. To rotate:
  1. Generate a new password (32+ chars, mixed case + digits + symbols).
  2. In Railway: update `METABASE_DB_PASSWORD` env var on the foundry-cip service.
  3. Run a manual SQL: `ALTER ROLE cip_metabase_role PASSWORD '<new>';` (executed as a superuser via Railway DB shell or your local psql with admin creds).
  4. Update Metabase's stored password (admin: edit connection, paste new value, save).
  5. Verify a dashboard still loads.
- **The migration's test sentinel password.** If you see `pytest_test_password_DO_NOT_USE_IN_PROD` as the role's password in production, the `METABASE_DB_PASSWORD` env var is missing on Railway. Set it immediately + run the rotation procedure above to swap to a real password.

---

## 8. Reference: fixture lens definitions

| View | Filter (SQL) | filter_config (M4 dict) | Expected row count (seed=42 STANDARD) |
|------|--------------|------------------------|---------------------------------------|
| `lens_all_companies` | `WHERE tenant_id = current_setting('app.current_tenant')::uuid` | `{}` | 50 |
| `lens_eu_west_companies` | `WHERE tenant_id = ... AND region = 'eu-west'` | `{"region": "eu-west"}` | ~10 (deterministic per seed; locked by snapshot SHA in `tests/integration_mesh/test_lens_golden_snapshots.py`) |

---

## 9. Forward compatibility

- **Multi-tenant Metabase (Phase 2+).** The single-tenant Init SQL pin is the Phase 1 tradeoff per VISION §S6. Phase 2 multi-tenant can take one of three shapes — per-tenant Metabase Collections, per-tenant DB connections, or a parameter-driven tenant switcher. That's a Metabase-project design call, not foundry-cip's problem.
- **Auto-update commit-watcher (Phase 2 — task #143).** When a row is INSERTed/UPDATEd in `cip_views`, the watcher will emit a CREATE-OR-REPLACE-VIEW migration to keep `lens_*` views in sync with the lens definitions. Until that lands, `cip_views` and `lens_*` can drift; the M5 dashboards reference the M4-deployed Lens-A and Lens-B which DO have matching `lens_*` views. (Earlier-draft notes attributed this to M6 — corrected on M7 read-through.)
- **Phase 4 REST/MCP/chatbot consumers** query the same `lens_*` views (per plan v3 §2.8). Single read-side abstraction across humans + agents.
- **Phase 2.5 write-back** uses a separate role (`cip_writeback_role`, per plan v3 §2.7). M5's `cip_metabase_role` stays read-only.

---

## 10. Where to get help

- **Initial setup or auth failures:** Tim (Railway access), Atlas (architectural review).
- **Dashboard authoring questions:** Atlas (understands lens semantics; can advise on what to surface and how).
- **Security-model regression** (e.g., §6.4 raw-table query succeeds): STOP — open an inbox note at `internal-tooling/inboxes/tims-inbox.md` flagging "M5 cip_09 grant-matrix drift detected" with the SQL output. Atlas reviews + decides next steps.
- **PM scope:** `e47f3cf4-89dc-4b31-9c88-08f13a072300` (M5 — Metabase platform service).
- **Acceptance evidence:** `WORKBENCH/tim/m5-acceptance-evidence/` (operator-side; not in foundry-cip repo).
