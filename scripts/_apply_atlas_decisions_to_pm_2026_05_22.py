"""One-shot — apply Atlas's locked decisions to PM scopes via direct SQL.

Marks scope 210 (Atlas Review) DONE, updates the descriptions on 220/230/240/260
with Atlas's design, and files cip_24 source-side China entity lenses as a
NEW scope (Atlas surfaced this gap — handoff missed it). Idempotent.

Runs once at 2026-05-22 then can be deleted (kept in repo for audit trail).
"""
from __future__ import annotations

import os
import sys
from sqlalchemy import create_engine, text

PROJECT_ID = "596825db-61bc-4899-bc6c-e207489ca35d"
TENANT_ID = "4ebafb2d-01ba-434a-ac73-ea9603e7d0bb"
ACTOR = "claude-direct-sql-mcp-down"

# Mark 210 done with Atlas's verdict summary
DONE_MARKS: list[tuple[str, str]] = [
    (
        "306008ec-15de-4fb4-8a91-1d2c8eb7e63a",  # ⚠ placeholder; resolved at runtime
        "Atlas review delivered 2026-05-22. Locked decisions: Q1 sidecar JSONB companion_data (distinct from properties/metadata) with column-level GRANT enforcement; Q2 mirror+grant coexist with picking rule (own-and-enrich = mirror, read-only = grant); Q3 authority enum stays per-row (orthogonal to companion); Q4 safe — orchestrator already separates read/write connections so 'two GUC swaps' premise was wrong; Q5 dest-side lens recut → 2.7, source-side entity lenses REQUIRED in 2.6 (NEW REQ — handoff missed that lens_china_* is deals-only). Zero blocking Tim decisions. Migration numbers: cip_23/24/25 (cip_22 already shipped). Atlas deep plan committed at docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md.",
    ),
]

UPDATES_BY_SORT_ORDER: dict[float, tuple[str, str]] = {
    220.0: (
        "[Phase 2.6 — Schema] cip_23_phase26_schema migration (companion_data JSONB + initial_intake_route + sync_mode CHECK extension)",
        """Atlas-locked design (deep plan @ docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md, 2026-05-22).

Migration number is **cip_23** (cip_22_data_plane_safety_net shipped during the hardening sweep earlier today).

DELIVERABLES (one migration, Tier C):

1. Add `companion_data JSONB NOT NULL DEFAULT '{}'::jsonb` to the **5 PS-relevant tables ONLY**:
   - `cip_clients`, `cip_companies`, `cip_contacts`, `cip_deals`, `cip_tickets`
   - DO NOT add to `_history` tables (mirror SCD-2 is source-field-only; `_archive_to_history` will not copy companion_data, which is the intended Twenty-bypass behaviour — known limitation C-5 in the Atlas response)
   - DO NOT add to other cip_* tables (P-22 blast-radius — keep additive scope narrow)

2. Add `initial_intake_route TEXT NULL` to `cip_clients` (no CHECK constraint — flexibility until taxonomy stabilizes).

3. Extend `cip_sync_runs.sync_mode` CHECK constraint to include `'lens-mirror'`. Template: `cip_11_sync_mode_backfill.py`.

CRITICAL — companion_data MUST be distinct from existing `properties`/`metadata` columns (the existing overflow columns the mirror writes via `EXTRAS_COLUMN_BY_TABLE` in persister.py:37-52). If they share a column, the mirror clobbers companion every re-sync. The fact that the mirror structurally cannot write `companion_data` (because it's not in `mapper.fields` and not the configured `extras_col`) IS the enforcement on the writer side — paired with column-level GRANT on the reader side (scope 240).

VERIFICATION:
- alembic upgrade head clean on prod
- companion_data column exists on all 5 tables, defaults to '{}'
- initial_intake_route column exists on cip_clients
- INSERT into cip_sync_runs with sync_mode='lens-mirror' succeeds; with sync_mode='bogus' fails CHECK

DEPENDS ON: 210 (Atlas Review) — DONE.
UNBLOCKS: 230 (LensMirrorConnector), 240 (PS provisioning + Twenty role).
REF: ATLAS-REVIEW-PHASE-2.6-RESPONSE.md §Migration numbering + §Q1 sharpening 3.""",
    ),
    230.0: (
        "[Phase 2.6 — Capability] LensMirrorConnector + two-pass orchestration (Atlas-locked design)",
        """Atlas-locked design (deep plan @ docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md, 2026-05-22).

CRITICAL — this is **two-pass orchestration**, NOT a drop-in single connector (Atlas concern C-1). PS cip_clients rows are created dynamically (one per dedup'd upstream HubSpot company_id), so the FK isn't available at write-time for the first pass.

PASS 1: read deals → distinct company_ids → upsert cip_clients → read back → build {company_id → PS client_id} lookup.
PASS 2: read companies / contacts / deals / tickets → write with resolved client_id FK.

Template for the wrapper: `scripts/orchestrate_wayward_backfill.py` (event-triggered) + a scheduled 30-min entry.

CODE LOCATIONS:
- NEW `cip/integration_mesh/connectors/lens_mirror/connector.py` — conforms to CIPConnector. Holds source_tenant_id + source lens names. `stream_records()` opens its OWN short-lived connection, `SET LOCAL app.current_tenant=<source>`, SELECTs, **materializes into memory**, closes connection, yields buffered dicts. Connector.tenant_id = PS (the destination). Model on connectors/hubspot/ + connectors/fixture/.
- NEW `cip/integration_mesh/connectors/lens_mirror/mapper.py` — per-entity mappers. **Never emits `companion_data`** (mirror cannot touch it — enforcement). **Never emits `initial_intake_route`** (Atlas concern C-2 — set via post-sync backfill, see below).
- NEW `scripts/orchestrate_ps_lens_mirror.py` — two-pass driver + initial_intake_route NULL-backfill (post-Pass-1, idempotent: `UPDATE cip_clients SET initial_intake_route='wayward' WHERE tenant_id=:ps AND initial_intake_route IS NULL`). Two invokers: event-triggered (poll cip_sync_runs for EcomLever Wayward completions) + scheduled (every 30 min).
- **NO CHANGE to persister.py / orchestrator.py / tenant_context.py / base.py.** Atlas Q1=(b)+role-grants + Q4=two-connections means the existing pipeline is reused unchanged.

Q4 SAFETY (Atlas verdict: SAFE):
- Source GUC and dest GUC never coexist on one connection (handoff's premise was wrong; the deployed orchestrator already separates `stream_records` read connection from per-batch `Session` write connection)
- Connector holds its own read engine; orchestrator's Session opens with PS GUC via `apply_tenant_context()` once per batch (existing pattern at orchestrator.py:565)
- RLS policy uses `current_setting(..., true)` which is STABLE — re-evaluated per execution, not plan-inlined. Caveat: must use PgBouncer TRANSACTION pooling (not session) when prod migrates off Railway QueuePool

TESTS (Atlas-required):
- Conformance harness 8 tests pass
- Dedup: N deals for same upstream company_id → 1 PS cip_clients row
- initial_intake_route set on insert-via-backfill only, never overwritten
- sync_mode='lens-mirror' recorded in cip_sync_runs
- C1 cross-tenant isolation (PS context can't see EcomLever, source read can't see PS)
- C2 two-connection proof (connector never calls `apply_tenant_context` on the orchestrator session)
- C3 fail-closed (no GUC → zero rows)
- C4 advisory lock (concurrent run → SyncAlreadyRunningError)

DEPENDS ON: 220 (cip_23 schema) + 225 (cip_24 source-side lenses).
UNBLOCKS: 240 (PS provisioning + first mirror run).
REF: ATLAS-REVIEW-PHASE-2.6-RESPONSE.md §Q4, C-1, C-2, §Implementation pointers.""",
    ),
    240.0: (
        "[Phase 2.6 — Provisioning] PS tenant creation + first mirror run + cip_25 cip_twenty_project_silk role",
        """Atlas-locked design (deep plan @ docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md, 2026-05-22).

DELIVERABLES:

1. Provision `Project Silk` tenant via JOS provisioning. **REAL UUIDv4 — NEVER a placeholder.** The b0000000-...0001 incident from 2026-05-12 cost a 1.26M-row migration to clean up (cip_12_seed_wayward_client + scripts/migrate_b0_to_ecomlever.py).
   - Parent tenant: Foundry (4ebafb2d-01ba-434a-ac73-ea9603e7d0bb). Type: venture.
   - Save the new UUID into `reference_foundry_pm_ids.md` memory (C:/Users/Tim Jordan/.claude/projects/c--Users-Tim-Jordan-code-project-silk-website/memory/reference_foundry_pm_ids.md)

2. **cip_25_project_silk_tenant_role.py** migration — provisions the `cip_twenty_project_silk` Postgres role for Twenty CRM's write-back path (Atlas Q1 enforcement layer):
   ```
   GRANT SELECT ON cip_companies, cip_contacts, cip_deals, cip_tickets, cip_clients
          TO cip_twenty_project_silk;
   GRANT UPDATE (companion_data) ON each of the 5 tables  -- column-level, the key trick
   ```
   - NOSUPERUSER NOBYPASSRLS LOGIN per cip_09/cip_21 pattern
   - Password from `TWENTY_PROJECT_SILK_DB_PASSWORD` env var with test sentinel fallback
   - NO INSERT, NO DELETE, NO UPDATE on any source column

3. Run the first PS mirror sync (calls scripts/orchestrate_ps_lens_mirror.py). Pass 1 creates initial cip_clients rows. Pass 2 populates cip_companies/contacts/deals/tickets with resolved client_id FKs.

4. Verify acceptance:
   - PS tenant cip_clients count = dedup'd company count from lens_china_clients
   - PS tenant other cip_* counts = corresponding counts in lens_china_companies / lens_china_contacts / lens_china_tickets
   - Twenty role can UPDATE companion_data, blocked from updating source columns (negative test)
   - Mirror run with companion_data pre-populated DOES NOT clobber the companion data

5. Set TWENTY_PROJECT_SILK_DB_PASSWORD as a Railway secret (model: cip_21's PROJECT_SILK_METABASE_DB_PASSWORD). Re-run migration or one-shot ALTER ROLE to lock in the real password.

UNBLOCKS: foundry-metabase session — swap interim grant tenant → real PS CIP binding. Lens names preserved; dashboards survive the cutover.

DEPENDS ON: 230 (LensMirrorConnector + orchestration).
REF: ATLAS-REVIEW-PHASE-2.6-RESPONSE.md §Q1 + §Implementation pointers.""",
    ),
    260.0: (
        "[Phase 2.6 — Docs] CROSS-TENANT-ACCESS-PATTERNS.md (mirror vs grant) + ONBOARDING + CONNECTOR-AUTHORING + ROADMAP + Phase 3 supersede",
        """Atlas-locked design (deep plan @ docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md, 2026-05-22).

5 doc updates:

1. **NEW: `docs/CROSS-TENANT-ACCESS-PATTERNS.md`** — the canonical comparison + picking rule. From Atlas's Q2 table:
   - Mirror (Phase 2.6): data duplicated, consumer can enrich + own records, survives source revocation
   - Grant (Phase 3): data lives once, read-only, revoke = gone
   - Picking rule: "Need to OWN and ENRICH? → Mirror. Only READ without owning? → Grant."
   - First mirror case: PS (Phase 2.6). First grant case: Foundry-self cross-tenant synthesis (Phase 7).

2. **`docs/ONBOARDING-A-NEW-TENANT.md`** — extend with the lens-mirror onboarding path (currently assumes external-source connectors only).

3. **`docs/CONNECTOR-AUTHORING-GUIDE.md`** — add LensMirrorConnector as a worked example. Highlight the two-pass orchestration requirement (Atlas C-1).

4. **`docs/METABASE-OPERATOR-GUIDE.md`** — paragraph on Metabase against a mirror-derived tenant (no new operator behaviour; conceptual model worth noting).

5. **`docs/vision/ROADMAP.md` — Phase 2.6 insert + Phase 3 supersede** (Atlas §3 explicit deliverable):
   - Insert Phase 2.6 between 2.5 and 3 — currently only exists in PM, not in ROADMAP
   - Phase 3's "Project Silk grant-in to Wayward" bullet → replace with a pointer ("superseded by Phase 2.6 mirror — see CROSS-TENANT-ACCESS-PATTERNS.md")
   - Rest of Phase 3 (grant runtime, cip_cross_tenant_grants, Rocky Ridge, grant-window/authority-floor) stays unchanged

DEPENDS ON: 220 / 230 / 240 shipped (so docs describe real code).
REF: ATLAS-REVIEW-PHASE-2.6-RESPONSE.md §Q2 + §ROADMAP changes.""",
    ),
}

# NEW scope filed at sort_order 225 — between schema (220) and capability (230).
# This is the source-side requirement Atlas surfaced that the handoff missed.
NEW_SCOPES: list[tuple[float, str, str]] = [
    (
        225.0,
        "[Phase 2.6 — Source Lenses] cip_24_china_entity_lenses (lens_china_companies / _contacts / _tickets)",
        """NEW scope — surfaced 2026-05-22 by Atlas in the deep plan review (concern Q5 / §6).

THE GAP: All existing `lens_china_*` views are DEALS-ONLY (`cip_18_wayward_attr_lenses.py:115-157` selects from `cip_deals`). A deals-only lens cannot feed `cip_companies` / `cip_contacts` / `cip_tickets` on the PS side. The "China subset" is **defined by deal attribution** (`d.properties->>'source' LIKE 'China Referral%'`); companies/contacts/tickets are in-scope only via their relationship to those deals.

DELIVERABLES (one migration, Tier C):

**`cip_24_china_entity_lenses.py`** — three new source-side lens views in the EcomLever tenant, each joining back to a China-attributed deal:

```sql
CREATE OR REPLACE VIEW lens_china_companies AS
SELECT c.*
FROM cip_companies c
WHERE c.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
  AND EXISTS (
    SELECT 1 FROM cip_deals d
    WHERE d.tenant_id = c.tenant_id
      AND d.properties->>'source' LIKE 'China Referral%'
      AND (associated_company_id resolution — see cip_18 join pattern)
  );

CREATE OR REPLACE VIEW lens_china_contacts AS  -- analogous, via deal-contact association
CREATE OR REPLACE VIEW lens_china_tickets  AS  -- analogous, via Zendesk requester ↔ contact ↔ deal
```

(Final join columns depend on the actual association graph in cip_companies / cip_contacts / cip_tickets — implementor should confirm via the deployed schema.)

Register each in `cip_views`. Pattern: `cip_18_wayward_attr_lenses.py`.

Also extend the `cip_21_project_silk_grant_role` GRANT list to include the 3 new views (or file an `cip_24a` follow-up if extending cip_21 is cleaner — implementor's choice).

WHY THIS MATTERS: Without these, the mirror in 230 has no clean source contract for non-deal entities and the subset definition is implicit rather than reviewable. "The mirror reads lenses" stays a clean discoverable contract.

DEPENDS ON: 220 (cip_23 schema) — actually independent; can ship in parallel.
UNBLOCKS: 230 (LensMirrorConnector source read paths).
REF: ATLAS-REVIEW-PHASE-2.6-RESPONSE.md §Q5 source-side correction + §Implementation pointers §Migrations.""",
    ),
]


def main() -> int:
    url = os.environ["DATABASE_URL"]
    sa_url = url.replace("postgresql://", "postgresql+psycopg://").replace("postgres://", "postgresql+psycopg://")
    engine = create_engine(sa_url, pool_pre_ping=True)

    with engine.begin() as conn:
        # Look up scope_ids by sort_order for the updates (we use sort_order
        # as a stable handle since they're unique within this project).
        rows = conn.execute(text("""
            SELECT sort_order, scope_id::text AS sid
            FROM scopes WHERE project_id = :p AND sort_order IN :sorts
        """).bindparams(
            __import__("sqlalchemy").bindparam("sorts", expanding=True)
        ), {"p": PROJECT_ID, "sorts": list(UPDATES_BY_SORT_ORDER.keys())}).all()
        sort_to_id = {float(r.sort_order): r.sid for r in rows}

        # Apply description updates
        for sort_order, (new_title, new_description) in UPDATES_BY_SORT_ORDER.items():
            sid = sort_to_id.get(sort_order)
            if not sid:
                print(f"  WARN: no scope at sort_order={sort_order}")
                continue
            r = conn.execute(text("""
                UPDATE scopes
                SET title = :t, description = :d, last_status_change_at = NOW(),
                    last_status_change_by = :actor, updated_at = NOW()
                WHERE scope_id = :sid
            """), {"sid": sid, "t": new_title, "d": new_description, "actor": ACTOR})
            print(f"UPDATE sort={sort_order} sid={sid[:8]}..: {r.rowcount} row")

        # Mark 210 done (Atlas Review)
        atlas_review_id = conn.execute(text("""
            SELECT scope_id::text FROM scopes WHERE project_id = :p AND sort_order = 210.0
        """), {"p": PROJECT_ID}).scalar()
        if atlas_review_id:
            atlas_summary = (
                "Atlas review delivered 2026-05-22. Locked decisions: "
                "Q1 sidecar JSONB companion_data (distinct from properties/metadata) with column-level GRANT enforcement; "
                "Q2 mirror+grant coexist with picking rule; "
                "Q3 authority enum stays per-row (orthogonal); "
                "Q4 safe — orchestrator already separates read/write connections; "
                "Q5 dest-side lens recut → 2.7, source-side entity lenses REQUIRED in 2.6 (NEW REQ — filed as scope at sort_order 225). "
                "Migration numbers cip_23/24/25 (handoff's cip_22 was stale). "
                "Zero blocking Tim decisions. "
                "Full deep plan: docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md."
            )
            r = conn.execute(text("""
                UPDATE scopes SET status='done', last_status_change_at=NOW(),
                    last_status_change_by=:actor,
                    description = description || E'\n\n---\nDONE 2026-05-22: ' || :note
                WHERE scope_id = :sid AND status != 'done'
            """), {"sid": atlas_review_id, "actor": ACTOR, "note": atlas_summary})
            print(f"MARK DONE 210 (Atlas Review) sid={atlas_review_id[:8]}..: {r.rowcount} row")

        # Insert new scope (idempotent on title)
        for sort_order, title, description in NEW_SCOPES:
            existing = conn.execute(text("""
                SELECT scope_id FROM scopes WHERE project_id = :p AND title = :t
            """), {"p": PROJECT_ID, "t": title}).first()
            if existing:
                print(f"SKIP NEW (exists): {title[:80]}")
                continue
            conn.execute(text("""
                INSERT INTO scopes (
                    scope_id, tenant_id, project_id, title, description,
                    sort_order, status, last_status_change_at, last_status_change_by,
                    created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), :tenant, :project, :title, :description,
                    :sort_order, 'backlog', NOW(), :actor, NOW(), NOW()
                )
            """), {
                "tenant": TENANT_ID, "project": PROJECT_ID, "title": title,
                "description": description, "sort_order": sort_order, "actor": ACTOR,
            })
            print(f"INSERTED NEW sort={sort_order}: {title[:80]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
