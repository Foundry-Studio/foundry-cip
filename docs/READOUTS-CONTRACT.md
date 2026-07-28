---
id: CIP-K03
uuid: c7d78a2b-28be-4bf3-8ff3-aabcc11507c8
title: Readouts Contract
type: contract
owner: tim
solve_for: The minimum architecture every Readout must satisfy, so any venture, dataset, or agent can stand up a new Readout without reinventing the engine, and so every Readout stays grounded, auditable, and safe.
stage_label: trial
domain: dat
version: '1.1'
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

> **Status:** trial. This is the agnostic contract for the Readouts capability, deliberately venture-neutral, dataset-neutral, and surface-neutral. The first concrete Readout (the Wayward channel Readout) is authored against this contract, not the other way around. Governed by JOS-S66 (Readouts Standard); realized as CIP Pillar 7 capability CIP-CAP-007 (Intelligence & Alerts); run by the FAS WORK system.
>
> **v1.1 (2026-07-28):** a Readout writes to the shelf and consumers pull it (no engine-side delivery); the run is a scheduled WORK-system job; the model authors one long master then distills it to sized renderings; the ledger stores named renderings with character budgets.

## Purpose, Vision, and What Good Looks Like

*The hardened statements to build toward. If a design decision does not serve these, it is wrong.*

**Purpose (the stable why).** Readouts exist so the state of any subject Foundry runs, a venture, a channel, a system, or a client, is legible in plain language to whoever needs it (human or agent), current on a schedule, grounded so every fact is trustworthy, and reusable so a new one is a config and not a rebuild. Without Readouts, every "how are we doing" answer is a bespoke one-off analysis that is stale the moment it is written and has to be redone from scratch next time.

**Vision (where this goes).** Every subject worth watching has a living Readout that keeps itself current, at whatever sizes its consumers need, filed to one shelf that dashboards, agents, and tools all pull from. Anyone in Foundry, person or agent, can ask "what is the state of X and what needs me" and get a trustworthy, current, appropriately-sized answer without reading raw data or commissioning an analysis. The same primitive powers a dashboard headline, a proactive nudge, an agent's cross-venture check-in, and a portfolio roll-up. Readouts become the connective narrative tissue of the system.

**What good looks like.**
- A reader understands the subject's state in seconds, trusts every fact because none was invented, and can scroll back through every past edition.
- A new Readout, or a new size for an existing one, is a config change, never new engine code.
- Every edition is grounded (100 percent fact fidelity), auditable (append-only plus provenance), audience-safe (nothing leaks past its scope), and on the shelf (pulled, never pushed).
- It is boring in the best way: it runs on schedule, fails closed, and never surprises anyone with a wrong number.

## 1. What a Readout is

A **Readout** is a periodically regenerated, machine-written narrative of a subject's current state, grounded entirely in facts a program computed, filed forever in an append-only ledger, and sized to fit wherever it is read.

Hold the whole thing as a newsroom:

- **Reporters** compute the facts. Code and math, never a model.
- **The writer** turns those facts into one full story: the long master edition. The LLM, and it only phrases; it never counts.
- **The copy desk** trims that master to each slot's word count: the short for a dashboard tile, a medium for a digest, whatever sizes are needed. Trimming, not rewriting.
- **The editor** checks every version against the facts and against the audience, and kills anything unsupported or out of scope.
- **The archive** keeps every past edition, so tomorrow's writer can say "still late since Tuesday."
- **The shelf** holds the finished edition in the ledger. Whoever needs it (a dashboard, an agent, another tool) walks up and pulls the size that fits. Nothing is delivered; everything is pulled.

**The golden rule (non-negotiable): narrate, never compute.** The model may only restate, rank, phrase, and shorten facts it was handed. It may not calculate a number, infer a total, or assert a fact that is not present in the fact pack. This is what makes a Readout safe to point at money.

A Readout is **not** the agent "briefing" (`briefing_items`, the Chief-of-Staff inbox of asks and FYIs). A briefing is a queue of items a human must action; a Readout is a narrative of computed state. They may relate later (a Readout can be consumed by a briefing), but they are different objects with different stores.

## 2. Where a Readout runs

CIP is a library, not a service (D-146: consumers host the runtime). The work splits across three homes, and every Readout MUST honor the split:

| Layer | Owns | Home |
|-------|------|------|
| **Definition + computation + storage** | The significance logic, the fact pack, the append-only ledger, the capability declaration | **CIP** (library, Pillar 7) |
| **Runtime** | Waking on schedule, importing the CIP engine, the model calls (via the LLM Roster), the guardrail pass, filing the edition | **FAS WORK system** (the work-execution plane that already runs scheduled jobs and agent duties) |
| **Consumption** | Pulling the edition and rendering the size that fits (a dashboard tile, an agent, another tool, a larger Readout) | Any consumer, at its own initiative |

Two hard boundaries:
- A Readout MUST NOT put model invocation or scheduling inside the CIP library. Those are runtime concerns owned by the WORK system.
- A Readout MUST NOT push or deliver. It writes a finished edition to the ledger and stops. Consumers pull. (An agent that then messages Slack is doing so as a consumer that pulled the edition, not as part of the Readout.)

## 3. Layers and renderings (two independent axes)

Every edition is described on two axes that do not depend on each other:

- **Layers = what kind of content.** Layer 1 (grounded) is facts, phrased. Layer 2 (open) is interpretation. A Readout MUST produce Layer 1 and MAY add Layer 2.
- **Renderings = how much of it.** The same content is produced at more than one length, each with a character budget: a `long` master, a `short` for a tight slot, and any others a consumer needs. Renderings are covered in sections 4, 6, and 7.

### Layer 1: Grounded ("what happened")

The facts, phrased. "Connect GMV is 8.2 percent ahead of last period across 63 producing brands. Two source feeds are late."

- The writer restates and ranks facts from the fact pack. No interpretation, no recommendation.
- **Fact fidelity is strict:** every fact in the prose, whether a figure, a count, a named entity, or an event, MUST appear in the fact pack, or the edition is rejected and regenerated.
- Highest trust. May be rendered to any audience the Readout's confidentiality rule permits, including external partners or customers.

### Layer 2: Open ("what it might mean, what to do")

Interpretation, hypotheses, connections, recommendations. "Boost brands are churning faster than Connect; onboarding is worth a look."

- The writer MAY reason beyond the literal facts, under a second set of guardrails:
  - It MUST label interpretation as interpretation (a hypothesis, not a fact), and carry a confidence signal.
  - It MUST still obey fact fidelity: any fact it cites MUST come from the fact pack. It may draw conclusions; it may not invent facts.
  - It is **internal-only by default.** A Readout MUST explicitly opt Layer 2 into any audience wider than internal operators.

Rule of thumb: Layer 1 tells you what is true; Layer 2 tells you what the system thinks.

## 4. The pipeline (six stages)

Every Readout run MUST execute these stages in order. Stages 1, 2, 5, and 6 are deterministic code; stages 3 and 4 are model calls.

1. **Gather.** The WORK system pulls inputs through source adapters (section 5.1). Sources MAY be CIP lenses, and MAY be anything else (a Slack channel, a Google Drive folder, an external dataset). Not all data comes from CIP.
2. **Compute the fact pack.** Deterministically compute every fact, delta, and significance score in code, and rank them. Output a locked fact pack of ground truths. This stage decides what is worth saying; it is math, not a model.
3. **Author the master.** Hand the ranked fact pack plus the last N editions (for continuity) to the LLM Roster and write one full **long** edition (Layer 1, and Layer 2 if declared). This long is the canonical master. The model sees the fact pack and prior editions, never the raw source rows.
4. **Distill to renderings.** Compress the master to each declared rendering budget (a `short` for a dashboard slot, any others). Distillation is a separate step: every smaller rendering is cut down *from the stored master*, never generated fresh. Because a rendering is a subset of the master, and the master is checked against the fact pack, a rendering cannot introduce or re-round a fact. This step is **re-runnable on its own**: a new slot added later is filled by distilling the existing master, with no re-gather and no re-author.
5. **Validate (the editor).** Reject and regenerate on any failure: fact fidelity (every asserted fact in the master traces to the fact pack; every fact in a rendering traces to the master), confidentiality (no content outside the edition's audience), freshness gate (do not publish over stale inputs without saying so). Fail closed.
6. **File and expose.** Insert one immutable edition (fact pack, master, renderings, metadata) into the append-only ledger. It is now on the shelf. The engine does not notify or deliver; consumers pull.

## 5. Minimum architecture (the contract)

A Readout is conformant if and only if it satisfies all of the following.

### 5.1 Source adapters (source-agnostic)

Inputs MUST arrive through a `ReadoutSource` adapter with a uniform shape: given a subject and a time window, return raw facts. At least these adapter kinds are in scope: a CIP lens adapter (reads `lens_*` under tenant RLS), and a generic external adapter (a Slack channel, a Google Drive folder, an HTTP dataset, a file). Adding a new source kind MUST be a new adapter, never a change to the engine. A Readout MAY combine multiple sources in one fact pack.

### 5.2 Deterministic fact pack

Every fact the Readout will ever state, whether a figure, a count, a named entity, or a change/event, MUST be produced here, in code, and placed in the fact pack. The fact pack is the model's entire universe of facts. If a fact is not in the fact pack, no layer and no rendering may state it. Numbers are the strictest case: the model never computes one. The fact pack MUST also carry significance ranking, so the writer leads with what matters.

### 5.3 Append-only ledger

Every edition MUST be inserted, never updated in place. The ledger is the audit and research trail: it MUST let an operator or agent read any past edition and reconstruct what was known when. See section 6.

### 5.4 Master-then-distill

Exactly one rendering is the **master** (the long), authored directly from the fact pack. Every other rendering is a distillation of the master. Renderings MUST be stored as distinct, separately addressable fields so a consumer can pull one size without loading the others.

### 5.5 Guardrails

Fact fidelity, confidentiality (role or audience shaping), and a freshness gate are all mandatory and enforced in stage 5, before filing, for the master and for every rendering. A Readout MUST fail closed: if a guardrail cannot be evaluated, nothing is filed.

### 5.6 Provenance

Every edition MUST record: the config version that produced it, the model the Roster resolved, a reference to the exact fact pack it narrated, the freshness verdict, and the generation timestamp (UTC). Provenance makes an edition reproducible and auditable.

### 5.7 On the shelf, pulled not pushed

A filed edition MUST be readable by any authorized consumer, which selects the rendering that fits its slot. The Readout does not know or care who consumes it; it files a well-formed edition and exposes it. The engine never pushes, notifies, or delivers.

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
| `renderings` | JSONB: a map of named renderings, keyed by name. Each entry carries `{ max_chars, text, layers, master }`. Exactly one entry has `master: true` (the long, authored from the fact pack); the rest are distilled from it. Always includes at least the master and a `short`. Adding a rendering is a data change, not a schema migration. |
| `highlights` | JSONB, optional: structured headline + ranked highlights for non-prose surfaces (a tile that wants values, not a paragraph) |
| `audience` | The confidentiality/role scope this edition may be rendered to. A Readout with multiple audiences files one edition per audience per run. |
| `source_refs` | JSONB: which sources and snapshots were read |
| `model_id`, `config_version` | Provenance for reproducibility |
| `freshness_ok` | Whether inputs were fresh at generation; drives the "trust after these clear" line |

**Live versus history.** The "live" Readout is simply the latest edition row for a (readout_id, subject_key, audience). The rest are the ledger. There is no separate live store; a reader who missed the last edition scrolls back.

**Cadence and identity.** Default cadence is twice daily, at **05:00 and 17:00 America/Chicago**, pinned to local time so DST does not drift it, chosen to align with both the US and Asia working day. The schedule is fired by the WORK system. Each run inserts NEW immutable editions, identified by `generated_at` and `edition_seq`, never by weekday.

## 7. The config card (defining one Readout)

A new Readout is a filled-in config, not new engine code. The config MUST declare:

1. **Subject** — what this Readout is about.
2. **Sources** — which adapters and inputs feed it (CIP lenses and/or external, per 5.1).
3. **Significance rules** — how the fact pack is computed and ranked (deltas, thresholds, what counts as worth saying).
4. **Storage** — which ledger table and tenant scope.
5. **Audience(s)** — the confidentiality/role shapes (who may see which layer); one edition is filed per audience per run.
6. **Layers** — Layer 1 only, or Layer 1 plus Layer 2, on the master.
7. **Renderings** — the named sizes and their character budgets (at minimum a `long` master and a `short`), each declaring which layers it carries. Smaller renderings are distilled from the master.
8. **Cadence** — when the WORK system runs it (default 05:00 and 17:00 America/Chicago).
9. **Writer settings** — the Roster model tier, the authoring prompt and the distill prompt, and how many prior editions to feed for continuity.

That card is the whole customization surface. Fill it, and the engine produces a conformant Readout.

## 8. How to add a new Readout

1. Write the config card (section 7). If you cannot fill every field, the Readout is not yet scoped.
2. Register or reuse the source adapters (5.1). If a needed source has no adapter, author one; do not modify the engine.
3. Define the fact-pack computation for the subject (the significance rules). Keep every fact in code.
4. Create or reuse the ledger table (section 6) under the subject's tenant scope.
5. Write the two prompts: the authoring prompt (writes the long master, Layer 1 always, Layer 2 if declared) and the distill prompt (cuts the master to a rendering's character budget). State the golden rule to the model in both.
6. Register the run in the WORK system (schedule + Roster). This is the only runtime-side step; there is nothing to deliver.
7. Dry-run against one period. Confirm fact fidelity and confidentiality pass for the master and every rendering before enabling the schedule.
8. Enable. The first editions file themselves; the ledger grows from there.

**Adding a rendering to an existing Readout** (for example when a new dashboard slot lands): add the rendering name and its character budget to the config and re-distill from the stored master. No re-gather, no re-author, no schema change.

## 9. What this is NOT

- **Not the agent briefing.** A briefing is a queue of items to action (`briefing_items`); a Readout is a narrative of computed state.
- **Not a compute engine.** The model never computes. If a fact is not in the fact pack, it does not exist for the Readout.
- **Not opinion in Layer 1.** Interpretation lives in Layer 2, labeled and confidence-scored, internal by default.
- **Not a push system.** The engine files editions to the shelf and stops. Consumers pull; nothing is delivered, and delivery is never the engine's concern.
- **Not tied to a place.** An edition is not "for the dashboard" or "for Slack." It is a well-formed artifact on the shelf; any authorized consumer pulls the rendering that fits.
- **Not CIP-hosted at runtime.** CIP defines and stores; the WORK system runs.

## 10. Cross-references

- **JOS-S66 (Readouts Standard)** — the venture-agnostic governance this contract implements.
- **CIP-CAP-007 (Intelligence & Alerts)** — the pillar this capability lives under.
- **D-146** — CIP library shape; consumers host the runtime.
- **`docs/LENS-AUTHORING-GUIDE.md` (CIP-SOP-003)** — how the CIP lens sources are authored.
