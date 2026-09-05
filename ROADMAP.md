---
doc_type: roadmap
elaborates_slot: lifecycle
declared_thing: foundry-cip
declared_thing_kind: product-internal
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-09-05
last_reviewed: 2026-09-04
review_cadence: 90
audience: [strategist, stakeholder, leadership, agent]
diataxis_type: explanation
---

# Roadmap: Foundry Client Intelligence Platform (CIP)

> **JOS-canonical entry point for CIP's roadmap.**
> Per JOS-D0054 + JOS-S29, this file elaborates the Lifecycle slot (Roadmap component) for the foundry-cip product root.
>
> **Companion documents are STALE as of this review.** `docs/vision/ROADMAP.md` (last touched 2026-05-23) still carries the retired phase sequence and should be read as history, not as plan, until it is rewritten. Do not treat it as authoritative. `CHANGELOG.md`, `features.yaml` and `capabilities.yaml` also carry known-false entries; see "Known-stale companions" below.

## TL;DR

**The eight-phase model is retired as the organizing frame for CIP.** It stopped describing reality on 2026-05-23 and was not renumbered because renumbering would not help: the sequencing broke, and the unit of work changed.

Since mid-2026, CIP has been the **substrate** for one program it never named: the Wayward China Commission recovery and the Project Silk reporting platform it feeds. Roughly 250 of the 261 commits and 147 of the 156 migrations landed since 2026-05-21 belong to that program, not to any declared phase.

Head is `cip_176_rls_tenant_gaps` (175 migration files; `cip_96` was never authored, numbering gap only). Product vision and the 2027-05 horizon are unchanged and live in [`VISION.md`](VISION.md); this file no longer claims phase-dated horizons, because every one of them was falsified.

## Why the phase model was retired

Two independent proofs, either sufficient:

1. **Sequencing inverted.** Phase 4 (Agent Access Surfaces) partially shipped May to July 2026 while Phases 2.5 and 3 remain unstarted. The roadmap's own declared dependency, that cross-tenant grants must work before tools expose cross-tenant data, was reversed in practice.
2. **The unit of work changed.** Phases 2.6, 2.7 and 2.8 were invented mid-flight, shipped 2026-05-22/23 (`cip_21` through `cip_28`), and never reached this file at all. Since mid-July, work has been organised by the program in `WORKBENCH/china-audit/PROGRAM.md` (P0 to P7), not by CIP phases or pillars. 60 `ps_*` tables and 92 `lens_ps_*` views now exist; the phase model anticipated none of them.

Retiring the frame is not a retreat from the vision. The [north star](VISION.md) is intact. What changed is that CIP grew a large tenant-specific financial and classification domain in service of one venture, and the generic platform build-out paused while that happened.

## Where the declared phases actually stand

| Phase | Declared status (2026-05-21) | ACTUAL status (2026-09-04) |
|---|---|---|
| 0: Data Model | complete | Complete, unchanged. |
| 1: Plain-Jane + Doc Suite | complete | Complete, unchanged. |
| 2: Wayward Onboarding | **active** | **Inbound half SHIPPED 2026-06-09.** Outbound half (Chatwoot push, Google Drive push) has zero code and was never started. |
| 2.6 / 2.7 / 2.8 | not listed | **SHIPPED 2026-05-22/23** (`cip_21`-`cip_28`). Established the lens-mirror pattern that superseded Phase 3's grant model. |
| 2.5: Self-Tenant + Write-Back | next | **NOT STARTED as specified.** No `cip_pending_writes` / `cip_write_authorities` / `cip_write_decisions`, no `cip_write()`. A narrower governed write path shipped instead (see W5). |
| 3: Multi-Tenant + Grants Runtime | future | **Grants runtime NOT STARTED and effectively superseded.** `cross_tenant_grants` appears nowhere in `cip/`. Multi-tenancy was proven by the mirror pattern, not the grant pattern. Rocky Ridge exists as a tenant but holds knowledge chunks only, with zero rows in every structured table. |
| 4: Agent Access Surfaces | future (2027-Q1) | **PARTIALLY SHIPPED, ~2 quarters early.** `/cip/query`, `/cip/search`, `/cip/registries` live in FAS `cip_router.py`; three MCP tools live. `/cip/files` signed-R2 resolver not shipped. |
| 5: Chatbot | future | **NOT STARTED, restated by D-238.** No vision doc, no architecture doc, zero code. Scope is now a thin conversational client over the knowledge fabric: thin means no standalone service and no per-tenant deployment, not fewer constraints. Grounding, refusal, citation-density and lens/grant-awareness requirements stand unchanged. |
| 6: Intelligence & Alerts | future | **PARTIALLY SHIPPED and reframed** as Readouts (CIP-K03, `CIP-CAP-007`). Back-end shipped (`cip_149`); the writer is deliberately deferred (Tim, 2026-08-01), so reader lenses return nothing until an edition is filed. Anomaly detection and alert channel not started. |
| 7: Investigative Agents | future | **NOT STARTED.** |
| 8: Scale & Extract | future | **NOT STARTED for extraction.** `cip_*` still shares the Foundry PostgreSQL. No retention policies. Performance tuning did land early (`cip_35`, `cip_136`, `cip_139`). |

## What actually got built, by workstream

These are the real units of work since 2026-05-21. They are recorded here because they are what CIP is, and no phase describes them.

| # | Workstream | Window | Anchor evidence |
|---|---|---|---|
| W1 | Cross-tenant lens mirror + Project Silk provisioning | May 22-23 | `cip_21`-`cip_28`, `LensMirrorConnector`, `crm_companion_writeback.py` |
| W2 | China nationality book: evidence and authority model | Jul 6-19 | `cip_38`-`cip_40`, `cip_66`-`cip_99`; 3-state verdict at `cip_95`; tiers at `cip_156`/`cip_157` |
| W3 | Money engine (commission recovery) | Jul 13-18 | `cip_41`-`cip_113`; ledger `cip_104`, eligibility `cip_105`, reconciliation `cip_108`, Stripe live-sync `cip_111` |
| W4 | Data-capture expansion | Jul 19-20 | `cip_114`-`cip_122` (brand revenue, Stripe charges/disputes/payouts, card-country, WeChat) |
| W5 | Reporting platform + governed write roles | Jul 20 - Aug 1 | `cip_120`, `cip_123`-`cip_151`; `ps_reporting_reader`/`ps_reporting_writer`; app in `reports-project-silk` |
| W6 | Trust and period-close layer | Jul 28 | `cip_137`, `cip_138` (`ps_periods`, `ps_period_gates`, snapshots, restatements, `ps_feed_registry`) |
| W7 | Readouts capability (CIP-K03) | Jul 28 - Aug 1 | `docs/READOUTS-CONTRACT.md`, `cip_149` (writer stubbed) |
| W8 | Correctness and hardening campaigns | Aug 3 - Sep 2 | `cip_152`-`cip_175`; integrity lens `cip_155`; mirror starvation `cip_166` |

**Shipped but undeclared elsewhere:** Stripe, LensMirror and the Slack `#amazon-brand-connections` feed are live connectors absent from `features.yaml`. A governed write path with an audit log (`ps_reporting_write_log`) exists. 22 executable data invariants run against production (`ps_invariants.py`).

## What is genuinely active now

**None of the eight phases.** The live workstream is program project **P4, Reporting Frontend** (`b3efe08b`), plan of record `WORKBENCH/china-audit/REPORTING-REBUILD-PLAN.md`.

The last four weeks were Wayward remittance reconciliation (`cip_169`-`cip_172`), partner-attribution accuracy for the reports app (`cip_173`-`cip_175`), and repo/CI hygiene. On 2026-09-04 `cip_176` closed three tenant-isolation gaps and the test suite went green for the first time since 2026-05-10. The current mode is hardening, not building.

## Linked to PM

- **CIP project:** `596825db-61bc-4899-bc6c-e207489ca35d`. Note it reads 100% complete: it tracks only historical Phase 1/2 work and carries no forward roadmap. Treat that number as an artefact, not a statement about CIP.
- **Program (where the real work lives):** initiative `be0bede6-7f33-4681-af1f-c5d1afcc83f4`, mapped in `WORKBENCH/china-audit/PROGRAM.md`.
- **Repo health workstream:** `33ee4b1c-5f81-4476-8312-4f71bfcd95d7` under the CIP project.

This doc does NOT carry weekly status.

## Health snapshot

Previous reviews recorded "on-track / no at-risk / no stalled" indicators. All three were false and are corrected here.

- **Stalled:** Phases 2.5 and 3 have been stalled since May 2026. Phase 4 shipped out of dependency order.
- **Quality, recovering:** the `test` workflow was red on every push from 2026-05-11 to 2026-09-04, so roughly four months of merges landed unverified. All three causes are now fixed: the missing DB role (`569130c`), eight tests stranded by deliberate lens retirements, and lockfile drift. The suite is green (600 local / 636 with a live Postgres). NOTE the gate is not durable: `lockfile-freshness` resolves against a live unpinned index with no `--exclude-newer`, so it re-reds whenever any transitive dependency publishes. Pinning that boundary is tracked in the repo-health workstream.
- **At risk, operations:** a tripped consecutive-failure breaker latches a feed off permanently and silently. On 2026-09-02 four Project Silk feeds died from a dependency-pin regression; the code recovered within hours but the feeds stayed dead until manually re-enabled on 2026-09-04.
- **Incidents worth remembering:** PS china dimension data silently frozen 2026-08-04 to 2026-08-12 when the mirror matched zero rows (`cip_166`); ten lenses carried a dead connector literal (`cip_153`); three apply-blocking migration bugs found only on production (`cip_130`, `cip_131`). A pattern runs through these and through the four-month CI blackout: the defect is usually detectable and the detection is usually absent, silenced, or unread.
- **Maturity grades were re-measured 2026-09-04** against an industry benchmark, and every one now carries `maturity_evidence`. All eight pillars are bronze; `structured-store` moved down from gold and `access-and-operations` from silver. CIP overall is bronze because those two are gating. The caps are unchanged by the September work: the app path still connects as `postgres` with `rolbypassrls`, no `ps_*` table has a two-tenant isolation test, and no restore drill has ever been performed.

## Known-stale companions

Fix these before trusting them:

- `docs/vision/ROADMAP.md`: last touched 2026-05-23, still the retired phase sequence.
- `CHANGELOG.md`: says "Nothing yet" for post-0.2.0 while 137 migrations have landed.
- `features.yaml`: `rest-api-endpoints` and `mcp-tool-surface` marked `planned` but shipped; connector inventory omits Stripe, LensMirror and Slack brand-connections.
- `capabilities.yaml`: `CIP-CAP-005` says REST + MCP are "coming Phase 4" (already here); `CIP-CAP-007` marked `planned` though the Readouts back-end shipped.
- `README.md`: "Current State" still says Phase 1 is "UP NEXT".
- `docs/CIP-CHEATSHEET.md`: declares `review_cadence: 1` (daily) and is 103 days stale. Nothing regenerates it. Either automate `scripts/generate_cip_cheatsheet.py` or change the declared cadence to the truth.

## Last reviewed

2026-09-04. Rewritten against measured repository state (git history, migration docstrings, live schedule and sync tables) rather than against the previous roadmap's own claims.

---

_This root-level file is a JOS-shaped index. Its former pointer to `docs/vision/ROADMAP.md` as authoritative is suspended until that file is rewritten._
