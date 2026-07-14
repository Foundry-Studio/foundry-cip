# foundry: kind=migration domain=client-intelligence-platform
"""cip_88 (W2): the constitution. Four states, and Wayward's flag stops deciding.

TIM, 2026-07-14 — this is the rule, verbatim:

    "If we Are SURE they are chinese based on the indicators, ANY OF THEM, they are confirmed.
     EVERYTHING else is unknown or probable. We will then do checks on all of those… KNOWN
     american and large brands, which we will flip to USA. or other countries, we flip to not
     china."

And, separately and emphatically:

    "DONT ASSUME THAT WAYAWARD DATA IS CORRECT."

THE FOUR STATES
---------------
    china      ANY approved confirming indicator, or a named human.
    probable   channel/name evidence ONLY -> TIM'S CHECK QUEUE. Never counted as Chinese.
    not_china  a named HUMAN, or a LEGAL RECORD. NOTHING ELSE.
    unknown    nothing.

WHAT WAS WRONG: `wayward_country_other` WAS DECIDING
----------------------------------------------------
The old view read: any china signal -> china; else any not_china signal -> not_china. And
`wayward_country_other` ("Wayward's feed says this brand is US") was a not_china signal. So
Wayward's own country field was CLEARING BRANDS.

That field is the least reliable thing in the dataset, and this whole audit exists because of it:
a Chinese seller behind a US-registered shell reports as US. It is not evidence of American
ownership. It is what the shell looks like.

MEASURED, on live data, right now: **104 brands are CONFIRMED CHINESE while Wayward's flag says
US.** Roborock. Honeywell (a Guangdong licensee). The exclusion-list brands. Had that flag been
allowed to decide on its own, it would have cleared all 104.

So it is DEMOTED, not deleted. It remains fully visible in `not_china_evidence` and in the new
`corroborates_not_china` column. It can support a verdict. It can no longer make one.

THE ONLY MACHINE EVIDENCE ALLOWED TO SAY "NOT CHINA"
----------------------------------------------------
    amazon_seller_entity    Amazon is COMPELLED by the INFORM Consumers Act to verify and publish
                            a high-volume seller's business name and registered address.
    uspto_trademark_owner   Brand Registry requires a trademark, and a Chinese company must file a
                            US trademark under its real legal entity.

These name the ENTITY, under legal compulsion, in public. Everything else in the table is a proxy.
A US LLC in a footer is not a clearance — Chinese sellers register Delaware and Wyoming shells by
the thousand, and we have the mail-drop addresses to prove it.

PREDICTED MOVEMENT (measured before applying, and re-measured after W1):

    china     -> china        1,620   (104 of them while Wayward says US)
    unknown   -> unknown        550
    not_china -> UNKNOWN        392   <- Wayward's flag stops deciding
    not_china -> not_china       39   (a human, or a legal record)
    china     -> PROBABLE          3   <- SZEE, Lille Home, Yoleo

THE UNKNOWN PILE GROWS BEFORE THE CHECKS SHRINK IT. That is the honest cost of the rule, and Tim
was shown the number before this ran.

THE THREE
---------
SZEE, Lille Home and Yoleo are china TODAY on `chinese_partner` alone — "one of our China partners
referred them". Tim already ruled that structure is NOT nationality (BrüMate: American, referred by
a Chinese partner). But he also ruled the opposite of a write-off:

    "if its chinese refered those other brands, they are LIKELY chinese, and I Will manually
     check each."

`probable` is exactly that: they stay in the book, at the top of his queue, decided by nobody but
him. Not confirmed. Not discarded.

Revision ID: cip_88_four_state_verdict
Revises: cip_87_honest_labels
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_88_four_state_verdict"
down_revision: str | Sequence[str] | None = "cip_87_honest_labels"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# ANY ONE of these confirms china. Tim: "any of them, they are confirmed."
_CONFIRMING = (
    "on_exclusion_list", "eric_sheet", "wayward_country_cn", "chinese_email_domain",
    "cjk_in_name", "phone_+86", "qq_handle", "cn_mobile_handle", "cn_company_name_pinyin",
    "shared_owner_mailbox", "amazon_seller_entity", "uspto_trademark_owner",
    "tim_batch_approval",
)
# The ONLY machine evidence permitted to say NOT china.
_LEGAL = ("amazon_seller_entity", "uspto_trademark_owner")
# Channel / name. A research task, never a verdict.
_PROBABLE = ("chinese_partner", "pinyin_name_in_email", "pinyin_contact_name")


def _arr(xs: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{x}'" for x in xs) + ")"


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_chase_list CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict CASCADE")
    op.execute(
        f"""
        CREATE VIEW lens_ps_china_verdict AS
        WITH agg AS (
            SELECT
                wayward_brand_id,
                -- a NAMED HUMAN. Outranks everything, in both directions. (BruMate lives here.)
                bool_or(signal = 'manual_review' AND points_to = 'not_china')  AS human_not_china,
                bool_or(signal = 'manual_review' AND points_to = 'china')      AS human_china,
                -- ANY approved confirming indicator
                count(*) FILTER (WHERE points_to = 'china'
                                   AND signal IN {_arr(_CONFIRMING)})          AS confirming,
                -- a LEGAL RECORD, the only machine evidence allowed to clear a brand
                count(*) FILTER (WHERE points_to = 'not_china'
                                   AND signal IN {_arr(_LEGAL)})               AS legal_not_china,
                -- channel / name -> Tim's queue
                count(*) FILTER (WHERE points_to = 'china'
                                   AND signal IN {_arr(_PROBABLE)})            AS probable_tier,
                -- Wayward's country flag. VISIBLE, NEVER DECIDING.
                count(*) FILTER (WHERE signal = 'wayward_country_other')       AS wayward_says_us,
                max(CASE strength
                        WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5
                        WHEN 'strong'       THEN 4 WHEN 'moderate'  THEN 3
                        WHEN 'weak'         THEN 2 ELSE 1 END)
                    FILTER (WHERE points_to = 'china'
                              AND signal IN {_arr(_CONFIRMING)})               AS best_china_rank,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to = 'china')
                                                                               AS china_evidence,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to = 'not_china')
                                                                               AS not_china_evidence,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to = 'china'
                                                            AND signal IN {_arr(_PROBABLE)})
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
            b.wayward_brand_id,
            b.brand_name,
            b.signup_date,
            -- *** THE CONSTITUTION ***
            CASE
                WHEN a.human_not_china                       THEN 'not_china'
                WHEN a.human_china                           THEN 'china'
                WHEN COALESCE(a.confirming, 0)       > 0     THEN 'china'
                WHEN COALESCE(a.legal_not_china, 0)  > 0     THEN 'not_china'
                WHEN COALESCE(a.probable_tier, 0)    > 0     THEN 'probable'
                ELSE 'unknown'
            END                                                          AS verdict,
            CASE
                WHEN a.human_not_china OR a.human_china      THEN 'human'
                WHEN COALESCE(a.confirming, 0) > 0 THEN
                    CASE a.best_china_rank
                        WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed'
                        WHEN 4 THEN 'strong'       ELSE 'confirmed' END
                WHEN COALESCE(a.legal_not_china, 0) > 0     THEN 'legal_record'
                WHEN COALESCE(a.probable_tier, 0)   > 0     THEN 'needs_a_human'
                ELSE NULL
            END                                                          AS verdict_strength,
            a.china_evidence,
            a.not_china_evidence,
            a.probable_evidence,
            -- Wayward said US. It is on the record. It decides NOTHING.
            (COALESCE(a.wayward_says_us, 0) > 0)                         AS corroborates_not_china,
            a.manual_rationale,
            a.manual_by,
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
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_china_verdict IS "
        "'THE CONSTITUTION. Four states, and Wayward''s country flag no longer decides any of them. "
        "*** china *** = ANY approved confirming indicator, or a named human. Tim: ''If we Are SURE "
        "they are chinese based on the indicators, ANY OF THEM, they are confirmed.'' "
        "*** probable *** = channel/name evidence ONLY (chinese_partner, pinyin). TIM''S CHECK "
        "QUEUE. Never counted as Chinese, never discarded. ''they are LIKELY chinese, and I Will "
        "manually check each.'' "
        "*** not_china *** = a named HUMAN, or a LEGAL RECORD (amazon_seller_entity / "
        "uspto_trademark_owner). NOTHING ELSE. "
        "*** unknown *** = nothing. "
        "*** wayward_country_other IS DEMOTED, NOT DELETED. *** It used to CLEAR brands. It is the "
        "least reliable field we hold — a Chinese seller behind a US-registered shell reports as US, "
        "which is the entire pattern this audit exists to find. MEASURED: 104 brands are CONFIRMED "
        "CHINESE while that flag says US. It stays visible in not_china_evidence and in "
        "corroborates_not_china. It supports a verdict; it never makes one. "
        "Tim, 2026-07-14: ''DONT ASSUME THAT WAYAWARD DATA IS CORRECT.'''"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_china_verdict.corroborates_not_china IS "
        "'Wayward''s own feed or HubSpot records this brand as non-Chinese. This is CORROBORATION "
        "ONLY and it decides nothing — 104 confirmed-Chinese brands carry it. Never filter money or "
        "claims on this column.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_china_verdict.probable_evidence IS "
        "'Why this brand is PROBABLE rather than confirmed: a Chinese partner referred it, or a "
        "contact/mailbox carries a Chinese personal name. Neither is a nationality. A referral is "
        "BruMate''s exact structure (American, referred by a Chinese partner) and a name is not a "
        "company (Bob and Brad is Chinese; Lifepro is Los Angeles). These go to a human.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_verdict TO {r}")

    # ── the chase list: CONFIRMED china only. Probable is not chased; it is checked. ──
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
        "COMMENT ON VIEW lens_ps_china_chase_list IS "
        "'CONFIRMED CHINESE, REAL, AND HAS NEVER SOLD A THING — the CRM chase list. One row per "
        "company (collapsed on canonical_brand_id). *** verdict = ''china'' ONLY. *** A ''probable'' "
        "brand is not chased, it is CHECKED — see lens_ps_china_check_queue.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_chase_list TO {r}")

    # ── Tim's check queue: the probable pile, with everything he needs to rule ──
    op.execute("DROP VIEW IF EXISTS lens_ps_china_check_queue CASCADE")
    op.execute(
        """
        CREATE VIEW lens_ps_china_check_queue AS
        SELECT
            v.wayward_brand_id,
            v.brand_name,
            v.probable_evidence,
            v.corroborates_not_china,
            v.not_china_evidence,
            (SELECT max(pc.partner_of_record) FROM ps_partner_credit pc
              WHERE pc.wayward_brand_id = v.wayward_brand_id)              AS referred_by,
            (SELECT max(s.email) FROM ps_stripe_customers s
              WHERE s.wayward_brand_id = v.wayward_brand_id)               AS email,
            (SELECT max(o.value) FROM ps_brand_observations o
              WHERE o.wayward_brand_id = v.wayward_brand_id
                AND o.field = 'website')                                   AS website,
            r.ever_billed,
            v.usage_collected
        FROM lens_ps_china_verdict v
        JOIN lens_ps_brand_reality r USING (wayward_brand_id)
        WHERE r.reality = 'REAL' AND v.verdict = 'probable'
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_china_check_queue IS "
        "'TIM''S QUEUE. Brands whose ONLY China evidence is channel or name — a Chinese partner "
        "referred them, or a contact has a Chinese name. Neither is a nationality, and neither is a "
        "write-off. Tim: ''if its chinese refered those other brands, they are LIKELY chinese, and I "
        "Will manually check each.'' Nothing here is counted as Chinese and nothing here is "
        "discarded. It waits for a human.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_check_queue TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_check_queue CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_chase_list CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict CASCADE")
    op.execute(
        """
        CREATE VIEW lens_ps_china_verdict AS
        WITH agg AS (
            SELECT wayward_brand_id,
                bool_or(signal='manual_review' AND points_to='china')     AS manual_china,
                bool_or(signal='manual_review' AND points_to='not_china') AS manual_not_china,
                count(*) FILTER (WHERE points_to='china')                 AS china_signals,
                count(*) FILTER (WHERE points_to='not_china')             AS not_china_signals,
                max(CASE strength WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5
                                  WHEN 'strong' THEN 4 WHEN 'moderate' THEN 3
                                  WHEN 'weak' THEN 2 ELSE 1 END)
                    FILTER (WHERE points_to='china')                      AS best_china_rank,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to='china')     AS china_evidence,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to='not_china') AS not_china_evidence,
                max(evidence)    FILTER (WHERE signal='manual_review')    AS manual_rationale,
                max(asserted_by) FILTER (WHERE signal='manual_review')    AS manual_by
            FROM ps_nationality_signals GROUP BY wayward_brand_id
        ),
        money AS (
            SELECT wayward_brand_id, sum(usage_collected) AS collected,
                   sum(ps_gross_owed) AS gross_if_claimable,
                   sum(ps_gross_owed)    FILTER (WHERE is_claimable) AS ps_owed,
                   sum(ps_actually_paid) FILTER (WHERE is_claimable) AS ps_paid
            FROM ps_monthly_earnings GROUP BY wayward_brand_id
        )
        SELECT b.wayward_brand_id, b.brand_name, b.signup_date,
            CASE WHEN a.manual_not_china THEN 'not_china'
                 WHEN a.manual_china THEN 'china'
                 WHEN COALESCE(a.china_signals,0) > 0 THEN 'china'
                 WHEN COALESCE(a.not_china_signals,0) > 0 THEN 'not_china'
                 ELSE 'unknown' END AS verdict,
            CASE WHEN a.manual_not_china OR a.manual_china THEN 'manual'
                 ELSE CASE a.best_china_rank
                        WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed'
                        WHEN 4 THEN 'strong' WHEN 3 THEN 'moderate'
                        WHEN 2 THEN 'weak' ELSE NULL END END AS verdict_strength,
            a.china_evidence, a.not_china_evidence, a.manual_rationale, a.manual_by,
            COALESCE(a.china_signals,0) > 0 AND COALESCE(a.not_china_signals,0) > 0 AS has_conflict,
            COALESCE(st.is_excluded,false) AS is_excluded, st.buckets AS excluded_buckets,
            (m.wayward_brand_id IS NOT NULL) AS ever_billed,
            round(m.collected,2) AS usage_collected,
            round(COALESCE(m.ps_owed,0),2) AS ps_owed_claimable,
            round(COALESCE(m.ps_paid,0),2) AS ps_paid,
            round(COALESCE(m.ps_owed,0)-COALESCE(m.ps_paid,0),2) AS shortfall,
            round(m.gross_if_claimable,2) AS hypothetical_if_all_claimable
        FROM ps_brands b
        LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN agg a ON a.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id
        """
    )
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
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_verdict TO {r}")
        op.execute(f"GRANT SELECT ON lens_ps_china_chase_list TO {r}")
