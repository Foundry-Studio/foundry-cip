# foundry: kind=migration domain=client-intelligence-platform
"""cip_80: nationality is not a property of revenue. Stop hiding brands that never billed.

TIM, 2026-07-14: "we need to fix the issue where the money lack is hiding brands, cause those
will be turned in to GOLD crm material to go chase and activate and get working! So they are
chinese, even without any money."

THE BUG
-------
lens_ps_china_verdict ended with `WHERE m.wayward_brand_id IS NOT NULL` — an inner filter against
ps_monthly_earnings. So the view could only see brands that had ALREADY BILLED:

    brands in ps_brands (the master) ......... 5,352
    brands the verdict view could see ........ 1,942
    BRANDS IT COULD NOT SEE .................. 3,410

And of those 3,410 invisible brands:

    710    ALREADY had China evidence in ps_nationality_signals — proven Chinese, undisplayable
     73    are on the FROZEN EXCLUSION LIST
  2,537    had never been assessed at all

A brand's nationality has nothing to do with whether it has paid us yet. Coupling them meant the
answer to "is this brand Chinese?" silently depended on "did this brand generate revenue?" — so
the moment we asked "who is Chinese?", every dormant Chinese brand answered "no". That is exactly
backwards: a confirmed-Chinese brand with NO revenue is not a dead row, it is the chase list.

The money columns stay (LEFT JOINed, NULL when there is no revenue) because they rank the chase.
They no longer decide who exists. `ever_billed` is added so the CRM list is one predicate away.

THE SIGNAL VOCABULARY
---------------------
The CHECK constraint on `signal` was a closed set of eight. Five new DEFINITIVE indicators came
out of the 2026-07-14 scan and had nowhere to live:

    phone_+86               a +86 number is a mainland-China line
    shared_owner_mailbox    same mailbox as a confirmed-Chinese brand = same owner, same portfolio
                            (zhou_yintong@163.com alone runs 18 of them)
    cn_mobile_handle        an 11-digit Chinese mobile (1[3-9]xxxxxxxxx) used as the email handle
    qq_handle               'qq' literally prefixing the mailbox handle
    cn_company_name_pinyin  e.g. DongGuanShiHengHengYuMaoYiYouXianGongSi

The constraint refusing them is the schema working. It is extended here rather than bypassed.

Revision ID: cip_80_china_scope_signals
Revises: cip_79_honest_partner_perf
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_80_china_scope_signals"
down_revision: str | Sequence[str] | None = "cip_79_honest_partner_perf"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_OLD_SIGNALS = (
    "on_exclusion_list", "wayward_country_cn", "cjk_in_name", "chinese_email_domain",
    "chinese_partner", "eric_sheet", "manual_review", "wayward_country_other",
)
_NEW_SIGNALS = (
    "phone_+86", "shared_owner_mailbox", "cn_mobile_handle", "qq_handle", "cn_company_name_pinyin",
)


def _signal_check(values: tuple[str, ...]) -> str:
    inner = ", ".join(f"'{v}'" for v in values)
    return f"CHECK (signal = ANY (ARRAY[{inner}]::text[]))"


def upgrade() -> None:
    # ── admit the five new definitive indicators ────────────────────────────
    op.execute("ALTER TABLE ps_nationality_signals DROP CONSTRAINT ps_nationality_signals_signal_check")
    op.execute(
        "ALTER TABLE ps_nationality_signals ADD CONSTRAINT ps_nationality_signals_signal_check "
        + _signal_check(_OLD_SIGNALS + _NEW_SIGNALS)
    )

    # ── the verdict, decoupled from revenue ────────────────────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict CASCADE")
    op.execute(
        """
        CREATE VIEW lens_ps_china_verdict AS
        WITH agg AS (
            SELECT
                wayward_brand_id,
                bool_or(signal = 'manual_review' AND points_to = 'china')     AS manual_china,
                bool_or(signal = 'manual_review' AND points_to = 'not_china') AS manual_not_china,
                count(*) FILTER (WHERE points_to = 'china')                   AS china_signals,
                count(*) FILTER (WHERE points_to = 'not_china')               AS not_china_signals,
                max(CASE strength
                        WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5
                        WHEN 'strong'       THEN 4 WHEN 'moderate'  THEN 3
                        WHEN 'weak'         THEN 2 ELSE 1 END)
                    FILTER (WHERE points_to = 'china')                        AS best_china_rank,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to = 'china')
                                                                              AS china_evidence,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to = 'not_china')
                                                                              AS not_china_evidence,
                max(evidence)    FILTER (WHERE signal = 'manual_review')      AS manual_rationale,
                max(asserted_by) FILTER (WHERE signal = 'manual_review')      AS manual_by
            FROM ps_nationality_signals
            GROUP BY wayward_brand_id
        ),
        money AS (
            -- LEFT JOINed below. Ranks the chase; does NOT decide who exists.
            SELECT wayward_brand_id,
                   sum(usage_collected)                                  AS collected,
                   sum(ps_gross_owed)                                    AS gross_if_claimable,
                   sum(ps_gross_owed)    FILTER (WHERE is_claimable)     AS ps_owed,
                   sum(ps_actually_paid) FILTER (WHERE is_claimable)     AS ps_paid
            FROM ps_monthly_earnings
            GROUP BY wayward_brand_id
        )
        SELECT
            b.wayward_brand_id,
            b.brand_name,
            b.signup_date,
            CASE
                WHEN a.manual_not_china                    THEN 'not_china'
                WHEN a.manual_china                        THEN 'china'
                WHEN COALESCE(a.china_signals, 0)     > 0  THEN 'china'
                WHEN COALESCE(a.not_china_signals, 0) > 0  THEN 'not_china'
                ELSE 'unknown'
            END                                                          AS verdict,
            CASE
                WHEN a.manual_not_china OR a.manual_china THEN 'manual'
                ELSE CASE a.best_china_rank
                        WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed'
                        WHEN 4 THEN 'strong'       WHEN 3 THEN 'moderate'
                        WHEN 2 THEN 'weak'         ELSE NULL END
            END                                                          AS verdict_strength,
            a.china_evidence,
            a.not_china_evidence,
            a.manual_rationale,
            a.manual_by,
            COALESCE(a.china_signals, 0) > 0
                AND COALESCE(a.not_china_signals, 0) > 0                 AS has_conflict,
            COALESCE(st.is_excluded, false)                              AS is_excluded,
            st.buckets                                                   AS excluded_buckets,
            -- *** the CRM axis: Chinese and NOT yet billing = the chase list ***
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
        "'Nationality for EVERY brand in the master (5,352) — not just the ones that billed. "
        "*** This view used to end in `WHERE m.wayward_brand_id IS NOT NULL`, an inner filter on "
        "ps_monthly_earnings, so it could only see 1,942 brands and HID 3,410. *** 710 of the "
        "hidden ones already had China evidence sitting in ps_nationality_signals — proven "
        "Chinese, undisplayable — and 73 were on the frozen exclusion list. A brand''s nationality "
        "does not depend on whether it has paid us yet. Coupling them meant asking ''who is "
        "Chinese?'' silently returned ''only the ones with revenue''. "
        "A confirmed-Chinese brand with NO revenue is not a dead row — it is the CHASE LIST. "
        "Filter `verdict = ''china'' AND NOT ever_billed` to get it.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_china_verdict.ever_billed IS "
        "'False = never generated a cent. Combined with verdict=''china'', that is CRM GOLD: a "
        "Chinese brand Wayward onboarded and never activated. Revenue ranks the chase; it does "
        "not decide who is Chinese.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_verdict TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict CASCADE")
    op.execute(
        "DELETE FROM ps_nationality_signals WHERE signal = ANY (ARRAY["
        + ", ".join(f"'{v}'" for v in _NEW_SIGNALS)
        + "]::text[])"
    )
    op.execute("ALTER TABLE ps_nationality_signals DROP CONSTRAINT ps_nationality_signals_signal_check")
    op.execute(
        "ALTER TABLE ps_nationality_signals ADD CONSTRAINT ps_nationality_signals_signal_check "
        + _signal_check(_OLD_SIGNALS)
    )
    op.execute(
        """
        CREATE VIEW lens_ps_china_verdict AS
        WITH agg AS (
            SELECT wayward_brand_id,
                bool_or(signal = 'manual_review' AND points_to = 'china')     AS manual_china,
                bool_or(signal = 'manual_review' AND points_to = 'not_china') AS manual_not_china,
                count(*) FILTER (WHERE points_to = 'china')                   AS china_signals,
                count(*) FILTER (WHERE points_to = 'not_china')               AS not_china_signals,
                max(CASE strength
                        WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5
                        WHEN 'strong' THEN 4 WHEN 'moderate' THEN 3
                        WHEN 'weak' THEN 2 ELSE 1 END)
                    FILTER (WHERE points_to = 'china')                        AS best_china_rank,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to = 'china')     AS china_evidence,
                string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to = 'not_china') AS not_china_evidence,
                max(evidence)    FILTER (WHERE signal = 'manual_review')      AS manual_rationale,
                max(asserted_by) FILTER (WHERE signal = 'manual_review')      AS manual_by
            FROM ps_nationality_signals GROUP BY wayward_brand_id
        ),
        money AS (
            SELECT wayward_brand_id,
                   sum(usage_collected) AS collected,
                   sum(ps_gross_owed)   AS gross_if_claimable,
                   sum(ps_gross_owed)    FILTER (WHERE is_claimable) AS ps_owed,
                   sum(ps_actually_paid) FILTER (WHERE is_claimable) AS ps_paid
            FROM ps_monthly_earnings GROUP BY wayward_brand_id
        )
        SELECT b.wayward_brand_id, b.brand_name, b.signup_date,
            CASE WHEN a.manual_not_china THEN 'not_china'
                 WHEN a.manual_china THEN 'china'
                 WHEN COALESCE(a.china_signals, 0) > 0 THEN 'china'
                 WHEN COALESCE(a.not_china_signals, 0) > 0 THEN 'not_china'
                 ELSE 'unknown' END AS verdict,
            CASE WHEN a.manual_not_china OR a.manual_china THEN 'manual'
                 ELSE CASE a.best_china_rank
                        WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed'
                        WHEN 4 THEN 'strong' WHEN 3 THEN 'moderate'
                        WHEN 2 THEN 'weak' ELSE NULL END END AS verdict_strength,
            a.china_evidence, a.not_china_evidence, a.manual_rationale, a.manual_by,
            COALESCE(a.china_signals, 0) > 0 AND COALESCE(a.not_china_signals, 0) > 0 AS has_conflict,
            st.is_excluded, st.buckets AS excluded_buckets,
            round(m.collected, 2) AS usage_collected,
            round(COALESCE(m.ps_owed, 0), 2) AS ps_owed_claimable,
            round(COALESCE(m.ps_paid, 0), 2) AS ps_paid,
            round(COALESCE(m.ps_owed, 0) - COALESCE(m.ps_paid, 0), 2) AS shortfall,
            round(m.gross_if_claimable, 2) AS hypothetical_if_all_claimable
        FROM ps_brands b
        JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN agg a ON a.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id
        WHERE m.wayward_brand_id IS NOT NULL
        """
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_verdict TO {r}")
