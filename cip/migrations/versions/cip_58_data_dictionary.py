# foundry: kind=migration domain=client-intelligence-platform
"""cip_58: the data dictionary. Every column says what it means.

Tim, 2026-07-13: "make sure all the new info you found in stripe matches to a field with
description in DB, and everything is correct."

310 of 344 columns had no description. Whole tables — ps_payment_events, ps_brands,
ps_brand_observations, ps_rate_cards — had none at all. A field with no description is a field
the next reader has to guess at, and in THIS schema the guesses are expensive and specific:

  * commission_fees_paid is 4.6x larger than usage_fees_paid and is NOT what we earn on. Anyone
    reaching for the bigger number is off by 460%. It has already happened once.
  * `amount` is DOLLARS, not Stripe's integer cents. Divide by 100 and you understate by 100x.
    That has already happened once too, in this same session.
  * billing_month is the month the usage is FOR, not the cycle it was billed in. They differ by
    one to seven months, and the 10/6/3 step-down is month-sensitive.
  * NULL means "we do not know" and must never become a number. A sentinel like 'unassigned'
    means "we know there is none" and legitimately IS zero. Confusing the two is what turned
    unknown rates into confident $0.00 payouts.

This migration writes no data and changes no structure. It records what the schema MEANS, at the
point of use, so the trap is met at the field rather than in a document nobody opens.

Revision ID: cip_58_data_dictionary
Revises: cip_57_stripe_customers
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_58_data_dictionary"
down_revision: str | Sequence[str] | None = "cip_57_stripe_customers"
branch_labels = None
depends_on = None

# Shared column meanings — the same field appears across many tables.
_COMMON = {
    "id": "Surrogate primary key (UUID v4).",
    "tenant_id": "Tenant scope. Every query must filter on it (D-026). Project Silk.",
    "created_at": "When this row was created.",
    "updated_at": "When this row was last changed.",
    "ingested_at": "When a connector last wrote this row from its source system.",
    "client_id": (
        "cip_clients surrogate. A CONVENIENCE JOIN, NOT the identity — it only exists for brands "
        "that arrived through the PS lens mirror (~65%). Key money on wayward_brand_id instead; "
        "keying it on client_id is what left $1.25M of collected usage unpriced."
    ),
    "wayward_brand_id": (
        "THE identity. Every source speaks it: Stripe (customer metadata.brandId, or the "
        "description field), the Slack onboarding feed, Jake's reports, the frozen exclusion "
        "list, Eric's sheets. FK to ps_brands."
    ),
    "product_id": "Which product this row is about: 'connect' or 'boost'. They have SEPARATE clocks and separate economics.",
    "source_ref": "Provenance: the exact file, message, sheet row or invoice this came from. How we prove it.",
    "notes": "Free-text human note.",
    "status": "Lifecycle state of this row.",
    "brand_name": "Brand name as the source system spelled it. Display only — never join on it.",
}

TABLES: dict[str, dict] = {
    # ── the master ────────────────────────────────────────────────────────
    "ps_brands": {
        "__table__": (
            "THE BRAND MASTER. One row per wayward_brand_id, which is the primary key. Before "
            "cip_55 no such table existed and wayward_brand_id was a loose UUID across 12 tables "
            "with no FK to anything — which is how identity coverage sat at 65/78/75% and nobody "
            "noticed. Now an unnameable brand is a constraint violation instead of a silent $0."
        ),
        "wayward_brand_id": "PRIMARY KEY. Wayward's own brand id — the one identifier every source agrees on.",
        "tenant_id": _COMMON["tenant_id"],
        "brand_name": _COMMON["brand_name"],
        "client_id": _COMMON["client_id"],
        "seen_in_stripe": "This brand appears in Stripe (customer metadata or description).",
        "seen_in_slack_feed": "This brand appears in the #amazon-brand-connections onboarding feed.",
        "seen_in_payment_reports": "This brand appears in Jake's monthly payment reports.",
        "seen_in_exclusion_list": "This brand is on the FROZEN exclusion list of 2025-11-18.",
        "seen_in_eric_sheets": "This brand appears in Eric's all-agreements sheet.",
        "first_seen_at": "When we first learned this brand exists, from any source.",
        "updated_at": _COMMON["updated_at"],
    },
    # ── the evidence store ────────────────────────────────────────────────
    "ps_brand_observations": {
        "__table__": (
            "APPEND-ONLY EVIDENCE. Facts as each source stated them, never resolved against each "
            "other. A DB trigger blocks UPDATE and DELETE. If Slack says a brand is Chinese and "
            "HubSpot says it is not, BOTH rows live here and neither wins — resolution happens in "
            "the decision layer, which writes to a separate column and records its reasoning. "
            "This separation is the whole point: it is what lets us show WHY we believe something."
        ),
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "subject_type": "What the observation is about (brand, partner, ...).",
        "wayward_brand_id": _COMMON["wayward_brand_id"],
        "client_id": _COMMON["client_id"],
        "field": "Which attribute was observed — e.g. 'country', 'email', 'usage_fee', 'referral_partner'.",
        "value": "The value EXACTLY as the source stated it. Never cleaned, never corrected.",
        "value_normalized": "A normalized form for matching. CJK-safe — the canonicaliser must never return empty (it once collapsed 雪球 to nothing and nearly deleted a partner).",
        "source_system": "Who said it: 'slack:amazon-brand-connections', 'gsheet:eric-all-agreements', 'stripe', 'hubspot'...",
        "source_ref": _COMMON["source_ref"],
        "observed_at": "When the SOURCE asserted this (not when we ingested it).",
        "ingested_at": _COMMON["ingested_at"],
    },
    # ── Jake's monthly payment reports ────────────────────────────────────
    "ps_payment_events": {
        "__table__": (
            "Jake's monthly payment reports, one row per brand per month. This is what Wayward "
            "SAYS it paid us, and under contract §4.4 Wayward's records are 'conclusive and "
            "controlling' — so this table is the other side of every claim we might make."
        ),
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "client_id": _COMMON["client_id"],
        "customer_id": "Stripe customer id as Jake's report gave it.",
        "wayward_brand_id": _COMMON["wayward_brand_id"],
        "brand_name": _COMMON["brand_name"],
        "payment_date": "The month this report row covers.",
        "signup_date": "When the brand signed up, per Jake.",
        "stripe_invoice_ids": "The Stripe invoices Jake says back this row. Our audit trail into Stripe.",
        "stripe_invoice_links": "Hosted links to those invoices.",
        "commission_fees_paid": (
            "*** NOT OUR BASE. THE CENTRAL TRAP OF THIS ENTIRE DATASET. *** Commission fees are "
            "CREATOR PAY passing through Wayward to influencers. They are ~4.6x larger than usage "
            "fees ($13.6M vs $2.97M all-time), which makes them the number everyone instinctively "
            "reaches for. We earn NOTHING on them. Use usage_fees_paid."
        ),
        "usage_fees_paid": (
            "*** THIS IS OUR BASE. *** The usage fee the BRAND pays Wayward — Connect (fee% of "
            "GMV) and Boost (10% of ad spend) COMBINED; Jake's report does not split them. PS is "
            "owed 10% of THIS, stepping down to 6% then 3%. Everything we are owed derives from "
            "this column and no other."
        ),
        "saas_fees_paid": "Wayward's SaaS/platform fee. Not our base.",
        "cc_processing_fees_paid": "Card processing costs. Not our base.",
        "total_amount_paid": "Everything the brand paid, all fee types. NOT our base — it is dominated by creator pass-through.",
        "rev_share_stated": "The rev-share figure Jake's report states for this brand-month.",
        "rev_share_computed": "What the same report's own numbers compute to. Where it disagrees with rev_share_stated, that is a dispute item.",
        "rev_share_variance": "stated minus computed. Non-zero = Wayward's arithmetic disagrees with itself.",
        "months_from_signup": "Months elapsed since signup, per Jake.",
        "rev_share_start_date": (
            "WAYWARD'S STATED productive date for this brand — when rev share starts. 289 brands "
            "state one and all 289 agree across every month they appear in. Copied to "
            "ps_product_subscriptions.productive_date_wayward. Under §4.4 this is the controlling "
            "date, so where it disagrees with our own computed productive_date, that gap is a "
            "dispute item, which is exactly why they are two separate columns."
        ),
        "days_since_start": "Days since rev_share_start_date, per Jake.",
        "source_ref": _COMMON["source_ref"],
        "ingested_at": _COMMON["ingested_at"],
    },
    # ── Stripe ────────────────────────────────────────────────────────────
    "ps_stripe_invoices": {
        "__table__": "Stripe invoice headers — what Wayward BILLED each brand, and what was actually collected.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "stripe_invoice_id": "Stripe's invoice id (in_...). The natural key.",
        "stripe_customer_id": "Stripe customer (cus_...). FK-ish to ps_stripe_customers. NOTE one brand may bill through several customers.",
        "wayward_brand_id": _COMMON["wayward_brand_id"],
        "client_id": _COMMON["client_id"],
        "customer_email": "Customer email as Stripe holds it.",
        "customer_name": "Customer display name. Often the brand, not always.",
        "status": "Stripe invoice status: paid, open, void, uncollectible, draft.",
        "paid": "Stripe's own paid flag.",
        "collection_method": "charge_automatically or send_invoice.",
        "amount_due": "Billed. IN DOLLARS — the ingest already converted from Stripe's integer cents. Do NOT divide by 100.",
        "amount_paid": "COLLECTED. In dollars. We are paid on what is collected, not on what is billed.",
        "amount_remaining": "Billed but NOT collected. amount_due - amount_paid.",
        "subtotal": "Before tax/discount. In dollars.",
        "total": "Invoice total. In dollars.",
        "currency": "Invoice currency.",
        "invoice_number": "Human-readable invoice number.",
        "hosted_invoice_url": "Stripe's hosted copy. The receipt we can show Wayward.",
        "created_at_stripe": "When Stripe created the invoice — the BILLING CYCLE, not the usage month.",
        "period_start": "Stripe's billing period start. NOT the usage month (see invoice_lines.billing_month).",
        "period_end": "Stripe's billing period end.",
        "due_date": "When payment was due.",
        "ingested_at": _COMMON["ingested_at"],
    },
    "ps_stripe_invoice_lines": {
        "__table__": (
            "Stripe invoice LINE ITEMS — the finest grain of money we hold, and the spine of every "
            "figure we claim. Read is_ps_base before reading amount: most of the money on this "
            "table is creator pass-through we earn nothing on."
        ),
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "stripe_invoice_id": "Parent invoice.",
        "stripe_line_id": "Stripe's line id. The natural key.",
        "wayward_brand_id": _COMMON["wayward_brand_id"],
        "client_id": _COMMON["client_id"],
        "description": (
            "Stripe's line text, VERBATIM. Shaped '<Month [Year]> - <channel or brand> - <fee "
            "type>'. It is the ONLY place the usage month is stated, and the only reliable "
            "product signal: a line is Boost if and only if it says 'Boosted' — verified across "
            "all 75,658 lines. Anything else is Connect."
        ),
        "currency": "Line currency.",
        "quantity": "Stripe line quantity.",
        "channel": "Sales channel parsed from the description, where the line names one.",
        "fee_type": "Parsed fee type: usage, commission, saas, processing, reconciliation.",
        "product_id": "'connect' or 'boost', parsed from the description. Boost is ALWAYS explicitly labelled 'Boosted'; absence of that word means Connect.",
        "invoice_status": "Status copied from the parent invoice, so a line can be filtered to COLLECTED money without a join.",
        "line_period_start": (
            "Stripe's period for this line — the BILLING CYCLE. *** NOT the usage month. *** The "
            "lag is not constant: 18,820 lines lag one month, 5,050 lag two, reconciliation lines "
            "lag up to seven. Use billing_month. Deriving the month from this field misdates most "
            "rows and silently moves brands into the wrong 10/6/3 rate tier."
        ),
        "line_period_end": "Stripe's period end for this line. Same caveat as line_period_start.",
        "ingested_at": _COMMON["ingested_at"],
    },
    # ── partners ──────────────────────────────────────────────────────────
    "ps_partner_registry": {
        "__table__": "The canonical partner roster. One row per real partner; ps_partner_aliases maps the many spellings onto it.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "partner_id": "Canonical partner key. 'unassigned' is a REAL row meaning a DECISION that nobody is credited — not a gap. PS keeps the full 10%.",
        "name": "Partner's person name.",
        "contact": "Legacy free-text contact. Prefer ps_partner_contacts.",
        "channel": "How they reach brands.",
        "default_rate": "Their usual % of the usage-fee base, when no per-product term overrides it.",
        "payment_method": "How we pay them.",
        "status": _COMMON["status"],
        "notes": _COMMON["notes"],
        "created_at": _COMMON["created_at"],
        "company_name": "Partner's company — e.g. Sarah = S姐联盟营销, Kerry = Snowball (雪球 / Xueqiu).",
        "country": "Where the partner operates.",
    },
    "ps_partner_terms": {
        "__table__": "What each partner earns, PER PRODUCT. Their cut comes OUT of our 10, not on top of it — if they take 5, we net 5.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "partner_id": "Which partner. '_default' is the fallback row (5%).",
        "product_id": _COMMON["product_id"],
        "commission_basis": "What their % applies to — the usage-fee base, same base we are paid on.",
        "credit_window_months": "How long they keep earning. 12 months from the brand's productive date, then they roll off and our net RISES (5%->6%), because our own step-down lands at the same moment. The clocks are aligned by design.",
        "effective_from": "Term start.",
        "effective_to": "Term end. NULL = current.",
        "contract_ref": "The contract this term comes from.",
        "notes": _COMMON["notes"],
        "created_at": _COMMON["created_at"],
    },
    "ps_partner_credit": {
        "__table__": "WHO is credited for a brand on a product, and on what deal. Attribution, deal type and PS ownership are three INDEPENDENT axes — do not collapse them.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "client_id": _COMMON["client_id"],
        "product_id": _COMMON["product_id"],
        "referral_detail_raw": "The referral text exactly as the source stated it, before canonicalisation.",
        "credit_start": "When the partner's 12-month earning window opens — the brand's productive date on THIS product.",
        "credit_end": "credit_start + 12 months. The partner rolls off here.",
        "partner_rate": "The partner's % of the usage-fee base. 0 for flat_fee brands (paid once, earns nothing ongoing) and for 'unassigned' (nobody credited). Those zeros are DECISIONS, not gaps.",
        "determined_by": "Which rule or human decided this. Decisions are never anonymous.",
        "determined_at": "When it was decided.",
        "determination_note": "WHY. The rationale, in prose, so a human can audit the decision without reading code.",
        "created_at": _COMMON["created_at"],
        "flat_fee_paid_at": "When the one-off flat fee was paid (Eric's book). After this, nothing further is owed on that brand.",
        "match_note": "How confidently the partner was matched, and on what evidence.",
    },
    "ps_partner_contacts": {
        "__table__": "People at each partner. WeChat is first-class here — it is how these partners actually communicate.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "partner_id": "Which partner.",
        "name": "Contact name.",
        "role": "Their role.",
        "email": "Email.",
        "phone": "Phone.",
        "wechat": "WeChat ID. The primary channel for Chinese partners; being requested from Jake for brands too.",
        "is_primary": "The main contact for this partner.",
        "status": _COMMON["status"],
        "notes": _COMMON["notes"],
        "created_at": _COMMON["created_at"],
        "updated_at": _COMMON["updated_at"],
    },
    "ps_partner_aliases": {
        "__table__": "Every spelling a partner has ever been written as, mapped to one canonical partner. This is the anti-double-count table: 236 raw spellings collapse to 155 real partners.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "partner_id": "The canonical partner this spelling means.",
        "alias_value": "The raw spelling as it appeared. CJK preserved — 雪球 IS Xueqiu IS Snowball IS Kerry's company, and a canonicaliser that strips CJK once nearly deleted that partner entirely.",
        "alias_kind": "What kind of alias: name, company, handle, email.",
        "source": "Where this spelling was seen.",
        "notes": _COMMON["notes"],
        "created_at": _COMMON["created_at"],
    },
    "ps_attribution": {
        "__table__": "PS-side ownership of a brand (who sourced it, who runs it). DISTINCT from partner credit and from deal type.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "client_id": _COMMON["client_id"],
        "product_id": _COMMON["product_id"],
        "ps_attribution_owner": "Who at PS owns this brand.",
        "ps_lead_source": "Where the lead came from.",
        "ps_conditional": "Any condition attached to the attribution.",
        "ps_sales_lead": "PS sales lead.",
        "ps_cs_lead": "PS customer-success lead.",
        "effective_from": "Attribution start.",
        "effective_to": "Attribution end. NULL = current.",
        "changed_by": "Who changed it.",
        "change_reason": "Why it changed.",
        "created_at": _COMMON["created_at"],
    },
    # ── eligibility & the frozen list ─────────────────────────────────────
    "ps_excluded_brands": {
        "__table__": (
            "THE FROZEN EXCLUSION LIST. 807 brand ids, exactly as Jake sent them on 2025-11-18 — "
            "the operative line. Everything onboarded AFTER that date is ours automatically, "
            "whatever the referral source, provided it is Chinese. Recovered from the original "
            "Slack upload, which is why these are exact ids and not fuzzy name matches (name "
            "matching only ever found 224 of them)."
        ),
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "wayward_brand_id": _COMMON["wayward_brand_id"],
        "client_id": _COMMON["client_id"],
        "brand_name": _COMMON["brand_name"],
        "bucket": "Which exclusion bucket: the 10%-deal partners, or Eric's FLAT FEE book.",
        "referrer": "Who the exclusion credits.",
        "eligible_for_10_rev_share": "True = this brand sits on a 10% partner deal. False = Eric flat fee, which we CAN win back.",
        "frozen_at": "2025-11-18 — the date the list was frozen. The whole audit turns on this date.",
        "source_ref": _COMMON["source_ref"],
        "created_at": _COMMON["created_at"],
    },
    "ps_reactivation_rights": {
        "__table__": "Brands we can WIN BACK. A flat-fee brand becomes ours on Connect if we negotiate its fee up, and ANY flat-fee brand is ours on Boost — Boost is a net-new product nobody holds.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "client_id": _COMMON["client_id"],
        "wayward_brand_id": _COMMON["wayward_brand_id"],
        "product_id": _COMMON["product_id"],
        "status": "Where this win-back stands.",
        "claimed_at": "When we claimed it.",
        "won_at": "When we won it.",
        "blocked_reason": "Why we cannot claim it — e.g. Eric is specifically attributed on Boost for this brand.",
        "rationale": "Why this brand is (or is not) winnable.",
        "decided_by": "Who decided.",
        "decided_at": "When.",
        "created_at": _COMMON["created_at"],
        "updated_at": _COMMON["updated_at"],
    },
    # ── the clock ─────────────────────────────────────────────────────────
    "ps_product_subscriptions": {
        "__table__": "One row per brand x PRODUCT. Connect and Boost have SEPARATE clocks: a brand can be at 6% on Connect and 10% on Boost simultaneously.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "client_id": _COMMON["client_id"],
        "product_id": _COMMON["product_id"],
        "status": _COMMON["status"],
        "adopted_date": "When the brand adopted this product. NOT the productive date — onboarding is not revenue.",
        "churned_date": "When they left.",
        "adoption_driven_by": "Who drove adoption.",
        "created_at": _COMMON["created_at"],
        "updated_at": _COMMON["updated_at"],
        "dormant_since": "No sales through the platform since this date. 90 days dormant on Connect makes the brand winnable by another partner.",
        "dormancy_evaluated_at": "When dormancy was last computed. Dormancy is derived at READ time from activity, never frozen into a stale flag.",
        "productive_date_confidence": "How sure we are of OUR productive date.",
        "productive_date_note": "How we arrived at it.",
        "productive_date_wayward": (
            "WAYWARD'S STATED productive date (Jake's Rev Share Start Date). Deliberately a "
            "SEPARATE column from our computed productive_date: under §4.4 Wayward's records are "
            "'conclusive and controlling', so where the two disagree, that disagreement is the "
            "dispute — and collapsing them into one column would erase it."
        ),
        "first_billed_month": "The first month Stripe actually billed this brand. Eligibility keys off THIS, not onboarding.",
    },
    # ── the money spine ───────────────────────────────────────────────────
    "ps_monthly_earnings": {
        "__table__": (
            "THE MONEY SPINE. One row per brand x product x month: what was billed, what was "
            "collected, our rate, what we are owed, what the partner is owed, what we were "
            "actually paid, and the variance. Named 'earnings' rather than 'commission' on "
            "purpose — 'commission' in this dataset means creator pass-through, which is the one "
            "thing we do NOT earn on."
        ),
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "client_id": _COMMON["client_id"],
        "wayward_brand_id": _COMMON["wayward_brand_id"],
        "brand_name": _COMMON["brand_name"],
        "product_id": _COMMON["product_id"],
        "period_month": "The month this row is FOR (always the 1st). The usage month, not the billing cycle.",
        "months_since_productive": "Months elapsed since the brand's productive date on this product. This is what drives the 10 -> 6 -> 3 step-down.",
        "partner_id": "Partner credited this month. 'unassigned' means a DECISION that nobody is credited, so PS keeps the full rate.",
        "partner_rate_pct": "Partner's % of the base. COALESCEd to 0 deliberately: 'unassigned' is a real decision meaning zero, not an unknown.",
        "ps_actually_paid": "What Wayward ACTUALLY paid us, from Jake's reports. The other side of the variance.",
        "eligibility": "Whether this brand-month is ours to claim.",
        "excluded_bucket": "If excluded, which bucket — and therefore whether it is winnable.",
        "is_chinese": "The nationality DECISION. Written only by the decision layer, never by ingestion.",
        "computed_at": "When this row was derived.",
        "ps_net_owed": (
            "What we keep: our gross minus the partner's cut. GENERATED. Deliberately NOT "
            "COALESCEd on the rate — if the rate is unknown this stays NULL and propagates. "
            "The old COALESCE(rate,0) turned every unknown into a confident $0.00 and reported "
            "it as fact."
        ),
    },
    # ── rate cards, products, claims, and the rest ────────────────────────
    "ps_rate_cards": {
        "__table__": "The rate tiers. PS: 10% for months 1-12, 6% for 13-18, 3% from 19 on — measured from each brand's PRODUCTIVE date, per product.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "kind": "Which kind of rate this row describes.",
        "client_id": _COMMON["client_id"],
        "product_id": _COMMON["product_id"],
        "fee_structure": "How the brand's own fee to Wayward is structured.",
        "rate": "The rate itself.",
        "rate_base": "What the rate applies to. For PS this is always the USAGE FEE, never commission.",
        "currency": "Currency.",
        "commission_pct": "The percentage.",
        "commission_base": "What the percentage applies to.",
        "tier_rule": "Which tier this is and when it applies (months 1-12 / 13-18 / 19+).",
        "effective_from": "Tier start.",
        "effective_to": "Tier end.",
        "source": "Which contract clause this comes from.",
        "created_at": _COMMON["created_at"],
    },
    "ps_products": {
        "__table__": "The two products. Connect (fee% of GMV) and Boost (10% of ad spend). Different bases, separate clocks, separate partner terms.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "product_id": "'connect' or 'boost'.",
        "name": "Display name.",
        "fee_basis": "What Wayward charges the brand on — GMV for Connect, ad spend for Boost. Our 10% is 10% of THAT fee, not of the underlying GMV.",
        "notes": _COMMON["notes"],
        "created_at": _COMMON["created_at"],
    },
    "ps_information_gaps": {
        "__table__": "The QUESTION QUEUE. Every unknown that blocks a decision becomes a routed, answerable question rather than a silent NULL. This is what makes 'we do not know' actionable.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "client_id": _COMMON["client_id"],
        "wayward_brand_id": _COMMON["wayward_brand_id"],
        "subject_label": "Human-readable subject of the question.",
        "gap_type": "What kind of unknown this is.",
        "question": "The question, phrased so it can be asked verbatim.",
        "context": "What we already know, so whoever answers does not start from zero.",
        "ask_who": "Who can answer — Jake, Ali, Eric, a partner, or us.",
        "ask_channel": "Where to ask.",
        "status": "open / asked / answered.",
        "priority": "How much turns on it.",
        "asked_at": "When we asked.",
        "asked_by": "Who asked.",
        "asked_ref": "The message or email in which we asked.",
        "answered_at": "When it was answered.",
        "answered_by": "Who answered.",
        "answer": "The answer, verbatim.",
        "created_at": _COMMON["created_at"],
        "updated_at": _COMMON["updated_at"],
    },
    "ps_claims": {
        "__table__": "Claims we put to Wayward. Note §4.4: their records are conclusive and controlling, and there is a 30-day dispute window — so a claim must be evidenced and timely.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "claim_number": "Our reference for the claim.",
        "submitted_to": "Who at Wayward it went to.",
        "submitted_at": "When. Starts the 30-day clock.",
        "resolution_amount": "What was actually agreed.",
        "resolution_notes": "How it was resolved.",
        "created_at": _COMMON["created_at"],
        "updated_at": _COMMON["updated_at"],
    },
    "ps_claim_lines": {
        "__table__": "The individual brand-months making up a claim. Every line must trace to a source_ref, or it is not claimable.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "claim_id": "Parent claim.",
        "client_id": _COMMON["client_id"],
        "product_id": _COMMON["product_id"],
        "period_month": "The month claimed.",
        "amount": "Amount claimed, in dollars.",
        "note": "Why we say we are owed it.",
        "source_ref": _COMMON["source_ref"],
        "created_at": _COMMON["created_at"],
    },
    "ps_brand_contacts": {
        "__table__": "People at each brand. WeChat is first-class — Jake has been asked to capture it at onboarding.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "client_id": _COMMON["client_id"],
        "wayward_brand_id": _COMMON["wayward_brand_id"],
        "name": "Contact name.",
        "role": "Their role at the brand.",
        "email": "Email.",
        "phone": "Phone.",
        "is_primary": "The main contact.",
        "status": _COMMON["status"],
        "source": "Where we learned of this contact.",
        "source_ref": _COMMON["source_ref"],
        "notes": _COMMON["notes"],
        "created_at": _COMMON["created_at"],
        "updated_at": _COMMON["updated_at"],
    },
    "ps_classification_rules": {
        "__table__": "Weighted signals used by the decision layer. Rules live in DATA, not in code, so a decision can be re-explained later without reading a diff.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "signal": "What the rule looks at.",
        "pattern": "The pattern it matches.",
        "weight": "How much it counts.",
        "notes": _COMMON["notes"],
        "created_at": _COMMON["created_at"],
    },
    "ps_annotations": {
        "__table__": "Human notes against any row. Where a person's judgement gets recorded without overwriting the evidence.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "entity_type": "What is being annotated.",
        "entity_id": "Which row.",
        "note_type": "What kind of note.",
        "body": "The note.",
        "author": "Who wrote it.",
        "source_ref": _COMMON["source_ref"],
        "created_at": _COMMON["created_at"],
    },
    "ps_ingestion_staging": {
        "__table__": "Proposed writes awaiting approval. Lets an agent PROPOSE a change to the money tables without being able to make it.",
        "id": _COMMON["id"],
        "tenant_id": _COMMON["tenant_id"],
        "batch_id": "Groups a proposal set.",
        "target_table": "Where it would land.",
        "row_action": "insert / update / delete.",
        "payload": "The proposed row.",
        "approved_by": "Who approved.",
        "approved_at": "When.",
        "applied_at": "When it was actually written.",
        "created_at": _COMMON["created_at"],
    },
}


def _q(s: str) -> str:
    return s.replace("'", "''")


def upgrade() -> None:
    for table, cols in TABLES.items():
        for col, doc in cols.items():
            if col == "__table__":
                op.execute(f"COMMENT ON TABLE {table} IS '{_q(doc)}'")
            else:
                op.execute(f"COMMENT ON COLUMN {table}.{col} IS '{_q(doc)}'")


def downgrade() -> None:
    # Descriptions are documentation. Removing them loses knowledge and restores nothing,
    # so downgrade only drops the TABLE-level comments to keep the migration reversible in
    # form without deliberately destroying the column dictionary.
    for table in TABLES:
        op.execute(f"COMMENT ON TABLE {table} IS NULL")
