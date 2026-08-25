# foundry: kind=migration domain=client-intelligence-platform
"""cip_172: document the three previously-uncommented wayward lenses (Tim, 2026-08-25).

Part of the post-cip_169 hardening: the "wayward" object cluster had black boxes (no COMMENT),
which is part of what makes the reconciliation landscape hard to navigate. These three now say
what they are and point at the canonical stores.

Comment-only. No schema/logic change.

Revision ID: cip_172_lens_comments
Revises: cip_171_wayward_signpost
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_172_lens_comments"
down_revision: str | Sequence[str] | None = "cip_171_wayward_signpost"
branch_labels = None
depends_on = None

_COMMENTS = {
    "lens_ps_wayward_acknowledgment": (
        "Per brand, whether Wayward has ACKNOWLEDGED/paid it: acknowledged=true if the brand appears "
        "in ps_payment_events (Wayward's monthly reports), with latest_payment_date, total_paid "
        "(sum of rev_share_stated) and payment_count. A brand ABSENT here has never been acknowledged "
        "by Wayward - the reconciliation dispute is exactly the china brands with a positive "
        "lens_ps_claim.mgmt_fee_owed that do NOT appear here."
    ),
    "lens_ps_wayward_indicators": (
        "Per brand, whether Wayward-adjacent sources INDICATE china: wayward_indicates_china=true if "
        "ps_nationality_signals carries a points_to='china' signal from a Wayward/HubSpot/exclusion-list/"
        "eric-sheet/wechat/amazon source, with the source list + best strength. Nationality EVIDENCE "
        "only; the actual verdict is lens_ps_china_verdict, not this."
    ),
    "lens_wayward_attribution_summary": (
        "Wayward's HubSpot deal PIPELINE grouped by attribution source (cip_deals via "
        "lens-mirror-deals-v1): deal_count, closed_won/lost, in_pipeline, and amounts. CRM funnel "
        "analytics by referral source - NOT a money or claim input (money = lens_ps_claim; what "
        "Wayward stated = ps_payment_events)."
    ),
}


def upgrade() -> None:
    for view, comment in _COMMENTS.items():
        op.execute(f"COMMENT ON VIEW {view} IS $c${comment}$c$")


def downgrade() -> None:
    for view in _COMMENTS:
        op.execute(f"COMMENT ON VIEW {view} IS NULL")
