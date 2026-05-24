# foundry: kind=migration domain=client-intelligence-platform
"""cip_29: history-lens view over cip_deals_history + Metabase grants.

Per PM scope a0aebe06 ASK 1 (foundry-metabase project, 2026-05-24,
comment 1416db2a): unblocks period-specific revenue trending on the
PS Performance dashboard. Today `total_fees_paid` on cip_deals is a
lifetime cumulative snapshot — the SCD-2 history table has snapshots
of how it evolved over time, which lets Metabase compute true
period-over-period revenue deltas (e.g. "PS commission earned in May
2026 specifically", not "lifetime commission for clients onboarded in
May").

Pattern mirrors cip_10 (lens_companies_history) exactly:

- CREATE OR REPLACE VIEW lens_deals_history over cip_deals_history with
  tenant scoping via explicit WHERE on app.current_tenant GUC. GUC-not-set
  → zero rows (NULLIF + true-mode current_setting handles fail-closed).
- GRANT SELECT to the two Metabase roles that need it:
    * cip_metabase_role (Foundry-internal Metabase, cip_09)
    * cip_metabase_project_silk (PS-tenant Metabase, cip_21)
  Both already have SELECT on the cip_18 china-attribution deal lenses
  + cip_24 china companies/contacts lenses; adding history is the next
  natural extension.
- P-21 enforcement intact: a Metabase native SQL question against raw
  cip_deals_history still raises permission denied. Only the lens_*
  surface is reachable.

Revision ID: cip_29_deals_history_lens
Revises: cip_28_sync_reader_role
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_29_deals_history_lens"
down_revision: str | Sequence[str] | None = "cip_28_sync_reader_role"
branch_labels = None
depends_on = None


_GRANTEE_ROLES = (
    "cip_metabase_role",
    "cip_metabase_project_silk",
)


def upgrade() -> None:
    # Hardcoded history-lens view over cip_deals_history.
    # Tenant scoping via explicit WHERE on app.current_tenant GUC, mirroring
    # the cip_10 lens_companies_history pattern.
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_deals_history AS
            SELECT *
            FROM cip_deals_history
            WHERE tenant_id = NULLIF(
                current_setting('app.current_tenant', true), ''
            )::uuid;
        """
    )

    # Grant SELECT to both Metabase roles.
    for role in _GRANTEE_ROLES:
        op.execute(f"GRANT SELECT ON lens_deals_history TO {role};")


def downgrade() -> None:
    for role in _GRANTEE_ROLES:
        op.execute(f"REVOKE SELECT ON lens_deals_history FROM {role};")
    op.execute("DROP VIEW IF EXISTS lens_deals_history;")
