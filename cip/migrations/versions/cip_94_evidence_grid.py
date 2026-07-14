# foundry: kind=migration domain=client-intelligence-platform
"""cip_94 (W8): the evidence grid, and a next-step for every unknown. The wave that shrinks the pile.

Phase 1 ends when every REAL company is one of: china, not_china, probable-with-owner, or
unknown-WITH-A-NEXT-STEP. The first three are done. This wave gives the 932 unknowns their next
step, and gives Tim a surface he can read without writing SQL.

ONE new lens, `lens_ps_china_evidence_grid`: one row per REAL company, a boolean per indicator, the
corroboration columns, the context we hold (website / own-domain email / contact / billing), and —
for unknowns — a `next_step`.

WHAT THE PRE-CHECK FOUND (the 932 unknown REAL companies)
---------------------------------------------------------
    801  are billing (this is not a pile of dead rows)
    385  carry Wayward-says-US — the flip-to-USA candidates
    387  have a website we could fetch
    749  have an own-domain email (a website by another name)
    297  have a CRM contact
    547  have NO signal of any kind — the hard tail

And the top Wayward-says-US unknowns are exactly who Tim said he would flip: Sports Research, First
Aid Beauty, Sun Bum, VERSED, Petiq, California Design Den. Recognisable American companies.

THE ONE RULE THIS LENS MUST NOT BREAK
-------------------------------------
It carries NO nationality opinion of its own. It does not guess "looks Western" from a name — a
name is not a nationality (Bob and Brad is Chinese; Lifepro is Los Angeles). It reports the FACTS
we hold and routes the company to a human or to research. `next_step` is a queue label, never a
verdict. NOTHING here flips anything: Tim rules, and only Tim can move a brand to not_china (that,
or a legal record).

    next_step for an unknown:
      REVIEW_USA          Wayward says US AND it has its own website -> Tim eyeballs it first
      RESEARCH_SELLER     has a website or own-domain email -> Amazon seller-of-record lookup
      RESEARCH_OR_ASK     has a contact but no web presence -> seller lookup, or ask the contact
      ENRICH_OR_JAKE      no signal, no website, no contact -> external enrichment or ask Wayward

Revision ID: cip_94_evidence_grid
Revises: cip_93_schema_honesty
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_94_evidence_grid"
down_revision: str | Sequence[str] | None = "cip_93_schema_honesty"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_FREE_MAIL = "gmail|outlook|hotmail|yahoo|icloud|aol|qq|163|126|foxmail|sina|aliyun|yandex|protonmail"


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_evidence_grid CASCADE")
    op.execute(
        f"""
        CREATE VIEW lens_ps_china_evidence_grid AS
        WITH member AS (
            SELECT b.wayward_brand_id,
                   COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS company_id
            FROM ps_brands b
        ),
        ind AS (
            -- one boolean per indicator, unioned across the company's rows
            SELECT m.company_id,
                bool_or(s.signal='on_exclusion_list')       AS on_exclusion_list,
                bool_or(s.signal='eric_sheet')              AS eric_sheet,
                bool_or(s.signal='wayward_country_cn')      AS wayward_country_cn,
                bool_or(s.signal='chinese_email_domain')    AS chinese_email_domain,
                bool_or(s.signal='cjk_in_name')             AS cjk_in_name,
                bool_or(s.signal='phone_+86')               AS phone_86,
                bool_or(s.signal='qq_handle')               AS qq_handle,
                bool_or(s.signal='cn_mobile_handle')        AS cn_mobile_handle,
                bool_or(s.signal='cn_company_name_pinyin')  AS cn_company_name_pinyin,
                bool_or(s.signal='shared_owner_mailbox')    AS shared_owner_mailbox,
                bool_or(s.signal='chinese_partner')         AS chinese_partner,
                bool_or(s.signal='tim_batch_approval')      AS tim_batch_approval,
                bool_or(s.signal IN ('pinyin_name_in_email','pinyin_contact_name'))  AS pinyin_name,
                bool_or(s.signal='amazon_seller_entity')    AS amazon_seller_entity,
                bool_or(s.signal='uspto_trademark_owner')   AS uspto_trademark_owner,
                bool_or(s.signal='manual_review' AND s.points_to='china')     AS human_china,
                bool_or(s.signal='manual_review' AND s.points_to='not_china') AS human_not_china
            FROM member m
            LEFT JOIN ps_nationality_signals s ON s.wayward_brand_id = m.wayward_brand_id
            GROUP BY m.company_id
        ),
        ctx AS (
            SELECT m.company_id,
                max(o.value) FILTER (WHERE o.field='website' AND o.value <> '')   AS website,
                bool_or(o.field='website' AND o.value <> '')                       AS has_website,
                bool_or(sc.email IS NOT NULL
                        AND sc.email !~* '@({_FREE_MAIL})\\.')                      AS has_own_domain_email,
                bool_or(ct.wayward_brand_id IS NOT NULL)                           AS has_contact
            FROM member m
            LEFT JOIN ps_brand_observations o  ON o.wayward_brand_id = m.wayward_brand_id
            LEFT JOIN ps_stripe_customers   sc ON sc.wayward_brand_id = m.wayward_brand_id
            LEFT JOIN ps_brand_contacts     ct ON ct.wayward_brand_id = m.wayward_brand_id
            GROUP BY m.company_id
        )
        SELECT
            co.company_id,
            co.company_name,
            co.verdict,
            co.verdict_strength,
            co.reality,
            co.ever_billed,
            co.usage_collected,
            co.sibling_rows,
            -- the indicators
            i.on_exclusion_list, i.eric_sheet, i.wayward_country_cn, i.chinese_email_domain,
            i.cjk_in_name, i.phone_86, i.qq_handle, i.cn_mobile_handle, i.cn_company_name_pinyin,
            i.shared_owner_mailbox, i.chinese_partner, i.tim_batch_approval, i.pinyin_name,
            i.amazon_seller_entity, i.uspto_trademark_owner, i.human_china, i.human_not_china,
            -- corroboration: Wayward/HubSpot say US. DECIDES NOTHING.
            co.corroborates_not_china,
            -- context we hold
            x.has_website, x.website, x.has_own_domain_email, x.has_contact,
            -- the next step, for unknowns only. A QUEUE LABEL, never a verdict.
            CASE
                WHEN co.verdict <> 'unknown' THEN NULL
                WHEN co.corroborates_not_china AND x.has_website THEN 'REVIEW_USA'
                WHEN x.has_website OR x.has_own_domain_email      THEN 'RESEARCH_SELLER'
                WHEN x.has_contact                               THEN 'RESEARCH_OR_ASK'
                ELSE 'ENRICH_OR_JAKE'
            END AS next_step
        FROM lens_ps_china_companies co
        JOIN ind i ON i.company_id = co.company_id
        JOIN ctx x ON x.company_id = co.company_id
        WHERE co.reality = 'REAL'
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_china_evidence_grid IS "
        "'ONE ROW PER REAL COMPANY, a boolean per indicator — the surface for eyeballing what we "
        "actually hold on a brand without writing SQL. It carries NO nationality opinion of its "
        "own: it does not guess ''looks Western'' from a name (a name is not a nationality — Bob and "
        "Brad is Chinese, Lifepro is Los Angeles). It reports FACTS and routes. "
        "*** corroborates_not_china DECIDES NOTHING *** — 104 confirmed-Chinese brands carry it. "
        "*** next_step is a QUEUE LABEL, never a verdict *** (only for verdict=''unknown''): "
        "REVIEW_USA = Wayward says US and it has its own website, Tim eyeballs first (Sports "
        "Research, First Aid Beauty, Sun Bum…); RESEARCH_SELLER = has a website/own-domain email -> "
        "Amazon seller-of-record lookup; RESEARCH_OR_ASK = a contact but no web presence; "
        "ENRICH_OR_JAKE = nothing internal, needs external enrichment. NOTHING here flips anything.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_evidence_grid TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_evidence_grid CASCADE")
