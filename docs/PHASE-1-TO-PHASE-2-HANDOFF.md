---
kind: doc
domain: client-intelligence-platform
status: draft
last_updated: 2026-05-11
milestone: Phase-1-M7
---

# Phase 1 → Phase 2 Handoff

> **Status:** draft — promoted from skeleton in M7 (2026-05-11). Atlas finalizes on return; M8 (Product-Ready Gate) is what flips `status: final` after the final read-through.
> This doc is the bridge from "plain-jane CIP green against the fixture tenant" to Phase 2 — Wayward Onboarding (first non-fixture venture, Zendesk + HubSpot ingestion) followed by Foundry self-tenant + write-back (Phase 2.5) and Rocky Ridge cross-tenant grants (Phase 3).

## Purpose

Enumerate the state at the end of Phase 1 — code, data, docs, tests, PM status, calibration insights — and the explicit Phase 2 entry criteria, so a fresh engineer can pick up Phase 2 (Wayward Zendesk + HubSpot ingestion, then outbound to Chatwoot/Twenty/Drive, then REST first-light) without re-reading Phase 1 history.

## Who reads this

- The engineer running Phase 2 M1–M9 (Wayward Onboarding).
- Tim / Atlas at the Phase-1 product-ready gate (M8).
- Future phase leads needing a reference for "what 'product-ready' means" as a repeatable pattern.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Created this skeleton. |
| **M7 — Four-access-paths validation + doc suite harden** | **Promoted skeleton → draft.** Structural content populated; M8 finalizes. |
| M8 — Phase 1 product-ready gate | Will populate the final §4 PM state + §6 entry criteria checkboxes; flips `status: final`. |

Cross-ref: [`docs/vision/PHASE-1-PLAN.md`](vision/PHASE-1-PLAN.md) (Phase 1 binding plan), [`docs/vision/PHASE-1-PLAIN-SPEC.md`](vision/PHASE-1-PLAIN-SPEC.md) (acceptance criteria), [`docs/vision/ROADMAP.md`](vision/ROADMAP.md) (Phase 2 block), CIPWAY scope chain in PM.

---

## 1. Phase 1 final state — code

**Migrations (`cip/migrations/versions/`)** — 9 applied in linear chain off `async_03_agents_cols`:

| Revision | Lights up |
|---|---|
| `cip_01_clients` | Multi-tenant tenant-of-tenants table + RLS policy template |
| `cip_02_views` | Lens catalog (M4's source-of-truth for filter configs) |
| `cip_03_sync_runs` | Per-run audit log (status + counters + error_detail JSONB) |
| `cip_04_files` | Originals registry (Path 4 surface) |
| `cip_05_contacts` | Bitemporal SCD-2 contacts |
| `cip_06_companies` | Bitemporal SCD-2 companies |
| `cip_07_deals` | Bitemporal SCD-2 deals + deal-contact linkage |
| `cip_08_tickets_and_registry` | Tickets + `cip_connector_property_registry` discoverability registry |
| `cip_09_metabase_role_views` | `cip_metabase_role` Postgres role + `lens_all_companies` + `lens_eu_west_companies` views; P-21 grant matrix (REVOKE on `cip_*`, GRANT only on `lens_*`) |

**Framework code (`cip/integration_mesh/`):**

- `CIPConnector` + `CIPMapper` Protocols (M2)
- Sync orchestrator with session-level advisory locks (M2 + M3)
- SCD-2 differ + persister with `EXTRAS_COLUMN_BY_TABLE` translation (M2 + M3 Δ5)
- Sync-run recorder + rate-limit token bucket (M2)
- Lens engine: `compile_filter`, `apply_lens`, `lens_query_for_table`, `load_lens` (M4)
- Tenant context: `apply_tenant_context()` + RLS-bound session pattern (M2)

**Reference connector (`cip/integration_mesh/connectors/fixture/`):**

- `FixtureConnector` + `FixtureMapper` (M3) — STANDARD corpus = 1150 rows (50 companies + 200 contacts + 300 deals + 500 tickets + 100 documents + 0 active notes), `seed=42`, byte-identical via `PYTHONHASHSEED=0` + `faker==40.15.0`.

**Test surface (`tests/`):**

- Conformance harness: `tests/fixtures/connector_conformance/` — 8 tests every connector must pass (including post-commit RLS isolation per PATCH-NR-1 and concurrent-sync advisory-lock per M3).
- Integration mesh: 21 test files covering orchestrator, persister, recorder, lens engine, fixture connector, M5 metabase role + views, M6 discoverability completeness, M7 four-access-paths validation.
- Migrations: 9 RLS smoke tests (one per `cip_*` table; 36 sub-cases).
- Total at HEAD `<set by M8>`: 300+ pass, ~38 skipped (Path 2/3 monorepo-deferred).

**Public API (`cip/integration_mesh/__init__.py`):** `CIPConnector`, `CIPMapper`, `CIPRow`, `CorpusSize`, `FixtureConnector`, `FixtureMapper`, `KnowledgeText`, `Lens`, `PropertyDescriptor`, `RateLimitPolicy`, `apply_lens`, `compile_filter`, `lens_query_for_table`, `load_lens`, `run_sync` (+ exceptions).

## 2. What's green (evidence)

| Surface | Evidence at Phase 1 close |
|---|---|
| Path 1 — Structured SQL (lens engine) | `tests/integration_mesh/test_lens_apply_e2e.py` + `test_four_access_paths_validation.py::test_path_1_structured_via_lens_query` |
| Path 1 — Structured SQL (Postgres views as `cip_metabase_role`) | `test_four_access_paths_validation.py::test_path_1_via_postgres_lens_views_as_metabase_role` |
| Path 2 — Knowledge vector + BM25 | Schema-correctly-absent assertion in foundry-cip standalone (`test_path_2_knowledge_layer_partial_validation`); full validation in monorepo platform-service scope (PM `458fb208-...`) |
| Path 3 — Knowledge graph (FalkorDB) | Skip with explanatory message in foundry-cip CI; full validation in monorepo FalkorDB environment |
| Path 4 — Originals via `cip_files` | `test_four_access_paths_validation.py::test_path_4_originals_via_cip_files` + cross-path composition test |
| Discoverability cold-start | `test_four_access_paths_validation.py::test_discoverability_registries_enumerate_all_phase_1_artifacts` |
| Capability registry vs. reality | `test_four_access_paths_validation.py::test_features_yaml_lists_all_deployed_capabilities` |
| Cross-tenant RLS through `cip_views` | `test_discoverability_completeness.py::test_cross_tenant_isolation_through_cip_views` |
| Lens golden-snapshot determinism | `test_lens_golden_snapshots.py` (SHA-256 locked, Python 3.12 + PYTHONHASHSEED=0) |
| Fixture corpus byte-identical determinism | `test_fixture_corpus_determinism.py` (regression guard for any Faker / random-RNG drift) |

CI matrix at Phase 1 close: 4-Python matrix + CodeQL + wheel-install + cross-pollution-guard + lockfile-freshness (FND-S13). All green at HEAD `<set by M8>`.

## 3. Phase 1 final state — docs

| Doc | Status at Phase 1 close (M7 read-through state) | Atlas-finalize on M8 |
|---|---|---|
| `CONNECTOR-AUTHORING-GUIDE.md` | draft — comprehensive | Final-pass review |
| `CSS-CLASSIFICATION-CONTRACT.md` | draft (skeleton-shaped — §1, §4-§9 still TBD) | **Atlas-author** the deferred sections OR demote to skeleton + tag for Phase 2 |
| `DEPLOYING-FOUNDRY-CIP-FOR-A-NEW-VENTURE.md` | stub (fill_when: Phase 2 M3) | Stays stub through Phase 1; Wayward Phase 2 M3 IS the trial run |
| `EXPORTING-VENTURE-CONNECTORS.md` | stub (fill_when: Phase 8) | Stays stub; Phase 8 concern |
| `EXTRACTION-HISTORY.md` | reference | No change |
| `FIXTURE-TENANT-HANDBOOK.md` | skeleton — §§1-9 TBD | **Atlas-author** during M8 OR defer to Phase 2 docs pass |
| `FOUR-ACCESS-PATHS.md` | draft — §§1-9 populated (M6) | Final-pass review; M8 candidate for `status: final` |
| `LENS-AUTHORING-GUIDE.md` | draft — comprehensive | Final-pass review |
| `METABASE-OPERATOR-GUIDE.md` | draft — comprehensive | Final-pass review |
| `MIGRATION-RUNBOOK.md` | draft — comprehensive (cip_09 added M7) | Final-pass review |
| `PHASE-1-TO-PHASE-2-HANDOFF.md` | **draft — this doc** | Atlas finalizes on M8 |
| `RLS-SET-LOCAL-OPERATOR-GUIDE.md` | draft — comprehensive (cross-tenant probe populated M7) | Final-pass review |
| `STANDALONE-INTEGRATION-GUIDE.md` | stub (fill_when: external consumer / PyPI) | Stays stub |
| `SYNC-ORCHESTRATOR-GUIDE.md` | draft — comprehensive | Final-pass review |
| `TENANT-ONBOARDING-CHECKLIST.md` | skeleton | **Atlas-author** during M8 OR defer to Phase 2 (the Wayward run IS the first real checklist exercise) |
| `TROUBLESHOOTING-AND-INCIDENT-RESPONSE.md` | stub (fill_when: first incident) | Stays stub; updated incrementally |

Cross-ref integrity: M7 read-through fixed the M5/M6 milestone-row misattributions across 6 drafts (CONNECTOR-AUTHORING, MIGRATION-RUNBOOK, RLS-SET-LOCAL, LENS-AUTHORING, METABASE-OPERATOR, SYNC-ORCHESTRATOR). The `_TEMPLATE.md` schema is retained for future Phase 2+ docs.

## 4. Phase 1 final state — PM

| Scope | Status at Phase 1 close |
|---|---|
| M0–M8 milestone scopes under CIP-PHASE1 (`596825db-...`) | M0–M7 closed; M8 closes at gate |
| Hygiene trackers | M2 v5.4, M3 v3.1, M4 v2.2, M5 v3.1 (pending — small mechanical roll), M6 + M7 (Atlas authors on return capturing Δs) |
| `94275cc8-...` — fixture self-test stream | Lit ongoing (CI regression harness) |
| CIPWAY M1 | Ready to enter (Wayward Phase 2 deep plan is the entry gate; needs Atlas authoring) |
| CIPRR (Rocky Ridge Phase 3) | Queued; gated on Phase 2 + cip_files semantics design call |
| Deferred Atlas-required scopes | Scope-gating design (`fa802d2f`), agent-access design (`e1e599b6`), Add-a-Use-Case procedure v1 (`0e9b06e6`), cip_files semantics (`8eebad28`), knowledge migration sub-scope |
| Deferred non-Atlas scopes | Auto-generator commit-watcher (task #143; Phase 2), knowledge taxonomy CHECK migration (`458fb208`), migrations conftest helper convergence (`cd12b6ea`), Metabase operator-side dashboards (`fbc9ab3d`; gated on Tim setting up Metabase) |

The final M8 checkboxes (all scopes closed, ROADMAP.md flipped to Phase 1 LIT, Phase 1 retrospective filed) are M8's job; this section captures the state Atlas finalizes.

## 5. Known-unknowns carried into Phase 2

Items intentionally deferred from Phase 1; Phase 2 must address or explicitly re-defer:

- **Real-credential auth flows.** M2 documents the `AuthenticationError` contract; Phase 2 Wayward is first-contact with OAuth refresh, expired-token mid-sync, and source-side rate-limit 429 backoff.
- **Pagination quirks in Zendesk / HubSpot.** Fixture connector's pagination is synthetic. Real source-system page-token semantics, cursor expiry, and gap-handling under high-velocity tenants are unproven.
- **History-clock semantics for HubSpot.** HubSpot's 20-revision retention clock is the Phase-1-kickoff R5 risk. Phase 2 either consumes pre-retention OR designs the "HubSpot backup tape" parallel project.
- **Operator extensibility in lens engine.** v2 dict-shape operators (`{"region": {"$eq": "eu-west"}}`) are forward-compat-guarded in M4's compiler but not implemented. Phase 2 Wayward decides whether to ship `$eq`/`$in`/`$gt` early or wait.
- **Cross-table lens joins.** M4 is single-table only. Real Phase 2 questions ("which deals have contacts at EMEA companies?") need either join compiler, denormalized materialized views, or graph-layer query plan — design call.
- **Lens auto-generator commit-watcher.** Task #143, Phase 2. M5 ships hardcoded `lens_*` views; new lenses need a new migration + manual CREATE VIEW until the watcher lands.
- **Knowledge taxonomy alignment.** Today `knowledge_sources.source_type` allows `{document_library, web_collection, expert_corpus, repo_documentation}`. CIP-tagged source types (`cip_doc`, `cip_ticket`, `cip_note`, `cip_fixture_*` per VISION §7g) require monorepo CHECK migration `458fb208-...`. Until aligned, CIP content in the knowledge subsystem uses fallback taxonomy.
- **`cip_files` semantics design call.** R2 path strategy, retention, citation grade, drift between cip_files row + R2 object presence. Surfaced from Rocky Ridge knowledge audit; Atlas synthesizes options before Phase 3.

## 6. Phase 2 entry criteria

To start Phase 2 M1 (Wayward Zendesk connector + first non-fixture tenant), the following must be in place:

- [ ] Phase 1 M8 gate closed (all milestone scopes done, ROADMAP.md flipped, retrospective filed).
- [ ] Fixture regression suite (full pytest tree) green at Phase 2 kickoff HEAD.
- [ ] Wayward tenant UUID provisioned + tenant row inserted in `cip_clients`.
- [ ] Zendesk OAuth credentials available + stored per the secrets convention (`ZENDESK_OAUTH_TOKEN` env var; cf. CONNECTOR-AUTHORING-GUIDE.md §3).
- [ ] HubSpot OAuth credentials available + `HUBSPOT_API_KEY` env var set.
- [ ] HubSpot backup-tape decision made (consume pre-retention OR run parallel tape project).
- [ ] Chatwoot / Twenty / Drive target endpoints identified for outbound (Phase 2 M5+).
- [ ] Wayward Phase 2 deep plan authored by Atlas + QC-cycled (mirrors M2/M3/M4/M5 deep-plan pattern; uses the calibration insights from §7).

## 7. Phase 1 calibration insights worth preserving

Atlas's working-notes during Phase 1 surfaced patterns that should inform Phase 2 authoring discipline:

- **Drafts-against-memory pattern.** ≥6 documented occurrences across M3-M6 where deep-plan or dispatch text drifted from deployed reality (features.yaml count, QBO→Plaid grep tension, M5 Δ3 revision_id length, M6 v1 fictional fixtures, M6 v2 BLOCKERs even after explicit rewrite, M6 dispatch's plural-object_type assertion). **Calibration:** Atlas authoring discipline going into Phase 2 — when authoring tests or schema-touching plans, MUST read deployed code first before writing any signature (Option Y citation-grounded pattern from M6/M7). Candidate for CHARTER addendum.
- **Option Y dispatch pattern.** For verification-only milestones (M6, M7), skip deep-plan ceremony; direct CC dispatch with file:line citations works better. For real design milestones (M2-M5), deep-plan ceremony remains the right shape because those have architectural substance to QC.
- **Test placement reconciliation.** integration_mesh testcontainer pattern beats migrations DATABASE_URL skip pattern for tests that need a real Postgres + per-test tenant. Established in M3 Δ4 + M5 Δ1.
- **Library-shape FND-S13.** pyproject ranges + uv-compiled `requirements-dev.txt` with `--universal` flag for cross-platform lockfile reproducibility. CI lockfile-freshness body-only diff (tail -n +3 skipping autogen header).
- **Stop-and-escalate discipline.** Report findings BEFORE editing; let Atlas confirm or amend. Saved multiple cycles of wasted code-time in M3-M6.

## 8. Phase 2 M1 first-action brief

The 1-paragraph brief for the Phase-2-M1 engineer (assumes Atlas-authored Wayward deep plan exists):

> Read `WORKBENCH/tim/cip-wayward-deep-plan.md` (Atlas-authored Phase 2 plan), then `docs/CONNECTOR-AUTHORING-GUIDE.md` end-to-end. Build the Zendesk connector under `cip/integration_mesh/connectors/zendesk/` mirroring `cip/integration_mesh/connectors/fixture/` layout: `connector.py` (ZendeskConnector), `mapper.py` (ZendeskMapper), `__init__.py` exports. Pass the 8-test conformance harness against `ZendeskConnector + ZendeskMapper`. Land in Wayward tenant context against `cip_clients` row pre-provisioned for Wayward. First commit explicitly NOT touching any framework code — Protocol generality is the M2 contract; if you find you need a framework extension, STOP and escalate (per M2 R1 mitigation).

## 9. Delta against `CONNECTOR-AUTHORING-GUIDE.md`

Phase 2 Wayward will surface real-world drifts; each goes into a per-connector hygiene tracker AND back into CONNECTOR-AUTHORING-GUIDE.md as a deployed-reality correction:

- Real OAuth refresh patterns (M2 forward-pointer in §3 stays open).
- Source-side rate-limit response shape (Zendesk 429 headers vs. HubSpot retry-after vs. fixture's no-op).
- Real pagination edge cases (e.g., HubSpot's `paging.next.after` token semantics under high-velocity tenants).
- Concrete `is_custom = True` handling against real tenant-defined fields (M2 contract validated against MockConnector; Phase 2 is first real exercise).

## 10. Non-goals of this handoff

- This doc does NOT design Phase 2. Phase 2 design lives in the Atlas-authored Wayward deep plan (CIPWAY M0).
- This doc does NOT lock the Phase 1 → Phase 2 boundary as immutable. Anything Phase 2 surfaces that's load-bearing for Phase 1's spec gets fed back in as a Phase 1 hygiene fix.
- This doc does NOT prescribe Phase 2 milestone ordering — Wayward's `M1 → M9` shape is the deep-plan author's call.

---

*Authored: M7 — Four Access Paths Validation + Doc Suite Harden (2026-05-11). Atlas finalizes on M8 close.*
