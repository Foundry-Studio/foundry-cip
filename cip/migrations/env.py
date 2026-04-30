# foundry: kind=service domain=client-intelligence-platform touches=storage
"""Alembic environment configuration for foundry-cip.

Per D-146: this repo uses a SEPARATE version table (`alembic_version_cip`)
distinct from Foundry-Agent-System's default `alembic_version`. The two
chains coexist in the shared Foundry Postgres until Phase 8 extracts
cip_* data to a dedicated database.

v3 (Round-2 Q3 fix): cross-pollution guard. Refuses to run if the target
DB has revisions in the default `alembic_version` table that don't match
the cip_* prefix. Override via FOUNDRY_CIP_ALLOW_CROSS_CHAIN=1 (operator
escape-hatch for known-safe transitional scenarios).
"""
from __future__ import annotations
import os
import sys
from typing import Any
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, inspect, pool, text

config = context.config
# v4 fix (Gap GAP-04): when invoked via `alembic` CLI with a real alembic.ini,
# config.config_file_name is the path. When invoked via in-memory Config
# (programmatic invocation, e.g. from tests), it's None and fileConfig(None)
# raises TypeError. Guard before calling.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# foundry-cip doesn't bundle ORM models — migrations are explicit op.create_table().
target_metadata = None

CIP_VERSION_TABLE = "alembic_version_cip"
CIP_REVISION_PREFIX = "cip_"


def get_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set — alembic requires a Postgres connection string. "
            "Example: postgresql+psycopg://user:pw@host:5432/db"
        )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def assert_no_cross_pollution(connection: Any) -> None:
    """v3 Q3 cross-pollution guard.

    If the target DB has a default `alembic_version` table containing
    revisions NOT prefixed with `cip_`, this connection is pointed at a
    monorepo / non-CIP chain — abort to prevent corrupting foreign state.

    Override via FOUNDRY_CIP_ALLOW_CROSS_CHAIN=1 for transitional scenarios
    where an operator knows the cross-chain situation is intentional
    (e.g., during Phase 8 data-layer migration).
    """
    # v5.2 (Round-6 BLOCKER 3): allowlist-based override replaces binary bypass.
    # Old `FOUNDRY_CIP_ALLOW_CROSS_CHAIN=1` was too coarse — set it during Phase 8
    # transition and the guard silently allows ANY cross-chain pollution. New
    # pattern: operator declares the EXPECTED foreign revisions; guard verifies
    # only those are present. Anything else still aborts.
    #
    #   FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS="async_03_agents_cols,pmmg01_backfill_comments_actor"
    #
    # Setting it to "*" (single asterisk) reproduces the old binary-bypass for
    # the rare case where operator wants the v4 behavior. Empty / unset = no
    # foreign revisions allowed (default safety).
    expected_foreign_csv = os.environ.get("FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS", "").strip()
    if expected_foreign_csv == "*":
        print("WARNING: FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS=* — bypassing cross-pollution guard entirely.")
        # Audit trail: log who bypassed
        try:
            import getpass
            print(f"         Bypass operator: {getpass.getuser()}")
        except Exception:
            pass
        return

    expected_foreign: set[str] = set()
    if expected_foreign_csv:
        expected_foreign = {r.strip() for r in expected_foreign_csv.split(",") if r.strip()}
        print(f"INFO: FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS allowlist active: {sorted(expected_foreign)}")

    # Backward-compat: honor the old env var as a "*" alias for one minor-version
    # window. Will be removed at v0.2.0; document in CHANGELOG.
    if os.environ.get("FOUNDRY_CIP_ALLOW_CROSS_CHAIN") == "1":
        print("DEPRECATION: FOUNDRY_CIP_ALLOW_CROSS_CHAIN=1 is deprecated; use FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS=* for binary bypass or set the allowlist explicitly. Honoring as bypass for backward-compat (will be removed in v0.2.0).")
        return

    insp = inspect(connection)
    table_names = set(insp.get_table_names())

    # Default `alembic_version` table present? Inspect contents.
    # Catches "this DB belongs to monorepo" — foreign chain detected.
    # v5.2: tolerates revisions on the allowlist (FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS).
    if "alembic_version" in table_names:
        rows = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).fetchall()
        non_cip = [r[0] for r in rows if not r[0].startswith(CIP_REVISION_PREFIX)]
        unexpected = [r for r in non_cip if r not in expected_foreign]
        if unexpected:
            raise RuntimeError(
                f"Cross-chain pollution risk detected: target DB has default "
                f"`alembic_version` table with UNEXPECTED non-CIP revisions {unexpected}. "
                f"This DB belongs to a different Alembic chain (likely "
                f"Foundry-Agent-System monorepo). foundry-cip uses "
                f"`{CIP_VERSION_TABLE}`. Refusing to proceed.\n\n"
                f"v5.2 transitional-mode pattern (Round-6 BLOCKER 3):\n"
                f"  - For Phase 8 transition with known coexisting revisions:\n"
                f"      FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS=\"<comma-separated list of expected foreign revs>\"\n"
                f"  - For total bypass (rare, NOT recommended):\n"
                f"      FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS=\"*\"\n"
                f"  - For deprecation backward-compat (will be removed in v0.2.0):\n"
                f"      FOUNDRY_CIP_ALLOW_CROSS_CHAIN=1\n"
            )

    # v4 fix (Senior CONC-4): symmetric guard. If alembic_version_cip exists,
    # check that EVERY revision in it has the cip_ prefix. Catches operator
    # error like "manually stamped wrong revision into the cip table" or
    # "DATABASE_URL points at a stranger's chain we typoed into."
    if CIP_VERSION_TABLE in table_names:
        rows = connection.execute(
            text(f"SELECT version_num FROM {CIP_VERSION_TABLE}")
        ).fetchall()
        foreign = [r[0] for r in rows if not r[0].startswith(CIP_REVISION_PREFIX)]
        if foreign:
            raise RuntimeError(
                f"Cross-chain pollution risk detected: `{CIP_VERSION_TABLE}` "
                f"contains foreign (non-cip_*) revisions {foreign}. This is "
                f"likely an operator error (manual stamp with wrong rev, or "
                f"DATABASE_URL pointed at the wrong chain). Refusing to proceed.\n\n"
                f"If you really know this is safe, set FOUNDRY_CIP_ALLOW_CROSS_CHAIN=1."
            )


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        version_table=CIP_VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config_dict = config.get_section(config.config_ini_section) or {}
    config_dict["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(config_dict, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # NOTE: foundry-cip RLS policies use SET LOCAL app.current_tenant per-transaction.
        # Migrations bypass RLS by running as the schema-owner role; see RLS-OPERATOR-GUIDE.md.
        #
        # version_table="alembic_version_cip" — foundry-cip and Foundry-Agent-System share
        # Foundry's Postgres until Phase 8 (data-layer extraction).
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=CIP_VERSION_TABLE,
        )
        with context.begin_transaction():
            # D-127 pattern: cross-pollution guard MUST run inside begin_transaction()
            # because inspect(connection) triggers SQLAlchemy autobegin under psycopg3.
            # If the inspect runs before begin_transaction, the autobegun transaction
            # absorbs alembic's migrations and never commits — DDL silently rolls back
            # (alembic logs "Running upgrade" for every revision but no tables persist).
            # Removed transaction_per_migration=True too — redundant with the explicit
            # begin_transaction wrapper and contributed to the same autobegin trap.
            assert_no_cross_pollution(connection)
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
