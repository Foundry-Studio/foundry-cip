# foundry: kind=migration domain=client-intelligence-platform
"""cip_93 (W7): make the schema tell the truth. FKs, CHECKs, and three comment lies.

A batch of small, mechanical, independently-verified fixes. Every one was measured against live data
before writing, and every one is 0-risk on today's rows. Nothing here moves a number — it closes
the gaps through which a FUTURE wrong number would arrive.

1. product_id has NO foreign key on ANY of the 10 tables that carry it.
   'boosted' could be misspelled on insert and nothing would catch it. All 10 are 0-orphan today,
   so the FK VALIDATEs clean. MATCH SIMPLE means a NULL product_id (brand-level ps_added_facts) is
   still allowed — only non-null values are checked.

2. canonical_brand_id — the column the whole company roll-up (cip_92) depends on — has NO FK to
   ps_brands. A dangling head would silently drop a company from every headline. 0 orphans today.

3. ps_excluded_brands.bucket decides winnability and had NO CHECK. It already held 'Jeremy  Caspar'
   with a double space (fixed in cip_86); nothing stopped the next one. The list is FROZEN (contract
   Exhibit A, 2025-11-18), so the seven buckets are the whole vocabulary — pin them.

4. eligible_for_10_rev_share is text holding Python-cased 'True'/'False'/NULL, with no CHECK, named
   like a boolean. It is NOT converted to boolean — two scripts (decide_partner_attribution,
   rebuild_partner_attribution) read it as text, so a type change would have blast radius. A CHECK
   on the three legal values is the safe fix.

5. ps_added_facts: 3 superseded rows are still pinned = true. `pinned` and `superseded_by` are two
   encodings of one state and they disagree. lens_ps_added_current filters on superseded_by so the
   live view is fine, but a direct reader of `WHERE pinned` sees replaced decisions as current.
   Fix the 3, then a CHECK makes the contradiction impossible.

6-8. Three comment lies a human reading \\d+ would be misled by:
   - ps_monthly_earnings.product_id comment said "'connect' or 'boost'". The data is 'boosted'.
     WHERE product_id='boost' returns zero rows, silently.
   - ps_monthly_earnings.variance had NO comment and is a GENERATED month-by-month reconciliation —
     the exact thing ps_actually_paid's comment forbids ("reconcile at BRAND level, never month by
     month"). 12,349 rows show a phantom shortfall. Warn on it.
   - ps_stripe_invoice_lines.amount is DOLLARS, not cents — the column that caused a near-100x
     error — and its comment never said so (the sibling ps_stripe_invoices.amount_due does).

Revision ID: cip_93_schema_honesty
Revises: cip_92_company_truth
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_93_schema_honesty"
down_revision: str | Sequence[str] | None = "cip_92_company_truth"
branch_labels = None
depends_on = None

_PRODUCT_FK_TABLES = (
    "ps_added_facts", "ps_attribution", "ps_claim_lines", "ps_monthly_earnings",
    "ps_partner_credit", "ps_partner_terms", "ps_product_subscriptions", "ps_rate_cards",
    "ps_reactivation_rights", "ps_stripe_invoice_lines",
)
_BUCKETS = (
    "Eric Flat Fee Brands", "Eric Rev Share Brands", "Heavy Producer Brands",
    "Jeremy Caspar", "Shallow", "OpenLight", "OceanWing",
)


def upgrade() -> None:
    # ── 1. product_id -> ps_products, on every table that carries it ─────────
    for tbl in _PRODUCT_FK_TABLES:
        op.execute(
            f"ALTER TABLE {tbl} ADD CONSTRAINT {tbl}_product_fk "
            f"FOREIGN KEY (tenant_id, product_id) "
            f"REFERENCES ps_products (tenant_id, product_id) ON DELETE RESTRICT NOT VALID"
        )
        op.execute(f"ALTER TABLE {tbl} VALIDATE CONSTRAINT {tbl}_product_fk")

    # ── 2. canonical_brand_id -> ps_brands (self) ───────────────────────────
    op.execute(
        "ALTER TABLE ps_brands ADD CONSTRAINT ps_brands_canonical_fk "
        "FOREIGN KEY (canonical_brand_id) REFERENCES ps_brands (wayward_brand_id) "
        "ON DELETE RESTRICT NOT VALID"
    )
    op.execute("ALTER TABLE ps_brands VALIDATE CONSTRAINT ps_brands_canonical_fk")
    op.execute(
        "COMMENT ON COLUMN ps_brands.canonical_brand_id IS "
        "'The HEAD row for this company. NULL means this row IS the head. The company roll-up "
        "(lens_ps_china_companies) collapses on COALESCE(canonical_brand_id, wayward_brand_id), so a "
        "dangling pointer would drop a company from every headline — now impossible (FK to "
        "ps_brands, ON DELETE RESTRICT). Correct but INCOMPLETE: links exact-name dupes, not name "
        "variants (Grownsy/Selgrownsy). See PARKING P3.'"
    )

    # ── 3. the frozen bucket vocabulary ─────────────────────────────────────
    inner = ", ".join(f"'{b}'" for b in _BUCKETS)
    op.execute(
        f"ALTER TABLE ps_excluded_brands ADD CONSTRAINT ps_excluded_brands_bucket_check "
        f"CHECK (bucket = ANY (ARRAY[{inner}]::text[]))"
    )

    # ── 4. eligible_for_10_rev_share: a CHECK, not a type change ─────────────
    op.execute(
        "ALTER TABLE ps_excluded_brands ADD CONSTRAINT ps_excluded_brands_eligible_check "
        "CHECK (eligible_for_10_rev_share IS NULL "
        "OR eligible_for_10_rev_share IN ('True', 'False'))"
    )
    op.execute(
        "COMMENT ON COLUMN ps_excluded_brands.eligible_for_10_rev_share IS "
        "'TEXT holding ''True'' / ''False'' / NULL (Python-cased, from the frozen sheet). It LOOKS "
        "like a boolean and is not one — decide_partner_attribution and rebuild_partner_attribution "
        "read it as text, so it is not converted. CHECK pins the three legal values. Compare with "
        "= ''True'', never a bare boolean cast.'"
    )

    # ── 5. pinned must not contradict superseded_by ─────────────────────────
    op.execute(
        "UPDATE ps_added_facts SET pinned = false WHERE superseded_by IS NOT NULL AND pinned"
    )
    op.execute(
        "ALTER TABLE ps_added_facts ADD CONSTRAINT ps_added_facts_superseded_not_pinned_check "
        "CHECK (NOT (superseded_by IS NOT NULL AND pinned))"
    )

    # ── 6-8. the comment lies ───────────────────────────────────────────────
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.product_id IS "
        "'Which product this row is about: ''connect'' or ''boosted''. *** The value is ''boosted'', "
        "NOT ''boost''. *** WHERE product_id = ''boost'' returns zero rows silently. Roborock is two "
        "deals: connect (Eric''s) and boosted (contested). FK to ps_products (cip_93).'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.variance IS "
        "'GENERATED month-by-month as ps_net_owed - ps_actually_paid. *** DO NOT READ THIS PER "
        "ROW. *** Wayward pays us 1-3 months AFTER the usage a payment settles, so a positive "
        "variance on a single month is almost always a phantom shortfall — 12,349 rows show one. "
        "The AGGREGATE is correct ($169,815.89); the row is not. Reconcile at BRAND level, never "
        "month by month — the same rule ps_actually_paid''s comment states.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_stripe_invoice_lines.amount IS "
        "'*** IN DOLLARS, not cents. *** The ingest already divided Stripe''s integer cents by 100; "
        "do NOT divide again. This is the column that nearly produced a 100x-too-small figure. May "
        "be NEGATIVE: ''Attribution Reconciliation Usage'' lines are adjustments. Only paid/open "
        "lines count as billed — a voided line was cancelled, never owed.'"
    )


def downgrade() -> None:
    # Comments are left as-is (cosmetic; the new ones are simply more correct).
    # The constraints and the 3-row pinned fix are the reversible parts.
    op.execute("ALTER TABLE ps_added_facts DROP CONSTRAINT ps_added_facts_superseded_not_pinned_check")
    op.execute("UPDATE ps_added_facts SET pinned = true WHERE superseded_by IS NOT NULL")
    op.execute("ALTER TABLE ps_excluded_brands DROP CONSTRAINT ps_excluded_brands_eligible_check")
    op.execute("ALTER TABLE ps_excluded_brands DROP CONSTRAINT ps_excluded_brands_bucket_check")
    op.execute("ALTER TABLE ps_brands DROP CONSTRAINT ps_brands_canonical_fk")
    for tbl in _PRODUCT_FK_TABLES:
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT {tbl}_product_fk")
