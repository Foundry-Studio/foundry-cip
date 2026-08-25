# foundry: kind=migration domain=client-intelligence-platform
"""cip_170: retire ps_wayward_remittance + lens_ps_wayward_remittance_recon (Tim, 2026-08-25).

cip_169 created ps_wayward_remittance as a July-only "cash-basis" store, not realizing
ps_payment_events ALREADY held Wayward's monthly reports (Dec 2025 - June 2026, ingested via
scripts/ingest_payment_reports.py). July has now been folded into ps_payment_events through that
same canonical pipeline (source_ref = 2026-07-referral-report.xlsx), so all 8 months live in one
place and lens_ps_claim nets every report (wayward_paid = sum of rev_share_stated). The 10b table
+ recon lens are therefore redundant, and the operations dashboard has been repointed onto
lens_ps_claim (reports-project-silk commit 3dde5ea). This drops the redundant objects.

Reversal: cip_169 recreates both objects; this downgrade intentionally leaves them retired (they
duplicate ps_payment_events). To restore, re-run cip_169's DDL and re-ingest July into the table.

Revision ID: cip_170_retire_remittance
Revises: cip_169_wayward_remittance
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_170_retire_remittance"
down_revision: str | Sequence[str] | None = "cip_169_wayward_remittance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # View first (it depends on the table), then the table. IF EXISTS keeps it idempotent.
    op.execute("DROP VIEW IF EXISTS lens_ps_wayward_remittance_recon")
    op.execute("DROP TABLE IF EXISTS ps_wayward_remittance")


def downgrade() -> None:
    # Intentional no-op: the dropped objects were redundant with ps_payment_events. Restoring them
    # means re-running cip_169's DDL + re-ingesting July; not done automatically.
    pass
