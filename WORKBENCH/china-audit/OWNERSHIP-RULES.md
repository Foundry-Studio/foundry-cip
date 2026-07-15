# OWNERSHIP & DEAL RULES — settled by Tim 2026-07-14, reviewed against the schema 2026-07-15

**These are Tim's operative rulings. Where they deviate from the written contract, the contract gets
amended to match (delta → the §11 amendment list) — never the reverse.** P2 encodes them; until
then this doc is the carrier of record.

---

## THE SETTLED RULES (verbatim intent, 2026-07-14)

1. **The DEAL is the unit: brand × product**, carrying `lead_source_initial` (who brought the brand
   to this product) and `lead_source_activation` (who revived it after dormancy).
2. **Two dates, two jobs:**
   - **2025-11-18 — the freeze.** Governs onboarding/list membership ONLY (Exhibit A frozen).
   - **2025-10-01 — the anchor.** Legacy revenue start AND the reactivation window. Fact-checked:
     Jake's first report paid mostly OCTOBER usage.
3. **Connect:** post-freeze onboard = ours; non-frozen legacy = ours from Oct-2025 sales;
   contract-10% brands = incumbent's EXCEPT evidenced reactivation by us/our partner;
   flat-fee brands dormant 90d then reactivated Oct+ = ours.
4. **Boost:** flat-fee + non-frozen = ours; contract-10% = contested — evidence decides;
   **unknown defaults to the incumbent** (attribution-unknown ≠ nationality-unknown; see grain
   notes below).
5. **Reactivation restarts the 10/6/3 rate clock, per product.**
6. **Decisions PIN.** Automated evidence FLAGS, never flips a pinned decision; only a manual change
   moves one.
7. **Ambiguity → the conflicts queue → Tim.** Never silently resolved.
8. **Evidence discipline:** log every cross-sell/reactivation AT THE MOMENT it happens.
9. **Supersedes:** cip_68's blanket hands-off; RULE_B's 2025-12-01 revenue start; the 2025-11-01
   reactivation window.

---

## REVIEW vs THE LIVE SCHEMA (2026-07-15) — what's already true, what isn't

### ✅ Already encoded (verified in code, not from memory)
| rule | where it lives |
|---|---|
| Deal = brand × product, two lead sources | `ps_partner_credit.lead_source_initial / lead_source_activation / activation_evidence_ref` (cip_77) |
| Unknown activation defaults to incumbent | cip_77's own logic: `someone_else_earning AND lead_source_activation IS NULL` → incumbent. *"Silence hands the revenue to Eric."* |
| 10/6/3 clock, calendar months, per product | `ps_product_subscriptions.rate_10_expires / rate_6_expires` GENERATED from `productive_date` (cip_91) |
| Incumbent-except-evidenced-reactivation | invariants `claiming_where_someone_else_earns` + `reactivation_regression` were WRITTEN to these rules — activation evidence flips `someone_else_earning` off; the invariant polices the residue |
| Decisions pin | `ps_added_facts.pinned` + `superseded_by`, contradiction impossible since cip_93 CHECK |
| Money grain = brand × product × month | `spine_grain_unique` invariant |

### ⚠️ Corrections / stale — the important findings
1. **NO revenue-start date exists in live code at all.** The superseded 2025-12-01 RULE_B died with
   cip_97's drops (good), but the settled **2025-10-01 anchor was never encoded anywhere**. Until P2
   lands it, this document is the only carrier. Same for 2025-11-18 (comments only).
2. **The frozen snapshot's claim columns embody the SUPERSEDED law.** `ps_monthly_earnings.is_claimable`
   / `claim_basis` were computed by the now-deleted writer under RULE_B (2025-12-01) and the old
   reactivation window. **Do not read them as current truth — including for P5 v0.** P2's engine
   recomputes them under these rules.
3. **"Restart the clock" is not yet expressible.** `rate_10_expires` is GENERATED from the single
   `productive_date`; a reactivation restart needs a re-anchor (e.g. GREATEST(productive_date,
   qualifying_reactivation_date) or episode rows). P2 design item — flagged so it isn't discovered
   mid-build.

### ➕ Proposed additions (mine — Tim confirms before they become law)
1. **Grain split, stated explicitly:** MONEY grain = `wayward_brand_id × product` (a billing
   relationship); NATIONALITY grain = the company (canonical rollup). One operator running 18 brands
   = 18 deals but one nationality ruling (PARKING P3: operator-merge is right for China, wrong for
   revenue). P2 must never blend the two.
2. **The nationality gate, stated explicitly:** a deal is claimable only when the brand's verdict is
   `china`. `unknown` nationality → claim QUEUED (`unknown_nationality`), never denied and never $0
   (the cip_65/cip_72 lesson: NULL propagates).
3. **Partner-side economics are half the math.** These rules cover PS-vs-Wayward; the same deal
   grain carries partner credit (finders fee, `credit_start/credit_end`, `partner_credit_expires`).
   P2's engine computes both sides; P6's SOPs govern changing them.
4. **Dormancy needs a definition ruling.** "Dormant 90d" reads from
   `ps_product_subscriptions.last_activity_at`; the 90-day derived logic lived in a view dropped by
   cip_97 and must be rebuilt in P2. What SOURCES feed `last_activity_at` (usage only? Zendesk
   activity?) is an open Tim question from 2026-07-14 — still unanswered.

### ❓ For Tim, when convenient (P2 blockers, not today's)
1. **Restart scope:** does a qualifying reactivation restart the FULL ladder (new 12 months at 10%)?
   And only when the reactivation is ours/our-partner's with evidence — correct?
2. **Dormancy source:** what counts as activity (Zendesk-as-dormancy scope, pending since 07-14)?
3. Where does Rhea's partner roster live? (P1/P6 intake.)
