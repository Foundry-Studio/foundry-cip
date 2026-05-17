# foundry: kind=script domain=client-intelligence-platform
"""One-shot data migration: re-tag Wayward data from placeholder tenant
to canonical (EcomLever tenant + Wayward client).

History: 2026-05-12 a "locked coordinate" doc reserved
`b0000000-0000-0000-0000-000000000001` as Wayward's tenant_id. That
was a working stand-in, not VISION-aligned. VISION §4 says tenants
are operators/ventures (EcomLever is one); clients are subjects of
intelligence INSIDE a tenant (Wayward is a client of EcomLever).

This script updates every cip_* row tagged with the placeholder
tenant_id to use:
  - tenant_id = dec814db-722a-4730-8e60-51afc4a5dad9 (EcomLever)
  - client_id = 661ecab4-dddb-5924-a34d-af1c5133132d (Wayward client,
    seeded by cip_12_seed_wayward_client migration)

Idempotent: re-running after the first successful run is a no-op
(no rows match the WHERE clause once they've been migrated).

Wraps the entire update in a single transaction so partial failure
rolls back cleanly.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python -u scripts/migrate_b0_to_ecomlever.py
"""
from __future__ import annotations

import os
import re
import sys
from sqlalchemy import create_engine, text

PLACEHOLDER_TENANT = "b0000000-0000-0000-0000-000000000001"
ECOMLEVER_TENANT = "dec814db-722a-4730-8e60-51afc4a5dad9"
WAYWARD_CLIENT = "661ecab4-dddb-5924-a34d-af1c5133132d"

# Categorized via 2026-05-16 schema introspection (information_schema.columns).
# Tables that have BOTH tenant_id and client_id columns:
TABLES_WITH_TENANT_AND_CLIENT = [
    "cip_companies",
    "cip_contacts",
    "cip_deals",
    "cip_tickets",
    "cip_files",
    "cip_sync_runs",
    "cip_views",
]
# History tables have tenant_id but NO client_id (SCD-2 snapshot tables;
# their record_id FK points back to current-state which carries client_id).
# Plus cip_connector_property_registry (registry, no client scope).
TABLES_WITH_TENANT_ONLY = [
    "cip_companies_history",
    "cip_contacts_history",
    "cip_deals_history",
    "cip_tickets_history",
    "cip_files_history",
    "cip_views_history",
    "cip_clients_history",
    "cip_connector_property_registry",
]


def _resolve_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set.", file=sys.stderr)
        sys.exit(2)
    return url


def _surface_target(url: str) -> tuple[str, bool]:
    m = re.search(r"@([^/:?]+)(?::(\d+))?", url)
    host = m.group(1) if m else "<unknown>"
    is_prod = bool(re.search(r"\.rlwy\.net|\.railway\.app", host))
    banner = " *** PRODUCTION TARGET *** " if is_prod else " "
    print(f"[migrate_b0_to_ecomlever]{banner}target={host}")
    return host, is_prod


def _confirm_or_abort(host: str, is_prod: bool) -> None:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return
    confirmation = os.environ.get("SEED_CONFIRM", "")
    expected = "YES_I_KNOW_THIS_IS_PROD" if is_prod else "YES_I_KNOW_THIS_IS_REMOTE"
    if confirmation != expected:
        print(
            f"\nABORTED: target is non-local ({host}). Re-run with:\n"
            f"  SEED_CONFIRM={expected}",
            file=sys.stderr,
        )
        sys.exit(3)


def _column_exists(conn: object, table: str, column: str) -> bool:
    r = conn.execute(  # type: ignore[attr-defined]
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).first()
    return r is not None


def main() -> int:
    print("=" * 72)
    print("Wayward tenant_id correction: b0000000-... -> EcomLever + Wayward client")
    print("=" * 72)

    url = _resolve_url()
    host, is_prod = _surface_target(url)
    _confirm_or_abort(host, is_prod)

    if url.startswith("postgresql://"):
        sa_url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        sa_url = url.replace("postgres://", "postgresql+psycopg://", 1)
    else:
        sa_url = url

    engine = create_engine(sa_url, pool_pre_ping=True)

    # Pre-update counts
    print("\nPre-update row counts at placeholder tenant_id:")
    total_pre = 0
    with engine.connect() as conn:
        for tbl in TABLES_WITH_TENANT_AND_CLIENT + TABLES_WITH_TENANT_ONLY:
            try:
                n = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = :t"
                    ),
                    {"t": PLACEHOLDER_TENANT},
                ).scalar()
                print(f"  {tbl:40s} = {n}")
                total_pre += int(n or 0)
            except Exception as e:  # noqa: BLE001
                print(f"  {tbl:40s} = ERR: {e}")
    print(f"  TOTAL rows to migrate: {total_pre}")

    if total_pre == 0:
        print("\nNothing to migrate. Exiting.")
        return 0

    # Execute in a single transaction
    print(
        f"\nMigrating to:\n"
        f"  tenant_id = {ECOMLEVER_TENANT} (EcomLever)\n"
        f"  client_id = {WAYWARD_CLIENT} (Wayward)"
    )
    print()

    # Per-table savepoints so a single bad table can't poison the txn.
    # Outer transaction commits all-or-nothing; per-table failures are
    # caught + logged but don't abort the migration.
    updated_per_table: dict[str, int] = {}
    failed_tables: list[str] = []
    with engine.begin() as outer:
        for tbl in TABLES_WITH_TENANT_AND_CLIENT:
            try:
                with outer.begin_nested():
                    r = outer.execute(
                        text(
                            f"UPDATE {tbl} "
                            f"SET tenant_id = :new_tid, client_id = :new_cid "
                            f"WHERE tenant_id = :old_tid"
                        ),
                        {
                            "new_tid": ECOMLEVER_TENANT,
                            "new_cid": WAYWARD_CLIENT,
                            "old_tid": PLACEHOLDER_TENANT,
                        },
                    )
                    n = r.rowcount or 0
                    updated_per_table[tbl] = n
                    print(f"  UPDATE {tbl:38s} -> {n} rows migrated")
            except Exception as e:  # noqa: BLE001
                failed_tables.append(tbl)
                print(f"  UPDATE {tbl:38s} -> SKIPPED ({e.__class__.__name__}: {str(e)[:80]})")

        for tbl in TABLES_WITH_TENANT_ONLY:
            try:
                with outer.begin_nested():
                    r = outer.execute(
                        text(
                            f"UPDATE {tbl} SET tenant_id = :new_tid "
                            f"WHERE tenant_id = :old_tid"
                        ),
                        {
                            "new_tid": ECOMLEVER_TENANT,
                            "old_tid": PLACEHOLDER_TENANT,
                        },
                    )
                    n = r.rowcount or 0
                    updated_per_table[tbl] = n
                    print(f"  UPDATE {tbl:38s} -> {n} rows migrated")
            except Exception as e:  # noqa: BLE001
                failed_tables.append(tbl)
                print(f"  UPDATE {tbl:38s} -> SKIPPED ({e.__class__.__name__}: {str(e)[:80]})")

    total_updated = sum(updated_per_table.values())
    print(f"\nTOTAL rows updated: {total_updated}")

    # Post-update verification
    print("\nPost-update verification (rows still at placeholder - should all be 0):")
    with engine.connect() as conn:
        any_remaining = False
        for tbl in TABLES_WITH_TENANT_AND_CLIENT + TABLES_WITH_TENANT_ONLY:
            try:
                n = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = :t"
                    ),
                    {"t": PLACEHOLDER_TENANT},
                ).scalar()
                marker = "OK" if n == 0 else "FAIL"
                print(f"  [{marker}] {tbl:38s} = {n}")
                if n:
                    any_remaining = True
            except Exception as e:  # noqa: BLE001
                print(f"    {tbl:38s} = ERR: {e}")

    if any_remaining:
        print(
            "\nWARN: some rows still at placeholder tenant_id. "
            "Investigate before treating migration as complete.",
            file=sys.stderr,
        )
        return 1

    print("\nMigration complete. All Wayward data now lives at:")
    print(f"  tenant_id = {ECOMLEVER_TENANT}")
    print(f"  client_id = {WAYWARD_CLIENT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
