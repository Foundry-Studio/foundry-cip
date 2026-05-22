# One-shot — files PM scopes via direct SQL because foundry-tools MCP is disconnected.
# Each row carries last_status_change_by='claude-direct-sql-mcp-down' so the
# provenance is auditable + can be re-attributed when MCP reconnects.
# Idempotent: skips on (title, project_id) duplicates so re-running is safe.
from __future__ import annotations

import os
from sqlalchemy import create_engine, text

PROJECT_ID = "596825db-61bc-4899-bc6c-e207489ca35d"
TENANT_ID = "4ebafb2d-01ba-434a-ac73-ea9603e7d0bb"
ACTOR = "claude-direct-sql-mcp-down"

# (sort_order, title, description, status)
SCOPES: list[tuple[float, str, str, str]] = [
    # ─────────────────────────────────────────────────────────────────────
    # Phase 2.6 — Project Silk cross-tenant lens-mirror cluster
    # Source: Foundry-Agent-System/WORKBENCH/handoffs/cip-handoff-2026-05-22-project-silk-cross-tenant-mirror.md
    # ─────────────────────────────────────────────────────────────────────
    (
        200.0,
        "[Phase 2.6 — Fast Path] cip_21_project_silk_china_grant_role migration (READ-ONLY grant — interim PS Metabase dashboard unblocker)",
        """SHIP FIRST, standalone. Author cip_21 migration creating a new Postgres role `cip_metabase_project_silk` with grants
on EcomLever's `lens_china_*` views ONLY (read-only), + `app.current_tenant` pre-bound to EcomLever's UUID
(dec814db-722a-4730-8e60-51afc4a5dad9). This is the grant-based interim that lets the China CS team get their Metabase
dashboard in days, while the bigger mirror-based architecture goes through Atlas review.

PATTERN: model on `cip_09_metabase_role_views`. ~50 lines. Read-only. Independent of the authority/companion design — does NOT depend on §3.2.

DEPENDS ON: none — unblocker, ship now.
UNBLOCKS: foundry-metabase session (Stage 1 PS Metabase tenant provisioning + Railway deploy).
REF: handoff §7 item 1; §6 cip/migrations/versions/cip_09_metabase_role_views.py pattern.""",
        "backlog",
    ),
    (
        210.0,
        "[Phase 2.6 — Atlas Review] Cross-tenant authority/companion mechanism (mirror vs grant, sidecar JSONB vs per-field tag)",
        """Architecture review BLOCKING the rest of Phase 2.6. Block all §4.3 work (LensMirrorConnector) until Atlas signs off.

OPEN QUESTIONS (handoff §5):
1. Authority/companion mechanism: (a) per-field auth tag / (b) sidecar JSONB (`companion_data` column) / (c) sidecar tables. Handoff recommends (b); Atlas to bless or override.
2. Relationship to Phase 3 (cross-tenant grants): does Phase 3 get redesigned mirror-first, or do mirror + grant coexist? Decision rule for picking.
3. Relationship to Phase 2.5 (Foundry self-tenant + write-back authority enum). Is the authority enum extended per-field, or does companion layer use a different mechanism?
4. RLS + GUC across tenants inside one connector session — safe with existing M2 advisory-lock + RLS pattern? Two `SET LOCAL app.current_tenant` swaps per row-batch — subtle correctness issues?
5. PS lens recut: part of Phase 2.6 (atomic) or Phase 2.7 follow-up? Handoff leans follow-up.

LOCKED DECISIONS (Tim 2026-05-22, do NOT relitigate without Tim):
- Mirror-based, NOT grant-based for PS data
- PS owns its own physical copy of the Chinese subset of Wayward data
- Twenty CRM as interactive consumer + producer of companion fields
- Dedup: 1 PS cip_clients row per upstream company_id (HubSpot company_id)
- `initial_intake_route='wayward'` set on insert only, never overwritten
- Sync cadence: event-triggered (on EcomLever Wayward sync completion) + scheduled (30-min poll)

OUTPUT: a v5.x-style deep plan locking the authority/companion mechanism + answering the 5 open questions. Then unblocks §4.3+.

DEPENDS ON: none — start immediately.
UNBLOCKS: 2.6-Schema, 2.6-Capability, 2.6-Provisioning.
REF: handoff §3, §5.""",
        "backlog",
    ),
    (
        220.0,
        "[Phase 2.6 — Schema] cip_22_initial_intake_route + companion-layer schema (pending Atlas blessing)",
        """Bundle two schema changes per handoff §4.2 + §3.2:

1. Add `initial_intake_route` column to `cip_clients`:
   - text, nullable, enum-ish values: 'wayward', 'twenty', 'direct', 'referral', 'manual', extensible
   - Set on INSERT only by LensMirrorConnector (preserves first-touch provenance)
   - No CHECK constraint yet — keep flexible

2. Companion-layer schema per Atlas's locked decision on §3.2:
   - If sidecar JSONB (recommended): add `companion_data jsonb NOT NULL DEFAULT '{}'::jsonb` to cip_companies, cip_contacts, cip_deals, cip_tickets, cip_engagements, etc.
   - If per-field authority tag: extend authority enum + add provenance column per relevant table
   - If sidecar tables: create cip_*_companion 1:1 tables

3. Register 'lens-mirror' as a valid `sync_mode` in `cip_sync_runs`.

DEPENDS ON: Phase 2.6 Atlas Review (§3.2 decision).
UNBLOCKS: LensMirrorConnector.
REF: handoff §4.2, §3.2.""",
        "backlog",
    ),
    (
        230.0,
        "[Phase 2.6 — Capability] LensMirrorConnector + sync orchestration (mirror EcomLever lens_china_* → PS cip_*)",
        """New connector under `cip/integration_mesh/connectors/lens_mirror/`. Conforms to CIPConnector + CIPMapper protocols
(same shape as HubSpot, Zendesk, Fixture). Handoff §4.3 has the detailed spec.

BEHAVIOR:
1. Takes source_tenant_id + list of source `lens_*` view names in config.
2. Opens session, `SET LOCAL app.current_tenant = '<source_tenant_id>'`, SELECTs from source lens views.
3. For each row: dedupe by upstream HubSpot company_id, upsert into local tenant's cip_* tables with source_connector='lens-mirror', source_tenant=<UUID>, source_lens=<view name>.
4. Honors authority model from §3.2 — writes ONLY source fields, never touches companion fields.
5. Creates/updates cip_clients row per dedup'd brand. Sets initial_intake_route='wayward' on INSERT only.
6. Records run in cip_sync_runs with sync_mode='lens-mirror'.

SYNC ORCHESTRATION (§4.4):
- Event-triggered: poll cip_sync_runs for EcomLever Wayward completions; invoke PS mirror on each.
- Scheduled: every 30 minutes regardless.
- Both invokers call same orchestrator with LensMirrorConnector.

TESTS (same coverage bar as HubSpot/Zendesk):
- Conformance harness: all 8 tests pass
- Authority enforcement: cannot overwrite companion fields
- Cross-tenant isolation: PS RLS context cannot read EcomLever rows directly
- Dedup: N deals for same company_id → 1 PS cip_clients row
- initial_intake_route set on insert only
- sync_mode='lens-mirror' recorded

DEPENDS ON: Phase 2.6 Atlas Review + Phase 2.6 Schema.
UNBLOCKS: PS tenant provisioning + first mirror run.
REF: handoff §4.3, §4.4.""",
        "backlog",
    ),
    (
        240.0,
        "[Phase 2.6 — Provisioning] Project Silk tenant creation + first mirror run",
        """After Atlas-blessed design is in code:

1. Provision `Project Silk` tenant via JOS provisioning. **REAL UUIDv4 — never a placeholder**. The b0000000-...0001 incident from 2026-05-12 cost a full 1.26M-row migration to clean up (cip_12_seed_wayward_client + scripts/migrate_b0_to_ecomlever.py).
2. Parent tenant: Foundry (4ebafb2d-01ba-434a-ac73-ea9603e7d0bb). Type: venture.
3. Save the new UUID into `reference_foundry_pm_ids.md` memory at C:/Users/Tim Jordan/.claude/projects/c--Users-Tim-Jordan-code-project-silk-website/memory/reference_foundry_pm_ids.md
4. First mirror run creates initial PS cip_clients + cip_companies / cip_contacts / cip_deals / cip_tickets rows automatically — do NOT hand-seed.
5. Verify: PS tenant cip_clients count matches dedup'd company count from lens_china_clients.

DEPENDS ON: Phase 2.6 Capability (LensMirrorConnector).
UNBLOCKS: foundry-metabase session swap from interim grant tenant → real PS CIP binding (lens names preserved; dashboards survive).
REF: handoff §4.5; §8 sequencing.""",
        "backlog",
    ),
    (
        250.0,
        "[Phase 2.7 — Design] PS lens recut conversation + cip_23_ps_lens_views",
        """Open a design conversation with Tim — PS lenses are NOT 1:1 with EcomLever's. EcomLever's lens_china_* are organized
by Wayward attribution source (China Referral - Eric/Tim/Adina etc.). PS's lenses will be organized by PS's mental model
— likely by PS rep, PS-side stage, client status from PS's perspective.

DELIVERABLES:
1. Sketch a proposal using EcomLever's lens_china_* as the template, reorganized per PS's axes
2. Conversation with Tim to lock lens taxonomy
3. cip_23_ps_lens_views migration creating the lenses

Phase 2.7 sequencing (not 2.6) — mirror lands first, lens design lands second. Mirror data is useful via existing
cip_views registry queries before PS lenses are recut.

DEPENDS ON: Phase 2.6 Provisioning (PS tenant exists).
REF: handoff §3.6, §4.6, §5.5.""",
        "backlog",
    ),
    (
        260.0,
        "[Phase 2.6 — Docs] Cross-tenant mirror pattern docs + ONBOARDING + CONNECTOR-AUTHORING updates",
        """4 doc updates per handoff §4.7:

1. NEW: `docs/CROSS-TENANT-MIRROR-PATTERN.md` — the architectural pattern itself. When to use mirror vs grant. Worked example. Authority/companion layer mechanics.
2. `docs/ONBOARDING-A-NEW-TENANT.md` — extend with the lens-mirror onboarding path. Currently assumes external-source connectors only; this is a new path (no external source, mirrored from another CIP tenant).
3. `docs/CONNECTOR-AUTHORING-GUIDE.md` — add LensMirrorConnector as a worked example alongside the existing HubSpot/Zendesk examples.
4. `docs/METABASE-OPERATOR-GUIDE.md` — section on Metabase against a mirror-derived tenant. No new operator behavior required, but the conceptual model deserves a paragraph.

DEPENDS ON: Phase 2.6 Capability shipped (so the docs describe real code).
REF: handoff §4.7.""",
        "backlog",
    ),
    # ─────────────────────────────────────────────────────────────────────
    # Hardening / quality from 2026-05-22 sniff-test
    # ─────────────────────────────────────────────────────────────────────
    (
        300.0,
        "[Hardening] CIP data-plane safety net — cip_files uniq + cip_knowledge_chunks source_kind CHECK + KnowledgeIndexer→Pinecone parity",
        """Three small fixes that together close real safety/parity gaps surfaced by today's Hard Split + Rocky Ridge migration:

1. **`cip_files` unique constraint.** Add `UNIQUE (tenant_id, client_id, sha256) WHERE sha256 IS NOT NULL` partial-index migration. Today the Rocky Ridge migration script does SELECT-then-INSERT to dedupe — race window if two ingestion paths run concurrently. Partial index closes it cheaply.

2. **`cip_knowledge_chunks.source_kind` CHECK constraint.** Mirror what we did Foundry-side with cip02_revert_source_types. Today CIP-side is wide open — any string can be written. Add a CHECK constraint listing valid CIP source_kinds: `cip_client_document`, `cip_ticket_comment`, `cip_engagement_note`, `cip_engagement_meeting`, `cip_sop`, `cip_contract`, `cip_training`, `cip_email_thread`, `cip_call_transcript`, `cip_ticket_body`. Defense-in-depth.

3. **KnowledgeIndexer → Pinecone write parity.** Today `KnowledgeIndexer.index(...)` writes ONLY to Postgres. Pinecone is populated via separate backfill scripts. Every CIP ingest is therefore out-of-parity by default until somebody remembers to run the backfill. Wire Pinecone upsert into `KnowledgeIndexer` itself so new ingestion stays in parity by default. Idempotent upsert pattern from the existing migrate scripts is the template.

ACCEPTANCE:
- pytest tests/integration_mesh pass with all three changes
- New ingest run creates PG + Pinecone rows atomically (or transactionally consistent)
- cip_knowledge_chunks insert with bogus source_kind raises CHECK violation
- cip_files insert with duplicate sha256 raises unique violation

REF: 2026-05-22 sniff-test (this session).""",
        "backlog",
    ),
    (
        310.0,
        "[Hardening] EmbeddingClient startup healthcheck + migration script heartbeat (RUN_BEGAN/RUN_ENDED markers)",
        """Two cheap improvements that would have saved real time today:

1. **EmbeddingClient startup healthcheck.** Today CIP's default embedding URL went stale silently when server-b's Ollama was decommissioned (2026-05-19 Track B Phase 3). The script ran, all embed calls timed out, OpenRouter fallback wasn't configured, migration crashed mid-run. Add a one-time HTTP GET to `{primary_url}/health` (or `/v1/models`) in `EmbeddingClient.__init__` that raises EmbeddingError immediately if the endpoint isn't reachable. Optional opt-out via `CIP_EMBEDDING_SKIP_HEALTHCHECK=1` for offline tests.

2. **Migration script heartbeat.** Today's Rocky Ridge migration "completed" twice per the harness wrapper while actually crashing silently mid-stream (Windows backgrounding quirk). Idempotency saved me. Add `print('RUN_BEGAN tag=<name> at <ts>')` at the top of `main()` and `print('RUN_ENDED tag=<name> at <ts>')` at the bottom — bounding markers so any tail of the log makes status obvious. Apply to all migration scripts (3 today: migrate_chunks_postgres_to_pinecone, migrate_rocky_ridge_to_cip, recover_rocky_ridge_missing_from_foundry_cache, purge_rocky_ridge_foundry_state).

ACCEPTANCE:
- EmbeddingClient with a bad URL fails fast at construction (not at first embed call)
- All migration scripts emit clear RUN_BEGAN / RUN_ENDED markers
- pytest for embedding client healthcheck (mock httpx)

REF: 2026-05-22 sniff-test.""",
        "backlog",
    ),
    (
        320.0,
        "[Capability] cip_knowledge_sources registry table (explicit ingestion-source registry, mirror Foundry's pattern)",
        """Foundry has `knowledge_sources` as an explicit registry (name, source_type, chunk_count, document_count, status). CIP doesn't — sources are inferred from `cip_files` + `cip_knowledge_chunks.source_kind` groupings. That works for queries but isn't discoverable, doesn't support per-source admin (status, refresh schedule, ingestion config), and is not JOS-compliant for the "what's in CIP" question.

DELIVERABLES:
1. New migration: `cip_knowledge_sources` table with columns:
   - source_id (uuid PK), tenant_id (FK), client_id (FK nullable for tenant-wide sources)
   - source_kind (FK to the new CHECK constraint values)
   - source_origin (TEXT — e.g., 'manual_upload', 'hubspot_engagement', 'zendesk_ticket_comment', 'foundry_knowledge_recovery')
   - name (human-readable: 'Rocky Ridge Research Library', 'Wayward Engagement Notes')
   - description, status, chunk_count, document_count
   - first_ingested_at, last_refreshed_at, ingestion_config (JSONB)
   - UNIQUE (tenant_id, source_kind, source_origin)

2. Backfill script that synthesizes registry rows from existing cip_files + cip_knowledge_chunks groupings.

3. Update `KnowledgeIndexer` to write/refresh the registry on every ingest run (with counter columns updated transactionally).

4. Cheatsheet integration: per-tenant block grows a "Sources" list showing each registered source with chunk/doc counts and last-refresh timestamp.

5. Per-file browse: `docs/tenants/{tenant_uuid}/SOURCES.md` (or similar) auto-generated showing each source + its files. Closes the "what documents do we have for Rocky Ridge" question with a scannable list.

ACCEPTANCE:
- All current CIP-Pinecone-populating sources have a registry row (Wayward Engagement Notes, Wayward Ticket Comments, Wayward Engagement Meetings, Rocky Ridge Research Library, Rocky Ridge image captions)
- Cheatsheet regen surfaces them
- Per-tenant SOURCES.md generated for Wayward + Rocky Ridge

REF: 2026-05-22 sniff-test discoverability gap; partial Phase 2 of inventory design call 9cd4071c.""",
        "backlog",
    ),
    (
        330.0,
        "[Diagnostic] Regenerate per-tenant MANIFEST.md (Wayward stale + Rocky Ridge missing) — Hard-Split-aware",
        """Today's audit surfaced two MANIFEST gaps:

1. **Wayward's MANIFEST.md is stale w/r/t the Hard Split.** It was generated before CIP-Pinecone existed; doesn't surface vectorCount, cip_files count, CIP-R2 bytes, or the new source_kinds (`cip_engagement_meeting` etc.).

2. **Rocky Ridge has no MANIFEST.md.** RR has data now: 70 cip_files, 4,505 chunks, 4,505 Pinecone vectors, 47.6 MB in CIP-R2. The generator script doesn't yet know how to render a "knowledge-heavy / structured-light" tenant.

DELIVERABLES:
1. Extend `scripts/generate_tenant_manifest.py` to include:
   - CIP-Pinecone vectorCount per namespace
   - cip_files count + total bytes + breakdown by source_connector
   - CIP-R2 bytes from R2 (call `s3.list_objects_v2` once)
   - cip_knowledge_chunks breakdown by source_kind
   - Drift section (if any Foundry-Knowledge content for this tenant — mirror cheatsheet's logic)
2. Regenerate Wayward MANIFEST.md (`dec814db-...`)
3. Generate Rocky Ridge MANIFEST.md (`80252ad9-...`) for the first time
4. Optional: extend pre-commit / CI to fail if a MANIFEST is stale (date check or hash check)

ACCEPTANCE:
- Wayward MANIFEST shows the new CIP-Pinecone + cip_files numbers
- Rocky Ridge MANIFEST exists with proper frontmatter (CIP-DIAG-104?)
- Both files in JOS registry

REF: 2026-05-22 sniff-test; aligns with cheatsheet pattern (CIP-DIAG-103).""",
        "backlog",
    ),
]

UPDATES: list[tuple[str, str]] = [
    # (scope_id, new_status, optional note)
]

DONE_MARKS: list[tuple[str, str]] = [
    ("a6c7d04b-bc49-403c-9673-3f83e91c9587", "Rocky Ridge migration complete 2026-05-22: 70 cip_files, 4,505 chunks, 4,505 Pinecone vectors (parity ✓), Foundry-side purged. See commits 06d9a6b + 2326809 on foundry-cip master."),
    ("9259a8e5-a15f-4eb2-9e09-777af0085edc", "Foundry-Agent-System schema gate closed via cip02_revert_source_types migration + runtime guard in knowledge_ingester_service + CONTRACT.md update. Commit c665d08e pushed to FAS master. Rocky Ridge audit + purge complete (5,825 chunks + 1 source row deleted). Per-tenant drift detection now lives in CIP-CHEATSHEET.md (regenerated to ✓ for RR)."),
]


def main() -> int:
    url = os.environ["DATABASE_URL"]
    sa_url = url.replace("postgresql://", "postgresql+psycopg://").replace("postgres://", "postgresql+psycopg://")
    engine = create_engine(sa_url, pool_pre_ping=True)
    inserted, skipped = 0, 0
    with engine.begin() as conn:
        # Insert new scopes (idempotent on title)
        for sort_order, title, description, status in SCOPES:
            existing = conn.execute(text(
                "SELECT scope_id FROM scopes WHERE project_id = :pid AND title = :title"
            ), {"pid": PROJECT_ID, "title": title}).first()
            if existing:
                print(f"SKIP (already exists): {title[:80]}")
                skipped += 1
                continue
            conn.execute(text("""
                INSERT INTO scopes (
                    scope_id, tenant_id, project_id, title, description,
                    sort_order, status, last_status_change_at, last_status_change_by,
                    created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), :tenant, :project, :title, :description,
                    :sort_order, :status, NOW(), :actor,
                    NOW(), NOW()
                )
            """), {
                "tenant": TENANT_ID, "project": PROJECT_ID,
                "title": title, "description": description,
                "sort_order": sort_order, "status": status,
                "actor": ACTOR,
            })
            print(f"INSERTED ({sort_order:>6.1f}): {title[:80]}")
            inserted += 1

        # Mark previously-open scopes as done where their work has actually completed
        for scope_id, note in DONE_MARKS:
            r = conn.execute(text("""
                UPDATE scopes
                SET status='done',
                    description=description || CHR(10) || CHR(10) || '---' || CHR(10) || 'DONE 2026-05-22 (' || :actor || '): ' || :note,
                    last_status_change_at=NOW(),
                    last_status_change_by=:actor,
                    updated_at=NOW()
                WHERE scope_id = :sid AND status != 'done'
            """), {"sid": scope_id, "actor": ACTOR, "note": note})
            print(f"MARK DONE ({r.rowcount}): {scope_id}")

    print(f"\nSummary: inserted={inserted}, skipped={skipped}, marked_done={len(DONE_MARKS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
