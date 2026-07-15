# PROGRAM — Wayward China Commission: Recovery & Ongoing

**The read-first map for everything after Phase 1.** One page: where we are, the projects, what's
decided, what waits on Tim. Rules live in [RULES.md](RULES.md) — read those before acting.
Live parked discoveries: [PARKING.md](PARKING.md). Phase-1 history: [archive/](archive/).

- **PM initiative:** `Wayward China Commission — Recovery & Ongoing` (`be0bede6-7f33-4681-af1f-c5d1afcc83f4`) —
  **deliberately separate from every other PS initiative. Other PS work is out of scope for this program.**
- Projects are created in PM **at kickoff only** — no pre-written task lists to go stale (Tim,
  2026-07-15: "clean context and no drifting").

---

## CURRENT TRUTH — 2026-07-15

- **The book (REAL companies): china 1,600 · not_china 310 · unknown 652.** All 652 unknowns carry a
  next_step in `lens_ps_china_evidence_grid`. 3-state verdict since cip_95 (probable retired).
- **Schema:** alembic head `cip_97_remove_nationality_system`. Phase-1 foundation = cip_87→cip_94
  (honest labels, 4→3-state verdict, is_chinese one home, calendar months, company rollup, FKs/CHECKs,
  evidence grid). Old cip_clients nationality system + 4 dead views REMOVED (cip_97).
- **Money:** `ps_monthly_earnings` is a STATIC SNAPSHOT (as of 2026-07-14) — the broken writer was
  retired (cip_97 commit e5c213f). Raw Stripe facts (`ps_stripe_*`) live and syncing hourly. The
  replacement engine is P2's deliverable. **Money/claims work stays frozen until P2.**
- **Invariants: 21/21 hold** (`scripts/check_invariants.py`). Post-cip_97 hourly syncs verified green.
- **Metabase:** connection + role intact; cards built on the 4 dropped views error until P4 rebuilds.

## THE PROJECTS

| # | project | PM id | status | one-liner |
|---|---------|-------|--------|-----------|
| P0 | Program Hygiene & Setup | `959a0019` (WCC0) | **active** | This structure; archive Phase-1 docs; backup posture; attic when quiescent |
| P1 | Raw Data Confirmation & Schema | `2b81922a` (WCC1) | backlog — next | Tim's spreadsheets → gut check → confirm/flip; WeChat + multi-contact; identity spine; 549 seller records; residue |
| P2 | Math Plan & Money Engine Rebuild | — | not created | Propose ALL calculated fields → Tim confirms → BUILD the live recompute engine on rails (data+writer same wave) |
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

## P1 KICKOFF NOTES (Tim's braindump — riff at kickoff, not before)

- Jake sent Tim a **WeChat list** → needs WeChat contact fields + matching users to wechat info.
- Likely need **2+ contacts per company** (multiple employees: different names, emails, wechat).
  `ps_brand_contacts` is already row-per-contact; the design question is person-identity across
  email/wechat/name-spelling, and how contacts rank (owner vs employee vs agency).
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
