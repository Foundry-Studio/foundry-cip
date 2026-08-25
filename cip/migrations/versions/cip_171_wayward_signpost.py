# foundry: kind=migration domain=client-intelligence-platform
"""cip_171: signpost comment on ps_payment_events (Tim, 2026-08-25).

Hardening after a near-miss: cip_169 built a parallel July-only "Wayward stated" store
(ps_wayward_remittance) without discovering that ps_payment_events ALREADY was that store
(Dec-June, 7 monthly reports). The table was documented, but discovery still failed. This
strengthens its COMMENT into a self-documenting signpost at the exact point a schema inspection
happens: what it is, how to add a month, do-not-duplicate, and how to read the dispute.

Comment-only. No schema/logic change.

Revision ID: cip_171_wayward_signpost
Revises: cip_170_retire_remittance
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_171_wayward_signpost"
down_revision: str | Sequence[str] | None = "cip_170_retire_remittance"
branch_labels = None
depends_on = None

_NEW = (
    "Jake's monthly rev-share reports (the 'referral-report' / 'Tim Rev Share Report' files), one "
    "row per brand per payment line. THE CANONICAL store of what Wayward STATES it owes/paid us: "
    "under contract 4.4 Wayward's records are 'conclusive and controlling', so this is the other side "
    "of every claim. Feeds wayward_paid in lens_ps_claim (wayward_paid = sum(rev_share_stated)). "
    "ADD EACH NEW MONTH HERE, never in a new table: drop the file in "
    "venture-ecomlever/clients/wayward/data/referral-reports/, add its row to EXPECTED-TOTALS.csv, and "
    "run scripts/ingest_payment_reports.py (header-mapped, drift-checked, idempotent). cip_169 built a "
    "parallel store by mistake and was retired in cip_170 - do not repeat that. THE DISPUTE (money "
    "Wayward owes but has not credited) = china brands with a positive lens_ps_claim.mgmt_fee_owed "
    "whose wayward_brand_id is ABSENT from this table; that anti-join is the reconciliation gap."
)

_OLD = (
    "Jake's monthly payment reports, one row per brand per month. This is what Wayward SAYS it paid "
    "us, and under contract 4.4 Wayward's records are 'conclusive and controlling' - so this table is "
    "the other side of every claim we might make."
)


def upgrade() -> None:
    op.execute(f"COMMENT ON TABLE ps_payment_events IS $c${_NEW}$c$")


def downgrade() -> None:
    op.execute(f"COMMENT ON TABLE ps_payment_events IS $c${_OLD}$c$")
