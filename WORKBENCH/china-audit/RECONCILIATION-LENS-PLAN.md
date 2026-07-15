# PLAN — Wayward reconciliation lens (VALIDATED by 2 subagents 2026-07-15)

**Status: plan validated + corrected by blast-radius (A) and mapping (B) subagents. Ready to build on
Tim's go.** Blast radius confirmed LOW/additive — nothing breaks.

## Goal
One row per brand: **WE say china + owe $X · WAYWARD credits "China Referral - Tim" (or not) + their
own commission number · WAYWARD paid $Y** → a `delta_status`. The point: surface **what Wayward's own
CRM already admits owing us but hasn't paid.**

## THE REFRAME the subagents surfaced (this is the important part)
Our $11,099 claim splits three ways by whether Wayward *acknowledges* it:
| bucket | brands | measure |
|---|---|---|
| **Wayward credits Tim, active, but $0 paid** | **194** | **≈ $14,603** Wayward-acknowledged lifetime commissions ($104,343 GMV @ ~14.8%) |
| We claim, Wayward acknowledges NOBODY | 109 | ~$10,168 of our mgmt-fee owed (92% of our pool) |
| We claim, Wayward credits someone else (Eric/Adina/…) | 16 | ~$521 (contested) |

The first bucket is the **strongest ask — Wayward's own system says it's owed.** The lens makes all
three visible and self-updating.

## Mapping (CORRECTED by subagent B — two traps avoided)
- ⚠️ **`cip_deals.source_id` is NOT unique** (1,530 version-dupes; stale copies have BLANK attribution).
  MUST dedup first: `DISTINCT ON (source_id) … ORDER BY refreshed_at DESC`. Skipping this both
  multiplies rows AND nulls-out the attribution. Non-negotiable.
- ⚠️ **`cip_deals.company_id` is 100% NULL** — the company key is `properties->>'hs_primary_associated_company'`.
- **Bridge on deal_id UNION company:** `ps_brand_observations(field='hubspot_deal_id').value = source_id`
  **∪** `(field='hubspot_company_id').value = hs_primary_associated_company`. Coverage over the 1,126
  china brands: deal 576, company 602, **union 606**. Deal bridge is strictly 1:1 (no multi-deal
  fan-out); **no brand has conflicting attribution sources** → aggregation is trivial.
- ~550 china brands have no HubSpot deal (slack/stripe-only) → NULL attribution = "not acknowledged".
  Label it so it never reads as "$0 owed".

## Object: `lens_ps_wayward_reconciliation` (per wayward_brand_id)
| column | source |
|---|---|
| our_verdict, our_mgmt_fee_owed, our_claim_owed, wayward_paid | **reuse `lens_ps_claim`** (live cip_104 — do NOT re-derive money) |
| wayward_credits_ps (bool) | `attribution_source ILIKE '%Tim%'` (verified: matches ONLY "China Referral - Tim", 492 — no false hits) |
| wayward_attribution_source | deduped cip_deals (prefer the active row, else freshest) |
| wayward_attribution_active | cip_deals |
| wayward_ack_commission | **`properties->>'lifetime_commissions_generated'`** — Wayward's OWN owed number (THE ask measure, not ps_claim_owed) |
| wayward_ack_rate, wayward_ack_gmv | avg_attribution_commission_rate, lifetime_gmv |
| delta_status | derived |

`delta_status`: `paid` · **`acknowledged_unpaid`** (credits Tim + active + $0 paid → the ask) ·
`we_claim_credit_other` (we owe, Wayward credits Eric/Adina) · `we_claim_no_ack` (we owe, no Wayward
attribution) · `not_ours`.

**⚠️ Do NOT headline `ps_claim_owed` for the ask.** It's a mgmt-fee residual already net of payments,
floored at 0 — it reads $30 for the acknowledged-unpaid set because those are newer/low-realized
brands. The real ask is Wayward's own `lifetime_commissions_generated` (~$14.6k). Keep `ps_claim_owed`
as a column (our formal management-fee claim) but drive `acknowledged_unpaid` from Wayward's number.

## Blast radius (subagent A — CONFIRMED LOW)
- The old `lens_*_attributed_deals` / `lens_wayward_attribution_summary` are empty because they're the
  **ecomlever tenant's `hubspot-v1` lenses** (our deals are mirrored under `lens-mirror-deals-v1`) —
  NOT a stale filter. **Zero consumers** (no DB dependents, no code, no Metabase). Leave them; don't
  build on them.
- `cip_deals` has FORCE RLS + `cip_tenant_scope` — the lens is tenant-scoped automatically (add the
  explicit `tenant_id` filter for defense-in-depth, matching every `lens_ps_*`).
- No triggers on cip_deals; a view's SELECT (ACCESS SHARE) never blocks the hourly HubSpot sync.
- Grants: `cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk, metabase_reader_foundry`
  (+ guarded `cip_rls_test_role`) — the current `lens_ps_*` block.
- No existing lens does this 3-axis reconciliation. `lens_ps_claim_reconciliation` does 2 axes off the
  FROZEN snapshot — we supersede that by layering on the live `lens_ps_claim`.

## Build steps (on Tim's go)
1. Migration `cip_105_wayward_reconciliation` — `CREATE VIEW lens_ps_wayward_reconciliation` (deduped
   cip_deals ∪ bridges → attribution; join live `lens_ps_claim`) + comments + standard grants.
2. Tier-C (up/down/up + full-chain replay) · ruff · a behavioral test (seed a Tim-credited-unpaid
   brand → assert `acknowledged_unpaid`) · reconcile the 194-brand / ~$14.6k headline on prod.
3. Commit + push. Additive, read-only; the frozen snapshot + claim engine are untouched.
