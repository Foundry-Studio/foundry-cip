# foundry: kind=migration domain=client-intelligence-platform
"""cip_124: reporting lens G4 — lens_ps_refund_events for the Refunds tab.

The Refunds tab (REPORTING-REBUILD-PLAN §7.13) surfaces refund/credit/chargeback
events that sit OUTSIDE the money engine's refund-netting — a reconciliation signal
("did Wayward credit the client instead of paying us?"). ps_stripe_disputes and
ps_stripe_credit_notes are base tables the reporting reader can't SELECT, so expose
a PS-scoped union lens + grant (§6.1 G4).

(G5 partner-payouts needed NO migration — lens_ps_partner_payout_summary already
covers the Partners screen and is already granted to ps_reporting_reader.)

Additive + reversible; runs as owner. Verified live 2026-07-22: 23 credit notes
($42,921.67) + 16 disputes ($10,631.74).

Revision ID: cip_124_refund_events
Revises: cip_123_reporting_lenses

(Revision id kept short — alembic_version_cip is VARCHAR(32).)
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_124_refund_events"
down_revision: str | Sequence[str] | None = "cip_123_reporting_lenses"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_LENS = "lens_ps_refund_events"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_refund_events AS
        SELECT 'dispute'::text        AS event_type,
               d.stripe_dispute_id    AS event_id,
               d.amount               AS amount,
               d.currency,
               d.status,
               d.reason,
               d.dispute_created      AS event_date
        FROM ps_stripe_disputes d
        UNION ALL
        SELECT 'credit_note'::text,
               cn.stripe_credit_note_id,
               cn.total,
               cn.currency,
               cn.status,
               cn.reason,
               cn.credit_note_created
        FROM ps_stripe_credit_notes cn;
        """
    )
    op.execute(f'GRANT SELECT ON "{_LENS}" TO {_READER};')
    print(f"cip_124: created + granted {_LENS} to {_READER}")


def downgrade() -> None:
    op.execute(f'DROP VIEW IF EXISTS "{_LENS}";')
