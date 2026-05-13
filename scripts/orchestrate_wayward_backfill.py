# foundry: kind=script domain=client-intelligence-platform
"""Autonomous orchestrator: watches Wayward current-state syncs, runs
backfill when each finishes. Zero Claude-token cost: this script runs
on the operator's machine, makes its own DB + HTTP calls, never invokes
Claude.

Loop logic (poll every POLL_SECONDS):

  1. Query Railway prod for Wayward cip_sync_runs status per connector.
  2. State machine per connector:
       - HubSpot current-state status='success' or 'partial' AND
         hubspot backfill NOT YET STARTED  ->  start hubspot backfill
       - Same shape for Zendesk
       - Each connector's backfill terminates with a status row recorded
         in cip_sync_runs (sync_mode='backfill' marker)
  3. Exit when both connectors have completed backfill (or when forced
     stop via Ctrl-C / SIGTERM).

Log: ``scripts/wayward_backfill_orchestrator.log`` (timestamped lines).

Pre-reqs:
  - Persister extension landed (persist_history_record + run_backfill)
  - HubSpotConnector + ZendeskConnector backfill_history() methods
  - WAYWARD_HUBSPOT_TOKEN + WAYWARD_HUBSPOT_PORTAL_ID +
    WAYWARD_ZENDESK_TOKEN + WAYWARD_ZENDESK_USER +
    WAYWARD_ZENDESK_SUBDOMAIN in env
  - DATABASE_URL pointing at Railway prod (with explicit
    SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD)

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_HUBSPOT_TOKEN=pat-... \\
        WAYWARD_HUBSPOT_PORTAL_ID=242173321 \\
        WAYWARD_ZENDESK_TOKEN=... \\
        WAYWARD_ZENDESK_USER=jake@wayward.com \\
        WAYWARD_ZENDESK_SUBDOMAIN=waywardsupport \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python -u scripts/orchestrate_wayward_backfill.py

(``-u`` flag ensures unbuffered output so log tailing works in real time.)
"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text

from cip.integration_mesh import run_backfill
from cip.integration_mesh.connectors.hubspot import HubSpotConnector
from cip.integration_mesh.connectors.zendesk import ZendeskConnector

TENANT_WAYWARD = UUID("b0000000-0000-0000-0000-000000000001")
POLL_SECONDS = int(os.environ.get("ORCHESTRATOR_POLL_SECONDS", "900"))  # 15 min default
LOG_PATH = Path(__file__).parent / "wayward_backfill_orchestrator.log"


def _log(msg: str) -> None:
    """Print + append to log file. Single source of truth for run history."""
    ts = datetime.now(UTC).isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _resolve_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        _log("ERROR: DATABASE_URL not set")
        sys.exit(2)
    return url


def _surface_target(url: str) -> tuple[str, bool]:
    m = re.search(r"@([^/:?]+)(?::(\d+))?", url)
    host = m.group(1) if m else "<unknown>"
    is_prod = bool(re.search(r"\.rlwy\.net|\.railway\.app", host))
    banner = " *** PRODUCTION TARGET *** " if is_prod else " "
    _log(f"[orchestrate_wayward_backfill]{banner}target={host}")
    return host, is_prod


def _confirm_or_abort(host: str, is_prod: bool) -> None:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return
    confirmation = os.environ.get("SEED_CONFIRM", "")
    expected = "YES_I_KNOW_THIS_IS_PROD" if is_prod else "YES_I_KNOW_THIS_IS_REMOTE"
    if confirmation != expected:
        _log(
            f"ABORTED: target is non-local ({host}). "
            f"Re-run with SEED_CONFIRM={expected}"
        )
        sys.exit(3)


def _check_tokens() -> None:
    required = [
        "WAYWARD_HUBSPOT_TOKEN", "WAYWARD_HUBSPOT_PORTAL_ID",
        "WAYWARD_ZENDESK_TOKEN", "WAYWARD_ZENDESK_USER",
        "WAYWARD_ZENDESK_SUBDOMAIN",
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        _log(f"ERROR: required env vars not set: {missing}")
        sys.exit(2)


def _to_sa_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def _current_state_status(engine: object, connector_id: str) -> str | None:
    """Return status of the most-recent CURRENT-STATE sync (sync_mode in
    {full, incremental, None}) for connector. None = no run yet."""
    with engine.connect() as conn:  # type: ignore[attr-defined]
        row = conn.execute(
            text(
                "SELECT status FROM cip_sync_runs "
                "WHERE tenant_id = :t AND connector_id = :cid "
                "AND (sync_mode IN ('full', 'incremental') OR sync_mode IS NULL) "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {"t": str(TENANT_WAYWARD), "cid": connector_id},
        ).first()
    return row[0] if row else None


def _backfill_done(engine: object, connector_id: str) -> str | None:
    """Return status of the most-recent BACKFILL run for connector.
    None = backfill never run."""
    with engine.connect() as conn:  # type: ignore[attr-defined]
        row = conn.execute(
            text(
                "SELECT status FROM cip_sync_runs "
                "WHERE tenant_id = :t AND connector_id = :cid "
                "AND sync_mode = 'backfill' "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {"t": str(TENANT_WAYWARD), "cid": connector_id},
        ).first()
    return row[0] if row else None


def _record_backfill_run(
    engine: object, connector_id: str, status: str, counters: dict[str, int]
) -> None:
    """Insert a cip_sync_runs row marking the backfill outcome."""
    from uuid import uuid4

    error_detail = None
    if status != "success":
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
                "cid": connector_id,
                "cname": connector_id,
                "bid": str(uuid4()),
                "status": status,
                "n_hist": counters["persisted"],
                "n_skip": counters["skipped_missing_current"],
                "err": error_detail,
            },
        )


def _run_hubspot_backfill(engine: object, db_url: str) -> dict[str, int]:
    _log("Starting HubSpot backfill...")
    connector = HubSpotConnector(tenant_id=TENANT_WAYWARD)
    counters = run_backfill(
        connector,
        engine,  # type: ignore[arg-type]
        tenant_id=TENANT_WAYWARD,
        batch_size=200,
        database_url=db_url,
    )
    _log(f"HubSpot backfill done: {counters}")
    return counters


def _run_zendesk_backfill(engine: object, db_url: str) -> dict[str, int]:
    _log("Starting Zendesk backfill...")
    connector = ZendeskConnector(tenant_id=TENANT_WAYWARD)
    counters = run_backfill(
        connector,
        engine,  # type: ignore[arg-type]
        tenant_id=TENANT_WAYWARD,
        batch_size=200,
        database_url=db_url,
    )
    _log(f"Zendesk backfill done: {counters}")
    return counters


def main() -> int:
    _log("=" * 60)
    _log(f"Wayward backfill orchestrator started (poll every {POLL_SECONDS}s)")
    _log("=" * 60)

    url = _resolve_url()
    host, is_prod = _surface_target(url)
    _confirm_or_abort(host, is_prod)
    _check_tokens()

    sa_url = _to_sa_url(url)
    engine = create_engine(sa_url, pool_pre_ping=True)

    hubspot_done = False
    zendesk_done = False

    while not (hubspot_done and zendesk_done):
        # HubSpot
        if not hubspot_done:
            cs_status = _current_state_status(engine, "hubspot-v1")
            bf_status = _backfill_done(engine, "hubspot-v1")
            if bf_status in {"success", "partial", "failed"}:
                _log(f"HubSpot backfill already recorded: status={bf_status}")
                hubspot_done = True
            elif cs_status in {"success", "partial"}:
                _log(f"HubSpot current-state done (status={cs_status}); triggering backfill")
                try:
                    counters = _run_hubspot_backfill(engine, sa_url)
                    status = "success" if counters["failed"] == 0 else "partial"
                    _record_backfill_run(engine, "hubspot-v1", status, counters)
                    hubspot_done = True
                except Exception as exc:  # noqa: BLE001
                    _log(f"HubSpot backfill EXCEPTION: {type(exc).__name__}: {exc}")
                    _record_backfill_run(
                        engine, "hubspot-v1", "failed",
                        {"persisted": 0, "skipped_missing_current": 0, "failed": 1},
                    )
                    hubspot_done = True
            else:
                _log(f"HubSpot current-state status={cs_status!r}; waiting")

        # Zendesk
        if not zendesk_done:
            cs_status = _current_state_status(engine, "zendesk-v1")
            bf_status = _backfill_done(engine, "zendesk-v1")
            if bf_status in {"success", "partial", "failed"}:
                _log(f"Zendesk backfill already recorded: status={bf_status}")
                zendesk_done = True
            elif cs_status in {"success", "partial"}:
                _log(f"Zendesk current-state done (status={cs_status}); triggering backfill")
                try:
                    counters = _run_zendesk_backfill(engine, sa_url)
                    status = "success" if counters["failed"] == 0 else "partial"
                    _record_backfill_run(engine, "zendesk-v1", status, counters)
                    zendesk_done = True
                except Exception as exc:  # noqa: BLE001
                    _log(f"Zendesk backfill EXCEPTION: {type(exc).__name__}: {exc}")
                    _record_backfill_run(
                        engine, "zendesk-v1", "failed",
                        {"persisted": 0, "skipped_missing_current": 0, "failed": 1},
                    )
                    zendesk_done = True
            else:
                _log(f"Zendesk current-state status={cs_status!r}; waiting")

        if not (hubspot_done and zendesk_done):
            _log(f"Sleeping {POLL_SECONDS}s before next poll")
            time.sleep(POLL_SECONDS)

    _log("=" * 60)
    _log("Wayward backfill orchestrator FINISHED")
    _log("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
