---
doc_type: guarantees
elaborates_slot: capability
declared_thing: foundry-cip
declared_thing_kind: product-internal
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
audience: [dev, product, agent]
diataxis_type: reference
connects_to:
  - HEALTH-STANDARD.md
  - capabilities.yaml
  - features.yaml
  - docs/architecture/ARCHITECTURE.md
---

# Guarantees — Foundry Client Intelligence Platform (CIP)

> Per JOS-S20. Promises CIP makes to consumers (Foundry-Agent-System, future products). Each `G-NN` is verified by a corresponding `H-NN` in [HEALTH-STANDARD.md](HEALTH-STANDARD.md).

## Guarantees (production-grade)

### G-01 — CIPConnector + CIPMapper Protocol contract

Every connector implements the locked Protocol shape: `stream_records()` (incremental sync), `map()` (translate to cip_* schema), optional `backfill_history()` (D-159). The 8-test conformance harness gates new connectors before their migration lands.

**Verified by:** [H-01](HEALTH-STANDARD.md), `tests/fixtures/connector_conformance/` 8-test suite.

### G-02 — Tenant isolation is structural

Every `cip_*` table carries `tenant_id`. RLS policies keyed on `app.current_tenant` GUC + explicit `tenant_id` predicates in lens views + `SET LOCAL` middleware. No class of "leaked across tenants" bug is possible at the data layer.

**Verified by:** [H-02](HEALTH-STANDARD.md), 9 RLS smoke tests + M8 cross-tenant probe.

### G-03 — Bitemporal SCD-2 history on every entity

Per D-135. Every record carries valid-time (record's truth window) + transaction-time (when CIP knew about it). Point-in-time queries always work; history is never lost.

**Verified by:** [H-03](HEALTH-STANDARD.md), `scd_differ` regression test + M3 conformance harness.

### G-04 — Mandatory historical backfill on first sync (D-159)

Every connector pulls source-system history (HubSpot 20-rev window, Zendesk audit log, etc.) on first sync for any new tenant. Delay = permanent loss. Synthesized `cip_*_history` rows preserve the past.

**Verified by:** [H-04](HEALTH-STANDARD.md), connector backfill_history test per implementation.

### G-05 — 9-column provenance on every row

Every `cip_*` row carries: `tenant_id`, `client_id`, `source_connector`, `source_id`, `ingested_at`, `refreshed_at`, `previous_version_id`, `ingestion_batch_id`, `authority`. Lineage from any record back to source is always present.

**Verified by:** [H-05](HEALTH-STANDARD.md), schema audit at every migration land.

### G-06 — P-21 Multi-Lens by Default (INSERT-only lens authoring)

Adding a new lens is INSERT-only into `cip_views` — no schema or code change required. The falsifiability test: if adding a lens requires touching code, P-21 has been violated.

**Verified by:** [H-06](HEALTH-STANDARD.md), `lens-authoring` regression in `tests/integration_mesh/`.

### G-07 — Metabase grant matrix structurally enforces P-21

`cip_metabase_role` has REVOKE on every `cip_*` table + GRANT only on `lens_*` views. A BI tool connected as the role *cannot* read raw tables — only filtered lens views. P-21 enforcement is structural, not policy-based.

**Verified by:** [H-07](HEALTH-STANDARD.md), `tests/integration_mesh/test_cip_09_metabase_role_views.py` (13 tests).

### G-08 — Golden-file snapshot harness locks corpus determinism

FixtureConnector produces a 1150-row deterministic corpus reproducible byte-for-byte under Python 3.12 + Faker pin + PYTHONHASHSEED=0. SHA-256-locked snapshots fail loud on drift.

**Verified by:** [H-08](HEALTH-STANDARD.md), `test_fixture_corpus_determinism.py` + `test_lens_golden_snapshots.py`.

### G-09 — Library shape — no Railway runtime surface

CIP is `pip install foundry-cip`. Migrations apply via `alembic upgrade head` against the consumer's Postgres. CIP does not run as a service. Per FND-S14, library-shape verification tier applies (no Tier D).

**Verified by:** [H-09](HEALTH-STANDARD.md), `pyproject.toml` ships library shape; CI matrix passes across Python 3.11/3.12/3.13/3.14.

### G-10 — Local-Verified discipline on every push

Every commit on master carries either `Local-Verified: <tier>` or `Local-Verify-Bypass: <reason>` trailer per FND-S14. CI `trailer-check` job fails workflow if neither present.

**Verified by:** [H-10](HEALTH-STANDARD.md), `.github/workflows/test.yml` trailer-check job.

## Guarantees (in-progress)

### G-11 — Wayward Onboarding round-trip (Phase 2)

Once Wayward goes live as primary tenant: HubSpot + Zendesk pull through; ≥2 lenses live; push to Chatwoot/PS-CRM/Drive; first-light REST API at `/cip/*`.

**Status:** Phase 2 active 2026-Q3. **Verified by future:** H-11 (end-to-end smoke on Wayward).

### G-12 — Authority model for write-back (Phase 2.5)

Three-tier authority (`agent_discovered` → `ingested` → `validated`) with TSP thresholds. Required before any cip_write() call.

**Status:** Phase 2.5 active 2026-Q3 → Q4. **Verified by future:** H-12.

### G-13 — Cross-tenant grants runtime (Phase 3)

`cip_09_cross_tenant_grants` schema + runtime ship together — held until Phase 3 explicitly so they ship as a unit.

**Status:** Phase 3 planned 2026-Q4. **Verified by future:** H-13.

## Anti-guarantees (NOT promised)

| Surface | Why NOT a guarantee |
|---|---|
| **Consumption surfaces (REST / MCP / chatbot)** | Live in FAS, not CIP. CIP exposes the Postgres views + Python API; FAS wraps them. Phase 4-5 work. |
| **Per-tenant business logic** | CIP is connector-agnostic. Wayward-specific lenses live in Wayward's tenant rows; CIP only enforces the framework. |
| **External customer-facing surfaces** | Foundry-Studio-internal product. End-user surfaces are at the venture layer (Wayward portal, partner portals). |
| **Backward compatibility pre-1.0.0** | SemVer pre-release rules apply. Minor versions may include breaking changes per pyproject.toml policy. Pin to a specific git SHA in production until 1.0.0. |

## Cross-references

- [HEALTH-STANDARD.md](HEALTH-STANDARD.md) — H-NN ↔ G-NN
- [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) — 1124-line Phase 0 lock
- [DECISION-LOG.md](DECISION-LOG.md) — D-117 through D-159 + P-21 (text in FAS DECISION-LOG.md)
- [.jos/charter.yaml](.jos/charter.yaml) — JOS binding (tier=full, schema=1.9)

## When a guarantee breaks

1. **It's an incident.** Open a PM task in CIP project (`596825db-61bc-4899-bc6c-e207489ca35d`).
2. Check the corresponding `H-NN` in HEALTH-STANDARD.md — does the test actually run, what's the assertion?
3. If a guarantee no longer holds and we don't want to fix: explicitly retire it here with a date + reason.
