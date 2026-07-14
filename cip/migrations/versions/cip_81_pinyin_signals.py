# foundry: kind=migration domain=client-intelligence-platform
"""cip_81: admit the two pinyin-name signals, so a human override has something to override.

The 2026-07-14 scan surfaced 61 brands on a Chinese PERSONAL NAME — in the mailbox local part
(lixuejing@mftech.ltd) or on the CRM contact (WANG JIANPING). Tim ruled every one individually:
57 Chinese, 4 not.

Those two signals had no name in the vocabulary, so the evidence had nowhere to live. Burying it
in the rationale text of the decision would have collapsed two different facts into one:

    "the scan detected a Chinese name here"      <- machine, reproducible, survives any ruling
    "Tim decided this brand is Chinese"          <- human, pinned, outranks the machine

They are recorded separately and BOTH kept, including where they disagree. On the four Tim
rejected — FineVu (Korean: FineDigital, Seoul), Luciella (a .co.kr mailbox), NeuEve and
Revolution Science (US firms with a Chinese-American founder) — the pinyin signal still fires,
Tim's manual_review still wins, and has_conflict goes true. That is not noise. It is the system
showing its work: a false positive that stays VISIBLE is one we can measure; one we delete on the
way past is one that comes back.

This is the same shape as BruMate: on_exclusion_list says china, Tim says not_china, the human
wins and the disagreement remains on the record.

Revision ID: cip_81_pinyin_signals
Revises: cip_80_china_scope_signals
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_81_pinyin_signals"
down_revision: str | Sequence[str] | None = "cip_80_china_scope_signals"
branch_labels = None
depends_on = None

_BASE = (
    "on_exclusion_list", "wayward_country_cn", "cjk_in_name", "chinese_email_domain",
    "chinese_partner", "eric_sheet", "manual_review", "wayward_country_other",
    "phone_+86", "shared_owner_mailbox", "cn_mobile_handle", "qq_handle", "cn_company_name_pinyin",
)
_NEW = ("pinyin_name_in_email", "pinyin_contact_name")


def _check(values: tuple[str, ...]) -> str:
    return "CHECK (signal = ANY (ARRAY[" + ", ".join(f"'{v}'" for v in values) + "]::text[]))"


def upgrade() -> None:
    op.execute("ALTER TABLE ps_nationality_signals DROP CONSTRAINT ps_nationality_signals_signal_check")
    op.execute(
        "ALTER TABLE ps_nationality_signals ADD CONSTRAINT ps_nationality_signals_signal_check "
        + _check(_BASE + _NEW)
    )
    op.execute(
        "COMMENT ON COLUMN ps_nationality_signals.signal IS "
        "'WHAT was observed. A Chinese personal name (pinyin_name_in_email, pinyin_contact_name) "
        "is a HINT, never a verdict — a Chinese NAME is not a Chinese COMPANY. Tim''s rule cuts "
        "both ways: BruMate is American, Bob and Brad is Chinese. These signals exist to route a "
        "brand to a HUMAN, not to decide it. Only manual_review (and ps_added_facts) decide.'"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM ps_nationality_signals WHERE signal = ANY (ARRAY["
        + ", ".join(f"'{v}'" for v in _NEW)
        + "]::text[])"
    )
    op.execute("ALTER TABLE ps_nationality_signals DROP CONSTRAINT ps_nationality_signals_signal_check")
    op.execute(
        "ALTER TABLE ps_nationality_signals ADD CONSTRAINT ps_nationality_signals_signal_check "
        + _check(_BASE)
    )
