# foundry: kind=migration domain=client-intelligence-platform
"""cip_85: I used email as a key, and graded a $23,345 brand as a staff test account.

cip_83 introduced lens_ps_brand_reality (REAL / GHOST / JUNK) to stop us counting Stripe ghosts as
clients. It worked. It also broke something.

The JUNK test asked: "is the Stripe mailbox @wayward.com or @artica.com?" — and if so, junk.

    GCI Outdoors   $23,345.23 collected   rebecca@wayward.com     -> graded JUNK
    VANDEL            $417.17 collected   rebecca+1@wayward.com   -> graded JUNK
    ALTA              $242.79 collected   rebecca+3@wayward.com   -> graded JUNK

GCI Outdoors is a real American outdoor-furniture company. Rebecca is a Wayward employee who set
the Stripe account up ON BEHALF OF the brand. rebecca@wayward.com is attached to 10 brands;
dpathania@artica.com to 19; creators@wayward.com to 11.

docs/SOURCE-MAP.md has a trap named "EMAIL IS NEVER A KEY" and it cost us $47,750 the last time.
I read that document, wrote it, and then used email as a key anyway — as a REALITY test, which is
upstream of everything.

The remediation everyone reaches for ("just filter money views to reality='REAL'") would have
silently written off $24,005.19 of collected cash.

THE FIX: MONEY WINS.
--------------------
A row that has BILLED is a client. Full stop. No heuristic gets to overrule a payment — a Stripe
invoice that a brand actually paid is the strongest evidence of existence there is, and it beats
any guess about what its contact mailbox means.

    JUNK  = a placeholder NAME ('Brand', 'test', '1', '.', 'Generic', 'Acme'), or a staff mailbox,
            AND it never billed, AND Wayward never onboarded it.
    REAL  = billed, OR onboarded, OR has a subscription, OR has a contact, OR is on a frozen list.
    GHOST = a Stripe customer record and nothing else.

The staff-mailbox test survives — it is genuinely useful for the ghost rows nobody ever activated —
but it is now subordinate to money and to onboarding, where it belongs.

Revision ID: cip_85_reality_money_wins
Revises: cip_84_research_signals
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_85_reality_money_wins"
down_revision: str | Sequence[str] | None = "cip_84_research_signals"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_INTERNAL = r"@(wayward|artica)\."
_PLACEHOLDER = (
    "1", "none", "generic", "brand", "brand 2", "brand co", "brand test", "test", "c",
    "country", "n/a", "na", "-", ".", "null", "x", "acme", "adore", "adores", "brand_test_2",
    "1234", "777",
)


def upgrade() -> None:
    placeholders = ", ".join(f"'{p}'" for p in _PLACEHOLDER)
    op.execute("DROP VIEW IF EXISTS lens_ps_china_chase_list CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_reality CASCADE")
    op.execute(
        f"""
        CREATE VIEW lens_ps_brand_reality AS
        WITH ev AS (
            SELECT
                b.wayward_brand_id,
                b.brand_name,
                EXISTS (SELECT 1 FROM ps_monthly_earnings m
                         WHERE m.wayward_brand_id = b.wayward_brand_id)    AS ever_billed,
                EXISTS (SELECT 1 FROM ps_brand_observations o
                         WHERE o.wayward_brand_id = b.wayward_brand_id
                           AND o.source_system LIKE 'slack:%%')            AS wayward_onboarded_them,
                EXISTS (SELECT 1 FROM ps_product_subscriptions s
                         WHERE s.wayward_brand_id = b.wayward_brand_id)    AS has_subscription,
                EXISTS (SELECT 1 FROM ps_brand_contacts ct
                         WHERE ct.wayward_brand_id = b.wayward_brand_id)   AS has_contact,
                EXISTS (SELECT 1 FROM ps_excluded_brands x
                         WHERE x.wayward_brand_id = b.wayward_brand_id)    AS on_a_frozen_list,
                b.seen_in_eric_sheets                                      AS on_eric_sheet,
                -- a Wayward/Artica staff mailbox. NOT proof of anything on its own: staff set
                -- Stripe accounts up ON BEHALF OF real brands. rebecca@wayward.com -> 10 brands.
                EXISTS (SELECT 1 FROM ps_stripe_customers s
                         WHERE s.wayward_brand_id = b.wayward_brand_id
                           AND s.email ~* '{_INTERNAL}')                   AS staff_mailbox,
                (lower(btrim(COALESCE(b.brand_name, ''))) IN ({placeholders})
                 OR b.brand_name ~* '^(test|brand_test|demo|sample)'
                 OR b.brand_name IS NULL OR btrim(b.brand_name) = '')      AS placeholder_name
            FROM ps_brands b
        )
        SELECT
            ev.*,
            CASE
                -- *** MONEY WINS. *** A row that BILLED is a client, and no heuristic about its
                -- contact mailbox gets to overrule a payment. Same for a brand Wayward actually
                -- onboarded. This ordering is the whole fix: cip_83 tested JUNK first and graded
                -- GCI Outdoors ($23,345 collected) as a staff test account.
                WHEN ev.ever_billed
                  OR ev.wayward_onboarded_them
                  OR ev.has_subscription
                  OR ev.has_contact
                  OR ev.on_a_frozen_list
                  OR ev.on_eric_sheet          THEN 'REAL'
                WHEN ev.staff_mailbox
                  OR ev.placeholder_name       THEN 'JUNK'
                ELSE 'GHOST'
            END AS reality
        FROM ev
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_brand_reality IS "
        "'IS THIS ACTUALLY A BRAND? *** REAL *** = it BILLED, or Wayward onboarded it, or it holds "
        "a subscription, or we have a human contact, or it is on a frozen list. "
        "*** GHOST *** = a Stripe customer record and NOTHING else — an abandoned signup. 2,179 of "
        "the 2,194 never-billed unknowns are ghosts; researching them buys nothing. "
        "*** JUNK *** = a placeholder name, or a Wayward/Artica staff mailbox, AND it never billed "
        "and was never onboarded. "
        "*** MONEY WINS, AND THAT ORDERING IS THE POINT. *** cip_83 tested JUNK first, on the "
        "Stripe mailbox alone, and graded GCI Outdoors — a real American company with $23,345.23 "
        "collected — as a staff test account, because a Wayward employee (rebecca@wayward.com, "
        "attached to TEN brands) had set its Stripe account up on its behalf. "
        "EMAIL IS NEVER A KEY. It is a hint about who typed, not about who is. A paid invoice is "
        "the strongest evidence of existence there is and it outranks every guess.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_brand_reality TO {r}")

    op.execute(
        """
        CREATE VIEW lens_ps_china_chase_list AS
        SELECT
            r.wayward_brand_id, r.brand_name, v.verdict, v.china_evidence,
            r.wayward_onboarded_them, r.on_a_frozen_list, r.on_eric_sheet,
            ct.name AS contact_name, ct.email AS contact_email,
            ct.phone AS contact_phone, ct.country AS contact_country,
            b.signup_date
        FROM lens_ps_brand_reality r
        JOIN lens_ps_china_verdict v ON v.wayward_brand_id = r.wayward_brand_id
        JOIN ps_brands b             ON b.wayward_brand_id = r.wayward_brand_id
        LEFT JOIN LATERAL (
            SELECT name, email, phone, country FROM ps_brand_contacts c
            WHERE c.wayward_brand_id = r.wayward_brand_id
            ORDER BY (c.email IS NOT NULL) DESC, (c.phone IS NOT NULL) DESC LIMIT 1
        ) ct ON true
        WHERE r.reality = 'REAL' AND v.verdict = 'china' AND NOT r.ever_billed
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_china_chase_list IS "
        "'CONFIRMED CHINESE, REAL, AND HAS NEVER SOLD A THING. The CRM chase list — brands Wayward "
        "onboarded and never activated. Filtered to reality = ''REAL''.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_chase_list TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_chase_list CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_reality CASCADE")
