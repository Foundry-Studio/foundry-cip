# foundry: kind=script domain=client-intelligence-platform
"""Backfill company_source_ids on cip_engagements rows.

Companies association was dropped in the first Block 3 backfill due
to the `rstrip("s")` plural→singular bug (companies → companie instead
of company). Bug fixed in cip/integration_mesh/connectors/hubspot/
connector.py 2026-05-17; this script repairs the existing rows without
re-running the full 23-minute backfill.

Idempotent: re-running is safe — UPDATE-by-source_id will just refresh
the company_source_ids array.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_HUBSPOT_TOKEN=... \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/fix_engagement_companies_associations.py
"""
from __future__ import annotations

import os
import re
import sys
import time

from sqlalchemy import create_engine, text

from cip.integration_mesh.connectors.hubspot import HubSpotConnector
from cip.integration_mesh.wayward_constants import ECOMLEVER_TENANT_ID


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    host_match = re.search(r"@([^/:?]+)", url)
    host = host_match.group(1) if host_match else "<unknown>"
    is_prod = bool(re.search(r"\.rlwy\.net|\.railway\.app", host))
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if not is_local:
        expected = "YES_I_KNOW_THIS_IS_PROD" if is_prod else "YES_I_KNOW_THIS_IS_REMOTE"
        if os.environ.get("SEED_CONFIRM") != expected:
            print(f"ABORTED: re-run with SEED_CONFIRM={expected}", file=sys.stderr)
            return 3
    banner = " *** PRODUCTION TARGET *** " if is_prod else " "
    print(f"[fix-companies]{banner}target={host}")

    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)

    conn = HubSpotConnector(tenant_id=ECOMLEVER_TENANT_ID)
    conn.authenticate()
    print(f"[fix-companies] HubSpot auth ok portal={conn.portal_id or '?'}")

    # Map (engagement_type → hubspot endpoint path)
    type_to_path = {"note": "notes", "meeting": "meetings", "task": "tasks"}
    BATCH = 100
    total_updated = 0
    start_ts = time.monotonic()

    for et, path in type_to_path.items():
        # Pull all source_ids for this engagement type
        with engine.connect() as c:
            c.execute(text(f"SELECT set_config('app.current_tenant','{ECOMLEVER_TENANT_ID}',true)"))
            rows = c.execute(
                text(
                    "SELECT source_id FROM cip_engagements "
                    "WHERE tenant_id = :t AND engagement_type = :e "
                    "ORDER BY source_id::bigint"
                ),
                {"t": str(ECOMLEVER_TENANT_ID), "e": et},
            ).all()
        ids = [r[0] for r in rows]
        print(f"\n[fix-companies] {et}: {len(ids)} rows to check")

        for i in range(0, len(ids), BATCH):
            batch = ids[i:i + BATCH]
            # Fetch companies associations for this batch via v4 endpoint
            try:
                resp = conn._http.post(
                    f"/crm/v4/associations/{path}/companies/batch/read",
                    json_body={"inputs": [{"id": x} for x in batch]},
                )
            except Exception as e:  # noqa: BLE001
                print(f"  ERROR fetching companies for {et} batch {i}: {e}")
                continue

            # Build {source_id: [company_id, ...]}
            assoc_map: dict[str, list[str]] = {}
            for row in resp.get("results", []):
                from_obj = row.get("from") or {}
                fid = str(from_obj.get("id", ""))
                if not fid:
                    continue
                to_list = row.get("to") or []
                co_ids = [
                    str(t.get("toObjectId"))
                    for t in to_list
                    if isinstance(t, dict) and t.get("toObjectId") is not None
                ]
                if co_ids:
                    assoc_map[fid] = co_ids

            if not assoc_map:
                continue

            # UPDATE in a single round-trip
            with engine.begin() as c:
                c.execute(text(f"SELECT set_config('app.current_tenant','{ECOMLEVER_TENANT_ID}',true)"))
                for sid, co_ids in assoc_map.items():
                    r = c.execute(
                        text(
                            "UPDATE cip_engagements "
                            "SET company_source_ids = :ids "
                            "WHERE tenant_id = :t AND source_connector = 'hubspot-v1' "
                            "  AND engagement_type = :e AND source_id = :s"
                        ),
                        {
                            "ids": co_ids,
                            "t": str(ECOMLEVER_TENANT_ID),
                            "e": et,
                            "s": sid,
                        },
                    )
                    total_updated += r.rowcount or 0

            elapsed = time.monotonic() - start_ts
            done = i + len(batch)
            print(
                f"  {et}: {done}/{len(ids)} | updated_so_far={total_updated} "
                f"| elapsed={elapsed/60:.1f}m"
            )

    print(f"\n[fix-companies] DONE. company_source_ids set on {total_updated} rows")
    # Final coverage check
    with engine.connect() as c:
        c.execute(text(f"SELECT set_config('app.current_tenant','{ECOMLEVER_TENANT_ID}',true)"))
        n = c.execute(
            text(
                "SELECT COUNT(*) FROM cip_engagements "
                "WHERE tenant_id = :t AND array_length(company_source_ids, 1) > 0"
            ),
            {"t": str(ECOMLEVER_TENANT_ID)},
        ).scalar()
        print(f"[fix-companies] Final rows with company associations: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
