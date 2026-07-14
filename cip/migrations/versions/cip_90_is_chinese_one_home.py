# foundry: kind=migration domain=client-intelligence-platform
"""cip_90 (W3): is_chinese gets exactly ONE home. The money table stops contradicting the verdict.

An adversarial schema audit found two authoritative-looking answers to "is this brand Chinese",
and one of them was sitting on the money table itself:

    verdict = china, is_chinese IS NULL     492 brands   4,526 rows   $48,652.77 gross owed
    verdict = china, is_chinese = FALSE       6 brands      26 rows      $111.77 gross owed

The six that say FALSE while the verdict says CHINA:

    COOLIFE     manual_review, phone_+86                    $753.33 billed
    Heyvalue    manual_review, phone_+86, shared_mailbox    $407.42
    Gelrova     eric_sheet, on_exclusion_list                $14.90
    Neathova    manual_review, phone_+86                      $8.81
    Jarkyfine   manual_review, phone_+86, shared_mailbox       $6.31
    MOSDART     manual_review, phone_+86                       $5.55

Every one carries a +86 phone or sits on the frozen exclusion list. The spine is simply wrong.

WHERE IT CAME FROM
------------------
`compute_monthly_earnings.py` read `is_chinese` from `lens_ps_eligibility` — whose own COMMENT
already admitted the problem: "its is_chinese is the LEGACY signal and disagrees with
lens_ps_china_verdict. Do not filter money on this column." The comment was right, and the writer
read it anyway. Meanwhile `ps_monthly_earnings.is_chinese` says "The nationality DECISION. Written
only by the decision layer." Both comments live in the database and they contradict each other; a
human running \\d+ sees only the lie.

THE FIX: ONE HOME, AND THE WRITER MOVES WITH THE DATA
------------------------------------------------------
`lens_ps_china_verdict` is the home. This migration backfills the column from it, AND
`compute_monthly_earnings.py` is changed IN THE SAME WAVE to derive it from the verdict on every
run. Fixing the data alone would have been undone by the very next --apply — that is the cip_68
lesson, and it cost us YOLIX and Nexiepoch.

    china      -> true
    not_china  -> false
    probable   -> NULL
    unknown    -> NULL

NULL, NOT FALSE. "We have not decided" is not "not Chinese" (cip_72). Treating unknown as false
silently drops brands out of the book, which is exactly the direction that costs us money.

NO MONEY MOVES. This is a flag, never an amount. Verified before and after.

Revision ID: cip_90_is_chinese_one_home
Revises: cip_89_referral_confirms
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_90_is_chinese_one_home"
down_revision: str | Sequence[str] | None = "cip_89_referral_confirms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE ps_monthly_earnings m
           SET is_chinese = CASE v.verdict
                                WHEN 'china'     THEN true
                                WHEN 'not_china' THEN false
                                ELSE NULL
                            END
          FROM lens_ps_china_verdict v
         WHERE v.wayward_brand_id = m.wayward_brand_id
           AND m.is_chinese IS DISTINCT FROM CASE v.verdict
                                                 WHEN 'china'     THEN true
                                                 WHEN 'not_china' THEN false
                                                 ELSE NULL
                                             END
        """
    )
    # a brand with no verdict row at all must not keep a stale flag
    op.execute(
        """
        UPDATE ps_monthly_earnings m
           SET is_chinese = NULL
         WHERE m.is_chinese IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM lens_ps_china_verdict v
                            WHERE v.wayward_brand_id = m.wayward_brand_id)
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.is_chinese IS "
        "'*** DERIVED. THE HOME IS lens_ps_china_verdict, AND THERE IS ONLY ONE HOME. *** "
        "china -> true, not_china -> false, probable/unknown -> NULL. "
        "NULL IS NOT FALSE: ''we have not decided'' is not ''not Chinese'' (cip_72). Treating "
        "unknown as false silently drops brands out of the book — the one direction that costs us "
        "money. "
        "This column used to be written from lens_ps_eligibility''s LEGACY nationality signal, and "
        "the two disagreed on 498 brands / $48,652.77 of gross owed — six of them saying FALSE "
        "while the verdict said china, every one carrying a +86 phone or sitting on the frozen "
        "exclusion list. Two authoritative-looking answers to the same question, on the money table "
        "itself. "
        "compute_monthly_earnings.py now derives this from the verdict on EVERY run (cip_90). Do "
        "not write it from anywhere else, and do not resurrect lens_ps_eligibility.is_chinese. "
        "Guarded by the `spine_is_chinese_matches_verdict` invariant.'"
    )


def downgrade() -> None:
    # Restore the legacy source. Deliberately kept simple: the defect it recreates is documented
    # above, and nothing should ever want this.
    op.execute(
        """
        UPDATE ps_monthly_earnings m
           SET is_chinese = e.is_chinese
          FROM lens_ps_eligibility e
         WHERE e.wayward_brand_id = m.wayward_brand_id
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.is_chinese IS "
        "'The nationality DECISION. Written only by the decision layer.'"
    )
