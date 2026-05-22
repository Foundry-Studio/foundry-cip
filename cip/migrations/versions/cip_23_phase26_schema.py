# foundry: kind=migration domain=client-intelligence-platform
"""cip_23: Phase 2.6 schema — companion_data + initial_intake_route + sync_mode lens-mirror.

Per Atlas-locked design (docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md,
2026-05-22) for PM scope `62b01382`. Three schema changes bundled:

1. `companion_data JSONB NOT NULL DEFAULT '{}'::jsonb` on the 5
   PS-relevant entity tables: cip_clients, cip_companies, cip_contacts,
   cip_deals, cip_tickets. NOT on the _history tables (mirror SCD-2 is
   source-field-only; companion edits bypassing the persister are an
   accepted limitation per Atlas C-5).

2. `initial_intake_route TEXT NULL` on cip_clients. No CHECK constraint
   (Atlas: keep flexible until taxonomy stabilizes). Set on INSERT only
   via post-sync NULL-backfill from the orchestrator — NOT as a mapper
   field (would fight persister UPDATE semantics; Atlas C-2).

3. Extend `cip_sync_runs.sync_mode` CHECK to include `'lens-mirror'`.
   Template: cip_11_sync_mode_backfill.

CRITICAL — companion_data is distinct from the existing properties
(cip_companies/contacts/deals/tickets) and metadata (cip_clients)
overflow JSONB columns the mirror writes via EXTRAS_COLUMN_BY_TABLE in
persister.py:37-52. Sharing the column would mean the mirror clobbers
companion every re-sync. The fact that companion_data is not in
mapper.fields and not the configured extras_col IS the write-side
enforcement — paired with the column-level GRANT on Twenty's role
(cip_25) for the read-side.

Revision ID: cip_23_phase26_schema
Revises: cip_22_data_plane_safety_net
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_23_phase26_schema"
down_revision: str | Sequence[str] | None = "cip_22_data_plane_safety_net"
branch_labels = None
depends_on = None


# Tables that gain companion_data. NOT the _history tables (intentional).
_COMPANION_TABLES = (
    "cip_clients",
    "cip_companies",
    "cip_contacts",
    "cip_deals",
    "cip_tickets",
)

_OLD_SYNC_MODES = ("full", "incremental", "backfill")
_NEW_SYNC_MODES = ("full", "incremental", "backfill", "lens-mirror")


def _check_csv(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # 1. companion_data on the 5 entity tables
    for tbl in _COMPANION_TABLES:
        op.execute(
            f"ALTER TABLE {tbl} "
            f"ADD COLUMN IF NOT EXISTS companion_data JSONB NOT NULL "
            f"DEFAULT '{{}}'::jsonb"
        )

    # 2. initial_intake_route on cip_clients (nullable, no CHECK)
    op.execute(
        "ALTER TABLE cip_clients "
        "ADD COLUMN IF NOT EXISTS initial_intake_route TEXT NULL"
    )

    # 3. Extend cip_sync_runs.sync_mode CHECK to allow 'lens-mirror'.
    # Pattern from cip_11_sync_mode_backfill.
    op.execute(
        "ALTER TABLE cip_sync_runs "
        "DROP CONSTRAINT IF EXISTS ck_cip_sync_runs_sync_mode"
    )
    op.execute(
        f"ALTER TABLE cip_sync_runs "
        f"ADD CONSTRAINT ck_cip_sync_runs_sync_mode "
        f"CHECK (sync_mode IN ({_check_csv(_NEW_SYNC_MODES)}))"
    )


def downgrade() -> None:
    # Reverse order. CHECK first (must drop before downgrade-target rows
    # could be ambiguous), then columns. Refuse the CHECK revert if any
    # 'lens-mirror' rows exist — destructive otherwise.
    conn = op.get_bind()
    from sqlalchemy import text as _text
    bad = conn.execute(_text(
        "SELECT COUNT(*) FROM cip_sync_runs WHERE sync_mode = 'lens-mirror'"
    )).scalar()
    if bad and int(bad) > 0:
        raise RuntimeError(
            f"Refusing to downgrade: {bad} cip_sync_runs row(s) have "
            "sync_mode='lens-mirror'. Resolve those before downgrading."
        )

    op.execute(
        "ALTER TABLE cip_sync_runs "
        "DROP CONSTRAINT IF EXISTS ck_cip_sync_runs_sync_mode"
    )
    op.execute(
        f"ALTER TABLE cip_sync_runs "
        f"ADD CONSTRAINT ck_cip_sync_runs_sync_mode "
        f"CHECK (sync_mode IN ({_check_csv(_OLD_SYNC_MODES)}))"
    )

    op.execute("ALTER TABLE cip_clients DROP COLUMN IF EXISTS initial_intake_route")
    for tbl in _COMPANION_TABLES:
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS companion_data")
