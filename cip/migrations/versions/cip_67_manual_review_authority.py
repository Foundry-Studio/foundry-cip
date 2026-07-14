# foundry: kind=migration domain=client-intelligence-platform
"""cip_67: the exclusion list beats Wayward's country flag. A human beats both.

TIM'S RULING (2026-07-13)
-------------------------
  "If it's on the exclusion list, that is more powerful than the Wayward flagging, and we will
   ask them to flip that in their data."
  "BrüMate is an exception for sure — American, but referred by a Chinese partner."

That second sentence is the key that explains the first. The exclusion list is not really an
assertion about a brand's NATIONALITY — it is an assertion about its REFERRAL CHANNEL. §1.4
defines Excluded Brands as Chinese-based brands "referred to Company under existing referral
arrangements" with Eric/Lysoatur, OpenLight, Oceanwing, Jeremy Dai, Shallow Wan. Being on it means
a China partner brought the brand. That is overwhelmingly Chinese brands — and occasionally, as
with BrüMate, an American brand a Chinese partner happened to refer.

So the precedence is:

    manual_review          A named human (or reviewed LLM) looked at the actual operating company.
                           Outranks everything, in BOTH directions. This is the ONLY way BrüMate
                           gets corrected — and the only way it gets corrected TRACEABLY.
        v
    on_exclusion_list      DEFINITIONAL. Wayward and Project Silk jointly listed this brand as
                           coming through a China referral channel, in a signed instrument. It
                           BEATS Wayward's own country field, which is demonstrably unreliable —
                           31 of the 32 brands where the two disagree are US-registered SHELLS
                           sitting in Eric's book (BABONIR, MARYSUN, Chasesun, TORUTA, ATVIOO,
                           Frizzlife...), classic Chinese private-label names every one. We will
                           be asking Wayward to fix their data, not the other way round.
        v
    other china signals    CHINA WINS — one positive locks it.
        v
    not_china signals      Only ever decides a brand with no positive signal at all.
        v
    unknown

THE REPORTING BUG THIS ALSO FIXES
---------------------------------
Tim: "if they are on exclusion list, then why does PS get owed?"

He is right, and the previous view invited exactly that misreading. ps_gross_owed is a GENERATED
column — collected x rate — and it computes for EVERY row regardless of whether we may claim it.
On an excluded brand it is a HYPOTHETICAL ("what 10% of this would be"), not a debt. We are owed
nothing on an excluded brand's Connect revenue. We are owed only:

    - its BOOST usage fees        (Ruling 1 — Boost does not inherit exclusion), and
    - qualifying REACTIVATIONS    (Ruling 2 — flat-fee brands, revived after 2025-11-01).

The verdict view now reports CLAIMABLE money (is_claimable) separately from the hypothetical, so a
reader can never mistake one for the other.

Revision ID: cip_67_manual_review_authority
Revises: cip_66_nationality_signals
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_67_manual_review_authority"
down_revision: str | Sequence[str] | None = "cip_66_nationality_signals"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    op.execute(
        "COMMENT ON COLUMN ps_nationality_signals.strength IS "
        "'Precedence, highest first. manual_review OUTRANKS EVERYTHING — a named human (or "
        "reviewed LLM) who looked at the actual operating company, in EITHER direction. Then "
        "on_exclusion_list (definitional): Wayward and PS jointly listed the brand as arriving "
        "through a China referral channel, in a signed instrument, and it BEATS Wayward''s own "
        "country field — which is demonstrably unreliable (31 of the 32 brands where they "
        "disagree are US-registered SHELLS in Eric''s book). Then CHINA WINS among the rest. A "
        "not_china signal only ever decides a brand that has no positive signal at all.'"
    )

    op.execute("DROP VIEW IF EXISTS lens_ps_nationality_conflicts")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict")
    op.execute(
        """
        CREATE VIEW lens_ps_china_verdict AS
        WITH agg AS (
            SELECT wayward_brand_id,
                   bool_or(signal = 'manual_review' AND points_to = 'china')     AS manual_china,
                   bool_or(signal = 'manual_review' AND points_to = 'not_china') AS manual_not_china,
                   count(*) FILTER (WHERE points_to = 'china')     AS china_signals,
                   count(*) FILTER (WHERE points_to = 'not_china') AS not_china_signals,
                   max(CASE strength WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5
                                     WHEN 'strong' THEN 4 WHEN 'moderate' THEN 3
                                     WHEN 'weak' THEN 2 ELSE 1 END)
                       FILTER (WHERE points_to = 'china')          AS best_china_rank,
                   string_agg(DISTINCT signal, ', ')
                       FILTER (WHERE points_to = 'china')          AS china_evidence,
                   string_agg(DISTINCT signal, ', ')
                       FILTER (WHERE points_to = 'not_china')      AS not_china_evidence,
                   max(evidence)    FILTER (WHERE signal = 'manual_review') AS manual_rationale,
                   max(asserted_by) FILTER (WHERE signal = 'manual_review') AS manual_by
            FROM ps_nationality_signals
            GROUP BY wayward_brand_id
        ),
        money AS (
            SELECT wayward_brand_id,
                   sum(usage_collected)                              AS collected,
                   -- HYPOTHETICAL: what 10/6/3% of the collected usage WOULD be. On an excluded
                   -- brand this is NOT a debt — we are owed nothing on its Connect revenue.
                   sum(ps_gross_owed)                                AS gross_if_claimable,
                   -- REAL: only the rows we may actually claim (Boost, Rule A/B, reactivation).
                   sum(ps_gross_owed)    FILTER (WHERE is_claimable) AS ps_owed,
                   sum(ps_actually_paid) FILTER (WHERE is_claimable) AS ps_paid
            FROM ps_monthly_earnings
            GROUP BY wayward_brand_id
        )
        SELECT
            b.wayward_brand_id,
            b.brand_name,
            b.signup_date,
            CASE
                WHEN a.manual_not_china                   THEN 'not_china'
                WHEN a.manual_china                       THEN 'china'
                WHEN COALESCE(a.china_signals, 0) > 0     THEN 'china'
                WHEN COALESCE(a.not_china_signals, 0) > 0 THEN 'not_china'
                ELSE 'unknown'
            END                                           AS verdict,
            CASE
                WHEN a.manual_not_china OR a.manual_china THEN 'manual'
                ELSE CASE a.best_china_rank
                        WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed' WHEN 4 THEN 'strong'
                        WHEN 3 THEN 'moderate' WHEN 2 THEN 'weak' ELSE NULL END
            END                                           AS verdict_strength,
            a.china_evidence,
            a.not_china_evidence,
            a.manual_rationale,
            a.manual_by,
            (COALESCE(a.china_signals,0) > 0 AND COALESCE(a.not_china_signals,0) > 0)
                                                          AS has_conflict,
            (x.wayward_brand_id IS NOT NULL)              AS is_excluded,
            x.bucket                                      AS excluded_bucket,
            round(m.collected, 2)                         AS usage_collected,
            -- what we are ACTUALLY owed and actually paid. Excluded brands earn only Boost and
            -- qualifying reactivations, so these are zero for most of them, and that is correct.
            round(COALESCE(m.ps_owed, 0), 2)              AS ps_owed_claimable,
            round(COALESCE(m.ps_paid, 0), 2)              AS ps_paid,
            round(COALESCE(m.ps_owed,0) - COALESCE(m.ps_paid,0), 2) AS shortfall,
            -- kept, but clearly labelled: this is NOT a debt on an excluded brand.
            round(m.gross_if_claimable, 2)                AS hypothetical_if_all_claimable
        FROM ps_brands b
        LEFT JOIN agg   a ON a.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN ps_excluded_brands x ON x.wayward_brand_id = b.wayward_brand_id
        WHERE m.collected > 0
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_china_verdict IS "
        "'THE CHINA CALL, derived from ps_nationality_signals — never hand-edited. Precedence: "
        "manual_review (a named human, EITHER direction) > on_exclusion_list (definitional — it "
        "BEATS Wayward''s country field) > CHINA WINS among the rest > not_china > unknown. "
        "*** ps_owed_claimable is the REAL debt; hypothetical_if_all_claimable is NOT. *** An "
        "excluded brand earns us nothing on Connect — only its Boost fees and qualifying "
        "reactivations. Reading the hypothetical as a debt is the single easiest way to overstate "
        "this book.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_china_verdict.hypothetical_if_all_claimable IS "
        "'What 10/6/3%% of this brand''s collected usage WOULD come to if every row were "
        "claimable. On an EXCLUDED brand it is NOT a debt — we are owed nothing on its Connect "
        "revenue. Use ps_owed_claimable for anything you intend to invoice.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_verdict TO {r}")

    op.execute(
        """
        CREATE VIEW lens_ps_nationality_conflicts AS
        SELECT v.wayward_brand_id, v.brand_name, v.verdict, v.verdict_strength,
               v.china_evidence, v.not_china_evidence, v.manual_rationale,
               v.excluded_bucket, v.usage_collected,
               v.ps_owed_claimable, v.hypothetical_if_all_claimable
        FROM lens_ps_china_verdict v
        WHERE v.has_conflict
        ORDER BY v.ps_owed_claimable DESC NULLS LAST, v.usage_collected DESC
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_nationality_conflicts IS "
        "'Brands where the evidence disagrees with itself — the exclusion list says China, "
        "Wayward''s country field says otherwise. 32 of them. The list WINS (Tim, 2026-07-13): 31 "
        "are US-registered shells in Eric''s book with classic Chinese private-label names, and we "
        "will be asking Wayward to correct their country data. BrüMate is the one true exception — "
        "an American company that a Chinese partner referred — which is precisely why the list "
        "asserts a REFERRAL CHANNEL, not a nationality, and why a human must be able to overrule "
        "it.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_nationality_conflicts TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_nationality_conflicts")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict")
