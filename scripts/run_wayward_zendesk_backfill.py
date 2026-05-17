# foundry: kind=script domain=client-intelligence-platform
"""Wayward Zendesk historical backfill — ticket audit log → cip_tickets_history.

Zendesk's only history-bearing entity is tickets: organizations + users
have no first-class audit/history endpoint in v2. The connector iterates
all tickets, calls /api/v2/tickets/{id}/audits.json per ticket, and
emits one HistoricalRecord per audit event with reconstructed ticket
state at that moment (D-159 + scope 218f67a4).

Prerequisite: run_wayward_zendesk_only.py must have completed
successfully so cip_tickets has anchor rows for the history-table FK.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_ZENDESK_TOKEN=... \\
        WAYWARD_ZENDESK_USER=jake@wayward.com \\
        WAYWARD_ZENDESK_SUBDOMAIN=waywardsupport \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python -u scripts/run_wayward_zendesk_backfill.py
"""
from __future__ import annotations

import os
import re
import sys
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text

from cip.integration_mesh import run_backfill
from cip.integration_mesh.connectors.zendesk import ZendeskConnector

from cip.integration_mesh.wayward_constants import (
    ECOMLEVER_TENANT_ID,
    WAYWARD_CLIENT_ID,
    set_wayward_client_id_on_null_rows,
)

TENANT_WAYWARD = ECOMLEVER_TENANT_ID  # Wayward data lives at EcomLever tenant + Wayward client


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
    print(f"[run_wayward_zendesk_backfill]{banner}target={host}")
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
    required = [
        "WAYWARD_ZENDESK_TOKEN", "WAYWARD_ZENDESK_USER",
        "WAYWARD_ZENDESK_SUBDOMAIN",
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(
            f"ERROR: required Zendesk env vars not set: {missing}",
            file=sys.stderr,
        )
        sys.exit(2)


def _record_backfill_run(
    engine: object, status: str, counters: dict[str, int]
) -> None:
    error_detail = (
        '{"backfill_counters": '
        f'{{"persisted": {counters["persisted"]}, '
        f'"skipped_missing_current": {counters["skipped_missing_current"]}, '
        f'"failed": {counters["failed"]}}}}}'
    )
    with engine.begin() as conn:  # type: ignore[attr-defined]
        conn.execute(
            text(
                "INSERT INTO cip_sync_runs ("
                "id, tenant_id, connector_id, connector_name, batch_id, "
                "sync_mode, status, "
                "rows_ingested, rows_history, rows_created, rows_updated, rows_skipped, "
                "started_at, ended_at, error_detail) "
                "VALUES ("
                ":id, :tid, :cid, :cname, :bid, "
                "'backfill', :status, "
                "0, :n_hist, 0, 0, :n_skip, "
                "NOW(), NOW(), CAST(:err AS jsonb))"
            ),
            {
                "id": str(uuid4()),
                "tid": str(TENANT_WAYWARD),
                "cid": "zendesk-v1",
                "cname": "ZendeskConnector",
                "bid": str(uuid4()),
                "status": status,
                "n_hist": counters["persisted"],
                "n_skip": counters["skipped_missing_current"],
                "err": error_detail,
            },
        )


def main() -> int:
    print("=" * 70)
    print("Wayward Zendesk historical backfill (ticket audit log)")
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
    started = datetime.now(UTC)
    print(f"\nStarted at {started.isoformat()}")

    connector = ZendeskConnector(tenant_id=TENANT_WAYWARD)
    try:
        counters = run_backfill(
            connector,
            engine,
            tenant_id=TENANT_WAYWARD,
            batch_size=200,
            database_url=sa_url,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"\nFATAL during backfill: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        _record_backfill_run(
            engine, "failed",
            {"persisted": 0, "skipped_missing_current": 0, "failed": 1},
        )
        return 1

    status = "success" if counters["failed"] == 0 else "partial"
    print(f"\nBackfill done. Counters: {counters}")
    _record_backfill_run(engine, status, counters)

    print("\nPost-backfill row counts:")
    with engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT COUNT(*) FROM cip_tickets_history WHERE tenant_id = :t"
            ),
            {"t": str(TENANT_WAYWARD)},
        ).scalar()
        print(f"  cip_tickets_history = {n}")

    elapsed = (datetime.now(UTC) - started).total_seconds()
    print(f"\nElapsed: {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
