# foundry: kind=migration domain=client-intelligence-platform
"""cip_28: provision cip_sync_reader role — least-priv reader for Leg A.

Per PM scope bd5bf34a (Phase 2.8 round-trip prereq, 2026-05-23).
Phase 2.8 Leg A (foundry-crm `src/sync/cip_to_crm_importer.py`) reads
PS brands + contacts out of CIP and pushes them into the Foundry-CRM.

Why this role exists:

  - Leg A reads ``cip_clients`` DIRECTLY rather than the cip_26 lens.
    The lens emits ``cl.client_id`` (the deterministic uuid5), but the
    LOCKED Leg-B-join contract requires ``cl.id`` (the gen_random_uuid
    PK) — the column the lens omits. Extending the lens would force
    a CIP migration; reading the raw table is the sanctioned path.

  - ``cip_metabase_project_silk`` (cip_21) is intentionally
    lens-only per P-21 — granting it SELECT on the raw entity tables
    would weaken the BI/lens boundary. So Leg A gets its own
    dedicated reader role with SELECT on the 3 tables it actually
    needs and nothing else.

  - The role is ``NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION LOGIN`` — RLS still scopes every read
    to the GUC tenant. Leg A sets ``app.current_tenant = PS`` at the
    top of every read txn (cip_18/cip_24/cip_25 idiom).

v1 surface (this migration): SELECT on ``cip_clients``,
``cip_companies``, ``cip_contacts`` only. ``cip_deals`` deliberately
NOT granted — v2 (deals→opportunities) is an unresolved design
decision (CIP-SPEC-012 §4: CRM owns the forward pipeline). When v2
ships, extend this role's grants in a follow-up migration.

Password handling mirrors cip_09 / cip_21 / cip_25: env var
``CIP_SYNC_READER_DB_PASSWORD`` with the noisy test sentinel for
CI/local. Operator MUST set the real Railway secret + re-run upgrade
(or one-shot ALTER ROLE) before Leg A connects in prod.

Revision ID: cip_28_sync_reader_role
Revises: cip_26_ps_lens_views
"""
from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "cip_28_sync_reader_role"
down_revision: str | Sequence[str] | None = "cip_26_ps_lens_views"
branch_labels = None
depends_on = None


_TEST_PASSWORD_SENTINEL = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105
_ROLE_NAME = "cip_sync_reader"

# Tables cip_sync_reader can SELECT (v1 — companies + contacts surface).
# cip_deals NOT granted yet — that's gated on the v2 deals decision
# (CIP-SPEC-012 §4 / Leg A spec §7).
_READABLE_TABLES = (
    "cip_clients",
    "cip_companies",
    "cip_contacts",
)


def upgrade() -> None:
    password = (
        os.environ.get("CIP_SYNC_READER_DB_PASSWORD")
        or _TEST_PASSWORD_SENTINEL
    )
    bind = op.get_bind()

    # 1. Provision role (idempotent CREATE-or-ALTER, mirrors cip_25).
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

    # 3. SELECT on the 3 entity tables
    for tbl in _READABLE_TABLES:
        op.execute(f"GRANT SELECT ON {tbl} TO {_ROLE_NAME};")

    # 4. Block default-privilege grants from auto-attaching to future tables.
    # Defense-in-depth: if a future cip_NN migration creates a new table and
    # an admin's role-default-privileges would otherwise sweep cip_sync_reader
    # into it, this REVOKE keeps the v1 surface tight.
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
