---
kind: doc
domain: client-intelligence-platform
project_id: client-intelligence-platform
pm_project_id: 596825db-61bc-4899-bc6c-e207489ca35d
phase: 2.5
shape: foundry-self-tenant-write-back
status: provisional
owner: tim
authors: [tim, atlas]
created: 2026-04-20
last_updated: 2026-05-15
appetite: session-bound (milestone-ordered, not week-ordered)
primary_tenant: foundry (self-tenant)
locks: []
depends_on: [phase-1-plain-jane, phase-2-wayward-onboarding]
blocks: [phase-3-rocky-ridge-and-grants-runtime]
---

# CIP Phase 2.5 — Foundry Self-Tenant + Early Write-Back

> Authors Phase 2.5 in Atlas's four-section shape: **VISION** / **WDGLL** / **SPEC** / **PLAN**.
>
> Phase 2.5 is **provisional** — it sharpens after Phase 2 Wayward Onboarding ships. This doc is the committed shape; specifics (producer choice in M4, authority thresholds in M3) get finalized at Phase 2.5 kickoff.

---

## VISION — Why Phase 2.5 Exists

### The bet

Phase 2.5 bets that **writable CIP is worth shipping before agents are consuming it at scale** — so by the time investigative agents (Phase 7) land, the write path is battle-tested, not a fresh surface.

Write-back was originally bundled into Phase 7. That decision got revisited 2026-04-20 when Tim named the real constraint: "sooner rather than later. get it ready, and the foundry agents will use it when THEY are ready. we could also have claude co-work or other apps writing to it!" Bundling write-back with Phase 7's investigative agents meant two risky surfaces ship together — the agents *and* the surface they write to. Pulling write-back forward lets us debug the write surface against one simple producer (a Foundry internal research agent, or a Cowork session) well before the complex investigative agents exist.

Phase 2.5 also does one more thing: **Foundry becomes a peer tenant in CIP**. Foundry eats its own dog food. Internal research topics, venture hypotheses, competitive intel threads live in the Foundry tenant just like EcomLever's ops live in the EcomLever tenant. The Tenant Onboarding Checklist (authored in Phase 1, hardened in Phase 2) is meta-tested by provisioning Foundry itself verbatim.

### What Phase 2.5 is NOT

- **Not push & sync** — that ships in Phase 2 as part of Wayward's full round-trip (Chatwoot routing, Twenty CRM sync, Drive exports).
- **Not cross-tenant writes** — a tenant writes only into its own tenant. Cross-tenant pattern synthesis is Phase 7, cross-tenant read grants are Phase 3.
- **Not the rich validated-promotion UX** — Phase 7. Phase 2.5 ships a minimal CLI/Metabase review surface.
- **Not chatbot writes** — Phase 5 chatbot is read-only by constraint; writes land in Phase 7.
- **Not the advanced investigative agents** — they're the Phase 7 *consumers* of the write surface this phase builds.

### Why insert at 2.5 (not append at 3, not delay to 7)

Phase 3 is already multi-tenant + grants-runtime heavy. Bundling write-back would double its appetite and couple two unrelated risks. Phase 7 would delay write-back too far — producers can't start building against a surface that doesn't exist, and "agents will use it when they're ready" requires the surface be ready *first*. Phase 2.5 lands write-back on its own, short and focused.

### Primary consumer

**Foundry itself.** The first producer is either a Foundry internal research agent or a Cowork session — both write into the Foundry tenant. Phase 2.5 acceptance is Tim seeing a row he (or an agent working on his behalf) wrote appear in a Foundry Metabase dashboard after passing through the promotion queue.

---

## SOLVE FOR — Writable CIP for Foundry's Own Producers

By Phase 2.5 exit, three things are true that weren't before:

1. **Foundry has its own CIP tenant.** Provisioned by following the Tenant Onboarding Checklist verbatim, which meta-tests the checklist's quality. Any friction during Foundry's provisioning becomes a checklist bug fixed in this phase.
2. **Producers can write to CIP.** A Foundry internal research agent (or a Cowork session) calls `cip_write(...)` and a row lands — first in a staging area (`cip_pending_writes`), then, after authority check, in the real `cip_*` tables.
3. **The authority model is live.** Every write carries provenance (who wrote, when, why, at what confidence). High-authority writes auto-promote; below-threshold writes queue for human review. Every promote/reject decision is audited.

These three together turn CIP from a read-only analytics surface into a **bidirectional knowledge substrate**. Phase 7 investigative agents inherit the substrate; they don't have to build it.

---

## WDGLL — What Done Looks Like

Phase 2.5 exits when **all** of the following are observable:

### Tenant deliverables

1. **Foundry tenant exists** with at least one lens defined (e.g., "Foundry Internal Ops View"). Provisioned by following `docs/cip/TENANT-ONBOARDING-CHECKLIST.md` verbatim. Any checklist bugs found during provisioning are logged and fixed before Phase 2.5 exits.
2. **At least one Foundry Metabase dashboard** exists for the Foundry lens. Empty initially; populated in M4+ by the first producer.

### Write surface deliverables

3. **`cip_write` API is live across three surfaces** with identical semantics:
   - REST: `POST /cip/write` with `{tenant_id, lens_id, payload, source_agent_id, confidence, rationale}`
   - MCP: `foundry_mcp_cip_write` (wraps REST for agent sessions)
   - Python: `cip_write(...)` function in `src/services/cip/write_service.py` for in-repo use
4. **Writes land in `cip_pending_writes`** (new table, migration cip_12 per the 2026-05-15 renumbering — see §"Migrations" below). Provenance columns populated: `source_agent_id`, `session_id`, `confidence`, `rationale`, `submitted_at`.
5. **Tenant scoping is enforced on writes** — writer session must `SET LOCAL app.current_tenant`; cross-tenant write attempts rejected with an audit log row.

### Authority model deliverables

6. **`cip_write_authorities` table exists** (migration cip_13 per the 2026-05-15 renumbering) — per-lens authority floors keyed by source_agent_id. Runtime-configurable, not hardcoded.
7. **Authority check runs on every pending write:**
   - If `confidence ≥ authority_floor_auto_promote` for that (agent, lens): row auto-promotes to the real `cip_*` tables.
   - Otherwise: row stays in `cip_pending_writes` with `status='pending_review'`.
8. **Promotion queue surface exists:**
   - CLI: `python scripts/cip_review.py --tenant=<id>` lists pending writes, lets reviewer approve/reject.
   - Optional Metabase view of `cip_pending_writes` for Tim's browsing convenience.
9. **Audit log** — every promote/reject decision writes a row to `cip_write_decisions` (append-only) with `decision`, `reviewer_id`, `rationale`, `decided_at`.

### First producer deliverable

10. **At least one real producer is wired end-to-end.** Choice made at M0:
    - **Option A:** Foundry internal research agent that scrapes news/RSS, synthesizes a topic summary, writes it into Foundry tenant with `authority=agent_discovered`, confidence from the agent's own self-report.
    - **Option B:** Cowork session producer — a skill that lets Tim (or any Cowork user) say "save this as a CIP note" and the session writes into Foundry tenant.
    - **Default recommendation:** Option A (cleaner failure modes, easier to restart).

### Observability deliverables

11. **Per-tenant write-rate metrics** surfaced in Metabase or a simple dashboard.
12. **Stale-write detection** — `agent_discovered` rows older than N days (TSP: 14) without a promote/reject decision flag for attention.
13. **Cross-tenant write smoke test** — attempting `cip_write` from Foundry tenant to Wayward tenant fails cleanly with an audit row. Proves grants don't leak into the write path (grants are read-only, Phase 3).

### Documentation deliverables

14. **Write-Back Operator Guide** — `docs/cip/WRITE-BACK-OPERATOR-GUIDE.md`. How to call `cip_write`, what gets staged, how promotion works, how to audit.
15. **Authority Model Reference** — `docs/cip/AUTHORITY-MODEL.md`. The taxonomy (`agent_discovered` / `ingested` / `validated`), per-lens authority_floors, how to configure, how to audit.
16. **Cowork Writer Cookbook** (if Option B chosen) — `docs/cip/COWORK-WRITER-COOKBOOK.md`. How Cowork session scripts write to CIP, example patterns.
17. **Phase 2.5 → Phase 3 Handoff Doc** — `docs/cip/PHASE-2.5-TO-PHASE-3-HANDOFF.md`. What Phase 3 inherits (Foundry tenant live, write surface live, grants schema still pending), what it must build (grants schema cip_09 finally lands here, grants runtime, Rocky Ridge onboarding).

### Non-criteria

- No rich validated-promotion UX (Phase 7).
- No chatbot-initiated writes (Phase 7).
- No cross-tenant writes of any kind — hard-blocked by tenant scoping.
- No temporal point-in-time query API (Phase 7).
- No multiple-producer wiring — one is enough to prove the surface; more producers are Phase 7+.

### Exit gate

Phase 2.5 exits when Tim calls `cip_write(...)` from a Cowork session (or runs the Foundry internal research agent), the row appears in `cip_pending_writes`, authority check runs, the row either auto-promotes or queues for review, Tim reviews it (if queued), and the final row appears in the Foundry Metabase dashboard.

---

## SPEC — Technical Requirements

### S1. Migrations

- **cip_12** — `cip_pending_writes` + `cip_pending_writes_history`. Columns: `pending_write_id`, `tenant_id`, `lens_id`, `target_table`, `payload_jsonb`, `source_agent_id`, `session_id`, `confidence`, `rationale`, `status` enum (`pending_review`, `auto_promoted`, `rejected`), `submitted_at`, plus 9 provenance columns.
- **cip_13** — `cip_write_authorities`. Columns: `authority_id`, `tenant_id`, `lens_id`, `source_agent_id`, `authority_floor_auto_promote` (numeric confidence threshold), `authority_floor_allow` (below which writes are rejected outright), `created_at`, `updated_at`.
- **cip_14** — `cip_write_decisions` (append-only audit). Columns: `decision_id`, `pending_write_id`, `decision` enum (`approved`, `rejected`), `reviewer_id`, `rationale`, `decided_at`.

Migration numbering note (updated 2026-05-15): the original Phase 2.5 plan reserved cip_10/cip_11/cip_12, and the original Phase 1 plan reserved cip_09 for Phase 3 cross-tenant grants. Both reservations are obsolete because the deployed alembic chain on Railway prod has now consumed `cip_09` (metabase role views, landed M5), `cip_10` (history lens views, landed M5), and `cip_11` (sync_mode_backfill — D-159 hotfix added 2026-05-15 during the Wayward incident response so the orchestrator could record `sync_mode='backfill'` rows). Phase 2.5 therefore uses **cip_12 / cip_13 / cip_14** for write-back. Phase 3 cross-tenant grants will use **cip_15** (or whichever slot is next free at Phase 3 kickoff).

### S2. Foundry Self-Tenant Provisioning

- Follow `docs/cip/TENANT-ONBOARDING-CHECKLIST.md` verbatim. Do not deviate — deviations are checklist bugs.
- Foundry tenant row: `type='foundry'`, parent `null`, status `active`.
- At least one Foundry lens: "Foundry Internal Ops View" with `filter_config={}` (unfiltered within Foundry tenant).
- Provision Foundry `cip_clients` shape — likely by topic/thread rather than by company, but the exact model is Tim's call at M1 kickoff.

### S3. `cip_write` API — three surfaces

**REST** — `POST /cip/write` in `src/api/cip/write.py`:
```
Request:  {tenant_id, lens_id, target_table, payload, source_agent_id, session_id, confidence, rationale}
Response: {pending_write_id, status, decided_at?}
```

**MCP** — `foundry_mcp_cip_write` in `foundry-mcp-system/foundry_mcp_server.py`. Wraps REST. Agent sessions call the tool directly.

**Python** — `cip_write()` in `src/services/cip/write_service.py`. In-repo code path. REST and MCP both converge on this function.

All three surfaces **must** go through the same `write_service.cip_write()` implementation — no forked logic. Tenant scoping enforced by `SET LOCAL` wrapping every call.

### S4. Authority model

- Default `authority_floor_auto_promote = 0.9` (TSP — tunable).
- Default `authority_floor_allow = 0.5` (TSP — tunable; below this, writes rejected with an audit row but no promotion queue entry).
- Per (agent, lens) override rows in `cip_write_authorities` for sharper control.
- Authority levels on actual row data: `agent_discovered` (default for agent writes), `validated` (after human promote), `ingested` (reserved for connector-origin; not used by Phase 2.5 writes).

### S5. Promotion queue surface

**CLI** (primary):
```
python scripts/cip_review.py --tenant=<uuid> --lens=<uuid>        # list pending
python scripts/cip_review.py approve <pending_write_id> --rationale="..."
python scripts/cip_review.py reject <pending_write_id> --rationale="..."
```

**Metabase** (optional convenience): a dashboard view of `cip_pending_writes` WHERE status='pending_review' for Tim's browsing. Approvals still go through the CLI.

### S6. First producer (Option A default — Foundry internal research agent)

- Scope: a minimal agent that takes a topic (e.g., "AI agent platform competitive landscape"), pulls recent news/RSS (through existing Integration Mesh connectors or a one-off scraper — infrastructure choice at M4 kickoff), synthesizes a short note, and writes it into Foundry tenant as a `cip_pending_writes` row targeting a "research notes" table (scope-out whether that's `cip_notes` or a new `cip_research_notes` at M0).
- Provenance: `source_agent_id=foundry_research_agent_v1`, `session_id=<agent run id>`, `confidence` self-reported by the agent from a calibration prompt.
- End-to-end: agent runs → writes row → authority check → (probably) queues for review → Tim approves → row appears in Foundry dashboard.

### S7. Observability

- Per-tenant write-rate metric: count of `cip_pending_writes` rows per hour, per tenant.
- Stale-write alerting: `SELECT * FROM cip_pending_writes WHERE status='pending_review' AND submitted_at < now() - interval '14 days'` — flag on dashboard, optional Slack ping.
- Write-decision audit: any row in `cip_write_decisions` is immutable and surfaces in a Metabase view.
- Cross-tenant write smoke test (automated): scripted test that attempts a cross-tenant write and verifies clean rejection with audit row.

### S8. Documentation

Four doc artifacts ship alongside code (S1–S7), following the Phase 1 doc template:
- Write-Back Operator Guide
- Authority Model Reference
- Cowork Writer Cookbook (conditional on Option B)
- Phase 2.5 → Phase 3 Handoff Doc

### S9. Non-negotiables

Same global set as Phase 1: D-017, D-018/D-031/D-077, D-026, CSS classification, UTC, UUIDv4, master branch only.

---

## PLAN — Execution Sequence

Milestones ordered by dependency. Session-bounded pacing.

### Milestone 0 — Vision Revisit + Producer Choice

**Goal:** lock Phase 2.5 scope after Phase 2 Wayward learnings; choose first producer (A or B).

- Review Phase 2 retrospective: any Wayward surprises that reshape Phase 2.5?
- Choose first producer: Foundry internal research agent (A) or Cowork session writer (B). Default A.
- Confirm migration numbering (cip_12+ for Phase 2.5 per the 2026-05-15 reconciliation; cip_15+ for Phase 3 cross-tenant grants).
- Author Phase 2.5 doc skeletons (4 artifacts).

**Exit:** scope locked, producer choice recorded, doc skeletons exist.

### Milestone 1 — Foundry Self-Tenant Provisioning

**Goal:** Foundry is a live CIP tenant; Tenant Onboarding Checklist meta-tested.

- Provision Foundry tenant row. Follow `TENANT-ONBOARDING-CHECKLIST.md` verbatim — log any friction as checklist bug.
- Create Foundry lens (Foundry Internal Ops View).
- Create empty Foundry Metabase dashboard.
- Fix any checklist bugs surfaced during provisioning. Update Phase 1 → Phase 2 handoff if the Phase 2 Wayward pass missed anything.

**Exit:** Foundry tenant exists, RLS verified, at least one lens defined, Metabase dashboard loads (empty), checklist bugs closed.

### Milestone 2 — `cip_write` API (three surfaces)

**Goal:** REST + MCP + Python call paths all converge on one write_service implementation.

- Apply migration cip_12 (`cip_pending_writes`).
- Implement `src/services/cip/write_service.py::cip_write()`. Tenant scoping enforced.
- Wire REST endpoint `POST /cip/write`.
- Wire MCP tool `foundry_mcp_cip_write`.
- Integration tests: all three surfaces produce the same row in `cip_pending_writes` given identical input.

**Exit:** all three surfaces write to `cip_pending_writes`; cross-tenant writes rejected with audit row; tenant scoping verified.

### Milestone 3 — Authority Model + Promotion Queue

**Goal:** authority floors live; CLI review tool works; audit log captured.

- Apply migrations cip_13 (`cip_write_authorities`) and cip_14 (`cip_write_decisions`).
- Seed default authority rows (global fallback + Foundry-lens-specific).
- Implement authority check in `write_service.cip_write()` — auto-promote if above threshold, queue if below.
- Implement `scripts/cip_review.py` CLI.
- Optional: Metabase pending-review view.
- Fill in: **Authority Model Reference** doc.

**Exit:** high-confidence writes auto-promote; low-confidence writes queue; CLI review works; audit log captures every decision.

### Milestone 4 — First Real Producer

**Goal:** one producer writes end-to-end into Foundry tenant; Tim sees the row in the dashboard.

- Implement first producer per M0 choice (A or B).
- Wire producer → `cip_write()` → authority check → (likely) queue → human approve → Foundry dashboard.
- Verify end-to-end with a real run.
- Fill in: **Write-Back Operator Guide** and (if Option B) **Cowork Writer Cookbook**.

**Exit:** one real producer produces real content, pending review works, approved content shows in Foundry Metabase.

### Milestone 5 — Observability + Stale-Write Detection

**Goal:** write surface has visibility and aging alarms.

- Implement per-tenant write-rate metric (Metabase view).
- Implement stale-write detection (query + dashboard flag + optional Slack integration).
- Implement automated cross-tenant-write smoke test.
- Verify: writes older than 14 days with no decision surface in the stale-write view.

**Exit:** operators can answer "how many writes per hour per tenant?" and "what's aging in the queue?" without writing ad-hoc SQL.

### Milestone 6 — Hardening + Phase 2.5 → Phase 3 Handoff

**Goal:** Phase 2.5 lock; Phase 3 has a clean starting point.

- Stress-test the three surfaces against pathological inputs (oversized payloads, malformed JSONB, wrong tenant_id, missing confidence).
- Retrospective: what did the write surface teach us? Any grant-runtime implications for Phase 3?
- Fill in: **Phase 2.5 → Phase 3 Handoff Doc**.
- Verify: cross-tenant write smoke test remains clean under all edge cases.

**Exit:** Phase 2.5 LOCKED DONE. Phase 3 Rocky Ridge + Grants Runtime VISION/WDGLL/SPEC/PLAN authoring can begin.

### Milestone 7 — Product-Ready Gate: Phase 2.5 Lock

**Goal:** demonstrable end-to-end write path from producer to Foundry dashboard.

- Tim (or another reviewer) runs the full flow: producer generates content, content queues, Tim approves, Tim sees the row in Foundry Metabase.
- All four Phase 2.5 docs reviewed and finalized.
- PM scope updates: Access & Operations pillar advances from "minimum viable" to "write path live"; Ingestion & Connectors pillar advances to "producer side lit."

**Exit:** Phase 2.5 LOCKED DONE. Ready for Phase 3.

### Risks & contingencies

**R1. Tenant Onboarding Checklist has gaps that surface during Foundry provisioning.**
*Mitigation:* gaps are expected — that's what meta-testing means. M1 allocates explicit time to fix them. Phase 3 Rocky Ridge onboarding gets a doubly-hardened checklist.

**R2. Authority thresholds prove wrong against real agent confidence distributions.**
*Mitigation:* thresholds are TSP — tunable without migration. First producer's confidence calibration drives threshold refinement. Expect tuning in M4–M5.

**R3. First producer's output is low-quality — nothing worth approving.**
*Mitigation:* Phase 2.5 acceptance is the *surface works*, not *the producer is good*. If Option A's research agent produces noise, that's a Phase 7 quality problem, not a Phase 2.5 surface problem. As long as the write path works end-to-end with some real content, Phase 2.5 ships.

**R4. Cross-tenant write path leaks despite tenant scoping.**
*Mitigation:* automated cross-tenant smoke test runs in CI from M2 forward. Any leak blocks Phase 2.5 exit. RLS + SET LOCAL review from Phase 1 RLS & SET LOCAL Operator Guide applies here too.

**R5. Producer choice (A vs B) gets litigated past M0.**
*Mitigation:* M0 choice is binding. Changing producer after M0 starts means restarting the milestone. If both producers end up being built, that's a Phase 7+ decision.

### Dependencies

- Phase 1 plain-jane LIT (framework, lenses, registry, docs).
- Phase 2 Wayward Onboarding LIT (real connectors, real lenses, real dashboards — proves the platform runs outside fixture).
- Foundry tenant can be created (type='foundry' — existing in the tenant model).
- Metabase platform service exists (Phase 1 M5 deliverable).
- MCP server repo (`foundry-mcp-system`) can accept a new tool.

### What this plan does NOT commit to

- Exact authority thresholds (TSP, tunable).
- Exact producer scope (A vs B chosen at M0).
- Metabase vs CLI for promotion queue primary surface (CLI is default; Metabase is a "nice to have").
- When Phase 3 starts (Phase 3 authoring decision).

---

## Cross-references

- `PHASE-1-PLAN.md` — plain-jane phase this one builds on
- `ROADMAP.md` — Phase 2.5 slot and dependencies
- `vision/VISION.md` — product vision
- `docs/cip/TENANT-ONBOARDING-CHECKLIST.md` — Phase 1 deliverable meta-tested here
- `docs/cip/WRITE-BACK-OPERATOR-GUIDE.md` — Phase 2.5 deliverable
- `docs/cip/AUTHORITY-MODEL.md` — Phase 2.5 deliverable
- `docs/DECISION-LOG.md` — D-numbers cited

## Authoring note

Phase 2.5 is provisional until Phase 2 ships and Phase 2.5 kicks off. At kickoff, M0 revisits this plan in light of Phase 2 learnings and locks the final shape. Expect small reshaping; large reshaping triggers a Tier 3 authorization from Tim.
