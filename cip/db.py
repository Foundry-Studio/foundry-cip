# foundry: kind=service domain=client-intelligence-platform touches=storage
"""foundry-cip schema-compatibility check.

v3 (Tim Decision-2 2026-04-28): YES, implement runtime check per T1
(do-it-right) + T7 (escalate-don't-fail-silently) + D-026-style defense-in-depth.
Cost: ~30 LOC + <5ms per process (cached). Cost of one production
'column does not exist' page: much higher.

v3 (Tim Decision-3 2026-04-28): runtime ScriptDirectory implementation per
T8 (no-post-hoc-memory). Reads expected head from packaged migrations at
runtime — cannot disagree with shipped migrations. Self-correcting; no
build-time discipline required.

The function compares:
  - DB state: SELECT version_num FROM alembic_version_cip
  - Code state: ScriptDirectory.get_current_head() from packaged migrations

If they don't match, raises SchemaMismatchError with both revisions named
+ the exact upgrade command.
"""
from __future__ import annotations
import os
import threading
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory


CIP_VERSION_TABLE = "alembic_version_cip"

# v5.2 (Round-6 panel): expose MIN_COMPATIBLE_DB_REVISION alongside CURRENT_HEAD
# so consumers can call check_schema_compatibility() with a more flexible
# contract than "DB rev == package head." For M2, both equal CURRENT_HEAD; for
# future milestones, MIN_COMPATIBLE_DB_REVISION can lag behind CURRENT_HEAD
# (e.g., during a backward-compatible window). Discovered at runtime via
# ScriptDirectory walk; default = current head until M3+ raises it explicitly.
MIN_COMPATIBLE_DB_REVISION_DEFAULT_TO_HEAD: bool = True


class SchemaMismatchError(RuntimeError):
    """Raised when DB schema state doesn't match the package's expected head.

    Always carries: db_revision, package_head, fix_command.
    """

    def __init__(self, db_revision: Optional[str], package_head: str):
        self.db_revision = db_revision
        self.package_head = package_head
        self.fix_command = (
            "DATABASE_URL=<your-url> foundry-cip-migrate upgrade head"
        )
        super().__init__(
            f"foundry-cip schema mismatch:\n"
            f"  DB at:       {db_revision or '(empty / not initialized)'}\n"
            f"  Package at:  {package_head}\n"
            f"\n"
            f"Run: {self.fix_command}\n"
        )


def _get_engine_from_url(url: Optional[str] = None) -> Engine:
    if url is None:
        url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set; pass explicit url= to check_schema_compatibility()"
        )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url)


def _get_db_revision(connection: Connection) -> Optional[str]:
    """Read current revision from the alembic_version_cip table."""
    ctx = MigrationContext.configure(
        connection,
        opts={"version_table": CIP_VERSION_TABLE},
    )
    heads = ctx.get_current_heads()
    if not heads:
        return None
    if len(heads) > 1:
        # Multiple heads — chain has unresolved branches
        raise RuntimeError(
            f"Multiple heads in alembic_version_cip: {heads}. "
            f"This indicates an unresolved migration branch — investigate."
        )
    return heads[0]


def _get_package_head() -> str:
    """Read expected head from the packaged migrations directory at runtime.

    Per Tim Decision-3 (T8 no-post-hoc-memory): runtime ScriptDirectory lookup
    rather than build-time constant. Cannot disagree with shipped migrations.

    v4 fix (Senior CONC-12): use the Alembic-native `cip:migrations` resolution
    via Config.set_main_option, which handles wheel/zip-installed packages
    correctly (alembic 1.18+ uses importlib.import_module). The old direct
    `resources.files("cip").joinpath("migrations")` returned a Traversable
    that didn't always coerce to a real filesystem path for zip wheels.
    """
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", "cip:migrations")
    cfg.set_main_option("version_path_separator", "os")
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if not head:
        raise RuntimeError(
            "ScriptDirectory.get_current_head() returned None — "
            "packaged migrations may be empty or corrupt."
        )
    return head


# v4 fix (Senior CONC-3): cache the BOOLEAN result keyed on (database_url,
# package_head), not the function call. This way a deploy-time package
# advance auto-invalidates (the package_head moves, the cache key changes,
# the function re-runs). Per-process; single threading.Lock for engine
# creation idempotency.
_check_lock = threading.Lock()
_check_cache: dict[tuple[str, str], str] = {}


def check_schema_compatibility(database_url: Optional[str] = None) -> str:
    """Verify DB schema matches the package's expected head.

    Args:
        database_url: Postgres connection string. Defaults to DATABASE_URL env.

    Returns:
        The matched revision (str) on success.

    Raises:
        SchemaMismatchError: if DB revision != package head, with named
            revisions + the exact upgrade command.

    Usage (CRITICAL — call at APPLICATION STARTUP only, not per-request):
        # In application startup, the FIRST DB-touching code path:
        from cip.db import check_schema_compatibility
        check_schema_compatibility()  # raises if schema mismatch

    Why startup-only: long-running worker processes that survive across a
    deploy could otherwise return stale truth if the package head advanced
    between calls. The (url, package_head) cache key auto-invalidates a stale
    cache when the package re-deploys, but only when this function is invoked
    again — don't rely on the cache for correctness in long loops; rely on it
    for performance only.
    """
    engine = _get_engine_from_url(database_url)
    package_head = _get_package_head()
    db_url = engine.url.render_as_string(hide_password=True)

    cache_key = (db_url, package_head)
    if cache_key in _check_cache:
        return _check_cache[cache_key]

    # First call (per process per DB+package_head): do the work, cache result.
    with _check_lock:
        # Re-check inside lock — another thread may have populated.
        if cache_key in _check_cache:
            return _check_cache[cache_key]

        with engine.connect() as conn:
            db_revision = _get_db_revision(conn)

        if db_revision != package_head:
            raise SchemaMismatchError(db_revision, package_head)

        _check_cache[cache_key] = package_head
        return package_head


# v5.2 (Round-6 Call B): `python -m cip.db check` is the supported entry point.
# Replaces the v4 `foundry-cip-migrate check` console script. Industry pattern:
# `python -m uv`, `python -m pip`. One less entry-point maintenance surface.
def _cli_main(argv: list[str] | None = None) -> int:
    """Module CLI: `python -m cip.db check`. Returns shell exit code.

    Usage:
        DATABASE_URL=<url> python -m cip.db check
    """
    import sys as _sys
    args = argv if argv is not None else _sys.argv[1:]
    if not args or args[0] != "check":
        print(
            "Usage: python -m cip.db check\n"
            "\n"
            "Verifies the connected DB schema matches the package's expected "
            "head. Reads DATABASE_URL from environment.\n"
            "\n"
            "For all other operations, use alembic directly:\n"
            "    DATABASE_URL=<url> alembic upgrade head\n"
            "    DATABASE_URL=<url> alembic downgrade -1\n"
            "    DATABASE_URL=<url> alembic history\n",
            file=_sys.stderr,
        )
        return 1
    try:
        head = check_schema_compatibility()
        print(f"Schema compatibility: OK (at revision {head})")
        return 0
    except Exception as e:
        print(f"Schema compatibility: FAILED\n{e}", file=_sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli_main())
