# foundry: kind=script domain=client-intelligence-platform
"""Wayward HubSpot Engagements backfill — notes + meetings + tasks.

Per PM scope 9952dd26 + PM decision 9cd16db1 (Firefly via HubSpot: 0
calls in Wayward portal, so the Firefly transcript investigation came
back negative — only notes/meetings/tasks have content). Calls and
emails skipped: calls have 0 records, emails are 403-blocked.

Iterates each engagement entity type via the extended HubSpotConnector
(stream_engagements method), maps to cip_engagements with discriminator,
persists in per-batch SAVEPOINTs. Idempotent via
UNIQUE(tenant_id, client_id, source_connector, source_id).

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_HUBSPOT_TOKEN=... \\
        WAYWARD_HUBSPOT_PORTAL_ID=242173321 \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/run_wayward_hubspot_engagements_backfill.py
"""
from __future__ import annotations

import os
import re
import sys
import time
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from cip.integration_mesh.connectors.hubspot import (
    HubSpotConnector,
    HubSpotMapper,
)
from cip.integration_mesh.persister import CIPRowPersister
from cip.integration_mesh.scd_differ import SCDDiffer
from cip.integration_mesh.tenant_context import apply_tenant_context
from cip.integration_mesh.wayward_constants import (
    ECOMLEVER_TENANT_ID,
    WAYWARD_CLIENT_ID,
    set_wayward_client_id_on_null_rows,
)

# Per-kind page size — HubSpot caps at 100. Smaller pages = more
# frequent commit checkpoints.
BATCH_SIZE = 100
COMMIT_EVERY = 100  # records


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
    print(f"[engagements-backfill]{banner}target={host}")

    if not os.environ.get("WAYWARD_HUBSPOT_TOKEN"):
        print("ERROR: WAYWARD_HUBSPOT_TOKEN not set", file=sys.stderr)
        return 2

    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)

    conn = HubSpotConnector(tenant_id=ECOMLEVER_TENANT_ID)
    conn.authenticate()
    print(f"[engagements-backfill] HubSpot authenticated portal={conn.portal_id or '?'}")

    mapper = HubSpotMapper()
    batch_id = uuid4()
    differ = SCDDiffer()

    totals = {
        "engagement_note": {"created": 0, "updated": 0, "skipped": 0, "errors": 0, "seen": 0},
        "engagement_meeting": {"created": 0, "updated": 0, "skipped": 0, "errors": 0, "seen": 0},
        "engagement_task": {"created": 0, "updated": 0, "skipped": 0, "errors": 0, "seen": 0},
    }
    start_ts = time.monotonic()

    # Open one Session for the whole entity stream; commit every N records
    db = Session(engine)
    apply_tenant_context(db, ECOMLEVER_TENANT_ID)
    persister = CIPRowPersister(db, differ)
    pending = 0

    try:
        for rec in conn.stream_engagements(batch_size=BATCH_SIZE):
            kind = rec.get("__cip_kind__")
            if not isinstance(kind, str) or kind not in totals:
                continue
            totals[kind]["seen"] += 1
            try:
                rows = list(mapper.map(rec))
                for row in rows:
                    res = persister.persist(
                        row,
                        tenant_id=ECOMLEVER_TENANT_ID,
                        connector_id=conn.connector_id,
                        batch_id=batch_id,
                    )
                    totals[kind]["created"] += res.created
                    totals[kind]["updated"] += res.updated
                    totals[kind]["skipped"] += res.skipped
                pending += 1
            except Exception as e:  # noqa: BLE001
                totals[kind]["errors"] += 1
                # Rollback the session to clear failed-state, then
                # re-establish context for next batch
                db.rollback()
                apply_tenant_context(db, ECOMLEVER_TENANT_ID)
                if totals[kind]["errors"] <= 3:
                    print(f"  ERROR on {kind} src={rec.get('source_id')}: {type(e).__name__}: {e}"[:200])

            if pending >= COMMIT_EVERY:
                db.commit()
                # Progress
                elapsed = time.monotonic() - start_ts
                grand_total = sum(t["seen"] for t in totals.values())
                grand_created = sum(t["created"] for t in totals.values())
                rate = grand_total / max(elapsed, 0.001)
                per_kind = " ".join(
                    f"{k.replace('engagement_','')}={v['created']}"
                    for k, v in totals.items()
                )
                print(
                    f"[engagements-backfill] elapsed={elapsed/60:.1f}m total={grand_total} created={grand_created} | {per_kind} | {rate:.1f} rec/s"
                )
                pending = 0

        # Final commit
        if pending > 0:
            db.commit()
    finally:
        db.close()

    # client_id backfill
    updated_map = set_wayward_client_id_on_null_rows(engine)
    ce_updated = updated_map.get("cip_engagements", 0)
    print(f"[engagements-backfill] client_id backfilled on {ce_updated} engagement rows")

    elapsed = time.monotonic() - start_ts
    print(f"\n[engagements-backfill] DONE in {elapsed/60:.1f}m")
    for kind, t in totals.items():
        print(f"  {kind:24s} seen={t['seen']:>5d} created={t['created']:>5d} updated={t['updated']:>4d} skipped={t['skipped']:>4d} errors={t['errors']}")

    # Final DB counts
    with Session(engine) as db:
        apply_tenant_context(db, ECOMLEVER_TENANT_ID)
        for et in ("note", "meeting", "task"):
            n = db.execute(
                text("SELECT COUNT(*) FROM cip_engagements WHERE tenant_id=:t AND engagement_type=:e"),
                {"t": str(ECOMLEVER_TENANT_ID), "e": et},
            ).scalar()
            print(f"  Final cip_engagements (type={et}): {n}")
        # Association coverage
        for col, label in [
            ("contact_source_ids", "contacts"),
            ("deal_source_ids", "deals"),
            ("company_source_ids", "companies"),
            ("ticket_source_ids", "tickets"),
        ]:
            n = db.execute(
                text(f"SELECT COUNT(*) FROM cip_engagements WHERE tenant_id=:t AND array_length({col}, 1) > 0"),
                {"t": str(ECOMLEVER_TENANT_ID)},
            ).scalar()
            print(f"  Rows with {label} associations: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
