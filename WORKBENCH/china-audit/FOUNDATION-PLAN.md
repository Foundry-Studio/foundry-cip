# FOUNDATION PLAN — the consolidation waves

**Written by Fable, 2026-07-14, at Tim's direction. Executed by Opus in checkpointed sections.**
**This file is the spec. The ACTION-LIST is the checkbox index. Read BOTH before every wave.**

---

## THE PHASES (Tim's sequencing — do not reorder)

1. **FOUNDATION** — the waves below. NOT the 549 seller records.
2. **SELF-MAINTAINING** — ingestion correctness, deterministic recompute on the rails, LLM
   check-ins. *Designed WITH Tim when Phase 1 is done.*
3. **TIM'S SPREADSHEETS** — coverage check against everything he holds; new fields if warranted;
   blast radius checked before any addition.
4. **GAPS, then Metabase / reporting.**

## THE VERDICT SEMANTICS (Tim, verbatim intent — this is the constitution)

> *"If we Are SURE they are chinese based on the indicators, any of them, they are confirmed.
> EVERYTHING else is unknown or probable. We will then do checks on all of those… KNOWN american
> and large brands, which we will flip to USA. or other countries, we flip to not china."*

| verdict | earned by |
|---|---|
| **china** (confirmed) | ANY approved indicator, or a human pin |
| **probable** | channel/name evidence only (`chinese_partner`, pinyin) → **Tim's check queue** |
| **not_china** | a human ruling, or a LEGAL RECORD (Amazon seller of record / USPTO owner). **NEVER Wayward's country flag** |
| **unknown** | nothing |

**Approved confirming indicators** (any ONE confirms china): `on_exclusion_list` · `eric_sheet` ·
`wayward_country_cn` · `chinese_email_domain` · `cjk_in_name` · `phone_+86` · `qq_handle` ·
`cn_mobile_handle` · `cn_company_name_pinyin` · `shared_owner_mailbox` · `amazon_seller_entity` ·
`uspto_trademark_owner` · `manual_review`(human).
**Probable-tier**: `chinese_partner` · `pinyin_name_in_email` · `pinyin_contact_name`.
**Corroboration-only, never verdict-bearing**: `wayward_country_other`.

---

## THE CHECKPOINT PROTOCOL (anti-drift — follow it literally)

Every wave, in order, no exceptions:

1. **READ** this wave's spec + the STANDING RULES in ACTION-LIST.md.
2. **PRE-CHECK** — run the wave's listed queries via the MCP read tool
   (`foundry_mcp_cip_query`, tenant `078a37d6-6ae2-4e22-869e-cc08f6cb2787`). Record the BEFORE
   numbers in the checkpoint report. **Look at actual rows before writing anything.**
3. **CHANGE** — exactly ONE migration or ONE script edit. Nothing rides along.
4. **VERIFY** — alembic up/down/up on the local `cipobs` container → apply to prod (read the live
   FAS revision for the cross-chain guard) → `ruff check cip/ tests/` → `python
   scripts/check_invariants.py`. All green or STOP and report.
5. **DIFF** — AFTER numbers vs the wave's PREDICTED movement. Any surprise = STOP, report, do not
   "fix forward."
6. **COMMIT** — one commit, message explains the why. `git branch --show-current` first (master).
7. **CHECKPOINT REPORT** to Tim in chat: before → after, what moved, anything parked. Update the
   ACTION-LIST checkbox.
8. **STOP.** Wait for Tim's go. No starting the next wave unprompted.

**Discoveries mid-wave** go to `PARKING.md` or `QUESTIONS-FOR-TIM.md`. They do NOT expand the wave.
**Reads via MCP, not throwaway scripts.** Writes only via the wave's migration/script.
**No subagents during foundation waves** — none of these need a fleet.

---

# THE WAVES

## W0 — BASELINE (no changes; pure snapshot)

**Goal:** every later wave diffs against a recorded number, not memory.
**Do:** via MCP, capture into `WORKBENCH/china-audit/BASELINE.md`:
- verdict distribution — whole book AND `reality='REAL'`-only, from `lens_ps_china_verdict` ×
  `lens_ps_brand_reality`
- the signal × source_system matrix with brand counts (`ps_nationality_signals` GROUP BY signal,
  source_system, points_to)
- `ps_added_facts` by asserted_by × value (live rows only)
- chase-list count; reality distribution; invariant run output (17/17)
- the six hard-contradict brands (COOLIFE, Gelrova, MOSDART, Jarkyfine, Neathova, Heyvalue) and
  `is_chinese` disagreement counts (498 / $48,764 expected)
**Predicted movement:** none. **Checkpoint:** the file, committed.

## W1 — HONEST LABELS (was B4; do this BEFORE the verdict rebuild)

**Goal:** no machine guess wears a human's authority. Verdicts must not move.
**Scope — exactly two row-sets, nothing else:**
- (a) The **131** rows `signal='manual_review' AND source_system='tim:tier1_approval_2026_07_14'
  AND evidence ILIKE '%shares mailbox%'` → they are the shared-mailbox rule restated. Tim approved
  the RULE (the tier-1 batch), not 131 individual investigations. Re-signal them to a new vocabulary
  entry **`tim_batch_approval`** (CHECK constraint extended; strength `confirmed`, points_to
  `china`). The evidence text already says exactly what happened — keep it.
- (b) The research-agent `manual_review` rows (AIRNEX, aloderma china; ACE Supply, Actial
  Nutrition, Acupoint not_china) → DELETE the `manual_review` row only. Their legal-record signal
  rows (`amazon_seller_entity` / `uspto_trademark_owner`) stay and carry the verdict.
**Explicitly out of scope:** the `Claude (manual review, Tim-delegated)` rows — those were
case-by-case reviews Tim explicitly delegated ("you check each one MANUALLY"), honestly attributed.
**Predicted movement:** verdict counts IDENTICAL before/after (131 keep `shared_owner_mailbox`;
research brands keep their legal signals). `pinned` added_facts untouched.
**Authority for the deletions:** this plan, approved by Tim in chat 2026-07-14 ("I am happy with
all of these" + the plan-of-record message). Quote in the migration docstring.
**Verify:** verdict distribution diff = zero rows moved.

## W2 — THE 4-STATE VERDICT (the constitution, in SQL)

**Goal:** rebuild `lens_ps_china_verdict` to the semantics table above.
**CASE order:** human `manual_review` not_china → human `manual_review` china → any approved
confirming indicator → legal-record not_china → probable-tier → unknown. `has_conflict` stays and
now also flags probable-vs-legal disagreements.
**Consequences to predict and report honestly:**
- `wayward_country_other`-only brands: **not_china → unknown** (~380 real brands). Wayward's flag
  stops deciding. It remains visible as corroboration in `not_china_evidence`.
- `chinese_partner`-only brands: **china → probable** (~3 real: SZEE, Lille Home, Yoleo — the A4
  three land at the TOP of Tim's probable queue, which is exactly "they are LIKELY chinese, and I
  Will manually check each"). Guard-relevant shrink, pre-authorized by that quote.
- pinyin-only brands: → probable (expected ~0 real; verify).
**Also in this migration:**
- `lens_ps_china_chase_list` recreated unchanged in meaning (verdict='china' only — probable is NOT
  chased yet).
- NEW invariant **`not_china_requires_human_or_legal`**: count of not_china verdicts with neither a
  human pin nor a legal-record signal = 0. Tim's rule becomes a permanent tripwire.
- Update `china_verdict_on_a_name_guess` invariant if its predicate needs the probable tier.
**Verify:** every count movement matches prediction; chase list ≈ unchanged; 18/18 invariants.

## W3 — ONE HOME FOR `is_chinese` (C1)

**Goal:** the money spine stops contradicting the verdict (498 brands / $48,764; six say `false`
while the verdict says china).
**Change:** backfill `ps_monthly_earnings.is_chinese` FROM the verdict (china→true,
not_china→false, probable/unknown→NULL) **and** fix the writer (`compute_monthly_earnings`) to
derive it from the verdict lens every run — data + script in the same wave, or the next run reverts
it (the cip_68 lesson). Column comment: DERIVED — the verdict lens is the home.
**New invariant `spine_is_chinese_matches_verdict`** = 0 disagreements.
**Predicted movement:** no verdict changes; spine flags only. The 6 hard-contradicts flip to true —
list them in the checkpoint.
**Verify:** disagreement count 0; money totals byte-identical (this touches a flag, never an amount).

## W4 — THE RATE CLOCK (C3)

**Goal:** kill the last `+365+183` day-count (wrong boundary on 2,371 of 2,829 deals; each fires the
day its deal crosses month 19).
**Change:** drop/recreate `rate_10_expires` / `rate_6_expires` as calendar-month GENERATED
expressions (`productive_date + INTERVAL '12 months'`, `+ INTERVAL '18 months'`, ::date).
**Verify:** `stored_rate_clock_is_a_day_count` query = 0 (promote it to invariant #19);
`lens_ps_rate_clock` spot-check on month-boundary deals; spine untouched (`rate_tier_18_months`
still holds).

## W5 — ALIAS TRUTH IN THE HEADLINES (C2, minimal)

**Goal:** stop double-counting the 852 alias rows in the numbers people quote — WITHOUT rewriting
money lenses (money is frozen).
**Change (one migration):** add `canonical_brand_id` + `is_alias_row` passthrough columns to
`lens_ps_china_verdict`; add a small `lens_ps_china_companies` rollup (one row per canonical
company: verdict by precedence china>probable>not_china>unknown across siblings, sibling count).
Headline counts come from the rollup from now on.
**Predicted:** row-level lens unchanged; new company-level truth ≈ 1,588 china (from the audit's
collapse estimate — verify live).
**Verify:** rollup count vs the audit's reproduction query; no lens regressions.

## W6 — SCRIPTS FULL CLEAN (D1 + the attic)

**Goal:** the scripts directory contains exactly the tools of record, and the harvest can rebuild
every deterministic signal from source.
**Keep:** `check_invariants.py` · `_guard.py` · `ingest_amazon_sellers.py` (with ONE change: stop
writing `manual_review` rows — `amazon_seller_entity` is itself an approved indicator now) ·
`load_added_facts.py` · `dbq_runner.py` (if FAS workaround still needed).
**Rewrite:** `harvest_nationality_signals.py` — regenerates ALL deterministic `(signal, source)`
pairs idempotently (today it knows 8 of 24): both Stripe email passes, HubSpot company+contact
country (CN and other), Stripe address country, `+86` phones, QQ/mobile handles, CJK, pinyin-company
names, shared-owner-mailbox **with the agency guard** (skip any mailbox whose brand-set contains a
confirmed not_china brand) and the JUNK exclusion. **DELETE the pinyin person-name regexes** —
existing pinyin rows stay as probable-tier evidence, but no machine creates new ones. Post-run:
prints the signal×source matrix vs live DB (self-audit).
**Attic:** every other script → `scripts/attic/` with a one-line README each (git mv, history kept).
**Verify:** dry-run harvest = zero new rows on today's data (idempotent); matrix self-audit clean;
invariants hold.

## W7 — SCHEMA CONSISTENCY BATCH (small, mechanical)

One migration: FK `product_id` → `ps_products` (10 tables — NOT VALID + VALIDATE to avoid
locks) · FK `canonical_brand_id` → self · CHECK on `ps_excluded_brands.bucket` vocabulary ·
normalize `eligible_for_10_rev_share` to boolean-with-CHECK (or CHECK on the text values) · fix the
`pinned`/`superseded_by` disagreement + CHECK (superseded ⇒ not pinned) · units comment on
`ps_stripe_invoice_lines.amount` ("DOLLARS, not cents") · fix the `'boost'`→`'boosted'` comment lie ·
warning comment on `ps_monthly_earnings.variance` (month-level phantom; brand-level only).
**Verify:** every FK VALIDATEs clean (0 orphans was already measured); invariants hold.

## W8 — THE SHRINK-THE-UNKNOWNS CHECKS (report, then Tim rules)

**Goal:** work the post-W2 pile (~930 real unknown + probable) down with CHECKS, per Tim: known
American/large brands → he flips to USA/other.
**Do:**
- Build `lens_ps_china_evidence_grid` — one row per company, one boolean column per indicator, plus
  the corroboration columns (wayward says US, HubSpot says US, has legal record). This is the "don't
  make Tim query" surface.
- Produce the ranked candidate report: unknown/probable brands with strongest not-china
  corroboration + recognizable-name flag + billing weight. **A report. Nothing auto-flips.**
- Tim rules in batches (chat or a review page, his choice). His flips go in via `load_added_facts`
  (pinned, attributed).
**Exit criteria for Phase 1:** every REAL brand is china / not_china / probable-with-owner /
unknown-with-next-step, and Tim has seen the shape of all four piles.

---

## PARKED (explicitly NOT in these waves)

- The **549 Amazon seller records** (A-track) — list, brief, and tested ingest are ready and waiting.
- B1 (`service908`), B2 (`zhou_yintong`), B3 (RobKushner), A4 (the three — now = probable queue) —
  **Tim's calls**, in QUESTIONS-FOR-TIM.md.
- added_facts → verdict direct wiring (today it flows via companion manual_review rows; works, but
  it's indirection — revisit in Phase 2).
- D2 (dead CIP tables), D3 (freshness monitor rewrite) — Phase 2.
- MCP write tools (`cip_china_record_decision` / `cip_china_ingest_sellers`) — decide in Phase 2
  when we design self-maintaining; the guard + single-script path covers Phase 1.
- Metabase — Tim: later.
