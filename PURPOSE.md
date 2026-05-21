---
doc_type: purpose
elaborates_slot: identity
declared_thing: foundry-cip
declared_thing_kind: product-internal
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 365
audience: [leadership, dev, strategy, agent]
diataxis_type: explanation
connects_to:
  - OVERVIEW.md
  - README.md
  - VISION.md
  - docs/vision/VISION.md
---

# Purpose — Foundry Client Intelligence Platform (CIP)

> Per JOS-S24. Stable existential WHY — why CIP exists NOW. Distinct from VISION (forward, evolves).

## The one sentence

**CIP exists so Foundry-Studio onboards a client's data ONCE and serves it EVERYWHERE — dashboards, reports, chatbots, agents, partner portals — instead of starting from zero on every engagement.**

## The longer answer

The Wayward engagement proved the operational pattern in a Claude Code session: pull Zendesk + HubSpot, unify into SQLite, generate CEO briefing with operational audit + 7 proposals. Day-1 outcome.

That session worked. It was also a one-off — every byte of work was bespoke. The script, the schema, the analysis, the report shape. If a second client engaged, day-1 starts at zero again.

CIP is the framework that refuses to start at zero. Three canonical data layers (Originals + Derived Knowledge + Structured), a connector framework that's connector-agnostic by construction (FixtureConnector proves the abstraction), a lens engine that lets one source of truth serve N stakeholder views via INSERT-only filter configs, a tenant model where data isolation is structural at the SQL layer.

The product Foundry sells is the engagement; the platform Foundry uses to deliver it is CIP. The first client takes a Phase-1 effort. The second should take an hour. The tenth should take minutes. That's the leverage curve CIP exists to create.

## What CIP replaces (the world without it)

Without CIP, every Foundry-Studio engagement is a separate Claude Code session with a separate SQLite, a separate ad-hoc schema, a separate analysis ritual. Reports go out manually. Chatbots don't exist. Agents can't operate on client data because there's no canonical store to operate on. Each new client adds linear effort; the platform doesn't compound.

With CIP, every engagement lands in the same shape. Wayward is tenant 1. Rocky Ridge is tenant 2. Foundry self-tenant is tenant 3. The CIP framework absorbs them without per-tenant code branching. The connector framework absorbs new data sources (HubSpot, Zendesk, Plaid, future Chatwoot) without per-engagement reinvention.

## What CIP is NOT a purpose for

- **Not a general-purpose CDP.** Foundry-Studio is the only customer. Selling CIP standalone is explicitly out (per VISION non-goals).
- **Not a service.** Library shape (`pip install foundry-cip`) is deliberate per D-146. Consumers (FAS, future products) host the runtime.
- **Not a multi-cloud abstraction.** Pinecone + R2 + Railway Postgres are pinned dependencies. Cloud portability is not the goal.
- **Not a sellable platform for consultancies.** The leverage exists for *Foundry-Studio*; replicating it elsewhere is not on the path.
- **Not the chatbot product.** Foundry Chatbot was spun out to `products/foundry-chatbot/` — shares retrieval stack with CIP Phase 5 but separate consumer + branding + scoping.

## Why this purpose is durable

It's been stable since CIP Phase 0 locked (2026-04-17 — 8 architecture decisions). It doesn't depend on:
- Which connectors are shipped (FixtureConnector, HubSpot, Zendesk landed; Plaid + Chatwoot planned)
- Which lens views exist (operators add lenses by INSERT-only)
- Which consumption surface is active (Metabase shipped; REST/MCP/chatbot Phase 4-5)
- Which model the LLM Roster routes to (rotates per FAS Roster)

It depends on:
- Foundry-Studio choosing to run multiple ventures (locked)
- The pattern of "onboard once, serve everywhere" being correct (validated by Wayward Phase 1)
- The library-shape vs service-shape choice (D-146 locked)

If any of those three change, the purpose changes. None are changing in the foreseeable horizon.

## Connected docs

- [`OVERVIEW.md`](OVERVIEW.md) — what's inside CIP today
- [`README.md`](README.md) — Phase status + pillar map
- [`VISION.md`](VISION.md) → [`docs/vision/VISION.md`](docs/vision/VISION.md) — where CIP is going (2027-05 horizon)
- [`ROADMAP.md`](ROADMAP.md) → [`docs/vision/ROADMAP.md`](docs/vision/ROADMAP.md) — the 9-phase shape
- [`docs/notes/03-vision-conversation-log.md`](docs/notes/03-vision-conversation-log.md) — the original Tim vision-session decisions
