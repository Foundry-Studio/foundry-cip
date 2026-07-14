# foundry: kind=migration domain=client-intelligence-platform
"""cip_87 (W1): a machine guess must not wear a human's authority.

TIM APPROVED THIS WAVE: FOUNDATION-PLAN.md W1, "I am happy with all of these" + "W1 go" (chat,
2026-07-14). Predicted movement: ZERO verdict changes. Verified before and after.

WHAT WAS WRONG
--------------
When Tim said "flip tier 1", I wrote a `manual_review` row for all 170 brands. But 131 of those
were the SHARED-MAILBOX RULE, and the evidence text proves it — it is the machine's own sentence
with four words bolted on the front:

    shared_owner_mailbox : "shares mailbox marketing@service908.com with confirmed-Chinese brand
                            'All (REDRIE)' — same owner, same portfolio"
    manual_review        : "Tim approved Tier-1 flip. shares mailbox marketing@service908.com with
                            confirmed-Chinese brand 'All (REDRIE)' — same owner, same portfolio"

Tim approved the RULE, in a batch. He did not investigate 131 brands one at a time.

WHY THAT IS DANGEROUS AND NOT MERELY UNTIDY
-------------------------------------------
`manual_review` is read SECOND in the verdict CASE, before ANY not_china evidence is looked at. So a
rubber-stamped heuristic became IMMUNE TO COUNTER-EVIDENCE, and it renders as
`verdict_strength = 'manual'` — which any reader takes to mean "a human investigated this brand".
Nobody did. It is the machine, promoted.

An adversarial audit found it, and it is the single largest systemic defect in the book: 32% of
"a human confirmed it" was the mailbox rule restated.

THE FIX
-------
A new signal, `tim_batch_approval`, which says exactly what happened: Tim approved a batch produced
by a rule. It is `confirmed` strength and points to china — it is REAL evidence, and the brands stay
Chinese. It simply stops impersonating an investigation.

    verdict BEFORE : china (via manual_review)
    verdict AFTER  : china (via shared_owner_mailbox, an approved confirming indicator)

MEASURED, not assumed — all 131 keep `shared_owner_mailbox`; ZERO would lose their China evidence;
ZERO have a conflicting human not_china row. The verdict is provably invariant.

ALSO: THE RESEARCH AGENT WAS NEVER A HUMAN EITHER
--------------------------------------------------
The Amazon-seller ingest wrote a companion `manual_review` row alongside every finding. An external
research agent is not a manual review. Those five rows are DELETED — the legal-record signals they
were escorting (`amazon_seller_entity`, `uspto_trademark_owner`) carry the verdict on their own, and
carry it better:

    AIRNEX (x2 rows), aloderma          -> keep uspto_trademark_owner / amazon_seller_entity (china)
    ACE Supply, Actial Nutrition,
    Acupoint                            -> keep both (not_china)

This also un-blocks W2: those three not_china brands were classifying as "a human pinned it" purely
because of the escort row. After this, they classify honestly as what they are — a LEGAL RECORD,
which is the only non-human thing allowed to say not_china.

Revision ID: cip_87_honest_labels
Revises: cip_86_flags_and_aliases
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_87_honest_labels"
down_revision: str | Sequence[str] | None = "cip_86_flags_and_aliases"
branch_labels = None
depends_on = None

_BASE = (
    "on_exclusion_list", "wayward_country_cn", "cjk_in_name", "chinese_email_domain",
    "chinese_partner", "eric_sheet", "manual_review", "wayward_country_other",
    "phone_+86", "shared_owner_mailbox", "cn_mobile_handle", "qq_handle",
    "cn_company_name_pinyin", "pinyin_name_in_email", "pinyin_contact_name",
    "amazon_seller_entity", "uspto_trademark_owner",
)
_NEW = ("tim_batch_approval",)


def _check(values: tuple[str, ...]) -> str:
    return "CHECK (signal = ANY (ARRAY[" + ", ".join(f"'{v}'" for v in values) + "]::text[]))"


def upgrade() -> None:
    op.execute("ALTER TABLE ps_nationality_signals DROP CONSTRAINT ps_nationality_signals_signal_check")
    op.execute(
        "ALTER TABLE ps_nationality_signals ADD CONSTRAINT ps_nationality_signals_signal_check "
        + _check(_BASE + _NEW)
    )

    # ── (a) the 131 rubber-stamps become what they are ──────────────────────
    op.execute(
        """
        UPDATE ps_nationality_signals
           SET signal   = 'tim_batch_approval',
               evidence = 'BATCH approval, not an investigation. ' || evidence
         WHERE signal = 'manual_review'
           AND source_system = 'tim:tier1_approval_2026_07_14'
           AND evidence ILIKE '%shares mailbox%'
        """
    )

    # ── (b) an external research agent is not a manual review ───────────────
    # The legal-record signals it was escorting stay, and carry the verdict alone.
    op.execute(
        """
        DELETE FROM ps_nationality_signals
         WHERE signal = 'manual_review'
           AND source_system = 'research:external_agent_2026_07_14'
        """
    )

    op.execute(
        "COMMENT ON COLUMN ps_nationality_signals.signal IS "
        "'WHAT was observed. *** manual_review MEANS A NAMED HUMAN INVESTIGATED THIS BRAND. *** It "
        "is read SECOND in the verdict, before any counter-evidence, so anything wearing it is "
        "IMMUNE TO CONTRADICTION and renders as verdict_strength=''manual''. Do not put a machine "
        "in it. "
        "*** tim_batch_approval *** = Tim approved a BATCH produced by a rule. Real evidence, "
        "honestly labelled — 131 rows wore manual_review while their text was the shared-mailbox "
        "rule''s own sentence with ''Tim approved Tier-1 flip'' bolted on the front. 32%% of ''a "
        "human confirmed it'' was the machine, promoted. "
        "*** amazon_seller_entity / uspto_trademark_owner *** are LEGAL RECORDS and need no human "
        "escort: Amazon is compelled by the INFORM Consumers Act to publish a seller''s business "
        "name and address, and a Chinese company must file a US trademark under its real entity. "
        "They are the ONLY non-human evidence permitted to say not_china. "
        "Everything else here is a proxy. A Chinese NAME is not a Chinese COMPANY — Bob and Brad is "
        "Chinese, Lifepro is Los Angeles. And a US LLC in a footer proves nothing: Chinese sellers "
        "register Delaware and Wyoming shells by the thousand.'"
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE ps_nationality_signals
           SET signal   = 'manual_review',
               evidence = replace(evidence, 'BATCH approval, not an investigation. ', '')
         WHERE signal = 'tim_batch_approval'
        """
    )
    op.execute("ALTER TABLE ps_nationality_signals DROP CONSTRAINT ps_nationality_signals_signal_check")
    op.execute(
        "ALTER TABLE ps_nationality_signals ADD CONSTRAINT ps_nationality_signals_signal_check "
        + _check(_BASE)
    )
    # NOTE: the five deleted research-agent manual_review rows are NOT recreated. They were an
    # escort for legal-record signals that remain in place and carry the verdict on their own.
    # Recreating them would restore the defect this migration exists to remove.
