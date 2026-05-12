# foundry: kind=script domain=client-intelligence-platform
"""Seed FixtureConnector STANDARD into a target DB under the reserved
TENANT_A fixture UUID.

Per PHASE-1-PLAIN-SPEC.md §5 + §7: the fixture tenant is the regression-
target tenant for Phase 1. Its UUID is `a0000000-0000-0000-0000-000000000001`
(reserved per METABASE-OPERATOR-GUIDE.md §2 Step 10 + `tests/migrations/
conftest.py` TENANT_A constant).

Deliberate-use script. Reads DATABASE_URL from env, prints the resolved
host + a production-target warning if applicable, requires the user to
confirm via the SEED_CONFIRM env var when targeting any non-localhost DB.

Usage:

    # Local dev:
    DATABASE_URL=postgresql://... python scripts/seed_railway_prod_fixture.py

    # Railway prod (requires explicit confirmation):
    DATABASE_URL=$DATABASE_PUBLIC_URL \
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \
        python scripts/seed_railway_prod_fixture.py

After a successful seed:

  - cip_companies for tenant a0000000-...0001 has 50 rows.
  - cip_contacts has 200, cip_deals 300, cip_tickets 500, cip_files 100.
  - cip_sync_runs has one row with status='success'.
  - SCD-2 history tables have 0 rows on initial seed (history written
    only on detected changes; idempotent re-runs produce no diff).

Idempotent: re-running against the same tenant detects no changes and
writes no new rows. Safe to re-run.
"""
from __future__ import annotations

import os
import re
import sys
from uuid import UUID

from sqlalchemy import create_engine, text

from cip.integration_mesh import (
    CorpusSize,
    FixtureConnector,
    FixtureMapper,
    run_sync,
)

# Reserved fixture-tenant UUID per PHASE-1-PLAIN-SPEC.md + tests/migrations/conftest.py
TENANT_A = UUID("a0000000-0000-0000-0000-000000000001")


def _resolve_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print(
            "ERROR: DATABASE_URL not set. Set it to your target Postgres URL.\n"
            "  Local: DATABASE_URL=postgresql://user:pw@localhost:5432/db\n"
            "  Railway prod: DATABASE_URL=$DATABASE_PUBLIC_URL + "
            "SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD",
            file=sys.stderr,
        )
        sys.exit(2)
    return url


def _surface_target(url: str) -> tuple[str, bool]:
    """Print the resolved host. Return (host, is_prod)."""
    m = re.search(r"@([^/:?]+)(?::(\d+))?", url)
    host = m.group(1) if m else "<unknown>"
    port = (m.group(2) if m else None) or "5432"
    is_prod = bool(re.search(r"\.rlwy\.net|\.railway\.app", host))
    banner = " *** PRODUCTION TARGET *** " if is_prod else " "
    print(f"[seed_railway_prod_fixture]{banner}target={host}:{port}")
    return host, is_prod


def _confirm_or_abort(host: str, is_prod: bool) -> None:
    """Require explicit confirmation for any non-localhost target."""
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if is_local:
        return
    confirmation = os.environ.get("SEED_CONFIRM", "")
    expected = "YES_I_KNOW_THIS_IS_PROD" if is_prod else "YES_I_KNOW_THIS_IS_REMOTE"
    if confirmation != expected:
        print(
            f"\nABORTED: target is non-local ({host}). Re-run with:\n"
            f"  SEED_CONFIRM={expected}\n"
            f"This is a one-time deliberate-action gate to prevent accidental "
            f"seeds against unintended databases.",
            file=sys.stderr,
        )
        sys.exit(3)


def _preflight_tenant_state(engine: object, tenant_id: UUID) -> dict[str, int]:
    """Probe current per-tenant row counts. Helps confirm before/after."""
    counts: dict[str, int] = {}
    with engine.connect() as conn:  # type: ignore[attr-defined]
        for tbl in (
            "cip_companies",
            "cip_contacts",
            "cip_deals",
            "cip_tickets",
            "cip_files",
            "cip_clients",
            "cip_sync_runs",
        ):
            try:
                row = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = :t"
                    ),
                    {"t": str(tenant_id)},
                ).scalar()
                counts[tbl] = int(row or 0)
            except Exception as e:  # noqa: BLE001
                counts[tbl] = -1  # table absent or unreachable
                print(f"  WARN: could not probe {tbl}: {e}")
    return counts


def main() -> int:
    print("=" * 70)
    print("foundry-cip fixture-tenant seeder")
    print("=" * 70)

    url = _resolve_url()
    host, is_prod = _surface_target(url)
    _confirm_or_abort(host, is_prod)

    # Convert to psycopg3 dialect for SQLAlchemy.
    if url.startswith("postgresql://"):
        sa_url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        sa_url = url.replace("postgres://", "postgresql+psycopg://", 1)
    else:
        sa_url = url

    engine = create_engine(sa_url, pool_pre_ping=True)

    print(f"\nFixture tenant: {TENANT_A}")
    print("\nPre-seed row counts (per-tenant scope):")
    pre = _preflight_tenant_state(engine, TENANT_A)
    for tbl, n in pre.items():
        print(f"  {tbl:30s} = {n}")

    if pre.get("cip_companies", -1) > 0:
        print(
            "\nNOTE: tenant already has rows. FixtureConnector's SCD-2 differ "
            "will detect no changes (seed=42 deterministic corpus) and write "
            "no new rows. Safe to re-run."
        )

    print(f"\nRunning FixtureConnector STANDARD sync (seed=42) against {host}...")
    print("(this writes ~1150 rows on a fresh tenant; idempotent on re-runs)")

    run_sync(
        FixtureConnector(
            tenant_id=TENANT_A, seed=42, size=CorpusSize.STANDARD
        ),
        FixtureMapper(),
        engine,
        tenant_id=TENANT_A,
        database_url=sa_url,  # orchestrator's lock-holder engine needs the +psycopg dialect
    )

    print("\nPost-seed row counts:")
    post = _preflight_tenant_state(engine, TENANT_A)
    for tbl, n in post.items():
        delta = "" if pre.get(tbl, 0) == n else f"  (+{n - pre.get(tbl, 0)})"
        print(f"  {tbl:30s} = {n}{delta}")

    expected_minimums = {
        "cip_companies": 50,
        "cip_contacts": 200,
        "cip_deals": 300,
        "cip_tickets": 500,
        "cip_files": 100,
        "cip_sync_runs": 1,
    }
    failures: list[str] = []
    for tbl, expected in expected_minimums.items():
        if post.get(tbl, 0) < expected:
            failures.append(
                f"{tbl}: expected >={expected}, got {post.get(tbl, 0)}"
            )

    if failures:
        print(
            "\nFAILED — row counts below expected:\n  " + "\n  ".join(failures),
            file=sys.stderr,
        )
        return 1

    print("\nOK - fixture seed verified for tenant", TENANT_A)
    print("\nNext step: Tim connects Metabase at reports.project-silk.com")
    print("per docs/METABASE-OPERATOR-GUIDE.md §2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
