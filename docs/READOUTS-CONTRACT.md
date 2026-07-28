---
id: CIP-K03
uuid: c7d78a2b-28be-4bf3-8ff3-aabcc11507c8
title: Readouts Contract
type: contract
owner: tim
solve_for: The minimum architecture every Readout must satisfy, so any venture, dataset, or agent can stand up a new Readout without reinventing the engine, and so every Readout stays grounded, auditable, and safe.
stage_label: trial
domain: dat
version: '1.0'
created: '2026-07-28'
last_modified: '2026-07-28'
last_reviewed: '2026-07-28'
review_cadence: 180
references:
  - id: JOS-S66
    relationship: implements
  - id: CIP-CAP-007
    relationship: part-of
  - id: D-146
    relationship: constrained-by
---

# Readouts Contract

> **Status:** trial (v1.0, authored 2026-07-28). This is the agnostic contract for the Readouts capability. It is deliberately venture-neutral, dataset-neutral, and surface-neutral. The first concrete Readout (the Wayward channel Readout) is authored against this contract, not the other way around. Governed by [`JOS-S66 Readouts Standard`]; realized as CIP Pillar 7 capability CIP-CAP-007 (Intelligence & Alerts); runtime hosted by Foundry-Agent-System (FAS).

## 1. What a Readout is

A **Readout** is a periodically regenerated, machine-written narrative of a subject's current state, grounded entirely in numbers a program computed, filed forever in an append-only ledger, and rendered anywhere a human or agent needs it.

Hold the whole thing as a newsroom:

- **Reporters** compute the facts (this is code and math, never a model).
- **A writer** turns those facts into readable prose (this is the LLM, and it only phrases; it never counts).
- **An editor** checks the copy against the facts and kills anything unsupported or confidential (a validation step).
- **The archive** keeps every past edition, so tomorrow's writer can say "still late since Tuesday" (the ledger).
- **Distribution** prints the same edition to a dashboard, a Slack message, an email, or a larger Readout.

**The golden rule (non-negotiable): narrate, never compute.** The model may only restate, rank, and phrase facts it was handed. It may not calculate a number, infer a total, or assert a figure that is not present in the fact pack. This is what makes a Readout safe to point at money.

A Readout is **not** the agent "briefing" (`briefing_items`, the Chief-of-Staff inbox of asks and FYIs). A briefing is a queue of items a human must action. A Readout is a narrative of computed state. They may relate later (a Readout can be consumed by a briefing), but they are different objects with different stores.

## 2. Where a Readout runs

CIP is a library, not a service (D-146: consumers host the runtime). The work therefore splits across three homes, and every Readout MUST honor the split:

| Layer | Owns | Home |
|-------|------|------|
| **Definition + computation + storage** | The metric/significance logic, the fact pack, the append-only ledger, the capability declaration | **CIP** (library, Pillar 7) |
| **Runtime** | The schedule, the model call (via the LLM Roster), the guardrail pass, delivery to Slack/email | **FAS** (hosts the CIP engine; Slack and the Roster are FAS-side by CIP's own pillar charter) |
| **Rendering** | Showing the latest edition + the ledger of past editions | Any surface (a dashboard, Slack, email, or a larger Readout) |

A Readout MUST NOT put model invocation, scheduling, or external delivery inside the CIP library. Those are runtime concerns hosted by FAS or another consumer.

## 3. The two layers

Every Readout declares which layers it produces. A Readout MUST produce Layer 1. It MAY additionally produce Layer 2.

### Layer 1: Grounded Readout ("what happened")

The facts, phrased. "Connect GMV is 8.2 percent ahead of last period across 63 producing brands. Two source feeds are late."

- The writer restates and ranks facts from the fact pack. No interpretation, no recommendation.
- **Fact fidelity is strict:** every fact in the prose, whether a figure, a count, a named entity, or an event, MUST appear in the fact pack, or the edition is rejected and regenerated.
- Highest trust. May be rendered to any audience the Readout's confidentiality rule permits, including external partners or customers.

### Layer 2: Open Readout ("what it might mean, what to do")

Interpretation, hypotheses, connections, recommendations. "Boost brands are churning faster than Connect; onboarding is worth a look."

- The writer MAY reason beyond the literal facts, but a second set of guardrails applies:
  - It MUST label interpretation as interpretation (a hypothesis, not a fact), and carry a confidence signal.
  - It MUST still obey numeric fidelity: any figure it cites MUST come from the fact pack. It may draw conclusions; it may not invent numbers.
  - It is **internal-only by default.** A Readout MUST explicitly opt Layer 2 into any audience wider than internal operators.

Rule of thumb: Layer 1 tells you what is true; Layer 2 tells you what the system thinks. Wire Layer 1 to an external surface; keep Layer 2 in the family until it earns trust.

## 4. The pipeline (six stages)

Every Readout run MUST execute these stages in order. Stages 1, 2, 4, and 5 are deterministic code. Only stage 3 is a model.

1. **Gather.** Pull inputs through source adapters (see section 5.1). Sources MAY be CIP lenses, and MAY be anything else (a Slack channel, an external dataset, an API). Not all data comes from CIP.
2. **Compute the fact pack.** Deterministically compute every figure, delta, and significance score in code. Rank the candidates. Output a locked fact pack of ground truths. This stage decides what is worth saying; it is math, not a model.
3. **Narrate.** Hand the ranked fact pack plus the last N editions (for continuity) to the LLM Roster. Produce Layer 1, and Layer 2 if declared. The model sees the fact pack and the prior editions, never the raw source rows.
4. **Validate (the editor).** Reject and regenerate on any failure: fact fidelity (every asserted fact, whether a figure, a count, a named entity, or an event, traces to the fact pack; numbers are never model-computed), confidentiality (no content outside the edition's audience), freshness gate (do not publish over stale inputs without saying so).
5. **File.** Insert one immutable edition row into the append-only ledger, with full provenance.
6. **Deliver.** Render or push the edition to its declared surfaces. Delivery is a consumer concern; the ledger is the source of truth regardless of whether delivery succeeds.

## 5. Minimum architecture (the contract)

A Readout is conformant if and only if it satisfies all of the following.

### 5.1 Source adapters (source-agnostic)

Inputs MUST arrive through a `ReadoutSource` adapter with a uniform shape: given a subject and a time window, return raw facts. At least these adapter kinds are in scope: a CIP lens adapter (reads `lens_*` under tenant RLS), and a generic external adapter (a Slack channel, an HTTP dataset, a file). Adding a new source kind MUST be a new adapter, never a change to the engine. A Readout MAY combine multiple sources in one fact pack.

### 5.2 Deterministic fact pack

Every fact the Readout will ever state, whether a figure, a count, a named entity, or a change/event, MUST be produced here, in code, and placed in the fact pack. The fact pack is the model's entire universe of facts. If a fact is not in the fact pack, no layer may state it. Numbers are the strictest case: the model never computes one. The fact pack MUST also carry significance ranking, so the writer leads with what matters.

### 5.3 Append-only ledger

Every edition MUST be inserted, never updated in place. The ledger is the audit and research trail: it MUST let an operator or agent read any past edition and reconstruct what was known when. See section 6 for the schema.

### 5.4 Two-layer separation

Layer 1 and Layer 2 MUST be stored as distinct fields. A surface MUST be able to render Layer 1 without exposing Layer 2.

### 5.5 Guardrails

Fact fidelity, confidentiality (role or audience shaping), and a freshness gate are all mandatory and enforced in stage 4, before filing. A Readout MUST fail closed: if a guardrail cannot be evaluated, the edition is not published.

### 5.6 Provenance

Every edition MUST record: the config version that produced it, the model the Roster resolved, a reference to the exact inputs/fact-pack it narrated, the freshness verdict, and the generation timestamp (UTC). Provenance makes an edition reproducible and auditable.

### 5.7 Consumable, agnostically

An edition MUST be readable by any authorized human or agent, and MUST be composable: it MAY be pushed to a dashboard, dropped in Slack, emailed, or aggregated into a higher-level Readout. The Readout does not know or care who consumes it; it files a well-formed edition and exposes it.

**Cross-venture composition** is achieved by granting a specific reader or agent (for example a Chief-of-Staff agent) read access to the relevant tenants' editions, never by generating data across tenants and never by relaxing tenant isolation. Readouts stay tenant-isolated; a portfolio or cross-venture view is a permissioned reader, not a new data layer or a change to CIP's tenant model.

## 6. The ledger schema

A Readout's ledger is a CIP structured-store table (append-only), inheriting CIP's tenant isolation (RLS) and 9-column provenance model. The Readout-specific columns are:

| Column | Purpose |
|--------|---------|
| `readout_id` | Which Readout config produced this edition |
| `subject_key` | The subject this edition is about (tenant, venture, or scoped subject) |
| `edition_seq` | Monotonic edition number per (readout_id, subject_key) |
| `period_start`, `period_end` | The window the edition covers |
| `generated_at` | UTC timestamp of generation (the edition's identity, not a weekday name) |
| `fact_pack` | JSONB: the locked ground truths and their significance ranks |
| `layer1_md` | Grounded narrative (Markdown) |
| `layer1_highlights` | JSONB: structured headline + ranked highlights for non-prose surfaces |
| `layer2_md` | Open narrative, nullable (only when Layer 2 is declared) |
| `layer2_confidence` | Confidence signal for Layer 2, nullable |
| `audience` | The confidentiality/role scope this edition may be rendered to |
| `source_refs` | JSONB: which sources and snapshots were read |
| `model_id`, `config_version` | Provenance for reproducibility |
| `freshness_ok` | Whether inputs were fresh at generation; drives the "trust after these clear" line |

**Live versus history.** The "live" Readout is simply the latest edition row for a (readout_id, subject_key). The rest of the rows are the ledger. There is no separate live store. A reader who missed the last edition scrolls back through the ledger.

**Cadence and identity.** Default cadence is every 12 hours (chosen so both sides of a US/Asia working day get a fresh edition). Each run inserts a NEW immutable edition. Editions are identified by `generated_at` and `edition_seq`, never by weekday.

## 7. The config card (defining one Readout)

A new Readout is a filled-in config, not new engine code. The config MUST declare:

1. **Subject** — what this Readout is about.
2. **Sources** — which adapters and inputs feed it (CIP lenses and/or external, per 5.1).
3. **Significance rules** — how the fact pack is computed and ranked (deltas, thresholds, what counts as worth saying).
4. **Storage** — which ledger table and tenant scope.
5. **Audience** — the confidentiality/role shape (who may see which layer).
6. **Layers** — Layer 1 only, or Layer 1 plus Layer 2.
7. **Cadence + delivery** — how often, and to which surfaces (dashboard, Slack, email, or none).
8. **Writer settings** — which Roster model, the narration prompt, and how many prior editions to feed for continuity.

That card is the whole customization surface. Fill it, and the engine produces a conformant Readout.

## 8. How to add a new Readout

1. Write the config card (section 7). If you cannot fill every field, the Readout is not yet scoped.
2. Register or reuse the source adapters (section 5.1). If a needed source has no adapter, author one; do not modify the engine.
3. Define the fact-pack computation for the subject (the significance rules). Keep every number in code.
4. Create or reuse the ledger table (section 6) under the subject's tenant scope.
5. Write the narration prompt(s): Layer 1 always, Layer 2 if declared. State the golden rule to the model explicitly.
6. Wire the run into the FAS runtime (schedule + Roster + delivery). This is the only runtime-side step.
7. Dry-run against one period. Confirm numeric fidelity and confidentiality pass before enabling the schedule.
8. Enable. The first live edition files itself; the ledger grows from there.

## 9. What this is NOT

- **Not the agent briefing.** A briefing is a queue of items to action (`briefing_items`); a Readout is a narrative of computed state.
- **Not a compute engine.** The model never computes. If a fact is not in the fact pack, it does not exist for the Readout.
- **Not opinion in Layer 1.** Interpretation lives in Layer 2, labeled and confidence-scored, internal by default.
- **Not a delivery guarantee.** The ledger is the source of truth; delivery is best-effort on top of it.
- **Not CIP-hosted at runtime.** CIP defines and stores; FAS runs.

## 10. Cross-references

- **[`JOS-S66`] Readouts Standard** — the venture-agnostic governance this contract implements.
- **CIP-CAP-007 (Intelligence & Alerts)** — the pillar this capability lives under.
- **D-146** — CIP library shape; consumers host the runtime.
- **`docs/LENS-AUTHORING-GUIDE.md` (CIP-SOP-003)** — how the CIP lens sources are authored.
