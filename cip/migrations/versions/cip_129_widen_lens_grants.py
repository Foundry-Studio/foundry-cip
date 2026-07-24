# foundry: kind=migration domain=client-intelligence-platform
"""cip_129: widen recent reporting-lens grants to all readers + clear registry drift.

The cip_123/124/125/126 reporting lenses were each granted ONLY to ps_reporting_reader (the
reporting-app role), unlike the rest of the lens catalog, which grants to the full read-role set
(cip_query_reader, cip_metabase_project_silk, cip_twenty_project_silk). Tim (2026-07-24): these
newer reporting lenses must be visible to everything (Metabase / Twenty / ad-hoc query), so widen
the 7 lenses to the full set. The app grant (ps_reporting_reader) predates this and stays.

Also clears 3 STALE cip_views registry rows -- lens_ps_billed_vs_collected / _client_performance /
_partner_performance. Their VIEW objects were dropped (cip_113 / cip_72) but the catalog rows were
never removed, so they still appear in the registry yet ERROR on read: the registry-drift symptom.

Additive + reversible; runs as owner.

Revision ID: cip_129_widen_lens_grants
Revises: cip_128_writer_nat_signals

(Revision id kept short -- alembic_version_cip is VARCHAR(32); this = 25 chars.)
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_129_widen_lens_grants"
down_revision: str | Sequence[str] | None = "cip_128_writer_nat_signals"
branch_labels = None
depends_on = None

# The full read-role set the rest of the lens catalog grants to (see cip_100-112).
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# Recent reporting lenses granted app-only (ps_reporting_reader) -- widen to the full read set.
_WIDEN = (
    "lens_ps_cash_ledger",         # cip_123
    "lens_ps_open_invoices",       # cip_123
    "lens_ps_refund_events",       # cip_124
    "lens_ps_coverage",            # cip_125
    "lens_ps_invariants",          # cip_125
    "lens_ps_brand_header",        # cip_126
    "lens_ps_statements_history",  # cip_126
)

# Orphaned cip_views registry rows (their VIEW objects were dropped in cip_113 / cip_72).
_STALE_VIEWS = (
    "lens_ps_billed_vs_collected",
    "lens_ps_client_performance",
    "lens_ps_partner_performance",
)


def upgrade() -> None:
    for lens in _WIDEN:
        for role in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {lens} TO {role};")
    # Clear the orphaned catalog rows (safe: the underlying views no longer exist).
    names = ", ".join(f"'{v}'" for v in _STALE_VIEWS)
    op.execute(f"DELETE FROM cip_views WHERE view_name IN ({names});")
    print(
        f"cip_129: widened {len(_WIDEN)} reporting lenses to {len(_READ_ROLES)} read roles; "
        f"cleared {len(_STALE_VIEWS)} stale cip_views rows"
    )


def downgrade() -> None:
    # Reverse the widen (the ps_reporting_reader app grant predates this migration and stays).
    for lens in _WIDEN:
        for role in _READ_ROLES:
            op.execute(f"REVOKE SELECT ON {lens} FROM {role};")
    # The cleared cip_views rows were orphaned drift (their views no longer exist); re-registering
    # them would just recreate stale, unreadable catalog entries, so they are intentionally NOT
    # restored on downgrade.
    print("cip_129 downgrade: revoked widened lens grants; stale cip_views rows intentionally not restored")
