---
id: CIP-SOP-010
uuid: 3e5c7ce1-0bd8-4009-b8b4-b1385d09b28e
title: Tenant Onboarding Checklist
type: sop
owner: tim
solve_for: Terse copy-pasteable checklist for standing up a new CIP tenant end-to-end.
  Pairs with ONBOARDING-A-NEW-TENANT (the why + what-to-investigate runbook).
stage_label: adopt
domain: ops
version: '1.0'
created: '2026-04-21'
last_modified: '2026-05-16'
last_reviewed: '2026-05-16'
review_cadence: 90
milestone: Phase-1-M8
---

# Tenant Onboarding Checklist

> **Pairs with [`ONBOARDING-A-NEW-TENANT.md`](ONBOARDING-A-NEW-TENANT.md)** (CIP-SOP-009) — that doc explains the *why* and *what-to-investigate-first*. This doc is the terse *how* — a literal checklist an operator can copy and execute. Walked end-to-end against the EcomLever+Wayward onboarding (2026-05-15→16), with lessons baked in.

## When to use

You are onboarding a new venture as a CIP tenant. The venture has at least one source system to ingest (HubSpot, Zendesk, Plaid, etc.) and at least one operator who can answer questions about the data.

**Not for:** adding a second client *inside* an existing tenant (that's a `cip_clients` INSERT — see §5); adding a new connector to an existing tenant (that's [`CIP-SOP-001 CONNECTOR-AUTHORING-GUIDE`](CONNECTOR-AUTHORING-GUIDE.md)).

## Phase 0 — Naming + identity (canonical UUIDs)

> **CRITICAL:** Per PM decision `c575c81c` (2026-05-16 — EcomLever/Wayward tenant-model correction), **never use placeholder UUIDs**. The right model is tenant=operator/venture, clients=subjects-of-intelligence inside the tenant.

| Step | Action | Verify |
|------|--------|--------|
| 0.1 | Decide what the **tenant** is (the operator/venture — e.g., EcomLever) | One name, one slug, no ambiguity |
| 0.2 | Decide what the **clients** inside the tenant are (subjects of intelligence — e.g., Wayward) | Each client has a unique slug within the tenant |
| 0.3 | Generate `tenant_id` UUIDv4 (or use existing if tenant pre-exists in JOS) | `python -c "import uuid; print(uuid.uuid4())"` |
| 0.4 | Generate deterministic `client_id` UUIDv5 from `(tenant_id, slug)` per the canonical helper in `cip/integration_mesh/wayward_constants.py` | `uuid5(tenant_uuid, slug)` |
| 0.5 | If the tenant is a known venture (e.g., already in PM), register the canonical UUIDs in `cip/integration_mesh/<venture>_constants.py` | Module exports `<VENTURE>_TENANT_ID`, `<CLIENT>_CLIENT_ID` |

## Phase 1 — Prerequisites (one-time per tenant)

| Step | Action | Verify |
|------|--------|--------|
| 1.1 | DB reachable: `DATABASE_URL=$DATABASE_PUBLIC_URL alembic current` returns `cip_NN_<...>` (head) | No connection error; revision matches `alembic heads` |
| 1.2 | Source-system credentials in a per-venture secrets file (e.g., `.foundry-secrets.yaml`) — NEVER in chat or code | Test auth: `curl -sH "Authorization: Bearer $TOKEN" <vendor-API-root>` |
| 1.3 | If using Pinecone: namespace allocated for tenant; index reachable | Pinecone console shows namespace |
| 1.4 | If using R2 (cip_files staging): bucket reachable + write access | Test write: small object to `cip-files/<tenant_uuid>/healthcheck` |
| 1.5 | Tenant exists in JOS-governed `tenants` table (if working under JOS-S15 venture rules) | `SELECT * FROM tenants WHERE tenant_id = '<uuid>'` returns one row |

## Phase 2 — Register the tenant in CIP

| Step | Action | Verify |
|------|--------|--------|
| 2.1 | Write a one-shot migration `cip_NN_seed_<venture>.py` mirroring `cip_12_seed_wayward_client.py` shape | Migration includes idempotent `ON CONFLICT (tenant_id, slug) DO NOTHING` |
| 2.2 | Migration sets `app.current_tenant` via `set_config` so RLS lets the INSERT through | First line of upgrade: `op.execute("SELECT set_config('app.current_tenant','<uuid>',true)")` |
| 2.3 | Run: `DATABASE_URL=$DATABASE_PUBLIC_URL alembic upgrade head` | New rows in `cip_clients` for the tenant; `alembic current` shows the new revision |
| 2.4 | If superseding a placeholder UUID: write + run a data migration like `scripts/migrate_b0_to_ecomlever.py` (per-table SAVEPOINTs to prevent transaction poisoning) | Verification queries show 0 rows at the old UUID, expected counts at the new UUIDs |

## Phase 3 — Connector setup (per source system)

> For each source system the tenant has data in, run Phase 3 once.

| Step | Action | Verify |
|------|--------|--------|
| 3.1 | If the connector doesn't yet exist in `cip/integration_mesh/connectors/<vendor>/`: build it per [`CIP-SOP-001 CONNECTOR-AUTHORING-GUIDE`](CONNECTOR-AUTHORING-GUIDE.md) | 8-test conformance harness passes |
| 3.2 | If connector exists: confirm it supports the tenant's source-system version/edition | Vendor API quickstart returns expected entity shape |
| 3.3 | Write a `run_<venture>_<vendor>_initial_sync.py` script under `scripts/` mirroring `scripts/run_wayward_initial_sync.py` | Script imports `<VENTURE>_TENANT_ID`, `<CLIENT>_CLIENT_ID` from venture_constants |
| 3.4 | Discovery sample run: `--limit 100` first, confirm shape, fix any auth/scope issues before full backfill | Sample data lands in `cip_*` tables, all rows tagged with correct tenant_id + client_id |

## Phase 4 — Full backfill

| Step | Action | Verify |
|------|--------|--------|
| 4.1 | Use the batched persister (`cip/integration_mesh/batched_persister.py`) — 100-200x speedup over per-record persistence | Backfill commits in chunks; `cip_sync_runs` shows progress every batch |
| 4.2 | Backfill order: companies → contacts → deals → tickets → files. Engagements (HubSpot calls/notes) + ticket comments are *separate* later passes when those connectors land. | Each entity backfill completes before next starts |
| 4.3 | Watch for rate-limit 429 responses; orchestrator handles backoff but sustained 429s warrant a token-bucket recalibration | `cip_sync_runs.error_detail` shows handled vs unhandled errors |
| 4.4 | After backfill: row counts per `cip_*` table match (within tolerance) the source-system counts | `SELECT COUNT(*) FROM cip_companies WHERE tenant_id = '<uuid>' AND client_id = '<client_uuid>'` |

## Phase 4.5 — Property Annotation Interview (the Glossary phase)

> **Per [`CIP-SOP-016 PROPERTY-GLOSSARY-PATTERN`](PROPERTY-GLOSSARY-PATTERN.md).** Skipping this turns every future query into "what does column X mean?" archaeology. Don't skip.

| Step | Action | Verify |
|------|--------|--------|
| 4.5.1 | Auto-baseline discovery: query each source's properties endpoint (e.g., HubSpot `/crm/v3/properties/{type}`) — pulls labels + vendor descriptions | All columns listed under each entity in a discovery report |
| 4.5.2 | Create `docs/tenants/<tenant_uuid>/GLOSSARY.md` with one section per entity, one row per column | Frontmatter includes `tenant_uuid` and (per-client) `client_uuid` |
| 4.5.3 | For high-traffic columns (top ~30 per entity), do the operator interview: confirm meaning, mark `verified` | Each verified entry has plain-English meaning + top values + coverage stats |
| 4.5.4 | For medium-confidence columns, mark `inferred` with caveat | Description includes "Inferred from name + sample data; verify before relying on this" |
| 4.5.5 | Long-tail columns stay `tentative` (auto-baseline only) — fine | Confidence distribution: ≥10 verified, rest tentative; no `unknown` for active columns |
| 4.5.6 | Run `scripts/seed_glossary_into_registry.py` to materialize markdown → `cip_connector_property_registry` | DB confidence counts match markdown |

## Phase 5 — Add additional clients inside the tenant (if needed)

| Step | Action | Verify |
|------|--------|--------|
| 5.1 | Generate `client_id` UUIDv5 from `(tenant_id, slug)` | `python -c "from uuid import uuid5; print(uuid5(tenant_uuid, 'slug'))"` |
| 5.2 | INSERT into `cip_clients` (idempotent via `ON CONFLICT (tenant_id, slug) DO NOTHING`) | `SELECT * FROM cip_clients WHERE tenant_id = '<t>' AND slug = '<s>'` |
| 5.3 | Update any backfill scripts to scope to the new client | Script sets `client_id` on persisted rows |

## Phase 6 — Lens configuration (per business question)

> Lenses materialize filtered perspectives. Add one per business question that recurs (e.g., "Chinese clients attributed to Tim").

| Step | Action | Verify |
|------|--------|--------|
| 6.1 | Per [`CIP-SOP-003 LENS-AUTHORING-GUIDE`](LENS-AUTHORING-GUIDE.md): write the lens YAML config + register in `cip_views` | `SELECT name, source_connector FROM cip_views WHERE tenant_id = '<t>'` shows new lens |
| 6.2 | If the lens needs a SQL view (recurrent dashboard / Metabase use): write a migration adding `lens_<tenant>_<name>` view | `SELECT * FROM lens_<...> LIMIT 1` returns expected shape |
| 6.3 | Grant SELECT on the lens view to `cip_metabase_role` | `\dp lens_<...>` shows the grant |
| 6.4 | Golden-snapshot the lens output for regression detection | `tests/integration_mesh/test_lens_golden_snapshots.py` extended |

## Phase 7 — Tenant Manifest regeneration

> Per [`CIP-SOP-016 PROPERTY-GLOSSARY-PATTERN`](PROPERTY-GLOSSARY-PATTERN.md) and PM scope `bfc3d5d0` (done). The manifest is the self-describing data directory for the tenant.

| Step | Action | Verify |
|------|--------|--------|
| 7.1 | `DATABASE_URL=$DATABASE_PUBLIC_URL python scripts/generate_tenant_manifest.py <tenant_uuid>` | Writes `docs/tenants/<tenant_uuid>/MANIFEST.md` |
| 7.2 | Manifest sections present: Tenant identity, Clients, Tables populated, Connector sync health, Property catalog, Lenses, Cross-references | All sections non-empty (except Lenses if Phase 6 deferred) |
| 7.3 | Per-client row breakdowns match Phase 4 counts | No rows attributed to NULL client_id (unless intentional) |

## Phase 8 — Four-access-paths gate

> Per [`CIP-SPEC-001 FOUR-ACCESS-PATHS`](FOUR-ACCESS-PATHS.md). All four paths must return non-empty results before declaring tenant green.

| Path | Verify |
|------|--------|
| **Path 1 — Structured SQL** | A `SELECT ... FROM cip_companies LIMIT 5` under tenant context returns expected rows |
| **Path 2 — Knowledge layer** | (If Pinecone wired) A semantic search against the tenant's namespace returns non-empty results. If knowledge ingestion isn't yet wired for this tenant: acceptable, mark deferred |
| **Path 3 — Knowledge graph** | (If FalkorDB wired) A graph query returns the expected node count. Same defer rule as Path 2 |
| **Path 4 — Originals via cip_files** | `SELECT * FROM cip_files WHERE tenant_id = '<t>' LIMIT 5` returns rows pointing at staged R2 objects |
| **Cross-tenant probe** | `SET LOCAL app.current_tenant = '<DIFFERENT-TENANT-UUID>'; SELECT * FROM cip_companies WHERE client_id = '<our-client>'` returns ZERO rows |

## Phase 9 — Glossary + manifest commit + PM tracking

| Step | Action | Verify |
|------|--------|--------|
| 9.1 | Commit `docs/tenants/<tenant_uuid>/GLOSSARY.md` + `MANIFEST.md` to foundry-cip master | `git log -1 --stat` shows both files |
| 9.2 | File a PM decision summarizing the onboarding (rows ingested, glossary coverage, deferred items) | `foundry_mcp_pm_decision_create` with `decision_type='configuration'` |
| 9.3 | Update the Wayward-v1-style PM scope (`da6a0110` is Wayward's; new tenants get their own) with status + remaining work | Scope comment on PM |
| 9.4 | (Optional) Update `wayward_constants.py`-style module if new canonical UUIDs need centralization | Module exports |

## Phase 10 — Rollback / teardown (if needed)

| Step | Action | Verify |
|------|--------|--------|
| 10.1 | Stop scheduled syncs for the tenant (`scripts/jos check --repo .` after disabling cron jobs) | No new `cip_sync_runs` rows after the cutoff |
| 10.2 | Decide on data: delete via migration vs preserve for audit | Decision recorded in PM |
| 10.3 | If deleting: `DELETE FROM cip_companies WHERE tenant_id = '<t>'` (cascades via FK chains where defined) | Row counts hit 0 |
| 10.4 | Revoke source-system credentials at the vendor side | Vendor token list shows revoked |
| 10.5 | Archive `docs/tenants/<tenant_uuid>/` to `docs/tenants/_archived/<tenant_uuid>-<YYYY-MM-DD>/` | Files moved; replace with a single tombstone note linking the rollback decision |

## Onboarding "good looks like" — the green light

A new tenant is fully onboarded when:

- [ ] Phase 0–7 all checkboxes complete
- [ ] Phase 8 four-access-paths gate green (or Path 2/3 explicitly deferred)
- [ ] `MANIFEST.md` auto-generated and committed
- [ ] `GLOSSARY.md` has ≥10 `verified` entries for the active first-class columns
- [ ] PM decision filed; scope updated
- [ ] No rows tagged with placeholder UUIDs anywhere
- [ ] `jos check` PASSes (per JOS-R18 / R06 / R17)

## Lessons baked in (from Wayward 2026-05-15→16)

1. **Use canonical UUIDs from Phase 0** — the placeholder `b0000000-...` cost a 1.25M-row remigration.
2. **Property glossary is non-optional** — without it, every later query becomes archaeology (the Tim/Eric attribution research took 4 round-trips guessing `paid_referral` / `rev_share_partner` / `deal_owner` before finding `source`).
3. **Per-table SAVEPOINTs in data migrations** — naive `with engine.begin()` poisons all sub-transactions when one fails.
4. **Discovery sample before full backfill** — `--limit 100` first catches auth scope mismatches and shape surprises before you've waited 30 minutes for a failed full backfill.
5. **Batched persister always** — 100-200x speedup over per-record. Per-record persistence is the wrong shape at any nontrivial volume.

## Cross-references

- [`CIP-SOP-009 ONBOARDING-A-NEW-TENANT.md`](ONBOARDING-A-NEW-TENANT.md) — the why + what-to-investigate runbook
- [`CIP-SOP-001 CONNECTOR-AUTHORING-GUIDE.md`](CONNECTOR-AUTHORING-GUIDE.md) — for building a new vendor connector
- [`CIP-SOP-002 MIGRATION-RUNBOOK.md`](MIGRATION-RUNBOOK.md) — for the alembic side
- [`CIP-SOP-016 PROPERTY-GLOSSARY-PATTERN.md`](PROPERTY-GLOSSARY-PATTERN.md) — Phase 4.5 detail
- [`CIP-SOP-003 LENS-AUTHORING-GUIDE.md`](LENS-AUTHORING-GUIDE.md) — Phase 6 detail
- [`CIP-SPEC-001 FOUR-ACCESS-PATHS.md`](FOUR-ACCESS-PATHS.md) — Phase 8 gate
- PM decision `c575c81c` — canonical-UUID rule (Wayward correction)
- PM scope `da6a0110` — Wayward v1 (first real-world walkthrough)
