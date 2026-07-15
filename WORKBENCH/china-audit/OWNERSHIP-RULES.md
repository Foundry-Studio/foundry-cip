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
5. **Reactivation restarts the 10/6/3 rate clock, per product — the FULL ladder** (a fresh 12
   months at 10%, then 6, then 3). Only when the reactivation is ours / our partner's, with
   evidence. (Confirmed Tim, 2026-07-15.)
   **Dormancy = platform SALES:** "dormant 90d" means no platform sales for 90 days (usage/billing),
   NOT support/Zendesk activity. (Confirmed Tim, 2026-07-15.)
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
3. **"Restart the clock" is not yet expressible — and it's a FULL-ladder restart (confirmed).**
   `rate_10_expires` is GENERATED from the single `productive_date`; a qualifying reactivation must
   re-anchor the WHOLE ladder to the reactivation date (fresh 12mo@10%, then 6, then 3). Needs a
   re-anchor design (GREATEST(productive_date, qualifying_reactivation_date), or per-episode
   subscription rows). P2 design item — flagged so it isn't discovered mid-build.

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
4. **Dormancy = platform SALES (Tim, 2026-07-15) — RESOLVED.** "Dormant 90d" = no platform sales for
   90 days: usage/billing (`ps_stripe_*` / `ps_monthly_earnings`), NOT Zendesk/support activity. The
   90-day derived logic lived in a view dropped by cip_97 and is rebuilt in P2 off the SALES signal,
   not `ps_product_subscriptions.last_activity_at` (whose source was ambiguous).

### ✅ ANSWERED by Tim 2026-07-15 (encode in P2)
1. **Restart scope — YES, full ladder.** A qualifying reactivation restarts a fresh 12 months at
   10% (then 6, then 3), per product. Only when the reactivation is ours / our partner's, with
   evidence.
2. **Dormancy = platform SALES.** Not Zendesk/support. See rule 5 + correction #4 above.

### ❓ Deferred to its phase (Tim: "discuss in that phase, make a note to update the docs then")
- **Where Rhea's partner roster lives** → the partner-intake / SOP phase (P1 intake or P6).
  **TODO at that phase: get the roster's home from Tim and update this doc + PROGRAM.md.**

### 📌 P2 CARRY-IN — type the HubSpot money fields (from the 2026-07-15 schema audit; Tim: handle in P2)
Wayward's OWN stated numbers live only in `cip_deals.properties` JSONB, un-typed:
`total_fees_paid` (2,911 deals), `lifetime_usage_fees_generated` (3,473), `lifetime_gmv` (3,484),
`amazon_seller_type` (276). `total_fees_paid` is literally **what Wayward says they've paid a brand**
— the other side of P5's owed-vs-paid. **P2 action:** decide which to promote to typed columns / a
typed lens (type once, don't re-parse per consumer), as part of the math design. Full detail:
[SCHEMA-AUDIT.md](SCHEMA-AUDIT.md) Finding 1. **Do not forget this in P2.**

### 🎯 RECOVERY SCOPE — what we actually pursue (Tim, 2026-07-15)
The recovery = **our management 10% on collected usage** for China brands we manage, from the revenue
anchor (2025-10-01), MINUS what Wayward has already paid us.
- **Exclusion / flat-fee list = NOT ours.** On `ps_excluded_brands` means someone else (Eric et al.)
  is the one being paid on that brand — excluded from recovery. (A flat-fee where PS is the one paid
  is not on this list; it stays ours.)
- **Pre-cutover REFERRAL commissions: do NOT pursue.** For pre-cutover brands we manage we still
  pursue our **management 10%** from the anchor date (non-exclusion only) — not the referral piece,
  not pre-anchor revenue.
- **Post-cutover brands: fully ours** (management 10%; partner referral per the partner rules).
- **Partner payout rate = 5% default** until Rhea's roster gives real per-partner rates
  (`ps_partner_terms._default` already = 5%). When the roster lands, **review it and manually map
  oddly-named referral sources to the right partner** via `ps_partner_aliases` (like xq→kerry).
- **Lytasaur = Eric** — it's Eric's company name; same entity as partner `eric`, no deal, we do NOT
  owe. NOTE: "lytasaur" appears NOWHERE in our DB — the exclusion list + every referrer value were
  already normalized to `eric` on ingest (so it's handled correctly). Alias rows added anyway to
  future-proof any raw sheet: `lytasaur` / `Litusor` / `referral(lytasaur)` → `eric` in
  `ps_partner_aliases`. **If Tim has the exact contract spelling, add that exact alias too.**

First-order magnitude (flat 10%, data through Jun 2026; precise number = the P2 engine): non-exclusion
China management fee **still-owed ≈ $10.4k** across ~306 brands (~$9.5k pre-cutover, ~$0.8k
post-cutover). Of the 278 China brands Wayward collected on but paid $0, **111 are ours** (not on
Eric's list); 167 are Eric's (correctly excluded).
