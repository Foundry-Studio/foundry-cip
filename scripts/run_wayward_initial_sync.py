# foundry: kind=script domain=client-intelligence-platform
"""Wayward initial sync - HubSpot + Zendesk current-state ingest.

Per the Wayward Phase 2 plan + D-159 contract: this script runs the
INITIAL sync for Wayward (tenant_id b0000000-...0001) against Railway
prod, in **current-state-only mode** (``backfill_history=False``).

Why backfill_history=False here? PM scope 218f67a4 documents the
framework gap: the persister + orchestrator don't yet recognize
backfill markers. The connector code is ready and gates itself by
raising NotImplementedError if backfill is invoked. This script runs
the half of D-159 that DOES work today - current-state ingest - and
the historical-backfill half follows once the persister extension
lands.

Deliberate-use script. Reads DATABASE_URL + WAYWARD_*_TOKEN env vars,
prints the resolved host with a production-target warning, and
requires SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD for any non-localhost
target. Mirrors seed_railway_prod_fixture.py discipline.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_HUBSPOT_TOKEN=pat-... \\
        WAYWARD_HUBSPOT_PORTAL_ID=242173321 \\
        WAYWARD_ZENDESK_TOKEN=... \\
        WAYWARD_ZENDESK_USER=jake@wayward.com \\
        WAYWARD_ZENDESK_SUBDOMAIN=waywardsupport \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/run_wayward_initial_sync.py

After a successful run:
  - cip_companies for tenant b0000000-...0001 has HubSpot companies +
    Zendesk organizations (two source_connectors)
  - cip_contacts has HubSpot contacts + Zendesk users
  - cip_deals has HubSpot deals only
  - cip_tickets has HubSpot tickets + Zendesk tickets
  - cip_sync_runs has 2 rows (one per connector), status='success'
  - cip_*_history tables remain 0 rows (no backfill on initial; SCD-2
    differ only writes history on detected changes)
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
from cip.integration_mesh.connectors.zendesk import (
    ZendeskConnector,
    ZendeskMapper,
)

from cip.integration_mesh.wayward_constants import (
    ECOMLEVER_TENANT_ID,
    WAYWARD_CLIENT_ID,
    set_wayward_client_id_on_null_rows,
)

# Wayward data lives at (EcomLever tenant, Wayward client). See
# `cip/integration_mesh/wayward_constants.py` for the canonical UUIDs
# and `docs/ONBOARDING-A-NEW-TENANT.md` Phase 0 for the rule against
# placeholder UUIDs. `TENANT_WAYWARD` is the legacy local name; resolves
# to EcomLever's tenant_id (the venture).
TENANT_WAYWARD = ECOMLEVER_TENANT_ID


def _resolve_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print(
            "ERROR: DATABASE_URL not set.",
            file=sys.stderr,
        )
        sys.exit(2)
    return url


def _surface_target(url: str) -> tuple[str, bool]:
    m = re.search(r"@([^/:?]+)(?::(\d+))?", url)
    host = m.group(1) if m else "<unknown>"
    port = (m.group(2) if m else None) or "5432"
    is_prod = bool(re.search(r"\.rlwy\.net|\.railway\.app", host))
    banner = " *** PRODUCTION TARGET *** " if is_prod else " "
    print(f"[run_wayward_initial_sync]{banner}target={host}:{port}")
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
    """Verify all required Wayward env vars are present before starting."""
    required = [
        "WAYWARD_HUBSPOT_TOKEN",
        "WAYWARD_HUBSPOT_PORTAL_ID",
        "WAYWARD_ZENDESK_TOKEN",
        "WAYWARD_ZENDESK_USER",
        "WAYWARD_ZENDESK_SUBDOMAIN",
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(
            f"ERROR: required Wayward env vars not set: {missing}",
            file=sys.stderr,
        )
        sys.exit(2)


def _row_counts(engine: object, tenant_id: UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.connect() as conn:  # type: ignore[attr-defined]
        for tbl in (
            "cip_companies",
            "cip_contacts",
            "cip_deals",
            "cip_tickets",
            "cip_files",
            "cip_sync_runs",
            "cip_companies_history",
            "cip_tickets_history",
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
    print("Wayward initial sync - HubSpot + Zendesk (current-state only)")
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
    print("\nPre-sync row counts (per-tenant scope):")
    pre = _row_counts(engine, TENANT_WAYWARD)
    for tbl, n in pre.items():
        print(f"  {tbl:30s} = {n}")

    # -- HubSpot sync --------------------------------------------------
    print("\n" + "-" * 70)
    print("Sync 1/2: HubSpot (companies + contacts + deals + tickets)")
    print("-" * 70)
    hs_connector = HubSpotConnector(tenant_id=TENANT_WAYWARD)
    run_sync(
        hs_connector,
        HubSpotMapper(),
        engine,
        tenant_id=TENANT_WAYWARD,
        database_url=sa_url,
    )
    print("  HubSpot sync completed.")

    # -- Zendesk sync --------------------------------------------------
    print("\n" + "-" * 70)
    print("Sync 2/2: Zendesk (organizations + users + tickets)")
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

    # -- Verify --------------------------------------------------------
    print("\nPost-sync row counts:")
    post = _row_counts(engine, TENANT_WAYWARD)
    for tbl, n in post.items():
        delta = "" if pre.get(tbl, 0) == n else f"  (+{n - pre.get(tbl, 0)})"
        print(f"  {tbl:30s} = {n}{delta}")

    # Per-connector breakdown
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

    print("\nPer-connector cip_sync_runs:")
    with engine.connect() as conn:
        for row in conn.execute(
            text(
                "SELECT source_connector, status, rows_created, rows_updated, "
                "rows_skipped FROM cip_sync_runs WHERE tenant_id = :t "
                "ORDER BY started_at"
            ),
            {"t": str(TENANT_WAYWARD)},
        ).all():
            print(
                f"  {row[0]:25s} status={row[1]:10s} "
                f"created={row[2]} updated={row[3]} skipped={row[4]}"
            )

    failures: list[str] = []
    if post.get("cip_companies", 0) <= 0:
        failures.append("cip_companies: expected >0, got 0")
    if post.get("cip_sync_runs", 0) < 2:
        failures.append(
            f"cip_sync_runs: expected >=2 (one per connector), got "
            f"{post.get('cip_sync_runs', 0)}"
        )

    if failures:
        print(
            "\nFAILED:\n  " + "\n  ".join(failures),
            file=sys.stderr,
        )
        return 1

    print(
        "\nOK - Wayward initial sync verified for tenant",
        TENANT_WAYWARD,
    )
    print("\nNext step: Tim switches Metabase Init SQL to Wayward UUID:")
    print(
        f"  SET app.current_tenant = '{TENANT_WAYWARD}';"
    )
    print(
        "Then existing lens_* views (lens_all_companies, "
        "lens_companies_history) show Wayward data via cip_metabase_role."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
