# foundry: kind=migration domain=client-intelligence-platform
"""cip_79: the partner metric was measuring the wrong denominator, and flattering everyone.

cip_78 computed production_rate from ps_partner_credit — and every partner came out at 98-100%.
That should have been the tell.

ps_partner_credit rows are created FROM THE MONEY SPINE, which only contains brands that ALREADY
BILL. So the denominator excluded exactly the population the metric exists to find: the brands
that signed and never sold anything. It was asking "of the brands that produced, how many
produced?" and reporting the answer as a performance score.

THE HONEST DENOMINATOR is brands ONBOARDED — the Slack brand-connection feed, which records every
brand Wayward brought on, whether or not it ever made a sale.

    onboarded through the feed   1,347
    ever made a sale               869
    SIGNED AND DIED                478      <- the number the metric exists to surface
    true production rate          64.5%     (not 98-100%)

And per referrer it says something worth knowing:

    China Referral - Adina    70 onboarded   62 sold    8 died   89%   <- brings brands that sell
    China Referral - Eric    389             277      112        71%
    Other                    451             298      153        66%
    China Referral - Tim     431             229      202        53%   <- our own channel is weakest

A partner who refers 100 brands that never sell has referred nothing. deals_referred is vanity;
production_rate is the number. Anyone can hit 100% if you only count the winners.

Revision ID: cip_79_honest_partner_perf
Revises: cip_78_freshness_partner
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_79_honest_partner_perf"
down_revision: str | Sequence[str] | None = "cip_78_freshness_partner"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_performance CASCADE")
    op.execute(
        """
        CREATE VIEW lens_ps_partner_performance AS
        WITH onboarded AS (
            -- EVERY brand Wayward brought on, whether or not it ever sold. This is the
            -- denominator. ps_partner_credit is NOT: it only holds brands that already bill,
            -- which is exactly the population that flatters the number.
            SELECT o.wayward_brand_id,
                   max(o.value) FILTER (WHERE o.field = 'deal_source')      AS deal_source,
                   max(o.value) FILTER (WHERE o.field = 'referral_source')  AS referral_source,
                   min(o.observed_at)                                       AS onboarded_at
            FROM ps_brand_observations o
            WHERE o.source_system LIKE 'slack:%' AND o.wayward_brand_id IS NOT NULL
            GROUP BY o.wayward_brand_id
        ),
        attributed AS (
            SELECT
                ob.wayward_brand_id,
                ob.onboarded_at,
                -- who gets the credit: the canonical partner we resolved, else Wayward's own
                -- deal_source tag, else nobody.
                COALESCE(
                    (SELECT NULLIF(pc.lead_source_initial, 'unassigned')
                       FROM ps_partner_credit pc
                      WHERE pc.wayward_brand_id = ob.wayward_brand_id
                        AND pc.lead_source_initial IS NOT NULL
                      LIMIT 1),
                    CASE WHEN ob.deal_source LIKE 'China Referral - %'
                         THEN lower(replace(ob.deal_source, 'China Referral - ', ''))
                    END,
                    'unattributed'
                )                                                            AS partner
            FROM onboarded ob
        ),
        sold AS (
            SELECT wayward_brand_id,
                   min(billing_month)                                        AS first_sale,
                   sum(amount) FILTER (WHERE invoice_status = 'paid')         AS usage_collected
            FROM ps_stripe_invoice_lines
            WHERE is_ps_base AND amount > 0 AND wayward_brand_id IS NOT NULL
            GROUP BY wayward_brand_id
        ),
        quiet AS (
            SELECT DISTINCT wayward_brand_id
            FROM ps_product_subscriptions
            WHERE dormant_since IS NOT NULL
        )
        SELECT
            a.partner,
            r.name                                                          AS partner_name,
            r.company_name,
            count(*)                                                        AS brands_onboarded,
            count(s.wayward_brand_id)                                       AS brands_that_sold,
            count(*) - count(s.wayward_brand_id)                            AS signed_and_died,
            round(100.0 * count(s.wayward_brand_id) / NULLIF(count(*), 0), 1)
                                                                            AS production_rate_pct,
            count(q.wayward_brand_id)                                       AS sold_then_went_quiet,
            round(sum(s.usage_collected), 2)                                AS usage_fees_generated,
            round(avg(s.usage_collected), 2)                                AS avg_per_producing_brand,
            -- a partner whose brands take a year to sell is not the same as one whose brands
            -- sell in a month, even at the same production rate.
            round(avg((s.first_sale - a.onboarded_at::date)::numeric), 0)   AS avg_days_to_first_sale
        FROM attributed a
        LEFT JOIN sold  s ON s.wayward_brand_id = a.wayward_brand_id
        LEFT JOIN quiet q ON q.wayward_brand_id = a.wayward_brand_id
        LEFT JOIN ps_partner_registry r ON r.partner_id = a.partner
        GROUP BY a.partner, r.name, r.company_name
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_partner_performance IS "
        "'WHO BRINGS BRANDS THAT SELL, versus who brings brands that SIGN AND DIE. "
        "*** The denominator is brands ONBOARDED (the Slack brand-connection feed), NOT "
        "ps_partner_credit. *** partner_credit only holds brands that ALREADY BILL, so using it "
        "excluded the very population this metric exists to find — and every partner scored "
        "98-100%%. Anyone can hit 100%% if you only count the winners. "
        "The truth: 1,347 brands onboarded, 869 ever sold, 478 SIGNED AND DIED — a 64.5%% "
        "production rate. Adina brings brands that sell (89%%); our own channel is the weakest "
        "(53%%). deals_referred is vanity; production_rate_pct is the number. "
        "sold_then_went_quiet is both a performance signal AND the win-back queue.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_partner_performance TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_performance CASCADE")
