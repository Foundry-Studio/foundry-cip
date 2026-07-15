# foundry: kind=migration domain=client-intelligence-platform
"""cip_95: retire the empty `probable` verdict — a clean 3-state audit (china / not_china / unknown).

WHY
---
The China audit verdict had four states: china, not_china, probable, unknown. `probable` was for a
brand whose ONLY china-pointing evidence is a pinyin PERSONAL name (`pinyin_name_in_email` /
`pinyin_contact_name`) — a "the name looks Chinese, a human should look" holding pen, deliberately
kept out of the china book (a Chinese NAME is not a Chinese COMPANY: Bob and Brad is Chinese;
Lifepro is Los Angeles).

It is EMPTY — 0 companies, 0 brand-rows — and it is now redundant. The evidence grid (cip_94) gives
every unknown a `next_step` AND a `pinyin_name` boolean, so a would-be `probable` is simply an
`unknown` that the grid already flags and routes. Tim asked to kill the state cleanly so no dead
verdict value, dead column, or dead view lingers ("no debt or anything not useful or clear").

WHAT
----
1. lens_ps_china_verdict  -> 3-state. Removes the `probable` verdict branch, the `needs_a_human`
   strength, the `probable_tier` aggregate, and the `probable_evidence` output column. A brand whose
   only hint was a pinyin personal name now reads `unknown` (its `pinyin_name` flag still shows in
   the evidence grid, so nothing is lost — it is surfaced there, not here).
2. lens_ps_china_companies -> same removal. Output columns are unchanged (it never exposed a
   probable_evidence column), so it goes through CREATE OR REPLACE and its dependents/grants ride
   along untouched.
3. lens_ps_china_check_queue -> DROPPED. It existed ONLY to list `verdict='probable'` and is now
   permanently empty. The evidence grid supersedes it as the review surface.
4. lens_ps_china_chase_list -> dropped and recreated VERBATIM. It joins the verdict view (so the
   verdict view cannot be replaced while it exists) but never referenced the probable column, so the
   same SQL is valid against the 3-state view.

ZERO VERDICT MOVEMENT. `probable` = 0 before this migration; no row changes bucket. is_chinese is
already NULL for anything not china/not_china, so the money spine does not move either. Money frozen.

NOT IN SCOPE — flagged separately for Tim: the OLDER `cip_clients.nationality_review_status` system
(95 rows still = 'probable', written by scripts/decide_nationality.py, which encodes the
"country decides nationality" logic the audit deliberately rejected). That is a different, pre-signal
subsystem with real data; decommissioning it is its own decision and is NOT touched here.

Revision ID: cip_95_retire_probable
Revises: cip_94_evidence_grid
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_95_retire_probable"
down_revision: str | Sequence[str] | None = "cip_94_evidence_grid"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# The 14 approved confirming indicators (ANY one -> china). Verbatim from cip_88/cip_89; inlined so
# this migration is self-contained and its SQL is byte-identical to what it replaces (minus probable).
_CONFIRMING = (
    "'on_exclusion_list','eric_sheet','wayward_country_cn','chinese_email_domain','cjk_in_name',"
    "'phone_+86','qq_handle','cn_mobile_handle','cn_company_name_pinyin','shared_owner_mailbox',"
    "'amazon_seller_entity','uspto_trademark_owner','tim_batch_approval','chinese_partner'"
)
_LEGAL_NOT_CHINA = "'amazon_seller_entity','uspto_trademark_owner'"
_PINYIN = "'pinyin_name_in_email','pinyin_contact_name'"

# chase_list depends on the verdict view but never used the probable column. Same SQL both ways.
_CHASE_LIST = """
CREATE VIEW lens_ps_china_chase_list AS
WITH collapsed AS (
    SELECT DISTINCT ON (COALESCE(b.canonical_brand_id, b.wayward_brand_id))
        COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS brand_id,
        b.wayward_brand_id, b.brand_name, b.signup_date
    FROM ps_brands b
    JOIN lens_ps_brand_reality r_1 ON r_1.wayward_brand_id = b.wayward_brand_id
    JOIN lens_ps_china_verdict v_1 ON v_1.wayward_brand_id = b.wayward_brand_id
    WHERE r_1.reality = 'REAL' AND v_1.verdict = 'china' AND NOT r_1.ever_billed
    ORDER BY COALESCE(b.canonical_brand_id, b.wayward_brand_id),
        (EXISTS (SELECT 1 FROM ps_brand_contacts c
                 WHERE c.wayward_brand_id = b.wayward_brand_id AND c.phone IS NOT NULL)) DESC,
        (EXISTS (SELECT 1 FROM ps_brand_contacts c
                 WHERE c.wayward_brand_id = b.wayward_brand_id)) DESC,
        b.wayward_brand_id
)
SELECT cp.brand_id AS wayward_brand_id, cp.brand_name, v.verdict, v.china_evidence,
    r.wayward_onboarded_them, r.on_a_frozen_list, r.on_eric_sheet,
    ct.name AS contact_name, ct.email AS contact_email, ct.phone AS contact_phone,
    ct.country AS contact_country, cp.signup_date
FROM collapsed cp
JOIN lens_ps_china_verdict v ON v.wayward_brand_id = cp.wayward_brand_id
JOIN lens_ps_brand_reality r ON r.wayward_brand_id = cp.wayward_brand_id
LEFT JOIN LATERAL (
    SELECT c.name, c.email, c.phone, c.country FROM ps_brand_contacts c
    WHERE c.wayward_brand_id = cp.wayward_brand_id
    ORDER BY (c.phone IS NOT NULL) DESC, (c.email IS NOT NULL) DESC LIMIT 1
) ct ON true
"""


def _verdict_view(*, probable: bool) -> str:
    """The verdict view. probable=False is the 3-state target; probable=True is the 4-state original
    (for downgrade). Only the pinyin-name holding-pen differs between them."""
    probable_tier_agg = (
        f"        count(*) FILTER (WHERE s.points_to='china' "
        f"AND s.signal = ANY(ARRAY[{_PINYIN}])) AS probable_tier,\n"
        if probable else ""
    )
    probable_evidence_agg = (
        "        string_agg(DISTINCT s.signal, ', ') FILTER (WHERE s.points_to='china' "
        f"AND s.signal = ANY(ARRAY[{_PINYIN}])) AS probable_evidence,\n"
        if probable else ""
    )
    verdict_probable_branch = (
        "            WHEN COALESCE(a.probable_tier,0) > 0 THEN 'probable'\n" if probable else ""
    )
    strength_probable_branch = (
        "            WHEN COALESCE(a.probable_tier,0) > 0 THEN 'needs_a_human'\n" if probable else ""
    )
    probable_evidence_col = "    a.probable_evidence,\n" if probable else ""
    return f"""
CREATE VIEW lens_ps_china_verdict AS
WITH agg AS (
    SELECT s.wayward_brand_id,
        bool_or(s.signal='manual_review' AND s.points_to='not_china') AS human_not_china,
        bool_or(s.signal='manual_review' AND s.points_to='china')     AS human_china,
        count(*) FILTER (WHERE s.points_to='china'
            AND s.signal = ANY(ARRAY[{_CONFIRMING}])) AS confirming,
        count(*) FILTER (WHERE s.points_to='not_china'
            AND s.signal = ANY(ARRAY[{_LEGAL_NOT_CHINA}])) AS legal_not_china,
{probable_tier_agg}        count(*) FILTER (WHERE s.signal='wayward_country_other') AS wayward_says_us,
        max(CASE s.strength WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5 WHEN 'strong' THEN 4
                            WHEN 'moderate' THEN 3 WHEN 'weak' THEN 2 ELSE 1 END)
            FILTER (WHERE s.points_to='china'
                AND s.signal = ANY(ARRAY[{_CONFIRMING}])) AS best_china_rank,
        string_agg(DISTINCT s.signal, ', ') FILTER (WHERE s.points_to='china') AS china_evidence,
        string_agg(DISTINCT s.signal, ', ') FILTER (WHERE s.points_to='not_china') AS not_china_evidence,
{probable_evidence_agg}        max(s.evidence)    FILTER (WHERE s.signal='manual_review') AS manual_rationale,
        max(s.asserted_by) FILTER (WHERE s.signal='manual_review') AS manual_by
    FROM ps_nationality_signals s
    GROUP BY s.wayward_brand_id
), money AS (
    SELECT e.wayward_brand_id,
        sum(e.usage_collected) AS collected,
        sum(e.ps_gross_owed) AS gross_if_claimable,
        sum(e.ps_gross_owed)     FILTER (WHERE e.is_claimable) AS ps_owed,
        sum(e.ps_actually_paid)  FILTER (WHERE e.is_claimable) AS ps_paid
    FROM ps_monthly_earnings e
    GROUP BY e.wayward_brand_id
)
SELECT b.wayward_brand_id, b.brand_name, b.signup_date,
    CASE
        WHEN a.human_not_china THEN 'not_china'
        WHEN a.human_china THEN 'china'
        WHEN COALESCE(a.confirming,0) > 0 THEN 'china'
        WHEN COALESCE(a.legal_not_china,0) > 0 THEN 'not_china'
{verdict_probable_branch}        ELSE 'unknown'
    END AS verdict,
    CASE
        WHEN a.human_not_china OR a.human_china THEN 'human'
        WHEN COALESCE(a.confirming,0) > 0 THEN
            CASE a.best_china_rank WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed'
                                   WHEN 4 THEN 'strong' ELSE 'confirmed' END
        WHEN COALESCE(a.legal_not_china,0) > 0 THEN 'legal_record'
{strength_probable_branch}        ELSE NULL
    END AS verdict_strength,
    a.china_evidence,
    a.not_china_evidence,
{probable_evidence_col}    COALESCE(a.wayward_says_us,0) > 0 AS corroborates_not_china,
    a.manual_rationale,
    a.manual_by,
    COALESCE(a.confirming,0) > 0 AND COALESCE(a.legal_not_china,0) > 0 AS has_conflict,
    COALESCE(st.is_excluded,false) AS is_excluded,
    st.buckets AS excluded_buckets,
    m.wayward_brand_id IS NOT NULL AS ever_billed,
    round(m.collected,2) AS usage_collected,
    round(COALESCE(m.ps_owed,0),2) AS ps_owed_claimable,
    round(COALESCE(m.ps_paid,0),2) AS ps_paid,
    round(COALESCE(m.ps_owed,0) - COALESCE(m.ps_paid,0),2) AS shortfall,
    round(m.gross_if_claimable,2) AS hypothetical_if_all_claimable
FROM ps_brands b
LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
LEFT JOIN agg a ON a.wayward_brand_id = b.wayward_brand_id
LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id
"""


def _companies_view(*, probable: bool) -> str:
    """The company roll-up (CREATE OR REPLACE — output columns identical both ways)."""
    probable_tier_agg = (
        f"        count(*) FILTER (WHERE s.points_to='china' "
        f"AND s.signal = ANY(ARRAY[{_PINYIN}])) AS probable_tier,\n"
        if probable else ""
    )
    verdict_probable_branch = (
        "            WHEN COALESCE(sg.probable_tier,0) > 0 THEN 'probable'\n" if probable else ""
    )
    strength_probable_branch = (
        "            WHEN COALESCE(sg.probable_tier,0) > 0 THEN 'needs_a_human'\n" if probable else ""
    )
    return f"""
CREATE OR REPLACE VIEW lens_ps_china_companies AS
WITH member AS (
    SELECT b.wayward_brand_id,
        COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS company_id,
        b.brand_name,
        b.canonical_brand_id IS NOT NULL AND b.canonical_brand_id <> b.wayward_brand_id AS is_alias_row
    FROM ps_brands b
), sig AS (
    SELECT m.company_id,
        bool_or(s.signal='manual_review' AND s.points_to='not_china') AS human_not_china,
        bool_or(s.signal='manual_review' AND s.points_to='china')     AS human_china,
        count(*) FILTER (WHERE s.points_to='china'
            AND s.signal = ANY(ARRAY[{_CONFIRMING}])) AS confirming,
        count(*) FILTER (WHERE s.points_to='not_china'
            AND s.signal = ANY(ARRAY[{_LEGAL_NOT_CHINA}])) AS legal_not_china,
{probable_tier_agg}        count(*) FILTER (WHERE s.signal='wayward_country_other') AS wayward_says_us,
        max(CASE s.strength WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5 WHEN 'strong' THEN 4
                            WHEN 'moderate' THEN 3 WHEN 'weak' THEN 2 ELSE 1 END)
            FILTER (WHERE s.points_to='china'
                AND s.signal = ANY(ARRAY[{_CONFIRMING}])) AS best_china_rank,
        string_agg(DISTINCT s.signal, ', ') FILTER (WHERE s.points_to='china') AS china_evidence,
        string_agg(DISTINCT s.signal, ', ') FILTER (WHERE s.points_to='not_china') AS not_china_evidence,
        max(s.asserted_by) FILTER (WHERE s.signal='manual_review') AS decided_by
    FROM member m
    LEFT JOIN ps_nationality_signals s ON s.wayward_brand_id = m.wayward_brand_id
    GROUP BY m.company_id
), shape AS (
    SELECT m.company_id,
        count(*) AS sibling_rows,
        min(m.brand_name) FILTER (WHERE NOT m.is_alias_row) AS head_name,
        min(m.brand_name) AS any_name,
        bool_or(r.reality='REAL') AS is_real,
        bool_or(r.reality='JUNK') AS any_row_junk,
        bool_or(r.ever_billed) AS ever_billed,
        bool_or(r.wayward_onboarded_them) AS onboarded,
        bool_or(r.on_a_frozen_list) AS on_a_frozen_list,
        bool_or(r.on_eric_sheet) AS on_eric_sheet
    FROM member m
    JOIN lens_ps_brand_reality r ON r.wayward_brand_id = m.wayward_brand_id
    GROUP BY m.company_id
), money AS (
    SELECT m.company_id, round(sum(e.usage_collected),2) AS usage_collected
    FROM member m
    JOIN ps_monthly_earnings e ON e.wayward_brand_id = m.wayward_brand_id
    GROUP BY m.company_id
)
SELECT sh.company_id,
    COALESCE(sh.head_name, sh.any_name) AS company_name,
    CASE
        WHEN sg.human_not_china THEN 'not_china'
        WHEN sg.human_china THEN 'china'
        WHEN COALESCE(sg.confirming,0) > 0 THEN 'china'
        WHEN COALESCE(sg.legal_not_china,0) > 0 THEN 'not_china'
{verdict_probable_branch}        ELSE 'unknown'
    END AS verdict,
    CASE
        WHEN sg.human_not_china OR sg.human_china THEN 'human'
        WHEN COALESCE(sg.confirming,0) > 0 THEN
            CASE sg.best_china_rank WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed'
                                    WHEN 4 THEN 'strong' ELSE 'confirmed' END
        WHEN COALESCE(sg.legal_not_china,0) > 0 THEN 'legal_record'
{strength_probable_branch}        ELSE NULL
    END AS verdict_strength,
    sg.china_evidence,
    sg.not_china_evidence,
    COALESCE(sg.wayward_says_us,0) > 0 AS corroborates_not_china,
    sg.decided_by,
    sh.sibling_rows,
    sh.sibling_rows > 1 AS is_split_identity,
    CASE WHEN sh.is_real THEN 'REAL' WHEN sh.any_row_junk THEN 'JUNK' ELSE 'GHOST' END AS reality,
    sh.ever_billed,
    sh.onboarded,
    sh.on_a_frozen_list,
    sh.on_eric_sheet,
    mo.usage_collected
FROM shape sh
JOIN sig sg ON sg.company_id = sh.company_id
LEFT JOIN money mo ON mo.company_id = sh.company_id
"""


_VERDICT_COMMENT_3STATE = (
    "Per-BRAND-ROW China verdict — THREE states: china / not_china / unknown (cip_95 retired the "
    "empty `probable` holding-pen). *** THIS IS ROW-LEVEL, and 852 of these rows are aliases of "
    "another row. *** For any count you say out loud, use lens_ps_china_companies (one row per "
    "company). china = ANY approved confirming indicator or a named human; not_china = a human or a "
    "legal record (amazon_seller_entity / uspto_trademark_owner) ONLY, never Wayward''s country flag; "
    "unknown = nothing decisive yet (a pinyin PERSONAL name is not a verdict — the evidence grid "
    "flags it as pinyin_name and routes it). corroborates_not_china DECIDES NOTHING."
)
_VERDICT_COMMENT_4STATE = (
    "Per-BRAND-ROW China verdict. *** THIS IS ROW-LEVEL, AND 852 OF THOSE ROWS ARE ALIASES OF "
    "ANOTHER ROW. *** For any count you intend to say out loud, use lens_ps_china_companies - this "
    "view repeats a company once per alias. Four states: china / not_china / probable / unknown."
)


def upgrade() -> None:
    # check_queue existed only to list verdict='probable' — now permanently empty. Retire it.
    op.execute("DROP VIEW IF EXISTS lens_ps_china_check_queue")
    # chase_list joins the verdict view, so it blocks replacing it. Drop, rebuild the verdict view
    # 3-state, then recreate chase_list verbatim against the new view.
    op.execute("DROP VIEW IF EXISTS lens_ps_china_chase_list")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict")
    op.execute(_verdict_view(probable=False))
    op.execute(_CHASE_LIST)
    op.execute(_companies_view(probable=False))  # CREATE OR REPLACE — dependents/grants ride along

    op.execute(f"COMMENT ON VIEW lens_ps_china_verdict IS '{_VERDICT_COMMENT_3STATE}'")
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_verdict TO {r}")
        op.execute(f"GRANT SELECT ON lens_ps_china_chase_list TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_chase_list")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict")
    op.execute(_verdict_view(probable=True))
    op.execute(_CHASE_LIST)
    op.execute(_companies_view(probable=True))
    op.execute(f"COMMENT ON VIEW lens_ps_china_verdict IS '{_VERDICT_COMMENT_4STATE}'")

    # restore the queue lens (lists verdict='probable' REAL brands)
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
        WHERE r.reality = 'REAL' AND v.verdict = 'probable'
        """
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_verdict TO {r}")
        op.execute(f"GRANT SELECT ON lens_ps_china_chase_list TO {r}")
        op.execute(f"GRANT SELECT ON lens_ps_china_check_queue TO {r}")
