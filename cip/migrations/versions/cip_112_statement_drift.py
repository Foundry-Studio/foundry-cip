# foundry: kind=migration domain=client-intelligence-platform
"""cip_112: the statement-drift guard — "did the live number move since we pinned it?".

WHY THIS EXISTS (AUTOMATIONS-PLAN §5)
-------------------------------------
Live money math stays live (Decision of Record: "live math, not frozen") — but a claim we HAND
Wayward is pinned into ``ps_claim_statements`` (cip_104), a bank statement vs the live balance.
Between pinning a statement and the next one, the live number moves: a late Stripe payment lands,
a refund posts, a brand's nationality gets ruled. So the pinned figure and ``lens_ps_claim`` drift
apart.

``lens_ps_statement_drift`` is the reconciliation between the two, per brand:

  - stated_claim_owed  — that brand's MOST-RECENT pinned ``ps_claim_owed`` (the frozen statement)
  - live_claim_owed    — its current ``lens_ps_claim.ps_claim_owed`` (the live balance)
  - drift_amount       — live − stated (up = we're now owed MORE than we told them)
  - drift_direction    — 'up' / 'down' / 'none'

THE RULE (§5): flag, don't block. This view is THE FIRST THING CHECKED BEFORE ANY invoice or
statement goes out — if a brand drifted, the pinned number no longer matches live and someone
decides before it ships. It never blocks the send; it surfaces the delta. (Also feeds a weekly
ops-Slack digest line: "N brands drifted vs their last statement, net $X".)

Grain: one row per ``wayward_brand_id`` that appears in ``ps_claim_statements``. A brand pinned in
several statements takes its latest (by ``generated_at``). No statement pinned yet ⇒ the view is
EMPTY (the expected state today — none pinned). A brand that has since fallen out of
``lens_ps_claim`` reads live 0 (its claim went to zero) — a real 'down' drift, not an error.

Thin read-surface only: one VIEW over cip_104's view stack + pinned-statement table. No new data,
no schema-of-record change. Grants + $c$ comment match the ``lens_ps_*`` set (cip_109 style).

Revision ID: cip_112_statement_drift
Revises: cip_111_stripe_live_sync
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_112_statement_drift"
down_revision: str | Sequence[str] | None = "cip_111_stripe_live_sync"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_VIEWS = {
    "lens_ps_statement_drift": """
CREATE VIEW lens_ps_statement_drift AS
WITH latest AS (
    -- the most-recently pinned statement row per brand (a brand can be pinned in many statements)
    SELECT DISTINCT ON (s.wayward_brand_id)
        s.wayward_brand_id,
        s.brand_name,
        s.statement_label,
        s.generated_at,
        s.verdict,
        s.ownership,
        s.ps_claim_owed AS stated_claim_owed,
        s.as_of_note,
        s.source_ref
    FROM ps_claim_statements s
    WHERE s.wayward_brand_id IS NOT NULL
    ORDER BY s.wayward_brand_id, s.generated_at DESC, s.created_at DESC
),
pinned AS (
    SELECT
        l.wayward_brand_id,
        COALESCE(l.brand_name, cl.brand_name)      AS brand_name,
        l.statement_label,
        l.generated_at                             AS statement_generated_at,
        l.verdict,
        l.ownership,
        round(COALESCE(l.stated_claim_owed, 0), 2) AS stated_claim_owed,
        round(COALESCE(cl.ps_claim_owed, 0), 2)    AS live_claim_owed,
        l.as_of_note,
        l.source_ref
    FROM latest l
    LEFT JOIN lens_ps_claim cl ON cl.wayward_brand_id = l.wayward_brand_id
)
SELECT
    p.wayward_brand_id,
    p.brand_name,
    p.statement_label,
    p.statement_generated_at,
    p.verdict,
    p.ownership,
    p.stated_claim_owed,
    p.live_claim_owed,
    (p.live_claim_owed - p.stated_claim_owed) AS drift_amount,
    CASE
        WHEN p.live_claim_owed > p.stated_claim_owed THEN 'up'
        WHEN p.live_claim_owed < p.stated_claim_owed THEN 'down'
        ELSE 'none'
    END AS drift_direction,
    p.as_of_note,
    p.source_ref
FROM pinned p
""",
}

_COMMENTS = {
    "lens_ps_statement_drift": (
        "Did the live number move since the last statement we handed Wayward? Per brand pinned in "
        "ps_claim_statements: stated_claim_owed = that brand's MOST-RECENT pinned figure (the frozen "
        "bank statement), live_claim_owed = current lens_ps_claim.ps_claim_owed (the live balance) -> "
        "drift_amount (live - stated) + drift_direction (up = we're now owed MORE than we told them / "
        "down / none). ps_claim_statements is the bank statement, lens_ps_claim is the live balance; "
        "this view IS the reconciliation between them. THE FIRST THING CHECKED BEFORE SENDING ANY "
        "INVOICE/STATEMENT -- flag, don't block (AUTOMATIONS-PLAN §5): a drifted brand means the pinned "
        "number no longer matches live, so decide before it ships. Empty until a claim is pinned (none "
        "yet). A brand that fell out of lens_ps_claim reads live 0 (a real 'down' to zero)."
    ),
}


def upgrade() -> None:
    for name, sql in _VIEWS.items():
        op.execute(sql)
        op.execute(f"COMMENT ON VIEW {name} IS $c${_COMMENTS[name]}$c$")
        for r in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {name} TO {r}")


def downgrade() -> None:
    for name in reversed(list(_VIEWS)):
        op.execute(f"DROP VIEW IF EXISTS {name}")
