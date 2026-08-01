---
id: CIP-K03-WAYWARD
title: Wayward Readout (concrete instance of CIP-K03)
type: implementation-note
owner: tim
solve_for: Record the decisions and the built back-end for the FIRST concrete Readout (the Wayward channel), authored against the agnostic Readouts Contract (CIP-K03), and flag where this instance currently diverges from that contract so nothing is built on bad information.
stage_label: trial
domain: dat
version: '0.2'
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
> internals are deliberately NOT built here (a separate FAS-agents session). The three reconciliations with
> CIP-K03 are RESOLVED (contract bumped to v1.2); the writer is unblocked for the FAS-agents session.

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

## Resolved reconciliations with CIP-K03 (v1.2, Tim 2026-08-01)

All three are RULED; CIP-K03 is bumped to **v1.2** to absorb them (see the READOUTS-CONTRACT.md changelog).

1. **Retention.** RESOLVED by refining the contract. CIP-K03 v1.2 adds a bounded **retention profile** (a
   hot window plus rolling summaries, with a declared external archive). Wayward's profile: 35 days of full
   editions + rolling ~2 monthly summaries in CIP; the deep archive is the FAS agent run-logs. This is now a
   first-class contract option, not a deviation ("the old stuff ends up housed by the agent anyway").
2. **Ledger schema.** RESOLVED: the WRITER writes the full CIP-K03 ledger (fact_pack, a renderings map with
   a master per locale, edition_seq, audience, provenance, freshness); cip_149's two lenses
   (current/history) become a thin **projection** over that ledger. No app rework, because the read shape the
   app consumes is stable. cip_149 stands as the read stub until the writer lands, then is reconciled to the
   full ledger.
3. **Per-locale masters.** RESOLVED: locale is an **audience-like axis**. Each natively-authored locale (en,
   zh) has its own master; its short distills from that locale's master. CIP-K03 v1.2 §5.4 and §7 now state
   this. zh stays authored, never translated (R8).

## Implications for other systems

- **FAS**: gains the readouts writer as a WORK-system capability using the LLM Roster (a generate slot +
  an independent audit slot, config-resolved, smoke-tested). This is the "readouts as a FAS-general
  capability" Tim flagged.
- **CIP-K03**: bumped to v1.2 (2026-08-01) absorbing the retention profile (recon 1) and per-locale masters
  (recon 3); the ledger relationship (recon 2) is the writer-writes-full-ledger + lenses-as-projection pattern.
- **App (reports-project-silk)**: the masthead readback slot + the last-updated indicator wire in when
  the overview screens land; renders empty until an edition is filed.
- **Project Silk chatbot (PS-CHAT)**: the on-demand regeneration + conversational CIP query surface.

## Cross-references

- CIP-K03 (`docs/READOUTS-CONTRACT.md`) - the agnostic contract this instance implements.
- cip_149 migration (`cip/migrations/versions/cip_149_readout_editions.py`) - the read-side back-end.
- Reporting re-grounding + readouts brief: reports-project-silk `WORKBENCH/ALIGNPROJECT-2026-08-01.md`.
- PM: RDL project workstream 1.5c (readouts); task d5f9d992 (writer agent); project PS-CHAT (chatbot).
