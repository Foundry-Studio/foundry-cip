---
id: CIP-SPEC-009
uuid: 12e165ca-6213-470e-a015-0d9ffc9c8668
title: CIP Extraction Reference
type: spec
owner: tim
solve_for: Reference history of how foundry-cip was extracted from the Foundry-Agent-System
  monorepo, preserved for audit.
stage_label: adopt
domain: meta
version: '1.0'
created: '2026-04-30'
last_modified: '2026-05-16'
last_reviewed: '2026-05-19'
review_cadence: 365
---

# CIP Extraction Reference

This file documents the extraction of CIP from the Foundry-Agent-System
monorepo into a standalone repository.

- **Extraction date:** YYYY-MM-DD
- **Split point tag:** `cip-extraction-point` (in this repo)
- **Source paths:**
  - `products/client-intelligence-platform/`
  - `docs/cip/`
  - `migrations/versions/cip_01_clients.py` … `cip_08_tickets_and_registry.py`
  - `tests/migrations/test_rls_cip_*.py` (9 files)
  - `tests/migrations/conftest.py` (CIP-specific fixtures)
- **Target repo:** `Foundry-Studio/foundry-cip`
- **Target HEAD at extraction:** `<foundry-cip-head-sha>`
- **Tool used:** `git filter-repo --path ...` (multi-path)
- **Note:** Commit SHAs in foundry-cip differ from this monorepo due to filter-repo's history rewrite. Extraction is deterministic — running the same command on `cip-extraction-point` produces identical results.
- **Pre-rename history:** CIP code lived under `WORKBENCH/tim/research/client-intelligence-platform/` until 2026-04-20 when promoted to `products/client-intelligence-platform/`. The pre-rename history is NOT preserved in foundry-cip (acceptable trade-off per Q4 of the extraction plan; pre-rename history remains visible in the monorepo at or before the `cip-extraction-point` tag).

## Where to find CIP now

- Code, docs, migrations: https://github.com/Foundry-Studio/foundry-cip
- Subsystem contracts that REFERENCE CIP (D-118 etc.): unchanged in this monorepo at `docs/subsystems/integration/CONTRACT.md` etc.
- PM scopes for CIP / CIPWAY / CIPRR: unchanged in this monorepo's PM system.
- D-118, D-122, D-123, D-126, D-133, D-134, D-135, D-146 (governance): unchanged in `docs/DECISION-LOG.md`.

## Why CIP code moved out (but governance stayed in)

CIP graduates to a standalone repo so ventures can `pip install foundry-cip` without dragging the full monorepo. Foundry-Agent-System still consumes foundry-cip as a dependency. Decision authority for CIP-affecting changes remains with this monorepo's DECISION-LOG; foundry-cip implements decisions, doesn't author them.

## Multi-repo Alembic operational model

Per D-146, foundry-cip's `migrations/env.py` uses a separate `version_table = "alembic_version_cip"`. Foundry-Agent-System keeps the default `alembic_version` table. The two `alembic upgrade head` chains coexist in the shared Foundry Postgres without conflict. When Phase 8 extracts cip_* data to a dedicated Postgres, the version-table separation makes the move trivial.

## SHA mapping

There is no 1:1 SHA mapping. To find the monorepo equivalent of a foundry-cip commit:

```bash
# In foundry-cip:
git log --oneline <foundry-cip-sha>

# In this monorepo (at or before cip-extraction-point):
git log --all --oneline --grep="<commit message snippet>" -- \
  products/client-intelligence-platform/ docs/cip/ migrations/versions/cip_*.py tests/migrations/test_rls_cip_*.py
```

The `cip-extraction-point` tag in Foundry-Agent-System marks the last commit that contained CIP. All foundry-cip commits derived from this tag's tree.
