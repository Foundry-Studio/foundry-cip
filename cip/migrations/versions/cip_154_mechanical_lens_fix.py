# foundry: kind=migration domain=client-intelligence-platform
"""cip_154_mechanical_lens_fix: DI-5b bundle of diagnosed mechanical lens fixes (M4, M5, M10, L5, H4).

Applied DYNAMICALLY at migration time so the exact live view bodies round-trip through the database unchanged.
This matters: lens_ps_attribution_at_risk carries non-ASCII text (em dashes) in its risk-message strings, so
hardcoding a captured body would risk mangling it through an encoding round-trip. Instead each fix reads the
live pg_get_viewdef, asserts its ASCII anchor occurs EXACTLY ONCE, swaps only that fragment, and
CREATE OR REPLACE's the view (identical column list, so grants survive). Every touched body is snapshotted
verbatim into tmp_cip_154_view_backup FIRST, so downgrade() restores byte-for-byte. If any anchor is absent or
ambiguous (the diagnosed shape drifted), the migration aborts before touching anything.

Fixes (audit family file -> change):
    M4  lens_ps_attribution_at_risk    operator precedence: WHERE `reactivated OR boosted AND competitor` binds
        as `reactivated OR (boosted AND competitor)`, flooding the view with ~330 non-competitor reactivations.
        Parenthesize to `(reactivated OR boosted) AND competitor`. Consumed by partners-attention.ts.
    M5  lens_ps_brand_status_grid      the month spine runs to date_trunc('month', CURRENT_DATE) while billing
        lags ~2 months, so the trailing empty months read as mass churn. Clamp the spine's upper bound to the
        data frontier max(period_month) in lens_ps_brand_revenue (the app's asOf; = 2026-06-01 today).
        lens_ps_brand_status and lens_ps_brand_movement read this grid and inherit the fix.
    M10 lens_ps_exclusion_status       the someone_else_earning bucket ARRAY literal 'Jeremy  Caspar' (two
        spaces) never matches the data value 'Jeremy Caspar' (one space, 34 brands). Fix the literal.
    L5  lens_ps_partner_payout_summary  the owed CTE's `partner_fee_owed > 0` filter drops negative adjustments
        and overstates ($3,753.60 vs the reconciled claim $3,753.49). Neutralize to `WHERE true`.
    H4  lens_ps_china_commission        wrong basis (10% of stated total_fees_paid, no china filter), UNWIRED,
        no dependent view. RETIRE via DROP; a correct rebuild is deferred to DI-5e. downgrade() recreates it.

NOT here (per the DI-5b plan's own guardrails):
    M8 lens_ps_gate_signals  SPLIT OUT - period-close gate (trust layer cip_138/139); a governance-sensitive
        close-gate change must not be bundled with trivia. Tracked as a separate task.
    L2 lens_ps_ar_aging      the plan's cited GREATEST(mgmt_fee_owed - negative wayward_paid, 0) phantom-claim
        floor is NOT in this view; the real floor is upstream in the do-not-touch lens_ps_claim. Re-plan needed.

Revision ID: cip_154_mechanical_lens_fix  (27 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_153_fix_connector_literals
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "cip_154_mechanical_lens_fix"
down_revision: str | Sequence[str] | None = "cip_153_fix_connector_literals"
branch_labels = None
depends_on = None

# Backup table for a byte-exact downgrade. Named tmp_* (NOT cip_*) so it is not mistaken for a data table and
# is invisible to preflight's cip_% table census. Dropped by downgrade().
_BACKUP = "tmp_cip_154_view_backup"

# (view, ascii_anchor_present_exactly_once, replacement). No anchor touches the non-ASCII risk strings.
_SWAPS: list[tuple[str, str, str]] = [
    # M4: parenthesize the OR so the competitor requirement binds to BOTH arms.
    (
        "lens_ps_attribution_at_risk",
        "WHERE reactivated_at IS NOT NULL OR product_id = 'boosted'::text AND someone_else_earning",
        "WHERE (reactivated_at IS NOT NULL OR product_id = 'boosted'::text) AND someone_else_earning",
    ),
    # M5: clamp the month spine to the data frontier (the app's asOf), not CURRENT_DATE. The anchor's
    # `::date::timestamp with time zone, '1 mon'::interval) gs(gs)` tail is unique to the spine upper bound and
    # does NOT match the at_risk_trend `... ::date AS at_risk_trend` use of the same date_trunc expression.
    (
        "lens_ps_brand_status_grid",
        "date_trunc('month'::text, CURRENT_DATE::timestamp with time zone)::date::timestamp with time zone, '1 mon'::interval) gs(gs)",
        "( SELECT max(period_month) FROM lens_ps_brand_revenue)::timestamp with time zone, '1 mon'::interval) gs(gs)",
    ),
    # M10: the data bucket is 'Jeremy Caspar' (one space); fix the two-space literal so 34 brands match.
    ("lens_ps_exclusion_status", "'Jeremy  Caspar'::text", "'Jeremy Caspar'::text"),
    # L5: neutralize the owed-CTE filter so negative adjustments net in (-> $3,753.49).
    (
        "lens_ps_partner_payout_summary",
        "WHERE lens_ps_commission_ledger.partner_fee_owed > 0::numeric",
        "WHERE true",
    ),
]
_DROP_VIEW = "lens_ps_china_commission"  # H4 - retired (unwired, wrong basis)
_ALL_TOUCHED = [v for v, _, _ in _SWAPS] + [_DROP_VIEW]


def _viewdef(conn, view: str) -> str:
    body = conn.execute(text("SELECT pg_get_viewdef(cast(:v as regclass), true)"), {"v": view}).scalar()
    if not body:
        raise AssertionError(f"cip_154: {view} has no viewdef (missing?)")
    return body


def _snapshot(conn) -> None:
    """Verbatim backup of every touched view body (UTF-8 stays inside the DB; no encoding round-trip)."""
    op.execute(f"DROP TABLE IF EXISTS {_BACKUP}")
    op.execute(f"CREATE TABLE {_BACKUP} (view_name text PRIMARY KEY, body text NOT NULL)")
    for v in _ALL_TOUCHED:
        conn.execute(
            text(f"INSERT INTO {_BACKUP}(view_name, body) VALUES (:v, :b)"),
            {"v": v, "b": _viewdef(conn, v)},
        )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    conn = op.get_bind()
    _snapshot(conn)
    for view, old, new in _SWAPS:
        body = _viewdef(conn, view)
        n = body.count(old)
        if n != 1:
            raise AssertionError(
                f"cip_154: expected exactly one occurrence of the anchor in {view}, found {n}; "
                "the live body drifted from the diagnosed shape, refusing to swap"
            )
        op.execute(f"CREATE OR REPLACE VIEW {view} AS {body.replace(old, new)}")
    op.execute(f"DROP VIEW IF EXISTS {_DROP_VIEW}")
    print(
        "cip_154: applied M4/M5/M10/L5 surgical swaps (grants preserved by CREATE OR REPLACE) and retired "
        f"{_DROP_VIEW} (H4). M8 + L2 intentionally excluded (see docstring). Backup in {_BACKUP}."
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    conn = op.get_bind()
    rows = conn.execute(text(f"SELECT view_name, body FROM {_BACKUP}")).fetchall()
    bodies = {r[0]: r[1] for r in rows}
    missing = [v for v in _ALL_TOUCHED if v not in bodies]
    if missing:
        raise AssertionError(f"cip_154 downgrade: {_BACKUP} is missing bodies for {missing}; cannot restore")
    # Recreate the dropped view first, then restore the swapped ones - all verbatim from the snapshot.
    for v in [_DROP_VIEW] + [s[0] for s in _SWAPS]:
        op.execute(f"CREATE OR REPLACE VIEW {v} AS {bodies[v]}")
    op.execute(f"DROP TABLE IF EXISTS {_BACKUP}")
    print(f"cip_154 downgrade: restored {len(_ALL_TOUCHED)} views verbatim from {_BACKUP}, then dropped it.")
