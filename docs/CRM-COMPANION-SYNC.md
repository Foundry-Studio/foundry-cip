---
id: CIP-OP-022
uuid: 6a3f81e2-4c5b-4d9a-9f1c-2b3e4a5d6c7f
title: CRM → CIP companion writeback (Phase 2.8 Leg B)
type: operational
owner: tim
solve_for: Operational runbook for Leg B — the CIP-owned sync job that
  reads PS-team enrichments from the Foundry-CRM and writes them into
  CIP `cip_clients.companion_data` JSONB via the restricted twenty role.
stage_label: adopt
domain: meta
version: '1.0'
created: '2026-05-23'
last_modified: '2026-05-23'
last_reviewed: '2026-05-23'
review_cadence: 180
authority_decisions:
- d342b7d1
references:
- CIP-SPEC-012
- CIP-FW-003
---

# CRM → CIP companion writeback — Leg B

This is the operational doc for Phase 2.8 Leg B (PM scope `d342b7d1`). The
field map + design rationale live in CIP-SPEC-012; this doc tells you what
the job is, how to run it, and how to read its output.

## What it does

Reads PS-team-curated brand enrichments out of the Foundry-CRM Postgres
and writes them into the matching `cip_clients.companion_data` JSONB on
the Project Silk tenant. Single-purpose reconciliation job — **not** a
`CIPConnector`. The mirror writes source fields; Leg B writes companion
fields. Different role, different column, different path.

## Run-order vs Leg A

Leg A (CIP → CRM) must run first in prod. Leg B keys CRM companies back
to CIP via `companies.external_ids->>'cip_client_id'` — that key only
exists if Leg A stamped it during its CRM-side write. With no Leg A, Leg B
selects zero rows.

Build + unit tests do not depend on Leg A (they use a CRM-shaped fixture
table inside the CIP testcontainer).

## Where it lives

- `cip/integration_mesh/sync/crm_companion_writeback.py` — pure field-map
  (`build_managed_companion`) + writer (`run_writeback`).
- `scripts/sync_crm_companion_to_cip.py` — orchestration entry; env-driven
  connection strings + the twenty role.
- `tests/integration_mesh/sync/` — pure + integration tests.

## Locked contracts

1. **Join key.** `companies.external_ids->>'cip_client_id'` (CRM) =
   `cip_clients.id` (CIP UUID PK, set by Leg A). NOT `cip_clients.source_id`.
   If a CRM row carries a `cip_client_id` not present in the PS valid set,
   Leg B skips it and counts it in `summary.dangling_ids` — never silently
   passes.

2. **Writer role.** CIP connection authenticates as `cip_twenty_project_silk`
   (provisioned by `cip_25`). The role is `NOSUPERUSER NOBYPASSRLS` and has
   column-level `UPDATE (companion_data)` on the 5 PS entity tables — only.
   Any attempt to write another column raises `permission denied for column`.

3. **GUC discipline.** Every CIP transaction starts with
   `SELECT set_config('app.current_tenant', PS_TENANT_ID, true)`. Read
   preflight + write happen in the SAME transaction so the txn-local GUC
   covers both. No GUC = zero rows visible (fail-closed).

4. **Merge + change-detect in SQL.**
   ```sql
   UPDATE cip_clients
      SET companion_data = companion_data || :managed::jsonb
    WHERE id = :cip_client_id
      AND (companion_data || :managed::jsonb) IS DISTINCT FROM companion_data
   ```
   Idempotent: a second run with no CRM change issues zero UPDATEs. The
   `||` operator preserves any key Leg B doesn't manage (additive,
   CRM-authoritative on managed keys).

5. **Enum miss = warn + SKIP.** An out-of-enum CRM value is logged + the
   key is OMITTED from the managed dict. The merge then leaves the
   brand's prior curated value intact. No silent degradation to `unknown`.

6. **Per-UPDATE rowcount ∈ {0, 1}.** A PK lookup must match 0 or 1 row.
   Anything else raises — broken contract.

7. **Observability is out-of-band.** The twenty role cannot write
   `cip_sync_runs` (denied). `run_writeback` returns a structured
   `RunSummary` and the script prints `LEG_B_RUN_SUMMARY {...}` for log
   scrapers.

8. **`ps_lead_owner_email` is DEFERRED.** CRM `owner_id` is a bare UUID;
   no users/owners table to resolve to email. Re-add when CRM ships one.

## Field map (summary — see CIP-SPEC-012 §2 for the full table)

| companion key             | CRM source                                              |
| ------------------------- | ------------------------------------------------------- |
| `ps_segment`              | pins `'china_referral'`; or `metadata->>'ps_segment'`   |
| `ps_onboarded_status`     | `onboarding_status` → CIP enum; falls back to `status`   |
| `ps_engagement_health`    | `metadata->>'engagement_health'`                        |
| `ps_local_alias_zh`       | `metadata->>'alias_zh'`                                 |
| `ps_local_alias_en`       | `dba_name`                                              |
| `ps_team_notes`           | `metadata->>'team_notes'`                               |
| `ps_commission_pct`       | `partners.commission_rate` (deterministic pick)         |
| `ps_billing_currency`     | `billing_currency` (uppercased)                         |
| `ps_invoice_cadence`      | `payment_terms` if it carries `monthly` / `quarterly` / `per-shipment` |
| `ps_payment_terms_days`   | `payment_terms` if it carries `Net 30` / `45 days` / etc. |
| `ps_first_onboarded_date` | `customer_since`                                        |
| `ps_last_reviewed_date`   | `metadata->>'last_reviewed'`                            |

## Running it

Live run (production):

```bash
CRM_DATABASE_URL=postgresql://<reader>:<pw>@<crm-host>/<db> \
CIP_DATABASE_URL=postgresql://<cip-host>:5432/railway \
TWENTY_PROJECT_SILK_DB_PASSWORD=<secret> \
python scripts/sync_crm_companion_to_cip.py
```

The script:

- Refuses to start with the test sentinel password unless `RUN_MODE=test`.
- Builds the CIP URL itself from the bare host + the twenty role — never
  accepts an embedded superuser DSN.
- Scrubs passwords from log lines.
- Exits 0 on success (including zero-row no-op). Exits 1 on uncaught
  exception; exits 2 on missing env var; exits 3 on URL build failure.

Cadence: scheduled poll, 15–30 min for v1. Add event-trigger later.

## Reading the output

`stdout`:

```
LEG_B_RUN_SUMMARY {"selected": 1404, "updated": 12, "unchanged": 1392, ...}
```

Counters in `RunSummary`:

- `selected` — CRM companies matched the Leg-A linkage filter
- `updated` — UPDATE returned `rowcount=1` (companion changed)
- `unchanged` — UPDATE returned `rowcount=0` (no-op; data already current)
- `skipped_no_key` — defensive: CRM rows without `cip_client_id` (the
  SQL filter excludes them; should always be 0)
- `skipped_dangling` — `cip_client_id` not in the PS valid set
- `dangling_ids` — list of those ids (for triage)
- `enum_coerced_skipped` — per-key drops due to enum validation (sum across rows)
- `partner_skipped_ambiguous` — companies with >1 partner the picker
  couldn't deterministically resolve
- `errors` — unexpected per-row errors (logged; next row attempted)

A clean run with no CRM changes returns `updated=0, unchanged=N`. A
real-world run after PS-team edits returns `updated≈small, unchanged=N`.

## What the live run needs that build/test does not

- A read connection to the CRM Postgres. The CRM has no GRANT machinery
  yet — coordinate a least-priv read credential with the CRM owner.
- `TWENTY_PROJECT_SILK_DB_PASSWORD` set in Railway + an
  `ALTER ROLE cip_twenty_project_silk PASSWORD '<secret>'` applied.
- Leg A producing CRM rows carrying `external_ids.cip_client_id`. Without
  Leg A there is nothing to read.

## Cross-references

- [CIP-SPEC-012 (PS Companion Data Contract)](PS-COMPANION-DATA-CONTRACT.md) —
  the 13 keys, 3 enums, ownership boundary
- [CIP-FW-003 (Atlas Phase 2.6 response)](vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md) §Q1 —
  sidecar-JSONB design + column-level GRANT enforcement
- [`cip/migrations/versions/cip_23_phase26_schema.py`](../cip/migrations/versions/cip_23_phase26_schema.py) — adds the `companion_data` column
- [`cip/migrations/versions/cip_25_project_silk_twenty_role.py`](../cip/migrations/versions/cip_25_project_silk_twenty_role.py) — provisions the role
- [`cip/migrations/versions/cip_26_ps_lens_views.py`](../cip/migrations/versions/cip_26_ps_lens_views.py) — the PS-side lenses that surface companion data
