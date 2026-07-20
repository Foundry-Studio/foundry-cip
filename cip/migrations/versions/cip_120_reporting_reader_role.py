# foundry: kind=migration domain=client-intelligence-platform
"""cip_120: provision ps_reporting_reader — least-priv reader for the
Project Silk reporting app (reports.project-silk.com).

The reporting/dashboard frontend (Next.js on Railway, server-only DAL)
connects to prod with THIS role — never the app superuser. Two fences:

1. NOSUPERUSER NOBYPASSRLS — so the cip_tenant_scope RLS policy applies.
   (Defence-in-depth only: every ps_* base table is already single-tenant
   Project Silk data — verified live 2026-07-20, 38/38 ps_* tables show
   distinct(tenant_id)=1 = PS — so the lens surface is structurally
   PS-only regardless. NOBYPASSRLS guarantees it stays that way if a
   multi-tenant row ever lands.)

2. Grant surface = the lens_ps_* views ONLY. No base tables, no cip_*
   (multi-tenant) tables, no non-PS lenses. The 37 curated reporting
   lenses ARE the app's contract; it cannot read around them. Views run
   as owner (postgres), so nested lens/base-table reads resolve under the
   owner's privileges — the role needs SELECT only on the top-level lens.

Pattern mirrors cip_31 (cip_query_reader): idempotent CREATE-or-ALTER
ROLE, password from `PS_REPORTING_READER_DB_PASSWORD` (test sentinel
fallback for CI/local), self-adjusting grant enumeration (future
lens_ps_* views auto-grant on re-apply), `ALTER DEFAULT PRIVILEGES
REVOKE ALL ON TABLES` so future tables don't auto-grant.

Revision ID: cip_120_reporting_reader_role
Revises: cip_119_reporting_labels
"""
from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "cip_120_reporting_reader_role"
down_revision: str | Sequence[str] | None = "cip_119_reporting_labels"
branch_labels = None
depends_on = None


_TEST_PASSWORD_SENTINEL = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105
_ROLE_NAME = "ps_reporting_reader"


def _enumerate_lens_grant_set(bind) -> list[str]:
    """Every lens_ps_* view/matview in public schema. Enumerated (not
    hardcoded) so a future reporting lens auto-grants on re-apply —
    matches the cip_31 self-adjusting pattern."""
    rows = bind.execute(text(
        "SELECT c.relname "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' "
        "  AND c.relkind IN ('v', 'm') "        # regular views + matviews
        "  AND c.relname LIKE 'lens_ps_%'"
    )).fetchall()
    return sorted(r[0] for r in rows)


def upgrade() -> None:
    password = (
        os.environ.get("PS_REPORTING_READER_DB_PASSWORD")
        or _TEST_PASSWORD_SENTINEL
    )
    bind = op.get_bind()

    # 1. Provision role (idempotent CREATE-or-ALTER, mirrors cip_25/28/31).
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

    # 2. Schema USAGE (required to reference any object in public).
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_ROLE_NAME};")

    # 3. SELECT on the lens_ps_* surface ONLY — the reporting contract.
    lenses = _enumerate_lens_grant_set(bind)
    for lens in lenses:
        op.execute(f'GRANT SELECT ON "{lens}" TO {_ROLE_NAME};')
    print(f"cip_120: granted SELECT on {len(lenses)} lens_ps_* views to {_ROLE_NAME}")

    # 4. Defense-in-depth: future tables don't auto-grant via the role's
    # default-privilege chain (matches cip_25/28/31).
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
