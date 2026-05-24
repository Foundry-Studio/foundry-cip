# foundry: kind=migration domain=client-intelligence-platform
"""cip_30: RLS WITH CHECK hardening for cip_tenant_scope (PM a1055c41).

The cip_tenant_scope RLS policy on every cip_* table was created
(starting in cip_01) as ``USING (tenant_id = <GUC>)`` with cmd=ALL
and no WITH CHECK clause. Under cmd=ALL the USING expression is
applied to BOTH the visible-row filter AND the target row of writes
— so an UPDATE on a non-tenant row finds zero rows + does nothing,
and a DELETE on a non-tenant row finds zero rows + does nothing.

But INSERTs are different. An INSERT has no "target row" to filter;
the USING expression doesn't apply. The fence on INSERT relied
implicitly on (a) the GUC being set correctly, and (b) the caller
passing the matching tenant_id in the INSERT payload. Nothing
re-validates the post-write row against the session GUC.

Same hole for UPDATEs that REWRITE tenant_id: USING filters which
existing row you can target, but Postgres re-evaluates the policy's
WITH CHECK (if any) against the post-update row — without one, you
could UPDATE a row from tenant A and rewrite tenant_id to tenant B.

This migration adds defense-in-depth by adding the SAME predicate as
WITH CHECK on every cip_tenant_scope policy. After this:
  - INSERT row whose tenant_id ≠ session GUC → REJECTED
  - UPDATE that rewrites tenant_id away from session GUC → REJECTED
  - Reads + within-tenant writes UNCHANGED

Per CIP scope a1055c41 (filed by foundry-metabase session 2026-05-23
during Leg B QC; reaffirmed by Atlas).

DATA-DRIVEN: enumerates the policy set from pg_policies at migration
runtime — every table currently carrying cip_tenant_scope gets the
WITH CHECK retrofit; future cip_* tables that adopt the policy
inherit the hardening automatically next time this migration is
re-run (it's idempotent — ALTER POLICY is). Enumerated at apply time
verified 26 tables on prod 2026-05-24:

  cip_clients{,_history}, cip_companies{,_history}, cip_connector_property_registry,
  cip_contact_list_memberships, cip_contact_lists, cip_contacts{,_history},
  cip_deals{,_history}, cip_engagements{,_history}, cip_files{,_history},
  cip_knowledge_chunks, cip_marketing_emails, cip_owners, cip_pipeline_stages,
  cip_sync_runs, cip_ticket_comments{,_history}, cip_tickets{,_history},
  cip_views{,_history}

Postgres semantics caveat: ALTER POLICY can ADD a WITH CHECK but
cannot REMOVE one — verified empirically. So downgrade DROPs and
re-CREATEs each policy with the original USING-only shape.

Revision ID: cip_30_rls_with_check
Revises: cip_29_deals_history_lens
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "cip_30_rls_with_check"
down_revision: str | Sequence[str] | None = "cip_29_deals_history_lens"
branch_labels = None
depends_on = None


# Canonical predicate — identical to the existing USING expression
# everywhere. Defined once here so any drift between USING and
# WITH CHECK would be visible in this file.
_TENANT_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
)


def _affected_tables(bind) -> list[str]:
    """Enumerate every public-schema table currently carrying the
    ``cip_tenant_scope`` policy. Data-driven so future cip_* tables
    inherit the WITH CHECK retrofit automatically when re-applied."""
    rows = bind.execute(text(
        "SELECT tablename FROM pg_policies "
        "WHERE schemaname='public' AND policyname='cip_tenant_scope' "
        "ORDER BY tablename"
    )).fetchall()
    return [r[0] for r in rows]


def upgrade() -> None:
    bind = op.get_bind()
    for tbl in _affected_tables(bind):
        # ALTER POLICY adds the WITH CHECK. Idempotent — running again
        # on a table that already has WITH CHECK is a no-op.
        op.execute(
            f"ALTER POLICY cip_tenant_scope ON {tbl} "
            f"USING ({_TENANT_PREDICATE}) "
            f"WITH CHECK ({_TENANT_PREDICATE})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    for tbl in _affected_tables(bind):
        # ALTER cannot remove WITH CHECK. DROP + CREATE preserves the
        # original USING-only shape (PERMISSIVE, role=public, cmd=ALL —
        # the Postgres defaults the original cip_01-era CREATE used).
        op.execute(f"DROP POLICY cip_tenant_scope ON {tbl}")
        op.execute(
            f"CREATE POLICY cip_tenant_scope ON {tbl} "
            f"USING ({_TENANT_PREDICATE})"
        )
