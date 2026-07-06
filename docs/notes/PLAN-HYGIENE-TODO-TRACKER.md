---
doc_type: note
owner: tim
status: active
created: 2026-07-06
last_modified: 2026-07-06
review_cadence: 90
---
# Plan-hygiene TODO tracker

Anchor for the deferred plan-hygiene / doc-sync TODOs scattered through the doc suite, surfaced by
the 2026-07-06 QC pass. **These are not being fixed now** — this note exists so they have a single
review home and cannot silently rot. They are prose "should document / should mention" items
reconciling the shipped reality against the older plan §-numbering; none is a code defect (a
repo-wide `grep -rEn "\bTODO\b" cip/` returns **zero** — the framework code carries no `# TODO`s).

Work them off in a dedicated plan-hygiene pass (Atlas's `v5.4` label), or delete each as it's
addressed.

## Anchors (file:line at 2026-07-06)

**docs/CONNECTOR-AUTHORING-GUIDE.md**
- `:392` — Atlas v5.4 TODO: update plan §9 acceptance #4 wording "6 PASSED" → "7 PASSED" (Test 7 `test_post_commit_rls_isolation.py` added by PATCH-NR-1).
- `:689` — `## v5.4 plan-hygiene TODOs surfaced by this guide` section:
  - `:695` — §10.1 §10 should mention `MAX_RATE_LIMIT_SLEEP_SECONDS = 300` cap explicitly.
  - `:696` — §10.1 §7 should document `EXTRAS_COLUMN_BY_TABLE` reality + `cip_views` no-extras case (Deltas 4 + 5).

**docs/SYNC-ORCHESTRATOR-GUIDE.md**
- `:399` — `## v5.4 plan-hygiene TODOs surfaced by this guide` section (line numbers shifted +~45 after the 2026-07-06 §12 "Scheduled deployment" insert):
  - §10.2 §4 should document the deployed 5-counter mapping explicitly (Delta 1).
  - §10.2 §6 should document the `set_config(..., true)` SQL (Delta 14), not the plan's `SET LOCAL = :tid` shape.
  - §10.2 §6 should mention `autoflush=False, expire_on_commit=False` rationale.
  - §10.2 §7 forward-pointer should mention the detect-then-assign pattern for `tenant_id` / `ingestion_batch_id` (Delta 8).

## Refresh command

Line numbers drift as docs are edited. To re-enumerate the full set (authoritative over the anchors
above):

```bash
grep -rEn "\bTODO\b|## v5\.4 plan-hygiene|should document|should mention" docs/ | grep -v __pycache__
```
