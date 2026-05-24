# foundry: kind=migration domain=client-intelligence-platform
"""cip_31: provision cip_query_reader role — least-priv reader for Path 1 SQL.

Per PM scope b7e4736a (CIP agent-access read surface). Enables the
new `POST /api/v1/cip/query` bridge endpoint (Path 1: structured SQL)
where agents pass arbitrary SELECT SQL. The FAS app engine is
superuser/BYPASSRLS — running agent SQL through it would let any
agent read any tenant. This role is the load-bearing RLS fence:
NOSUPERUSER NOBYPASSRLS so the cip_tenant_scope policy actually
applies, scoping every query to `app.current_tenant`.

Why this role, not cip_metabase_role / cip_metabase_project_silk:
- Metabase roles are lens-only (P-21); broadening them would
  weaken the BI/lens boundary.
- Why not cip_sync_reader (cip_28): it has only 3 tables; agent
  queries need the full entity surface + history + views.

Read surface (enumerated from live prod 2026-05-24; per dispatch:
"enumerate live, don't blind-list"). v1 grants the 13 entity tables
the dispatch lists, their _history twins where they exist, the
discoverability + content surfaces (cip_views, cip_views_history,
cip_connector_property_registry, cip_knowledge_chunks), plus the
existing lens_* views. Deliberately excluded:

  cip_sync_runs   — operational metadata, not part of the agent
                    read surface (foundry_mcp_pm tools cover it).
  cip_test_trace  — test scaffolding.

Pattern mirrors cip_25 / cip_28: idempotent CREATE-or-ALTER ROLE,
password from `CIP_QUERY_READER_DB_PASSWORD` (sentinel fallback for
CI / local). `ALTER DEFAULT PRIVILEGES REVOKE ALL ON TABLES` —
future tables don't auto-grant.

Revision ID: cip_31_query_reader_role
Revises: cip_30_rls_with_check
"""
from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "cip_31_query_reader_role"
down_revision: str | Sequence[str] | None = "cip_30_rls_with_check"
branch_labels = None
depends_on = None


_TEST_PASSWORD_SENTINEL = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105
_ROLE_NAME = "cip_query_reader"

# The 13 entity tables the dispatch lists. Their _history twins are
# enumerated at migration runtime (only the existing pairs get the
# grant — so the migration self-adjusts if a future cip_* table
# adopts the entity shape + history twin).
_ENTITY_TABLES = (
    "cip_clients",
    "cip_companies",
    "cip_contacts",
    "cip_deals",
    "cip_tickets",
    "cip_ticket_comments",
    "cip_engagements",
    "cip_files",
    "cip_owners",
    "cip_pipeline_stages",
    "cip_marketing_emails",
    "cip_contact_lists",
    "cip_contact_list_memberships",
)

# Non-entity tables the agent read surface needs (discoverability +
# semantic content).
_DISCOVERY_TABLES = (
    "cip_views",
    "cip_connector_property_registry",
    "cip_knowledge_chunks",
)


def _enumerate_grant_set(bind) -> list[str]:
    """Resolve the live grant set: entity tables, their _history
    twins (only where they exist), discovery tables, and every
    lens_* view in public schema."""
    # _history twins that actually exist
    existing_tables = {
        r[0] for r in bind.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "AND table_name LIKE 'cip_%'"
        )).fetchall()
    }
    history_twins = [
        f"{t}_history" for t in _ENTITY_TABLES
        if f"{t}_history" in existing_tables
    ]
    # Also include cip_views_history (it's an existing _history table not
    # paired with an entity in the list, but it's part of the lens-history
    # discoverability surface).
    if "cip_views_history" in existing_tables:
        history_twins.append("cip_views_history")

    # All lens_* views (enumerated, not hardcoded — future lenses
    # auto-grant via this same role at re-apply).
    lens_views = [
        r[0] for r in bind.execute(text(
            "SELECT viewname FROM pg_views "
            "WHERE schemaname='public' AND viewname LIKE 'lens_%'"
        )).fetchall()
    ]

    return sorted(
        set(_ENTITY_TABLES) | set(history_twins)
        | set(_DISCOVERY_TABLES) | set(lens_views)
    )


def upgrade() -> None:
    password = (
        os.environ.get("CIP_QUERY_READER_DB_PASSWORD")
        or _TEST_PASSWORD_SENTINEL
    )
    bind = op.get_bind()

    # 1. Provision role (idempotent CREATE-or-ALTER, mirrors cip_25/cip_28).
    escaped_pwd = password.replace("'", "''")
    role_exists = bind.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
        {"role": _ROLE_NAME},
    ).fetchone() is not None
    if role_exists:
        op.execute(f"ALTER ROLE {_ROLE_NAME} PASSWORD '{escaped_pwd}'")
    else:
        op.execute(
            f"""
            CREATE ROLE {_ROLE_NAME}
                NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
                NOINHERIT NOREPLICATION LOGIN PASSWORD '{escaped_pwd}'
            """
        )

    # 2. Schema USAGE
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_ROLE_NAME};")

    # 3. SELECT on the resolved read surface.
    for relation in _enumerate_grant_set(bind):
        op.execute(f"GRANT SELECT ON {relation} TO {_ROLE_NAME};")

    # 4. Defense-in-depth: future tables don't auto-grant via the
    # role's default-privilege chain (matches cip_25/cip_28).
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE ALL ON TABLES FROM {_ROLE_NAME};"
    )


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {_ROLE_NAME};")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT ALL ON TABLES TO {_ROLE_NAME};"
    )
    op.execute(f"REASSIGN OWNED BY {_ROLE_NAME} TO CURRENT_USER;")
    op.execute(f"DROP OWNED BY {_ROLE_NAME};")
    op.execute(f"DROP ROLE IF EXISTS {_ROLE_NAME};")
