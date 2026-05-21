---
doc_type: wdgll
elaborates_slot: capability
declared_thing: foundry-cip
declared_thing_kind: product-internal
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
audience: [operator, agent, leadership]
diataxis_type: explanation
connects_to:
  - GUARANTEES.md
  - HEALTH-STANDARD.md
---

# What Does Good Look Like — Foundry CIP

> Per JOS-S22. Operator-feel doc — what "CIP humming" feels like. Distinct from HEALTH-STANDARD (mechanical pass/fail) — WDGLL is the qualitative landscape.

## The day-in-the-life snapshot (Phase 2 onwards)

It's morning. Wayward's overnight sync ran. An operator opens Metabase at `reports.project-silk.com` and sees:

- **Wayward dashboards** — fresh data; no "stale" indicator.
- **Sync runs table** — last 24h shows: Zendesk sync `success` (~20s), HubSpot sync `success` (~45s), zero `error` rows.
- **Connector circuit breakers** — all `closed` (healthy).
- **`cip_sync_runs.error_detail`** — empty across the last 24h.
- **Lens views** — `lens_all_companies` returning expected row count; lens-vs-raw probe blocks cross-tenant.
- **Cost line** — yesterday's per-tenant LLM spend (for knowledge ingestion + GraphRAG extraction) within envelope.

They don't have to do anything. They glance, click through a dashboard, and the platform keeps running. The Wayward team gets their dashboards; the CEO briefings happen on schedule; the operator stays at the strategic layer.

## What's humming

### Connector health
- Every connector's last `cip_sync_runs` row in the last 24h is `success`.
- HubSpot connector pulled historical property revisions on first sync (D-159 backfill) — `cip_*_history` rows visible immediately after first sync.
- Zendesk pagination terminates cleanly (`end_of_stream=true`); no 22-hour infinite loop (the 2026-05-14 bug class stays caught).
- Connector schema-drift tests pass — every column the mapper references exists in the deployed schema.

### Data integrity
- SCD-2 history rows accumulate correctly — every update to a company/contact/deal/ticket creates a `_history` row with proper valid_from/valid_to.
- 9 provenance columns populated on every row — `tenant_id`, `client_id`, `source_connector`, `source_id`, etc.
- Cross-tenant probe (run as `cip_metabase_role` with TENANT_B GUC against TENANT_A data) returns 0 rows. Always.

### Lens engine
- New lenses get added by INSERT-only into `cip_views` — operators can deploy a new client view without engineering involvement.
- Lens snapshot harness passes — corpus + lens results SHA-256-match committed snapshots.
- Per-tenant lens isolation holds — tenant A's lens doesn't surface tenant B's data.

### Discoverability
- `cip_connector_property_registry` has ≥22 rows per active object_type.
- `features.yaml` matches deployed reality — every `status: shipped` feature's `path_to_more` resolves at HEAD.
- 4 access paths (Structured / Derived Knowledge vector / Derived Knowledge graph / Originals) all queryable end-to-end.

### Governance
- Every commit on master carries `Local-Verified: <tier>` trailer (FND-S14).
- `pyproject.toml` ranges + `requirements-dev.txt` lockfile in sync; `uv pip compile --check` clean.
- `pytest`, `mypy --strict`, `ruff` all clean on cip/.

## What's drifting (early signals)

| Early signal | What it usually means |
|---|---|
| Single connector's last `cip_sync_runs` shows `running` for >2h | Stuck (likely pagination or auth issue) — kill the run, investigate before next scheduled fire |
| `error_detail` showing the same exception class 3+ times in 24h | Connector regression — pause schedule, fix, regression test |
| `_history` row count not growing while parent table is updating | SCD differ may be broken; check `differ_test.py` regression |
| `cip_metabase_role` permission error on a `lens_*` view | New lens INSERTed but grant matrix not extended — fix in migration |
| `cip_views.filter_config` JSONB malformed | Lens authoring discipline broke; validation should catch in unit tests |
| Faker corpus golden-file snapshot diff | Either intentional bump (commit-explain) or determinism broke (Python version, PYTHONHASHSEED, Faker pin) |

## What's broken (alert fires)

| Failure | Recovery |
|---|---|
| Connector returns `ProtocolShapeError` | Caught by conformance harness pre-deploy; rollback connector code if it slipped through |
| RLS test fails | CRITICAL — block migrations; investigate via `tests/migrations/test_rls_cip_*.py` |
| Cross-tenant probe returns rows | P0 incident — pause writes; investigate `app.current_tenant` GUC + middleware |
| `mypy --strict` regression on cip/ | CI block; fix types or escalate to bypass with explicit reason |
| Lockfile divergence | `lockfile-freshness` job fails; recompile with `uv pip compile --universal` |

## What CIP does NOT do (so operators don't wait for it)

- **Does not auto-deploy migrations.** `alembic upgrade head` is operator-initiated (manually triggered for prod).
- **Does not auto-deploy connector code.** New connector requires conformance-harness pass + manual approval.
- **Does not silently swallow errors.** Every connector failure lands in `cip_sync_runs.error_detail` with stack trace; circuit breakers trip; alerts fire.
- **Does not run consumption surfaces.** Metabase, REST, MCP all live in FAS; CIP only exposes the Postgres views + Python API.

## Test "are we humming?" (5-min drive-by)

1. Metabase dashboard loads in <5s for the venture (Wayward, etc.)?
2. `cip_sync_runs` last 24h has zero `error` rows?
3. `pytest` against last commit passes 44/44 connector tests?
4. `git log -5` shows commits with `Local-Verified:` trailers?
5. No `running`-status sync rows older than 2h?

5/5 = humming. 3-4 = drifting; check the failing signal. ≤2 = active incident.

## Connected docs

- [`GUARANTEES.md`](GUARANTEES.md) — contractual promises
- [`HEALTH-STANDARD.md`](HEALTH-STANDARD.md) — mechanical verification
- [`docs/vision/VISION.md`](docs/vision/VISION.md) — 2027-05 north star
- [`docs/vision/ROADMAP.md`](docs/vision/ROADMAP.md) — 9-phase shape
- [`docs/PHASE-1-TO-PHASE-2-HANDOFF.md`](docs/PHASE-1-TO-PHASE-2-HANDOFF.md) — Phase 1 exit + Phase 2 entry criteria
