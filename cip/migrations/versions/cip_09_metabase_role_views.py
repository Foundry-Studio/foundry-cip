# foundry: kind=migration domain=client-intelligence-platform
"""cip_09: provision cip_metabase_role + 2 hardcoded fixture lens views.

Per FND-S14 / D-155: Tier C migration. Affects Postgres roles + grants +
views; must run alembic upgrade head against local Postgres before push.

Per VISION §S6: Metabase is the sole Phase 1 consumer. This migration
ships the role + 2 views matching M4's deployed fixture lenses (Lens-A
all_companies, Lens-B eu_west_companies).

P-21 enforcement: ``cip_metabase_role`` grants SELECT only on lens_*
views, NOT on cip_* tables. A Metabase native SQL question targeting raw
``cip_companies`` raises ``permission denied for table cip_companies``.

Tenant scoping in views via explicit WHERE on ``app.current_tenant`` GUC;
not via RLS-on-view (which would bypass when view owner is superuser).

CI / test password handling per plan v3 §2.10 (QC2 C1+C2): the migration
falls back to a sentinel test password when ``METABASE_DB_PASSWORD`` env
var is unset, so alembic upgrade head doesn't break test fixtures + CI
matrix jobs. Production deployment failure mode is "Metabase fails to
authenticate" (immediate operator alert at deploy time). A sentinel test
``test_role_password_is_not_test_sentinel_in_prod`` would assert
production never falls back; M5 ships test-side validation only.

M5 Δ3 (2026-05-09 build): plan v3 §1 + dispatch §2 specified
``revision = "cip_09_metabase_role_and_lens_views"`` (35 chars). Deployed
``alembic_version_cip.version_num`` is ``VARCHAR(32)``; the longer name
truncates at upgrade time (psycopg ``StringDataRightTruncation``).
QC Round 2 Verifier H2 caught the bare ``cip_09`` issue and fixed to a
descriptive name, but didn't check the column-width constraint.
Shortened to ``cip_09_metabase_role_views`` (25 chars) — preserves both
noun deliverables (role + views), fits the constraint.

Revision ID: cip_09_metabase_role_views
Revises: cip_08_tickets_and_registry
"""
from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "cip_09_metabase_role_views"
down_revision: str | Sequence[str] | None = "cip_08_tickets_and_registry"
branch_labels = None
depends_on = None


# Test sentinel — see module docstring + plan v3 §2.10. Intentionally noisy
# so accidental production use is a grep-finding.
_TEST_PASSWORD_SENTINEL = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105


_LENS_VIEWS = ("lens_all_companies", "lens_eu_west_companies")
_CIP_ENTITY_TABLES = (
    "cip_companies",
    "cip_contacts",
    "cip_deals",
    "cip_tickets",
    "cip_files",
)


def upgrade() -> None:
    metabase_password = (
        os.environ.get("METABASE_DB_PASSWORD") or _TEST_PASSWORD_SENTINEL
    )

    bind = op.get_bind()

    # 1. Provision cip_metabase_role (idempotent CREATE-or-ALTER).
    #
    # M5 Δ2 (2026-05-09 build): plan §4.1 originally specified a DO block
    # with ``EXECUTE format(... %L, :pwd)`` for safe-quoted password
    # injection. Two separate Postgres/psycopg constraints made bind
    # parameters unworkable here:
    # (a) psycopg can't infer parameter type for a bind nested inside a
    #     DO block's dynamic SQL (raises ``IndeterminateDatatype`` even
    #     with explicit ``::VARCHAR`` cast).
    # (b) Postgres's grammar for ``CREATE ROLE ... PASSWORD`` and
    #     ``ALTER ROLE ... PASSWORD`` requires a literal string token —
    #     it does NOT accept bind parameters in this position at the
    #     parse level (``LINE x: ... PASSWORD $1`` is a syntax error).
    #
    # Mitigation: Python-side literal escaping (PG-standard single-quote
    # doubling). The password comes from a controlled source — either the
    # ``METABASE_DB_PASSWORD`` Railway secret or the test sentinel. SQL
    # injection requires control over that env var, which implies full
    # Railway access (a higher-privilege compromise than this migration
    # surface). The escape gives defense-in-depth against accidental
    # special-char passwords without trusting the source.
    escaped_pwd = metabase_password.replace("'", "''")

    role_exists = bind.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = 'cip_metabase_role'")
    ).fetchone() is not None

    if role_exists:
        op.execute(
            f"ALTER ROLE cip_metabase_role PASSWORD '{escaped_pwd}'"
        )
    else:
        op.execute(
            f"""
            CREATE ROLE cip_metabase_role
                NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
                NOINHERIT NOREPLICATION LOGIN PASSWORD '{escaped_pwd}'
            """
        )

    # 2. Create the 2 hardcoded fixture lens views.
    # Tenant scoping via explicit WHERE on app.current_tenant GUC. View body
    # runs as owner (superuser; RLS bypassed at table level), but predicate
    # filters per-session GUC. NULLIF + true-mode current_setting handles
    # GUC-not-set safely (NULL = exclude row).
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_all_companies AS
            SELECT *
            FROM cip_companies
            WHERE tenant_id = NULLIF(
                current_setting('app.current_tenant', true), ''
            )::uuid;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_eu_west_companies AS
            SELECT *
            FROM cip_companies
            WHERE tenant_id = NULLIF(
                current_setting('app.current_tenant', true), ''
            )::uuid
              AND region = 'eu-west';
        """
    )

    # 3. Strict P-21 grants.
    # USAGE on schema (required for any access to public objects).
    op.execute("GRANT USAGE ON SCHEMA public TO cip_metabase_role;")

    # Explicit GRANT only on lens_* views.
    for view in _LENS_VIEWS:
        op.execute(f"GRANT SELECT ON {view} TO cip_metabase_role;")

    # Explicit REVOKE on cip_* entity tables. Defense-in-depth — would also
    # be blocked by ALTER DEFAULT PRIVILEGES below, but explicit revoke makes
    # the constraint visible at the migration source.
    for tbl in _CIP_ENTITY_TABLES:
        op.execute(f"REVOKE ALL ON {tbl} FROM cip_metabase_role;")

    # Block default-privilege grants from auto-attaching SELECT on future
    # cip_* tables added by later migrations.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE ALL ON TABLES FROM cip_metabase_role;"
    )


def downgrade() -> None:
    # Reverse order: drop views first (depend on cip_companies), then
    # revoke grants, then drop role.
    op.execute("DROP VIEW IF EXISTS lens_eu_west_companies;")
    op.execute("DROP VIEW IF EXISTS lens_all_companies;")
    op.execute("REVOKE ALL ON SCHEMA public FROM cip_metabase_role;")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT ALL ON TABLES TO cip_metabase_role;"
    )
    # REASSIGN OWNED before DROP — handles edge case where the role owns
    # objects (shouldn't given the grant pattern above, but defensive).
    #
    # M5 Δ4 (2026-05-09 build): plan §4.1 hardcoded ``TO postgres`` for the
    # reassign target. Testcontainer Postgres (postgres:16-alpine) default
    # user is ``test``; production Railway is whatever Railway provisioned.
    # ``CURRENT_USER`` is a portable PG keyword that resolves to the
    # connection's authenticated role, which by definition has the
    # privilege to receive the reassignment (and is the same role running
    # alembic upgrade head, so no privilege escalation).
    op.execute("REASSIGN OWNED BY cip_metabase_role TO CURRENT_USER;")
    op.execute("DROP OWNED BY cip_metabase_role;")
    op.execute("DROP ROLE IF EXISTS cip_metabase_role;")
