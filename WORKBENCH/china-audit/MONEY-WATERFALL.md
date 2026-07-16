# MONEY WATERFALL — schema readiness (Tim, 2026-07-15)

> ⚠️ **SUPERSEDED (2026-07-16).** This was the pre-build schema check; the money is now **LIVE, not
> frozen** (cip_104–110). Its stage→column mappings point at the legacy `ps_monthly_earnings`
> snapshot — **which was DROPPED in cip_110**, so every `ps_monthly_earnings.*` reference below is
> historical (the live equivalents are in `lens_ps_commission_ledger` / `lens_ps_claim`). For the
> current money read-surface see [LENS-CATALOG.md](LENS-CATALOG.md). Kept as historical record.

**Purpose:** before we build any owed-vs-paid math (P2), confirm the schema can HOLD every stage of
the money flow, month by month. No engine here — just: do we have the fields? Grounded in Jake's
payment reports (now in `ps_payment_events`).

**Money stays FROZEN** — this is a schema check, not a computation.

---

## THE WATERFALL — each stage → its schema home

| # | Stage | Schema home | Ready? |
|---|-------|-------------|--------|
| 0 | Client uses the platform (usage occurs) | only visible once invoiced (below) | see GAP 1 |
| 1 | **Accrued, not yet billed to client** (expected income, ours + partners) | — | **GAP 1** |
| 2 | **Billed to client, not collected** | `ps_stripe_invoices` (amount_due/paid/remaining, status); `ps_monthly_earnings.usage_billed/usage_outstanding` | ✅ |
| 3 | **Client paid Wayward** | `ps_stripe_invoices.amount_paid`; `ps_monthly_earnings.usage_collected` | ✅ |
| 4 | **Wayward owes us** (our commission on collected) | `ps_monthly_earnings.ps_gross_owed / ps_net_owed / ps_rate_pct` | ✅ (frozen snapshot; engine = P2) |
| 5 | **Wayward paid us** | `ps_payment_events` — Jake's monthly reports: `total_amount_paid`, `rev_share_stated / _computed / _variance`, fee breakdown; `ps_monthly_earnings.ps_actually_paid` | ✅ |
| 6 | **Wayward's shortfall to us** (owed − paid = what we proactively bill) | derived: `ps_net_owed` vs `ps_actually_paid` (`variance`); `ps_payment_events.rev_share_variance` | ✅ |
| 7 | **We owe partners** | `ps_partner_credit` (partner_of_record, partner_rate) + `ps_partner_terms` (commission_pct, basis, window); `ps_monthly_earnings.partner_owed / partner_rate_pct` | ✅ |
| 8 | **We paid partners** | — (`ps_partner_credit.flat_fee_paid_at` exists but unused/insufficient) | **GAP 2** |
| 9 | Our claim to Wayward | `ps_claims` + `ps_claim_lines` (period_month grain) | ✅ |

## Month-by-month history: YES
- `ps_payment_events`: per payment, dated, **7 months (Dec 2025 – Jun 2026)**, fee breakdown + variance.
- `ps_monthly_earnings`: **brand × product × month** (`period_month`) — the spine.
- `ps_stripe_invoices` / `_lines`: dated billing.
Caveat: the COMPUTED side (owed) is a **frozen snapshot** until P2 rebuilds the engine; the FACTS
(Stripe billing, Jake's payments) stay live.

---

## GAPS

1. **"Accrued, not yet billed to client"** — we only see usage once Wayward INVOICES it; no
   pre-invoice usage feed (`free_tier_daily_usage` is unrelated FAS LLM data). **Tim, 2026-07-15:**
   don't build it — Wayward almost certainly reconciles at invoice time today, so the data likely
   doesn't exist yet. **Non-dependent: ask Jake; build the field later only if he can provide it.**
   Added to DATA-WE-NEED.md.
2. **"We paid partners"** — ✅ **RESOLVED (cip_101): `ps_partner_payouts`** — the us→partner ledger,
   mirroring `ps_payment_events`. **SCOPE (Tim's rule):** only partners WE pay (brands referred in
   OUR timeframe, post-cutover). Partners on the 10% exclusion list are paid by **Wayward** directly
   and are NOT recorded here. Direct (no-partner) deals have no rows. Reconcile `amount_paid` vs
   `ps_monthly_earnings.partner_owed` for the partner shortfall (the math is P2).

## LAYERS to make explicit (answer to "any layer I forgot?")
- **"What Wayward has actually PAID us"** — you folded this into "Wayward owes us," but it is a
  distinct stage (Jake's reports), and **owed − paid = the recovery number** — the whole point of
  proactive billing. It is stage 5/6 above; keep it explicit.
- **Adjustments / refunds / voids / disputes** — money that reverses after billing/collection.
  Partially captured (`ps_monthly_earnings.usage_voided`, invoice status=void); refunds/chargebacks/
  credits may need a home.
- **Our NET margin** — our income − partner payouts = what PS keeps. The bottom line; worth a layer.
- **Aging (a dimension, not a layer)** — how old each uncollected/unpaid amount is (30/60/90+) —
  drives which to chase first.

## Anything unexpected in Jake's payment sheets?
`ps_payment_events` captured a rich set: fee breakdown by type (commission / usage / saas /
**cc_processing**), rev_share stated vs computed vs variance, timing (signup, months_from_signup,
rev_share_start_date, days_since_start), invoice ids + links. Nothing looks un-modeled.
- **cc_processing_fees_paid** is captured — decide whether CC processing is its own layer (who bears it).
- To be 100% sure the sheets dropped NOTHING: re-drop one payment sheet in `intake/` and I'll diff
  its columns against `ps_payment_events`. (We hold the ingested data, not the raw files — those were
  loaded in a prior session.)

## PARTNER PORTAL — use cases the schema must support (Tim, 2026-07-15; fact-checked)
Each partner will see what's in flight for THEIR referred brands: fees heading to Wayward, what
Wayward has billed but not collected, and what's been collected — from which the partner is **owed
their amount** (we keep ours). The partner does NOT see the Wayward→us→partner chain; they just see
"client paid Wayward → you are owed $XXX." Schema supports it:
- partner → brand/product: `ps_partner_credit` (2,869 attributions) + `ps_partner_registry`.
- in-flight / billed-not-collected / collected: `ps_stripe_invoices` + `ps_monthly_earnings`
  (usage_billed / usage_outstanding / usage_collected).
- partner owed: `ps_monthly_earnings.partner_owed` (+ partner_rate_pct).
- partner paid: `ps_partner_payouts` (cip_101).
- **Direct deals (no partner)** have no `ps_partner_credit` / payout rows — handled natively.
The portal itself is a later reporting/lens build (P4); the DATA it needs is now all present.

## Decisions — settled 2026-07-15
1. `ps_partner_payouts` — **approved, built (cip_101).**
2. Refunds/adjustments — **not needed now; cross later.**
3. Un-invoiced usage — **ask Jake; build later only if he can provide it** (non-dependent).
4. Payment-sheet re-drop + diff — **yes; awaiting a payment sheet dropped in `intake/`.**
