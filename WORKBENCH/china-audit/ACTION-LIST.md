# CHINA AUDIT — ACTION LIST

**READ THIS FILE BEFORE EVERY ACTION. Do not work from memory.**
Opened 2026-07-14 after four self-inflicted errors in one session.

---

# STANDING RULES — check every one before you touch anything

### 1. ADDING evidence is my call. REMOVING it is Tim's. No exceptions.
Every error in this session was a **removal** or a **reclassification** done on my own authority.
Adding is safe and reversible. Removing is destructive.
**Enforced mechanically by `scripts/_guard.py`. Do not bypass it.**

### 2. NEVER assume Wayward's data is correct.
`wayward_country_other` ("Wayward says US") is **not evidence of anything.** A US-registered shell
reports as US — that is the entire pattern we are auditing. It may CORROBORATE. It may never
OVERRULE.

### 3. BrüMate is a ONE-OFF, not a precedent.
A Chinese partner's referral is evidence **FOR** China, not against it. Tim: *"if its chinese
referred those other brands, they are LIKELY chinese."* I inverted this and dropped three brands.

### 4. NEVER accept an agent's finding without re-running its SQL myself.
Five audits were right today. They still all got re-run. That is the deal.

### 5. Check the KIND of evidence, not just its presence.
**An evidence TYPE Tim has not approved is not evidence. Ask him. Do not act.**
This is the rule the import-records failure broke: the research agent used customs data — a type I
had never cleared — and I ingested it without asking. Tim killed it: *"EVERYONE imports from china.
no shipping info helps."*

**APPROVED — act on these:**
- ✅ Who **OWNS the trademark** (USPTO / national register)
- ✅ The **Amazon seller of record** (INFORM Consumers Act business name + address)
- ✅ A **list** — exclusion list, Eric's sheet, heavy producers (definitional, per Tim)
- ✅ A **`+86` phone** · a **Chinese mailbox domain** · **CJK** in the name · a **Hong Kong entity**
- ✅ A **Chinese company name in pinyin** (`…YouXianGongSi`)

**BANNED — never act on these:**
- ❌ **Import / shipping / customs records** (Panjiva, ImportYeti) — *everyone* imports from China
- ❌ A **US LLC in a footer** — Chinese sellers register Wyoming shells by the thousand
- ❌ A **brand name** — Bob and Brad is Chinese, Lifepro is Los Angeles
- ❌ An **email used as a KEY** — `rebecca@wayward.com` is on 10 brands; it junked a $23,345 company

**ANYTHING ELSE → QUARANTINE IT AND ASK TIM.** A novel evidence type is a question, not a finding.
`ingest_research_findings.py` enforces this: unapproved types are held and listed, never written.

### 6. A weak/inferred signal is NEVER a verdict. It goes to Tim's review queue.

### 7. Money wins. A paid invoice outranks any heuristic about who a brand is.

### 8. After EVERY write: `python scripts/check_invariants.py`. A failure means STOP.

---

# THE PLAN OF RECORD (Tim, 2026-07-14)

**PHASE 1 — FOUNDATION (now): several small consolidation waves. NOT the 549 seller records.**
**PHASE 2 — self-maintaining: ingestion correctness, deterministic recompute, LLM check-ins (design together).**
**PHASE 3 — Tim's spreadsheets: coverage check, new fields if needed, blast radius.**
**PHASE 4 — what else is missing, then Metabase / reporting.**

**THE VERDICT SEMANTICS (Tim's rule, verbatim intent):**
> "If we Are SURE they are chinese based on the indicators, any of them, they are confirmed.
> EVERYTHING else is unknown or probable. We will then do checks on all of those… KNOWN american
> and large brands, which we will flip to USA. or other countries, we flip to not china."

- **confirmed china** ← ANY approved indicator (lists, Wayward CN, Chinese mailbox, +86, CJK, QQ
  handle, shared owner mailbox, Amazon seller entity, USPTO owner, HK) or a human pin
- **probable** ← channel/name evidence only (`chinese_partner`, pinyin) → **Tim's check queue**
- **not_china** ← a human ruling or a LEGAL RECORD only. **NEVER Wayward's country flag** ("DONT
  ASSUME THAT WAYWARD DATA IS CORRECT")
- **unknown** ← nothing

# THE WAVES — full specs live in FOUNDATION-PLAN.md. Read the spec, run the protocol, STOP after each.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[T]` **blocked on Tim — do not touch**

- [x] **W0 — BASELINE.** Snapshot in `BASELINE.md`. No changes. ✅ 2026-07-14
- [x] **W1 — HONEST LABELS.** ✅ 2026-07-14 · cip_87 · zero verdict movement· The 131 tier1 rubber-stamp `manual_review` rows → `tim_batch_approval`;
      research-agent `manual_review` rows → deleted (their legal signals carry the verdict).
      **Verdicts must not move. Verify identical.**
- [x] **W2 — THE 4-STATE VERDICT.** ✅ 2026-07-14 · cip_88 · landed exactly on prediction · china / probable / not_china(human-or-legal-only) / unknown.
      Predicted: ~380 real not_china→unknown (Wayward's flag stops deciding); ~3 china→probable
      (the A4 three land at the top of Tim's probable queue). +invariant
      `not_china_requires_human_or_legal`.
- [x] **W3 — ONE HOME FOR `is_chinese`.** ✅ 2026-07-14 · cip_90 · 5,248 → 0 disagreements, $0 moved · Spine derives from the verdict; data + writer in the same
      wave. +invariant `spine_is_chinese_matches_verdict`.
- [x] **W4 — THE RATE CLOCK.** ✅ 2026-07-14 · cip_91 · 2,371 → 0 wrong, $0 moved · `+365+183` GENERATED columns → calendar months. +invariant.
- [ ] **W5 — ALIAS TRUTH.** Passthrough columns + `lens_ps_china_companies` rollup for headlines.
      Money lenses untouched (frozen).
- [ ] **W6 — SCRIPTS FULL CLEAN.** Harvest rewritten (all 24 signal/source pairs, agency guard, NO
      pinyin regexes); ingest stops writing `manual_review`; everything else → `scripts/attic/`.
- [ ] **W7 — SCHEMA CONSISTENCY BATCH.** FKs, CHECKs, pinned/superseded fix, units + comment lies.
- [ ] **W8 — SHRINK THE UNKNOWNS.** `lens_ps_china_evidence_grid` + ranked candidate report →
      **Tim flips**, nothing auto-flips.

## PHASE 2 (queued, do not start): D2 dead CIP tables · D3 freshness monitor rewrite ·
## deterministic recompute chain on the FAS rails · LLM check-in design — WITH TIM.

## Parked until Phase 1 done
- **A-track.** The 549 Amazon seller records (list + brief are ready; ingest exists and is tested).
- [T] **A4.** SZEE · Lille Home · Yoleo — Tim checks personally (now = the probable queue).
- [T] **B1.** `marketing@service908.com` — owner or shared service?
- [T] **B2.** `zhou_yintong@163.com` — agency or owner?
- [T] **B3.** RobKushner — ask Jake.
- [x] ~~Metabase~~ — Tim: later.

---

## Done this session

- [x] cip_85 — MONEY WINS. Un-junked GCI Outdoors ($23,345), VANDEL, ALTA.
- [x] cip_86 — resynced the `seen_in_*` flags (26 brands were on the exclusion list while the flag
      said false — $41,743, incl. CrownShade where another partner still earns). Killed the
      `'Jeremy  Caspar'` double space. Collapsed the chase list on `canonical_brand_id` → 511
      companies, not 517 rows.
- [x] +4 invariants (13 → 17): `money_on_a_brand_graded_junk`, `stale_seen_in_flags`,
      `china_verdict_on_a_name_guess`, `humans_live_and_opposed`.
- [x] Reverted my own bad calls: import-records flips, UNRESOLVED-as-china signals, the 3-brand drop.
