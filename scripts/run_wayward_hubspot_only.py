# foundry: kind=script domain=client-intelligence-platform
"""Wayward HubSpot-only current-state sync.

Parallel partner to ``run_wayward_zendesk_only.py``. Per the 2026-05-15
connector-resilience commit, HubSpotConnector now handles per-entity
permission errors (Wayward tickets 403) natively — no subclassing needed.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_HUBSPOT_TOKEN=pat-... \\
        WAYWARD_HUBSPOT_PORTAL_ID=242173321 \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python -u scripts/run_wayward_hubspot_only.py
"""
from __future__ import annotations

import os
import re
import sys
from uuid import UUID

from sqlalchemy import create_engine, text

from cip.integration_mesh import run_sync
from cip.integration_mesh.connectors.hubspot import (
    HubSpotConnector,
    HubSpotMapper,
)

TENANT_WAYWARD = UUID("b0000000-0000-0000-0000-000000000001")


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
    print(f"[run_wayward_hubspot_only]{banner}target={host}")
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


def _check_tokens() -> None:
    required = ["WAYWARD_HUBSPOT_TOKEN", "WAYWARD_HUBSPOT_PORTAL_ID"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(
            f"ERROR: required HubSpot env vars not set: {missing}",
            file=sys.stderr,
        )
        sys.exit(2)


def main() -> int:
    print("=" * 70)
    print("Wayward HubSpot-only sync (current-state; full property catalog)")
    print("=" * 70)

    url = _resolve_url()
    host, is_prod = _surface_target(url)
    _confirm_or_abort(host, is_prod)
    _check_tokens()

    if url.startswith("postgresql://"):
        sa_url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        sa_url = url.replace("postgres://", "postgresql+psycopg://", 1)
    else:
        sa_url = url

    engine = create_engine(sa_url, pool_pre_ping=True)

    print(f"\nWayward tenant: {TENANT_WAYWARD}\n")
    print("Sync: HubSpot (companies + contacts + deals; tickets 403'd "
          "for this token, will be skipped per-entity)")
    print("-" * 70)
    connector = HubSpotConnector(tenant_id=TENANT_WAYWARD)
    run_sync(
        connector,
        HubSpotMapper(),
        engine,
        tenant_id=TENANT_WAYWARD,
        database_url=sa_url,
    )
    print("  HubSpot sync completed.")

    print("\nPost-sync row counts:")
    with engine.connect() as conn:
        for tbl in (
            "cip_companies", "cip_contacts", "cip_deals", "cip_tickets",
            "cip_sync_runs",
        ):
            n = conn.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = :t"),
                {"t": str(TENANT_WAYWARD)},
            ).scalar()
            print(f"  {tbl:30s} = {n}")

    print(f"\nUnavailable entities (per-entity isolation): "
          f"{sorted(connector._unavailable_entities)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
