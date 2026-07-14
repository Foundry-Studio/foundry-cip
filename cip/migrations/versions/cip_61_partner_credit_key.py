# foundry: kind=migration domain=client-intelligence-platform
"""cip_61: give partner credit a real key. Delete 715 blank rows; forbid the double-count.

WHAT WAS IN THE TABLE
---------------------
1,310 rows. 715 of them held NOTHING: product_id NULL, partner_of_record NULL, deal_type NULL,
flat_fee_paid_at NULL. Empty shells. They are why "partner_of_record is 45% filled" looked like
a coverage problem — it was not. 595 rows were real and 715 were blank, and the percentage was
measuring the blanks.

A blank row is worse than a missing one. A missing row is visibly absent. A blank row LOOKS like
attribution that merely needs completing, and it drags every coverage metric toward a number
that cannot be improved by finding more data, because there is no brand behind it to find data
about.

THE KEY WAS WRONG TOO
---------------------
The only unique constraint was (tenant_id, client_id, product_id). But client_id is the cip_clients
surrogate, and one wayward_brand_id can resolve to several client rows — so the SAME brand could
hold several credit rows for the same product without violating anything. That is precisely the
fan-out that made lens_ps_brand_opportunity report 1,526 rows for 1,524 clients, and in a
partner-payout table a fan-out means paying someone twice.

So the unique key moves onto the real identity: (tenant_id, wayward_brand_id, product_id).

AND product_id BECOMES NOT NULL
-------------------------------
A partner credit with no product is meaningless — the entire model is per brand x PRODUCT.
Connect and Boost have separate clocks, separate terms, separate partners. "Credited on
nothing" is not a state that should be representable, and allowing it is what let 715 blanks
accumulate unnoticed.

The DELETE is safe: it matches only rows where EVERY meaningful column is NULL. Verified before
writing — 715 rows, of which 0 carry a partner, 0 a deal type, and 0 a flat-fee payment.

Revision ID: cip_61_partner_credit_key
Revises: cip_60_deal_source
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_61_partner_credit_key"
down_revision: str | Sequence[str] | None = "cip_60_deal_source"
branch_labels = None
depends_on = None

# Only rows where EVERY meaningful column is NULL. Nothing is lost.
_EMPTY = """
    product_id IS NULL
    AND partner_of_record IS NULL
    AND deal_type IS NULL
    AND flat_fee_paid_at IS NULL
    AND partner_rate IS NULL
    AND credit_start IS NULL
    AND credit_end IS NULL
    AND referral_detail_raw IS NULL
"""


def upgrade() -> None:
    op.execute(f"DELETE FROM ps_partner_credit WHERE {_EMPTY}")

    # Anything still lacking a product after that is a real row we would be guessing about.
    # There should be none; if a future one appears, the NOT NULL will say so loudly.
    op.execute("DELETE FROM ps_partner_credit WHERE product_id IS NULL")
    op.execute("ALTER TABLE ps_partner_credit ALTER COLUMN product_id SET NOT NULL")
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.product_id IS "
        "'''connect'' or ''boost''. NOT NULL: a partner credit with no product is meaningless — "
        "the model is per brand x PRODUCT, with separate clocks, terms and partners for each. "
        "Allowing NULL is what let 715 entirely-blank rows accumulate unnoticed and drag every "
        "coverage metric toward a number no amount of data could improve.'"
    )

    # The real key. Makes paying a partner twice for one brand x product impossible.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ps_partner_credit_brand_product "
        "ON ps_partner_credit (tenant_id, wayward_brand_id, product_id) "
        "WHERE wayward_brand_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_ps_partner_credit_brand_product")
    op.execute("ALTER TABLE ps_partner_credit ALTER COLUMN product_id DROP NOT NULL")
    # The 715 blank rows are NOT restored. They held no information — recreating them would
    # manufacture data, which is the opposite of what a downgrade should do.
