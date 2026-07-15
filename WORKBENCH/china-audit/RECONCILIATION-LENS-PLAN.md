# PLAN — Wayward reconciliation lens (our claim ↔ Wayward's acknowledgment ↔ paid)

**Status: PLAN for review — no code yet. Being pressure-tested by a subagent for blast radius.**

## Goal
One row per brand showing the **delta ladder** Tim asked for:
1. **WE say** — our verdict (china) + `ps_claim_owed` (our engine, cip_104).
2. **WAYWARD acknowledges** — do they credit us? From `cip_deals.properties.attribution_source`
   (e.g. "China Referral - Tim"), `attribution_active`, `average_attribution_commission_rate`.
3. **WAYWARD paid** — `ps_payment_events.rev_share_stated`.

So at a glance: *brands Wayward doesn't even acknowledge as ours · brands they credit to Tim but
haven't paid (THE ASK) · brands paid.* Updates itself as Wayward edits HubSpot (hourly sync).

## The mapping (the crux)
`cip_deals` has no `wayward_brand_id` — it carries `source_id` (HubSpot deal id) + `company_id`.
Bridge: **`ps_brand_observations` (field=`hubspot_deal_id`) → `cip_deals.source_id`**.
Verified coverage: 1,347 brands carry a `hubspot_deal_id`; **1,215 match a `cip_deals.source_id`.**
(Brands with no HubSpot deal — slack/stripe-only — simply show NULL attribution = "not acknowledged".)

## ⚠️ Blast-radius flags found already
- **The existing attribution lenses are EMPTY** (`lens_tim_attributed_deals`,
  `lens_wayward_attribution_summary`, + per-partner ones all return **0 rows**) — their filters
  predate the current `attribution_source = "China Referral - Tim"` format. **Do NOT reuse them; do
  NOT assume anything reads them.** (Subagent: confirm why they're empty + whether anything depends
  on them / Metabase cards break.)
- There are ~17 views over `cip_deals` (`lens_ps_china_commission`, `lens_ps_china_deal_financials`,
  `lens_ps_china_brands_by_original_attribution`, …). Subagent: do any already do this reconciliation?
  Any we'd duplicate or should fix instead of adding a 18th?

## Proposed object (additive, read-only)
`lens_ps_wayward_reconciliation` (per brand):
| column | source |
|---|---|
| wayward_brand_id, brand_name | ps_brands |
| our_verdict, our_claim_owed | lens_ps_claim |
| wayward_attribution_source | cip_deals via hubspot_deal_id map (agg per brand) |
| wayward_credits_ps (bool) | attribution_source ILIKE '%Tim%' |
| wayward_attribution_active | cip_deals |
| wayward_stated_rate | avg_attribution_commission_rate |
| wayward_paid | ps_payment_events |
| delta_status | derived (below) |

`delta_status`: `paid` · `acknowledged_unpaid` (credits Tim, active, $0 paid → the ask) ·
`we_claim_credit_other` (we say china+owed, Wayward credits Eric/Adina) · `we_claim_no_ack`
(we say china+owed, no Wayward attribution) · `not_ours`.

## Self-QC (my pass)
- **Fan-out risk:** one brand → many deals (connect+boost, historical). MUST aggregate per brand
  (bool_or credits_ps, pick active/latest attribution) or the join multiplies rows / double-labels.
- **Mapping gap:** ~1,215 of the china brands map; the rest show NULL attribution — correct (=
  "Wayward hasn't acknowledged"), not an error, but label it so it's not read as "$0 owed".
- **attribution_source parsing:** `%Tim%` match — verify no false hits (no other source contains
  "Tim"); "China Referral - Tim" is the only Tim value seen.
- **RLS:** cip_deals is tenant-scoped; the lens inherits it (same pattern as cip_104). Confirm.
- **Perf:** cip_deals ~5.2k rows — a view is fine; no materialization.
- **Not authoritative for money:** this is a *reconciliation/negotiation* view, NOT a claim input.
  The claim stays lens_ps_claim. This lens only *compares*.

## What the subagent must verify (blast radius)
1. Why are the existing attribution lenses empty — stale filter? and does ANYTHING (Metabase, code,
   other lens) depend on them (so a fix/rebuild wouldn't break a consumer)?
2. Is the `hubspot_deal_id → source_id` mapping the right/complete bridge, or is `company_id` better?
   Fan-out shape (deals per brand)?
3. Does any existing lens already produce this reconciliation (don't duplicate)?
4. RLS + grant pattern for a new lens over cip_deals; any risk to the hourly HubSpot sync.
5. Sanity-check the `delta_status` logic against real rows (esp. the "China Referral - Tim" 493).
