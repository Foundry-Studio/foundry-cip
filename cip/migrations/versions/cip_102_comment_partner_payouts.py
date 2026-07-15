# foundry: kind=migration domain=client-intelligence-platform
"""cip_102: finish documenting ps_partner_payouts — a comment on every column (Tim, 2026-07-15).

cip_101 commented the table + the two load-bearing columns; this brings the rest to the same bar as
every other money table (0 uncommented columns). Plain-text: what each field is + where it comes
from. Comments only.

Revision ID: cip_102_comment_partner_payouts
Revises: cip_101_partner_payouts
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_102_comment_partner_payouts"
down_revision: str | Sequence[str] | None = "cip_101_partner_payouts"
branch_labels = None
depends_on = None

_COMMENTS = {
    "id": "Primary key.",
    "tenant_id": "Tenant scope (RLS).",
    "wayward_brand_id": "The brand this payout is for (matches ps_monthly_earnings.wayward_brand_id).",
    "client_id": "CRM client id (nullable; the brand is the key).",
    "product_id": "Which product this payout covers — connect or boosted. FK to ps_products.",
    "period_month": "The usage month this payout covers; align with ps_monthly_earnings.period_month "
                    "to reconcile partner owed vs paid.",
    "partner_rate_pct": "Commission rate applied for this payout.",
    "paid_at": "Date we actually paid the partner.",
    "source_ref": "Provenance of this payout record (sheet name, bank/transfer ref, etc.).",
    "notes": "Free-text context.",
    "created_at": "Row created timestamp.",
    "updated_at": "Row last-updated timestamp.",
}


def upgrade() -> None:
    for colname, comment in _COMMENTS.items():
        op.execute(f"COMMENT ON COLUMN ps_partner_payouts.{colname} IS $c${comment}$c$")


def downgrade() -> None:
    for colname in _COMMENTS:
        op.execute(f"COMMENT ON COLUMN ps_partner_payouts.{colname} IS NULL")
