---
kind: doc
domain: client-intelligence-platform
status: stub
purpose: "Procedure for moving a venture-specific connector out of foundry-cip into the venture's own repo at graduation."
owner: tim
created: 2026-04-27
fill_when: "Phase 8 (Scale & Extract) — when the first venture graduates to its own deployment."
phase_relevance: "Phase 8+"
---

# Exporting Venture Connectors

> **Status: stub.** This document fills out at Phase 8 when the first venture graduates to its own deployment.

## Scope

Some connectors start their lives inside foundry-cip's `cip/connectors/` (because we built them while the venture didn't have its own repo). When the venture graduates — gets its own engineering team, its own deployment, its own Postgres — those venture-specific connectors should move to the venture repo.

## Outline (TBD)

1. **Pre-export check** — is the connector truly venture-specific? (If it's reusable across ventures, it stays in foundry-cip.)
2. **`git filter-repo` extraction** — move the connector's files + history to the venture repo using the same multi-path pattern this extraction plan uses.
3. **Foundry-cip cleanup** — delete the extracted files from foundry-cip; leave a note pointing to the venture repo.
4. **Venture-side scaffolding** — venture repo needs to declare `foundry-cip` as a dependency.
5. **Test** — venture repo's CI can run the connector against the same fixture data.
