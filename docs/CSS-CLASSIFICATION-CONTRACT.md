---
id: CIP-K01
uuid: ae7524b9-ef2e-402d-a9a2-782aacb4b8a1
title: CIP CSS Classification Contract
type: contract
owner: tim
solve_for: Contract for how CIP files classify under the CSS dimension — kind/domain/touches
  declarations, resolution priority, and discoverability-registry coupling.
stage_label: adopt
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

Per D-122 (domain ownership by CSS tag, not folder location), every file in foundry-cip declares its **kind** (what category of artifact it is) and **domain** (which subsystem owns it). The classifier reads those declarations and surfaces them to:

- The **blast-radius tool** — answers "what does this file touch?" so a change to one connector doesn't accidentally trigger noisy reviews of unrelated subsystems.
- The **discoverability registry** — agents searching for "all CIP migrations" or "all CIP connectors" filter by `kind=migration` / `kind=fixture`, not by directory path.
- **PR review routing** — CSS-tagged files announce their owner; reviewers don't need to know the directory layout.
- **JOS compliance** — JOS-S07 (all governed objects registered) consumes the kind/domain pair to verify ownership and registry membership.

Without explicit classification, a Python file at `cip/integration_mesh/foo.py` could be a service, a fixture, a script, or a test — only the directory hints, and directory inference breaks the first time a file moves. The CSS contract is the binding declaration.

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

`touches` is an optional comma-separated list of adjacent monorepo subsystems that a CIP file reads or writes. It's the input to the blast-radius tool: when this file changes, what else might be affected?

**Allowed `touches` values** (monorepo subsystem slugs):

| Slug | When to use |
|------|-------------|
| `integration` | File interacts with integration-mesh code outside foundry-cip (rare — mostly historical from pre-extraction) |
| `knowledge` | File writes to or reads from the Pinecone knowledge layer |
| `graph` | File interacts with FalkorDB / Cypher queries |
| `pm` | File reads/writes PM tables (project_scopes, project_decisions, etc.) |
| `roster` | File invokes the LLM Roster (none in Phase 1; M5+ will) |
| `metabase` | File creates / grants on `lens_*` views consumed by Metabase |

**When to add `touches`:** add it when a code change to *this* file could plausibly require a reviewer from the touched subsystem. Don't add it for transitive dependencies; only direct contact.

**Example.** A new lens that materializes a Pinecone-augmented query would declare:

```python
# foundry: kind=service domain=client-intelligence-platform touches=knowledge,metabase
```

A pure intra-CIP file (e.g., a connector that only touches `cip_*` tables) needs no `touches` at all.

### 5. Declaration-priority resolution

When multiple declaration mechanisms are present for the same file, **first match wins** in this order:

1. **Inline `# foundry: ...` comment** in the file's first 10 lines (Python source only).
2. **YAML frontmatter** `kind:` / `domain:` keys (Markdown docs).
3. **Sidecar seed file** entry (`docs/_classification-seed.yaml` if present — not currently deployed in foundry-cip).
4. **Path inference** — fallback based on directory location (`cip/migrations/versions/*.py` → `migration`, `tests/**/*.py` → `test`, etc.).

**Why this order:** explicit beats implicit. An inline comment is the most local declaration — anyone reading the file sees the kind immediately. Frontmatter is a close second for markdown (no comment syntax). Seed files exist for config files that have no comment-or-frontmatter mechanism (rare).

If `safe: false` warnings fire from the classifier, the resolution chain found no declaration. For Phase 1 foundry-cip, `safe: false` is acceptable for config files (no sidecar deployed); any Python or Markdown file fires `safe: false` indicates a missing declaration that must be added.

### 6. Python file template

For framework / service / connector code:

```python
# foundry: kind=service domain=client-intelligence-platform
"""Module docstring — what this module does, in 1-3 lines."""
from __future__ import annotations
# ...
```

For a fixture connector / mapper:

```python
# foundry: kind=fixture domain=client-intelligence-platform
"""Reference implementation — passes the conformance harness."""
```

For a file that touches an adjacent subsystem:

```python
# foundry: kind=service domain=client-intelligence-platform touches=knowledge
"""Service that writes embeddings to Pinecone."""
```

For a test file:

```python
# foundry: kind=test domain=client-intelligence-platform
"""Test module — what it covers."""
```

For a script:

```python
# foundry: kind=script domain=client-intelligence-platform
"""One-shot operational script — what it does, who runs it, when."""
```

**The CSS comment goes on line 1.** Line 2 is the module docstring. No blank line between them (consistent with the cip codebase convention).

### 7. Markdown file template

Per JOS-K01 (Frontmatter Schema Contract v1.5), every governed CIP Markdown doc declares the full JOS schema in YAML frontmatter. The `kind:` (CSS) is implied by JOS `type:` — these are siblings, not duplicates:

```markdown
---
id: CIP-SOP-NN
uuid: <generated-uuid4>
title: Doc Title
type: sop                          # JOS doc type — also implies CSS kind
owner: tim
solve_for: One-sentence WHY this doc exists.
stage_label: adopt                 # JOS lifecycle: assess|trial|adopt|hold|rejected|retire
domain: ops                        # JOS domain — meta|eng|doc|dat|fin|str|ops|ppl|leg
version: '1.0'
created: '2026-04-21'
last_modified: '2026-05-16'
last_reviewed: '2026-05-16'
review_cadence: 90                 # days
---

# Doc Title

> Optional callout / status line.

## Purpose
...
```

**Mapping JOS `type:` ↔ CSS `kind:`:**

| JOS `type:` | CSS `kind:` equivalent |
|-------------|------------------------|
| `sop`, `playbook`, `spec`, `diagnostic`, `framework`, `contract`, `best-practice`, `capability` | `doc` |
| `standard`, `rule`, `principle`, `concept`, `decision`, `standing-order` | `doc` (CIP venture-local; mostly inherited from JOS) |

For markdown, `kind: doc` is the only value; **type granularity lives in the JOS `type:` field.** Legacy ad-hoc `kind:` declarations from pre-JOS frontmatter (`kind: contract`, `kind: doc`) are preserved but JOS `type:` is authoritative.

See [`_TEMPLATE.md`](_TEMPLATE.md) (CIP-BP-005) for the canonical authoring template.

### 8. Migration-file classification

Alembic migration files always declare:

```python
# foundry: kind=migration domain=client-intelligence-platform
"""Migration docstring — what tables/columns this changes."""
```

The `kind=migration` declaration is what the discoverability registry uses to enumerate all CIP schema changes in order. The `domain=client-intelligence-platform` is always literal (no per-migration domain split — CIP migrations are CIP-wide).

`touches` on a migration MAY reference downstream subsystems impacted by the schema change:

```python
# foundry: kind=migration domain=client-intelligence-platform touches=metabase
"""cip_09_metabase_role_views — grants lens_* views to cip_metabase_role."""
```

When a migration creates / drops / renames a table or column consumed downstream, declare `touches` to surface the blast radius.

### 9. Discoverability-registry coupling

Per JOS-S01 (Discoverable Registries) and JOS-S07 (All Governed Objects Registered), every CSS-tagged file is reachable via the registry:

- **Code files** (`kind=service`, `kind=fixture`, `kind=test`, `kind=script`, `kind=migration`, `kind=config`): registered transitively via the conformance harness + features.yaml feature registry. No per-file registry entry needed; the registry queries the filesystem + classification.
- **Doc files** (`kind=doc`): registered explicitly in `docs/_registry.yaml` with `id`, `uuid`, `title`, `type`, `stage_label`, `domain`, `owner`, `path`, `last_reviewed`. The migration script `scripts/migrate_frontmatter_to_jos.py` regenerates this registry on each run.
- **Tenant artifacts** (per-tenant `GLOSSARY.md`, `MANIFEST.md`): registered as `type: diagnostic`, `domain: dat`. Auto-generation scripts (`generate_tenant_manifest.py`, `seed_glossary_into_registry.py`) are responsible for emitting JOS-conformant frontmatter.

Agents querying CIP go:

1. Read `docs/_registry.yaml` to find candidate governed objects.
2. Filter by `type:` or `domain:` for relevance.
3. Read the matched file (path is in the registry entry).
4. If the file declares `touches`, follow up with the touched subsystem registries.

This couples CSS classification + JOS registry + JOS-S16 governance-discovery standard into one path that agents and humans both walk.
