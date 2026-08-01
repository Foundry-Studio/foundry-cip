---
id: CIP-K03-WAYWARD
title: Wayward Readout (concrete instance of CIP-K03)
type: implementation-note
owner: tim
solve_for: Record the decisions and the built back-end for the FIRST concrete Readout (the Wayward channel), authored against the agnostic Readouts Contract (CIP-K03), and flag where this instance currently diverges from that contract so nothing is built on bad information.
stage_label: trial
domain: dat
version: '0.1'
created: '2026-08-01'
last_modified: '2026-08-01'
last_reviewed: '2026-08-01'
review_cadence: 90
references:
  - id: CIP-K03
    relationship: implements
  - id: CIP-CAP-007
    relationship: part-of
---

# Wayward Readout (concrete instance of CIP-K03)

> **Status: draft.** This records the 2026-08-01 design decisions with Tim and the read-side back-end
> that is BUILT (cip_149). The WRITER (the FAS agent that generates and files editions) and the engine
> internals are deliberately NOT built here (a separate FAS-agents session). Three reconciliations with
> the agnostic contract (CIP-K03) are OPEN and marked below; resolve them before the writer is built.

## What this is

The Wayward channel Readout is the first concrete Readout authored against CIP-K03 (the agnostic
Readouts Contract). It powers the plain-language "readback" atop the reporting app's overview screens
(Home, Operations, Partners). Same golden rule as the contract: **narrate, never compute.** The model
only phrases facts a program computed; it never calculates or invents a number.

## Decisions (Tim, 2026-08-01) and why

| Decision | Why |
|----------|-----|
| **4 sections per surface/time-slot**: short + long, each in EN and ZH. | Short = the masthead readback; long = the expanded narrative. The site language toggle picks EN vs ZH. |
| **ZH is AUTHORED in Chinese, never translated** (ruling R8). | A real bilingual voice, not machine-translated English. Implies a master PER locale (see reconciliation 3). |
| **Pipeline = generate then audit then file**: draft into a sandbox, an independent audit model checks it against a checklist (every number traces to the fact pack, no computed claim, tone, role-safety, language), on pass it is filed; a deterministic number-check runs first. | This IS the narrate-never-compute guardrail. Because editions are pre-generated on a schedule, we are latency-insensitive and can spend on a strong model + an adversarial audit. |
| **Auto-publish** internal readbacks after the audit passes; **partner-facing statements are a future human gate.** | Internal is safe to auto-file; anything a partner sees gets a human in the loop. |
| **Surfaces v1 = Home, Operations, Partners** (all three at once). Brand-book deck stays DETERMINISTIC (non-LLM). | The overview narratives are the LLM's job; a templated book summary is not. |
| **Cadence = twice daily (05:00/17:00 America/Chicago) + on month-close + on-demand.** On-demand is NOT a button; it is the future Project Silk chatbot. Full/biweekly cadence is a larger reporting conversation, punted. | Matches the contract's default cadence; the chatbot is a separate project (PS-CHAT). |
| **Retention = 35 days of full editions + rolling ~2 monthly summaries in CIP;** older raw editions age out. | 35 days (not 14) so a month-review always has the full month; monthlies give month-over-month; the FAS agent run-logs are the deep archive. SEE reconciliation 1 (this diverges from the contract). |
| **App read slot**: the masthead renders the current edition if present, else nothing; a "last updated N ago" indicator turns RED past ~14h. | The design's optional-readback rule; the red line is a staleness alarm aligned to the ~12h cadence + grace. |

## What is built (read side, cip_149, applied to prod 2026-08-01)

- `ps_readout_editions`: one row per (surface, role, grain, generated_at) carrying the 4 sections
  (short_en/long_en/short_zh/long_zh), plus model/run_id/status. WRITER-STUBBED (no rows yet).
- `lens_ps_readout_current`: the latest filed daily edition per (surface, role) for the masthead + its
  `generated_at`.
- `lens_ps_readout_history`: the 35-day full window + rolling monthly summaries for an agent look-back.
- Granted to the reporting read set. With no writer, the lenses return nothing and the app renders no
  readback; the slot lights up the moment an edition is filed.

## What is NOT built (gated, owned elsewhere)

The **writer** (gather -> fact pack -> author -> audit -> file) and the engine internals (which LLMs,
the authoring + distill prompts, the audit rubric, cost/latency budget, the exact fact-pack whitelist)
are built with real FAS agents in a separate conversation. Tracked as RDL 1.5c task
`Readouts WRITER agent (FAS)` (d5f9d992). The on-demand/conversational path is the Project Silk chatbot
project (PS-CHAT, e0b353d8).

## OPEN reconciliations with CIP-K03 (pending Tim's ruling)

These are where the Wayward decisions currently diverge from the agnostic contract. Do not build the
writer until they are resolved; the contract may need a v1.2.

1. **Retention vs the append-only forever ledger.** CIP-K03 section 6 says the ledger is append-only and
   kept forever ("scroll back through every past edition"). Our decision prunes CIP to 35 days + monthly
   summaries and relies on the FAS agent run-logs as the deep archive. Options: (a) Wayward deviates
   (bounded CIP + agent-log archive); (b) keep the full ledger forever per the contract; (c) refine
   CIP-K03 to allow a bounded-retention profile with a declared external archive. Lean: (c), because the
   agent-logging rationale is sound and generalizes.
2. **cip_149 vs the full ledger schema.** cip_149 is a SIMPLIFIED read-side stub (4 content columns +
   two lenses) built to unblock the front end. CIP-K03 section 6 specifies a richer ledger: fact_pack
   JSONB, a `renderings` JSONB map (one master + distilled sizes), edition_seq, audience, source_refs,
   model_id/config_version, freshness_ok. cip_149 is therefore NOT yet a contract-conformant ledger.
   When the writer lands, reconcile: evolve cip_149 to the full schema, or have the writer write the
   full ledger and make cip_149's lenses a projection over it.
3. **Per-locale masters vs one master.** CIP-K03's rendering model is "author one long master, distill
   the rest." Because ZH is authored natively (not translated), Wayward needs a master PER locale
   (en-master + zh-master), each with its own distilled short. Reconcile: treat locale as an
   audience-like axis (one edition/master per locale) or extend the contract's rendering model.

## Implications for other systems

- **FAS**: gains the readouts writer as a WORK-system capability using the LLM Roster (a generate slot +
  an independent audit slot, config-resolved, smoke-tested). This is the "readouts as a FAS-general
  capability" Tim flagged.
- **CIP-K03**: likely a v1.2 to absorb the retention profile (recon 1) and per-locale masters (recon 3),
  and to note the Wayward ledger's relationship to the contract schema (recon 2).
- **App (reports-project-silk)**: the masthead readback slot + the last-updated indicator wire in when
  the overview screens land; renders empty until an edition is filed.
- **Project Silk chatbot (PS-CHAT)**: the on-demand regeneration + conversational CIP query surface.

## Cross-references

- CIP-K03 (`docs/READOUTS-CONTRACT.md`) - the agnostic contract this instance implements.
- cip_149 migration (`cip/migrations/versions/cip_149_readout_editions.py`) - the read-side back-end.
- Reporting re-grounding + readouts brief: reports-project-silk `WORKBENCH/ALIGNPROJECT-2026-08-01.md`.
- PM: RDL project workstream 1.5c (readouts); task d5f9d992 (writer agent); project PS-CHAT (chatbot).
