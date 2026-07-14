# foundry: kind=migration domain=client-intelligence-platform
"""cip_91 (W4): the rate clock stops counting days and starts counting months.

The bug that started this whole class of defect is still in the schema, as GENERATED columns:

    rate_10_expires         GENERATED AS (productive_date + 365)
    partner_credit_expires  GENERATED AS (productive_date + 365)
    rate_6_expires          GENERATED AS ((productive_date + 365) + 183)

That is `+365+183` = 548 days, standing in for "18 calendar months". Eighteen calendar months is
546 to 549 days depending on which month you start in. It is not a constant, and you cannot count
it in days.

MEASURED, on live data:

    rate_6_expires WRONG on 2,371 of 2,829 deals (83.8%)
    ...of which 1,539 KEEP 6% TOO LONG    <- that is money out the door

    worked example:  productive 2024-09-01
                     stored:  6% ends 2026-03-03
                     truth:  18 months = 2026-03-01
                     -> two extra days at 6% instead of 3%

WHY THIS SURVIVED
-----------------
`compute_monthly_earnings.py` WAS fixed — it uses INTERVAL '12 months' / '18 months' and even
carries a comment explaining the bug. So the money spine is correct and the `rate_tier_18_months`
invariant passes. The SCHEMA was never fixed, and `lens_ps_rate_clock` — the view that answers
"what rate is this deal on TODAY?" — reads these columns raw.

One fact, two computations. One right, one wrong. That is the disease this whole foundation phase
exists to cure: EVERY FACT GETS EXACTLY ONE HOME.

THE TWO 12-MONTH CLOCKS ARE RIGHT TODAY BY LUCK, NOT BY DESIGN
---------------------------------------------------------------
`rate_10_expires` and `partner_credit_expires` currently show ZERO wrong rows. That is because
+365 days == +12 calendar months ONLY when no leap day falls inside the window — and none of our
current productive_dates land that way. A deal starting 2023-06-01 would give +365 = 2024-05-31
while 12 calendar months is 2024-06-01. The coin simply has not landed yet.

`partner_credit_expires` decides when a PARTNER STOPS BEING PAID. Tim: "the partner percentage
expires 12 months after the same exact kickoff." A one-day error there pays a partner for a day
they had not earned, or cuts them off a day early. Both are wrong; neither would raise an error.

All three are fixed. Not just the one that is currently bleeding.

NO MONEY MOVES. The spine already computed this correctly; only the stored columns and the display
lens were lying. Verified before and after.

Revision ID: cip_91_calendar_months
Revises: cip_90_is_chinese_one_home
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_91_calendar_months"
down_revision: str | Sequence[str] | None = "cip_90_is_chinese_one_home"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_RATE_CLOCK_VIEW = """
    CREATE VIEW lens_ps_rate_clock AS
    SELECT
        tenant_id, wayward_brand_id, client_id, product_id,
        productive_date, productive_date_source, productive_date_confidence,
        rate_10_expires, rate_6_expires, partner_credit_expires,
        CASE
            WHEN productive_date IS NULL           THEN NULL::integer
            WHEN CURRENT_DATE <= rate_10_expires   THEN 10
            WHEN CURRENT_DATE <= rate_6_expires    THEN 6
            ELSE 3
        END                                                     AS current_rate_pct,
        productive_date IS NOT NULL
            AND CURRENT_DATE <= partner_credit_expires          AS partner_still_earning,
        CASE
            WHEN productive_date IS NULL THEN NULL::integer
            ELSE rate_10_expires - CURRENT_DATE
        END                                                     AS days_until_10_drops
    FROM ps_product_subscriptions s
"""


def upgrade() -> None:
    # the view reads the generated columns, so it has to come down first
    op.execute("DROP VIEW IF EXISTS lens_ps_rate_clock CASCADE")

    for col, months in (("rate_10_expires", 12),
                        ("partner_credit_expires", 12),
                        ("rate_6_expires", 18)):
        op.execute(f"ALTER TABLE ps_product_subscriptions DROP COLUMN {col}")
        op.execute(
            f"ALTER TABLE ps_product_subscriptions ADD COLUMN {col} date "
            f"GENERATED ALWAYS AS ((productive_date + INTERVAL '{months} months')::date) STORED"
        )

    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.rate_10_expires IS "
        "'When our 10%% tier ends: productive_date + 12 CALENDAR MONTHS. "
        "*** NEVER COUNT MONTHS IN DAYS. *** This column used to be (productive_date + 365), and its "
        "sibling rate_6_expires was (productive_date + 365 + 183) = 548 days standing in for 18 "
        "months — which is 546-549 days depending on the start month. That put 2,371 of 2,829 deals "
        "on the wrong boundary and kept 1,539 of them at 6%% too long. "
        "+365 happens to equal 12 months only when no leap day falls in the window. That is luck, "
        "not correctness.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.partner_credit_expires IS "
        "'When the PARTNER stops being paid: productive_date + 12 CALENDAR MONTHS. Tim: ''the "
        "partner percentage expires 12 months after the same exact kickoff.'' "
        "This was (productive_date + 365) — right today only because no current deal spans a leap "
        "day. A one-day error here pays a partner for a day they had not earned, or cuts them off a "
        "day early. Neither would raise an error.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.rate_6_expires IS "
        "'When our 6%% tier ends and 3%% begins: productive_date + 18 CALENDAR MONTHS. "
        "*** THIS IS THE COLUMN THAT WAS BLEEDING. *** It was ((productive_date + 365) + 183) — a "
        "548-day approximation of 18 months. Wrong on 2,371 of 2,829 deals; 1,539 of them ran long, "
        "billing 6%% into month 19. compute_monthly_earnings.py was fixed long ago and used real "
        "calendar months, so the money spine was RIGHT while this column and lens_ps_rate_clock were "
        "WRONG. One fact, two computations. Every fact gets exactly one home.'"
    )

    op.execute(_RATE_CLOCK_VIEW)
    op.execute(
        "COMMENT ON VIEW lens_ps_rate_clock IS "
        "'What rate is this deal on TODAY? Reads the stored expiry columns, which are now real "
        "CALENDAR MONTHS (cip_91). Before that they were day-counts (+365, +548) and this view "
        "reported 6%% where the calendar said 3%% — on any day a deal happened to cross its "
        "boundary.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_rate_clock TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_rate_clock CASCADE")
    for col, expr in (("rate_10_expires", "(productive_date + 365)"),
                      ("partner_credit_expires", "(productive_date + 365)"),
                      ("rate_6_expires", "((productive_date + 365) + 183)")):
        op.execute(f"ALTER TABLE ps_product_subscriptions DROP COLUMN {col}")
        op.execute(
            f"ALTER TABLE ps_product_subscriptions ADD COLUMN {col} date "
            f"GENERATED ALWAYS AS ({expr}) STORED"
        )
    op.execute(_RATE_CLOCK_VIEW)
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_rate_clock TO {r}")
