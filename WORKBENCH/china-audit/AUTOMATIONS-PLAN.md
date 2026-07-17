# AUTOMATIONS PLAN (P3) — data comes in by itself, and silence screams

**Status: DRAFT for riff + review.** Research done (2 land surveys + best-practices pass,
2026-07-16). Next: riff with Tim on the LLM/enrichment side (§6), then adversarial review by an
Opus subagent, then build. Nothing here is applied yet.

**The mission in one line:** the money engine and the china book stay correct **without anyone
remembering to run a script** — and when a feed stops, we hear about it in Slack before the numbers
go stale.

---

## 0. The anchors (agreed with Tim, 2026-07-16)

1. **Silence is the enemy** — every feed gets a freshness tripwire; staleness is a loud failure.
2. **Same pull twice lands once** — idempotent by construction, not by luck.
3. **The past changes** — refunds/voids rewrite old months; live math moves; statements are pinned.
   (Tim's stance: decide after research → recommendation in §5.)
4. **Pull everything, filter later** — connectors never filter at ingest.
5. **One pattern, one home** — new feeds ride the existing FAS scheduler + CIP sync machinery. No
   second scheduler, no stray cron.
6. **Machines gather, code decides, Tim rules** — LLMs transcribe evidence; code classifies
   mechanically; ambiguity queues for Tim. Nothing automated overturns a human ruling.
7. **No anonymous facts** — every automated write carries source_system / asserted_by / evidence.
8. **Every sync ends with the tripwires** — the 21 invariants run on schedule; a violation escalates.
9. **Keys in one safe place** — restricted read-only Stripe key, Railway env, never in repo.
10. **Jake/Rhea boundary** — no asks yet (RULES #9), so their feeds get *hardened manual drops*, not
    true automation.

**Screams land in:** the ops Slack channel — already wired: `post_ops_alert()` →
`SLACK_ALERTS_CHANNEL` (default `#foundry-ops-alerts`), token via `SLACK_SYSTEM_BOT_TOKEN` /
`SLACK_BOT_TOKEN` (FAS `src/integration_mesh/channel_adapters/slack_client.py:79-147`).

---

## 1. Land survey — what exists vs what's manual (the honest picture)

### Already automated and healthy (don't rebuild — extend)
| thing | where | proof |
|---|---|---|
| Hourly HubSpot sync (:17 UTC) | FAS `seed.py` SYSTEM_SCHEDULES → `cip_sync.py:run_wayward_hubspot_sync` → CIP `run_sync()` orchestrator | `cip_deals.refreshed_at` ~50 min old when checked |
| Hourly Zendesk sync (:47) | same pattern | — |
| PS lens mirror (:37) | `cip.integration_mesh.sync.ps_lens_mirror.run_ps_china_mirror` — **a sync module, not a full connector** (lifted from a script; precedent for Stripe) | — |
| **CIP freshness watchdog** (:23/:53, every 30 min) | FAS `cip_freshness_watchdog.py` — checks `MAX(refreshed_at)` per entity, alerts >3h stale to ops Slack | catches the silent-death modes `consecutive_failures` misses |
| Failure escalation | dispatcher increments `consecutive_failures`; ≥5 → `schedule_health_notifier` Slacks; ≥10 → schedule auto-disabled | — |
| Sync bookkeeping | `cip_sync_runs` (status, counters, `cursor_state` JSONB, error_detail) written by `SyncRunRecorder` | — |

### Manual today (the gaps this plan closes)
| feed | today | risk |
|---|---|---|
| **Stripe (the money spine)** | `scripts/ingest_stripe_invoices.py` run by hand — **all 75,658 lines landed in ONE run on 2026-07-13, never refreshed** | the whole engine reads a stale snapshot while looking "live" |
| Payment reports (Jake) | `scripts/ingest_payment_reports.py` per sheet — already well-hardened (header-mapping, reject-on-missing, email-total cross-check, idempotent) but EXPECTED_TOTALS is a **code edit per month** + no "month is missing" tripwire | forgotten months; silent absence |
| Seller-of-record / website enrichment | manual LLM research → handoff files → `ingest_amazon_sellers.py` | the 549 queue ($82.7k) clears at human speed only |
| Invariants | run ad-hoc (`scripts/check_invariants.py`) | violations found only when someone thinks to look |

Key architecture facts (from the surveys):
- CIP is an **installed package** in FAS's venv; FAS executors are thin glue
  (`src/work_execution/producers/scheduled_tasks/cip_sync.py`), NullPool engine (avoids the 180s
  statement_timeout + PgBouncer advisory-lock issues).
- The full connector framework (Protocol + `run_sync()` orchestrator + mappers) targets the `cip_*`
  SCD-2 entity tables. **`ps_stripe_*` are bespoke tables** with computed fields (`is_ps_base`,
  `billing_month` parsing) — the mapper contract doesn't obviously fit them. The **lens-mirror
  precedent** (sync module + `SyncRunRecorder`, no mapper) does.
- The Stripe scripts' upsert keys are sound: `(tenant_id, stripe_invoice_id)` /
  `(tenant_id, stripe_line_id)`, `ON CONFLICT DO UPDATE`. The parsing (`classify()`: month/channel/
  fee_type/`is_ps_base`) is the formula that reconciled to the penny — **reuse it verbatim, never
  re-derive**.

---

## 2. Best-practices findings that shape the design (citation-backed)

1. **Poll, don't webhook.** Mature warehouse pipelines (Airbyte, Fivetran, Stripe's own Data
   Pipeline) poll — webhooks are at-least-once, unordered, ~3-day retry, and need an endpoint.
   Hourly polling of **`/v1/events` as the change feed** is the converged pattern.
2. **A `created` cursor alone silently misses mutations** (paid→void, refunds, credit notes) —
   most Stripe list endpoints have no `updated` filter. Pattern: Events API cursor + **hydrate the
   named object by ID** (don't trust event payloads) + **24h lookback window** + **weekly full
   refresh** as the safety net (events expire at 30 days; some changes emit no event).
3. **"Collected" is subtler than `status='paid'`.** An invoice can reach `paid` via a 100% credit
   note with **zero cash**; refunds live on charges, not invoices. → §5 watch-item.
4. **Idempotency:** upsert by Stripe object ID + recency guard (never let a stale fetch overwrite
   newer data); soft-delete flags; log processed event IDs.
5. **Restricted key scopes (read-only):** Invoices, Customers, Credit notes, Charges, Refunds,
   Events (+ Balance transactions if we reconcile cash later). Rotate with the 7-day-overlap
   dashboard feature; capture the old key before overwrite (house rule).
6. **Rate limits are a non-issue** at our scale: hourly incremental ≈ 10–100 requests; weekly full
   ≈ ~1,000 requests (~2–3 min at a self-throttled 10 req/s vs Stripe's 100 reads/s live limit).
7. **Freshness:** warn at 2× cadence, error at 4× (hourly sync → warn 2h / error 4h); check twice
   per cadence; a heartbeat row per run so "zero new data" ≠ "sync died"; **absence of success
   alerts, not just presence of failure**.

---

## 3. Scope item 1 — Stripe goes truly live (the foundation)

**Decision: the lens-mirror pattern, not a full framework connector.**
Lift `ingest_stripe_invoices.py` + `ingest_stripe_customers.py` into
`cip/integration_mesh/sync/ps_stripe_sync.py` (callable from scheduler / CLI / tests; scripts
remain operator wrappers). Reasons: (a) the `ps_stripe_*` tables + penny-reconciled parsing don't
fit the `cip_*` mapper contract; (b) `ps_lens_mirror` already proved this exact shape in
production; (c) smallest new surface on the money path. A full connector refactor stays possible
later — this decision is reversible.

**Honesty note (review H5):** the reused-verbatim kernels are `classify()` + the two upsert
statements (the penny-reconciled parts). `run()`'s control flow is REPLACED, not lifted — the old
script prefetches the ENTIRE customer list every call (incompatible with hourly); the new module
hydrates customers per-event (the script's `brand_of` fallback is the seed for this).

**The sync, each hour (holding the `ps-stripe-v1` advisory lock — see below):**
1. Read cursor from last `cip_sync_runs` row (`connector_id='ps-stripe-v1'`): last event `created`
   + last event id.
2. Poll `/v1/events?created[gt]=cursor−24h&types[]=` invoice.*, customer.*, credit_note.*,
   charge.refunded (types list finalized at build).
3. For each named object: **hydrate by ID** (GET the current invoice/customer), then upsert with
   the existing keys + `classify()` parsing. **Hydrate-by-ID IS the correctness guard** — we always
   land current state, so replaying an event is idempotent; there is no separate version check
   (review C3.3: the scripts' `ON CONFLICT DO UPDATE` is unconditional and Stripe invoices carry no
   reliable `updated` to compare).
4. Customers: same event-driven path (`customer.updated` etc.) + the brandId join logic from
   `ingest_stripe_customers.py`.
5. Write counters + new cursor to `cip_sync_runs` via `SyncRunRecorder`.

**`ps_stripe_events_processed` (review H6 — specified):** `event_id TEXT PK, event_created
timestamptz, object_id TEXT, applied_at timestamptz` + tenant/RLS like siblings; pruned to 45 days
(> Stripe's 30-day event retention). Because hydrate-by-ID makes replays idempotent, this table is
an **optimization + audit trail**, not a correctness requirement — a lost row causes a redundant
re-fetch, never wrong data.

**Concurrency (review C3 — REQUIRED):** the lens-mirror precedent is only half-applicable — its
locked half goes through `run_sync`; its direct-upsert half (which Stripe entirely is) holds NO
lock, and `max_concurrent=1` only serializes within one schedule_id. The Stripe module therefore
takes its own **advisory lock** (reuse the orchestrator's `_advisory_lock_key(tenant,
"ps-stripe-v1")` pattern) around BOTH hourly and full modes — second-to-fire skips cleanly and
records a skipped run.

**Weekly full refresh** (safety net for event-less mutations): same module, `mode="full"`,
scheduled **Sunday 03:03 UTC** (review C3.2: NOT :07 — the hourly fires at :07 every hour incl.
Sunday 03:07, so the original minute collided with itself; :03 is unused fleet-wide). Runtime ≈
2–3 min; explicit `timeout_seconds` set (1800 hourly / 3600 full — review L12). Auto-fallback:
cursor >25 days old → force full (only 5 days inside Stripe's 30-day event horizon — don't let it
slip). **Deployment order (review M7): the full refresh is STEP 0** — run it once to close the
2026-07-13→now gap and seed the cursor, THEN enable the hourly schedule. **Why Stripe
specifically:** HubSpot's API supports "modified since" natively, so hourly increments already
catch edits; Stripe's list endpoints filter on `created` only, events expire at 30 days, and a few
mutations emit no event — the weekly full is the guarantee the MONEY table can never drift >7 days
from truth.

**Refunds + credit notes (REFRAMED — review C1, verified on prod):** refund economics are
**already partially in "collected"**: 777 negative paid `is_ps_base` lines (−$10,543.11; 102
ledger rows with negative collected months) — Wayward's reconciliation-adjustment lines are
Stripe-native negative invoice lines, and the ledger already nets them (the
`net_negative_on_positive_revenue` invariant explicitly tolerates refund months). So the danger
inverts: naively netting new `ps_stripe_refunds`/`ps_stripe_credit_notes` tables into collected
would **double-subtract**. Build rule: the new tables land **EVIDENCE-ONLY** (ingest, don't net).
The verification question is not "are there refunds?" but "**which refund economics are NOT
already represented as negative `is_ps_base` lines?**" — reconcile Stripe-native
refunds/credit-notes against the negative-line total; only a proven-uncovered remainder may ever
enter the derivation, as its own explicit term, with the invariant suite re-baselined.

**Monthly full re-sync for HubSpot/Zendesk (Tim, 2026-07-17):** their hourly "modified since"
increments miss DELETED/MERGED records. Same framework (`sync_mode="full"`), one schedule row each,
monthly — **1st Sunday 04:11 / 04:41 UTC** (review L11: NOT 04:00 — three existing Sunday-04:00
jobs incl. a 2h graph sweep already pile there; these route through `run_sync` so they self-lock,
it's purely a load-window courtesy). Cheap insurance, same pattern.

**FAS wiring** (mirrors HubSpot exactly):
- `seed.py` SYSTEM_SCHEDULES: `cip_ps_stripe` hourly at **:07** (unused minute; existing: :17 :23
  :37 :47 :53) + `cip_ps_stripe_full` weekly. **Tenant = Project Silk `078a37d6`** (the survey's
  sketch guessed EcomLever — wrong; `ps_stripe_*` rows are PS-tenant).
- Executor `run_wayward_stripe_sync` in `cip_sync.py` (NullPool engine, same as siblings).
- `STRIPE_API_KEY` → **new restricted read-only key** (scopes per §2.5) set on Railway; the current
  key in Tim's env is replaced per the capture-old-credential rule.

**Verification gates:** replay Dec-2025→Jun-2026 and reconcile to the existing penny-exact totals;
run twice in a row → second run lands ~0 changes; void an invoice in test → status flips within
one cycle; `lens_ps_claim` recovery unchanged on a quiet hour; **per-scope key probe at deploy**
(one GET per required scope — a mis-scoped restricted key is caught at setup, not Sunday 03:03;
review L13); staged concurrency test (fire hourly + full together in cipobs → second skips via the
advisory lock).

---

## 4. Scope item 2 — freshness + invariants (the "silence screams" layer)

1. **Extend the existing watchdog — via a small REFACTOR, not a one-liner (review H4):** the
   watchdog hardcodes `MAX(refreshed_at)` and `ps_stripe_invoice_lines` has `ingested_at` — naively
   adding the table crashes the WHOLE watchdog (`UndefinedColumn` → EC + PS monitoring both go
   dark). Refactor `TENANT_ENTITY_MATRIX` to per-entity `(table, timestamp_column)`, template the
   column, then add `ps_stripe_invoice_lines → ingested_at`. Two more review items land here:
   **"money table empty = ALERT, not skip"** (the current empty-table branch would suppress the
   stale-money alarm under an RLS change — review M10), and warn/error tiers need real plumbing
   (today it's a single threshold).
2. **Schedule the invariants — with a SWALLOW-not-fail contract (review C2):** naive wiring is a
   trap: `run_ps_invariants` RAISES on violation → task fails → `consecutive_failures` climbs → at
   10 the schedule AUTO-DISABLES — a real violation lasting >10h would disable the very tripwire
   that's screaming. The FAS glue therefore **catches `InvariantViolationError`, posts
   `post_ops_alert()` immediately, and returns a violations dict (task SUCCEEDS and keeps checking
   hourly)**; only genuine execution errors (DB down, dropped lens) propagate as task failures.
   Data problems alert; infra problems fail. New schedule `ps_invariants_check` hourly at :12.
   Two pre-conditions: fix the GUC leak (`set_config(..., false)` is session-scoped and would leak
   PS tenant onto FAS's pooled connections — flip to `true` or run on a NullPool engine; review
   M8), and add `seen_in_*` flag maintenance to ingest so `stale_seen_in_flags` can't flap (green
   today — 21/21 verified — but nothing maintains those caches; review C2/M9 shared root cause).
3. **Monthly expectation for Jake's reports**: a check (same watchdog run) that month M's payment
   report exists in `ps_payment_events` by day N of M+1 — else a *reminder-grade* Slack (it's a
   human dependency, not a system failure). **Open question for Tim: what day is "late"?** (Jake's
   cadence?)
4. **Add freshness to the invariant suite** as a backstop (`stripe_spine_fresh`: newest
   `ingested_at` < 26h) so even the invariant path catches a dead feed.

---

## 5. The "past changes" recommendation (Tim asked me to bring one)

**Recommendation: let live numbers move + build a cheap drift flag. Flag, don't block.**
- Live math stays live (already decided; correct).
- Build **`lens_ps_statement_drift`**: current live `ps_claim_owed` per brand vs the latest pinned
  `ps_claim_statements` figure → `drift_amount` + `drift_direction`. One thin view, no schema-of-
  record change.
- Surface it two ways: (a) it's the **first thing checked before sending any invoice/statement**
  (LENS-CATALOG gets the rule); (b) weekly ops-Slack digest line: "N brands drifted vs their last
  statement, net $X" — visibility without alarm fatigue.
- **Watch-item (v2, verify-first):** per §2.3, `paid` can be cashless (100% credit note) and
  refunds live on charges. Current `usage_collected` counts line amounts when
  `invoice_status='paid'`. First step is a one-off verification query (do any Wayward invoices have
  credit notes / refunds at all?); ingest `credit_notes` + `refunds` tables **only if** the answer
  is yes. Don't build for a case the account may not contain — but check, because it silently
  inflates "collected" if present.

---

## 6. DEFERRED — the decision system (Tim, 2026-07-17: solid data first)

**Tim's framing, now the plan's law:** two kinds of data. **SOLID data** = facts pulled from
sources (Stripe, HubSpot, Zendesk, Slack exports, payment sheets) — automate that first, it's
plumbing, no judgment anywhere. If a source *says* chinese (country=CN, exclusion list, Eric
sheet), the existing approved signal rules settle it mechanically on ingest. **DECISION data** =
"the sources are silent — is this chinese?" — the enrichment/research system below. That gets
designed AFTER solid-data automation ships. The decision queue self-builds meanwhile: whatever
solid data doesn't settle stays `unknown` in `lens_ps_china_evidence_grid`.

One addition this framing surfaces: **`harvest_nationality_signals.py` is solid-data machinery,
not decision machinery** — it deterministically turns already-ingested fields (CN country codes,
+86 phones, exclusion-list membership…) into settled signals. It runs **hourly at :27** (Tim,
2026-07-17: daily would create "a weird day of reporting" — a CN brand arriving at 9:17 must not
report as `unknown` until tomorrow; :27 sits right after the Stripe :07 and HubSpot :17 pulls so
facts become verdicts inside the same hour). Gate before scheduling: verify idempotency (double-run
= zero new rows); it's cheap deterministic SQL over already-ingested data, no API calls.
**Review-verified (M9):** the harvester IS idempotent (`ON CONFLICT ... DO NOTHING`), additive-only,
no book-guard/promotion side effects — hourly is semantically safe. Two build items: give it a
**heartbeat** (`cip_sync_runs` row per run — today, if it silently dies, nothing notices), and its
`eric_sheet` harvest reads the unmaintained `seen_in_eric_sheets` cache — same root cause as the
`stale_seen_in_flags` invariant; the §4.2 seen_in maintenance fixes both.

### The deferred sketch (riff when we get here — not now)

The machine that clears the 549 queue ($82.7k) and every future unknown. Sketch to riff on:

```
[queue: lens_ps_china_evidence_grid unknowns / SELLER-RECORDS-549 list]
   → FETCH (code): Amazon storefront seller page + brand website
   → TRANSCRIBE (LLM): extract strings ONLY — business name, address, country as printed.
        No judgment. Output = quoted evidence + source URL.
   → CLASSIFY (code, existing ingest_amazon_sellers.py rules):
        CN/HK/Macau address → china signal (amazon_seller_entity, definitional-grade)
        elsewhere + real address → not_china signal (legal_record grade)   [gated by Q0 ruling]
        registered-agent mail-drop → HELD for Tim (never auto-cleared)
        no seller page found → stays unknown
   → WRITE (code): ps_nationality_signals with evidence + source, asserted_by = pipeline id
   → TIM'S QUEUE: held/conflict cases, in a reviewable doc (SELLER-RECORDS pattern)
```

Riff questions:
- **Where does the LLM run?** Options: local fleet models via the roster (cheap, private, slower) /
  frontier API (better at messy pages) / hybrid (local first, escalate ambiguous). Cost vs quality.
- **Fetch reality:** Amazon seller pages behind bot-detection — headless browser? rate?
  screenshots-as-evidence? This is the hard engineering bit, not the LLM bit.
- **Checkpoint UX:** where does Tim review the held queue — MD doc in repo (like
  SELLER-RECORDS-549), a sheet, or CRM-later? How often does the pipeline run — nightly batch?
- **Q0 dependency:** auto-clearing to not_china needs Tim's Q0 rule (trademark owner + seller =
  same entity, non-China, real address?). Until ruled: pipeline can still auto-flip **china**
  (positive identifications are already-approved signals) and queue the rest. That alone likely
  converts a large slice of the 413 billing-unknowns.
- Tim: "we will riff… or come up with better ideas too" — this section is the riff input, not a
  decision.

---

## 7. Scope item 4 — payment-report drop, hardened (until Jake becomes a feed)

Small, surgical:
1. **EXPECTED_TOTALS out of code** → sidecar CSV next to the reports dir (month, expected_total,
   source-note); script reads it; unknown month = loud reject unless `--force`. Tim edits a CSV,
   not Python.
2. **Monthly expectation tripwire** → §4.3.
3. **One-command flow** stays: drop file → run script → invariants auto-run after (already §4.2).
4. Document the drop procedure in LENS-CATALOG/SOURCE-MAP so it's not tribal knowledge.

---

## 8. Build phases + verification discipline

| phase | contents | gate |
|---|---|---|
| **A — money spine live** | §3 sync module + FAS schedules + restricted key + §4.1/4.2/4.4 freshness+invariants wiring | Tier-C, penny-reconcile replay, double-run idempotency, staged Slack test (force a stale reading in cipobs → alert fires) |
| **B — solid-data completion** | schedule the signal harvester (hourly :27; idempotency verified first) + monthly HubSpot/Zendesk full re-syncs + §5 statement-drift lens **[✅ delivered-pending-QC — cip_112_statement_drift]** + §7 payment-drop hardening **[✅ delivered-pending-QC — EXPECTED-TOTALS.csv sidecar]** | harvester double-run = no new rows; drift lens reconciles against a hand-computed brand; drop flow rehearsed on the June sheet |
| **C — decision system (DEFERRED)** | §6 enrichment/research pipeline, designed with Tim after A+B ship | riff + design-lock + Q0 first |

Every phase: subagent QC + self QC + pathspec-scoped commit + push (the cip_110 protocol).
PM: create the P3 project at Phase-A kickoff (per PROGRAM rules — at kickoff, not before).

## 9. Open questions
1. Jake's report cadence — what day counts as "late"? (§4.3)
2. Q0 ruling — gates auto-not_china in the pipeline (§6); china-side can proceed without it.
3. Riff outcomes for §6 (LLM placement, fetch strategy, review UX, cadence).
4. Credit-note/refund presence in Wayward's account — verification query first (§5).
5. Weekly full-refresh window — Sunday 03:07 UTC proposed; any conflict?

## 10. Review trail
- [x] Scope riff with Tim (2026-07-17): solid-data first; harvester hourly; refunds into Phase A;
      monthly CRM fulls; decision system deferred to Phase C
- [x] **Adversarial review by Opus subagent (2026-07-17): GO-WITH-FIXES.** 3 critical / 3 high /
      4 medium / 4 low findings; all 5 load-bearing claims independently re-verified on prod/source
      before folding (incl. C1 stronger than stated: 777 negative paid is_ps_base lines,
      −$10,543.11 already inside "collected").
- [x] Findings folded (this revision): C1 evidence-only refund tables + reframed reconciliation ·
      C2 swallow-not-fail invariant glue + seen_in maintenance + M8 GUC fix · C3 advisory lock +
      full moved to Sun 03:03 · H4 watchdog matrix refactor + M10 empty-is-alert · H5 honest
      reuse-scope · H6 events-table DDL/prune · M7 full-refresh-as-step-0 · M9 harvester heartbeat ·
      L11 monthly fulls off the 04:00 pile · L12 explicit timeouts · L13 key-scope probe.
- [ ] Tim's go → Phase A begins (build model: Fable plans/QCs, Opus agents build — Tim 2026-07-17)

## 11. Build packages (the Opus fan-out, me reviewing/monitoring/QC-ing)

| pkg | repo | contents | depends on |
|---|---|---|---|
| **P1 — pre-fixes** | foundry-cip | M8 GUC `false`→`true` in ps_invariants · seen_in_* maintenance (C2/M9 root cause) · harvester heartbeat | — (small, first) |
| **P2 — the sync** | foundry-cip | cip_111 migration (`ps_stripe_events_processed` + evidence-only `ps_stripe_refunds`/`ps_stripe_credit_notes`) · `cip/integration_mesh/sync/ps_stripe_sync.py` (events cursor, hydrate-by-ID, advisory lock, SyncRunRecorder, per-txn tenant ctx) · refund-overlap reconciliation query · tests + Tier-C | P1 (same repo, sequential) |
| **P3 — FAS wiring** | Foundry-Agent-System | watchdog matrix refactor (per-entity timestamp col, money-empty=alert) · schedules (stripe :07 hourly / Sun 03:03 full / invariants :12 / harvester :27 / CRM fulls 04:11-04:41 monthly) · swallow-contract invariant glue · executors | parallel with P1/P2 (different repo); integration test needs P2 |
| **P4 — deploy + verify** | both | STRIPE restricted key (per-scope probe) → step-0 full refresh → enable schedules → staged Slack + concurrency tests → verification gates | P1+P2+P3 |
