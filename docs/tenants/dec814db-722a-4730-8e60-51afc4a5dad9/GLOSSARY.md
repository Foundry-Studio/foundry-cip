---
id: CIP-DIAG-101
uuid: 6110af38-a26d-4498-9c47-56c218b9c9ca
title: EcomLever Tenant / Wayward Client — Property Glossary
type: diagnostic
owner: tim
solve_for: Wayward (EcomLever tenant) property glossary — plain-English semantic layer
  with confidence levels. Hand-maintained source-of-truth; materialized into cip_connector_property_registry
  via scripts/seed_glossary_into_registry.py.
stage_label: adopt
domain: dat
version: '1.0'
created: '2026-05-16'
last_modified: '2026-05-16'
last_reviewed: '2026-05-16'
review_cadence: 90
tenant_uuid: dec814db-722a-4730-8e60-51afc4a5dad9
tenant_name: EcomLever
client_uuid: 661ecab4-dddb-5924-a34d-af1c5133132d
client_name: Wayward
authors:
- tim
- cc-session-2026-05-16
supersedes: Glossary originally lived at `docs/tenants/b0000000-0000-0000-0000-000000000001/GLOSSARY.md`
  (the placeholder tenant_id). Moved 2026-05-16 to the canonical path under EcomLever's
  tenant_id; Wayward is now properly modeled as a client inside the EcomLever venture-tenant
  per VISION §4. All data re-tagged via `scripts/migrate_b0_to_ecomlever.py` (1,257,771
  rows).
---

# EcomLever Tenant / Wayward Client — Property Glossary

> Plain-English semantic layer over Wayward's CIP data. Wayward is the first (and currently only) client inside the **EcomLever** venture-tenant. Authored 2026-05-16 after the initial full-property HubSpot + Zendesk ingest. Confidence levels per `docs/PROPERTY-GLOSSARY-PATTERN.md`. Last comprehensive review: 2026-05-16 by Tim Jordan + cc-session-2026-05-16.
>
> **Tenant model**:
> - `tenant_id = dec814db-722a-4730-8e60-51afc4a5dad9` (EcomLever, venture)
> - `client_id = 661ecab4-dddb-5924-a34d-af1c5133132d` (Wayward, client)
>
> All cip_* rows reference both — filter on BOTH to scope to Wayward specifically (e.g., `WHERE tenant_id = '<EcomLever>' AND client_id = '<Wayward>'`). Future EcomLever clients (additional consulting engagements) would get their own client_id under the same tenant.

## Conventions

- **`verified`** = Tim or another knowledgeable Wayward stakeholder confirmed the meaning.
- **`inferred`** = derived from sample data + name + label; not yet confirmed by Tim.
- **`tentative`** = auto-baseline only; meaning is a best-guess from values alone.
- **`unknown`** = exists in the data, meaning not yet established.

## Tenant business model (one paragraph for grounding)

Wayward is an Amazon affiliate marketing platform. Brands pay Wayward a commission (typically ~10% of GMV driven by Wayward's creators) plus a platform usage fee (~1% of GMV). Wayward keeps the usage fee as its cut, pays the rest to creators. Referral partners (Tim Jordan, Eric of LYTASAUR, Adina, OpenLight, Jeremy Dai, Shallow) bring brands to Wayward — they get 10% of `total_fees_paid` per month on the brands they referred. The China-brand cohort is a strategically distinct portfolio with its own CS team (Rhea Deng, Monica Rovetto in China; Rebecca Jessup, Roselle Falculan in US).

---

## `cip_companies` — HubSpot company + Zendesk organization records

### `name`
- **Location:** `cip_companies.name` (first-class column)
- **Confidence:** `verified`
- **Meaning:** The company/brand name as recorded in HubSpot or Zendesk. For Wayward this is the BRAND name (Roborock, Insta360, Dreame, etc.) — these are Wayward's customers (the brands paying for affiliate marketing).
- **Coverage:** 100% (a fallback `(unnamed hubspot company #<source_id>)` is applied when HubSpot returns an empty name; ~185 companies had this fallback applied on 2026-05-13).
- **Watch out for:** Same company may appear twice if both HubSpot AND Zendesk track it (deduplicate on natural-key heuristics if joining across sources).
- **Last reviewed:** 2026-05-16 by Tim Jordan

### `country`
- **Location:** `cip_companies.country`
- **Confidence:** `verified`
- **Meaning:** Country of the brand. Wayward records this inconsistently — same country can appear as ISO code (`CN`) OR full name (`China`). Other Chinese-region variants: `Hong Kong`, `Taiwan`, `HK`, `TW`.
- **Coverage:** ~59% of companies have it set (39,094 of 66,595 HubSpot). NULL on ~41%.
- **Used to answer:** "Show me Chinese clients" — but see watch-out below.
- **Watch out for:** Wayward's country tagging is unreliable. We found 553 producing deals on companies country-tagged as US/Germany/etc. whose contacts had clearly Chinese signals (qq.com emails, .cn TLD, +86 phones, CJK names). **Do NOT use `country` alone as the canonical "is Chinese?" signal. Combine with contact-side signals.**
- **Last reviewed:** 2026-05-16 by Tim Jordan + Claude (verified 2026-05-16)

### `domain`
- **Location:** `cip_companies.domain`
- **Confidence:** `inferred`
- **Meaning:** Primary website domain of the brand (e.g., "roborock.com"). HubSpot's auto-extracted from associated contacts' email domains in many cases.
- **Coverage:** ~70%, often the same domain across multiple contacts of the same company.
- **Last reviewed:** 2026-05-16 by Claude

### `industry`, `region`, `language`, `city`, `employee_count`, `annual_revenue`
- **Location:** `cip_companies.*` (first-class)
- **Confidence:** `inferred` (these are HubSpot-standard fields, meaning is obvious; coverage is patchy)
- **Coverage notes:** Most are NULL on >70% of records. Useful when set, not authoritative.

### `properties->>'customer_target_segment'` (CUSTOM enum)
- **Location:** `cip_companies.properties->>'customer_target_segment'` (JSONB key)
- **Confidence:** `unknown` — field exists in HubSpot catalog, 0 values populated, Tim 2026-05-16 said leave blank for now.
- **Vendor label:** "Customer Target Segment"
- **Meaning:** *(not yet defined — empty in current data; will populate when/if Wayward starts using it)*
- **Last reviewed:** 2026-05-16 by Tim Jordan

### `properties->>'hubspot_owner_id'` + `properties->>'owneremail'` + `properties->>'ownername'`
- **Location:** `cip_companies.properties->>'hubspot_owner_id'` (and similar)
- **Confidence:** `inferred`
- **Meaning:** HubSpot's standard owner-of-record fields. `hubspot_owner_id` is the integer ID of the Wayward staff member assigned to the company. `owneremail` and `ownername` are usually NULL in our data because they require the `crm.objects.owners.read` scope which Wayward's token lacks — we have the ID but can't resolve to name/email programmatically. Tim's affiliate-owner attribution is NOT here — see `cip_deals.properties->>'source'`.
- **Top values:** `78132035` (639 companies), `161617282` (8 companies), one with no ID.
- **Watch out for:** Owner-resolution requires the Owners API scope (not granted) OR PM scope `cb6750f0` (HubSpot Owners + Pipelines resolver) shipping. Until then, treat as opaque integer.
- **Last reviewed:** 2026-05-16 by Claude

### `properties->>'tags'`, `properties->>'prospecting_tags'`
- **Location:** `cip_companies.properties->>'tags'`
- **Confidence:** `tentative`
- **Meaning (best guess):** Free-form tags HubSpot users apply to companies. Could be used for ad-hoc segmentation.
- **Coverage:** Mostly empty on Wayward's data.
- **Open question for Tim:** Does Wayward use HubSpot tags? Any conventions?

### Amazon-stack fields (custom on companies)
- **Fields:** `amazon_seller_id`, `amazon_seller_page`, `primary_amazon_category`, `secondary_amazon_categories`, `lifetime_amazon_seller_reviews`, `top_product_url`
- **Confidence:** `inferred`
- **Meaning:** Brand's Amazon storefront identity + product catalog signals. `amazon_seller_id` is the unique seller ID on Amazon. `primary_amazon_category` is the main product category the brand sells in (enumeration). Useful for filtering brands by Amazon vertical.
- **Used to answer:** "What category does this brand sell in?" "How established is the brand on Amazon (review counts)?"
- **Last reviewed:** 2026-05-16 by Claude

### Hyphen-platform fields (custom — internal Wayward acquisition product)
- **Fields:** `hyphen_gmv_rank`, `hyphen_overlapping_gmv`, `hyphen_units_sold_rank`
- **Confidence:** `verified`
- **Meaning:** "Hyphen" is **Hyphen Social** — a company Wayward purchased; treated as an internal Wayward product/platform. These fields capture Hyphen-platform analytics rolled up to the company level. `hyphen_gmv_rank` ranks the brand among the Hyphen portfolio by GMV. `hyphen_overlapping_gmv` tracks GMV overlap between the Hyphen affiliate program and other channels. `hyphen_units_sold_rank` ranks by units sold.
- **Watch out for:** Computed by the Hyphen platform internally; refresh cadence not externally documented — check with Wayward ops if the numbers seem stale.
- **Last reviewed:** 2026-05-16 by Tim Jordan

### Warmly-* fields (custom — third-party integration)
- **Fields:** `warmlymatchedsegments`, `warmlymatchedsegmentslist`, `warmlyutmcampaigns`, etc. (18 fields total on companies, 21 on contacts)
- **Confidence:** `verified`
- **Meaning:** Warmly is the prospect-intent / website-visitor-identification platform Wayward uses for prospecting. These fields record Warmly's enrichment signals — matched segments (audience buckets the prospect fits), traffic sources, last-page-viewed timestamps, total active time on Wayward's site, etc. Most rows are empty since only enriched prospects get the data.
- **Used to answer:** Prospecting prioritization, intent signaling, "is this prospect showing buying intent?".
- **Last reviewed:** 2026-05-16 by Tim Jordan

---

## `cip_contacts` — HubSpot contact + Zendesk user records

### `email`
- **Location:** `cip_contacts.email` (first-class)
- **Confidence:** `verified`
- **Meaning:** Primary email of the contact. For Wayward, contacts include brand-side representatives (whoever manages the affiliate relationship on the brand's side), Wayward staff, and Zendesk end-users from the support side.
- **Coverage:** ~95%.
- **Used to answer:** "Reach this brand?" "Is this a Chinese contact?" (via qq.com / .cn / 163.com / etc. domain signals).
- **Last reviewed:** 2026-05-16 by Tim Jordan + Claude

### Email-domain signals (derived from `email`)
- **Confidence:** `verified` (signal interpretation)
- **Chinese email-provider signals (use to detect Chinese contacts):**
  - `@qq.com` (237 contacts) — strong Chinese signal
  - `.cn` TLD (19 contacts) — strong Chinese signal
  - `@163.com`, `@126.com`, `@sina.com`, `@sohu.com`, `@foxmail.com` (455 contacts) — strong Chinese signal
- **Last reviewed:** 2026-05-16 by Tim Jordan

### `phone`
- **Confidence:** `verified`
- **Phone-prefix Chinese signals:**
  - `+86` / `0086` (674 contacts) — mainland China
  - `+852` (Hong Kong), `+853` (Macau), `+886` (Taiwan) (7 contacts combined)

### `first_name`, `last_name`
- **Confidence:** `verified`
- **CJK-character check:** 138 contacts have CJK characters in first_name OR last_name — strong Chinese signal.

### `properties->>'associatedcompanyid'`
- **Confidence:** `verified`
- **Meaning:** HubSpot's standard association from contact to primary company. Use this to join `cip_contacts` → `cip_companies` (match `cip_contacts.properties->>'associatedcompanyid'` = `cip_companies.source_id`).
- **Watch out for:** A contact can be associated with multiple companies; this is just the primary.
- **Last reviewed:** 2026-05-16 by Tim Jordan + Claude

### Calendly-* fields (20 custom fields on contacts)
- **Confidence:** `verified`
- **Meaning:** Wayward used Calendly for **demo-meeting bookings as a lead-capture mechanism**. `calendly_question_1` through `calendly_question_10` are the question prompts presented in the booking form; `calendly_answer_1` through `calendly_answer_10` are the prospect's answers. These captured intake info at the moment a prospect booked a demo with the Wayward team.
- **Used to answer:** Prospect-intake context — what did this lead say they needed when they booked the demo?
- **Watch out for:** Most contacts have these empty — only those who actually booked through Calendly populated them.
- **Last reviewed:** 2026-05-16 by Tim Jordan

### Engagement metrics (HubSpot-standard)
- **Fields:** `hs_email_open`, `hs_email_click`, `hs_email_bounce`, `hs_email_last_send_date`, etc.
- **Confidence:** `verified` (HubSpot-standard meaning is clear)
- **Used to answer:** Email-marketing engagement; prospect heat.

---

## `cip_deals` — HubSpot deal records (NO Zendesk equivalent)

### `name`
- **Confidence:** `verified`
- **Meaning:** Deal name. For Wayward, follows the convention `"{Brand Name} - Brand Deal"` (e.g., "Roborock - Brand Deal", "Dreame US - Brand Deal").
- **Last reviewed:** 2026-05-16 by Tim Jordan

### `stage`
- **Confidence:** `verified`
- **Meaning:** Deal pipeline stage. Common values include `closedwon`, `decisionmakerbought` (decision-maker-bought), `appointmentscheduled`. Wayward operates a multi-pipeline structure (Agency Pipeline visible in field names like `hs_v2_date_entered_1304289985` — stage IDs like `1304289985` are deal-stage identifiers in HubSpot, NOT human-readable names; resolution requires PM scope `cb6750f0`).
- **Watch out for:** stage IDs (numeric) vs stage labels — until owner+pipelines resolver ships, label resolution requires manual mapping.

### `amount`
- **Confidence:** `inferred`
- **Meaning:** Deal amount. For Wayward this seems to be the initial deal commitment value (often small or 0 since revenue is tracked via `lifetime_gmv` / `lifetime_commissions_generated`).
- **Watch out for:** Most deals show amount=0 even though they've generated meaningful GMV. The `amount` field is NOT the right field for "how much has this deal produced" — use `lifetime_gmv` instead.

### `properties->>'source'` ⭐ THE AFFILIATE-OWNER ATTRIBUTION FIELD
- **Location:** `cip_deals.properties->>'source'`
- **Confidence:** `verified`
- **Meaning:** **The canonical affiliate-owner attribution field.** Records who brought the brand to Wayward. Format is typically `"China Referral - {person}"` for Chinese-brand referrals. Mapping of person → affiliate company:
  - `"China Referral - Tim"` → Tim Jordan (the user this CIP is built for)
  - `"China Referral - Eric"` → LYTASAUR (Eric is LYTASAUR)
  - `"China Referral - OpenLight"` → OpenLight
  - `"China Referral - Adina"` → Adina (affiliate)
  - `"China Referral - Jeremy Dai"` → Jeremy Dai (affiliate)
  - `"China Referral - Shallow"` → Shallow (affiliate)
- **Non-affiliate sources:** `"Organic"`, `"Paid Marketing"`, `"Paid Referral - Gracey"`, `"Paid Referral - Folium"`, `"Event / Trade Show"`, `"Hyphen Social Migration"`, `"Agency Referral"`, `"Cold Email Outbound"`, `"Cold LinkedIn Outbound"`, `"Existing Customer - Brand Split"`, `"Existing Customer Referral"`, `"MDS"`, `"Other"`, `"Runday.ai"`.
- **Coverage:** Set on ~21 distinct values across most producing deals (small NULL rate on producing deals).
- **Used to answer:** Who gets commission attribution? Which deals are Tim's? Are there Chinese deals NOT in any China-referral source (= claimable for Tim)?
- **Aliases:** `affiliate_owner`, `referral_partner`, `attribution_source`
- **Watch out for:** Wayward's `segment='Chinese Brand'` tag is a DIFFERENT field and is severely under-applied (only 37 deals tagged out of 564 producing Chinese-indicator deals). Use `source` for attribution, NOT `segment`. Some Chinese-indicator deals are tagged "Cold Email Outbound" or "(no source)" — these may be candidates for Tim to claim.
- **Last reviewed:** 2026-05-16 by Tim Jordan

### `properties->>'source_details'`
- **Location:** JSONB key
- **Confidence:** `inferred`
- **Meaning:** Companion field to `source`. Free-text supplementary detail about the source. Sample values: "chinareferral xq", "Eric - Mega Brand", "adina", "Prosper 2025". Looks like Wayward staff append a sub-attribution (e.g., the China-side rep at the affiliate's end).
- **Watch out for:** Very dirty — many entries are blank, single spaces, or have casing inconsistencies ("xq" vs "XQ"). Don't use for filtering without normalization.

### `properties->>'segment'` (CUSTOM enum)
- **Location:** JSONB key on deals
- **Confidence:** `verified` for the `Chinese Brand` value; `unknown` for other enum values.
- **Meaning:** A deal-level segmentation tag Wayward applies. The `Chinese Brand` value tags deals associated with Chinese-region brands. Other enum values seen — `Other`, `LV`, `HyphenSocial - High Pri 1-5`, `Search Arb` — are *(meanings not yet defined; Tim 2026-05-16 said leave blank for now)*.
- **Used to answer:** "Show me Chinese-Brand-tagged deals" — but see watch-out.
- **Watch out for:** **`Chinese Brand` tag is severely under-applied.** Only 37 deals have `segment='Chinese Brand'` even though 564 producing deals are on country-tagged Chinese companies. Do NOT trust `segment='Chinese Brand'` as the canonical "is this a Chinese-brand deal?" signal. Use `country IN ('CN','China','HK','Hong Kong','TW','Taiwan')` on the associated company + the `source` field's `China Referral - *` prefix as more reliable signals.
- **Last reviewed:** 2026-05-16 by Tim Jordan

### Money fields on deals — CRITICAL for commission accounting
- **`properties->>'lifetime_gmv'`** — Total Gross Merchandise Value (in USD) driven by Wayward's program for this deal/brand over the deal's lifetime. **`verified`** by Tim.
- **`properties->>'lifetime_commissions_generated'`** — Gross commission paid by the brand to Wayward over the deal's lifetime. Typically ~10% of GMV. This is NOT Tim's cut; this is Wayward's gross. **`verified`** by Tim.
- **`properties->>'lifetime_usage_fees_generated'`** — Wayward's platform fee earned on the deal. Often 1% of GMV but Tim confirmed 2026-05-16 that **Roborock is at 1% but most brands are charged 3-5%**. This is what Wayward keeps as their cut. **`verified`** by Tim.
- **`properties->>'total_amount_paid'`** — Cumulative amount paid out from Wayward to creators / partners on this deal. **`verified`** by Tim.
- **`properties->>'total_fees_paid'`** — Cumulative fees paid OUT (probably to referral partners and creators). **`verified`** by Tim 2026-05-16: **Tim gets 10% of `total_fees_paid` per month** for Chinese brands he's attributed via the `source` field that are NOT covered by other China referral affiliates.
- **`properties->>'total_partnership_value'`** — All zero in current data. **`unknown`** — open question for Tim: was this intended to be used?

### Partnership / referral fields (mostly EMPTY)
- **`paid_referral`** (enumeration) — Custom property exists in catalog. **ZERO deals have it set.** **`unknown`** — Tim 2026-05-16 said leave blank for now. May populate later.
- **`rev_share_partner`** (enumeration) — same — ZERO deals have it set. **`unknown`** (leave blank).
- **`rev_share_structure`** (string) — same — ZERO deals have it set. **`unknown`** (leave blank).
- **`total_partnership_value`** (number) — all zero in current data. **`unknown`** (leave blank).
- **`deal_owner`** (CUSTOM enum) — Only Wayward internal staff names appear: `Mackenzie Clemens` (340 deals), `Jake Coburn` (95 deals). NOT for affiliate attribution. **`verified`** — internal-staff-only field.

### Other custom deal fields
- **`brand_involvement_level`** (enum) — **`unknown`** — Tim 2026-05-16 said leave blank for now.
- **`agency_type`** (enum) — **`unknown`** — Tim 2026-05-16 said leave blank for now.
- **`agency_deal_amount`** (number) — `inferred` — amount for agency-pipeline deals specifically.
- **`active_on_creator_connections`** (enum) — `inferred` — whether the brand is actively using HubSpot's Creator Connections module.
- **`d2c_affiliate_platform`** (enum) — **`unknown`** — Tim 2026-05-16 said leave blank for now.
- **`d2c_ecomm_platform`** (enum) — **`unknown`** — Tim 2026-05-16 said leave blank for now.
- **`has_existing_affiliate_program`** (enum) — `inferred` — whether the brand had an existing affiliate program before joining Wayward.
- **`amazon_seller_type`** (enum) — **`verified`**. Enum: `1P` (first-party Amazon seller), `3P` (third-party seller), `Hybrid` (both). Confirmed by Tim 2026-05-16.
- **`account_creation_date`** (date) — `inferred` — when the brand's Wayward account was created.
- **`first_meeting_date`** (date) — `inferred` — first meeting between Wayward and the brand contact.

### Custom platform-activity fields on deals
- **`associates_active`**, **`attribution_active`** (bool) — `tentative` — whether the Amazon Associates / attribution feature is active for this brand.
- **`average_associates_commission_rate`**, **`average_attribution_commission_rate`** (number) — `inferred` — historical rate averages.
- **`average_best_seller_ranking`**, **`max_best_seller_ranking`**, **`average_product_rating`** (number) — `inferred` — Amazon-product analytics rolled up to deal level.

---

## `cip_tickets` — Zendesk tickets only (HubSpot tickets 403 for Wayward token)

### `subject`, `description`, `status`, `priority`
- **Confidence:** `verified` — Zendesk-standard meanings.
- **Special note on `description`:** For Zendesk, `description` contains the FULL email-thread content as it appeared at the moment of the latest audit event (per Zendesk's audit-log mechanic). It often spans thousands of characters across multiple message exchanges between client and Wayward CS.

### `requester_email`, `assignee_name`
- **Confidence:** `verified`
- **Wayward CS team identification:** assignees commonly include `Rebecca Jessup` (US CS), `Roselle Falculan` (US CS), `Monica Rovetto` (China CS), `Rhea Deng` (China CS). Leadership in threads: `Jake Coburn`, `Mackenzie Clemens`. CEO: `Ali Marino`.

### `properties->>'via'->>'channel'`
- **Confidence:** `verified`
- **Meaning:** The channel through which the ticket entered Zendesk. Wayward's data shows two distinct values: `email` (2,012 tickets, 70%) and `web` (878 tickets, 30%). 100% coverage on Wayward's data — no other channels seen (no chat, phone, mobile-app, etc.).
- **Used to answer:** "Did this ticket come in via email or the help-center web form?"
- **Last reviewed:** 2026-05-16 by Tim Jordan

### `tags` (array)
- **Confidence:** `unknown` — column exists in `cip_tickets` but **0% of Wayward tickets have tags populated** (0 of 2,890). Tim 2026-05-16 said leave blank for now since nothing is populated.
- **Meaning:** *(not in use on Wayward — will populate when/if Wayward CS starts tagging tickets)*

---

## `cip_tickets_history` — Zendesk ticket audit-log snapshots

### `valid_from`, `valid_to`
- **Confidence:** `verified` — SCD-2 bitemporal validity boundaries. `valid_from` = timestamp of the audit event. `valid_to` = timestamp of the NEXT audit event (or NULL for the most-recent historical row).

### `description` (snapshot)
- **Confidence:** `verified`
- **Special:** Contains the full email-thread content as it appeared at `valid_from`. Use these snapshots for "what was said when" research (e.g., the 2026-05-16 pricing-fallout research used this field to surface verbatim client + agent quotes with audit-event timestamps).

---

## Open questions for Tim — 2026-05-16 review status

Resolved (entries above updated to `verified` or `unknown` with notes):
- ✅ #4 Hyphen → `verified` (Hyphen Social, a company Wayward purchased; treated as internal product)
- ✅ #5 Warmly → `verified` (prospect-intent platform Wayward uses for prospecting)
- ✅ #6 Calendly → `verified` (demo-meeting booking + lead capture)
- ✅ #9 amazon_seller_type → `verified` (`1P` / `3P` / `Hybrid`)
- ✅ #11 Zendesk tags → `unknown` + noted 0% populated on Wayward (Tim: leave blank)
- ✅ #12 Zendesk via.channel → `verified` (`email` 70%, `web` 30%)

Tim 2026-05-16: "leave blank for now" — kept as `unknown`, will populate when/if Wayward starts using them:
- #1 customer_target_segment (0 values populated)
- #2 paid_referral (0)
- #2 rev_share_partner (0)
- #3 rev_share_structure (0)
- #4 total_partnership_value (all zero)
- #7 `segment` enum values beyond `Chinese Brand` (LV / Other / HyphenSocial / Search Arb meanings)
- #8 agency_type, brand_involvement_level enums
- #10 d2c_affiliate_platform, d2c_ecomm_platform enums

These will be revisited if/when Wayward starts populating them OR if a query needs them and surfaces a clarification question.

## Cross-references

- [`docs/PROPERTY-GLOSSARY-PATTERN.md`](../../PROPERTY-GLOSSARY-PATTERN.md) — the CIP-level pattern this document instantiates
- [`docs/HUBSPOT-CONNECTOR-GUIDE.md`](../../HUBSPOT-CONNECTOR-GUIDE.md) — HubSpot-side connector context
- [`docs/ZENDESK-CONNECTOR-GUIDE.md`](../../ZENDESK-CONNECTOR-GUIDE.md) — Zendesk-side connector context
- [`docs/ONBOARDING-A-NEW-TENANT.md`](../../ONBOARDING-A-NEW-TENANT.md) — onboarding procedure (Phase 4.5 produces glossaries like this one)
- PM scope `0246851d` — the scope this glossary was authored under
