---
id: CIP-SOP-017
uuid: 8a4c7e2d-0e9f-4c5b-9a3f-2b8e9c5d7e4a
title: Junior Dev Onboarding — Your First Two Weeks on CIP
type: sop
owner: tim
solve_for: A junior dev arriving Monday morning can take on CIP autonomously and ship
  meaningful work by Friday. Read this first.
stage_label: adopt
domain: meta
version: '1.0'
created: '2026-05-19'
last_modified: '2026-05-19'
last_reviewed: '2026-05-19'
review_cadence: 90
---

# Junior Dev Onboarding — Your First Two Weeks on CIP

> Welcome. This doc is the literal step-by-step you walk through Monday through Friday of week one. Day-by-day. Every doc you need to read is linked. Every command you need to run is in here. If something is wrong, **the doc is wrong, not you** — escalate so we fix it.

## TL;DR — What CIP is

CIP = **Client Intelligence Platform**. It's a Foundry product (one of several: CRM, Knowledge System, Chatbot, etc.) that turns a venture's scattered client data — Zendesk tickets, HubSpot deals, Firefly call transcripts, files, etc. — into a **live, queryable, agent-accessible intelligence layer**.

**Three things to know in 30 seconds:**

1. **It's a product, not a script.** Foundry will eventually sell CIP to external customers (Stage 3 graduation). Architectural choices reflect that — `foundry-cip` is its own repo, its own Pinecone index, its own R2 prefix, its own roadmap.
2. **Multi-tenant.** Every CIP row carries a `tenant_id` (e.g., EcomLever venture) and most carry a `client_id` (e.g., Wayward inside EcomLever). Postgres RLS enforces isolation; tenant context is set via `SET LOCAL app.current_tenant`.
3. **Four access paths**: SQL (`cip_*` tables + `lens_*` views), semantic search (CIP-Pinecone), knowledge graph (FalkorDB — Phase 3+), file originals (CIP-R2). See [`FOUR-ACCESS-PATHS.md`](FOUR-ACCESS-PATHS.md).

## Day 1 — Orient + run-it-locally (Monday, 4-6 hours)

### Step 1 — Read in this order (90 min)
1. [`README.md`](../README.md) — repo intro
2. [`CLAUDE.md`](../CLAUDE.md) — agent behavioral standards + Foundry conventions (master-branch-only, FND-S14 tier discipline, etc.)
3. [`docs/vision/VISION.md`](vision/VISION.md) — top-level product vision (CIP-FW-001). Read §1-§6, skim §7-§10.
4. [`docs/ARCHITECTURE-SPLIT.md`](ARCHITECTURE-SPLIT.md) — the HARD SPLIT rule (CIP-SPEC-010). **The single most important architectural doc.** Read every word.
5. [`docs/architecture/ARCHITECTURE.md`](architecture/ARCHITECTURE.md) — three-data-layers model
6. [`docs/vision/ROADMAP.md`](vision/ROADMAP.md) — phase progression
7. [`docs/PROPERTY-GLOSSARY-PATTERN.md`](PROPERTY-GLOSSARY-PATTERN.md) — semantic layer for connector data

### Step 2 — Repo setup (1 hour)
```bash
git clone https://github.com/Foundry-Studio/foundry-cip.git
cd foundry-cip
pip install -e ".[dev,fixture]"
pre-commit install
```

### Step 3 — Env vars (30 min)
Talk to Tim for the secrets. You need (minimum to do anything real):

```bash
# DB (Railway prod for read access; spin up a local Postgres for write tests)
export DATABASE_PUBLIC_URL=postgresql://...

# Vendor tokens (for any backfill work)
export WAYWARD_HUBSPOT_TOKEN=pat-na2-...
export WAYWARD_ZENDESK_TOKEN=...
export WAYWARD_ZENDESK_USER=jake@wayward.com
export WAYWARD_ZENDESK_SUBDOMAIN=waywardsupport

# CIP infrastructure (per the hard split)
export CIP_PINECONE_API_KEY=pcsk_...
export CIP_PINECONE_INDEX_HOST=https://foundry-cip-h705p9t.svc.aped-4627-b74a.pinecone.io
export CIP_PINECONE_INDEX_NAME=foundry-cip
export CIP_R2_BUCKET_NAME=foundry-agent-system
export CIP_R2_ACCESS_KEY_ID=...
export CIP_R2_SECRET_ACCESS_KEY=...
export CIP_R2_ENDPOINT_URL=https://...r2.cloudflarestorage.com
export CIP_R2_PATH_PREFIX=cip-originals

# JOS CLI
export JOS_LOCAL=/path/to/jordan-operating-system
```

### Step 4 — Verify your setup (30 min)
```bash
# Tests pass (unit-only; full suite needs Docker)
PYTHONHASHSEED=0 pytest --ignore=tests/migrations -q

# JOS compliance is clean
scripts/jos check

# Talk to Pinecone
python -c "from cip.integration_mesh.clients import PineconeClient; pc = PineconeClient(); print(pc.describe_index_stats())"

# Talk to the embedding endpoint
python -c "from cip.integration_mesh.clients import EmbeddingClient; e = EmbeddingClient(); v = e.embed('hello'); print(f'dim={len(v)}')"
```

If any of those fail: STOP. Ask Tim or whoever is on-call. Don't push through — the env is the foundation and "I'll fix it later" never works.

### Step 5 — Demo CIP semantic search (1 hour)
Run the demo against Wayward's live data:

```bash
DATABASE_URL=$DATABASE_PUBLIC_URL python scripts/demo_wayward_semantic_search.py
```

You should see 5 real Wayward queries returning relevant ticket comments + engagement notes with cosine similarity 0.6-0.8. **If that works, your setup is good.** Spend 30 min playing with custom queries — modify the script to try your own questions against Wayward data.

## Day 2 — Read PM + pick your first ticket (Tuesday, 4-6 hours)

### Step 1 — Get oriented in PM (90 min)
```bash
# Project state
mcp_tool foundry_mcp_pm_project_status --project_id 596825db-61bc-4899-bc6c-e207489ca35d

# All scopes (the work units)
mcp_tool foundry_mcp_db_query "SELECT substring(scope_id::text,1,8) as id, title, status FROM project_scopes WHERE project_id='596825db-61bc-4899-bc6c-e207489ca35d' AND status NOT IN ('done','archived','cancelled','killed') ORDER BY sort_order"
```

The `health_note` on the project tells you what's going on RIGHT NOW. Read it carefully — it's the closest thing to a "what's the team doing this week" status.

### Step 2 — Skim recent decisions (45 min)
```bash
mcp_tool foundry_mcp_db_query "SELECT substring(decision_id::text,1,8) as id, decision_type, summary, created_at FROM project_decisions WHERE project_id='596825db-61bc-4899-bc6c-e207489ca35d' ORDER BY created_at DESC LIMIT 15"
```

The 5 most important recent decisions (as of 2026-05-19):
- `d83c7e1d` — **CIP Hard Split** (read CIP-SPEC-010 alongside this)
- `c575c81c` — Tenant model correction (placeholder UUIDs forbidden; canonical IDs only)
- `859c0bd9` — JOS adoption (every doc has JOS-conformant frontmatter)
- `426ae5c0` — Frameworks/Surfaces as navigation buckets only
- `c225af8b` — M8 Product-Ready Gate PASSED (Phase 1 LIT)

### Step 3 — Pick a first scope (1 hour)
Three good first scopes for a junior dev (all roughly 3-4h each, low risk):

- **`cb6750f0` HubSpot Owners + Pipelines resolver** (already DONE — read it to understand the pattern)
- **Owner name fill-in**: take the 5 placeholder owners in `cip_owners` and update with real names (Tim provides). Update `scripts/seed_wayward_hubspot_pipelines_and_owners.py` `OWNER_ROSTER` constant and re-run.
- **Apply drift detector findings**: run `scripts/detect_property_drift.py --apply` after confirming with Tim. Baseline ~1,300 new properties into the registry.

### Step 4 — Read the operator guides (rest of day)
Skim these — you'll need them:
- [`CONNECTOR-AUTHORING-GUIDE.md`](CONNECTOR-AUTHORING-GUIDE.md) — building a new vendor connector
- [`MIGRATION-RUNBOOK.md`](MIGRATION-RUNBOOK.md) — alembic discipline
- [`LENS-AUTHORING-GUIDE.md`](LENS-AUTHORING-GUIDE.md) — building lens views
- [`RLS-SET-LOCAL-OPERATOR-GUIDE.md`](RLS-SET-LOCAL-OPERATOR-GUIDE.md) — tenant context discipline
- [`SYNC-ORCHESTRATOR-GUIDE.md`](SYNC-ORCHESTRATOR-GUIDE.md) — how syncs work
- [`TENANT-ONBOARDING-CHECKLIST.md`](TENANT-ONBOARDING-CHECKLIST.md) — onboard a tenant

## Day 3-4 — Ship your first PR (Wed-Thu, 8-12 hours)

### Pattern to follow (every commit)
1. `git branch --show-current` → confirm `master` (foundry-cip is master-only)
2. Read existing similar code BEFORE writing new. CIP has strong conventions (provenance columns, RLS, SCD-2 history).
3. Write the code. Tests if you're modifying behavior.
4. `scripts/jos check` → PASS
5. `PYTHONHASHSEED=0 pytest --tb=line -q` → all green
6. Commit with a **`Local-Verified: <tier>`** trailer (FND-S14; see [CLAUDE.md](../CLAUDE.md))
7. Push to master.

### Commit shape (look at recent commits for the pattern)
```
feat(scope): one-line summary

Multi-line description explaining WHY, not what.
PM scope: <id> (mark done if shipping the scope).
Decisions referenced: <decision_id>.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
Local-Verified: A (docs only) | B (code, pytest+mypy+ruff clean) | C (schema, includes alembic upgrade head clean)
```

## Day 5 — Update PM + share what you learned (Friday)

### Step 1 — Update PM
For every scope you touched:
- Comment with what changed (`foundry_mcp_pm_comment`)
- If complete: `foundry_mcp_pm_mark_scope_done`
- If new follow-up surfaced: file a new scope (`foundry_mcp_pm_create_scope`)

### Step 2 — Refresh project health
If anything material changed:
- `foundry_mcp_pm_set_project_health` with a fresh narrative note

### Step 3 — Update onboarding doc
If you found anything in THIS doc wrong/missing/confusing, fix it. The next junior dev reads what you fix.

---

## When you're stuck — escalation tree

| Symptom | Who/what to check first |
|---|---|
| Can't reach Pinecone / R2 / Postgres | Railway dashboard → are credentials valid? Tunnels up? |
| Embedding endpoint failing | Check `server-b` status; embedding model running on Ollama at `100.100.10.110:11434` |
| jos check failing | Frontmatter on whichever doc; CIP-K01 (CSS classification contract) + JOS schema v1.5 |
| pytest failing in tests/migrations | Need Docker — those tests use testcontainers. CI runs them; locally skip with `--ignore=tests/migrations` |
| Schema confusion | `cip/migrations/versions/cip_NN_*.py` is authoritative; never edit deployed migrations |
| "Where does this new content live?" | [`ARCHITECTURE-SPLIT.md`](ARCHITECTURE-SPLIT.md) §1 — answer is there |
| Concept you don't recognize | Search docs/ first; then `git log --grep`; then ask |

## Key contacts (as of 2026-05-19)

| Role | Person |
|---|---|
| Owner / Product | Tim Jordan |
| Secondary dev | Van |
| AI agent | Claude Code (typically via Cowork / claude.ai / IDE) |

## Cross-references

- [`VISION.md`](vision/VISION.md) — top-level product vision (CIP-FW-001)
- [`ARCHITECTURE-SPLIT.md`](ARCHITECTURE-SPLIT.md) — hard split rule (CIP-SPEC-010)
- [`ARCHITECTURE.md`](architecture/ARCHITECTURE.md) — three-data-layers model (CIP-SPEC-003)
- [`ROADMAP.md`](vision/ROADMAP.md) — phase progression (CIP-SPEC-008)
- [`TENANT-ONBOARDING-CHECKLIST.md`](TENANT-ONBOARDING-CHECKLIST.md) — adding a tenant (CIP-SOP-010)
- PM project `596825db-61bc-4899-bc6c-e207489ca35d` — all scopes, decisions, activity
- Foundry-Studio/foundry-cip — the repo
- Foundry-Studio/jordan-operating-system — JOS governance source
- Foundry-Studio/Foundry-Agent-System — monorepo that CONSUMES foundry-cip
