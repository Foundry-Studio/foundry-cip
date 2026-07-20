# foundry: kind=migration domain=client-intelligence-platform
"""cip_117: china-contention review queue lens.

WHY (Tim's question 2026-07-20 — "is there a queue for the china/not-china calls in
contention and not sure?")
----------------------------------------------------------------------------------
Two decision surfaces already exist implicitly: the ``unknown`` verdict IS the
"not sure yet" queue (claimed at $0, revisitable, never denied). This lens builds
the OTHER one — the "in CONTENTION" queue: brands whose signals actively disagree
(china evidence AND not_china evidence both present). It exists to be reviewed by
a human, and is the natural feed for a "contention review" screen in the reporting
frontend.

It respects the asymmetry (a human ``manual_review`` not_china wins in the verdict):
the highest-priority rows are the ones where a china signal (card_country, chinese
partner, a slack flag …) is being OVERRIDDEN by a human/legal not_china on a brand
that HAS collected revenue — i.e. "are we right to NOT be claiming this one?".
Surfacing it never changes a verdict; it only makes the tension visible.

WHAT (additive — read-only view over lens_ps_china_verdict):
  contention_type  — not_china_overrides_china | china_over_not_china_hint | other
  review_priority  — high (not_china + china evidence + money) | medium | low
  + the evidence both ways, the human rationale/author, and money at stake.

Revision ID: cip_117_china_contention
Revises: cip_116_card_country_signal
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_117_china_contention"
down_revision: str | Sequence[str] | None = "cip_116_card_country_signal"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_LENS = """
CREATE VIEW lens_ps_china_contention AS
SELECT v.wayward_brand_id,
       v.brand_name,
       v.verdict,
       v.verdict_strength,
       v.china_evidence,
       v.not_china_evidence,
       v.manual_rationale,
       v.manual_by,
       v.usage_collected,
       CASE
         WHEN v.verdict = 'not_china' AND v.china_evidence IS NOT NULL
              THEN 'not_china_overrides_china'
         WHEN v.verdict = 'china' AND v.not_china_evidence IS NOT NULL
              THEN 'china_over_not_china_hint'
         ELSE 'other'
       END AS contention_type,
       CASE
         WHEN v.verdict = 'not_china' AND v.china_evidence IS NOT NULL
              AND COALESCE(v.usage_collected, 0) > 0 THEN 'high'
         WHEN v.verdict = 'not_china' AND v.china_evidence IS NOT NULL THEN 'medium'
         ELSE 'low'
       END AS review_priority
  FROM lens_ps_china_verdict v
 WHERE v.china_evidence IS NOT NULL
   AND v.not_china_evidence IS NOT NULL
"""


def upgrade() -> None:
    op.execute(_LENS)
    op.execute(
        "COMMENT ON VIEW lens_ps_china_contention IS $c$"
        "The CONTENTION review queue: brands whose nationality signals disagree "
        "(china evidence AND not_china evidence both present). review_priority='high' "
        "= a china signal (card_country / chinese_partner / slack flag) is overridden "
        "by a human/legal not_china on a brand WITH collected revenue — review whether "
        "the not_china ruling still holds. Read-only; surfacing never changes a verdict. "
        "The 'unknown' verdict is the separate 'not-sure-yet' queue.$c$"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_contention TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_contention")
