# HubSpot lifetime_gmv inflation — diagnostic + fix checklist (DI-1)

Authored 2026-08-25 (/startbuild, DI-1). Read-only CIP verification done by the agent; the HubSpot fix is HUMAN (Tim or the HubSpot admin). The agent never writes HubSpot. No em dashes.

## What is wrong

The HubSpot deal property `lifetime_gmv` (and its siblings `total_fees_paid`, `lifetime_commissions_generated`) has been inflating since roughly Jul 9. It flows into CIP via the deal mirror (`cip_deals`, connector `lens-mirror-deals-v1`) and from there into the Wayward reconciliation lenses (`lens_ps_wayward_reconciliation`, `lens_ps_wayward_stated`), where it is Wayward's OWN acknowledged number (the ASK measure). An inflated `lifetime_gmv` makes those reconciliation views nonsense.

**Current CIP state (measured read-only 2026-08-25, Project Silk tenant):**

| Measure | Value |
|---|---|
| sum(lifetime_gmv) across deals carrying the field | **$630,184,018** |
| deals carrying the field | 1,230 |
| deals over $1M | **75** |
| single largest deal | **$207,293,138** |

For scale, the ~Jul 7 baseline (pre-inflation) was about **$54M**. The book has inflated more than 10x.

**The canaries (the worst deals, by HubSpot deal id — inspect these first):**

| HubSpot deal id | Company id | lifetime_gmv | Referral source |
|---|---|---|---|
| **107964640993** | 104402345669 | **$207,293,138** | China Referral - Eric |
| 129116204763 | 125217097442 | $24,347,043 | China Referral - Adina |
| 197783887598 | 196285804262 | $21,387,504 | China Referral - Tim |
| 71518961343 | 68007276248 | $14,654,384 | China Referral - Adina |
| 55451733733 | 51959110390 | $14,058,633 | China Referral - Adina |

A single brand doing $207M of lifetime GMV is not real; deal `107964640993` is the primary canary.

## Diagnostic checklist (HUMAN, in HubSpot)

Work these in order. The goal is to find WHAT re-inflates the property and WHEN it started (~Jul 9).

**(a) Property definition.** In HubSpot Settings > Properties > Deal properties, open `lifetime_gmv`. Determine its TYPE:
- Is it a **calculated / rollup** property (a formula over associated line items, other deals, or a sum across the company's deals)? A rollup that double-counts associations is the classic cause of a runaway sum.
- Or a **workflow-set** value (a workflow writes it)?
- Or an **imported** value (a recurring import / integration from a Wayward feed)?
Record the exact definition. Do the same for `total_fees_paid` and `lifetime_commissions_generated`.

**(b) Property history on the canary.** Open deal `107964640993`, then the property history for `lifetime_gmv`. Since ~Jul 9:
- What is the per-change delta, and how often does it change (daily? on every sync?)?
- WHO or WHAT is the actor on each change (a specific workflow, an integration user, a person)?
- Does the delta look like a fixed ~daily re-add, or a compounding rollup?
Note the first inflated timestamp (confirm it is ~Jul 9) and the actor.

**(c) Automations / imports.** Search HubSpot for anything that writes `lifetime_gmv`:
- Workflows (enrolled on these deals) that set or increment it.
- Any recurring import or integration (a Wayward data feed, a Zapier/Operations Hub sync) that re-adds a value.
- A calculated-property recompute that changed definition on ~Jul 9.
Identify the single mechanism re-adding value. This is the thing to disable/correct.

**(d) Correct value + reset.** Establish the CORRECT `lifetime_gmv` per deal (the real cumulative GMV, roughly the ~$54M-total baseline as of Jul 7). Decide the reset mechanism (fix the property definition, disable the offending workflow/import, and backfill the corrected values). This is a HubSpot data correction, owned by the HubSpot admin.

**(e) Scope of the blast.** 75 deals are over $1M and 1,230 carry the field; the inflation concentrates in the largest deals (China Referral deals). Confirm whether the mechanism hits all 1,230 or only a subset, so the correction targets the right set.

## CIP verification (agent, read-only) — proves the fix landed

**BEFORE (today, measured):** total $630,184,018 across 1,230 deals; 75 over $1M; largest $207,293,138.

Re-run after the HubSpot fix + a CIP sync:

```sql
select round(sum((properties->>'lifetime_gmv')::numeric),0) as total_gmv,
       count(*) as deals_with_field,
       count(*) filter (where (properties->>'lifetime_gmv')::numeric > 1000000) as deals_over_1m,
       max((properties->>'lifetime_gmv')::numeric) as largest_deal
from cip_deals
where source_connector='lens-mirror-deals-v1'
  and tenant_id='078a37d6-6ae2-4e22-869e-cc08f6cb2787'
  and properties->>'lifetime_gmv' ~ '^[0-9.]+$';
```

**PASS criteria (AFTER):** total near the ~$54M baseline; NO single deal in the tens or hundreds of millions (largest_deal back to a realistic level); deals_over_1m collapses toward zero; and on the following day the total does not move (daily delta ~0). Once that holds, the four Wayward reconciliation lenses (`lens_ps_wayward_reconciliation`, `lens_ps_wayward_stated`, `lens_ps_wayward_acknowledgment`, `lens_ps_wayward_indicators`) return sane Wayward-stated figures again, and the DI-0 containment can be lifted.

## Ownership

- HUMAN (Tim / HubSpot admin): steps (a)-(e) — the property inspection and the correction. One-way door: correcting a HubSpot property is an external-system write.
- AGENT: this checklist + the read-only CIP verification above. The agent does NOT write HubSpot.
