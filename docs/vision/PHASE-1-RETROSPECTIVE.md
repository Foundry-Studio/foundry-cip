---
id: CIP-DIAG-001
uuid: b19b9478-caf8-4fe6-b3b0-a113d7efa243
title: CIP Phase 1 Retrospective
type: diagnostic
owner: tim
solve_for: Phase 1 retrospective — what went right, what went wrong, calibration insights
  carried into Phase 2.
stage_label: adopt
domain: meta
version: '1.0'
created: '2026-05-12'
last_modified: '2026-05-16'
last_reviewed: '2026-05-16'
review_cadence: 365
milestone: Phase-1-M8
authors:
- cc-vacation-mode
purpose: 'Phase 1 close-out retrospective. Per PHASE-1-PLAN.md §M8: ''what did the
  framework teach us? Did the Lens Engine abstraction survive first contact? What
  should Phase 2 Wayward Onboarding sharpen when it meets real connectors?'''
---

# CIP Phase 1 Retrospective

**Closing HEAD:** foundry-cip @ `ad04e72` (post-M8 fixture+Metabase verified + Wayward scaffolds landed)
**Closing date:** 2026-05-12
**Author:** Claude Code (vacation-mode; Atlas reviews retroactively on return)
**Time elapsed:** M0 (2026-04-20) → M8 close (2026-05-12) = ~3 weeks build

## What we shipped

| # | Milestone | Status | Closing HEAD |
|---|---|---|---|
| M0 | Vision Lock + Doc Skeletons | ✅ | (pre-extraction) |
| M1 | Foundation cip_01–08 + RLS | ✅ | (pre-extraction) |
| M2 | Connector Framework + 8-test conformance | ✅ | 99d8ca0 |
| M3 | FixtureConnector + 1150-row deterministic corpus | ✅ | 8518bba |
| M4 | Lens Engine + golden-file snapshot harness | ✅ | 887a88e |
| M5 | Metabase platform service (cip_09) | ✅ | 13e5234 |
| M6 | Discoverability registry completeness pass | ✅ | cece39d |
| M7 | Four Access Paths Validation + Doc Suite Harden | ✅ | 3797b7b |
| **M8** | **Product-Ready Gate** | ✅ | **ad04e72** (with cip_10 history-lens at e85f1e9 + Tim Metabase click-through 2026-05-12) |

## What the framework taught us

### 1. The Protocol abstraction held up

`CIPConnector` + `CIPMapper` were authored in M2 before any non-mock connector existed. FixtureConnector (M3) was the first non-trivial implementation. The Protocol survived without modification — even small surprises like deterministic-corpus needs, advisory-lock dual-run prevention, knowledge-text validation, and bitemporal SCD-2 history all fit within the existing Protocol shape.

**Phase 2 carry-forward:** the Wayward Zendesk + HubSpot connectors should be straight Protocol implementations. Any urge to add a new Protocol method should trigger a STOP and an explicit "why is this generic enough to belong on the Protocol vs. a connector-specific helper" review (per PHASE-1-PLAN R1 mitigation).

### 2. The Lens Engine v1 (equality-only) is sufficient for proof-of-concept, but Phase 2 will pressure it

M4 shipped equality-only `filter_config` and explicit fail-fast guards against v2 operator syntax (`{"$eq": ...}`). M5 + M6 + M7 didn't surface a use case that broke that constraint at fixture scale. **But** the Wayward use cases described by Tim (BI-style historical comparisons, deal-pipeline funnels, time-bucketed ticket trends) will need `$gt` / `$lt` / range / IN operators almost immediately. Phase 2 Wayward deep plan should decide whether to cherry-pick a v2 operator subset early or stick with the M4 fail-fast and force per-table workarounds for the duration.

### 3. The structural surface is solid; the consumption surface is thin

CIP's data layer (cip_01–10, RLS, SCD-2 bitemporal, lens engine, registries) is comprehensive. The consumption surface is intentionally narrow at Phase 1 close:

- **Path 1 Structured:** lens engine + 3 Postgres lens views (`lens_all_companies`, `lens_eu_west_companies`, `lens_companies_history`).
- **Path 2 Knowledge vector+BM25:** monorepo platform-service scope (PM `458fb208`); foundry-cip standalone validates the Protocol shape only.
- **Path 3 Knowledge graph:** monorepo platform-service scope; FalkorDB not in foundry-cip CI.
- **Path 4 Originals:** `cip_files` r2_path pattern verified; signed-URL retrieval against R2 is post-Phase-2.

**Phase 2 carry-forward:** the consumption surface widens at Wayward — more lens views per entity table, history lenses for all 6 entities (not just `cip_companies`), eventually the auto-generator commit-watcher (task #143) that flips manual `CREATE VIEW` migrations to automatic.

### 4. Discoverability registries work; the agent-side surface is unproven

M6 verified that `cip_connector_property_registry`, `cip_views`, `cip_sync_runs`, `cip_files`, `features.yaml`, and `pg_views LIKE 'lens_%'` all return rows under the fixture tenant. M7's cold-start agent test (`test_discoverability_registries_enumerate_all_phase_1_artifacts`) proved a fresh agent can light up each surface programmatically.

**What's NOT proven:** an actual agent in an actual conversation, given only the `foundry_mcp_*` tool surface, successfully orienting and querying CIP data for the first time. The four-access-paths report at `validation/M7-discoverability-report.md` is intentionally not authored — that's an Atlas / agent-system retrospective deliverable on return.

### 5. The bitemporal SCD-2 framework is the unsung load-bearing pillar

Phase 1 didn't exercise much actual history — fixture data is static; initial inserts don't write history rows. M8 surfaced this clearly when the first history-lens test had to inject a synthetic history row to verify the view (the M3 conformance harness covers the differ; M8 covers the lens surface).

**Phase 2 will pound on history.** Wayward's HubSpot data has years of property changes; Wayward's Zendesk has thousands of ticket-state transitions. The differ + history-table pattern was designed for exactly this volume but hasn't been load-tested.

## What surprised us (most important section)

### Atlas's drafts-against-memory pattern

Recurring across M3 → M7: Atlas (or anyone authoring against memory rather than against deployed code) drifts on small details — column names, fixture row counts, milestone-attribution, plural-vs-singular enums. 6+ documented occurrences during the Phase 1 build. The pattern was finally addressed in M6 / M7 via the "Option Y dispatch" — citation-grounded direct-CC dispatch with explicit file:line references for every deployed signature.

**Phase 2 carry-forward:** for verification-style milestones, Option Y dispatches work well. For real design milestones (Wayward Phase 2 deep plan), the deep-plan ceremony with QC rounds is still right BUT the deep-plan author must explicitly mark which statements are FROM-DEPLOYED-CODE vs. FROM-INTENT. Audit before authoring.

### The DB-URL foot-gun (cip01 incident, 2026-05-11)

Mid-Phase-1, CC accidentally migrated Railway prod with a knowledge-taxonomy CHECK constraint expansion because `DATABASE_DEV_URL` was empty in the bash shell and `src/db/session.py` fell through to `DATABASE_PUBLIC_URL` = Railway prod. Recovery was clean; postmortem at `WORKBENCH/tim/cip01-knowledge-taxonomy-incident-2026-05-11.md`. The systemic fix — fail-closed `get_database_url()` + alembic env.py target-host banner — landed at monorepo `7da78ebf` and foundry-cip `3828e27`.

**Phase 2 carry-forward:** before any DDL against any DB, print the resolved host BEFORE the migration runs. The banner pattern (`*** PRODUCTION TARGET *** target=<host>`) is now load-bearing.

### M5 vs Metabase separation

Mid-Phase-1 Tim split Metabase out of CIP M5 into its own first-class product (`Foundry-Studio/foundry-metabase`, PM scope `7b70764c`). M5 in CIP became "provide the cip_metabase_role + lens views surface" — much narrower than "build the Metabase deployment." This separation cleaned up the architecture: CIP owns data + lens shapes; Metabase owns presentation + per-tenant Collections.

**Phase 2 carry-forward:** any future per-venture BI customization is a CIP-side lens-view addition AND a Metabase-side dashboard authoring task — two repos, coordinated at the venture-onboarding moment. The two products meet at Wayward (CIP Phase 2 ↔ Metabase Phase 1).

## What Phase 2 Wayward should sharpen

Per PHASE-1-PLAN.md §M8 retrospective prompt:

1. **The HubSpot "backup tape" decision — RESOLVED 2026-05-12 by D-159.** Originally flagged as PHASE-1-PLAN R5 kickoff risk; M8 surfaced as architectural choice; **Tim's call 2026-05-12**: historical backfill is mandatory across all CIP connectors, per tenant, by default. Locked in `docs/DECISION-LOG.md` D-159 and codified in `docs/CONNECTOR-AUTHORING-GUIDE.md` §13 "Historical Backfill Contract". Phase 2 Wayward's HubSpot + Zendesk connectors implement the contract from the start — no separate "backup tape mini-project" needed.

2. **Real OAuth refresh.** M2 documented the `AuthenticationError` contract but never exercised real token refresh. HubSpot tokens expire; Zendesk OAuth tokens rotate. Phase 2 connectors need a refresh hook + retry-on-expiry pattern. Atlas/Tim decide where it lives (per-connector vs. shared base).

3. **Real pagination quirks.** FixtureConnector pagination is synthetic. HubSpot's `after` cursor + Zendesk's `next_page` URL + their respective "what if the underlying data changes between pages" semantics need real coverage. Test against rate-limited 429 retries (the orchestrator handles this; needs to be exercised end-to-end).

4. **Operator extensibility in lens engine.** v2 `{"$eq": ...}` / `$in` / `$gt` operators are forward-compat-guarded but not implemented. First Wayward question that needs a date range will pressure this.

5. **Auto-generator commit-watcher (task #143).** M5 hardcoded `cip_09` views; M8 hardcoded `cip_10`. Wayward will want lens views per entity table per use-case. Manual migrations don't scale; the watcher needs Phase 2 attention.

6. **`cip_files` semantics + R2 path strategy.** Phase 2 first real R2 uploads (Wayward attachments, Zendesk ticket attachments). PM scope `8eebad28` parked for design.

7. **Multi-tenant Metabase pattern.** Phase 1 pinned single-tenant via Init SQL. Phase 2 needs to decide per-tenant Collections vs. per-tenant DB connections vs. parameter-driven tenant switcher. Foundry-metabase project's design call.

## Phase 1 metrics

- **Migrations applied:** cip_01 through cip_10 (10 alembic revisions in the foundry-cip chain) — both local testcontainer and Railway prod.
- **Tests:** 306 passing + 38 skipped + 2 warnings.
- **CI matrix:** 4-Python (3.11/3.12/3.13/3.14) + CodeQL + wheel-install + cross-pollution-guard + lockfile-freshness — all green at every milestone close.
- **Docs:** 15 docs in `docs/`; 8 in draft (comprehensive), 4 in stub (deliberately deferred per `fill_when:` frontmatter), 2 in skeleton (Atlas-author or defer), 1 reference (EXTRACTION-HISTORY.md).
- **Public API surface:** `from cip.integration_mesh import …` exports 17 names (Protocol + dataclasses + entry functions + exceptions).
- **Lines of code (rough):** ~5500 LOC framework + ~2000 LOC tests + ~3000 LOC docs.
- **Atlas drafts-against-memory occurrences:** 6+ documented across M3–M7 (drafts-against-memory CHARTER addendum candidate on Atlas return).
- **Production incidents:** 1 (cip01, 2026-05-11, additive constraint expansion, ~3 min Railway deploy crash, recovered cleanly via Tim's `4e67d9f8`).

## Phase 1 LOCKED

All M0–M8 milestone scopes complete. Phase 1 framework code, structural data layer, lens engine, Metabase platform service, discoverability registries, four access paths, doc suite, and the Tim-amendment historical-lens proof are landed and verified.

**The plain-jane is shippable.** Tim opens Metabase at `reports.project-silk.com`, connects to Railway via `cip_metabase_role`, sees fixture data through `lens_*` views, switches between lenses, and the P-21 multi-lens-by-default proof holds.

The framework is ready for Phase 2 Wayward Onboarding.

## Atlas on return

When Atlas returns from vacation, the following sit waiting:

1. Ingest the 3 CC reports + 1 incident postmortem (m6-cc-report-cece39d.md, m7-cc-report-3797b7b.md, cip01-knowledge-taxonomy-incident-2026-05-11.md, m8-railway-deploy-plan-2026-05-11.md).
2. Read this retrospective.
3. Close M6 / M7 / M8 / 458fb208 PM scopes; record gate_pass decisions; append write-log receipts.
4. Author M6 / M7 / M8 hygiene trackers from the Δ notes in the CC reports.
5. Consider CHARTER addenda for: drafts-against-memory pattern, DB-fallback foot-gun, alembic target-host discipline.
6. Pivot to Wayward Phase 2 deep plan authoring (CIPWAY scope chain).
7. Decide the parked-scope queue: scope-gating design (`fa802d2f`), agent-access design (`e1e599b6`), Add-a-Use-Case procedure v1 (`0e9b06e6`), cip_files semantics (`8eebad28`), knowledge migration sub-scope.

Welcome back.

---

## 2026-05-16 addendum — post-M8 Wayward push + JOS adoption

The retrospective above closed Phase 1 at HEAD `ad04e72` (2026-05-12). In the 4 days that followed, Phase 2 Wayward Onboarding ran end-to-end and the M8 Product-Ready Gate was formally completed. This addendum captures what happened so the retrospective stays current.

### Wayward Phase 2 ingestion shipped (2026-05-12 → 2026-05-16)

| Connector | Outcome |
|-----------|---------|
| HubSpot (Wayward portal 242173321) | 119,729 companies + 68,084 contacts + 3,057 deals ingested via the batched persister (100-200× speedup vs per-record). |
| Zendesk (waywardsupport subdomain) | 2,890 tickets ingested. Comments + attachments deferred to Block 2 of M8 follow-on. |
| Total rows | 1,257,771 across `cip_*` tables and SCD-2 history siblings. |

### Tenant model correction

A discrepancy surfaced 2026-05-16 between the data layer (using placeholder `b0000000-0000-0000-0000-000000000001` tenant) and VISION §4 (which mandates tenants = operators/ventures = EcomLever, clients = subjects-of-intelligence = Wayward). Corrected end-to-end:

- New canonical UUIDs locked: `dec814db-722a-4730-8e60-51afc4a5dad9` (EcomLever tenant) + `661ecab4-dddb-5924-a34d-af1c5133132d` (Wayward client, UUIDv5 deterministic).
- 1,257,771 rows re-tagged across 14 tables via `scripts/migrate_b0_to_ecomlever.py` (per-table SAVEPOINT isolation to prevent transaction poisoning — a naive `with engine.begin()` would have rolled back ALL prior updates on the first table failure).
- 8 Wayward orchestration scripts migrated to import canonical UUIDs from `cip/integration_mesh/wayward_constants.py`.
- `docs/ONBOARDING-A-NEW-TENANT.md` (CIP-SOP-009) Phase 0 added: forbids placeholder UUIDs, explains tenant-vs-client model, adds 2 lessons-table entries.
- PM decision `c575c81c-047d-42b1-a453-c858423b171d` filed.

**Carry-forward:** every new tenant follows the canonical-UUID rule from Day 0. Block 1c's [`CIP-SOP-010 TENANT-ONBOARDING-CHECKLIST`](../TENANT-ONBOARDING-CHECKLIST.md) Phase 0 is the operationalization.

### Property Glossary pattern (PM scope 0246851d, DONE)

The Tim/Eric attribution research surfaced the pain — 4 round-trips guessing `paid_referral` / `rev_share_partner` / `deal_owner` before finding `source`. The vendor `label` and `description` didn't carry the meaning. Solution shipped:

- `docs/PROPERTY-GLOSSARY-PATTERN.md` (CIP-SOP-016) — the meta-doc defining confidence levels (verified / inferred / tentative / unknown) and behavioral rules.
- `docs/tenants/dec814db-.../GLOSSARY.md` — first real instance, populated for Wayward with 14 verified entries.
- Schema migration `cip_13_extend_property_registry` — 11 new semantic-layer columns on `cip_connector_property_registry` with a CHECK constraint on the confidence enum.
- `scripts/seed_glossary_into_registry.py` — materializes markdown → DB rows.

**Carry-forward:** every new tenant gets a glossary; auto-baseline `tentative` confidence + operator interview promotes to `verified` for the top ~30 columns per entity. Long tail stays tentative indefinitely.

### Tenant Manifest framework (PM scope bfc3d5d0, DONE)

Self-describing data directory per tenant — the "what's in CIP for this tenant?" surface that agents and humans both query:

- Migration `cip_14_lens_tenant_manifest` — two views: `lens_tenant_manifest_properties` + `lens_tenant_manifest_sync_health` (with freshness buckets: fresh / stale_gt_24h / stale_gt_7d / never_succeeded).
- `scripts/generate_tenant_manifest.py` — reads the views + tenant identity + clients + lenses, writes `docs/tenants/<uuid>/MANIFEST.md`.
- First MANIFEST shipped at 162 lines for EcomLever, proving the markdown → DB → view → generated-doc pipeline end-to-end.

**Carry-forward:** v1.5 will wire the generator as a post-sync hook so the manifest auto-refreshes after every connector run.

### M8 ceremony + JOS adoption (Block 1 of M8, 2026-05-16)

The original M8 plan (PHASE-1-TO-PHASE-2-HANDOFF.md vintage 2026-05-11) was a doc-suite hardening pass. Tim 2026-05-16 expanded it: **full JOS-S03 governance compliance + full QC.** Sub-blocks shipped:

| Block | Outcome |
|-------|---------|
| 1a | CIP onboarded as JOS venture per JOS-SOP-009. Master charter at `jordan-operating-system/distribution/charters/foundry-cip.yaml` (full tier, venture=foundry, 9 domains, 10 SOs, 8 rules, 7 contracts). Venture-side scaffolding: `.jos/`, `context-bundle/`, `scripts/jos` shim, `docs/_registry.yaml`. |
| 1b | 54 CIP docs migrated to JOS-conformant frontmatter (id/uuid/title/type/owner/solve_for/stage_label/domain/version/created/last_modified/last_reviewed/review_cadence). 36 active + 19 retired (stage_label: retire) registered objects. CLAUDE.md gets jos:begin/end managed block per JOS-R18. `scripts/migrate_frontmatter_to_jos.py` is idempotent; preserves uuids on re-run. |
| 1c | 3 skeleton docs authored: TENANT-ONBOARDING-CHECKLIST (220 lines, from real Wayward experience), FIXTURE-TENANT-HANDBOOK (190 lines, from FixtureConnector code), CSS-CLASSIFICATION-CONTRACT (filled §1, §4–§9). |
| 1d-1j | Final-pass review + handoff finalize + ROADMAP flip + PM scope closure + full pytest + JOS-S14 verification (this addendum + parallel work). |

**`scripts/jos check` PASSes** at the close of Block 1c. JOS-S14 verification is implicit in jos check; M8 Block 1j makes it explicit.

### Phase 1 LOCKED — for real this time

Phase 1 closed 2026-05-12 by the test surface. M8 closes 2026-05-16 by the governance surface. Both gates green.

The framework is ready for Phase 2 Wayward Onboarding **continuation** — the first sync already shipped; remaining work is Engagements (HubSpot calls/notes/transcripts via Firefly-through-HubSpot, PM scope 9952dd26) and Zendesk Comments (PM scope 28739b6e), then Wayward-specific lens views, then Raw Knowledge Ingestion (paused pending design call per PM decision e68add85).

