# foundry: kind=migration domain=client-intelligence-platform
"""cip_21: provision cip_metabase_project_silk role + grant on lens_china_* views.

Per CIP handoff 2026-05-22 (Project Silk cross-tenant lens-mirror) §7
item 1: this is the FAST-PATH UNBLOCKER. Read-only grant-based interim
that lets the Project Silk China CS team query EcomLever's Wayward data
via the existing `lens_china_*` views, while the bigger mirror-based
Phase 2.6 architecture goes through Atlas review.

Pattern: directly modeled on cip_09_metabase_role_views.

The role grants SELECT on the 8 China-attribution lens views from cip_18
(`lens_china_clients` + the 6 per-rep attribution lenses +
`lens_wayward_attribution_summary`). Nothing else. P-21 enforcement:
no SELECT on raw cip_* tables; no UPDATE/INSERT/DELETE on anything;
no schema-level USAGE beyond what SELECT requires.

Tenant scoping happens via the GUC `app.current_tenant`. The
foundry-metabase session bound to this role MUST set this GUC to
EcomLever's UUID (`dec814db-722a-4730-8e60-51afc4a5dad9`) before
querying — the lens views are GUC-filtered (NULLIF + current_setting
pattern from cip_09). foundry-metabase wires this via JDBC
session_preparation_statement.

INTERIM STATUS: this is grant-based by design. Phase 2.6 will replace
it with a real PS CIP tenant + mirror-based ingestion (PR-d / scope
240). When that lands, the foundry-metabase tenant gets repointed from
this role → PS CIP, lens names preserved, dashboards survive.

Password handling: per cip_09's pattern, uses env var
`PROJECT_SILK_METABASE_DB_PASSWORD` (or `METABASE_DB_PASSWORD` as
fallback for shared-secret setups) with a noisy test sentinel for
local / CI runs.

Revision ID: cip_21_project_silk_grant_role
Revises: cip_20_marketing_lists
"""
from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "cip_21_project_silk_grant_role"
down_revision: str | Sequence[str] | None = "cip_20_marketing_lists"
branch_labels = None
depends_on = None


_TEST_PASSWORD_SENTINEL = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105
_ROLE_NAME = "cip_metabase_project_silk"

# Lens views the PS Metabase tenant is allowed to read.
# All defined in cip_18 (Wayward attribution lenses). Each filters on
# app.current_tenant GUC + a `source LIKE 'China Referral%'` predicate
# (or per-rep equality).
_GRANTED_LENS_VIEWS = (
    "lens_china_clients",
    "lens_tim_attributed_deals",
    "lens_eric_attributed_deals",
    "lens_adina_attributed_deals",
    "lens_openlight_attributed_deals",
    "lens_jeremy_attributed_deals",
    "lens_hyphen_migration_deals",
    "lens_wayward_attribution_summary",
)

# Raw cip_* tables the role MUST NOT have any access to.
# Explicit REVOKE provides defense-in-depth on top of the default
# privilege revocation below.
_CIP_ENTITY_TABLES = (
    "cip_clients",
    "cip_companies",
    "cip_contacts",
    "cip_deals",
    "cip_tickets",
    "cip_ticket_comments",
    "cip_engagements",
    "cip_files",
    "cip_knowledge_chunks",
    "cip_owners",
    "cip_pipeline_stages",
    "cip_marketing_emails",
    "cip_contact_lists",
    "cip_contact_list_memberships",
    "cip_sync_runs",
    "cip_views",
    "cip_connector_property_registry",
)


def upgrade() -> None:
    password = (
        os.environ.get("PROJECT_SILK_METABASE_DB_PASSWORD")
        or os.environ.get("METABASE_DB_PASSWORD")
        or _TEST_PASSWORD_SENTINEL
    )
    bind = op.get_bind()

    # 1. Provision the role (idempotent CREATE-or-ALTER).
    # Same Python-side escape pattern as cip_09 — Postgres's CREATE/ALTER
    # ROLE grammar doesn't accept bind parameters for the password literal.
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

    # 2. Schema USAGE — required for any SELECT against public objects.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_ROLE_NAME};")

    # 3. Explicit SELECT on each granted lens view. Standard PG views are
    # owner-rights — view body executes as view owner, so the role does
    # NOT need direct access to the underlying cip_* tables.
    for view in _GRANTED_LENS_VIEWS:
        op.execute(f"GRANT SELECT ON {view} TO {_ROLE_NAME};")

    # 4. Explicit REVOKE on every cip_* entity table. Defense-in-depth —
    # blocked by ALTER DEFAULT PRIVILEGES below too, but explicit revoke
    # makes the constraint visible in the migration source.
    for tbl in _CIP_ENTITY_TABLES:
        op.execute(f"REVOKE ALL ON {tbl} FROM {_ROLE_NAME};")

    # 5. Block default-privilege grants from auto-attaching SELECT on
    # future cip_* tables added by later migrations.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE ALL ON TABLES FROM {_ROLE_NAME};"
    )


def downgrade() -> None:
    # Reverse: revoke grants, then drop role. Views are NOT dropped (they
    # came from cip_18 and remain in use by EcomLever's own consumers).
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {_ROLE_NAME};")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT ALL ON TABLES TO {_ROLE_NAME};"
    )
    # Same REASSIGN-then-DROP pattern as cip_09 for safe role cleanup.
    op.execute(f"REASSIGN OWNED BY {_ROLE_NAME} TO CURRENT_USER;")
    op.execute(f"DROP OWNED BY {_ROLE_NAME};")
    op.execute(f"DROP ROLE IF EXISTS {_ROLE_NAME};")
