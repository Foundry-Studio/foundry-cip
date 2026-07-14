# foundry: kind=migration domain=client-intelligence-platform
"""cip_89: a Chinese partner's referral CONFIRMS china. BrüMate is the only exception.

TIM, 2026-07-14, ruling on the probable queue:

    "if they were refered by tsoe chinese partners, yes they are chinese. BruMAte is the only
     exception for now. And tose are hre for sure chniese ones."

This REVERSES the tier I put `chinese_partner` in one migration ago, and Tim is right.

WHAT I GOT WRONG, TWICE
-----------------------
I reasoned: BrüMate is American and was referred by a Chinese partner, therefore a referral is not a
nationality, therefore `chinese_partner` is channel evidence and belongs in `probable`.

That inverts the base rate. Our China partners — Kerry, Cassie, Sarah, Adina, Eric, Shallow,
OpenLight, Chen, Caspar, DBZW — source Chinese brands. That is their job and it is why they are
called China partners. **BrüMate is the exception that proves the rule, not a rule of its own.** I
took a single counterexample and let it overturn 575 brands' worth of base rate.

I already made this mistake once today in a worse form: I DROPPED SZEE, Lille Home and Yoleo out of
the book entirely, on the reasoning that "Wayward's feed says US". Tim: "DONT ASSUME THAT WAYWARD
DATA IS CORRECT... if its chinese refered those other brands, they are LIKELY chinese."

MEASURED BLAST RADIUS: exactly 3 brands
---------------------------------------
`chinese_partner` covers 575 REAL brands. 572 are ALREADY confirmed china on independent evidence —
a list, a CN country field, a Chinese mailbox. Only THREE rest on the referral alone:

    SZEE        referred by adina       marketing@szeepet.com
    Lille Home  referred by kerry       yilin2008@gmail.com     <- "Yi Lin", a Chinese name
    Yoleo       referred by openlight   therunaffiliate@outlook.com

All three go to china. The `probable` tier empties, and stays as a live state for future
name-only evidence.

BRUMATE IS UNTOUCHED, AND STRUCTURALLY SO
------------------------------------------
Verified before applying: BrüMate does not even carry a `chinese_partner` signal (her China evidence
is `on_exclusion_list`, the OceanWing bucket). And a named human's `not_china` is read FIRST in the
verdict CASE, before any confirming indicator is looked at. Her ruling cannot be overturned by a
rule change — that is the whole point of the human tier.

Revision ID: cip_89_referral_confirms
Revises: cip_88_four_state_verdict
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_89_referral_confirms"
down_revision: str | Sequence[str] | None = "cip_88_four_state_verdict"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# ANY ONE of these confirms china. Tim: "any of them, they are confirmed."
# `chinese_partner` JOINS THIS LIST — our China partners source Chinese brands. That is the job.
_CONFIRMING = (
    "on_exclusion_list", "eric_sheet", "wayward_country_cn", "chinese_email_domain",
    "cjk_in_name", "phone_+86", "qq_handle", "cn_mobile_handle", "cn_company_name_pinyin",
    "shared_owner_mailbox", "amazon_seller_entity", "uspto_trademark_owner",
    "tim_batch_approval", "chinese_partner",
)
_LEGAL = ("amazon_seller_entity", "uspto_trademark_owner")
# What is left in probable: a NAME. A Chinese name is not a Chinese company — Bob and Brad is
# Chinese, Lifepro is Los Angeles. A name still goes to a human, always.
_PROBABLE = ("pinyin_name_in_email", "pinyin_contact_name")


def _arr(xs: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{x}'" for x in xs) + ")"


def _verdict_view(confirming: tuple[str, ...], legal: tuple[str, ...],
                  probable: tuple[str, ...]) -> str:
    return f"""
        CREATE VIEW lens_ps_china_verdict AS
        WITH agg AS (
            SELECT
                wayward_brand_id,
                bool_or(signal = 'manual_review' AND points_to = 'not_china')  AS human_not_china,
                bool_or(signal = 'manual_review' AND points_to = 'china')      AS human_china,
                count(*) FILTER (WHERE points_to = 'china'
                                   AND signal IN {_arr(confirming)})           AS confirming,
                count(*) FILTER (WHERE points_to = 'not_china'
                                   AND signal IN {_arr(legal)})                AS legal_not_china,
                count(*) FILTER (WHERE points_to = 'china'
                                   AND signal IN {_arr(probable)})             AS probable_tier,
                count(*) FILTER (WHERE signal = 'wayward_country_other')       AS wayward_says_us,
                max(CASE strength
                        WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5
                        WHEN 'strong'       THEN 4 WHEN 'moderate'  THEN 3
                        WHEN 'weak'         THEN 2 ELSE 1 END)
                    FILTER (WHERE points_to = 'china'
                              AND signal IN {_arr(confirming)})                AS best_china_rank,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to = 'china')
                                                                               AS china_evidence,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to = 'not_china')
                                                                               AS not_china_evidence,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to = 'china'
                                                            AND signal IN {_arr(probable)})
                                                                               AS probable_evidence,
                max(evidence)    FILTER (WHERE signal = 'manual_review')       AS manual_rationale,
                max(asserted_by) FILTER (WHERE signal = 'manual_review')       AS manual_by
            FROM ps_nationality_signals
            GROUP BY wayward_brand_id
        ),
        money AS (
            SELECT wayward_brand_id,
                   sum(usage_collected)                              AS collected,
                   sum(ps_gross_owed)                                AS gross_if_claimable,
                   sum(ps_gross_owed)    FILTER (WHERE is_claimable) AS ps_owed,
                   sum(ps_actually_paid) FILTER (WHERE is_claimable) AS ps_paid
            FROM ps_monthly_earnings GROUP BY wayward_brand_id
        )
        SELECT
            b.wayward_brand_id, b.brand_name, b.signup_date,
            CASE
                WHEN a.human_not_china                   THEN 'not_china'
                WHEN a.human_china                       THEN 'china'
                WHEN COALESCE(a.confirming, 0)      > 0  THEN 'china'
                WHEN COALESCE(a.legal_not_china, 0) > 0  THEN 'not_china'
                WHEN COALESCE(a.probable_tier, 0)   > 0  THEN 'probable'
                ELSE 'unknown'
            END                                                          AS verdict,
            CASE
                WHEN a.human_not_china OR a.human_china  THEN 'human'
                WHEN COALESCE(a.confirming, 0) > 0 THEN
                    CASE a.best_china_rank
                        WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed'
                        WHEN 4 THEN 'strong'       ELSE 'confirmed' END
                WHEN COALESCE(a.legal_not_china, 0) > 0  THEN 'legal_record'
                WHEN COALESCE(a.probable_tier, 0)   > 0  THEN 'needs_a_human'
                ELSE NULL
            END                                                          AS verdict_strength,
            a.china_evidence, a.not_china_evidence, a.probable_evidence,
            (COALESCE(a.wayward_says_us, 0) > 0)                         AS corroborates_not_china,
            a.manual_rationale, a.manual_by,
            (COALESCE(a.confirming, 0) > 0 AND COALESCE(a.legal_not_china, 0) > 0)
                                                                         AS has_conflict,
            COALESCE(st.is_excluded, false)                              AS is_excluded,
            st.buckets                                                   AS excluded_buckets,
            (m.wayward_brand_id IS NOT NULL)                             AS ever_billed,
            round(m.collected, 2)                                        AS usage_collected,
            round(COALESCE(m.ps_owed, 0), 2)                             AS ps_owed_claimable,
            round(COALESCE(m.ps_paid, 0), 2)                             AS ps_paid,
            round(COALESCE(m.ps_owed, 0) - COALESCE(m.ps_paid, 0), 2)    AS shortfall,
            round(m.gross_if_claimable, 2)                               AS hypothetical_if_all_claimable
        FROM ps_brands b
        LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN agg   a ON a.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id
    """


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict CASCADE")
    op.execute(_verdict_view(_CONFIRMING, _LEGAL, _PROBABLE))
    op.execute(
        "COMMENT ON VIEW lens_ps_china_verdict IS "
        "'THE CONSTITUTION. *** china *** = ANY approved confirming indicator, or a named human. "
        "*** probable *** = a NAME only (pinyin) — Tim''s check queue. *** not_china *** = a named "
        "HUMAN or a LEGAL RECORD (amazon_seller_entity / uspto_trademark_owner). NOTHING ELSE. "
        "*** unknown *** = nothing. "
        "*** A CHINESE PARTNER''S REFERRAL CONFIRMS CHINA. *** Tim, 2026-07-14: ''if they were "
        "refered by tsoe chinese partners, yes they are chinese. BruMAte is the only exception for "
        "now.'' Our China partners (Kerry, Cassie, Sarah, Adina, Eric, Shallow, OpenLight, Chen, "
        "Caspar, DBZW) SOURCE CHINESE BRANDS — that is the job. BruMate is the exception that "
        "proves the rule, not a rule of its own; she is protected structurally, because a named "
        "human''s not_china is read FIRST and cannot be overturned by any rule change. "
        "*** wayward_country_other DECIDES NOTHING. *** 104 CONFIRMED-CHINESE brands carry it — a "
        "Chinese seller behind a US-registered shell reports as US, which is the entire pattern "
        "this audit exists to find. It corroborates. It never clears. "
        "Tim: ''DONT ASSUME THAT WAYAWARD DATA IS CORRECT.'''"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_china_verdict.corroborates_not_china IS "
        "'Wayward''s own feed or HubSpot records this brand as non-Chinese. CORROBORATION ONLY — it "
        "decides nothing, and 104 confirmed-Chinese brands carry it. Never filter on this column.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_china_verdict.probable_evidence IS "
        "'A Chinese personal NAME on a contact or a mailbox — and nothing else. A Chinese NAME is "
        "not a Chinese COMPANY: Bob and Brad is Chinese, Lifepro is Los Angeles. This always goes "
        "to a human. (A referral no longer lands here — Tim ruled a Chinese partner''s referral "
        "CONFIRMS china, cip_89.)'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_verdict TO {r}")

    # the two dependent views are unchanged in meaning; recreate them on the new verdict
    op.execute(
        """
        CREATE VIEW lens_ps_china_chase_list AS
        WITH collapsed AS (
            SELECT DISTINCT ON (COALESCE(b.canonical_brand_id, b.wayward_brand_id))
                COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS brand_id,
                b.wayward_brand_id, b.brand_name, b.signup_date
            FROM ps_brands b
            JOIN lens_ps_brand_reality r ON r.wayward_brand_id = b.wayward_brand_id
            JOIN lens_ps_china_verdict v ON v.wayward_brand_id = b.wayward_brand_id
            WHERE r.reality = 'REAL' AND v.verdict = 'china' AND NOT r.ever_billed
            ORDER BY COALESCE(b.canonical_brand_id, b.wayward_brand_id),
                     (EXISTS (SELECT 1 FROM ps_brand_contacts c
                               WHERE c.wayward_brand_id = b.wayward_brand_id
                                 AND c.phone IS NOT NULL)) DESC,
                     (EXISTS (SELECT 1 FROM ps_brand_contacts c
                               WHERE c.wayward_brand_id = b.wayward_brand_id)) DESC,
                     b.wayward_brand_id
        )
        SELECT cp.brand_id AS wayward_brand_id, cp.brand_name, v.verdict, v.china_evidence,
               r.wayward_onboarded_them, r.on_a_frozen_list, r.on_eric_sheet,
               ct.name AS contact_name, ct.email AS contact_email,
               ct.phone AS contact_phone, ct.country AS contact_country, cp.signup_date
        FROM collapsed cp
        JOIN lens_ps_china_verdict  v ON v.wayward_brand_id = cp.wayward_brand_id
        JOIN lens_ps_brand_reality  r ON r.wayward_brand_id = cp.wayward_brand_id
        LEFT JOIN LATERAL (
            SELECT name, email, phone, country FROM ps_brand_contacts c
            WHERE c.wayward_brand_id = cp.wayward_brand_id
            ORDER BY (c.phone IS NOT NULL) DESC, (c.email IS NOT NULL) DESC LIMIT 1
        ) ct ON true
        """
    )
    op.execute(
        """
        CREATE VIEW lens_ps_china_check_queue AS
        SELECT v.wayward_brand_id, v.brand_name, v.probable_evidence, v.corroborates_not_china,
               v.not_china_evidence,
               (SELECT max(pc.partner_of_record) FROM ps_partner_credit pc
                 WHERE pc.wayward_brand_id = v.wayward_brand_id)            AS referred_by,
               (SELECT max(s.email) FROM ps_stripe_customers s
                 WHERE s.wayward_brand_id = v.wayward_brand_id)             AS email,
               (SELECT max(o.value) FROM ps_brand_observations o
                 WHERE o.wayward_brand_id = v.wayward_brand_id
                   AND o.field = 'website')                                 AS website,
               r.ever_billed, v.usage_collected
        FROM lens_ps_china_verdict v
        JOIN lens_ps_brand_reality r USING (wayward_brand_id)
        WHERE r.reality = 'REAL' AND v.verdict = 'probable'
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_china_check_queue IS "
        "'TIM''S QUEUE. Brands whose ONLY China evidence is a NAME (pinyin on a contact or a "
        "mailbox). A Chinese name is not a Chinese company. Nothing here is counted as Chinese and "
        "nothing here is discarded — it waits for a human. Empty today: the three referral brands "
        "(SZEE, Lille Home, Yoleo) were confirmed CHINESE by Tim''s cip_89 ruling.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_chase_list TO {r}")
        op.execute(f"GRANT SELECT ON lens_ps_china_check_queue TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_check_queue CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_chase_list CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict CASCADE")
    # back to cip_88: chinese_partner returns to the probable tier
    old_confirming = tuple(x for x in _CONFIRMING if x != "chinese_partner")
    old_probable = ("chinese_partner", *_PROBABLE)
    op.execute(_verdict_view(old_confirming, _LEGAL, old_probable))
    op.execute(
        """
        CREATE VIEW lens_ps_china_chase_list AS
        WITH collapsed AS (
            SELECT DISTINCT ON (COALESCE(b.canonical_brand_id, b.wayward_brand_id))
                COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS brand_id,
                b.wayward_brand_id, b.brand_name, b.signup_date
            FROM ps_brands b
            JOIN lens_ps_brand_reality r ON r.wayward_brand_id = b.wayward_brand_id
            JOIN lens_ps_china_verdict v ON v.wayward_brand_id = b.wayward_brand_id
            WHERE r.reality='REAL' AND v.verdict='china' AND NOT r.ever_billed
            ORDER BY COALESCE(b.canonical_brand_id, b.wayward_brand_id),
                     (EXISTS (SELECT 1 FROM ps_brand_contacts c
                               WHERE c.wayward_brand_id=b.wayward_brand_id AND c.phone IS NOT NULL)) DESC,
                     (EXISTS (SELECT 1 FROM ps_brand_contacts c
                               WHERE c.wayward_brand_id=b.wayward_brand_id)) DESC,
                     b.wayward_brand_id
        )
        SELECT cp.brand_id AS wayward_brand_id, cp.brand_name, v.verdict, v.china_evidence,
               r.wayward_onboarded_them, r.on_a_frozen_list, r.on_eric_sheet,
               ct.name AS contact_name, ct.email AS contact_email,
               ct.phone AS contact_phone, ct.country AS contact_country, cp.signup_date
        FROM collapsed cp
        JOIN lens_ps_china_verdict v ON v.wayward_brand_id = cp.wayward_brand_id
        JOIN lens_ps_brand_reality r ON r.wayward_brand_id = cp.wayward_brand_id
        LEFT JOIN LATERAL (
            SELECT name, email, phone, country FROM ps_brand_contacts c
            WHERE c.wayward_brand_id = cp.wayward_brand_id
            ORDER BY (c.phone IS NOT NULL) DESC, (c.email IS NOT NULL) DESC LIMIT 1
        ) ct ON true
        """
    )
    op.execute(
        """
        CREATE VIEW lens_ps_china_check_queue AS
        SELECT v.wayward_brand_id, v.brand_name, v.probable_evidence, v.corroborates_not_china,
               v.not_china_evidence,
               (SELECT max(pc.partner_of_record) FROM ps_partner_credit pc
                 WHERE pc.wayward_brand_id = v.wayward_brand_id) AS referred_by,
               (SELECT max(s.email) FROM ps_stripe_customers s
                 WHERE s.wayward_brand_id = v.wayward_brand_id) AS email,
               (SELECT max(o.value) FROM ps_brand_observations o
                 WHERE o.wayward_brand_id = v.wayward_brand_id AND o.field='website') AS website,
               r.ever_billed, v.usage_collected
        FROM lens_ps_china_verdict v
        JOIN lens_ps_brand_reality r USING (wayward_brand_id)
        WHERE r.reality='REAL' AND v.verdict='probable'
        """
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_verdict TO {r}")
        op.execute(f"GRANT SELECT ON lens_ps_china_chase_list TO {r}")
        op.execute(f"GRANT SELECT ON lens_ps_china_check_queue TO {r}")
