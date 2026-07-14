# foundry: kind=migration domain=client-intelligence-platform
"""cip_71: three defects that moved the invoice, and the reconciliation that inverts it.

Found by an adversarial audit of the money math, then verified independently. All three were
invisible in the totals and all three were real money.

DEFECT A — $4,012.06 OF RECEIVED CASH WAS BEING THROWN AWAY
-----------------------------------------------------------
ps_actually_paid was joined with `AND u.product_id = 'connect'`, so any payment that could not
find a Connect row that month was silently dropped:

    Jake's reports say he paid us   $23,298.85
    Landed in the spine             $19,286.79
    DROPPED                          $4,012.06

variance = owed - paid, so every dropped dollar of cash WE HAVE ALREADY RECEIVED inflated the
claim 1:1. This is the direction that gets you challenged under §4.4, where Wayward's records are
"conclusive and controlling" and the dispute window is 30 days.

AND THE JOIN WAS ON THE WRONG AXIS ENTIRELY
-------------------------------------------
Jake's payment_date is when he PAID, not the month the usage was FOR. Measured across every brand
where the same amount appears on both sides:

    payment lands 2 months after the usage   794 matches
    payment lands 1 month after              133
    3+ months after                           60

So `pd.m = u.billing_month` was comparing a March PAYMENT against March USAGE, when the March
payment is settling January. Owed is indexed by usage month; paid is indexed by payment month.
They are different axes, and a month-by-month variance across them is meaningless no matter how
the join is written.

    => The claim is reconciled at BRAND level (lens_ps_claim_reconciliation). Month-level variance
       is kept for trend-spotting only, and its column comment now says so, loudly.

DEFECT B — 548 DAYS IS NOT 18 MONTHS
------------------------------------
The 6% -> 3% step used `productive_date + 365 + 183`. Eighteen calendar months from the 1st is
546-549 days depending on the start month, so when it is 546 or 547 the nineteenth month falls
INSIDE the boundary and keeps 6%.

    46 brands, $7,243.84 collected, booked at 6% = $434.64, correct at 3% = $217.32
    OVERSTATED by $217.32

Systematic, and it grows: every brand crosses month 19 exactly once, and this book is young. Now
INTERVAL '18 months'. (The 10->6 boundary at +365 is correct — verified, 0 mismatches.)

DEFECT E — 'NULL BECOMES A NUMBER', RELOCATED FROM rate TO deal_type
--------------------------------------------------------------------
457 rows have ps_partner_credit.deal_type = NULL — we do not know whether the partner is on a
flat fee or a rev share — and populate_partner_economics only zeroes the KNOWN flat_fee rows. An
unknown deal type therefore fell through to the 5% default and paid the partner $1,054.97 out of
Project Silk's net.

This is precisely the sin cip_55 was written to kill, moved one field across: an unknown silently
becoming a number. If we do not know the deal, we do not know the rate, and NULL must propagate.

Revision ID: cip_71_reconciliation_truth
Revises: cip_70_partner_reporting
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_71_reconciliation_truth"
down_revision: str | Sequence[str] | None = "cip_70_partner_reporting"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # ── DEFECT E: an unknown deal type must not pay a partner ────────────────
    op.execute(
        """
        UPDATE ps_partner_credit
           SET partner_rate = NULL,
               determination_note = COALESCE(determination_note, '') ||
                 ' | RATE CLEARED (cip_71): deal_type is UNKNOWN, so the partner rate is unknown '
                 'too. It had defaulted to 5% and was paying out $1,054.97 of Project Silk net on '
                 'deals nobody has established. An unknown must not become a number.'
         WHERE deal_type IS NULL
           AND partner_rate IS NOT NULL
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.partner_rate IS "
        "'The partner''s %% of the usage-fee base, taken OUT of our 10. ZERO is a DECISION "
        "(flat_fee: paid once, earns nothing ongoing; ''unassigned'': nobody credited). NULL is an "
        "UNKNOWN and must never become a number — 457 rows with an unknown deal_type were "
        "defaulting to 5%% and paying out $1,054.97 of PS net on deals nobody had established.'"
    )

    # ── THE CLAIM, reconciled where it is actually meaningful: per BRAND ─────
    op.execute("DROP VIEW IF EXISTS lens_ps_claim_reconciliation")
    op.execute(
        """
        CREATE VIEW lens_ps_claim_reconciliation AS
        WITH owed AS (
            SELECT wayward_brand_id,
                   sum(ps_gross_owed) FILTER (WHERE is_claimable)  AS ps_owed,
                   sum(usage_collected) FILTER (WHERE is_claimable) AS collected,
                   min(period_month) FILTER (WHERE is_claimable)    AS first_month,
                   max(period_month) FILTER (WHERE is_claimable)    AS last_month,
                   string_agg(DISTINCT claim_basis, ', ')
                       FILTER (WHERE is_claimable)                  AS claim_basis
            FROM ps_monthly_earnings
            GROUP BY wayward_brand_id
        ),
        paid AS (
            -- ALL of it. Nothing dropped, no product filter, no month matching — Jake's payment
            -- month is 1-3 months adrift of the usage month, so only the BRAND total is comparable.
            SELECT wayward_brand_id, sum(rev_share_stated) AS ps_paid
            FROM ps_payment_events
            GROUP BY wayward_brand_id
        )
        SELECT
            b.wayward_brand_id,
            b.brand_name,
            COALESCE(o.ps_owed, 0)                                  AS ps_owed,
            COALESCE(p.ps_paid, 0)                                  AS ps_paid,
            round(COALESCE(o.ps_owed,0) - COALESCE(p.ps_paid,0), 2) AS balance,
            CASE
                WHEN COALESCE(o.ps_owed,0) > 0 AND COALESCE(p.ps_paid,0) = 0
                     THEN 'owed_never_paid'
                WHEN COALESCE(o.ps_owed,0) > COALESCE(p.ps_paid,0) + 0.01
                     THEN 'underpaid'
                WHEN COALESCE(p.ps_paid,0) > COALESCE(o.ps_owed,0) + 0.01
                     AND COALESCE(o.ps_owed,0) > 0
                     THEN 'OVERPAID'
                WHEN COALESCE(o.ps_owed,0) = 0 AND COALESCE(p.ps_paid,0) > 0
                     THEN 'PAID_ON_A_BRAND_WE_DO_NOT_CLAIM'
                ELSE 'square'
            END                                                     AS status,
            round(o.collected, 2)                                   AS usage_collected,
            o.claim_basis,
            o.first_month,
            o.last_month,
            st.is_excluded,
            st.buckets                                              AS excluded_buckets
        FROM ps_brands b
        LEFT JOIN owed o ON o.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN paid p ON p.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
        WHERE COALESCE(o.ps_owed, 0) <> 0 OR COALESCE(p.ps_paid, 0) <> 0
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_claim_reconciliation IS "
        "'*** THE CLAIM. Reconciled per BRAND, because that is the only axis on which it means "
        "anything. *** Jake''s payment_date is 1-3 months AFTER the usage month it settles (794 "
        "brand-matches at 2 months'' lag), so `owed` is indexed by USAGE month and `paid` by "
        "PAYMENT month — a month-by-month variance across those axes is meaningless however the "
        "join is written. READ THE STATUS COLUMN BEFORE QUOTING A NUMBER: we are underpaid on 137 "
        "brands ($6,759.63) and OVERPAID on 429 others ($14,027) — mostly the excluded flat-fee "
        "book Wayward pays us on voluntarily, owing nothing. Net, they have paid us MORE than the "
        "contract requires. Under §4.4 their records are conclusive and controlling with a 30-day "
        "window, so invoicing the $6,759 without knowing about the $14,027 invites an audit that "
        "leaves us $7,267 WORSE off.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_claim_reconciliation.status IS "
        "'owed_never_paid / underpaid -> our claim. OVERPAID / PAID_ON_A_BRAND_WE_DO_NOT_CLAIM -> "
        "Wayward paying beyond the contract, overwhelmingly on the Eric flat-fee book. That is "
        "ESTABLISHED PRACTICE and it is the strongest card we hold with Ali — but it is also a "
        "clawback risk, and the two facts have to be held together.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_claim_reconciliation TO {r}")

    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.variance IS "
        "'ps_net_owed - ps_actually_paid, PER MONTH. *** DO NOT INVOICE FROM THIS. *** Jake pays "
        "1-3 months in arrears, so a month''s `owed` and that month''s `paid` describe different "
        "usage. Useful for spotting a trend; useless as a balance. The claim lives in "
        "lens_ps_claim_reconciliation, at brand level.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.ps_actually_paid IS "
        "'What Jake''s report says Wayward paid us, landed on this brand-month. NOTE the axis "
        "mismatch: his payment_date is 1-3 months AFTER the usage it settles. Reconcile at BRAND "
        "level (lens_ps_claim_reconciliation), never month by month.'"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_claim_reconciliation")
