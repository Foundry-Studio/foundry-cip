# THE RULES — the china-audit constitution

**Read before every action, on every project. These survived Phase 1's mistakes; they do not expire
when a project ends.** Extracted verbatim from ACTION-LIST.md (now archived) on 2026-07-15;
additions since are dated.

---

## STANDING RULES

### 1. ADDING evidence is my call. REMOVING it is Tim's. No exceptions.
Every error in the 2026-07-14 session was a **removal** or a **reclassification** done on my own
authority. Adding is safe and reversible. Removing is destructive.
**Enforced mechanically by `scripts/_guard.py`. Do not bypass it.**

### 2. NEVER assume Wayward's data is correct.
`wayward_country_other` ("Wayward says US") is **not evidence of anything.** A US-registered shell
reports as US — that is the entire pattern we are auditing. It may CORROBORATE. It may never
OVERRULE.

### 3. BrüMate is a ONE-OFF, not a precedent.
A Chinese partner's referral is evidence **FOR** China, not against it. Tim: *"if its chinese
referred those other brands, they are LIKELY chinese."*

### 4. NEVER accept an agent's finding without re-running its SQL myself.
Five audits were right one day. They still all got re-run. That is the deal.
(2026-07-14 corollary, from the test-triage session: an agent's failing-list is a floor, not a
ceiling; re-verify root causes by reading source myself.)

### 5. Check the KIND of evidence, not just its presence.
**An evidence TYPE Tim has not approved is not evidence. Ask him. Do not act.**

**APPROVED — act on these:**
- ✅ Who **OWNS the trademark** (USPTO / national register)
- ✅ The **Amazon seller of record** (INFORM Consumers Act business name + address)
- ✅ A **list** — exclusion list, Eric's sheet, heavy producers (definitional, per Tim)
- ✅ A **`+86` phone** · a **Chinese mailbox domain** · **CJK** in the name · a **Hong Kong entity**
  (HK = China; Macau = China; Taiwan and Singapore are NOT)
- ✅ A **Chinese company name in pinyin** (`…YouXianGongSi`)
- ✅ The brand's **own page declaring a Chinese operating address / owner** (the dwindle pattern:
  Nine Carat→Difung, SinAlpha, VVENACE, CuPiLo)

**BANNED — never act on these:**
- ❌ **Import / shipping / customs records** (Panjiva, ImportYeti) — *everyone* imports from China
- ❌ A **US LLC in a footer** — Chinese sellers register Wyoming shells by the thousand
  (30 N Gould St Sheridan WY and friends = registered-agent mail-drops, not identities)
- ❌ A **brand name** — Bob and Brad is Chinese, Lifepro is Los Angeles
- ❌ An **email used as a KEY** — `rebecca@wayward.com` is on 10 brands; it junked a $23,345 company
- ❌ A **"Made in USA" claim** — marketing, not ownership

**ANYTHING ELSE → QUARANTINE IT AND ASK TIM.** A novel evidence type is a question, not a finding.

### 6. A weak/inferred signal is NEVER a verdict. It goes to Tim's review queue.

### 7. Money wins. A paid invoice outranks any heuristic about who a brand is.

### 8. After EVERY write: `python scripts/check_invariants.py`. A failure means STOP.

---

## THE VERDICT SEMANTICS (Tim's rule, unchanged; 3-state since cip_95)

> "If we Are SURE they are chinese based on the indicators, any of them, they are confirmed.
> EVERYTHING else is unknown. We will then do checks… KNOWN american and large brands, which we
> will flip to USA. or other countries, we flip to not china."

- **china** ← ANY approved indicator or a human pin
- **not_china** ← a human ruling or a LEGAL RECORD (amazon_seller_entity / uspto_trademark_owner)
  ONLY. NEVER Wayward's country flag.
- **unknown** ← nothing decisive. Unknown is a QUEUE, never a denial; it propagates as NULL, never
  as false.

One home for every derived value: nationality lives in `ps_nationality_signals →
lens_ps_china_verdict`; `is_chinese` on the money spine DERIVES from the verdict (cip_90) —
re-derive after every flip. For any count said out loud, use `lens_ps_china_companies`
(one row per company), never the row-level lens.

---

## PROGRAM-PHASE ADDITIONS (2026-07-15, Tim)

### 9. NO ASKS TO JAKE (or anyone at Wayward) for now.
Tim supplies all new data himself (spreadsheets, lists). We review, confirm, flip. This rule stands
until Tim lifts it.

### 10. Every incoming artifact gets the FULL GUT CHECK.
Not just "is the data in the DB" — *"is there ANYTHING on here we didn't have or know — data,
fields, structure — that should adjust the system, the schema, or anything else?"* New facts enter
as ADDED evidence (pinned, provenanced, Tim-ranked). New FIELDS get a schema home only when no
existing home fits — and that's a migration with the full checkpoint protocol, not an ad-hoc column.

### 11. Stay inside this initiative.
This program is deliberately a separate PM initiative. Other PS projects/initiatives are out of
scope — do not touch them, do not reason about them.

### 12. Git discipline (carried from Phase 1, still in force).
`git branch --show-current` before staging; pathspec-scoped commits only (concurrent sessions edit
this repo); fetch origin + check for untracked sister migrations before pushing migration commits;
after reorgs check `git status --untracked-files=all`.
