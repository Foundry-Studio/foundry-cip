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

**The sync, each hour:**
1. Read cursor from last `cip_sync_runs` row (`connector_id='ps-stripe-v1'`): last event `created`
   + last event id.
2. Poll `/v1/events?created[gt]=cursor−24h&types[]=` invoice.*, customer.*, credit_note.*,
   charge.refunded (types list finalized at build).
3. For each named object: **hydrate by ID** (GET the current invoice/customer), then upsert with
   the existing keys + `classify()` parsing. Recency-guard so out-of-order events can't regress a
   row. Record processed event ids (dedup table `ps_stripe_events_processed`).
4. Customers: same event-driven path (`customer.updated` etc.) + the brandId join logic from
   `ingest_stripe_customers.py`.
5. Write counters + new cursor to `cip_sync_runs` via `SyncRunRecorder`.

**Weekly full refresh** (safety net for event-less mutations): same module, `mode="full"` — the
existing full-pull path, scheduled Sunday ~03:07 UTC. Also the auto-fallback if the cursor is >25
days old.

**FAS wiring** (mirrors HubSpot exactly):
- `seed.py` SYSTEM_SCHEDULES: `cip_ps_stripe` hourly at **:07** (unused minute; existing: :17 :23
  :37 :47 :53) + `cip_ps_stripe_full` weekly. **Tenant = Project Silk `078a37d6`** (the survey's
  sketch guessed EcomLever — wrong; `ps_stripe_*` rows are PS-tenant).
- Executor `run_wayward_stripe_sync` in `cip_sync.py` (NullPool engine, same as siblings).
- `STRIPE_API_KEY` → **new restricted read-only key** (scopes per §2.5) set on Railway; the current
  key in Tim's env is replaced per the capture-old-credential rule.

**Verification gates:** replay Dec-2025→Jun-2026 and reconcile to the existing penny-exact totals;
run twice in a row → second run lands ~0 changes; void an invoice in test → status flips within
one cycle; `lens_ps_claim` recovery unchanged on a quiet hour.

---

## 4. Scope item 2 — freshness + invariants (the "silence screams" layer)

1. **Extend the existing watchdog** (`cip_freshness_watchdog.py` TENANT_ENTITY_MATRIX): add
   `ps_stripe_invoice_lines` (max `ingested_at`) for PS-tenant with warn 2h / error 4h. Zero new
   infrastructure — it already runs every 30 min and Slacks.
2. **Schedule the invariants**: `run_ps_invariants` already matches the FAS executor contract
   (`function(db, **params)`, raises on violation). New schedule `ps_invariants_check` hourly at
   :12. The FAS glue catches `InvariantViolationError` and posts `post_ops_alert()` **immediately**
   (not waiting for the ≥5-consecutive-failures notifier) — a lying number is urgent.
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
+86 phones, exclusion-list membership…) into settled signals. It belongs on the schedule (daily,
after the syncs) so a new CN flag arriving via HubSpot becomes a china verdict without anyone
running anything. (Verify its idempotency before scheduling; it upserts signals.)

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
| **B — solid-data completion** | schedule the signal harvester (§6 note, daily post-sync; idempotency verified first) + §5 statement-drift lens + §7 payment-drop hardening + §5 credit-note verification query | harvester double-run = no new rows; drift lens reconciles against a hand-computed brand; drop flow rehearsed on the June sheet |
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
- [ ] Riff with Tim on §6 (+ any scope updates)
- [ ] Adversarial review by Opus subagent (architecture, failure modes, missed best practices)
- [ ] Findings folded in; plan marked APPROVED; Phase A begins
