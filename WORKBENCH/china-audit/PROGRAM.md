# PROGRAM — Wayward China Commission: Recovery & Ongoing

**The read-first map for everything after Phase 1.** One page: where we are, the projects, what's
decided, what waits on Tim. Rules live in [RULES.md](RULES.md) — read those before acting.
Tim's settled deal/money rules + schema review: [OWNERSHIP-RULES.md](OWNERSHIP-RULES.md) (P2's spec
seed; note the frozen snapshot's `is_claimable`/`claim_basis` embody SUPERSEDED law — never read as
current). Live parked discoveries: [PARKING.md](PARKING.md). Phase-1 history: [archive/](archive/).

- **PM initiative:** `Wayward China Commission — Recovery & Ongoing` (`be0bede6-7f33-4681-af1f-c5d1afcc83f4`) —
  **deliberately separate from every other PS initiative. Other PS work is out of scope for this program.**
- Projects are created in PM **at kickoff only** — no pre-written task lists to go stale (Tim,
  2026-07-15: "clean context and no drifting").

---

## CURRENT TRUTH — 2026-07-16

- **The book:** china / not_china / unknown — **live counts in `lens_ps_china_companies`** (moves with
  each flip; don't hard-code). 3-state verdict since cip_95. Grew via the July intake sheets + the
  Amazon seller-of-record / internal-breadcrumb triage (see SUSPECTS-IN-CONTENTION.md); unknowns
  queued in `lens_ps_china_evidence_grid`.
- **Schema:** alembic head **`cip_109_reporting_lenses`**. Phase-1 = cip_87→94. **Money engine =**
  cip_104 (commission ledger, lens-first) · cip_105 (per-product eligibility) · cip_106 (Wayward
  client fee rate) · cip_107 (ledger→per-product rewire) · cip_108 (Wayward reconciliation lens) ·
  cip_109 (reporting lenses: aging / partner-payout / monthly / excluded-partner / wayward-stated).
- **Money: LIVE, not frozen.** The engine is `lens_ps_commission_ledger` → `lens_ps_claim`,
  self-updating off hourly Stripe. **Recovery ≈ $12,035** — the canonical number lives in
  `lens_ps_claim`; see [LENS-CATALOG.md](LENS-CATALOG.md). The frozen `ps_monthly_earnings` is legacy
  (the ledger no longer depends on it); retiring the old writer is cleanup, not a gate. Payments
  Dec-2025→Jun-2026 reconciled in `ps_payment_events`; partner payouts in `ps_partner_payouts`.
- **Ownership:** china is the only gate; eligibility is **per product** (cip_105/107) — the pre-PS
  rev-share exclusion is Connect-only, so Boost is ours. Full rules: [OWNERSHIP-RULES.md](OWNERSHIP-RULES.md);
  what-each-lens-answers + glossary: [LENS-CATALOG.md](LENS-CATALOG.md).
- **Invariants: 25/25 green** (`scripts/check_invariants.py`, re-run 2026-07-16 post-cip_109).
- **Metabase:** the cip_104–109 lenses are the read-surface; wiring cards is the next reporting step.

## THE PROJECTS

| # | project | PM id | status | one-liner |
|---|---------|-------|--------|-----------|
| P0 | Program Hygiene & Setup | `959a0019` (WCC0) | **done** | Structure built; Phase-1 docs archived; rules re-grounded 2026-07-15 |
| P1 | Raw Data Confirmation & Schema | `2b81922a` (WCC1) | **active — mostly done** | Overdue + WeChat sheets ingested; WeChat + multi-contact (cip_100); payments reconciled Dec–Jun; hygiene (cip_98/99); partner ledger (cip_101/102); flat-fee labels (cip_103). RESIDUE: identity spine, 549 seller records, HOLDS below |
| P2 | Math Plan & Money Engine Rebuild | — | **BUILT (cip_104–109), live + self-updating** | Commission engine (cip_104), per-product eligibility (cip_105), Wayward client fee rate (cip_106), ledger→per-product rewire (cip_107), Wayward reconciliation lens (cip_108), reporting lenses (cip_109: aging/partner-payout/monthly/excluded-partner/wayward-stated). Ongoing "what's owed this month" tool; lens map = [LENS-CATALOG.md](LENS-CATALOG.md). Recovery $12,035. REMAINING: backfills, retire ps_monthly_earnings writer, partner-side reconciliation on Rhea's roster |
| P3 | Ingest Automations | — | not created | Design source pulls, code-vs-LLM review checkpoints (Tim has ideas); governance gate applies to any MCP write tools |
| P4 | Metabase Dashboards | — | not created | Layers, permissions, design; Metabase as base + possibly a smoother layer on top (Tim); card inventory first |
| P5 | Owed vs Paid — Claim & Evidence | — | not created | Live owed-vs-paid; the KNOWN-Chinese-but-uncredited list (their HubSpot flag + payment sheets vs our book); pinned as-of statements |
| P6 | SOPs & Ongoing Ops (v1: manual via MCP) | — | not created | Health checks; reporting (PS internal, Wayward China, partners); change SOPs (partner rates, brand×product attribution) |
| P7 | Twenty CRM Integration | — | not created | The CRM becomes the update surface; big design project, planned on its own |

**Sequencing:** P0 → P1 → P2 → (P3 ∥ P4) → P5 → P6 → P7.
P5 can ship a v0 (HubSpot-flag discrepancy list) during P2 — the flag comparison needs no money math.

## DECISIONS OF RECORD (this program)

| date | decision |
|------|----------|
| 2026-07-15 | **Live math, not frozen.** The money engine recomputes owed-vs-paid continuously as data changes. "Frozen" was only the interim safety state after retiring the broken writer. The ONE deliberate freeze: claim **statements** handed to Wayward are pinned as-of copies (bank statement vs live balance) so the number can't shift mid-negotiation. |
| 2026-07-15 | **No asks to Jake/Wayward for now** — Tim supplies all new data (RULES #9). |
| 2026-07-15 | **Separate initiative**, other PS work untouched and out of mind (RULES #11). |
| 2026-07-15 | **Metabase = base layer**; possibly a smoother consumption layer on top — design deferred wholly to P4. |
| 2026-07-14 | Any future MCP write tools go through the tool-creation contract + FAS/JOS governance (committed note, FOUNDATION-PLAN §governance — carried into P3/P6). |
| 2026-07-14 | Metabase DB role stays live (severing it breaks the tested read-role contract); broken cards are repaired app-side in P4. |
| 2026-07-15 | **Ownership = "is anyone else paid on this brand?"**, not raw list membership. Flat-fee-era-Eric brands = OURS from the first billing-sheet cycle (2025-12-01); genuinely-excluded = partner-earning buckets (Eric Rev Share, Heavy Producer, Jeremy Caspar, Shallow, OpenLight, OceanWing). Encoded cip_103 (`disposition` + `ours_revenue_from`). Spec: OWNERSHIP-RULES.md. |
| 2026-07-15 | **Pre/post-cutover is a vanity gut-check ONLY** — never reported, never changes handling; a china brand we own is ours regardless of which side of the freeze it signed up on. |
| 2026-07-15 | **Partner payout rate = 5% default** until Rhea's roster (then review + map odd-named referral sources via `ps_partner_aliases`). **Lytasaur = Eric** — already normalized to `eric` in-DB. |

## P1 KICKOFF NOTES (Tim's braindump — riff at kickoff, not before)

- Jake sent Tim a **WeChat list** → needs WeChat contact fields + matching users to wechat info.
- **Brand-company contacts (NEW schema work, P1)** — the people we talk to AT the brand. Need at
  least TWO contact slots, each **name + email + WeChat**: (1) our primary contact — often the
  official person who signed up to Wayward; (2) a second employee, since we get additional info from
  them. `ps_brand_contacts` is row-per-contact already but has **no WeChat field and no
  primary/secondary role** — that's the P1 add. (Jake's WeChat list is the first data for this.)
- **Partner attribution is SEPARATE and already per-PRODUCT** — do NOT conflate it with brand
  contacts. One partner can be the lead source for Connect, another for Boost; that's
  `ps_partner_credit` keyed by brand×product (`lead_source_initial`/`activation`). No schema change,
  just the discipline of keeping the two models apart.
- Some artifacts are pure confirmation, some carry new data — every one gets the RULES #10 gut check.
- Fold in: PARKING P3 (identity spine policy — operator vs company merge is TIM'S call),
  the 549 seller records (blocked on Q0 ruling below), the lost batch-7 chunk (20 brands,
  usa7_chunk_3.txt — re-runnable), retiring PARKING P1's 116 propagation rows.

## ⏳ HOLDS — waiting on Tim (do not act without his ruling)

1. **Solid Gold** — real US pet-food brand (Chesterfield MO), parent = Hong-Kong-listed H&H Group
   ($163M acquisition). HK=China by rule, but this is a genuine US operating brand with an HK parent,
   not a shell. Does the parent's nationality flip it? (Symmetric case: Kate Farms left not_china
   under French majority owner Danone.)
2. **NORDMOND** — conflicted: one batch says likely-China; another found a Romanian privacy-policy
   entity (NORDMOND STORE LLC, Bucharest) but self-flagged it thin.
3. **Intent Brands** — leans not_china (named founder Janco Bronkhorst, US LLC holds trademarks);
   held only because its sole address is a Sheridan WY mail-drop.
4. **Q0 — what clears a brand via the 549 seller records?** Proposed: trademark owner AND Amazon
   seller of record name the SAME entity, non-China country, REAL street address (not a
   registered-agent drop). Blocks the A-track ingest. (Full detail: archive/QUESTIONS-FOR-TIM.md.)
5. **Q1 — `marketing@service908.com`**: one owner or shared service? (4 billing brands ride on it.)
6. **Q2 — `zhou_yintong@163.com`**: agency or owner? (18 brands; migrations describe it both ways.)
7. *(Deferred by RULES #9, not waiting:)* Q3/RobKushner (needed a Jake ask) · the 652-unknown
   seller-of-record enrichment (was the "Jake list").
