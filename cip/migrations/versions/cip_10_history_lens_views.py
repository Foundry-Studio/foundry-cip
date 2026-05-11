# foundry: kind=migration domain=client-intelligence-platform
"""cip_10: hardcoded history-lens view + grant to cip_metabase_role.

Per FND-S14 / D-155: Tier C migration. Affects Postgres views + grants;
runs cleanly against local Postgres before push.

Per PHASE-1-PLAIN-SPEC.md §15.1 (Tim amendment 2026-05-11): close the
question "can a BI tool reach CIP's bitemporal SCD-2 history surface
through the cip_metabase_role grant matrix" before locking Phase 1.

This migration adds ONE history-lens view (over `cip_companies_history`)
as proof-of-life. The same pattern scales to the other 5 history tables
when Wayward Phase 2 needs them — that's deliberately Phase 2+ work
(auto-generator commit-watcher per task #143).

Pattern mirrors cip_09 exactly:

- Tenant scoping in the view via explicit WHERE on `app.current_tenant`
  GUC, not via RLS-on-view. (View body runs as superuser owner; the
  predicate filters per-session GUC. NULLIF + true-mode current_setting
  handles GUC-not-set safely — NULL excludes every row.)
- `cip_metabase_role` gets SELECT only on the new `lens_companies_history`
  view, NOT on the underlying `cip_companies_history` table. The role
  was never granted access to history tables in cip_09, so principle of
  least privilege already holds; no REVOKE needed.
- Idempotent CREATE OR REPLACE VIEW + GRANT.

P-21 enforcement remains intact: a Metabase native SQL question against
raw `cip_companies_history` still raises `permission denied`. Only the
`lens_*` surface is reachable.

Revision ID: cip_10_history_lens_views
Revises: cip_09_metabase_role_views
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_10_history_lens_views"
down_revision: str | Sequence[str] | None = "cip_09_metabase_role_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Hardcoded history-lens view over cip_companies_history.
    # Tenant scoping via explicit WHERE on app.current_tenant GUC, mirroring
    # the cip_09 pattern for lens_all_companies / lens_eu_west_companies.
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_companies_history AS
            SELECT *
            FROM cip_companies_history
            WHERE tenant_id = NULLIF(
                current_setting('app.current_tenant', true), ''
            )::uuid;
        """
    )

    # Grant SELECT on the new view to cip_metabase_role. The role itself
    # was provisioned in cip_09; this migration only extends the grant
    # matrix for the new history-lens view.
    op.execute(
        "GRANT SELECT ON lens_companies_history TO cip_metabase_role;"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE SELECT ON lens_companies_history FROM cip_metabase_role;"
    )
    op.execute("DROP VIEW IF EXISTS lens_companies_history;")
