# MATH-SPEC — the money engine, every calculated field (P2 Phase A → BUILT)

**Status (2026-07-15): BUILT — cip_104 shipped the lens stack (`lens_ps_rate_schedule` →
`lens_ps_commission_ledger` → `lens_ps_claim` + `ps_claim_statements`), reconciled to the penny,
25/25 invariants + tests green.** REMAINING: the on-rails swap (retire `ps_monthly_earnings` writer +
repoint consumers — the ONE shared-contract step, gated for Tim); `lens_ps_wayward_stated` (deferred,
needs the cip_deals→brand mapping); partner-side reconciliation when Rhea's roster lands.
Design-first, per the approved P2 plan. The frozen snapshot (`ps_monthly_earnings`) stays untouched
until the new engine is proven, then we swap on rails (data + writer same wave). Rules of record live
in [OWNERSHIP-RULES.md](OWNERSHIP-RULES.md) and [RULES.md](RULES.md); this doc turns them into fields.

**The grain of everything below: `wayward_brand_id × product_id × period_month`** (the
`spine_grain_unique` invariant). Company-level numbers roll up on
`COALESCE(canonical_brand_id, wayward_brand_id)`.

---

## 0. PRECHECK RESULTS (2026-07-15, read-only) — the three inputs the math stands on

| input | finding | verdict |
|---|---|---|
| **Identity spine** | 5,353 brands; only **1** canonical id has >1 money-bearing brand row; 107 merged companies but the rest are 1:1 in money; 4,501 NULL-canonical are their own 1:1 entities | **SAFE** — roll up on `COALESCE(canonical, wayward_brand_id)`; flag the 1 merge (§7 edge cases) |
| **Rates / ladder** | `ps_product_subscriptions`: 2,829/2,834 carry `productive_date` + `rate_10/6_expires`; 361 `reactivated_at`. `ps_partner_terms`: default-only (5%). `ps_partner_credit`: 18 real partners | **READY** — build with 5% default, re-run when Rhea's roster lands |
| **Stripe spine + HubSpot** | `ps_stripe_invoice_lines` carries amount/invoice_status/billing_month/product_id/fee_type/is_ps_base/brand. HubSpot `total_fees_paid` 2,911, `lifetime_usage_fees_generated` 3,473 | **READY** — engine reads Stripe, not the frozen snapshot |

---

## 1. THE WATERFALL — layer by layer

Each layer is a field (or set) at the brand×product×month grain. `→` reads "flows into".

### L1 · `usage_accrued` — client usage before Wayward invoices it
- **Formula:** *(does not exist yet)*. Jake ask (DATA-WE-NEED). Wayward reconciles at invoice time.
- **Now:** engine starts at L2 (billed). Column reserved, NULL until the accrued feed exists.
- **OLD vs NEW:** unchanged (never existed).

### L2 · `usage_billed` — what Wayward invoiced the client
- **Grain:** brand×product×month. **Source:** `ps_stripe_invoice_lines`.
- **Formula:** `Σ amount WHERE fee_type = 'usage' AND is_ps_base = false`, grouped by
  `wayward_brand_id, product_id, billing_month`. (SaaS/base fees excluded — commission is on usage.)
- **Edge:** currency is USD across the spine (confirm in build); credit-note/negative lines net in.

### L3 · `usage_collected` — what the client actually PAID Wayward *(the commission base)*
- **Formula:** L2 restricted to `invoice_status = 'paid'`.
- **Why it's the base:** the deal is "10% of **collected** usage" — we bill Wayward on realized cash,
  not on what they invoiced but never collected.
- **OLD vs NEW:** the frozen `ps_monthly_earnings.usage_collected` was this same idea but computed
  once (2026-07-14) and never refreshed. NEW = recomputed live from Stripe every run.

### L4 · `ps_mgmt_fee_owed` — **what Wayward owes us** (the core field)
- **Formula:** `usage_collected × mgmt_rate(brand, product, month)` — but ONLY when the brand is
  **ours** and **claimable**. Three gates modulate it (§2):
  1. **Nationality gate** — brand verdict must be `china` (unknown → computed but flagged, never $0).
  2. **Ownership gate** — brand is ours (never-listed OR `flat_fee_era_eric`); and only for months
     `>= ours_revenue_from` (never-listed 2025-10-01, flat-fee 2025-12-01). Genuinely-excluded → 0.
  3. **Rate ladder** — `mgmt_rate` steps 10% → 6% → 3% by the ladder dates (§2.3).
- **OLD vs NEW:** OLD writer used RULE_B's 2025-12-01 blanket start + the old reactivation window and
  wrote `is_claimable`/`claim_basis` under superseded law. **NEW** = the two settled revenue-starts,
  the full-ladder restart, and disposition-aware ownership. This is the field that moves most.

### L5 · `wayward_paid_us` — what Wayward actually paid us
- **Grain:** brand×product×month. **Source:** `ps_payment_events` (`rev_share_stated`).
- **Formula:** `Σ rev_share_stated` grouped to the grain (payment sheets are per-brand per-month).
- **Cross-check (not a source):** HubSpot `total_fees_paid` = Wayward's *own stated* paid number →
  a reconciliation column `wayward_stated_paid`, never the primary (§4).

### L6 · `partner_fee_owed` — what WE owe the partner
- **Formula:** `usage_collected × partner_rate(partner, product, month)` for brands with a
  `partner_of_record` (from `ps_partner_credit`, per product), within the partner's credit window
  (`credit_start`..`credit_end` / `partner_credit_expires`).
- **Rate:** `ps_partner_terms` — 5% default until Rhea's per-partner rows land. Carved FROM our 10%
  pool (PS nets `mgmt_fee_owed − partner_fee_owed`), not added on top.
- **Edge:** eric/adina/lytasaur = no deal → `partner_fee_owed = 0` (tracked for reporting, §4).

### L7 · `partner_paid` — what we actually paid the partner
- **Source:** `ps_partner_payouts` (cip_101). `Σ amount_paid` to the grain.

### L8 · the CLAIMS (net)
- `ps_claim_owed = ps_mgmt_fee_owed − wayward_paid_us` (floored at 0 per brand; overpay is $0, not
  negative — never offsets other brands).
- `partner_claim_owed = partner_fee_owed − partner_paid`.
- `ps_net = mgmt_fee_owed − partner_fee_owed` (our retained share before/after Wayward pays).
- **Pinned statements:** a claim handed to Wayward is a frozen as-of copy (Decision of Record
  2026-07-15) — a snapshot table `ps_claim_statements`, not the live number.

---

## 2. THE MODULATING RULES (precise)

### 2.1 Nationality gate
`china` → claimable. `unknown` → compute the number but set `claim_status='unknown_nationality'`
(QUEUED, never denied, never $0 — the cip_65/72 lesson: NULL propagates). `not_china` → not claimable
(`mgmt_fee_owed = 0`, `claim_status='not_china'`). Verdict from `lens_ps_china_verdict`.

### 2.2 Ownership + revenue-start
| cohort | ours? | revenue counts from |
|---|---|---|
| never on the exclusion list | yes | **2025-10-01** (anchor) |
| `disposition='flat_fee_era_eric'` (582) | yes | **2025-12-01** (`ours_revenue_from`, first sheet) |
| `disposition='excluded'` (235, partner earns) | **no** | — (`mgmt_fee_owed = 0`) |

`lens_ps_exclusion_status.takeable` already computes the ours/not boolean; the per-row
`ours_revenue_from` (cip_103) supplies the date. Months before the applicable start → 0.

### 2.3 Rate ladder (10/6/3), per brand×product
- `mgmt_rate(month)` = 10% while `month <= rate_10_expires`; 6% while `<= rate_6_expires`; else 3%.
- Dates GENERATED from `productive_date` (cip_91).
- **Full-ladder restart** on qualifying reactivation: when `reactivation_qualifies` and the
  reactivation is ours/our-partner's, re-anchor the WHOLE ladder to `reactivated_at`
  (fresh 12mo@10% → 6 → 3). Implement as `effective_anchor = GREATEST(productive_date,
  qualifying_reactivated_at)` feeding the ladder dates. (OWNERSHIP-RULES correction #3.)
- **Flat-fee-era brands:** ladder still applies, but the clock starts no earlier than 2025-12-01.

### 2.4 Dormancy (feeds reactivation)
"Dormant 90d" = **no platform SALES** for 90 days (usage/billing signal), NOT Zendesk. Rebuilt off
the sales signal, not `last_activity_at` (ambiguous source). (OWNERSHIP-RULES correction #4.)

---

## 3. ARCHITECTURE DECISION — LENS-FIRST (decided 2026-07-15; Tim delegated the call)

**Decision: a pure view stack. No materialized objects in v1.** Reasoning:

- **Intent is decisive.** Decision of Record = "live math, not frozen — recompute continuously." We
  retired the old writer *because* a compute-to-a-table went stale and embodied superseded law with
  nobody noticing. A materialized table / scheduled writer reintroduces that exact failure mode (a
  REFRESH lags or fails silently; the number looks authoritative while stale) — our recurring failure
  class (old writer, corsair zombie: "computed once, looks current, isn't"). A view is derived on read
  and structurally cannot go stale.
- **Proven, not asserted.** The collected formula, recovered from the retired writer's git history, was
  reconciled against the frozen snapshot: **every historical month ties to the penny** (2025-10 …
  2026-06); the only delta is **+$1,781 of NEW collections since the 2026-07-14 freeze** — the lens is
  already MORE correct than the snapshot after one day. That +$1,781 is the whole argument, concrete.
- **SQL-expressible.** Collected = `Σ amount FILTER(invoice_status='paid')` over `is_ps_base AND
  product_id NOT NULL AND wayward_brand_id NOT NULL`, grouped brand×product×billing_month. Ladder =
  CASE on stored dates (`productive_date +12mo → 10%`, `+18mo → 6%`, else 3%). Reactivation re-anchor =
  `GREATEST(productive_date, qualifying_reactivated_at)`. No procedural logic → no writer needed.
- **Performance is not a real cost** at tens-of-thousands of rows (server-side, sub-second; Metabase
  queries views fine). IF a P4 dashboard is *measured* slow → wrap the FINAL lens in a
  `MATERIALIZED VIEW` + scheduled `REFRESH`: additive, no redesign. Escape hatch, not architecture.
- **The one thing that MUST freeze** — a claim handed to Wayward — is a SEPARATE snapshot table
  `ps_claim_statements` (SELECT the live lens INTO a pinned as-of row at statement time). Lens-first
  separates *live truth* (lens) from *pinned statement* (snapshot); a materialized ledger blurs them.
- **Testability:** insert known facts → assert derived output; deterministic, no refresh timing.

**Objects (all views except the one table):** `lens_ps_rate_schedule` (re-anchored ladder) →
`lens_ps_commission_ledger` (waterfall L2–L8) → `lens_ps_claim` (net, china-gated);
`lens_ps_wayward_stated` (typed HubSpot cross-check); **`ps_claim_statements`** (the one table —
pinned as-of claims). `ps_monthly_earnings` stays as-is until the lens reconciles, then the writer
retires + consumers repoint — the **on-rails swap, the ONE shared-contract step, gated for Tim.**

**Recovered exact collected formula (validated):** `is_ps_base AND invoice_status='paid' AND
product_id IS NOT NULL AND wayward_brand_id IS NOT NULL AND billing_month IS NOT NULL`, `Σ amount`
grouped brand×product×billing_month. Billed = same base, status IN ('paid','open') (voids/uncollectible
excluded — a void was never billed). Partner note: `deal_type='flat_fee'` partners earn NOTHING
ongoing (rate 0 regardless of `partner_rate`).

---

## 4. THE HUBSPOT MONEY FIELDS (Decision B — typed lens)
Per your approval: a **cast-once typed lens** `lens_ps_wayward_stated` exposing `total_fees_paid`,
`lifetime_usage_fees_generated`, `lifetime_gmv` as typed numerics out of `cip_deals.properties`
JSONB — reversible, no data duplication. Used ONLY as a reconciliation cross-check against L5
(`wayward_paid_us`), never as the primary paid number. Discrepancy (their stated vs our
sheet-derived) becomes a reportable column — and is itself part of the recovery evidence.

## 4b. Partners we DON'T owe (reporting only)
eric / adina / lytasaur(=eric): `partner_fee_owed = 0`, but we still surface the *hypothetical*
number (`partner_fee_hypothetical`) so you can see "what a deal with them would have cost." Requested
in your rundown; it's a display field, never a payable.

---

## 5. NEW INVARIANTS (police the engine; added with the build)
1. `mgmt_fee_owed >= 0` always; `= 0` when `not_china` or `disposition='excluded'` or month < start.
2. `claimable ⇒ verdict='china'` (nationality gate holds).
3. `mgmt_rate ∈ {0.10, 0.06, 0.03}` and **monotonically non-increasing** within an unbroken ladder
   (a reactivation is the only way rate goes back up).
4. `partner_fee_owed <= mgmt_fee_owed` (partner share never exceeds our pool).
5. `ps_claim_owed = GREATEST(mgmt_fee_owed − wayward_paid_us, 0)` — never negative.
6. Ledger grain unique (brand×product×month) — extends `spine_grain_unique`.

## 6. RECONCILIATION TARGETS (Phase C acceptance)
- Live ledger's `usage_collected` total ties to the frozen snapshot within rounding (drift = a finding
  to explain, not silently accept).
- `wayward_paid_us` total ties to the Dec–Jun payment sheets **exactly** (already reconciled).
- Recovery (`Σ ps_claim_owed` for china, non-excluded) lands near the first-order **~$10.4k**;
  material deviation = investigate before shipping.
- Spot-checks reproduce: Tiny Land ~$1,152, Neakasa ~$2,355, Beetles ~$7.

## 7. EDGE CASES / CARRY-INS
- **The 1 merged money-bearing canonical** — pick the surviving brand row; document which.
- **5 subscriptions missing `productive_date`** — no ladder; default to 3%? or hold? (minor; propose 3%).
- **Un-invoiced accrued usage (L1)** — reserved NULL until Jake feed.
- **Partner rates** — 5% default now; re-run on Rhea's roster (no rebuild, just data + recompute).
- **`ps_monthly_earnings.is_claimable/claim_basis`** — superseded law; DROP or ignore in the swap.

---

*Approve §1 (fields), §2 (rules), §3 (architecture — the real decision), §4/§5 as the build contract.
On approval → Phase B: build the rate-schedule helper + the ledger/claim lenses + invariants + tests,
reconcile, then the on-rails swap.*
