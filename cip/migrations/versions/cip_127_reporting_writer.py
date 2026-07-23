# foundry: kind=migration domain=client-intelligence-platform
"""cip_127: provision ps_reporting_writer — the ONE governed money-write role for the reporting path.

The reporting app is read-only on CIP (ps_reporting_reader, cip_120). Three actions must change
money-critical data — statement.pin, partner.upsert, nationality.rule (REPORTING-REBUILD-PLAN §10.1 /
FAS-WRITE-CONTRACT) — and they go through a governed FAS endpoint, NEVER the app. That endpoint
connects to CIP with THIS role: a dedicated writer, least-privilege, NOSUPERUSER NOBYPASSRLS (so the
tenant RLS policy still applies), with write access to ONLY the three targets + a CIP-local idempotency
log. It is inert until the FAS endpoint is configured with its password (PS_REPORTING_WRITER_DB_PASSWORD,
Fernet/env) — no other caller holds it.

Grant surface:
  - ps_added_facts        INSERT + SELECT   (nationality.rule — APPEND-ONLY, §11.5; never UPDATE/DELETE)
  - ps_claim_statements   INSERT + SELECT   (statement.pin — pins are append-only as-of snapshots)
  - ps_partner_registry/credit/aliases  INSERT + UPDATE + SELECT  (partner.upsert — add/set_rate/map_alias)
  - ps_reporting_write_log INSERT + SELECT  (idempotency + FAS-side write audit — created here, in CIP,
                            so the money write + its dedup record commit in ONE transaction)
  - lens_ps_*             SELECT            (server-side re-validation — FAS re-derives every money rule)
No base-table read beyond the three write targets; no DELETE anywhere; default privileges revoked so a
future table never auto-grants.

Mirrors the cip_120 reader-role pattern (idempotent CREATE-or-ALTER, self-adjusting lens enumeration).

Revision ID: cip_127_reporting_writer
Revises: cip_126_sprint3_lenses

(Revision id ≤32 chars — alembic_version_cip is VARCHAR(32); this = 24 chars.)
"""
from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "cip_127_reporting_writer"
down_revision: str | Sequence[str] | None = "cip_126_sprint3_lenses"
branch_labels = None
depends_on = None

_TEST_PASSWORD_SENTINEL = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105
_ROLE = "ps_reporting_writer"
_APPEND_ONLY = ["ps_added_facts", "ps_claim_statements"]  # INSERT + SELECT (never UPDATE/DELETE)
_UPSERT = ["ps_partner_registry", "ps_partner_credit", "ps_partner_aliases"]  # INSERT + UPDATE + SELECT


def _enumerate_lens_grant_set(bind) -> list[str]:
    rows = bind.execute(text(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind IN ('v', 'm') AND c.relname LIKE 'lens_ps_%'"
    )).fetchall()
    return sorted(r[0] for r in rows)


def upgrade() -> None:
    password = os.environ.get("PS_REPORTING_WRITER_DB_PASSWORD") or _TEST_PASSWORD_SENTINEL
    bind = op.get_bind()
    escaped_pwd = password.replace("'", "''")

    # 1. Provision the role (idempotent CREATE-or-ALTER, mirrors cip_120).
    role_exists = bind.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": _ROLE}
    ).fetchone() is not None
    if role_exists:
        op.execute(f"ALTER ROLE {_ROLE} PASSWORD '{escaped_pwd}'")
    else:
        op.execute(
            f"CREATE ROLE {_ROLE} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE "
            f"NOINHERIT NOREPLICATION LOGIN PASSWORD '{escaped_pwd}'"
        )

    op.execute(f"GRANT USAGE ON SCHEMA public TO {_ROLE};")

    # 2. The CIP-local idempotency + write-audit log (created here so it lives with the writes, and a
    #    money write + its dedup record can commit in one transaction — §5/§7 of the write contract).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ps_reporting_write_log (
          id              bigint generated always as identity primary key,
          idempotency_key uuid        not null unique,
          write_id        uuid        not null,
          action          text        not null,
          actor_email     text        not null,
          subject         text,
          outcome         text        not null,   -- committed | rejected | noop
          payload_hash    text,                    -- same key + different payload → 409 conflict
          detail          jsonb,
          committed_at    timestamptz not null default now()
        );
        """
    )
    op.execute(f"GRANT INSERT, SELECT ON ps_reporting_write_log TO {_ROLE};")

    # 3. Write-target grants — least privilege, append-only where the model is append-only.
    for t in _APPEND_ONLY:
        op.execute(f"GRANT INSERT, SELECT ON {t} TO {_ROLE};")
    for t in _UPSERT:
        op.execute(f"GRANT INSERT, UPDATE, SELECT ON {t} TO {_ROLE};")

    # 4. SELECT on the lens surface — the writer RE-VALIDATES every money rule server-side before it commits.
    lenses = _enumerate_lens_grant_set(bind)
    for lens in lenses:
        op.execute(f'GRANT SELECT ON "{lens}" TO {_ROLE};')

    # 5. Defense-in-depth: a future table never auto-grants to the writer.
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {_ROLE};")
    print(f"cip_127: provisioned {_ROLE} (+ ps_reporting_write_log), granted {len(lenses)} lenses")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ps_reporting_write_log;")
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {_ROLE};")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {_ROLE};")
    op.execute(f"REASSIGN OWNED BY {_ROLE} TO CURRENT_USER;")
    op.execute(f"DROP OWNED BY {_ROLE};")
    op.execute(f"DROP ROLE IF EXISTS {_ROLE};")
