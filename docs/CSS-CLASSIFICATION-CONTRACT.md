---
id: CIP-K01
uuid: ae7524b9-ef2e-402d-a9a2-782aacb4b8a1
title: CIP CSS Classification Contract
type: contract
owner: tim
solve_for: Contract for how CIP content classifies under the JOS triad CSS dimension.
  Currently skeleton; populated in M8 Block 1c.
stage_label: assess
domain: doc
version: '1.0'
created: '2026-04-21'
last_modified: '2026-05-09'
last_reviewed: '2026-05-16'
review_cadence: 180
milestone: Phase-1-M3
---

# CIP CSS Classification Contract

> **Status:** draft — populated 2026-05-09 during the post-M3 hardening sweep with the permitted-`kind:` enumeration. The monorepo's `docs/subsystems/meta/classification-contract.md` is the canonical CSS contract; this doc is foundry-cip's local instantiation: which `kind:` slugs apply *here*, plus the resolved `domain:` (always `client-intelligence-platform`).

## Purpose

Specify the CSS classification required for every CIP file: which `kind` values apply, which `domain` values are allowed, how `touches` is populated, and the declaration-priority resolution order (inline > seed > frontmatter > path inference).

## Who reads this

- Every engineer adding a file to CIP (migration, connector, lens, service, doc).
- Reviewers enforcing the classification on PR.
- CSS tooling that reads/writes `# foundry: kind=X domain=Y` headers and frontmatter.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Creates this skeleton. |
| M1–M8 — each Phase-1 milestone | Populates §2 kind/domain tables as new file classes come online. |
| M7 — Four-access-paths validation | Populates §5 discoverability-registry coupling (registry entries carry CSS tags). |

Cross-ref: `CLAUDE.md` → CSS Classification rule, `docs/subsystems/meta/classification-contract.md` (parent CSS contract), D-122 (domain ownership by CSS tag, not folder location).

## Outline

### 1. Why classification matters for CIP

TBD (M1) — D-122 domain-ownership-by-tag lets `cip_*` files live anywhere in the repo without losing ownership semantics.

### 2. Allowed `kind` values in CIP

The 8 permitted `kind:` slugs for foundry-cip files (subset of the monorepo's component-type guide; only the kinds actually instantiated in this repo):

| `kind` | Where it applies | Example artifacts |
|---|---|---|
| `service` | Framework code under `cip/integration_mesh/` (orchestrator, persister, recorder, scd_differ, etc.) | `cip/integration_mesh/orchestrator.py`, `cip/integration_mesh/persister.py` |
| `fixture` | Reference-implementation connectors + mappers + corpus generators under `cip/integration_mesh/connectors/fixture/` | `cip/integration_mesh/connectors/fixture/connector.py` |
| `migration` | Alembic migrations under `cip/migrations/versions/` | `cip/migrations/versions/cip_01_clients.py` |
| `schema` | Migration env / script template — schema infrastructure, not data DDL | `cip/migrations/env.py`, `cip/migrations/script.py.mako` |
| `test` | Everything under `tests/` (unit, integration, conformance, e2e, RLS) | `tests/integration_mesh/test_orchestrator.py` |
| `doc` | Everything under `docs/` (vision, architecture, runbooks, notes, archive, research) + root `*.md` | `docs/vision/VISION.md`, `CLAUDE.md`, `README.md` |
| `config` | Build / lint / CI / pre-commit / governance config files | `pyproject.toml`, `.pre-commit-config.yaml`, `.gitleaks.toml`, `.github/workflows/test.yml`, `requirements-dev.txt`, `alembic.ini` |
| `script` | Standalone executable scripts (none currently — kind reserved for future operational scripts) | (reserved) |

The monorepo's classification contract may permit additional kinds (`engine`, `tool`, `agent`, `module`, etc.) — those don't apply in foundry-cip because the library shape doesn't host engines, tools, or agents.

**Declaration mechanism:**
- **Python source:** inline `# foundry: kind=X domain=client-intelligence-platform [touches=...]` comment in the first 10 lines of the file.
- **Markdown docs:** YAML frontmatter with `kind:` and `domain:` keys.
- **Config files** (no comment/frontmatter syntax): inferred by directory + filename per the monorepo's classification-contract sidecar pattern (no sidecar deployed yet for foundry-cip — `safe: false` warnings are acceptable for now).

### 3. Allowed `domain` values in CIP

**Single value: `client-intelligence-platform`.** Every artifact in this repo declares `domain: client-intelligence-platform`. There is no second-level domain split inside the library — finer-grained subdomain slugs (`cip-structured`, `cip-unstructured`, `cip-lenses`) are deferred until a D-number authorizes them.

`Touches` MAY reference adjacent monorepo subsystems (`integration`, `knowledge`, `graph`, etc.) when a CIP file connects to them — see §4.

### 4. `touches` rules

TBD (M1) — comma-separated list of adjacent domains this file reads/writes; guides the CSS blast-radius tool.

### 5. Declaration-priority resolution

TBD (M1) — inline comment (`# foundry: kind=X domain=Y`) beats YAML frontmatter beats seed file beats path inference; first-match wins.

### 6. Python file template

TBD (M1) — `# foundry: kind=... domain=... touches=...` example for connectors, lenses, services.

### 7. Markdown file template

TBD (M1) — YAML frontmatter example (this doc is the reference example).

### 8. Migration-file classification

TBD (M1) — `kind=migration domain=client-intelligence-platform` plus a `touches` of affected subsystems.

### 9. Discoverability-registry coupling

TBD (M7) — registry entries carry CSS tags so agents can filter by domain when searching for tools / data / lenses.
