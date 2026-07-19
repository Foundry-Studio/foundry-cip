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
- **Schema:** alembic head **`cip_113_refund_netting`** (cip_111 Stripe live-sync + refund/CN tables ·
  cip_112 statement-drift lens · cip_113 collected = net of refunds). Phase-1 = cip_87→94. **Money engine =**
  cip_104 (commission ledger, lens-first) · cip_105 (per-product eligibility) · cip_106 (Wayward
  client fee rate) · cip_107 (ledger→per-product rewire) · cip_108 (Wayward reconciliation lens) ·
  cip_109 (reporting lenses: aging / partner-payout / monthly / excluded-partner / wayward-stated) ·
  cip_110 (**retired the frozen `ps_monthly_earnings` snapshot** — the last tie to the old writer).
- **Money: LIVE, not frozen.** The engine is `lens_ps_commission_ledger` → `lens_ps_claim`,
  self-updating off hourly Stripe (LIVE hourly since 2026-07-17). **Recovery ≈ $13,713** (net of
  refunds; grew from $12,035 as the live sync recovered $254k of truncated usage) — the canonical number lives in
  `lens_ps_claim`; see [LENS-CATALOG.md](LENS-CATALOG.md). **The frozen `ps_monthly_earnings` snapshot
  is GONE (cip_110)** — every lens/invariant/script that touched it was repointed to the live spine or
  retired; recovery + china headcount verified penny/row-identical before and after. The 16,020-row
  snapshot is archived at `archive/ps_monthly_earnings_frozen_snapshot.csv.gz` (audit baseline).
  Payments Dec-2025→Jun-2026 reconciled in `ps_payment_events`; partner payouts in `ps_partner_payouts`.
- **Ownership:** china is the only gate; eligibility is **per product** (cip_105/107) — the pre-PS
  rev-share exclusion is Connect-only, so Boost is ours. Full rules: [OWNERSHIP-RULES.md](OWNERSHIP-RULES.md);
  what-each-lens-answers + glossary: [LENS-CATALOG.md](LENS-CATALOG.md).
- **Invariants: 22/22 green** (`cip/integration_mesh/ps_invariants.py`, re-run 2026-07-18 post-cip_113
  on **prod**). 21 after cip_110's repoint/retire/rewrite; +1 in cip_113
  (`refund_alloc_never_exceeds_gross`, guards the refund-netting cap).
- **Metabase:** the cip_104–109 lenses are the read-surface; wiring cards is the next reporting step.

## THE PROJECTS

| # | project | PM id | status | one-liner |
|---|---------|-------|--------|-----------|
| P0 | Program Hygiene & Setup | `959a0019` (WCC0) | **done** | Structure built; Phase-1 docs archived; rules re-grounded 2026-07-15 |
| P1 | Raw Data Confirmation & Schema | `2b81922a` (WCC1) | **done** | Overdue + WeChat sheets ingested; WeChat + multi-contact (cip_100); payments reconciled Dec–Jun; hygiene (cip_98/99); partner ledger (cip_101/102); flat-fee labels (cip_103). Residue folded → P3 Phase C (549), P7 (identity spine), HOLDS resolved |
| P2 | Math Plan & Money Engine Rebuild | `bfdcc15c` (WCC2) | **done — BUILT (cip_104–113), live + self-updating** | Commission engine (cip_104), per-product eligibility (cip_105), Wayward fee rate (cip_106), ledger→per-product (cip_107), reconciliation lens (cip_108), reporting lenses (cip_109), frozen snapshot retired (cip_110), Stripe live-sync + refund/CN tables (cip_111), statement-drift lens (cip_112), **collected = net of refunds (cip_113)**. Recovery ≈$13,713. REMAINING: partner-side reconciliation on Rhea's roster |
| P3 | Ingest Automations | `b7978b92` (WCC3) | **active — building** | Plan of record: [AUTOMATIONS-PLAN.md](AUTOMATIONS-PLAN.md) (Opus-reviewed GO-WITH-FIXES, folded). Build = Opus agents, Fable QC (Tim 2026-07-17). **Tim (2026-07-16): automate the missing-info feeds so accuracy stops depending on manual loads.** Concrete streams that arrive by hand today and need pipelines: (1) Amazon **seller-of-record** enrichment (the 549 + 652 unknown-nationality queue); (2) **Wayward client fee rate** per brand×product (feed-first from HubSpot deal props, CRM override) — feeds `wayward_client_fee_rate`; (3) **partner rates** from Rhea's roster → `ps_partner_credit`/`ps_partner_aliases`; (4) **WeChat** contact lists (Jake) → `ps_brand_contacts`; (5) **payment reports** (the Dec–Jun sheets were hand-loaded → `ps_payment_events`). Design source pulls + code-vs-LLM review checkpoints (Tim has ideas); governance gate applies to any MCP write tools |
| P4 | Reporting Frontend (was "Metabase Dashboards") | `b3efe08b` (WCC4) | **planned — [REPORTING-FRONTEND-PLAN.md](REPORTING-FRONTEND-PLAN.md)** | **PIVOT 2026-07-18: build a custom Next.js frontend on the lenses; RETIRE Metabase for PS money reporting** (keep for other CIP for now). 10 operational-pipeline screens (Overview · Revenue/Billing · Collections · What-Wayward-Owes-Us [recon blended] · Payments-In · Partners · Brand&Product Perf · Brand-360 · Exceptions · Statements) + Refunds/DataHealth/Excluded. Lands at `reports.project-silk.com`, Railway/Project-Silk, Google OAuth, zh/en i18n, no Metabase Pro. Reports = FAS-scheduled (independent). Build not started |
| P5 | Owed vs Paid — Claim & Evidence | `53fd8958` (WCC5) | **backlog (in PM)** | Live owed-vs-paid; the KNOWN-Chinese-but-uncredited list (their HubSpot flag + payment sheets vs our book); pinned as-of statements |
| P6 | SOPs, Ongoing Ops & Automated Reporting | `73daddfa` (WCC6) | **backlog (in PM)** | Health checks; automated reporting (PS internal, Wayward China, partners — design session); change SOPs (partner rates, attribution, rulings) |
| P7 | Twenty CRM Integration | `1984ad2c` (WCC7) | **backlog (in PM)** | The CRM becomes the update surface + identity spine home; big design project, planned on its own |

**Sequencing:** P0 → P1 → P2 → (P3 ∥ P4) → P5 → P6 → P7.
P5 can ship a v0 (HubSpot-flag discrepancy list) during P2 — the flag comparison needs no money math.

## DECISIONS OF RECORD (this program)

| date | decision |
|------|----------|
| 2026-07-15 | **Live math, not frozen.** The money engine recomputes owed-vs-paid continuously as data changes. "Frozen" was only the interim safety state after retiring the broken writer. The ONE deliberate freeze: claim **statements** handed to Wayward are pinned as-of copies (bank statement vs live balance) so the number can't shift mid-negotiation. |
| 2026-07-15 | **No asks to Jake/Wayward for now** — Tim supplies all new data (RULES #9). |
| 2026-07-15 | **Separate initiative**, other PS work untouched and out of mind (RULES #11). |
| 2026-07-15 | ~~**Metabase = base layer**; possibly a smoother consumption layer on top — design deferred wholly to P4.~~ **SUPERSEDED 2026-07-18 (below).** |
| 2026-07-18 | **P4 = custom reporting frontend; RETIRE Metabase for Project Silk money reporting.** The engine is the CIP lenses, not Metabase (Metabase was only ever a viewer). Custom Next.js on the lenses (trader-dashboard pattern), read-only role, `reports.project-silk.com`, Railway/Project-Silk, Google OAuth, zh/en i18n. **No Metabase Pro** (row-level isolation + branding + i18n are the reasons for custom; Pro's $575/mo row-sandboxing declined). Metabase **kept for now for other CIP things**, relocated off reports.project-silk.com; its old money cards (on the dropped `ps_monthly_earnings`) are abandoned not repaired. Accounts: treckrg@gmail.com (Tim/admin), samantha/rhea/james/sheila/van @project-silk.com. Plan: REPORTING-FRONTEND-PLAN.md. |
| 2026-07-18 | **Automated reports are independent of the frontend** — FAS-scheduled jobs off the lenses (Wayward China statement monthly; per-partner statements; optional internal digest), not Metabase subscriptions. Sent at set times to set people. |
| 2026-07-14 | Any future MCP write tools go through the tool-creation contract + FAS/JOS governance (committed note, FOUNDATION-PLAN §governance — carried into P3/P6). |
| 2026-07-14 | Metabase DB role stays live (severing it breaks the tested read-role contract). ~~broken cards are repaired app-side in P4~~ → **SUPERSEDED 2026-07-18: Metabase money cards are ABANDONED (superseded by the custom frontend), not repaired.** Role stays for the retained-for-CIP Metabase. |
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

**✅ RESOLVED 2026-07-16 (Tim's rulings, encoded in `scripts/manual_china_review_2026_07_16.py`,
applied to prod, verdicts = not_china/human):**
1. ~~**Solid Gold**~~ → **not_china** (US operating brand; HK-listed parent doesn't flip it, cf. Kate
   Farms under Danone).
2. ~~**NORDMOND**~~ → **not_china** (Tim's call over conflicted signals).
3. ~~**Intent Brands**~~ → **not_china** (named founder + US trademark owner outweigh the WY mail-drop;
   was already not_china/human).

**Still open:**
4. **Q0 — what clears a brand via the 549 seller records?** Proposed: trademark owner AND Amazon
   seller of record name the SAME entity, non-China country, REAL street address (not a
   registered-agent drop). Blocks the A-track ingest. **Review list built 2026-07-16:**
   [SELLER-RECORDS-549.md](SELLER-RECORDS-549.md) — 548 brands, **413 still `unknown` AND billing
   (~$82.7k collected)** = the priority queue. All kept `unknown` (Tim: "think about next step").
**✅ RESOLVED 2026-07-18 (investigation, no ruling needed — both already settled):**
5. ~~**Q1 `marketing@service908.com`**~~ — 10 brands, **all already `china`** (eric_sheet /
   exclusion_list / shared_owner_mailbox / tim_batch; one is literally "DongGuanShiHengHengYuMaoYi…
   GongSi"). No distinct websites → looks like **one Chinese owner** operating several brands. The
   owner-vs-agency question doesn't change any verdict (all china via independent signals) — it's an
   identity-grouping nuance for the future identity spine, not a money/claim blocker.
6. ~~**Q2 `zhou_yintong@163.com`**~~ — 18 brands, **all already `china`** (163.com = Chinese email
   domain + eric_sheet). **9 distinct Amazon storefronts → it's an AGENCY/service**, not one owner.
   Same conclusion: nationality settled; grouping is identity-spine only, no money impact.

**Still open:**
7. **Q0 — the 549 clearance rule** (above) — the real remaining decision + the $94k opportunity queue.
8. *(Deferred by RULES #9, not waiting:)* Q3/RobKushner · the 652-unknown seller enrichment.
9. **Identity-spine nuance (parked):** shared-mailbox operators (service908 = owner, 163 = agency) —
   whether to merge same-owner brands into one company affects headcount only. Fold into P7/identity.
