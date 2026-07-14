# foundry: kind=migration domain=client-intelligence-platform
"""cip_69: a VOIDED invoice was never billed. BILLED vs COLLECTED vs OWED, properly separated.

Tim, 2026-07-13: "in the logic, make sure that we separate what's been BILLED to client, what's
been COLLECTED, so that's OWED to PS and/or partners then."

Checking that turned up a $561,209 error in the BILLED number.

    usage_billed was computed as sum(amount) over ALL invoice lines, whatever their status.
    3,389 usage-fee lines sit on VOIDED invoices ($559,045.85), and 20 more are uncollectible
    ($2,163.16). A voided invoice was CANCELLED. It was never billed to anybody, nobody owes it,
    and it will never be collected.

    billed, as computed          $2,969,122.54
    billed, correctly            $2,407,913.53      <-- $561,209.01 lower
    collected (paid)             $2,149,612.72
    outstanding (open)             $258,300.81      <-- the REAL pipeline

It also produced an impossible state: 73 brand-months where COLLECTED EXCEEDED BILLED. Zyllion
showed billed = -$57.78 against collected = $470.80, because large negative credit lines on VOIDED
invoices were dragging "billed" below zero while "collected" correctly counted only the paid ones.
A number that says a brand paid us more than we ever invoiced them is a number nobody can defend.

THE FOUR NUMBERS, and why they must never be conflated
------------------------------------------------------
    BILLED       Wayward issued a live invoice.  = paid + open. NOT void, NOT uncollectible.
    COLLECTED    Wayward actually received the cash. = paid.
                 *** §3.1 pays PS on "Usage Fees ACTUALLY RECEIVED". This, and only this, is
                     the base for our 10/6/3%. ***
    OUTSTANDING  billed - collected = the open invoices. PIPELINE, not a claim. It becomes ours
                 when the brand pays, and never before.
    OWED         10/6/3% of COLLECTED, minus the partner's share (which comes OUT of our cut,
                 not on top of it).

VOIDED is now kept as its own column rather than being silently folded into billed. $559k of
cancelled invoicing is a fact worth being able to see — not least because a spike in voids is how
a brand disputes its bill, and that is the leading indicator of revenue we are about to lose.

WHAT THIS DOES NOT CHANGE
-------------------------
The CLAIM. ps_gross_owed is computed on usage_COLLECTED and always was, so the money we say
Wayward owes us is unaffected. What was wrong was the pipeline: we were reporting $561k of
cancelled invoices as though it were revenue on its way.

Revision ID: cip_69_billed_excludes_void
Revises: cip_68_someone_else_earning
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_69_billed_excludes_void"
down_revision: str | Sequence[str] | None = "cip_68_someone_else_earning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ps_monthly_earnings ADD COLUMN IF NOT EXISTS usage_voided NUMERIC(14,2)"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.usage_voided IS "
        "'Usage fees on VOIDED invoices — cancelled, never owed, never collectable. Kept as its "
        "own number rather than folded into usage_billed, where $559,045.85 of it was silently "
        "inflating the pipeline and, on 73 brand-months, dragging BILLED below COLLECTED. A spike "
        "in voids is also how a brand disputes its bill, which makes it a leading indicator of "
        "revenue about to disappear — worth being able to see.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.usage_billed IS "
        "'Usage fees on LIVE invoices — paid + open. EXCLUDES void and uncollectible: a cancelled "
        "invoice was never billed to anybody. This is the top of the funnel, NOT a claim.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.usage_collected IS "
        "'Usage fees Wayward ACTUALLY RECEIVED. *** §3.1 pays Project Silk on ''Usage Fees actually "
        "received'' — this, and only this, is the base for our 10/6/3%%. *** Never compute the "
        "commission on usage_billed.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.usage_outstanding IS "
        "'billed - collected = the OPEN invoices. PIPELINE, not a claim: it becomes ours when the "
        "brand pays, and not before. Quoting it as money owed to us is the easiest way to promise "
        "revenue that has not arrived.'"
    )

    # Voided amounts, from the source.
    op.execute(
        """
        UPDATE ps_monthly_earnings e
           SET usage_voided = v.voided
          FROM (
            SELECT wayward_brand_id, product_id, billing_month,
                   sum(amount) AS voided
            FROM ps_stripe_invoice_lines
            WHERE is_ps_base AND invoice_status IN ('void', 'uncollectible')
              AND billing_month IS NOT NULL AND wayward_brand_id IS NOT NULL
              AND product_id IS NOT NULL
            GROUP BY 1, 2, 3
          ) v
         WHERE v.wayward_brand_id = e.wayward_brand_id
           AND v.product_id = e.product_id
           AND v.billing_month = e.period_month
        """
    )
    # BILLED = live invoices only.
    op.execute(
        """
        UPDATE ps_monthly_earnings e
           SET usage_billed = b.billed
          FROM (
            SELECT wayward_brand_id, product_id, billing_month,
                   COALESCE(sum(amount) FILTER (
                        WHERE invoice_status IN ('paid', 'open')), 0) AS billed
            FROM ps_stripe_invoice_lines
            WHERE is_ps_base
              AND billing_month IS NOT NULL AND wayward_brand_id IS NOT NULL
              AND product_id IS NOT NULL
            GROUP BY 1, 2, 3
          ) b
         WHERE b.wayward_brand_id = e.wayward_brand_id
           AND b.product_id = e.product_id
           AND b.billing_month = e.period_month
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ps_monthly_earnings DROP COLUMN IF EXISTS usage_voided")
    op.execute(
        """
        UPDATE ps_monthly_earnings e
           SET usage_billed = b.billed
          FROM (SELECT wayward_brand_id, product_id, billing_month, sum(amount) AS billed
                  FROM ps_stripe_invoice_lines
                 WHERE is_ps_base AND billing_month IS NOT NULL
                   AND wayward_brand_id IS NOT NULL AND product_id IS NOT NULL
                 GROUP BY 1,2,3) b
         WHERE b.wayward_brand_id = e.wayward_brand_id
           AND b.product_id = e.product_id
           AND b.billing_month = e.period_month
        """
    )
