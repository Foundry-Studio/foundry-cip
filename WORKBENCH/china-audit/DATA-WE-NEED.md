# DATA WE NEED — outstanding asks to Jake / Wayward / Rhea

**Durable list so these don't live only in a chat context.** RULES #9 still holds: **no active asks
to Jake/Wayward yet** — Tim sends data himself for now. These are QUEUED for when we engage, and they
shape what the connectors/backfill should eventually pull.

---

## For JAKE — automate the richer brand/contact detail (Tim, 2026-07-15)

Right now Jake hands us this as one-off spreadsheets (e.g. "China brands with provided wechat").
**We want it flowing automatically** — the current connectors + a one-time backfill should carry it,
not manual sheets:

- **WeChat** — `wechat_id` (handle) AND `wechat_phone` (number). Jake's sheet mixes both in one
  column; we now hold them in two fields (`ps_brand_contacts.wechat_id` / `wechat_phone`, cip_100).
- **Named contacts** — `contact_first_name`, `contact_last_name`, `contact_email`, `contact_title`
  per brand (the real person, not just the billing email). Support 2+ contacts per brand.
- **The fields that were EMPTY in the 2026-07-14 export but would be gold if populated:**
  `amz_seller_id`, `amz_brand_name` (Amazon seller entity — nationality + identity evidence),
  `business_name`, `parent_brand_id` (identity/hierarchy), `shipping_source_country`.
- Coverage gap surfaced: at least one brand on Wayward's own China list (**ELTRIKO**) was **not in
  our system** — the sync/backfill should not silently drop brands Wayward has.

**Ask shape:** (1) a backfill of the historical richer detail; (2) the live HubSpot/brand connector
extended so new/updated brands carry it going forward. Not sent yet — queued.

### Automate the monthly payment / rev-share reports
Jake's monthly "Rev Share / Referral Report" is the **only** source of what Wayward actually PAID us
(and their stated rev share) — not derivable from Stripe/HubSpot. Today it's a manual sheet per
month → `ps_payment_events`. **Ask:** deliver it as a feed (or a stable dated file drop) so payments
flow automatically. (Dec 2025–Jun 2026 are backfilled and reconciled — totals tie exactly.)

### Un-invoiced (accrued) usage — for the money waterfall
Can we see client usage **before** Wayward invoices it? (Tim, 2026-07-15: suspects they reconcile at
invoice time today, so it probably doesn't exist yet.) If Jake can provide accrued/un-invoiced
usage, we build the "expected income on unbilled" layer then — **non-dependent**, no schema change
until he confirms. See MONEY-WATERFALL.md gap 1.

## For RHEA — partner roster & rates
Where the partner roster + commission rates live (referenced across the audit; needed for the
attribution/SOP phase). Deferred to that phase; note to update OWNERSHIP-RULES.md + PROGRAM.md then.

## Never-ingested sources (from SOURCE-MAP.md — external enrichment, not a person-ask)
- **Brand websites** (`.cn` TLD, Chinese-language content, ICP filing numbers = hard nationality
  evidence) — never fetched.
- **Amazon storefront "Sold by"** (legal entity + address the INFORM Act requires) — never fetched.

---

*When any of these is fulfilled, record it in INTAKE-LOG.md and clear it from this list.*
