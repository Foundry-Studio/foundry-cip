# MONEY WATERFALL — schema readiness (Tim, 2026-07-15)

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

## GAPS (schema additions to propose — not built yet)

1. **"Accrued, not yet billed to client"** — we only see usage once Wayward INVOICES it. There is no
   pre-invoice usage feed (the `free_tier_daily_usage` table is unrelated FAS LLM data). So layer 1
   is ESTIMABLE (from run-rate) but not directly measurable. → **Jake ask:** can we get usage before
   it is invoiced? Until then, layer 1 is a projection, not a fact.
2. **"We paid partners"** — there is **no partner-payout ledger.** We track partner_OWED but not
   partner_PAID. `flat_fee_paid_at` is one date, unused (0 rows), and can't hold per-period amounts.
   → **Propose `ps_partner_payouts`** (partner × period × amount paid + ref), mirroring
   `ps_payment_events`. Then "owed vs paid to partners" reconciles exactly like "owed vs paid from
   Wayward."

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

## Open decisions for Tim
1. Approve **`ps_partner_payouts`** table (gap 2)?
2. Do refunds/adjustments need their own home, or is `usage_voided` + invoice-status enough?
3. Add the **un-invoiced-usage** ask to Jake's list (gap 1)?
4. Want me to diff a re-dropped payment sheet vs `ps_payment_events` to confirm nothing was dropped?
