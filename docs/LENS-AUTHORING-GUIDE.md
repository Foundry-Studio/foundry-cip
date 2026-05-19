---
id: CIP-SOP-003
uuid: b68b1316-aee6-4de4-bfb6-78a4a88da7cd
title: Lens Authoring Guide
type: sop
owner: tim
solve_for: Procedure for adding new lens views so analysts and agents can author filtered
  perspectives consistently.
stage_label: adopt
domain: dat
version: '1.0'
created: '2026-04-21'
last_modified: '2026-05-11'
last_reviewed: '2026-05-19'
review_cadence: 90
milestone: Phase-1-M7
---

# Lens Authoring Guide

> **Status:** draft — populated 2026-05-09 alongside the M4 Lens Engine landing; M7 read-through 2026-05-11 corrected the M5/M6 milestone-row descriptions in §Related (M5 was Metabase platform service, NOT knowledge-text materialization; M6 was discoverability verification, NOT operator extensibility — operator extensibility is a Phase 2 lift). Reflects the deployed lens engine surface. Filter operator extensibility (Phase 2+), cross-table joins (Phase 2+), and JSONB-overflow filtering (Phase 2+) are documented as forward-compat in §7 but not buildable today.

## Purpose

Teach an engineer how to author a new Lens against `cip_*` structured data: row anatomy, filter-config schema, the authoring workflow, composition with tenant context, and the workarounds available when M4's equality-only filter doesn't cover a use case.

## Who reads this

- Engineers defining tenant lenses (Phase 1 ships Lens-A + Lens-B; Phase 2 onward authors venture-specific lenses for Wayward, Rocky Ridge, etc.).
- Reviewers validating lens PRs against the golden-file test pattern.
- Downstream consumers of lens output (four-access-paths, consumption surfaces).

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Created this stub. |
| M4 — Lens Engine | Defines `cip_views` row anatomy + `compile_filter` + `apply_lens`. **This guide reflects M4-deployed reality.** |
| M5 — Metabase platform service | First operator-facing lens consumer: M5's `cip_09` migration mirrors Lens-A + Lens-B as Postgres views (`lens_all_companies` / `lens_eu_west_companies`) and enforces P-21 via the `cip_metabase_role` grant matrix (REVOKE on `cip_*`, GRANT only on `lens_*`). |
| M6 — Discoverability registry completeness pass | Verified the `cip_views` lens catalog is queryable + cross-tenant-isolated (`tests/integration_mesh/test_discoverability_completeness.py` Tests 2 + 7). |
| M7 — Four Access Paths Validation + Doc Suite Harden | M5/M6 row corrections in this guide. Operator extensibility ($eq/$in/$gt) and cross-table joins are Phase 2+, NOT M6 deliverables. |
| Phase 2 — Wayward Onboarding | First venture-specific lenses authored against real (non-fixture) data. |

Cross-ref: `docs/architecture/principles/DESIGN-PRINCIPLES.md` §P-21 (Multi-Lens by Default), `docs/vision/VISION.md` §7g, `cip/migrations/versions/cip_02_views.py` (deployed schema).

---

## 1. What is a lens?

A **lens** is a tenant-defined query-time WHERE predicate, stored as a row in `cip_views`. It is NOT a Postgres `CREATE VIEW`, and NOT a materialized table.

When you ask "show me all eu-west companies for tenant X," the lens engine:

1. Loads the lens row from `cip_views` (RLS-scoped to tenant X).
2. Compiles the row's `filter_config` JSONB to a SQLAlchemy WHERE predicate.
3. Applies the predicate to a base `SELECT` against the target `cip_<entity>` table.
4. Hands the composed query back to the caller; results stream through PostgreSQL's RLS-enforced row filtering.

Why this shape (per P-21 + D-117 + D-120):

- **Filter configurations live as JSONB rows, not as code branches.** Adding a new lens = INSERT into `cip_views`. No DDL, no migration, no framework code change.
- **Lens output is always-fresh.** Materialized views drift on every sync; query-time application reads the current state of the base data.
- **RLS-native.** Lens loading and lens application both run inside an `apply_tenant_context()` transaction. Lens filtering is AND-composed on top of tenant scoping, never in place of it.

**Anti-patterns** (what a lens is not):

- Not a transform pipeline. Lenses do not rename, derive, or coerce field values; they pick rows.
- Not a join engine. M4 single-table only; cross-entity joins are M6+ (see §7).
- Not a write-side surface. The lens engine is read-only with respect to `cip_views` and the target table.
- Not a code branch. If a lens needs Python logic, escalate to §9 workarounds + file the M6+ requirement; do not encode it in lens engine code.

---

## 2. Lens row anatomy

Every lens is one row in `cip_views`. The columns that matter:

| Column | Type | Meaning |
|---|---|---|
| `id` | UUID | Server-default `gen_random_uuid()`. The lens's stable identifier. |
| `tenant_id` | UUID | Owning tenant. Enforced by RLS policy `cip_tenant_scope`. |
| `source_connector` | Text | **Per-lens-class identifier.** See M4 Δ2 note below. |
| `source_id` | Text | Target entity table name — one of `cip_companies`, `cip_contacts`, `cip_deals`, `cip_tickets`, `cip_files` (the deployed `_VALID_TARGET_TABLES` whitelist). |
| `view_name` | Text | Human-readable name; what callers pass to `load_lens(view_name=...)`. |
| `description` | Text | Free-text. |
| `filter_config` | JSONB | The lens predicate. See §3. Default `'{}'::jsonb` = no-op (returns all rows). |
| `is_default` | Bool | Reserved for M5/M6 (default-lens-per-table semantics). M4 ignores this flag at engine read; authors may set it but it has no behavioral effect today. |
| `ingestion_batch_id` | UUID | Required NOT NULL provenance. Author supplies any UUID at INSERT. |
| `authority` | Text | Default `'validated'`. Inherited from cip_views table-wide convention. |

Plus standard provenance + bitemporal SCD-2 history columns (`ingested_at`, `refreshed_at`, `created_at`, `updated_at`); the engine never references these.

**M4 Δ1 — region values.** The deployed `FixtureConnector` distributes `region` across five lowercase values: `us-east`, `us-west`, `eu-west`, `apac`, `latam`. Authors targeting region must use those exact strings (not `EMEA` / `NA` / `APAC` uppercase, even though those read more naturally — Phase 2+ may add an `industry_region` column with human-readable mapping).

**M4 Δ2 — UNIQUE(tenant_id, source_connector, source_id).** The deployed schema has a unique constraint on `(tenant_id, source_connector, source_id)`. **A single tenant can only have one lens per (source_connector, source_id) pair.** Two lenses on `cip_companies` for the same tenant — say "all_companies" and "eu_west_companies" — must use **different `source_connector` values** to coexist.

The convention M4 settled on (via the `seed_lens()` test helper): `source_connector = f"cip_engine_v1.{view_name}"`. Treat `source_connector` as a per-lens-class sub-namespace identifier, not a fixed string. The `cip_engine_v1.` prefix marks it as engine-authored; the suffix disambiguates lenses-per-table-per-tenant.

When you author a non-fixture connector (Phase 2+), pick a similar namespace pattern: `<your_connector_name>.<lens_view_name>`.

---

## 3. `filter_config` schema (v1, M4)

`filter_config` is a flat dict of `{field_name: value}` entries, AND-composed at query time. Each entry compiles to `WHERE <field_name> = <value>`. Empty `{}` is a no-op (returns all rows).

**Supported value types:** `str`, `int`, `bool`, `None` (compiles to `IS NULL`).

**Unsupported (raises `LensCompilationError`):**

- `list`, `dict`, `date`, `datetime`, anything else.
- v2-style operator dicts (`{"region": {"$eq": "eu-west"}}`) — fail-fast guard so accidental v2 syntax raises today.
- `$`-prefixed field names — entire `$` namespace reserved for v2 operator extensibility.
- Provenance / SCD / tenancy columns (`tenant_id`, `id`, `created_at`, `updated_at`, `ingestion_batch_id`, `valid_from`, `valid_to`, `is_current`, etc.) — see `_RESERVED_COLUMNS` in `cip/integration_mesh/lens_engine/compiler.py`. RLS already covers tenancy; filtering on infra columns is a foot-gun.
- `filter_config` size > 32 keys (DoS guard; JSONB allows ~1GB; capped at 32).
- Field names not present on the target entity table.

**Examples (valid):**

```json
{}                                                  // no-op, returns all
{"region": "eu-west"}                               // single equality
{"region": "eu-west", "industry": "tech"}           // AND-composed
{"region": null}                                    // IS NULL
{"is_current": true}                                // bool — would be valid IF is_current weren't reserved
```

**Examples (invalid, will raise):**

```json
{"region": ["eu-west", "us-east"]}                  // list value → unsupported type
{"region": {"$in": ["eu-west", "us-east"]}}         // v2 operator dict → fail-fast
{"$where": "..."}                                   // forbidden operator token
{"tenant_id": "..."}                                // reserved column
{"name_like": "Acme%"}                              // unknown column on target table
```

When an invalid filter is loaded, `apply_lens()` raises `LensCompilationError` with a diagnostic message naming the offending field + the available columns.

---

## 4. Authoring a new lens

Step-by-step:

1. **Pick a target table** from the whitelist: `cip_companies`, `cip_contacts`, `cip_deals`, `cip_tickets`, `cip_files`.
2. **Design `filter_config`.** Stick to v1 shape (equality on one or more fields). If your filter needs `IN` / range / nested predicates — see §9 workarounds.
3. **Pick a `view_name`.** Human-readable; describe purpose (`active_eu_customers`, `closed_won_deals_q3`, etc.). Unique per tenant.
4. **Pick a `source_connector`.** Use `f"cip_engine_v1.{view_name}"` to satisfy the UNIQUE constraint. (Or whatever sub-namespace your connector convention uses.)
5. **INSERT into `cip_views`.** Under `apply_tenant_context()` so RLS accepts the row. The deployed migration's NOT NULL columns (`tenant_id`, `source_connector`, `source_id`, `ingestion_batch_id`, `view_name`, `filter_config`) must all be supplied.
6. **Query through the engine:**

```python
from cip.integration_mesh import lens_query_for_table
from cip.integration_mesh.tenant_context import apply_tenant_context
from sqlalchemy.orm import Session
import sqlalchemy as sa

# Reflect (or import a pre-defined Table object for) the target entity.
md = sa.MetaData()
md.reflect(bind=engine, only=["cip_companies"])
companies = md.tables["cip_companies"]

with Session(engine, autoflush=False) as db, db.begin():
    apply_tenant_context(db, tenant_id)
    query = lens_query_for_table(
        db,
        tenant_id=tenant_id,
        view_name="active_eu_customers",
        target_table=companies,
    )
    rows = db.execute(query).all()
```

7. **Add a golden-file test.** Snapshot the canonical-JSON SHA-256 of the output. Pattern: `tests/integration_mesh/test_lens_golden_snapshots.py`.

---

## 5. Composition with tenant context

`load_lens()` and `apply_lens()` both REQUIRE the caller's session to have `apply_tenant_context()` already applied:

```python
with Session(engine, autoflush=False) as db, db.begin():
    apply_tenant_context(db, tenant_id)   # ← MANDATORY before any lens call
    lens = load_lens(db, tenant_id=tenant_id, view_name="...")
    # ... lens work ...
```

**Why mandatory:**

- Lens loading is RLS-bound. Without tenant context, the GUC `app.current_tenant` is empty, RLS hides the row, `load_lens` raises `LensNotFoundError`.
- `load_lens` additionally verifies the GUC matches the passed `tenant_id` and raises `LensSecurityError` on mismatch (catches stale-GUC pool-reuse vectors). This is the M4 v2 QC1 Stress [2] hardening.
- `apply_lens` runs against `cip_<entity>` tables which also have RLS. The tenant scoping is enforced by Postgres, not by the engine.

**`SET LOCAL` semantics:** `apply_tenant_context()` uses `SET LOCAL`, which scopes the GUC to the current transaction. As soon as you commit / rollback, the GUC clears. This is intentional — it's what makes tenant context safe under PgBouncer transaction-pooling and prevents one transaction's tenant from leaking into the next.

---

## 6. Multi-tenancy

Lens rows are tenant-scoped. Tenant A cannot read Tenant B's lenses (RLS hides them). This is verified at the test level — `tests/integration_mesh/test_lens_loading.py::test_load_lens_cross_tenant_blocked_by_rls`.

**Cross-tenant lens sharing** (e.g., a "platform-wide default lens" applicable to every venture) is a Phase 3 grants-runtime feature. M4 does not support it; if you need it now, the workaround is to seed the same `(view_name, filter_config)` row per-tenant.

**Note on test environments:** the testcontainer's default user is a Postgres superuser with `BYPASSRLS`. To honestly exercise RLS in tests, the integration_mesh harness provisions `cip_rls_test_role` (NOSUPERUSER NOBYPASSRLS) and provides `session_as_role_and_tenant()` for read-side queries. This is the M4 Δ3 reconciliation — production deployments connect as non-superuser roles, so RLS enforces in the production path. Test-side honesty requires the same role.

---

## 7. Forward compatibility

What's deferred and where each item lights up:

| Feature | Deferred to | Reason |
|---|---|---|
| Operator extensibility (`$eq`, `$ne`, `$in`, `$gt`, range, `LIKE`) | Phase 2 (Wayward) | M4 ships equality-only TSP; v2 superset is dict-shaped (`{"region": {"$eq": "eu-west"}}`) and fully compatible with v1 (`{"region": "eu-west"}` reads identically). M6 (discoverability verification) did NOT include this extension, despite earlier drafts pointing here. |
| Cross-entity joins (e.g., `cip_deals` filtered by `cip_companies.region`) | Phase 2 (Wayward) | Single-table only in M4; would require a join compiler in the lens engine OR materialized denormalized views OR graph-layer query plan — none fit Phase 1 scope. |
| JSONB-overflow filtering (e.g., `properties->>'industry_region'`) | Phase 2+ | M4 filters domain columns only; overflow lives in the per-table `properties` / `metadata` JSONB column. |
| Lens authoring UX (web form, CLI) | Phase 2+ | M4 seeds via direct INSERT; tooling is venture-side. |
| Push-side lens application (outbound to Chatwoot etc.) | Phase 2 (Wayward) | M4 is read-side only. |
| Pagination / streaming for large lens results | Phase 2+ | STANDARD corpus is 50 companies; pagination unneeded. |
| Materialized lens caching | Phase 2+ TSP | Query-time application is fast at fixture scale. |
| Cross-tenant lens sharing | Phase 3 grants runtime | Multi-tenant grants is Phase 3 work. |

**v1→v2 fail-fast:** if you accidentally write a v2-style operator dict against M4's engine (`{"region": {"$eq": "eu-west"}}`), the compiler raises `LensCompilationError` with an explicit "looks like v2 operator syntax" message. This locks the v1 contract until v2 ships intentionally.

---

## 8. Reference implementation

M4's two demo lenses + the e2e test harness are the canonical reference:

- **Lens-A** — `view_name="snapshot_lens_a"` (or `"lens_a_..."`), `filter_config={}`, `target_table="cip_companies"`. Returns all 50 companies in STANDARD. The "no-op filter" baseline.
- **Lens-B** — `filter_config={"region": "eu-west"}`, `target_table="cip_companies"`. Returns the deterministic eu-west subset (~10 of 50 with seed=42 and the 5-value region distribution).

Test files (in `tests/integration_mesh/`):

- `test_lens_compiler.py` — 17 unit tests covering the compiler's full surface.
- `test_lens_loading.py` — 10 integration tests covering `load_lens` happy path + RLS-bound isolation + GUC-mismatch security.
- `test_lens_apply_e2e.py` — 5 e2e tests against real Postgres + STANDARD corpus.
- `test_lens_golden_snapshots.py` — 2 SHA-256 snapshot regression tests (Python 3.12 + PYTHONHASHSEED=0 only, matching M3's corpus determinism scoping).

The engine module:

- `cip/integration_mesh/lens_engine/exceptions.py` — `LensNotFoundError`, `LensCompilationError`, `LensSecurityError`.
- `cip/integration_mesh/lens_engine/compiler.py` — `compile_filter()`.
- `cip/integration_mesh/lens_engine/lens.py` — `Lens` dataclass, `load_lens()`, `apply_lens()`, `lens_query_for_table()`.

Public API: `from cip.integration_mesh import Lens, load_lens, apply_lens, lens_query_for_table, compile_filter, LensCompilationError, LensNotFoundError, LensSecurityError`.

---

## 9. Workarounds for unsupported filters

When v1 equality-only doesn't cover your use case, options before M6 ships operator extensibility:

### 9a. Union of equality lenses (M4-compatible)

Need `region IN ("eu-west", "us-east")`? Author two lenses (`eu_west_<x>`, `us_east_<x>`), apply each, UNION the results in Python:

```python
rows = []
for view_name in ("eu_west_active", "us_east_active"):
    with session_as_role_and_tenant(engine, tenant_id) as conn:
        q = lens_query_for_table(conn, tenant_id=tenant_id, view_name=view_name, target_table=companies)
        rows.extend(conn.execute(q).all())
```

Trade-off: two queries instead of one. For small lens sets, fine; deduplicate by primary key if needed.

### 9b. Post-fetch Python filtering (escape valve)

Author the most permissive lens that v1 supports, then narrow in Python:

```python
with session_as_role_and_tenant(engine, tenant_id) as conn:
    q = lens_query_for_table(conn, tenant_id=tenant_id, view_name="all_companies", target_table=companies)
    rows = [r for r in conn.execute(q).all() if r.created_at >= cutoff_date]
```

Trade-off: pulls more rows than needed. Acceptable at fixture scale; consider pagination + caching at production scale.

### 9c. Escalate to M6 D-number (the right move when neither workaround fits)

If a Phase 2 venture genuinely needs a v2 operator (range, `IN`-list, `LIKE`) immediately and the workarounds above are too painful, file an inbox note + new D-number proposal:

1. Write to `internal-tooling/inboxes/tims-inbox.md` describing the use case + which operator(s) are needed.
2. Atlas / Tim decide whether to cherry-pick a v2 operator subset into M4.5 (likely not — the `$eq`/`$in`/`$gt` set is cohesive) or wait for Phase 2 Wayward.
3. If accepted, the operator extension lives on the Phase 2 plan; M4's `_FORBIDDEN_OPERATOR_TOKENS` guard keeps the surface stable in the meantime.

The fail-fast guards in M4's compiler are deliberate: v1 contract fail-loud, v2 contract escalation-required. The cost of a strict v1 is real; the cost of accidentally enabling unsafe operator syntax under stress is higher.
