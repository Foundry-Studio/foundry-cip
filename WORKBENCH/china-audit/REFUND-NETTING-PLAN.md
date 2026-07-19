# PLAN — refunds as a first-class money variable (Tim, 2026-07-18)

**Goal:** "collected" — the base our commission is calculated on — becomes **net of refunds**, in the
math, the reporting, the DB, the docs, everything. It nets out, it shows integrity, and it matches
the contract's own language. Nothing hand-wavy; installed correctly and self-maintaining off the
hourly Stripe sync.

## Why (the contract basis)
§3.1 pays Project Silk revenue share on **"Usage Fees *actually received* by Company [Wayward]."**
A usage fee that was collected and then refunded was not, in the end, *actually received*. The word
"refund" appears nowhere in the contract, so this is the governing phrase — and it cuts both ways
(it's also what stops Wayward claiming we owe on money they gave back). Netting refunds makes every
claim more defensible.

## The rule (validated on prod, reason-agnostic)
A refund is at the **invoice/charge** level; our collected is per **is_ps_base line**. A refund nets
only the **usage-fee (is_ps_base) *share* of its invoice, pro-rata by paid line amount** — NEVER the
full refund. Worked example (AEOCKY): a $1,475.76 refund on a $1,675.76 invoice whose usage is only
$367.96 (rest = commission passthrough + reconciliation) nets ≈ the usage share, ~$324 — not $1,475.

Per is_ps_base paid line:
`refund_alloc(line) = LEAST(refund_total_on_invoice, invoice_paid_total) × line_amount / invoice_paid_total`
aggregated to (brand, product, month), then **capped** so it can never exceed the cell's gross:
`usage_collected_net = gross − LEAST(refund_alloc, GREATEST(gross, 0))`.

Properties (all verified):
- **Reason-agnostic.** Correct for "duplicate" refunds (removes the duplicate invoice's usage,
  leaving the original) AND genuine returns — the reason label never enters the math.
- **Never negative from refunds** (the cap); negative-reconciliation months are left untouched.
- **No double-count** with Wayward's own negative reconciliation lines (those are already in gross;
  measured overlap = $16.47 total, immaterial; the pro-rata is on positive paid lines).

## Credit notes — EVIDENCE-ONLY (not separately netted), and why
23 credit notes / $42.9k, mostly "order_change" ($38.6k). A credit note either (a) reduces an OPEN
invoice's amount before payment → the paid line already reflects the reduction (netting again would
double-subtract), or (b) is issued on a PAID invoice → it spawns a **refund** which we already net.
So credit notes stay in `ps_stripe_credit_notes` as evidence; they do not enter the derivation. (1
invoice has both a refund and a CN — the refund path handles it.)

## Impact (validated, prod)
- Total usage netted across all brands: **$3,494.30**. By nationality: not_china $2,857.89 (we don't
  claim on them), **china $620.41**, unknown $21.34.
- Gross mgmt-fee-owed: −$33.72. **Recovery (still-owed): $13,716.66 → $13,712.58 (−$4.08)** — smaller
  than the fee drop because `ps_claim_owed` is floored per brand net of what Wayward already paid, and
  the refunded brands are mostly already paid. Immaterial to direction; material to integrity.
- The naive "subtract the whole refund" would have over-netted ~5× ($3,494 → ~$21k). This is why the
  pro-rata is_ps_base rule matters.

## Implementation (cip_113 + code + docs)
1. **`lens_ps_refund_allocation`** (new view): brand × product × month → `usage_refund_raw`,
   `usage_refund_netted` (capped). The transparency surface + the ledger's input. Grants to the 3
   read roles.
2. **`lens_ps_commission_ledger`** (CREATE OR REPLACE — SAME column signature, no cascade):
   `usage_collected` becomes NET (gross − capped refund alloc). mgmt_fee/partner_fee auto-follow
   (commission on net received). `usage_billed` stays gross (a refund doesn't un-bill; billed ≥
   collected preserved).
3. **`lens_ps_monthly_summary`** (CREATE OR REPLACE, append `usage_refunded`): reporting shows the
   gross→refund→net story, so it visibly nets out.
4. **Invariant** `refund_alloc_never_exceeds_gross` (new): 0 cells where netted > gross — guards the
   cap. Re-baseline any invariant the blast-radius sweep flags.
5. **Docs**: LENS-CATALOG (redefine "collected" = net of refunds + the rule + glossary), MATH-SPEC,
   MONEY-WATERFALL, OWNERSHIP-RULES (the "actually received" basis), SOURCE-MAP; this plan.
6. **Self-maintaining**: the hourly Stripe sync already lands refunds into `ps_stripe_refunds`, so
   the netting updates every hour with no further work.

## Blast radius (from the read-only sweep, 2026-07-18)
**14 views reference the collected surface.** Split into:
- **Follow automatically (read the ledger/claim — net for free once the ledger nets):**
  `lens_ps_claim`, `lens_ps_ar_aging`, `lens_ps_monthly_summary`, `lens_ps_excluded_partner_performance`,
  `lens_ps_partner_payout_summary`, `lens_ps_wayward_reconciliation`, `lens_ps_wayward_stated`,
  `lens_ps_statement_drift`.
- **INDEPENDENT recomputers — must be handled explicitly or they ship the OLD number:**
  - `lens_ps_china_verdict` + `lens_ps_china_companies` (cip_110 `money` CTEs — separate copies of the
    formula; `china_companies.usage_collected` feeds `lens_ps_china_evidence_grid`) → **net them** (1c).
  - `lens_ps_billed_vs_collected` + `lens_ps_partner_performance` (pre-cip_104 legacy diagnostics;
    **0 downstream views**, stale grants only; `partner_performance` is already refund-blind via its
    `amount>0` filter) → **RETIRE both** (dead, superseded by the cip_104–109 engine; keeping a stale
    copy of the collected formula is the exact drift the sweep warns about).
- **Script:** `scripts/refresh_information_gaps.py` independently recomputes collected → repoint to the
  net ledger. (Other `is_ps_base` scripts only count/order lines, not dollars — unaffected.)

**Invariants (9 of 21 touch the ledger):** only two are in play — `ledger_grain_unique` (the one that
could BREAK if the refund join fans out; guarded by building the refund term at exactly
brand×product×month grain — verified **0 grain dupes** in `lens_ps_refund_allocation`) and
`net_negative_on_positive_revenue` (stays valid — already exempts refund/negative months; `why` reworded).
New: `refund_alloc_never_exceeds_gross` (guards the cap). 21 → 22.

**Succeeded-only correction:** of 75 refund rows, only **23 succeeded** ($33,796); 46 failed + 6
pending never returned money and are excluded. 12 succeeded refunds have NULL invoice_id ($12.1k) —
un-attributable to product/month, so excluded from netting (surfaced as evidence, not netted).

**Docs to update:** MATH-SPEC (§L3 `usage_collected` def + recovered formula + reconciliation targets),
LENS-CATALOG (glossary `usage_collected`/`usage_billed` + add `lens_ps_refund_allocation`),
MONEY-WATERFALL (refund "needs a home" → has one), SOURCE-MAP (is_ps_base void/refund note),
OWNERSHIP-RULES (recovery-scope math), AUTOMATIONS-PLAN §3/§5 (evidence-only → netted for refunds),
LENS-INVENTORY (regenerate), and the ledger view's own `$c$` comment.

## QC gates
Penny-reconcile before/after on prod (recovery moves by exactly the china netting, nothing else);
21→22 invariants green; Tier-C up/down/up; adversarial subagent review; the refund lens reconciles
to `reconcile_refund_overlap.py`. Then commit + push + apply to prod.
