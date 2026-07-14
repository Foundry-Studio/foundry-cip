# foundry: kind=migration domain=client-intelligence-platform
"""cip_92 (W5): 5,352 rows are 4,500 companies. Every headline has been counting rows.

`ps_brands` holds 852 ALIAS rows — a company with several Stripe customer records gets several rows,
and `canonical_brand_id` records which is the head. It is populated. Exactly ONE view consumed it,
and that view is PARKED. So every live lens counted a split company twice.

    ps_brands rows ...... 5,352
    REAL COMPANIES ...... 4,500
    alias rows .......... 852

Measured on the China book, REAL brands only:

    verdict     ROWS (what we quote)   COMPANIES (the truth)
    china             1,623                  1,591        <- overstated by 32
    unknown             942                    932
    not_china            39                     39

THE ROLL-UP RULE, AND WHY THE OBVIOUS ONE IS WRONG
---------------------------------------------------
The tempting design is to take the row verdicts and pick a winner by precedence — china beats
not_china beats unknown. **That would OVERRULE A HUMAN.** If Tim pins not_china on one row of a
company and a machine signal says china on its sibling, precedence hands it to the machine. It has
not happened yet (verified: 0 human-vs-machine conflicts across the 29 companies whose rows
currently disagree — they are all `china + unknown`, i.e. one row holds the evidence and its sibling
does not). But "it has not happened yet" is how every bug in this dataset began.

So the company verdict is NOT a vote over row verdicts. It is the SAME CONSTITUTION, applied once to
the UNION of all the company's signals:

    a named human's not_china  ->  not_china     (wins from ANY row, always)
    a named human's china      ->  china
    any confirming indicator   ->  china
    a legal record             ->  not_china
    a name only                ->  probable
    nothing                    ->  unknown

Evidence unions naturally, and the human tier survives the roll-up. That is the whole point of it.

WHAT THIS MIGRATION DOES *NOT* DO
----------------------------------
It does not retire the 116 `manual_review` alias-propagation rows, which PARKING.md had pencilled in
for this wave. **35 alias rows carry MONEY**, and `ps_monthly_earnings.is_chinese` keys on the ROW.
Retiring those propagation rows would flip real money rows from china to unknown, and their
`is_chinese` from true to NULL. The propagation rows are ugly, but they are load-bearing until the
SPINE keys on the company — which is a far bigger change than this wave. Re-parked, with the reason.

It also does not touch a single money lens. Money is frozen.

Revision ID: cip_92_company_truth
Revises: cip_91_calendar_months
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_92_company_truth"
down_revision: str | Sequence[str] | None = "cip_91_calendar_months"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_CONFIRMING = (
    "on_exclusion_list", "eric_sheet", "wayward_country_cn", "chinese_email_domain",
    "cjk_in_name", "phone_+86", "qq_handle", "cn_mobile_handle", "cn_company_name_pinyin",
    "shared_owner_mailbox", "amazon_seller_entity", "uspto_trademark_owner",
    "tim_batch_approval", "chinese_partner",
)
_LEGAL = ("amazon_seller_entity", "uspto_trademark_owner")
_PROBABLE = ("pinyin_name_in_email", "pinyin_contact_name")


def _arr(xs: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{x}'" for x in xs) + ")"


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_companies CASCADE")
    op.execute(
        f"""
        CREATE VIEW lens_ps_china_companies AS
        WITH member AS (
            -- one row per ps_brands row, tagged with the company it belongs to.
            -- Verified before building this: 0 orphan pointers, 0 two-hop chains, 0 self-refs.
            -- So a single COALESCE is a correct head — no recursion needed.
            SELECT b.wayward_brand_id,
                   COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS company_id,
                   b.brand_name,
                   (b.canonical_brand_id IS NOT NULL
                      AND b.canonical_brand_id <> b.wayward_brand_id) AS is_alias_row
            FROM ps_brands b
        ),
        sig AS (
            -- *** THE UNION OF ALL THE COMPANY'S SIGNALS. *** Not a vote over row verdicts —
            -- that would let a machine outrank a human. See the docstring.
            SELECT m.company_id,
                bool_or(s.signal = 'manual_review' AND s.points_to = 'not_china')   AS human_not_china,
                bool_or(s.signal = 'manual_review' AND s.points_to = 'china')       AS human_china,
                count(*) FILTER (WHERE s.points_to = 'china'
                                   AND s.signal IN {_arr(_CONFIRMING)})             AS confirming,
                count(*) FILTER (WHERE s.points_to = 'not_china'
                                   AND s.signal IN {_arr(_LEGAL)})                  AS legal_not_china,
                count(*) FILTER (WHERE s.points_to = 'china'
                                   AND s.signal IN {_arr(_PROBABLE)})               AS probable_tier,
                count(*) FILTER (WHERE s.signal = 'wayward_country_other')          AS wayward_says_us,
                max(CASE s.strength
                        WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5
                        WHEN 'strong'       THEN 4 WHEN 'moderate'  THEN 3
                        WHEN 'weak'         THEN 2 ELSE 1 END)
                    FILTER (WHERE s.points_to = 'china'
                              AND s.signal IN {_arr(_CONFIRMING)})                  AS best_china_rank,
                string_agg(DISTINCT s.signal, ', ') FILTER (WHERE s.points_to = 'china')
                                                                                    AS china_evidence,
                string_agg(DISTINCT s.signal, ', ') FILTER (WHERE s.points_to = 'not_china')
                                                                                    AS not_china_evidence,
                max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review')        AS decided_by
            FROM member m
            LEFT JOIN ps_nationality_signals s ON s.wayward_brand_id = m.wayward_brand_id
            GROUP BY m.company_id
        ),
        shape AS (
            SELECT m.company_id,
                   count(*)                                             AS sibling_rows,
                   -- the company's NAME: prefer the head row's, else any non-alias, else any.
                   min(m.brand_name) FILTER (WHERE NOT m.is_alias_row)  AS head_name,
                   min(m.brand_name)                                    AS any_name,
                   -- a company is REAL if ANY of its rows is real. Money or onboarding on one
                   -- row makes the whole company a client.
                   bool_or(r.reality = 'REAL')                          AS is_real,
                   bool_or(r.reality = 'JUNK')                          AS any_row_junk,
                   bool_or(r.ever_billed)                               AS ever_billed,
                   bool_or(r.wayward_onboarded_them)                    AS onboarded,
                   bool_or(r.on_a_frozen_list)                          AS on_a_frozen_list,
                   bool_or(r.on_eric_sheet)                             AS on_eric_sheet
            FROM member m
            JOIN lens_ps_brand_reality r ON r.wayward_brand_id = m.wayward_brand_id
            GROUP BY m.company_id
        ),
        money AS (
            -- Stripe lines are attributed to exactly ONE brand row (verified: 75,658 lines,
            -- 75,658 distinct ids, 0 lines on two brands). Revenue is already disjoint across
            -- siblings, so summing them is arithmetically correct — it does not double-count.
            -- CLAIM math is deliberately absent: money is frozen. This ranks the chase, nothing more.
            SELECT m.company_id, round(sum(e.usage_collected), 2) AS usage_collected
            FROM member m
            JOIN ps_monthly_earnings e ON e.wayward_brand_id = m.wayward_brand_id
            GROUP BY m.company_id
        )
        SELECT
            sh.company_id,
            COALESCE(sh.head_name, sh.any_name)                          AS company_name,
            CASE
                WHEN sg.human_not_china                   THEN 'not_china'
                WHEN sg.human_china                       THEN 'china'
                WHEN COALESCE(sg.confirming, 0)      > 0  THEN 'china'
                WHEN COALESCE(sg.legal_not_china, 0) > 0  THEN 'not_china'
                WHEN COALESCE(sg.probable_tier, 0)   > 0  THEN 'probable'
                ELSE 'unknown'
            END                                                          AS verdict,
            CASE
                WHEN sg.human_not_china OR sg.human_china  THEN 'human'
                WHEN COALESCE(sg.confirming, 0) > 0 THEN
                    CASE sg.best_china_rank
                        WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed'
                        WHEN 4 THEN 'strong'       ELSE 'confirmed' END
                WHEN COALESCE(sg.legal_not_china, 0) > 0   THEN 'legal_record'
                WHEN COALESCE(sg.probable_tier, 0)   > 0   THEN 'needs_a_human'
                ELSE NULL
            END                                                          AS verdict_strength,
            sg.china_evidence,
            sg.not_china_evidence,
            (COALESCE(sg.wayward_says_us, 0) > 0)                        AS corroborates_not_china,
            sg.decided_by,
            sh.sibling_rows,
            (sh.sibling_rows > 1)                                        AS is_split_identity,
            CASE WHEN sh.is_real THEN 'REAL'
                 WHEN sh.any_row_junk THEN 'JUNK'
                 ELSE 'GHOST' END                                        AS reality,
            sh.ever_billed,
            sh.onboarded,
            sh.on_a_frozen_list,
            sh.on_eric_sheet,
            mo.usage_collected
        FROM shape sh
        JOIN sig   sg ON sg.company_id = sh.company_id
        LEFT JOIN money mo ON mo.company_id = sh.company_id
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_china_companies IS "
        "'*** ONE ROW PER REAL COMPANY. QUOTE YOUR HEADLINE NUMBERS FROM HERE, NOT FROM "
        "lens_ps_china_verdict. *** ps_brands holds 5,352 ROWS but only 4,500 COMPANIES — 852 are "
        "ALIAS rows, because a company with several Stripe customer records gets several rows. "
        "canonical_brand_id has always recorded which row is the head, and exactly ONE view "
        "consumed it — a view that is PARKED. So every live lens counted split companies twice: "
        "the China book reads 1,623 at row level and 1,591 at company level, overstated by 32. "
        "*** THE VERDICT IS NOT A VOTE OVER ROW VERDICTS. *** It is the SAME CONSTITUTION applied "
        "to the UNION of all the company''s signals. A vote by precedence (china beats not_china) "
        "would OVERRULE A HUMAN the day Tim pins not_china on one row while a machine signal sits "
        "on its sibling. Unioning the signals means a human''s ruling wins from ANY row, by "
        "construction. "
        "A company is REAL if ANY of its rows is real — money or onboarding on one row makes the "
        "whole company a client. usage_collected is summed across siblings, which is correct: "
        "Stripe lines are attributed to exactly one row each, so revenue is already disjoint. "
        "No claim math here — money is frozen. This ranks the chase, nothing more.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_companies TO {r}")

    op.execute(
        "COMMENT ON VIEW lens_ps_china_verdict IS "
        "'*** THIS IS ROW-LEVEL, AND 852 OF THOSE ROWS ARE ALIASES OF ANOTHER ROW. *** For any "
        "count you intend to say out loud, use lens_ps_china_companies — this view reads 1,623 "
        "china where the truth is 1,591 companies. This one stays row-level on purpose: the money "
        "spine (ps_monthly_earnings) keys on wayward_brand_id, so is_chinese must be resolvable "
        "per row. "
        "THE CONSTITUTION: *** china *** = ANY approved confirming indicator, or a named human. "
        "*** probable *** = a NAME only (pinyin) — Tim''s check queue. *** not_china *** = a named "
        "HUMAN or a LEGAL RECORD (amazon_seller_entity / uspto_trademark_owner). NOTHING ELSE. "
        "*** unknown *** = nothing. "
        "A CHINESE PARTNER''S REFERRAL CONFIRMS CHINA (cip_89) — our China partners source Chinese "
        "brands, that is the job. BruMate is the exception that proves the rule and she is "
        "protected structurally: a human''s not_china is read FIRST and no rule change can overturn "
        "it. "
        "wayward_country_other DECIDES NOTHING — 104 confirmed-Chinese brands carry it. It "
        "corroborates; it never clears. Tim: ''DONT ASSUME THAT WAYAWARD DATA IS CORRECT.'''"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_companies CASCADE")
