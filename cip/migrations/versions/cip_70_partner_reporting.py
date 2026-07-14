# foundry: kind=migration domain=client-intelligence-platform
"""cip_70: what we show our China partners, and what we show a client. Two audiences, two lenses.

Tim: "we will think about the lens of providing reports to our referral partners in China, to make
sure that's all done."

A partner statement is not an internal report with the columns hidden. It is a different document
with a different duty of care, and getting it wrong costs trust rather than money:

  - A partner must NEVER see another partner's brands. lens_ps_partner_statement is keyed on
    partner_id and exposes nothing else — the row simply does not exist for them.
  - A partner is owed on what Wayward COLLECTED, not on what it billed. Showing them billed makes
    a promise the cash has not kept, and they will hold us to it.
  - Their 12-month window EXPIRES. A statement that does not show the expiry date invites the
    argument, six months later, that nobody told them.
  - What they earn comes OUT of our 10%, not on top of it. The statement says so, in the column
    names, because the alternative is discovering the misunderstanding during a dispute.

WHAT IS DELIBERATELY EXCLUDED FROM THE PARTNER VIEW
  - ps_actually_paid / variance / shortfall: our dispute with Wayward is ours, not theirs.
  - Brands where they are not partner_of_record.
  - Anything on a brand somebody else is being paid on (cip_68) — it is not their money either.

lens_ps_client_statement is the other audience: the BRAND. It shows a brand its own billing and
what it is generating, and it never mentions commission, partners, or Wayward's internal splits.

Revision ID: cip_70_partner_reporting
Revises: cip_69_billed_excludes_void
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_70_partner_reporting"
down_revision: str | Sequence[str] | None = "cip_69_billed_excludes_void"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # ── what a PARTNER sees: their brands, their earnings, their clock ───────
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_statement")
    op.execute(
        """
        CREATE VIEW lens_ps_partner_statement AS
        SELECT
            e.partner_id,
            r.name                                          AS partner_name,
            r.company_name,
            e.period_month,
            e.wayward_brand_id,
            e.brand_name,
            e.product_id,
            -- what the brand actually PAID Wayward. This is the base — not what was invoiced.
            round(e.usage_collected, 2)                     AS usage_fees_collected,
            -- still outstanding: it is NOT yet earned, and saying otherwise makes a promise the
            -- cash has not kept.
            round(e.usage_outstanding, 2)                   AS billed_not_yet_collected,
            e.partner_rate_pct                              AS your_rate_pct,
            round(e.partner_owed, 2)                        AS you_earned,
            -- the clock. A partner who is not shown their expiry will dispute it later.
            pc.credit_start                                 AS your_window_opened,
            pc.credit_end                                   AS your_window_closes,
            (e.period_month >= pc.credit_end)               AS window_expired,
            e.months_since_productive
        FROM ps_monthly_earnings e
        JOIN ps_partner_registry r ON r.partner_id = e.partner_id
                                  AND r.tenant_id  = e.tenant_id
        LEFT JOIN ps_partner_credit pc ON pc.wayward_brand_id = e.wayward_brand_id
                                      AND pc.product_id       = e.product_id
                                      AND pc.tenant_id        = e.tenant_id
        WHERE e.partner_id IS NOT NULL
          AND e.partner_id <> 'unassigned'
          AND e.is_claimable          -- never show them money that is not ours to share
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_partner_statement IS "
        "'WHAT WE SEND A CHINA PARTNER. Keyed on partner_id — a partner must never see another "
        "partner''s brands, and here the rows simply do not exist for them. Shows COLLECTED (what "
        "the brand actually paid Wayward), never billed: billed makes a promise the cash has not "
        "kept, and they will hold us to it. Shows their 12-month window and its EXPIRY, because a "
        "partner who was never shown the expiry will dispute it six months later. Deliberately "
        "OMITS ps_actually_paid, variance and shortfall — our dispute with Wayward is ours, not "
        "theirs. And it only includes claimable rows: money on a brand somebody else is being paid "
        "on is not their money either.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_partner_statement.you_earned IS "
        "'The partner''s share, taken OUT of Project Silk''s 10%% — not added on top of it. Named "
        "in the statement rather than left implicit, because the alternative is discovering the "
        "misunderstanding in the middle of a dispute.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_partner_statement TO {r}")

    # ── the partner's book at a glance ───────────────────────────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_summary")
    op.execute(
        """
        CREATE VIEW lens_ps_partner_summary AS
        SELECT
            s.partner_id,
            s.partner_name,
            s.company_name,
            count(DISTINCT s.wayward_brand_id)                              AS brands,
            count(DISTINCT s.wayward_brand_id) FILTER (
                 WHERE NOT s.window_expired)                                AS brands_still_earning,
            min(s.period_month)                                             AS first_month,
            max(s.period_month)                                             AS latest_month,
            round(sum(s.usage_fees_collected), 2)                           AS usage_collected,
            round(sum(s.billed_not_yet_collected), 2)                       AS in_the_pipeline,
            round(sum(s.you_earned), 2)                                     AS earned_to_date,
            round(sum(s.you_earned) FILTER (
                 WHERE s.period_month >= date_trunc('month', now())
                        - INTERVAL '3 months'), 2)                          AS earned_last_3_months,
            min(s.your_window_closes) FILTER (WHERE NOT s.window_expired)   AS next_window_closes
        FROM lens_ps_partner_statement s
        GROUP BY 1, 2, 3
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_partner_summary IS "
        "'One row per China partner: their book, what it has generated, what they have earned, and "
        "WHEN THEIR NEXT WINDOW CLOSES. next_window_closes is the number to act on — a partner "
        "whose brands are rolling off has months, not years, to bring new ones.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_partner_summary TO {r}")

    # ── what a CLIENT (brand) sees: their own activity. No commission, ever. ─
    op.execute("DROP VIEW IF EXISTS lens_ps_client_statement")
    op.execute(
        """
        CREATE VIEW lens_ps_client_statement AS
        SELECT
            e.wayward_brand_id,
            e.brand_name,
            e.period_month,
            e.product_id,
            round(e.usage_billed, 2)      AS fees_billed,
            round(e.usage_collected, 2)   AS fees_paid,
            round(e.usage_outstanding, 2) AS fees_outstanding,
            round(e.usage_voided, 2)      AS fees_voided,
            s.productive_date             AS first_sale_month,
            s.reactivated_at,
            s.dormant_since
        FROM ps_monthly_earnings e
        LEFT JOIN ps_product_subscriptions s
               ON s.wayward_brand_id = e.wayward_brand_id
              AND s.product_id       = e.product_id
              AND s.tenant_id        = e.tenant_id
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_client_statement IS "
        "'WHAT WE SHOW A BRAND about itself: what it was billed, what it paid, what is outstanding, "
        "when it first sold, whether it has gone dormant. It contains NO commission, NO partner, "
        "and NO Project Silk economics — a brand has no business seeing what we earn on it, and a "
        "view that omits those columns cannot leak them by accident.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_client_statement TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_client_statement")
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_summary")
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_statement")
