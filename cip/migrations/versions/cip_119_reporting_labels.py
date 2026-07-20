# foundry: kind=migration domain=client-intelligence-platform
"""cip_119: schema hardening + reporting labels (pre-dashboard audit adjustments).

From the 2026-07-20 schema/math/labeling audit before the reporting build. All
ADDITIVE (RLS force + COMMENTs) — no data or verdict change; recovery unchanged.

FIXES
-----
1. RLS consistency: 3 tables (ps_added_facts, ps_nationality_signals,
   ps_stripe_customers) had RLS ENABLED but not FORCED; 36/39 siblings are forced.
   Force them (they already carry the correct *_tenant policy) — defense-in-depth.
2. H1 (report-corrupting): 10 tables' product_id COMMENT said "'connect' or 'boost'"
   but the stored value is 'boosted'. A `WHERE product_id='boost'` filter returns
   ZERO rows -> a silently empty Boost report. Correct all of them.
3. H2: undocumented CRM/HubSpot-derived china_* lenses shadow the money lenses;
   commission_10pct_of_paid is a naive flat 10% (no 6/3 ladder, eligibility, or
   refund-netting). Comment them so nobody charts a CRM number as the claim.
4. H3: the dashboard reads the LENSES, which were column-comment-bare. Comment the
   key money-lens columns (units, gross/net, what-if warnings).
5. H4: ps_partner_payouts comments pointed at ps_monthly_earnings (dropped in
   cip_110). Repoint to the live lenses.
6. M2/M3: comment the overloaded `amount` on the Stripe cash tables, and warn that
   lens_ps_brand_revenue.revenue_amount is GMV(connect)/ad-spend(boosted) — not
   summable across products.

Revision ID: cip_119_reporting_labels
Revises: cip_118_stripe_cash_recon
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_119_reporting_labels"
down_revision: str | Sequence[str] | None = "cip_118_stripe_cash_recon"
branch_labels = None
depends_on = None

# 1. RLS force (already ENABLED with a *_tenant policy; align with the 36 siblings).
_RLS_FORCE = ("ps_added_facts", "ps_nationality_signals", "ps_stripe_customers")

# 2. H1 — product_id is 'connect' | 'boosted' (NOT 'boost'). FK tables + the catalog.
_PRODUCT_FK = (
    "ps_stripe_invoice_lines", "ps_partner_terms", "ps_attribution",
    "ps_reactivation_rights", "ps_product_subscriptions", "ps_rate_cards",
    "ps_claim_lines", "ps_partner_credit", "ps_added_facts",
)

# 3+4. COMMENT ON COLUMN <target> IS <body>  (dollar-quoted bodies)
_COL_COMMENTS: tuple[tuple[str, str], ...] = (
    # H3 — lens_ps_claim (THE invoice / recovery lens)
    ("lens_ps_claim.mgmt_fee_owed",
     "What Wayward owes us on this brand: usage_collected x the 10/6/3 ladder, "
     "gross of payments. USD."),
    ("lens_ps_claim.wayward_paid", "What Wayward has already paid us for this brand. USD."),
    ("lens_ps_claim.ps_claim_owed",
     "THE recovery number: GREATEST(mgmt_fee_owed - wayward_paid, 0), floored per "
     "brand. Sum over verdict='china' = the total still owed. USD."),
    ("lens_ps_claim.partner_claim_owed", "Still owed to the partner of record: "
     "GREATEST(partner_fee_owed - partner_paid, 0). USD."),
    # H3 — lens_ps_commission_ledger (the per brand x product x month detail)
    ("lens_ps_commission_ledger.usage_billed",
     "Usage fee invoiced (paid+open, voids excluded), GROSS - a refund does not "
     "un-bill. billed >= collected. USD."),
    ("lens_ps_commission_ledger.usage_collected",
     "Usage fee the client actually PAID, NET of succeeded refunds (cip_113). Our "
     "commission base. USD."),
    ("lens_ps_commission_ledger.mgmt_rate",
     "The 10/6/3 ladder rate for this brand x product x month (0.10 / 0.06 / 0.03)."),
    ("lens_ps_commission_ledger.mgmt_fee_owed", "usage_collected x mgmt_rate. USD."),
    ("lens_ps_commission_ledger.partner_fee_owed",
     "What we pass the referral partner (partner_rate_pct of the usage fee), carved "
     "from our commission. USD."),
    # H3 — lens_ps_monthly_summary (the trend line)
    ("lens_ps_monthly_summary.net_owed",
     "mgmt_fee_owed - partner_fee_owed = what WE keep for the month x product. USD."),
    ("lens_ps_monthly_summary.collected_claimable",
     "usage_collected restricted to claimable brand-months. USD."),
    # M3 — lens_ps_brand_revenue (data asset)
    ("lens_ps_brand_revenue.revenue_amount",
     "connect = GMV, boosted = ad-spend - DIFFERENT bases, do NOT sum across "
     "products. NULL where rate_missing=true (no client fee rate yet). USD."),
    ("lens_ps_brand_revenue.revenue_type", "'gmv' (connect) or 'ad_spend' (boosted)."),
    ("lens_ps_brand_revenue.rate_missing",
     "true = no wayward_client_fee_rate, so revenue_amount is NULL (surfaced, not zero)."),
    # H3 — lens_ps_china_verdict money columns (distinct vocab from lens_ps_claim)
    ("lens_ps_china_verdict.hypothetical_if_all_claimable",
     "WHAT-IF ONLY: owed if every unknown-nationality brand were claimable. NOT a "
     "real claim - never report as owed."),
    ("lens_ps_china_verdict.ps_owed_claimable",
     "Owed on claimable brand-months only (different scope/floor than "
     "lens_ps_claim.ps_claim_owed - prefer lens_ps_claim for THE number). USD."),
    ("lens_ps_china_verdict.usage_collected",
     "Collected usage fee for the brand, net of refunds. USD."),
    # M2 — Stripe cash tables: the overloaded `amount`
    ("ps_stripe_charges.amount", "GROSS amount charged to the card (= net + fee). USD."),
    ("ps_stripe_charges.fee", "Stripe processing fee on the charge (from the ledger). USD."),
    ("ps_stripe_charges.net", "Cash after the Stripe fee (amount - fee). USD."),
    ("ps_stripe_balance_transactions.amount", "Gross of the money movement. USD."),
    ("ps_stripe_balance_transactions.net", "amount - fee for this ledger entry. USD."),
    ("ps_stripe_payouts.amount", "Cash paid out to Wayward's bank in this payout. USD."),
    ("ps_stripe_refunds.amount", "Refund amount (positive). USD."),
    ("ps_stripe_disputes.amount", "Disputed (charged-back) amount. USD."),
    # H4 — ps_partner_payouts: repoint the dead ps_monthly_earnings references
    ("ps_partner_payouts.wayward_brand_id",
     "Brand - join to lens_ps_commission_ledger for partner_fee_owed."),
    ("ps_partner_payouts.period_month",
     "Billing month - align with lens_ps_commission_ledger.period_month."),
)

# H2 — CRM/HubSpot-derived china_* lenses (NOT the money engine) + missing view comments
_VIEW_COMMENTS: tuple[tuple[str, str], ...] = (
    ("lens_ps_china_commission",
     "CRM/HubSpot-derived china summary (from cip_deals). commission_10pct_of_paid "
     "is a NAIVE flat 10% of paid - NOT the money engine (ignores the 6/3 step-down, "
     "per-product eligibility, and refund-netting). For anything owed/claimed use "
     "lens_ps_commission_ledger / lens_ps_claim (Stripe spine, 10/6/3, refund-net)."),
    ("lens_ps_china_deal_financials",
     "CRM/HubSpot deal financials (total_fees_billed/paid, ar_gap) per china brand. "
     "Reference/AR view - NOT the money engine; use lens_ps_claim for what's owed."),
    ("lens_ps_china_brands_financial_summary",
     "CRM-derived per-brand financial rollup (HubSpot fees). NOT the money engine - "
     "use lens_ps_claim / lens_ps_commission_ledger for owed/collected."),
    ("lens_ps_china_brands_all",
     "The china book from the CRM/attribution side (one row per china brand w/ "
     "attribution). For the nationality verdict use lens_ps_china_verdict."),
    ("lens_ps_china_brands_by_original_attribution",
     "China brands grouped by their ORIGINAL attribution owner (CRM lineage)."),
    ("lens_ps_china_chase_list",
     "The collections chase list: china brands with an outstanding balance, ordered "
     "for follow-up. See lens_ps_claim for the underlying owed number."),
    ("lens_ps_brand_contact_book",
     "Per-brand contact book (names/emails/roles) from the CRM contacts, for outreach."),
)


def _c(target: str, body: str, kind: str) -> None:
    op.execute(f"COMMENT ON {kind} {target} IS $c${body}$c$")


def upgrade() -> None:
    for t in _RLS_FORCE:
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")

    for t in _PRODUCT_FK:
        _c(f"{t}.product_id",
           "Product - 'connect' or 'boosted' (FK to ps_products). NOTE the Boost "
           "product id is the string 'boosted', not 'boost'.", "COLUMN")
    _c("ps_products.product_id",
       "Canonical product id: 'connect' or 'boosted'. Filter on these literals - the "
       "Boost product id is 'boosted', not 'boost'.", "COLUMN")

    _c("ps_partner_payouts",
       "What WE have paid referral partners. Reconcile amount_paid vs "
       "lens_ps_commission_ledger.partner_fee_owed (brand x product x month) or "
       "lens_ps_partner_payout_summary (per partner). (ps_monthly_earnings was "
       "dropped in cip_110.)", "TABLE")

    for target, body in _COL_COMMENTS:
        _c(target, body, "COLUMN")
    for view, body in _VIEW_COMMENTS:
        _c(view, body, "VIEW")


def downgrade() -> None:
    # Un-force RLS (the one structural change). The corrected COMMENTs are left in
    # place — reverting to the wrong/absent text would only re-introduce the traps.
    for t in _RLS_FORCE:
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
