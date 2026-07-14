# foundry: kind=migration domain=client-intelligence-platform
"""cip_83: is this actually a brand? Nothing in the schema could answer that, so every count lied.

I told Tim there were 1,071 "CRM gold" brands — confirmed Chinese, never billed, ready to chase.
The real number is 381. The other 690 were STRIPE CUSTOMER RECORDS WITH NOTHING BEHIND THEM: no
subscription, no invoice line, never onboarded through Wayward's Slack feed, no contact, not on any
list. Abandoned checkouts. I counted them as brands because nothing in the schema said they weren't.

That error was not a one-off. It was silently in EVERY number in this dataset:

    ps_brands rows ................... 5,352
      REAL brands ....................    ~2,400
      GHOSTS (a Stripe row, nothing else)  ~2,800
      JUNK (Wayward/Artica staff tests)      129

THE THREE STATES
----------------
    REAL   Wayward onboarded them (the Slack brand-connections feed), OR they billed, OR they hold
           a product subscription, OR we have a human contact, OR they are on a frozen list.
           These are clients. Every claim, every chase, every count belongs here.

    GHOST  A Stripe customer record and nothing else. Somebody started a signup and stopped.
           They never became a client. Determining a ghost's nationality buys nothing: there is no
           deal, no revenue and no relationship behind it. 2,179 of the 2,194 never-billed unknowns
           are ghosts — which is why researching that pile would have been 2,000 lookups to learn
           that an abandoned checkout was Chinese.

    JUNK   Not a brand at all. kevin@wayward.com, rebecca+2@wayward.com, dpathania@artica.com,
           eshapiro@artica.com — Wayward's and Artica's own staff, testing the product. Brands
           literally named 'Brand', 'Brand 2', 'Brand test', 'Generic', 'Acme', '1', '.'.
           THREE OF THEM HAVE BILLING ATTACHED, so they are in the money spine too.

WHY THIS IS A LENS AND NOT A COLUMN
-----------------------------------
Reality is derived, and it CHANGES. A ghost that finally onboards becomes real that day; a column
would have to be maintained and would drift. The lens is always right, by construction.

Revision ID: cip_83_brand_reality
Revises: cip_82_lists_are_definitive
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_83_brand_reality"
down_revision: str | Sequence[str] | None = "cip_82_lists_are_definitive"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# Wayward's and Artica's own staff, testing the product. Not clients.
_INTERNAL = r"@(wayward|artica)\."
# placeholder names people type into a form to get past it
_PLACEHOLDER = (
    "1", "none", "generic", "brand", "brand 2", "brand co", "brand test", "test", "c",
    "country", "n/a", "na", "-", ".", "null", "x", "acme", "adore", "adores", "brand_test_2",
)


def upgrade() -> None:
    placeholders = ", ".join(f"'{p}'" for p in _PLACEHOLDER)
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_reality CASCADE")
    op.execute(
        f"""
        CREATE VIEW lens_ps_brand_reality AS
        SELECT
            b.wayward_brand_id,
            b.brand_name,
            -- the evidence that this is a real client
            EXISTS (SELECT 1 FROM ps_brand_observations o
                     WHERE o.wayward_brand_id = b.wayward_brand_id
                       AND o.source_system LIKE 'slack:%%')            AS wayward_onboarded_them,
            EXISTS (SELECT 1 FROM ps_monthly_earnings m
                     WHERE m.wayward_brand_id = b.wayward_brand_id)    AS ever_billed,
            EXISTS (SELECT 1 FROM ps_product_subscriptions s
                     WHERE s.wayward_brand_id = b.wayward_brand_id)    AS has_subscription,
            EXISTS (SELECT 1 FROM ps_brand_contacts ct
                     WHERE ct.wayward_brand_id = b.wayward_brand_id)   AS has_contact,
            EXISTS (SELECT 1 FROM ps_excluded_brands x
                     WHERE x.wayward_brand_id = b.wayward_brand_id)    AS on_a_frozen_list,
            b.seen_in_eric_sheets                                      AS on_eric_sheet,
            CASE
                -- JUNK first: an internal test row can still carry billing, and it must never
                -- be counted as a client just because money moved through it.
                WHEN EXISTS (SELECT 1 FROM ps_stripe_customers s
                              WHERE s.wayward_brand_id = b.wayward_brand_id
                                AND s.email ~* '{_INTERNAL}')
                  OR lower(btrim(COALESCE(b.brand_name, ''))) IN ({placeholders})
                  OR b.brand_name ~* '^(test|brand_test|demo|sample)'
                  OR b.brand_name IS NULL OR btrim(b.brand_name) = ''
                     THEN 'JUNK'
                WHEN EXISTS (SELECT 1 FROM ps_brand_observations o
                              WHERE o.wayward_brand_id = b.wayward_brand_id
                                AND o.source_system LIKE 'slack:%%')
                  OR EXISTS (SELECT 1 FROM ps_monthly_earnings m
                              WHERE m.wayward_brand_id = b.wayward_brand_id)
                  OR EXISTS (SELECT 1 FROM ps_product_subscriptions s
                              WHERE s.wayward_brand_id = b.wayward_brand_id)
                  OR EXISTS (SELECT 1 FROM ps_brand_contacts ct
                              WHERE ct.wayward_brand_id = b.wayward_brand_id)
                  OR EXISTS (SELECT 1 FROM ps_excluded_brands x
                              WHERE x.wayward_brand_id = b.wayward_brand_id)
                  OR b.seen_in_eric_sheets
                     THEN 'REAL'
                ELSE 'GHOST'
            END                                                        AS reality
        FROM ps_brands b
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_brand_reality IS "
        "'IS THIS ACTUALLY A BRAND? Nothing in the schema could answer that, so every count was "
        "quietly inflated — I reported 1,071 chaseable Chinese brands when the real number was 381. "
        "*** REAL *** = Wayward onboarded them (Slack feed), OR they billed, OR they hold a "
        "subscription, OR we have a human contact, OR they are on a frozen list. These are clients. "
        "*** GHOST *** = a Stripe customer record and NOTHING else. Somebody started a signup and "
        "stopped. Determining a ghost''s nationality buys nothing — no deal, no revenue, no "
        "relationship. 2,179 of the 2,194 never-billed unknowns are ghosts. "
        "*** JUNK *** = Wayward''s and Artica''s own staff testing the product "
        "(kevin@wayward.com, dpathania@artica.com) and placeholder names (''Brand'', ''test'', "
        "''1''). THREE CARRY BILLING, so they sit in the money spine too. "
        "JUNK is tested FIRST, on purpose: an internal test row must never count as a client just "
        "because money moved through it. "
        "*** ALWAYS filter to reality = ''REAL'' before quoting any number to anyone. ***'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_brand_reality TO {r}")

    # ── the chase list, which is the whole point ────────────────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_china_chase_list CASCADE")
    op.execute(
        """
        CREATE VIEW lens_ps_china_chase_list AS
        SELECT
            r.wayward_brand_id,
            r.brand_name,
            v.verdict,
            v.china_evidence,
            r.wayward_onboarded_them,
            r.on_a_frozen_list,
            r.on_eric_sheet,
            ct.name       AS contact_name,
            ct.email      AS contact_email,
            ct.phone      AS contact_phone,
            ct.country    AS contact_country,
            b.signup_date
        FROM lens_ps_brand_reality r
        JOIN lens_ps_china_verdict v ON v.wayward_brand_id = r.wayward_brand_id
        JOIN ps_brands b             ON b.wayward_brand_id = r.wayward_brand_id
        LEFT JOIN LATERAL (
            SELECT name, email, phone, country
            FROM ps_brand_contacts c
            WHERE c.wayward_brand_id = r.wayward_brand_id
            ORDER BY (c.email IS NOT NULL) DESC, (c.phone IS NOT NULL) DESC
            LIMIT 1
        ) ct ON true
        WHERE r.reality = 'REAL'
          AND v.verdict = 'china'
          AND NOT r.ever_billed
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_china_chase_list IS "
        "'CONFIRMED CHINESE, REAL, AND HAS NEVER SOLD A THING. This is the CRM chase list and it is "
        "the payoff of the whole nationality exercise: brands Wayward onboarded and never activated. "
        "*** 381 of them, and 315 have a human with an email and often a +86 phone. *** "
        "Filtered to reality = ''REAL'' — the naive version of this query returns 1,071 because it "
        "counts 690 Stripe ghosts that never became clients. Revenue does not decide who is Chinese, "
        "but REALITY decides who is worth calling.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_chase_list TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_chase_list CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_reality CASCADE")
