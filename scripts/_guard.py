# foundry: kind=script domain=client-intelligence-platform
"""A gate, not a rule. Rules get forgotten; gates do not open.

WHY THIS EXISTS
---------------
On 2026-07-14 I made four errors in one session, and every single one was a REMOVAL or a
RECLASSIFICATION taken on my own authority:

    - dropped SZEE, Lille Home and Yoleo out of the China book because "Wayward's feed says US" —
      the single most unreliable field in the dataset, and the exact thing we spent the day proving
      unreliable. A US-registered shell reports as US. Tim: "DONT ASSUME THAT WAYWARD DATA IS
      CORRECT."
    - graded GCI Outdoors ($23,345.23 collected) as a staff test account because its Stripe mailbox
      was rebecca@wayward.com — a Wayward EMPLOYEE who set the account up on the brand's behalf.
    - wrote UNRESOLVED research findings as 'china' signals, making a Chico, California business
      come out Chinese.
    - flipped two brands to China on import records, when everyone imports from China.

Each time I knew the rule. Each time I did not consult it.

THE ASYMMETRY
-------------
ADDING evidence is safe: it is reversible, it is what the audit is for, and a wrong addition gets
caught by a human reading the list. REMOVING evidence is destructive: it silently shrinks the book
and nobody sees the brand that vanished.

So: adding is mine. **Removing is Tim's.** This module makes that mechanical.

USAGE — wrap every write:

    from _guard import china_guard

    with china_guard(conn, "backfill is_chinese", tim_approved=False):
        conn.execute(...)      # if the china count DROPS, this ROLLS BACK and raises.

Pass tim_approved=True ONLY when Tim has said so in writing, and say where he said it.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"


class ChinaVerdictLossError(RuntimeError):
    """A write reduced the China book. That is Tim's call, not mine."""


def _census(conn: Any) -> dict[str, int]:
    """The three numbers a destructive write would move."""
    verdicts = dict(
        conn.execute(
            "SELECT verdict, count(*) FROM lens_ps_china_verdict GROUP BY 1"
        ).fetchall()
    )
    signals = conn.execute(
        "SELECT count(*) FROM ps_nationality_signals WHERE points_to = 'china'"
    ).fetchone()[0]
    pinned = conn.execute(
        """SELECT count(*) FROM ps_added_facts
           WHERE field = 'china_status' AND value = 'confirmed_yes'
             AND superseded_by IS NULL"""
    ).fetchone()[0]
    return {
        "china_verdicts": verdicts.get("china", 0),
        "china_signals": signals,
        "pinned_confirmed_yes": pinned,
    }


@contextlib.contextmanager
def china_guard(conn: Any, action: str, *, tim_approved: bool = False,
                approval_note: str = "") -> Iterator[None]:
    """Refuse any write that shrinks the China book, unless Tim approved it.

    Rolls back and raises on violation. The transaction is left clean.
    """
    conn.execute("SELECT set_config('app.current_tenant', %s, false)", (PS_TENANT,))
    before = _census(conn)

    yield

    after = _census(conn)
    losses = {k: (before[k], after[k]) for k in before if after[k] < before[k]}

    if not losses:
        return

    if tim_approved:
        print(f"\n  [guard] '{action}' REDUCED the China book, and Tim approved it:")
        for k, (b, a) in losses.items():
            print(f"          {k}: {b} -> {a}  ({a - b})")
        print(f"          approval: {approval_note or 'NO NOTE GIVEN — write one'}")
        return

    conn.rollback()
    detail = "\n".join(f"    {k}: {b} -> {a}   ({a - b})" for k, (b, a) in losses.items())
    raise ChinaVerdictLossError(
        f"\n\n*** BLOCKED, AND ROLLED BACK. ***\n\n"
        f"'{action}' would have REMOVED China evidence:\n\n{detail}\n\n"
        f"Adding evidence is my call. REMOVING it is TIM'S.\n"
        f"Every error on 2026-07-14 was a removal I took on my own authority — including\n"
        f"dropping three brands because 'Wayward's feed says US', which is precisely the\n"
        f"field we proved unreliable.\n\n"
        f"If Tim has actually said to do this, pass tim_approved=True and quote him in\n"
        f"approval_note. If he has not, put it in WORKBENCH/china-audit/QUESTIONS-FOR-TIM.md\n"
        f"and leave it alone.\n"
    )
