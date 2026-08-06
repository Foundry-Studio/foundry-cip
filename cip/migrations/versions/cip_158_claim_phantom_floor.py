"""cip_158 phantom-claim floor: floor negative wayward_paid / partner_paid in lens_ps_claim

A refund/reversal (negative rev_share_stated -> negative wayward_paid) currently INFLATES
ps_claim_owed, because lens_ps_claim floors only the RESULT of (fee_owed - paid) at 0, not the
paid term. mgmt_fee_owed - (-X) = mgmt_fee_owed + X. Today this affects exactly 3 china brands
that all have mgmt_fee_owed = 0 (BESTMOW 2.70, 100FIXEO 0.14, somiliss 0.03 = 2.87 phantom).

Fix: floor the PAID term inside the claim calc only -- GREATEST(COALESCE(paid,0),0) -- so a
negative payment cannot manufacture a positive claim. Identity for all 1,158 non-negative rows.
The DISPLAYED wayward_paid / partner_paid columns are left un-floored so the reversal stays visible
as an audit trail. Symmetric for partner_paid (0 negative rows today, but structurally identical).

Approved by Tim 2026-08-06 (accept the -2.87 correction; a $0-fee brand's true claim is $0).

Dynamic surgical swap: reads the live view def (prod is at cip_157; the local checkout is stale and
does not carry lens_ps_claim's current SQL), asserts each anchor appears exactly once, replaces, and
backs up the original def byte-exact for a clean downgrade.

Revision ID: cip_158_claim_phantom_floor
Revises: cip_157_legal_research
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = "cip_158_claim_phantom_floor"
down_revision = "cip_157_legal_research"
branch_labels = None
depends_on = None

_VIEW = "lens_ps_claim"
_BACKUP = "tmp_cip_158_claim_backup"

# Floor ONLY the claim-calc paid terms. The distinctive "o.<fee>_fee_owed - " prefix makes each
# anchor unique -- it does NOT match the displayed "round(COALESCE(p.wayward_paid,0::numeric),2)
# AS wayward_paid" column, which must stay un-floored.
_SWAPS = [
    (
        "o.mgmt_fee_owed - COALESCE(p.wayward_paid, 0::numeric)",
        "o.mgmt_fee_owed - GREATEST(COALESCE(p.wayward_paid, 0::numeric), 0::numeric)",
    ),
    (
        "o.partner_fee_owed - COALESCE(pp.partner_paid, 0::numeric)",
        "o.partner_fee_owed - GREATEST(COALESCE(pp.partner_paid, 0::numeric), 0::numeric)",
    ),
]


def _current_def(conn) -> str:
    return conn.execute(
        sa.text("SELECT pg_get_viewdef(:v ::regclass, true)"), {"v": _VIEW}
    ).scalar()


def upgrade() -> None:
    conn = op.get_bind()
    old_def = _current_def(conn)

    conn.execute(
        sa.text(
            f"CREATE TABLE IF NOT EXISTS {_BACKUP} "
            "(view_name text PRIMARY KEY, def text NOT NULL, backed_up_at timestamptz DEFAULT now())"
        )
    )
    conn.execute(
        sa.text(
            f"INSERT INTO {_BACKUP}(view_name, def) VALUES (:n, :d) "
            "ON CONFLICT (view_name) DO UPDATE SET def = EXCLUDED.def, backed_up_at = now()"
        ),
        {"n": _VIEW, "d": old_def},
    )

    new_def = old_def
    for anchor, repl in _SWAPS:
        count = new_def.count(anchor)
        if count != 1:
            raise RuntimeError(
                f"cip_158: expected exactly 1 occurrence of anchor in {_VIEW}, found {count}: {anchor!r}"
            )
        new_def = new_def.replace(anchor, repl)

    if new_def == old_def:
        raise RuntimeError("cip_158: no change produced; aborting")

    conn.execute(sa.text(f"CREATE OR REPLACE VIEW {_VIEW} AS {new_def.rstrip().rstrip(';')}"))


def downgrade() -> None:
    conn = op.get_bind()
    old_def = conn.execute(
        sa.text(f"SELECT def FROM {_BACKUP} WHERE view_name = :n"), {"n": _VIEW}
    ).scalar()
    if not old_def:
        raise RuntimeError("cip_158 downgrade: no backup def found for lens_ps_claim")
    conn.execute(sa.text(f"CREATE OR REPLACE VIEW {_VIEW} AS {old_def.rstrip().rstrip(';')}"))
    conn.execute(sa.text(f"DELETE FROM {_BACKUP} WHERE view_name = :n"), {"n": _VIEW})
