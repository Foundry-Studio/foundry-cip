# foundry: kind=script domain=client-intelligence-platform
"""Wayward HubSpot historical backfill — companies + contacts + deals only.

Why this exists (2026-05-15): on 2026-05-14 the combined Wayward current-state
sync died on HubSpot tickets with a 403 ("The scope needed for this API call
isn't available for public use") AFTER successfully ingesting 117,000 rows of
companies/contacts/deals. The autonomous backfill orchestrator was gated on
``cs_status in {'success', 'partial'}`` and saw ``failed``, so backfill never
fired. Tim's "I need the historical data, that was very important" → this
tactical script pulls history for the 3 entities that DID succeed in
current-state and skips tickets (whose scope is genuinely unavailable on
the Wayward token).

This is a workaround until PM scope ``d3311846`` lands (partial-success
connector orchestration). When that ships, the production orchestrator will
do this automatically and this script can be deleted.

Approach:
  - Subclass HubSpotConnector and override ``_OBJECT_TYPES`` at the
    class-method level by filtering out tickets in ``backfill_history``.
    Minimal blast radius — no edits to shared connector code.
  - Reuse run_backfill() from cip.integration_mesh (identical persister
    contract: looks up cip_<table>.id by source_id and writes to
    cip_<table>_history with valid_from/valid_to SCD-2 columns).
  - Records a cip_sync_runs row with sync_mode='backfill' status='success'
    (or 'partial' if any records were skipped because their current-state
    row went missing).

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_HUBSPOT_TOKEN=pat-... \\
        WAYWARD_HUBSPOT_PORTAL_ID=242173321 \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python -u scripts/run_wayward_hubspot_backfill_no_tickets.py
"""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text

from cip.integration_mesh import run_backfill
from cip.integration_mesh.base import HistoricalRecord
from cip.integration_mesh.connectors.hubspot import HubSpotConnector
from cip.integration_mesh.connectors.hubspot.connector import _OBJECT_TYPES

TENANT_WAYWARD = UUID("b0000000-0000-0000-0000-000000000001")
SKIP = {"tickets"}  # HubSpot scope unavailable to Wayward token


class HubSpotConnectorNoTickets(HubSpotConnector):
    """Override backfill_history to skip tickets entity.

    Doesn't touch stream_records (current-state) because current-state
    has already succeeded for companies/contacts/deals on Railway prod;
    this connector instance is for backfill only.
    """

    def backfill_history(
        self, tenant_id: UUID
    ) -> Iterator[HistoricalRecord]:
        if not getattr(self, "_authenticated", False):
            self.authenticate()

        filtered = tuple(
            (path, rt) for path, rt in _OBJECT_TYPES if path not in SKIP
        )

        for hubspot_path, record_type in filtered:
            from cip.integration_mesh.connectors.hubspot.connector import (
                _CIP_TABLE_BY_TYPE,
                _DEFAULT_PROPERTIES,
            )
            target_table = _CIP_TABLE_BY_TYPE[record_type]
            properties = _DEFAULT_PROPERTIES.get(hubspot_path, ())
            properties_csv = ",".join(properties)
            after: str | None = None
            while True:
                params: dict[str, str | int] = {
                    "limit": 50,  # HubSpot caps propertiesWithHistory at 50
                    "properties": properties_csv,
                    "propertiesWithHistory": properties_csv,
                }
                if after:
                    params["after"] = after
                page = self._http.get(
                    f"/crm/v3/objects/{hubspot_path}", params=params
                )
                for obj in page.get("results", []):
                    yield from self._historical_records_for_obj(
                        obj, record_type, target_table
                    )
                paging = page.get("paging", {})
                nxt = (
                    paging.get("next", {}) if isinstance(paging, dict) else {}
                )
                after = nxt.get("after") if isinstance(nxt, dict) else None
                if not after:
                    break


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
    print(f"[hubspot_backfill_no_tickets]{banner}target={host}")
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


def _record_backfill_run(
    engine: object, status: str, counters: dict[str, int]
) -> None:
    error_detail = None
    if status != "success":
        error_detail = (
            '{"backfill_counters": '
            f'{{"persisted": {counters["persisted"]}, '
            f'"skipped_missing_current": {counters["skipped_missing_current"]}, '
            f'"failed": {counters["failed"]}, '
            f'"entities_skipped": ["tickets (403 scope unavailable)"]}}}}'
        )
    else:
        error_detail = (
            '{"backfill_counters": '
            f'{{"persisted": {counters["persisted"]}, '
            f'"skipped_missing_current": {counters["skipped_missing_current"]}, '
            f'"failed": {counters["failed"]}, '
            f'"entities_skipped": ["tickets (403 scope unavailable)"]}}}}'
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
                "cid": "hubspot-v1",
                "cname": "HubSpotConnectorNoTickets",
                "bid": str(uuid4()),
                "status": status,
                "n_hist": counters["persisted"],
                "n_skip": counters["skipped_missing_current"],
                "err": error_detail,
            },
        )


def main() -> int:
    print("=" * 72)
    print("Wayward HubSpot historical backfill (companies+contacts+deals only)")
    print("=" * 72)

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

    connector = HubSpotConnectorNoTickets(tenant_id=TENANT_WAYWARD)
    try:
        counters = run_backfill(
            connector,
            engine,  # type: ignore[arg-type]
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

    print("\nPost-backfill row counts (per-tenant scope):")
    with engine.connect() as conn:
        for tbl in (
            "cip_companies_history",
            "cip_contacts_history",
            "cip_deals_history",
            "cip_tickets_history",
        ):
            n = conn.execute(
                text(
                    f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = :t"
                ),
                {"t": str(TENANT_WAYWARD)},
            ).scalar()
            print(f"  {tbl:30s} = {n}")

    elapsed = (datetime.now(UTC) - started).total_seconds()
    print(f"\nElapsed: {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
