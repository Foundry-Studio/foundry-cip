# foundry: kind=script domain=client-intelligence-platform
"""Wayward Zendesk-only initial sync.

Why this exists: on 2026-05-14 the combined HubSpot+Zendesk script
``run_wayward_initial_sync.py`` died on HubSpot tickets with a 403
(scope unavailable for public use), which cascade-blocked Zendesk
because the script runs HubSpot then Zendesk sequentially. CIP scope
``d3311846`` tracks the long-term fix (partial-success connector
orchestration). This script is the tactical workaround: ingest Zendesk
on its own, no dependency on the HubSpot half.

Mirrors ``run_wayward_initial_sync.py`` discipline:
  - Requires SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD for non-localhost.
  - Prints target host with PRODUCTION banner.
  - Reads DATABASE_URL + WAYWARD_ZENDESK_* env vars only.
  - Current-state mode (no historical backfill).

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_ZENDESK_TOKEN=... \\
        WAYWARD_ZENDESK_USER=jake@wayward.com \\
        WAYWARD_ZENDESK_SUBDOMAIN=waywardsupport \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/run_wayward_zendesk_only.py
"""
from __future__ import annotations

import os
import re
import sys
from uuid import UUID

from sqlalchemy import create_engine, text

from cip.integration_mesh import run_sync
from cip.integration_mesh.connectors.zendesk import (
    ZendeskConnector,
    ZendeskMapper,
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
    port = (m.group(2) if m else None) or "5432"
    is_prod = bool(re.search(r"\.rlwy\.net|\.railway\.app", host))
    banner = " *** PRODUCTION TARGET *** " if is_prod else " "
    print(f"[run_wayward_zendesk_only]{banner}target={host}:{port}")
    return host, is_prod


def _confirm_or_abort(host: str, is_prod: bool) -> None:
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if is_local:
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
    required = [
        "WAYWARD_ZENDESK_TOKEN",
        "WAYWARD_ZENDESK_USER",
        "WAYWARD_ZENDESK_SUBDOMAIN",
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(
            f"ERROR: required Wayward Zendesk env vars not set: {missing}",
            file=sys.stderr,
        )
        sys.exit(2)


def _row_counts(engine: object, tenant_id: UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.connect() as conn:  # type: ignore[attr-defined]
        for tbl in (
            "cip_companies",
            "cip_contacts",
            "cip_tickets",
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
                counts[tbl] = -1
                print(f"  WARN: could not probe {tbl}: {e}")
    return counts


def main() -> int:
    print("=" * 70)
    print("Wayward Zendesk-only sync (orgs + users + tickets, current state)")
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

    print(f"\nWayward tenant: {TENANT_WAYWARD}")
    print("\nPre-sync row counts:")
    pre = _row_counts(engine, TENANT_WAYWARD)
    for tbl, n in pre.items():
        print(f"  {tbl:30s} = {n}")

    print("\n" + "-" * 70)
    print("Zendesk sync (organizations + users + tickets)")
    print("-" * 70)
    zd_connector = ZendeskConnector(tenant_id=TENANT_WAYWARD)
    run_sync(
        zd_connector,
        ZendeskMapper(),
        engine,
        tenant_id=TENANT_WAYWARD,
        database_url=sa_url,
    )
    print("  Zendesk sync completed.")

    print("\nPost-sync row counts:")
    post = _row_counts(engine, TENANT_WAYWARD)
    for tbl, n in post.items():
        delta = "" if pre.get(tbl, 0) == n else f"  (+{n - pre.get(tbl, 0)})"
        print(f"  {tbl:30s} = {n}{delta}")

    print("\nPer-connector breakdown in cip_companies:")
    with engine.connect() as conn:
        for row in conn.execute(
            text(
                "SELECT source_connector, COUNT(*) AS n "
                "FROM cip_companies WHERE tenant_id = :t "
                "GROUP BY source_connector ORDER BY source_connector"
            ),
            {"t": str(TENANT_WAYWARD)},
        ).all():
            print(f"  {row[0]:30s} = {row[1]}")

    print("\nWayward Zendesk sync runs:")
    with engine.connect() as conn:
        for row in conn.execute(
            text(
                "SELECT connector_name, status, rows_ingested, rows_created, "
                "rows_updated, rows_skipped, started_at, ended_at "
                "FROM cip_sync_runs WHERE tenant_id = :t "
                "AND connector_name = 'ZendeskConnector' "
                "ORDER BY started_at"
            ),
            {"t": str(TENANT_WAYWARD)},
        ).all():
            print(
                f"  {row[0]:20s} status={row[1]:10s} "
                f"ingested={row[2]} created={row[3]} updated={row[4]} "
                f"skipped={row[5]} started={row[6]} ended={row[7]}"
            )

    if post.get("cip_tickets", 0) <= 0:
        print(
            "\nWARN: cip_tickets still 0 after Zendesk sync — inspect logs.",
            file=sys.stderr,
        )

    print("\nOK - Wayward Zendesk sync done for tenant", TENANT_WAYWARD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
