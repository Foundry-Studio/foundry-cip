# foundry: kind=migration domain=client-intelligence-platform
"""cip_82: a list IS the answer. Tim's ruling, 2026-07-14.

    "ANY that are on an eric list or something are definitely, you dont even need to ask me,
     CHinese. Exclusion list, heav performaer, or any of them."

I was about to ask him to rule on 71 brands whose only China evidence was Eric's sheet — framing it
as "channel is not nationality, BruMate proves it." He cut that off. Eric's book IS the China
programme. Being in it is not a hint that generates a research task; it is the answer.

WHAT WAS WRONG
--------------
`on_exclusion_list` was already `definitional`. `eric_sheet` was only `strong`. Nothing justified
the gap — they are the same kind of fact, recorded by the same people, about the same programme.
The asymmetry meant 71 brands that Wayward and Eric both know are Chinese sat one query away from
being demoted to "probable" on my initiative.

    Eric Flat Fee Brands     582      Jeremy / Caspar    34
    Eric Rev Share Brands    133      Shallow            13
    Heavy Producer Brands     50      OpenLight           4
                                      OceanWing           1   <- BruMate

THE CARVE-OUT, AND WHY IT IS NOT AN EXCEPTION TO THE RULE
---------------------------------------------------------
BruMate is on the list (OceanWing) and is American — "american but referred by a chinese partner."
It stays not_china because Tim ruled it personally, and a PINNED ps_added_facts row outranks every
machine signal, definitional included.

That is the whole design working as intended: the rule is absolute, AND a named human can still
overrule it by name. A rule you can override by hand does not need exceptions built into it.

`chinese_partner` deliberately stays 'strong'. It is a REFERRAL relationship, not a list — and it
is literally BruMate's stated situation. Tim's ruling was about lists. Do not over-extend it.

THE SCRIPT IS FIXED TOO
-----------------------
scripts/harvest_nationality_signals.py wrote 'strong' for eric_sheet. Changing only the data here
would have been reverted by the very next --apply. That is the cip_68 lesson, and it cost us
YOLIX and Nexiepoch: a migration a script overwrites is not a fix, it is a delay.

Revision ID: cip_82_lists_are_definitive
Revises: cip_81_pinyin_signals
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_82_lists_are_definitive"
down_revision: str | Sequence[str] | None = "cip_81_pinyin_signals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE ps_nationality_signals
           SET strength = 'definitional',
               evidence = evidence || ' TIM, 2026-07-14: list membership is DEFINITIVE, not a '
                                   || 'hint. "you dont even need to ask me."'
         WHERE signal = 'eric_sheet'
           AND strength <> 'definitional'
        """
    )
    op.execute(
        "COMMENT ON TABLE ps_nationality_signals IS "
        "'One row per (brand, source, signal). Evidence, NOT verdicts — Slack saying CN and HubSpot "
        "saying US coexist here, and the conflict stays visible. "
        "*** STRENGTH LADDER: definitional > confirmed > strong > moderate > weak. *** "
        "DEFINITIONAL means A LIST SAYS SO — the frozen exclusion list (contract Exhibit A, which "
        "defines Excluded Brands as ''any and all CHINESE-BASED Brands'') or Eric''s all-agreements "
        "sheet. Tim, 2026-07-14: ''ANY that are on an eric list or something are definitely, you "
        "dont even need to ask me, CHinese.'' A list is the ANSWER, not a hint that generates a "
        "research task. "
        "chinese_partner is NOT definitional and must not be promoted: it is a REFERRAL "
        "relationship, and it is exactly BruMate''s situation (American, referred by a Chinese "
        "partner). "
        "Any of this can still be overruled BY NAME: a pinned row in ps_added_facts outranks every "
        "signal here, definitional included. That is how BruMate stays not_china while sitting on "
        "the list.'"
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE ps_nationality_signals
           SET strength = 'strong',
               evidence = replace(evidence,
                   ' TIM, 2026-07-14: list membership is DEFINITIVE, not a hint. '
                   '"you dont even need to ask me."', '')
         WHERE signal = 'eric_sheet'
        """
    )
