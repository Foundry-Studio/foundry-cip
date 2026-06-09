# foundry: kind=script domain=client-intelligence-platform
"""Two-pass Project Silk lens-mirror orchestrator (Phase 2.6).

Per Atlas-locked design (docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md
C-1 / C-2) for PM scope 280a2f20.

This is a THIN operator wrapper around
``cip.integration_mesh.sync.run_ps_china_mirror``. The orchestration
logic moved into that callable as part of PM scope 8d47e809 (2026-06-09)
so the FAS subsystem_scheduler can drive it on a cadence.

  PASS 1 — derive PS cip_clients (deterministic uuid5, idempotent upsert)
  PASS 2 — mirror entities (deals + companies + contacts) via run_sync

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        PS_TENANT_ID=<uuidv4> \\
        python scripts/orchestrate_ps_lens_mirror.py [--dry-run]

The PS_TENANT_ID is REQUIRED — there is no default. Provisioning the PS
tenant is a separate one-shot (see scope 240); this script assumes the
PS tenants row exists in `tenants` table before running.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import create_engine, text

from cip.integration_mesh.sync import run_ps_china_mirror

logger = logging.getLogger("orchestrate_ps_lens_mirror")


def _safety_gate(url: str) -> int | None:
    m = re.search(r"@([^/:?]+)", url)
    host = m.group(1) if m else "<unknown>"
    is_prod = bool(re.search(r"\.rlwy\.net|\.railway\.app", host))
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if not is_local:
        expected = "YES_I_KNOW_THIS_IS_PROD" if is_prod else "YES_I_KNOW_THIS_IS_REMOTE"
        if os.environ.get("SEED_CONFIRM") != expected:
            print(f"ABORTED: re-run with SEED_CONFIRM={expected}", file=sys.stderr)
            return 3
    print(f"[ps-mirror] target={host} (prod={is_prod})")
    return None


def _resolve_ps_tenant_id() -> UUID:
    raw = os.environ.get("PS_TENANT_ID", "").strip()
    if not raw:
        print(
            "ERROR: PS_TENANT_ID env var required. Provision the Project Silk "
            "tenant first (scope 240) and pass its UUIDv4 here.",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        return UUID(raw)
    except ValueError:
        print(f"ERROR: PS_TENANT_ID='{raw}' is not a valid UUID", file=sys.stderr)
        sys.exit(2)


def _verify_ps_tenant_active(engine, ps_tenant: UUID) -> None:
    """Operator-side precondition: the FAS-owned ``tenants`` table must
    have an active row for the PS tenant. (This file is run against prod
    where FAS migrations have run; CIP migrations don't create `tenants`.)"""
    with engine.begin() as c:
        row = c.execute(
            text("SELECT name, type, status FROM tenants WHERE tenant_id = :t"),
            {"t": str(ps_tenant)},
        ).first()
    if not row:
        print(
            f"ERROR: PS_TENANT_ID={ps_tenant} not found in `tenants`. "
            "Provision it first (scope 240).",
            file=sys.stderr,
        )
        sys.exit(2)
    if row.status != "active":
        print(
            f"ERROR: PS tenant exists but status={row.status!r}. Activate first.",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"[ps-mirror] PS tenant verified: {row.name} (type={row.type})")


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(
        f"RUN_BEGAN tag=orchestrate_ps_lens_mirror at="
        f"{datetime.now(UTC).isoformat()}"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Build the Pass 1 lookup + describe Pass 2 without writing.",
    )
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    err = _safety_gate(url)
    if err is not None:
        return err

    ps_tenant = _resolve_ps_tenant_id()

    # Force the psycopg v3 driver — run_sync's _make_lock_holder_engine
    # rebuilds an engine from this URL and would default to psycopg2.
    psycopg_url = (
        url.replace("postgresql://", "postgresql+psycopg://", 1)
           .replace("postgres://", "postgresql+psycopg://", 1)
    )
    engine = create_engine(psycopg_url, pool_pre_ping=True)
    _verify_ps_tenant_active(engine, ps_tenant)

    try:
        summary = run_ps_china_mirror(
            engine=engine,
            ps_tenant_id=ps_tenant,
            dry_run=args.dry_run,
            database_url=psycopg_url,
        )
    finally:
        engine.dispose()

    print(f"SUMMARY {json.dumps(summary, sort_keys=True, default=str)}")
    print(
        f"RUN_ENDED tag=orchestrate_ps_lens_mirror at="
        f"{datetime.now(UTC).isoformat()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
