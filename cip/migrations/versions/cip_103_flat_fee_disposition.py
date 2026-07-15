# foundry: kind=migration domain=client-intelligence-platform
"""cip_103: label flat-fee-era Eric brands as OURS + their revenue-start date (Tim, 2026-07-15).

ps_excluded_brands is the contract Exhibit A. One bucket — "Eric Flat Fee Brands" — is where Eric is
paid a FLAT FEE, so the usage rev-share is free and Wayward already pays it to us (confirmed: 415 of
582 of these appear in Jake's payment sheets, ~$11.3k paid to us). Tim's ruling: treat ALL flat-fee
brands as OURS — but only for revenue from the FIRST billing cycle Jake actually sent a sheet for
(the December 2025 payments sheet; payments begin 2025-12-04), NOT the revenue before that.

The other buckets (Eric Rev Share, Heavy Producer, Jeremy Caspar, Shallow, OpenLight, OceanWing) are
where a partner genuinely earns the rev-share — those stay excluded (not ours) unless a win-back
trigger fires.

This adds a persistent `disposition` label so we can act on the flat-fee-era brands later, plus their
distinct `ours_revenue_from` date. Note the two different revenue-start dates this encodes: the
never-listed china brands anchor at 2025-10-01; these flat-fee brands anchor later, at 2025-12-01.

Reference/classification only — no money-math columns are touched (the frozen P2 engine will consume
these). lens_ps_exclusion_status.takeable already computes ownership on the fly; this makes the label
and the revenue-start first-class and reportable.

Revision ID: cip_103_flat_fee_disposition
Revises: cip_102_comment_partner_payouts
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cip_103_flat_fee_disposition"
down_revision: str | Sequence[str] | None = "cip_102_comment_partner_payouts"
branch_labels = None
depends_on = None

FLAT_FEE_BUCKET = "Eric Flat Fee Brands"
FLAT_FEE_REVENUE_FROM = "2025-12-01"  # first billing cycle Jake sent a sheet for (Dec 2025 payments)


def upgrade() -> None:
    # Persistent ownership label on each contract-exhibit row. Defaults to 'excluded' so any brand
    # later added to the exhibit is excluded until it is explicitly classified.
    op.add_column(
        "ps_excluded_brands",
        sa.Column("disposition", sa.Text(), nullable=False, server_default="excluded"),
    )
    # For flat-fee-era-eric brands, PS revenue ownership begins on this date (NULL otherwise).
    op.add_column(
        "ps_excluded_brands",
        sa.Column("ours_revenue_from", sa.Date(), nullable=True),
    )
    # Flat-fee bucket -> ours (labeled), revenue counted only from the first billing sheet cycle.
    op.execute(
        f"""
        UPDATE ps_excluded_brands
           SET disposition = 'flat_fee_era_eric',
               ours_revenue_from = DATE '{FLAT_FEE_REVENUE_FROM}'
         WHERE bucket = $b${FLAT_FEE_BUCKET}$b$
        """
    )
    op.create_check_constraint(
        "ck_ps_excluded_brands_disposition",
        "ps_excluded_brands",
        "disposition IN ('flat_fee_era_eric', 'excluded')",
    )
    op.execute(
        "COMMENT ON COLUMN ps_excluded_brands.disposition IS "
        "$c$Ownership disposition of this contract-exhibit brand (Tim, 2026-07-15). "
        "'flat_fee_era_eric' = Eric is on a FLAT FEE so the usage rev-share is free and Wayward pays "
        "it to us -> treat as OURS; labeled so we can act on these later. "
        "'excluded' = a partner genuinely earns the rev-share (Eric Rev Share, Heavy Producer, "
        "Jeremy Caspar, Shallow, OpenLight, OceanWing) -> NOT ours unless a win-back trigger fires.$c$"
    )
    op.execute(
        "COMMENT ON COLUMN ps_excluded_brands.ours_revenue_from IS "
        "$c$For flat_fee_era_eric brands: PS revenue ownership begins on this date — the first "
        "billing cycle Jake sent a payment sheet for (Dec 2025). Revenue before this is NOT ours. "
        "NULL for genuinely-excluded brands. Note: never-listed china brands anchor at 2025-10-01; "
        "these flat-fee brands anchor later, at 2025-12-01.$c$"
    )


def downgrade() -> None:
    op.drop_constraint("ck_ps_excluded_brands_disposition", "ps_excluded_brands", type_="check")
    op.drop_column("ps_excluded_brands", "ours_revenue_from")
    op.drop_column("ps_excluded_brands", "disposition")
