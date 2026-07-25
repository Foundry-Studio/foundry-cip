# foundry: kind=migration domain=client-intelligence-platform
"""cip_133: customer payments lens (BE-6) — a read-only, CLIENT-SAFE per-invoice view of a
customer's own billing history. HEADER AMOUNTS ONLY — it exposes ZERO of our economics.

Design of record: WORKBENCH/china-audit/REPORTING-BACKEND-CHECKPOINT.md ("BE-6").

WHAT THIS ADDS (purely additive; nothing renamed, altered, or dropped):
  * lens_ps_customer_payments — ONE row per Stripe INVOICE. It only READS existing surfaces
    (ps_stripe_invoices, ps_stripe_charges, ps_stripe_invoice_lines, ps_products, the cip_130 party
    spine, lens_ps_china_verdict) and creates no table. Read-only + additive => ZERO money-movement
    BY CONSTRUCTION.

HARD CONFIDENTIALITY RULE — CLIENT-SAFE, HEADER AMOUNTS ONLY (this is the whole point of the lens):
  Every money column comes STRICTLY from the Stripe INVOICE HEADER (ps_stripe_invoices):
  amount_paid / amount_due / amount_remaining (+ status, paid, currency, dates). These are the
  customer's OWN billed/paid figures — exactly what they see on their invoice. The lens NEVER
  exposes, and NEVER reads, any of OUR economics: no commission / mgmt-fee, no rev-share /
  partner-fee, no wayward-paid, no claim / recovery, no margin. It deliberately does NOT touch
  ps_payment_events, ps_cash_ledger, lens_ps_commission_ledger, lens_ps_claim, ps_partner_* or any
  refund / rev-share source. From the charge it reads ONLY the paid DATE + charge status (never the
  charge amount / fee / net — those are Stripe processing economics). From the invoice LINES it reads
  ONLY product identity (product_id + ps_products.name), never the line amounts.

PER-INVOICE GRAIN (held to ONE row per invoice despite two 1:many inputs):
  * A single invoice may have MANY charges (retries — up to 27 seen; 11,904 succeeded / 7,292 failed
    across the book) => the charge is collapsed to ONE representative row per invoice (DISTINCT ON,
    succeeded-first then most-recent) before the join, so no fan-out.
  * A single invoice may bill MANY products (2,530 invoices bill both Connect + Boosted) => product
    identity is aggregated to arrays per invoice (product_ids / product_names) in a CTE, so no fan-out.
  All four identity joins (charge, products, brand->company->party, verdict) are LEFT JOINs onto a
  UNIQUE key => at most one match each => the result is exactly one row per invoice (15,332 today).

PAID-DATE HONESTY (keep the null): paid_date is taken ONLY from a SUCCEEDED charge's charge_created.
  A paid invoice may have no synced (or no succeeded) charge — 558 of the 12,282 paid invoices have
  no succeeded charge synced today — so its paid_date is NULL while the header still shows it paid.
  That NULL is honest (charge-sync completeness, not payment truth) and is kept, not papered over.

CUSTOMER IDENTITY (company grain, cip_130): the invoiced wayward_brand_id -> ps_brands ->
  company spine COALESCE(canonical_brand_id, wayward_brand_id) -> ps_customer_party (UNIQUE per
  company) -> ps_party gives a STABLE customer id (party_id) + a mutable display_name. cip_130
  backfilled customer parties for CHINA companies only, so non-china invoices resolve to a NULL
  customer_party_id — consistent with the china-scoped reporting (the DAL filters china anyway).
  (ps_party / ps_customer_party are created by cip_130, guaranteed present by the revision chain.)

CHINA SCOPE (sibling convention): the DAL filters china. This lens does NOT hard-filter; it TAGS a
  `verdict` column via a cheap LEFT JOIN to lens_ps_china_verdict on wayward_brand_id (exactly as
  lens_ps_commission_ledger does), so the DAL can scope WHERE verdict = 'china'. `verdict` is a
  nationality classification, NOT economics — tagging it does not breach the header-only money rule.

INTERNAL COLUMNS — DO NOT PROJECT TO A CLIENT: `verdict` (china nationality) and `wayward_brand_id` (our
  internal brand id) are present for DAL scoping / joining ONLY. The client-facing surface (FE-5) must
  select EXPLICIT customer-safe columns from this view — never SELECT * — so our internal nationality/brand
  id never leaves the building. (customer_party_id is an opaque uuid; customer_display_name is the
  customer's own name; the money is their own invoice header — all client-safe.)

Revision ID: cip_133_customer_payments   (25 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_132_pipeline
APPLY-TIME (not in file): export FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS="solo_kimi_k3_engine_dir"
for env.py's cross-pollution guard (the shared prod DB carries a foreign monorepo revision).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_133_customer_payments"
down_revision: str | Sequence[str] | None = "cip_132_pipeline"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
# The lens read-role set + the reporting app's reader (cip_129/130/131/132 convention). A lens_ps_*
# VIEW still gets an EXPLICIT grant here — cip_120's auto-enumeration is a one-time grant, not live.
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
_READER = "ps_reporting_reader"

# ── lens_ps_customer_payments — ONE row per invoice. CLIENT-SAFE: every money column is a Stripe
#    INVOICE-HEADER amount (amount_paid / amount_due / amount_remaining); NONE of our economics
#    (commission / rev-share / fee / claim / margin) is read or exposed. ─────────────────────────────
_PAYMENTS_VIEW = r"""CREATE OR REPLACE VIEW lens_ps_customer_payments AS
WITH inv_charge AS (
    -- ONE representative charge per invoice: prefer a SUCCEEDED charge (most recent), else the most
    -- recent charge of any status. IDENTITY + DATE ONLY — amount / fee / net are NOT read (Stripe
    -- processing economics). paid_date is derived from this row ONLY when it is succeeded (below).
    SELECT DISTINCT ON (c.stripe_invoice_id)
           c.stripe_invoice_id,
           c.status        AS charge_status,
           c.charge_created
    FROM ps_stripe_charges c
    WHERE c.stripe_invoice_id IS NOT NULL
    ORDER BY c.stripe_invoice_id,
             (c.status = 'succeeded') DESC NULLS LAST,
             c.charge_created DESC NULLS LAST
),
inv_products AS (
    -- Product IDENTITY per invoice, aggregated to arrays (an invoice can bill Connect AND Boosted)
    -- so the grain stays ONE row per invoice. product_id from the line; name from ps_products.
    -- NO line amount / quantity / fee is read — identity only.
    SELECT l.stripe_invoice_id,
           array_agg(DISTINCT l.product_id) FILTER (WHERE l.product_id IS NOT NULL) AS product_ids,
           array_agg(DISTINCT pr.name)      FILTER (WHERE pr.name IS NOT NULL)      AS product_names
    FROM ps_stripe_invoice_lines l
    LEFT JOIN ps_products pr ON pr.product_id = l.product_id
    GROUP BY l.stripe_invoice_id
)
SELECT
    -- ── identity (opaque ids + the customer's own display name) ─────────────────────────────────
    i.stripe_invoice_id,
    i.invoice_number,
    i.wayward_brand_id,
    cp.party_id      AS customer_party_id,   -- stable customer id (company grain, cip_130)
    pty.display_name AS customer_display_name,
    cv.verdict,                              -- china TAG for DAL scoping (nationality, NOT economics)
    -- ── product identity (from invoice lines; NO line amounts) ─────────────────────────────────
    ip.product_ids,
    ip.product_names,
    -- ── money — STRICTLY the Stripe INVOICE HEADER (no commission / rev-share / fee / claim / margin) ─
    i.currency,
    i.status,                                -- invoice status (draft/open/paid/uncollectible/void)
    i.paid,
    i.amount_due,
    i.amount_paid,
    i.amount_remaining,
    i.collection_method,
    i.hosted_invoice_url,                    -- the customer's OWN Stripe-hosted invoice link
    -- ── dates: header lifecycle + the real paid date from the succeeded charge ──────────────────
    i.created_at_stripe AS invoice_created,
    i.period_start,
    i.period_end,
    i.due_date,
    CASE WHEN c.charge_status = 'succeeded' THEN c.charge_created END AS paid_date,  -- NULL if none synced
    c.charge_status
FROM ps_stripe_invoices i
LEFT JOIN inv_charge   c  ON c.stripe_invoice_id  = i.stripe_invoice_id
LEFT JOIN inv_products ip ON ip.stripe_invoice_id = i.stripe_invoice_id
LEFT JOIN lens_ps_china_verdict cv ON cv.wayward_brand_id = i.wayward_brand_id
LEFT JOIN ps_brands b ON b.wayward_brand_id = i.wayward_brand_id
LEFT JOIN ps_customer_party cp
       ON cp.canonical_brand_id = COALESCE(b.canonical_brand_id, b.wayward_brand_id)
LEFT JOIN ps_party pty ON pty.party_id = cp.party_id
ORDER BY i.created_at_stripe DESC NULLS LAST, i.stripe_invoice_id"""

_VIEW_COMMENT = (
    "COMMENT ON VIEW lens_ps_customer_payments IS $c$BE-6 (cip_133): CLIENT-SAFE per-invoice "
    "customer payment history. ONE row per Stripe invoice; read-only, additive. HEADER AMOUNTS "
    "ONLY: amount_due / amount_paid / amount_remaining (+ status, paid, currency, dates) come "
    "STRICTLY from the Stripe invoice header (ps_stripe_invoices) — the customer's own billed/paid "
    "figures. NO ECONOMICS: it exposes and reads NONE of our commission / mgmt-fee / rev-share / "
    "partner-fee / wayward-paid / claim / margin, and never touches ps_payment_events, "
    "ps_cash_ledger, lens_ps_commission_ledger, lens_ps_claim or any partner/refund source. From "
    "the charge it reads only paid_date + charge_status (never amount/fee/net); from the invoice "
    "lines only product identity (product_ids/product_names via ps_products), never line amounts. "
    "GRAIN held to one row/invoice: charges (many per invoice, retries) collapse to one "
    "representative row (succeeded-first, most-recent); products (an invoice may bill Connect AND "
    "Boosted) aggregate to arrays. paid_date is taken ONLY from a succeeded charge's charge_created "
    "and is NULL when no succeeded charge is synced (~558 of the paid invoices today) — an honest "
    "charge-sync gap, NOT unpaid; the header still shows the invoice paid. customer_party_id / "
    "customer_display_name are the cip_130 company-grain party (via wayward_brand_id -> ps_brands -> "
    "ps_customer_party -> ps_party); NULL for non-china invoices (backfill is china-only). CHINA "
    "SCOPE: not hard-filtered — verdict is TAGGED (lens_ps_china_verdict) so the DAL filters "
    "WHERE verdict='china' (sibling convention); verdict is nationality, not economics.$c$"
)


def _grant_lens_reads(view: str) -> None:
    for role in (*_READ_ROLES, _READER):
        op.execute(f"GRANT SELECT ON {view} TO {role}")


def upgrade() -> None:
    # Pattern parity with cip_130/131/132 (harmless here — this migration has NO DML, only DDL/GRANT).
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")

    op.execute(_PAYMENTS_VIEW)
    _grant_lens_reads("lens_ps_customer_payments")
    op.execute(_VIEW_COMMENT)

    print(
        "cip_133: created lens_ps_customer_payments (CLIENT-SAFE per-invoice customer payment "
        "history; Stripe invoice-header amounts only, zero economics) + reads to the 3 read roles "
        "+ ps_reporting_reader"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_customer_payments")
