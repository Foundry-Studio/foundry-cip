# foundry: kind=migration domain=client-intelligence-platform
"""CIP M2 step — add 'backfill' to cip_sync_runs.sync_mode constraint.

Per D-159 (historical backfill by default, per tenant): the orchestrator
records each historical backfill as a separate cip_sync_runs row with
``sync_mode = 'backfill'``, distinct from current-state runs
('full' / 'incremental'). The original cip_03 migration only allowed
'full' and 'incremental'; this migration extends the constraint to
include 'backfill'.

Filed 2026-05-15 after the Wayward Phase 2 backfill attempt revealed
the gap: orchestrate_wayward_backfill.py's _record_backfill_run INSERT
hit `psycopg.errors.CheckViolation: new row for relation
"cip_sync_runs" violates check constraint "ck_cip_sync_runs_sync_mode"`.
The fix is structural (constraint widening), not workaround-style.

Revision ID: cip_11_sync_mode_backfill
Revises: cip_10_history_lens_views
"""
from collections.abc import Sequence

from alembic import op

revision: str = "cip_11_sync_mode_backfill"
down_revision: str | Sequence[str] | None = "cip_10_history_lens_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_cip_sync_runs_sync_mode", "cip_sync_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_cip_sync_runs_sync_mode",
        "cip_sync_runs",
        "sync_mode IN ('full','incremental','backfill')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_cip_sync_runs_sync_mode", "cip_sync_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_cip_sync_runs_sync_mode",
        "cip_sync_runs",
        "sync_mode IN ('full','incremental')",
    )
