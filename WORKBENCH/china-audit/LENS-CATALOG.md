# LENS CATALOG — what each lens answers, in plain English

**The read-first reference for the Wayward China-commission money system.** If you want a number —
for an invoice, a report, Metabase, a partner, or Wayward — start here. Current as of the head
migration **`cip_109_reporting_lenses`** (money engine = cip_104–109). Live + self-updating; every
figure recomputes from current data.

## 📌 THE canonical number (updated on each engine change)
**Recovery / still-owed to us by Wayward ≈ $12,035** (china, PS-eligible per product, from the 2025-10-01
anchor, minus what Wayward has paid). This is the one figure to quote; it lives in `lens_ps_claim`
(`SELECT round(sum(ps_claim_owed),2) FROM lens_ps_claim WHERE verdict='china'`). Older docs cite
$10.4k / $10.88k / $11,099 — those are superseded first-order / pre-rewire estimates.

---

## The model in one breath
**China? (yes/no)** is the only gate for whether *we* earn Wayward's management commission. Then it's
**per product**: the pre-PS **rev-share** exclusion list is Connect-only, so those brands' **Boost** is
still ours. Of what we earn, if a **partner** is the lead we pass them a cut. Three separate money
flows: (1) *Wayward → us* (our commission), (2) *us → our partners* (the split), (3) *Wayward → the
exclusion-list partners direct* (Eric et al. — **not ours**, tracked separately).

---

## The lenses, by the question they answer

### "What does Wayward owe us?" (the invoice)
| lens | answers |
|---|---|
| **lens_ps_claim** | Per china brand: `mgmt_fee_owed` · `wayward_paid` · **`ps_claim_owed`** (still owed, floored at 0) + partner side. THE invoice source. |
| **lens_ps_commission_ledger** | The detail behind it — per brand × product × month: collected, `mgmt_rate` (10/6/3), `claimable`, `mgmt_fee_owed`, `partner_fee_owed`, `claim_status`. |
| **lens_ps_rate_schedule** | The 10/6/3 ladder dates per brand × product (re-anchored by a qualifying reactivation). |
| **lens_ps_ar_aging** | Of what's owed, **how long unpaid** — `months_outstanding` + `aging_bucket`. |
| **lens_ps_monthly_summary** | The trend line: owed / partner-owed / **net** by month × product. |

### "Is each brand set up right?"
| lens | answers |
|---|---|
| **lens_ps_product_eligibility** | Per china brand × product: `ps_rev_share_eligible` · `wayward_client_fee_rate` (what Wayward charges the client) · `ps_partner_rev_share_eligible` + `partner_name` + `partner_rate_pct`. The setup view. |
| **lens_ps_china_verdict** | The nationality call per brand (china / not_china / unknown) + its evidence strength. |
| **lens_ps_china_companies** | The book, one row per company (not per brand-row) — for headcounts. |
| **lens_ps_exclusion_status** | Is a brand on the contract exclusion list, and is it `takeable`. |

### "What do we owe our partners?"
| lens | answers |
|---|---|
| **lens_ps_partner_payout_summary** | Per partner WE pay: owed / paid / **still-owed** / brand count. |
| (detail) `lens_ps_commission_ledger.partner_fee_owed` | The per-brand × product split. |

### "Does Wayward agree / what are they owning?" (reconciliation)
| lens | answers |
|---|---|
| **lens_ps_wayward_reconciliation** | Per brand: our claim vs **Wayward-credits-Tim** (their attribution) vs paid → `delta_status`. |
| **lens_ps_wayward_stated** | Wayward's OWN stated numbers (total_fees_paid / lifetime commissions / GMV) vs our recorded paid — the cross-check. |

### "What are the exclusion-list partners driving?" (separate — NOT ours)
| lens | answers |
|---|---|
| **lens_ps_excluded_partner_performance** | The pre-PS rev-share book (Eric / Heavy Producers / etc., paid **direct by Wayward**): brands + collected revenue per bucket × referrer × product. **Walled off from our owed on purpose** — look here to see what Eric's driving; never subtract it from the claim. |

---

## `delta_status` values (from lens_ps_wayward_reconciliation)
- **`paid_settled`** — Wayward paid, nothing left owed.
- **`paid_partial`** — Wayward paid something, a balance remains.
- **`acknowledged_unpaid`** — Wayward's own CRM credits Tim + marks active, but paid $0 → **the strongest ask**.
- **`credited_other_unpaid`** — we claim it, but Wayward's attribution credits someone else (Eric/Adina), $0 paid (164 brands — the 2nd-biggest bucket; a negotiation conversation, still ours).
- **`unacknowledged_unpaid`** — we claim it, Wayward has no attribution on record, $0 paid.
- **`no_claim`** — nothing owed (not china-eligible, or fully square).
*(An older plan doc lists `we_claim_credit_other` / `we_claim_no_ack` / `not_ours` — those are NOT the shipped names.)*

## Glossary (terms partners/Wayward will hit)
- **usage fee / `usage_collected`** — the base fee the client actually PAID Wayward (Connect = % of GMV, Boost = % of ad spend). `is_ps_base` lines, status=paid. Our commission is a % of this.
- **`usage_billed`** — invoiced (paid + open), voids excluded. Billed ≥ collected.
- **`wayward_client_fee_rate`** — what WAYWARD charges the CLIENT (5% GMV Connect / ad-spend rate Boost, negotiated 1–6%). NOT our commission.
- **our commission / `mgmt_fee_owed`** — what Wayward owes US: `usage_collected × mgmt_rate`, where `mgmt_rate` is the **10/6/3 ladder** (10% first 12mo, 6% next 6mo, 3% after).
- **`ps_claim_owed`** — `mgmt_fee_owed − wayward_paid`, floored at 0 per brand. The still-owed / invoice number.
- **partner cut / `partner_fee_owed`** — what WE pass a referral partner (default 5% of the usage fee), carved from our commission.
- **`ours_revenue_from`** — the date we start counting a brand's revenue (2025-10-01 never-listed, 2025-12-01 flat-fee, 2025-10-01 rev-share Boost).
- **`flat_fee_era_eric` / `excluded`** — disposition on the contract list: flat-fee = **ours** (Wayward pays us); excluded (rev-share) = **not ours on Connect**, Boost still ours.
- **`unknown_nationality`** — brand not yet ruled china; queued, claimed at $0, revisitable — never denied.

## Source-of-truth tables (not lenses)
`ps_brands` (master) · `ps_nationality_signals` → `lens_ps_china_verdict` · `ps_excluded_brands`
(contract list + disposition) · `ps_product_eligibility` (per-product eligibility + fee-rate
overrides) · `ps_partner_credit` (partner + rate per brand×product) · `ps_partner_payouts` (what we
paid partners) · `ps_payment_events` (what Wayward paid us) · `ps_stripe_invoice_lines` (the money
spine) · `ps_claim_statements` (pinned as-of claims handed to Wayward).
