# foundry: kind=migration domain=client-intelligence-platform
"""cip_72: an ambiguous email is not an identity, and an unknown partner is not a zero.

Two defects found by adversarial audit, both of the same family: something we did not know was
being SPENT as something we had decided.

DEFECT 1 — EMAIL WAS USED AS A KEY, AND IT IS NOT ONE
------------------------------------------------------
repair_identity_spine built email -> brand_id as a plain dict: last write wins, ordered by Stripe's
pagination. But 531 emails map to MORE THAN ONE brand:

    dpathania@artica.com       -> 19 different brands   (an agency)
    zhou_yintong@163.com       -> 18                    (an agency)
    creators@wayward.com       -> 11                    (WAYWARD'S OWN mailbox)
    marketing@service908.com   -> 10

$47,749.87 of usage-fee base sits on 784 lines whose brand identity was resolved from an AMBIGUOUS
email. The assignment is NON-DETERMINISTIC — a re-run against a different pagination order picks a
different brand. This is exactly the failure repair_identity_spine's own docstring rejects NAME
matching for: "a wrong brand id yields a confident number on the wrong brand, not an error."

Four of those brands are in the live claim ($611.07). We would be invoicing Wayward for revenue we
may have attributed to the wrong company — the single most embarrassing way to lose a §4.4 dispute.

    => Identities resolved from an ambiguous email are RETRACTED to NULL. Unknown, and visibly so.
       An identity we cannot defend is worth less than no identity at all, because no identity
       raises a question and a wrong one does not.

DEFECT 2 — 'unassigned' MEANT TWO DIFFERENT THINGS
---------------------------------------------------
'unassigned' was documented as a DECISION: "nobody is credited, PS keeps the full rate." But the
attribution rebuild ALSO wrote 'unassigned' whenever it could not decode a referrer — Eric's
two-letter codes (WE/WT/WX/VY/WG/MA), and referrers erased by an exact-match canonicaliser
("other(Ledo (openlight tech))" -> unassigned).

So 636 brands where Wayward's own data NAMES A REFERRER now claim the full 10% and pay that
referrer nothing. An UNKNOWN is being spent as a DECIDED ZERO — the identical sin cip_55 removed
from the rate, and cip_65 removed from nationality, reappearing on the partner.

    => match_status already records the doubt ('unknown' vs 'confirmed'). The money never read it.
       partner_rate is now NULL — not 0 — wherever a referrer was STATED but could not be decoded.
       NULL propagates: partner_owed and ps_net_owed become NULL, and the row says out loud that
       we do not know what we keep.

    ps_gross_owed is deliberately UNAFFECTED. What Wayward owes US is 10% of collected, whoever
    the partner turns out to be — the partner split is our problem, not theirs. The claim stands;
    only our NET is unknown.

Revision ID: cip_72_unknown_is_not_zero
Revises: cip_71_reconciliation_truth
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_72_unknown_is_not_zero"
down_revision: str | Sequence[str] | None = "cip_71_reconciliation_truth"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # ── 1. retract identities resolved from an ambiguous email ───────────────
    for tbl in ("ps_stripe_invoices", "ps_stripe_invoice_lines"):
        op.execute(
            f"""
            UPDATE {tbl} t
               SET wayward_brand_id = NULL,
                   brand_id_source  = NULL
             WHERE t.brand_id_source IN ('stripe_email_match', 'slack_feed_email')
               AND EXISTS (
                    SELECT 1
                    FROM ps_stripe_customers c
                    WHERE c.wayward_brand_id = t.wayward_brand_id
                      AND lower(c.email) IN (
                            SELECT lower(email) FROM ps_stripe_customers
                             WHERE email IS NOT NULL AND wayward_brand_id IS NOT NULL
                             GROUP BY lower(email)
                            HAVING count(DISTINCT wayward_brand_id) > 1)
               )
            """
        )
    op.execute(
        "COMMENT ON COLUMN ps_stripe_invoice_lines.brand_id_source IS "
        "'HOW we know this line''s brand. stripe_metadata (Wayward set it) > stripe_description "
        "(Wayward''s own UUID, filed in free text) > stripe_email_match / slack_feed_email. "
        "*** EMAIL IS NOT A KEY: 531 addresses map to more than one brand — dpathania@artica.com "
        "to 19 of them, creators@wayward.com to 11. Identities resolved from an AMBIGUOUS email "
        "have been retracted to NULL (cip_72). An identity we cannot defend is worth less than no "
        "identity at all: no identity raises a question, a wrong one does not. ***'"
    )

    # ── 2. an unknown partner is not a zero ─────────────────────────────────
    op.execute(
        """
        UPDATE ps_partner_credit
           SET partner_rate = NULL,
               determination_note = COALESCE(determination_note, '') ||
                 ' | RATE SET TO NULL (cip_72): Wayward''s data NAMES a referrer for this brand, '
                 'but we could not decode it (Eric''s two-letter codes, or a referrer erased by '
                 'the canonicaliser). ''unassigned'' was being read as a DECISION that nobody is '
                 'credited, so PS claimed the full rate and paid the referrer nothing. It is an '
                 'UNKNOWN. NULL now propagates to partner_owed and ps_net_owed, so the row says '
                 'we do not know what we keep. What WAYWARD owes us is unaffected.'
         WHERE partner_of_record = 'unassigned'
           AND match_status = 'unknown'
           AND referral_detail_raw IS NOT NULL
           AND partner_rate IS NOT NULL
        """
    )

    # ── 3. NULL must actually propagate. Kill the COALESCE on partner_rate. ──
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_performance")
    op.execute("DROP VIEW IF EXISTS lens_ps_client_performance")
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_statement CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_unclaimed")
    op.execute(
        """
        ALTER TABLE ps_monthly_earnings
            DROP COLUMN IF EXISTS variance,
            DROP COLUMN IF EXISTS ps_net_owed,
            DROP COLUMN IF EXISTS partner_owed
        """
    )
    op.execute(
        """
        ALTER TABLE ps_monthly_earnings
            ADD COLUMN partner_owed NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * partner_rate_pct / 100.0, 2)) STORED,
            ADD COLUMN ps_net_owed NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * ps_rate_pct / 100.0, 2)
                  - ROUND(usage_collected * partner_rate_pct / 100.0, 2)) STORED,
            ADD COLUMN variance NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * ps_rate_pct / 100.0, 2)
                  - ROUND(usage_collected * partner_rate_pct / 100.0, 2)
                  - ps_actually_paid) STORED
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.partner_owed IS "
        "'What the partner earns, out of OUR cut. NULL when partner_rate_pct is NULL — meaning "
        "Wayward''s data names a referrer we could not decode, so we do NOT know what the partner "
        "is owed and therefore do not know what we keep. The COALESCE(...,0) that used to sit here "
        "turned that unknown into a confident zero and let PS book the full 10%%.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.ps_net_owed IS "
        "'What PS KEEPS: gross minus the partner''s cut. NULL when the partner is unknown. *** "
        "This is NOT what we invoice Wayward. *** Wayward owes ps_gross_owed — the partner split "
        "is our internal problem, not theirs. Invoicing from net under-bills by the partner''s "
        "share.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.partner_rate_pct IS "
        "'The partner''s %% of the base. ZERO is a DECISION (flat_fee = paid once; ''unassigned'' "
        "with no referrer named = nobody credited). NULL is an UNKNOWN — Wayward names a referrer "
        "we cannot decode. The two are not the same and must never be collapsed.'"
    )

    # rebuild the dependants on the corrected columns
    op.execute(
        """
        CREATE VIEW lens_ps_unclaimed AS
        SELECT e.claim_basis, e.product_id,
               count(DISTINCT e.wayward_brand_id)                       AS brands,
               count(*)                                                 AS brand_months,
               round(sum(e.usage_collected), 2)                         AS usage_collected,
               round(sum(e.ps_gross_owed), 2)                           AS ps_owed_gross,
               round(sum(e.ps_actually_paid), 2)                        AS ps_paid,
               round(sum(e.ps_gross_owed) - sum(e.ps_actually_paid), 2) AS shortfall,
               count(*) FILTER (WHERE e.ps_rate_pct IS NULL)            AS rows_unknown_rate,
               count(*) FILTER (WHERE e.partner_rate_pct IS NULL)       AS rows_unknown_partner
        FROM ps_monthly_earnings e
        WHERE e.is_claimable
        GROUP BY 1, 2
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_unclaimed IS "
        "'What Wayward owes and has not paid, by the rule that entitles us. ps_owed_gross is the "
        "invoice figure — Wayward owes the GROSS; the partner split comes out of it afterwards and "
        "is our problem. rows_unknown_partner counts rows where we do not know what we KEEP. "
        "*** This is a monthly view and Jake pays 1-3 months in arrears — reconcile at BRAND level "
        "in lens_ps_claim_reconciliation before invoicing anything. ***'"
    )
    op.execute(
        """
        CREATE VIEW lens_ps_partner_statement AS
        SELECT e.partner_id, r.name AS partner_name, r.company_name,
               e.period_month, e.wayward_brand_id, e.brand_name, e.product_id,
               round(e.usage_collected, 2)   AS usage_fees_collected,
               round(e.usage_outstanding, 2) AS billed_not_yet_collected,
               e.partner_rate_pct            AS your_rate_pct,
               round(e.partner_owed, 2)      AS you_earned,
               pc.credit_start               AS your_window_opened,
               pc.credit_end                 AS your_window_closes,
               (e.period_month >= pc.credit_end) AS window_expired,
               e.months_since_productive
        FROM ps_monthly_earnings e
        JOIN ps_partner_registry r ON r.partner_id = e.partner_id AND r.tenant_id = e.tenant_id
        LEFT JOIN ps_partner_credit pc ON pc.wayward_brand_id = e.wayward_brand_id
                                      AND pc.product_id = e.product_id
                                      AND pc.tenant_id = e.tenant_id
        WHERE e.partner_id IS NOT NULL AND e.partner_id <> 'unassigned' AND e.is_claimable
        """
    )
    op.execute(
        """
        CREATE VIEW lens_ps_partner_summary AS
        SELECT s.partner_id, s.partner_name, s.company_name,
               count(DISTINCT s.wayward_brand_id)                            AS brands,
               count(DISTINCT s.wayward_brand_id) FILTER (
                    WHERE NOT s.window_expired)                              AS brands_still_earning,
               min(s.period_month)                                           AS first_month,
               max(s.period_month)                                           AS latest_month,
               round(sum(s.usage_fees_collected), 2)                         AS usage_collected,
               round(sum(s.billed_not_yet_collected), 2)                     AS in_the_pipeline,
               round(sum(s.you_earned), 2)                                   AS earned_to_date,
               min(s.your_window_closes) FILTER (WHERE NOT s.window_expired) AS next_window_closes
        FROM lens_ps_partner_statement s
        GROUP BY 1, 2, 3
        """
    )
    for v in ("lens_ps_unclaimed", "lens_ps_partner_statement", "lens_ps_partner_summary"):
        for r in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {v} TO {r}")


def downgrade() -> None:
    # The retracted identities and cleared rates are NOT restored: they were wrong, and putting a
    # wrong brand id or a made-up partner rate back to satisfy symmetry is the opposite of a fix.
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_summary")
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_statement")
    op.execute("DROP VIEW IF EXISTS lens_ps_unclaimed")
