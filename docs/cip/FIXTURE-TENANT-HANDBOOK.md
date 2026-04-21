---
kind: doc
domain: client-intelligence-platform
status: skeleton
last_updated: 2026-04-20
milestone: Phase-1-M0
---

# Fixture Tenant Handbook

> **Status:** skeleton stub — authored Phase 1 M0, populated as Phase 1 milestones land.
> Once final, this handbook is the canonical reference for the synthetic fixture tenant that Phase 1 validates CIP against — schema, seed, byte-identical determinism, and how to regenerate.

## Purpose

Document the fixture tenant end-to-end: what synthetic data FixtureConnector produces, how `scripts/seed_fixture_tenant.py` deterministically seeds it, how to verify byte-identical repeatability, and how tests consume it.

## Who reads this

- Engineers running `seed_fixture_tenant.py` locally or in CI.
- Test authors consuming fixture data in Lens / access-path tests.
- Reviewers validating a PR that changes the fixture data shape (breaking change by default).

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Creates this skeleton. |
| M2 — FixtureConnector | Populates §2 data shape and §3 generator. |
| M3 — Sync orchestrator | Populates §5 first-seed runbook. |
| M7 — Four-access-paths validation | Populates §6 byte-identical repeatability proof. |

Cross-ref: [`PHASE-1-PLAIN-SPEC.md §5`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md) — Fixture data-shape binding.

## Outline

### 1. Why a fixture tenant

TBD (M2) — plain-jane CIP validates against synthetic data, no venture data; D-122 CSS-domain isolation.

### 2. Data shape

TBD (M2) — ~50 companies, ~200 contacts, ~300 deals, ~500 tickets, ~100 documents, ~50 notes; region/language/industry distributions.

### 3. Seed mechanics

TBD (M2) — single random seed at top of `seed_fixture_tenant.py`, deterministic `random.Random(seed)` threading, template pool for text fields.

### 4. Tenant registration

TBD (M3) — fixture tenant UUID, `tenants` row fields, RLS attachment.

### 5. First-seed runbook

TBD (M3) — `python scripts/seed_fixture_tenant.py --tenant <uuid>`; expected row counts per `cip_*` table; idempotency (re-run yields same rows).

### 6. Byte-identical repeatability

TBD (M7) — hash the seeded tables, assert identical across machines and reruns; how to diagnose drift.

### 7. Breaking-change policy

TBD (M2) — any change to fixture data shape rev-bumps fixture version; callers must adapt or pin.

### 8. How tests consume fixture data

TBD (M2) — fixtures in `tests/fixtures/lens/golden_files/`, test conventions for asserting against fixture output.

### 9. Phase 2 retention

TBD (M2) — fixture tenant keeps running in CI after Phase 1 as the regression harness; Wayward tenant is additive, not replacement.
