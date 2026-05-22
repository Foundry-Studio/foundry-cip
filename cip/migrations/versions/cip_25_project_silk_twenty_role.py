# foundry: kind=migration domain=client-intelligence-platform
"""cip_25: provision cip_twenty_project_silk role — column-level GRANT pattern.

Per Atlas-locked design (docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md
§Q1 enforcement, 2026-05-22) for PM scope 240. Provisions the Postgres
role Twenty CRM authenticates as. The role:

- SELECTs the 5 PS-relevant entity tables (cip_clients, cip_companies,
  cip_contacts, cip_deals, cip_tickets)
- Column-level UPDATE ONLY on `companion_data` of those 5 tables — and
  nothing else
- No INSERT, no DELETE, no UPDATE on any source column
- NOSUPERUSER NOBYPASSRLS LOGIN — RLS scopes to PS tenant via the
  session's `app.current_tenant` GUC (set by Twenty's JDBC
  session_preparation_statement)

This is **the entire enforcement mechanism** for Atlas's Q1 sidecar-JSONB
companion-data design. No persister changes, no application-side
validation. Twenty CAN'T write source-field columns because Postgres
won't let it.

Password handling per the cip_09 / cip_21 pattern: env var
`TWENTY_PROJECT_SILK_DB_PASSWORD` with the noisy test sentinel fallback
for CI/local. Operator must set the real Railway secret + re-run
upgrade (or one-shot ALTER ROLE) before Twenty connects.

Revision ID: cip_25_project_silk_twenty_role
Revises: cip_24_china_entity_lenses
"""
from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "cip_25_project_silk_twenty_role"
down_revision: str | Sequence[str] | None = "cip_24_china_entity_lenses"
branch_labels = None
depends_on = None


_TEST_PASSWORD_SENTINEL = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105
_ROLE_NAME = "cip_twenty_project_silk"

# Tables Twenty can read AND write companion_data on.
_COMPANION_TABLES = (
    "cip_clients",
    "cip_companies",
    "cip_contacts",
    "cip_deals",
    "cip_tickets",
)

# Tables Twenty must be denied ALL access to (defense-in-depth on top
# of the default-privilege revoke).
_DENIED_TABLES = (
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
        os.environ.get("TWENTY_PROJECT_SILK_DB_PASSWORD")
        or _TEST_PASSWORD_SENTINEL
    )
    bind = op.get_bind()

    # 1. Provision role (idempotent CREATE-or-ALTER, same Python-side
    # escape pattern as cip_09/cip_21).
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

    # 3. SELECT on the 5 entity tables
    for tbl in _COMPANION_TABLES:
        op.execute(f"GRANT SELECT ON {tbl} TO {_ROLE_NAME};")

    # 4. Column-level UPDATE on companion_data ONLY.
    # This is the load-bearing trick. Postgres column-level GRANT
    # restricts UPDATE to listed columns — any other column fails
    # with "permission denied for column <col>" at execute time.
    for tbl in _COMPANION_TABLES:
        op.execute(
            f"GRANT UPDATE (companion_data) ON {tbl} TO {_ROLE_NAME};"
        )

    # 5. Explicit REVOKE on every other cip_* entity table.
    for tbl in _DENIED_TABLES:
        op.execute(f"REVOKE ALL ON {tbl} FROM {_ROLE_NAME};")

    # 6. Block default-privilege grants from auto-attaching to future tables.
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
