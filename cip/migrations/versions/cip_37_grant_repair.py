# foundry: kind=migration domain=client-intelligence-platform
"""cip_37: grant-repair — lens_ps_china_deal_financials → cip_query_reader + sweep.

QC audit 2026-07-06 (foundry-cip full-repo QC pass, HANDOFF-QC-CLEANUP) found
a permission gap on the agent read surface:

`lens_ps_china_deal_financials` (created in cip_32) is registered in cip_views
but was never granted to `cip_query_reader`. cip_32's grant set was
`("cip_metabase_project_silk", "cip_twenty_project_silk")` — it predates the
convention (cip_33 onward) of always including cip_query_reader for lenses on
the agent read surface. Every other post-cip_31 lens (cip_33, cip_34, cip_36)
grants cip_query_reader; cip_32 is the sole gap. Consequence: agent SQL through
the `POST /api/v1/cip/query` bridge (Path 1), which runs as `cip_query_reader`
(cip_31 — the NOSUPERUSER NOBYPASSRLS RLS fence), gets
`permission denied for view lens_ps_china_deal_financials`.

`lens_ps_china_brands_financial_summary` (also touched by cip_32 via
CREATE OR REPLACE) is unaffected — it kept its pre-existing cip_query_reader
grant through the OR REPLACE (cip_31 had already swept it).

Two changes, both idempotent, both `cip_query_reader`-only:

(a) Primary fix — GRANT SELECT ON lens_ps_china_deal_financials TO
    cip_query_reader. Closes the audited gap directly.

(b) Self-heal sweep — enumerate every lens_* view in the public schema and
    GRANT SELECT to cip_query_reader on any it cannot currently read. This
    restores the cip_31 design invariant ("cip_query_reader reads every lens_*
    view") and prevents a future single-lens grant omission from silently
    breaking the agent query path. Safe: cip_query_reader is NOSUPERUSER
    NOBYPASSRLS (cip_31) and every lens is GUC-scoped, so the grant surface is
    exactly the cip_31-designed read surface. The metabase / twenty roles are
    deliberately NOT swept — their per-lens grants are intentional (the P-21
    lens-scoping boundary), so this migration never touches them.

Does NOT edit shipped cip_32 (immutable-migrations rule). Does NOT create or
alter any role — cip_query_reader is provisioned by cip_31, a guaranteed
ancestor.

Revision ID: cip_37_grant_repair
Revises: cip_36_lens_china_deals_history
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

revision: str = "cip_37_grant_repair"
down_revision: str | Sequence[str] | None = "cip_36_lens_china_deals_history"
branch_labels = None
depends_on = None


_ROLE = "cip_query_reader"
# The audited gap (cip_32). Granted explicitly so the intent is legible even
# though the sweep below would also catch it.
_PRIMARY_LENS = "lens_ps_china_deal_financials"


def _lens_views_missing_select(bind: Connection) -> list[str]:
    """Every lens_* view in public that _ROLE currently cannot SELECT.

    Uses has_table_privilege so the sweep is precise (grants only what's
    actually missing) and idempotent (re-apply grants nothing). _ROLE is
    created by cip_31, a guaranteed ancestor, so has_table_privilege resolves.
    """
    rows = bind.execute(
        text(
            "SELECT viewname FROM pg_views "
            "WHERE schemaname = 'public' AND viewname LIKE 'lens_%' "
            "AND NOT has_table_privilege("
            "    :role, format('public.%I', viewname), 'SELECT') "
            "ORDER BY viewname"
        ),
        {"role": _ROLE},
    ).fetchall()
    return [r[0] for r in rows]


def upgrade() -> None:
    bind = op.get_bind()

    # ── (a) Primary fix — the audited gap ───────────────────────────────
    op.execute(f"GRANT SELECT ON {_PRIMARY_LENS} TO {_ROLE}")

    # ── (b) Self-heal sweep — restore the cip_31 read-every-lens invariant ─
    missing = _lens_views_missing_select(bind)
    for view in missing:
        op.execute(f'GRANT SELECT ON "{view}" TO {_ROLE}')
    if missing:
        print(f"[cip_37] self-heal: granted SELECT to {_ROLE} on {missing}", flush=True)
    else:
        print(
            f"[cip_37] self-heal: {_ROLE} already reads every lens_* view "
            f"(primary grant on {_PRIMARY_LENS} applied)",
            flush=True,
        )


def downgrade() -> None:
    # Reverse only the primary fix. The self-heal sweep restores the cip_31
    # invariant (cip_query_reader reads every lens_*); those grants are design-
    # restoration, not individually tracked — mirrors cip_31's downgrade, which
    # likewise does not attempt per-grant reversal of its enumerate-and-grant.
    # At this point in history the sweep grants only _PRIMARY_LENS (every other
    # lens already carries the grant), so this revoke fully reverses the effect.
    op.execute(f"REVOKE SELECT ON {_PRIMARY_LENS} FROM {_ROLE}")
