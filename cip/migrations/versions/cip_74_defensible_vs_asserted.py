# foundry: kind=migration domain=client-intelligence-platform
"""cip_74: 73% of the claim rests on "Claude said so". Split DEFENSIBLE from ASSERTED.

THE FINDING THAT MATTERS MOST, AND IT IS ABOUT MY OWN WORK
----------------------------------------------------------
An adversarial audit checked my 17 manual China calls against the database. Eleven of them have
ZERO corroborating evidence — no country field, no exclusion-list entry, no Chinese partner, no
Chinese email domain, nothing. They are pure assertion. And they carry:

    $4,737.08 of a $6,449.10 invoice  =  73% of the entire claim

Neakasa, Renpho, Apolosign, SpaceAid, DEERC, Tiny Land, Selgrownsy, turandoss, Cute Stone,
Morento, RobKushner. If Jake asks "why is Neakasa Chinese?", the honest answer today is: an LLM
said so, citing world knowledge that appears nowhere in Wayward's records.

Contract §4.4 makes WAYWARD'S RECORDS "conclusive and controlling", with a 30-day dispute window.
An invoice whose evidence is our own prose is an invoice we lose.

These brands ARE Chinese — Renpho and Neakasa are well-known Shenzhen manufacturers, and Tim
personally confirmed Tiny Land. That is not the problem. The problem is that BEING RIGHT AND
BEING ABLE TO PROVE IT ARE DIFFERENT THINGS, and the schema was not distinguishing them.

TWO SPECIFIC RATIONALES THAT WERE NON-SEQUITURS
-----------------------------------------------
DEERC and Cute Stone were justified by "the same billing contact, beryl@". That establishes ONE
OPERATOR — it does not establish a CHINESE one. Beryl is a Western given name. The reasoning does
not reach its conclusion, and it carries $423.07.

RobKushner rests entirely on the domain urbantrendhk.com and the policy "HK is China for this
book". But Urban Trend HK could as easily be a Hong Kong DISTRIBUTOR for a Western brand — which
is the BrüMate structure exactly inverted. It is the closest thing to a BrüMate-class error in
the set, and it carries $328.69.

Both rationales are corrected below to say what is actually known, and both brands are now marked
as requiring external verification rather than quietly carrying a claim.

WHAT THIS MIGRATION DOES
------------------------
It does NOT retract the calls. They are probably right, and deleting a probably-right call to
feel rigorous just loses money in the other direction.

It makes the distinction VISIBLE and enforced:

    corroborated  = at least one signal OTHER than our own assertion points to China.
                    Wayward's country field, the exclusion list, a Chinese partner, a .cn domain,
                    a Stripe address_country. Something Jake can check.

    asserted_only = the ONLY evidence is a human/LLM saying so.

lens_ps_claim_pack then splits the invoice in two, so nobody can send Wayward a number without
seeing how much of it they can actually defend — and so the ask to Jake ("give us the country
field on these brands") is aimed at exactly the rows that need it.

Revision ID: cip_74_defensible_vs_asserted
Revises: cip_73_fanout_aliases_signals
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_74_defensible_vs_asserted"
down_revision: str | Sequence[str] | None = "cip_73_fanout_aliases_signals"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # ── correct the two rationales that did not reach their conclusion ───────
    op.execute(
        """
        UPDATE ps_nationality_signals
           SET evidence = 'DEERC is a Shenzhen RC-toy and drone manufacturer. NOTE: my original '
                          'rationale cited "the same billing contact (beryl@) as Cute Stone" — '
                          'that establishes ONE OPERATOR, not a CHINESE one, and Beryl is a '
                          'Western given name. The reasoning did not reach its conclusion. The '
                          'claim now rests on the company itself, and NEEDS EXTERNAL '
                          'VERIFICATION: there is no corroborating signal in Wayward''s data.'
         WHERE signal = 'manual_review'
           AND wayward_brand_id IN (SELECT wayward_brand_id FROM ps_brands WHERE brand_name = 'DEERC')
        """
    )
    op.execute(
        """
        UPDATE ps_nationality_signals
           SET evidence = 'Cute Stone is a Chinese toy manufacturer. NOTE: my original rationale '
                          'cited "the same billing contact (beryl@) as DEERC" — that establishes '
                          'ONE OPERATOR, not a CHINESE one. Non-sequitur, corrected. NEEDS '
                          'EXTERNAL VERIFICATION.'
         WHERE signal = 'manual_review'
           AND wayward_brand_id IN (SELECT wayward_brand_id FROM ps_brands WHERE brand_name = 'Cute Stone')
        """
    )
    op.execute(
        """
        UPDATE ps_nationality_signals
           SET evidence = 'Billing domain urbantrendhk.com — a Hong Kong entity. *** WEAKEST CALL '
                          'IN THE SET. *** "HK is China for this book" is a POLICY, and Urban '
                          'Trend HK could equally be a Hong Kong DISTRIBUTOR for a Western brand '
                          '— which is precisely the BrüMate structure inverted (American company, '
                          'Chinese referral channel). This is the closest thing to a BrüMate-class '
                          'error in the set and it carries $328.69. DO NOT INVOICE IT WITHOUT '
                          'ASKING JAKE.'
         WHERE signal = 'manual_review'
           AND wayward_brand_id IN (SELECT wayward_brand_id FROM ps_brands WHERE brand_name = 'RobKushner')
        """
    )

    # ── the claim pack: what we can DEFEND vs what we merely ASSERT ──────────
    op.execute("DROP VIEW IF EXISTS lens_ps_claim_pack")
    op.execute(
        """
        CREATE VIEW lens_ps_claim_pack AS
        WITH corrob AS (
            SELECT wayward_brand_id,
                   bool_or(signal <> 'manual_review' AND points_to = 'china') AS has_hard_evidence,
                   bool_or(signal =  'manual_review' AND points_to = 'china') AS was_asserted,
                   string_agg(DISTINCT signal, ', ')
                       FILTER (WHERE signal <> 'manual_review' AND points_to = 'china')
                                                                              AS hard_evidence,
                   max(evidence)    FILTER (WHERE signal = 'manual_review')   AS assertion,
                   max(asserted_by) FILTER (WHERE signal = 'manual_review')   AS asserted_by
            FROM ps_nationality_signals
            GROUP BY wayward_brand_id
        )
        SELECT
            r.wayward_brand_id,
            r.brand_name,
            r.status,
            r.ps_owed,
            r.ps_paid,
            r.balance,
            r.usage_collected,
            r.claim_basis,
            r.excluded_buckets,
            COALESCE(c.has_hard_evidence, false)                            AS corroborated,
            c.hard_evidence,
            c.assertion                                                     AS manual_rationale,
            c.asserted_by,
            CASE
                WHEN COALESCE(c.has_hard_evidence, false) THEN 'DEFENSIBLE'
                WHEN COALESCE(c.was_asserted, false)      THEN 'ASSERTED_ONLY'
                ELSE 'NO_NATIONALITY_EVIDENCE'
            END                                                             AS evidence_grade
        FROM lens_ps_claim_reconciliation r
        LEFT JOIN corrob c ON c.wayward_brand_id = r.wayward_brand_id
        WHERE r.status IN ('owed_never_paid', 'underpaid')
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_claim_pack IS "
        "'*** WHAT WE WOULD INVOICE, GRADED BY WHETHER WE CAN PROVE IT. *** "
        "DEFENSIBLE: at least one signal OTHER than our own assertion says the brand is Chinese — "
        "Wayward''s own country field, the exclusion list, a Chinese partner, a .cn domain, a "
        "Stripe address_country. Something Jake can check. "
        "ASSERTED_ONLY: the sole evidence is an LLM or a human saying so. These brands are "
        "probably Chinese (Renpho and Neakasa are well-known Shenzhen manufacturers) but §4.4 "
        "makes WAYWARD''S records conclusive and controlling, with a 30-day window — an invoice "
        "whose evidence is our own prose is an invoice we lose. 73%% of the claim started here. "
        "Sort by evidence_grade before sending anything, and aim the ask to Jake (the country "
        "field) at exactly these rows.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_claim_pack.corroborated IS "
        "'TRUE when something OTHER than our own assertion points to China. Being right and being "
        "able to PROVE it are different things, and this column is the difference.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_claim_pack TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_claim_pack")
