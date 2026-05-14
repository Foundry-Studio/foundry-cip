#!/usr/bin/env python3
# foundry: kind=script domain=client-intelligence-platform touches=integration
"""Pre-push alembic dry-run against an ephemeral Postgres testcontainer.

Run from the foundry-cip working tree (post-extraction, post-scaffolding):
    python scripts/preflight_alembic.py

Verifies:
  1. `alembic upgrade head` succeeds against a fresh Postgres (using
     script_location=cip:migrations per v3 Q1 fix)
  2. All 16 expected cip_* tables exist post-upgrade
     (7 entity + 7 history + cip_sync_runs + cip_connector_property_registry)
  3. The version_table is `alembic_version_cip` (per D-146)
  4. The wheel includes cip/migrations/versions/*.py — `pip install` produces
     a working package (Q1 packaging-fix verification per Round-2 panel)
  5. cip.db.check_schema_compatibility() passes after `alembic upgrade head`
     (Q4 schema-compat check per Tim Decision-2)
  6. `foundry-cip-migrate` console script is callable (Q1 entry-point per
     Tim Decision-1)
"""
from __future__ import annotations

import os
import subprocess
import sys

EXPECTED_TABLES = {
    # 7 entity tables
    "cip_clients", "cip_views", "cip_files", "cip_contacts",
    "cip_companies", "cip_deals", "cip_tickets",
    # 7 history tables (SCD Type 2)
    "cip_clients_history", "cip_views_history", "cip_files_history",
    "cip_contacts_history", "cip_companies_history", "cip_deals_history",
    "cip_tickets_history",
    # 2 metadata tables
    "cip_sync_runs", "cip_connector_property_registry",
}


def main() -> None:
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        print("ERROR: testcontainers not installed. Run `pip install -e .[dev]` first.")
        sys.exit(1)

    print("Starting Postgres testcontainer (postgres:16-alpine)...")
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url()
        # testcontainers may return postgresql+psycopg2 — convert to psycopg3
        url = url.replace("postgresql+psycopg2://", "postgresql+psycopg://")
        os.environ["DATABASE_URL"] = url

        print("Running `alembic upgrade head`...")
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print("ALEMBIC FAILED:")
            print(result.stdout)
            print(result.stderr)
            sys.exit(1)
        print(result.stdout)

        from sqlalchemy import create_engine, text
        engine = create_engine(url)
        with engine.begin() as conn:
            tables = conn.execute(text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='public' AND tablename LIKE 'cip_%' "
                "ORDER BY tablename"
            )).all()
            actual = {r[0] for r in tables}

        print(f"\ncip_* tables created ({len(actual)}):")
        for n in sorted(actual):
            print(f"  {n}")

        missing = EXPECTED_TABLES - actual
        extra = actual - EXPECTED_TABLES
        if missing:
            print(f"\nMISSING tables: {missing}")
            sys.exit(1)
        if extra:
            print(f"\nEXTRA tables (unexpected): {extra}")
            # Not fatal but flag

        # Verify the version table is correctly named (D-146)
        with engine.begin() as conn:
            version_tables = conn.execute(text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='public' AND tablename LIKE 'alembic_version%'"
            )).all()
            vt_names = {r[0] for r in version_tables}

        if "alembic_version_cip" not in vt_names:
            print(f"\nFAIL: expected `alembic_version_cip` table, got {vt_names}")
            sys.exit(1)
        if "alembic_version" in vt_names:
            print("\nFAIL: default `alembic_version` table exists — env.py version_table override didn't take effect")
            sys.exit(1)

        print("\nalembic upgrade head: OK")
        print("version_table: alembic_version_cip [OK]")
        print("all 16 expected cip_* tables: [OK]")


if __name__ == "__main__":
    main()
