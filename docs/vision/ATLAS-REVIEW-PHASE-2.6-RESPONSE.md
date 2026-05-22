---
id: CIP-FW-003
uuid: 8d4a7c2e-9f1b-4e8d-a6c3-5b2f9a8d1e7c
title: Atlas Review Response — Phase 2.6 Cross-Tenant Lens-Mirror (locked plan)
type: framework
owner: tim
solve_for: Atlas's deep plan locking the Phase 2.6 architecture (PM scope
  306008ec). Returned 2026-05-22. Unblocks scopes 220 / 230 / 240 / 260
  + introduces a new 2.6 source-side requirement (cip_24).
stage_label: adopt
domain: meta
version: '1.0'
created: '2026-05-22'
last_modified: '2026-05-22'
last_reviewed: '2026-05-22'
review_cadence: 90
authority_decisions:
- 306008ec
references:
- CIP-FW-002
- CIP-SPEC-010
---

# Atlas Review Response — Phase 2.6 Cross-Tenant Lens-Mirror

Atlas's deep plan against `foundry-cip` @ HEAD `4ad6ffa`, returned 2026-05-22.
Unblocks PM scopes `62b01382` (220 schema), `280a2f20` (230 capability),
`12550346` (240 provisioning), `7bde40e3` (260 docs) + introduces a new
2.6 source-side requirement filed as a new scope.

## Decisions locked

| Q | Decision | One-liner |
|---|----------|-----------|
| Q1 | **(b) sidecar JSONB `companion_data`** — endorsed, sharpened | New column distinct from existing `properties`/`metadata`; enforcement via column-level GRANT to Twenty's role, NOT persister changes |
| Q2 | **Coexist** (mirror + grant) with a picking rule | Mirror = own-and-enrich; Grant = read-only cross-tenant. PS's Phase 3 grant-in to Wayward is **superseded** by 2.6 mirror; rest of Phase 3 stays |
| Q3 | **(B) authority enum stays per-row** | Orthogonal to companion. Authority = write-event provenance (row); companion = field-ownership (column). Don't overload one mechanism |
| Q4 | **Safe — premise was wrong** | The deployed orchestrator already separates read connection (`stream_records`) from write connection (per-batch `Session`). No "two GUC swaps in one session." |
| Q5 | **Split — with a correction** | Dest-side PS lens recut → Phase 2.7. **Source-side entity lenses REQUIRED in 2.6**: `lens_china_*` is deals-only and can't feed companies/contacts/tickets |

**Net: zero blocking Tim decisions.** 2.6 is ship-implementable solo.

## Atlas's correction set

Five things the original handoff under-stated or missed:

### C-1 — Mirror is two-pass, not a drop-in connector

PS `cip_clients` are *created dynamically* (one per Chinese brand, dedup by upstream HubSpot `company_id`) — inverting the normal "seed clients first, attach data after" flow. `CIPRow.target_table` is per-row so mixed-table emission is possible, but the persister doesn't return ids for resolved FKs. **Resolution: a two-pass orchestrator** (template: `scripts/orchestrate_wayward_backfill.py`):

- **Pass 1:** read deals → distinct upstream `company_id`s → upsert `cip_clients` → read back → build `{company_id → PS client_id}` lookup
- **Pass 2:** read companies/contacts/deals/tickets → write with resolved `client_id` FK

### C-2 — `initial_intake_route` is post-sync NULL-backfill, NOT a mapper field

The persister overwrites all `domain_cols` on UPDATE; emitting `initial_intake_route` as a mapper field would have re-written it every sync. **Resolution:** idempotent post-sync SQL:

```sql
UPDATE cip_clients
SET initial_intake_route='wayward'
WHERE tenant_id=:ps AND initial_intake_route IS NULL
```

Never overwrites a later route. Do NOT add insert-only semantics to the persister.

### C-3 — `'lens-mirror'` sync_mode needs a CHECK extension

`cip_sync_runs.sync_mode` CHECK is `IN ('full','incremental','backfill')` per `cip_03` + `cip_11`. A new value needs a tiny CHECK-extending migration. **Template: `cip_11_sync_mode_backfill.py`.**

### C-4 — Knowledge-layer mirror is OUT of 2.6 scope

PS gets its own CIP-Pinecone namespace + R2 prefix per Hard Split. Re-embedding mirrored entities into PS's CIP-Pinecone namespace is a Knowledge-layer follow-on (Phase 2.8?), not part of 2.6. **Don't cross CIP-Pinecone with Foundry-Pinecone.**

### C-5 — Companion edits aren't historized (known limitation)

`_archive_to_history` only copies columns present on history tables; we're deliberately NOT adding `companion_data` to `_history`. So Twenty's direct `UPDATE companion_data` bypasses the persister and doesn't get a SCD-2 history row. **Acceptable for 2.6; a 2.7+ trigger or service can add it.**

## Migration numbering (Atlas correction)

The handoff said `cip_22_initial_intake_route` but `cip_22_data_plane_safety_net` shipped 2026-05-22. **Next free: `cip_23`.**

Recommended migration shape (one schema migration, one views migration, one role migration):

- **`cip_23_phase26_schema.py`** — `companion_data JSONB NOT NULL DEFAULT '{}'::jsonb` on the 5 PS-relevant tables (`cip_clients`, `cip_companies`, `cip_contacts`, `cip_deals`, `cip_tickets`) — NOT `_history`. Plus `initial_intake_route TEXT NULL` on `cip_clients` (no CHECK). Plus extend `cip_sync_runs` sync_mode CHECK to include `'lens-mirror'`. Tier C migration.

- **`cip_24_china_entity_lenses.py`** — source-side companion views: `lens_china_companies`, `lens_china_contacts`, `lens_china_tickets`. Each joins back to a China-attributed deal (the subset is defined BY deal attribution, not by an independent property). Pattern: `cip_18_wayward_attr_lenses.py`. Registered in `cip_views`.

- **`cip_25_project_silk_tenant_role.py`** — `cip_twenty_project_silk` role (NOSUPERUSER NOBYPASSRLS LOGIN). `SELECT` on the 5 entity tables; column-level `UPDATE (companion_data)` ONLY on those tables. RLS scopes to PS tenant. Model: `cip_21_project_silk_grant_role.py`.

## ROADMAP changes (Atlas proposes; CC/Tim execute)

1. Insert Phase 2.6 between 2.5 and 3 in `docs/vision/ROADMAP.md` — currently only exists in PM scope `306008ec`.
2. Phase 3's "Project Silk grant-in to Wayward" line is **superseded** by 2.6 mirror; replace with a pointer.
3. Rest of Phase 3 (grant runtime, `cip_cross_tenant_grants`, Rocky Ridge onboarding, grant-window/authority-floor) **all stays unchanged**.
4. New doc `docs/CROSS-TENANT-ACCESS-PATTERNS.md` — both patterns + picking rule.

## Twenty role enforcement pattern (Q1)

```sql
-- cip_twenty_project_silk: NOSUPERUSER NOBYPASSRLS LOGIN, modeled on cip_21
GRANT SELECT ON cip_companies, cip_contacts, cip_deals, cip_tickets, cip_clients
       TO cip_twenty_project_silk;
GRANT UPDATE (companion_data) ON cip_companies TO cip_twenty_project_silk;  -- column-level
GRANT UPDATE (companion_data) ON cip_contacts TO cip_twenty_project_silk;
GRANT UPDATE (companion_data) ON cip_deals    TO cip_twenty_project_silk;
GRANT UPDATE (companion_data) ON cip_tickets  TO cip_twenty_project_silk;
GRANT UPDATE (companion_data) ON cip_clients  TO cip_twenty_project_silk;
-- No UPDATE on any source column. No INSERT/DELETE. RLS scopes to PS tenant.
```

Twenty can update `companion_data` and nothing else, only on PS rows.

## Picking rule (mirror vs grant, deliverable for the cross-tenant docs)

> Need to OWN and ENRICH (companion fields, own workflows, own lens recut)? → **Mirror.**
> Only need to READ without owning? → **Grant.**

PS is the first mirror case. Foundry-self cross-tenant synthesis (Phase 7) is the grant case.

## Tests Atlas calls out

- Q1 tests: (1) mirror can't clobber companion; (2) Twenty role: `UPDATE companion_data` ok, `UPDATE name` → permission denied; (3) INSERT leaves `'{}'`; (4) SCD-2 writes no history when only `companion_data` changes; (5) RLS holds on companion.
- Q4 tests: C1 cross-tenant isolation; C2 two-connection proof; C3 fail-closed (no GUC → zero rows); C4 advisory lock (concurrent → `SyncAlreadyRunningError`).
- Conformance + dedup + intake-route insert-only-via-backfill + sync_mode recorded.

## Implementation pointers (verbatim from Atlas)

**No change** to `persister.py` / `orchestrator.py` / `tenant_context.py` / `base.py` for authority/companion — that's the point of Q1=(b)+role-grants and Q4=two-connections.

- New: `cip/integration_mesh/connectors/lens_mirror/{connector.py, mapper.py}` — connector holds `source_tenant_id` + source lens names; `stream_records()` opens its OWN short-lived connection, `SET LOCAL app.current_tenant=<source>`, SELECTs, **materializes fully into memory**, closes source connection, yields buffered dicts. Orchestrator persists under GUC=PS as for HubSpot/Zendesk.
- New: `scripts/orchestrate_ps_lens_mirror.py` — two-pass orchestration + intake-route post-sync backfill + two triggers (event-on-EcomLever-sync-completion + 30-min poll). Template: `orchestrate_wayward_backfill.py`.

## Boundary conditions Atlas reaffirms

- Hard Split (CIP-SPEC-010) is binding — no proposals that cross CIP-Pinecone with Foundry-Pinecone or that put CIP-shaped data into Foundry-Knowledge.
- Phase 1 closed — no changes.
- Phase 2.5 parked — may reshape its authority enum design but cannot retire it. (Atlas's Q3 verdict: keep authority per-row, so Phase 2.5's design stands.)

---

_Grounded against foundry-cip @ `4ad6ffa`. Unblocks PM `306008ec` → 220 / 230 / 240 / 260._
