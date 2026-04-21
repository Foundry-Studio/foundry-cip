---
kind: doc
domain: client-intelligence-platform
status: skeleton
last_updated: 2026-04-20
milestone: Phase-1-M0
---

# CIP CSS Classification Contract

> **Status:** skeleton stub — authored Phase 1 M0, populated as Phase 1 milestones land.
> Once final, this contract defines how every CIP file carries a CSS (Kind/Domain/Touches) classification so that D-122 domain-ownership-by-CSS-tag (not folder) holds across the product.

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

TBD (M1) — `migration`, `connector`, `mapper`, `orchestrator`, `lens`, `service`, `route`, `doc`, `test`, `fixture`, `script`.

### 3. Allowed `domain` values in CIP

TBD (M1) — start with `client-intelligence-platform`; finer-grained subdomains (e.g. `cip-structured`, `cip-unstructured`, `cip-lenses`) to be locked if and when a D-number authorizes them.

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
