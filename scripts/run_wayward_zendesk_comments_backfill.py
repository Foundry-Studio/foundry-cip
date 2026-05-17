# foundry: kind=script domain=client-intelligence-platform
"""Wayward Zendesk ticket-comments backfill — targeted, no full re-sync.

Per PM scope 28739b6e (Zendesk Ticket Comments + Attachments).

Why this exists vs running the full ``run_wayward_zendesk_only.py``:
the full sync re-streams 119K companies + 68K users + 2,890 tickets
(~2h10min as of last full run). Comments are the only new data Block 2
needs; running the full sync to get them is wasteful. This script
iterates cip_tickets directly, fetches comments per ticket via the
ZendeskConnector's _stream_ticket_comments method, and persists them
in batches.

Idempotent: UNIQUE(tenant_id, client_id, source_connector, source_id)
on cip_ticket_comments means re-runs no-op for unchanged rows; differ
detects unchanged comments and skips.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_ZENDESK_TOKEN=... \\
        WAYWARD_ZENDESK_USER=jake@wayward.com \\
        WAYWARD_ZENDESK_SUBDOMAIN=waywardsupport \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/run_wayward_zendesk_comments_backfill.py
"""
from __future__ import annotations

import os
import sys
import time
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from cip.integration_mesh.connectors.zendesk import (
    ZendeskConnector,
    ZendeskMapper,
)
from cip.integration_mesh.persister import CIPRowPersister
from cip.integration_mesh.scd_differ import SCDDiffer
from cip.integration_mesh.tenant_context import apply_tenant_context
from cip.integration_mesh.wayward_constants import (
    ECOMLEVER_TENANT_ID,
    WAYWARD_CLIENT_ID,
    set_wayward_client_id_on_null_rows,
)


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2

    # Safety gate
    import re as _re
    host_match = _re.search(r"@([^/:?]+)", url)
    host = host_match.group(1) if host_match else "<unknown>"
    is_prod = bool(_re.search(r"\.rlwy\.net|\.railway\.app", host))
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if not is_local:
        expected = "YES_I_KNOW_THIS_IS_PROD" if is_prod else "YES_I_KNOW_THIS_IS_REMOTE"
        if os.environ.get("SEED_CONFIRM") != expected:
            print(
                f"\nABORTED: target is non-local ({host}). Re-run with:\n"
                f"  SEED_CONFIRM={expected}",
                file=sys.stderr,
            )
            return 3
    banner = " *** PRODUCTION TARGET *** " if is_prod else " "
    print(f"[comments-backfill]{banner}target={host}")

    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)

    conn = ZendeskConnector(tenant_id=ECOMLEVER_TENANT_ID)
    conn.authenticate()
    print(f"[comments-backfill] Authenticated as {conn.user} @ {conn.subdomain}")

    # Get all Wayward ticket source_ids ordered for deterministic resumption
    with Session(engine) as db:
        apply_tenant_context(db, ECOMLEVER_TENANT_ID)
        ticket_rows = db.execute(
            text(
                "SELECT source_id FROM cip_tickets "
                "WHERE tenant_id = :t AND source_connector = 'zendesk-v1' "
                "ORDER BY source_id::bigint ASC"
            ),
            {"t": str(ECOMLEVER_TENANT_ID)},
        ).all()
    ticket_ids = [r[0] for r in ticket_rows]
    print(f"[comments-backfill] Found {len(ticket_ids)} Wayward Zendesk tickets")

    start_ts = time.monotonic()
    batch_id = uuid4()
    differ = SCDDiffer()
    mapper = ZendeskMapper()

    total_created = total_updated = total_skipped = 0
    total_comments_seen = 0
    tickets_with_errors: list[tuple[str, str]] = []

    # Process in batches of 50 tickets per DB session to keep transactions
    # small and limit memory.
    BATCH_TICKETS = 50

    for batch_start in range(0, len(ticket_ids), BATCH_TICKETS):
        batch = ticket_ids[batch_start : batch_start + BATCH_TICKETS]
        with Session(engine) as db:
            apply_tenant_context(db, ECOMLEVER_TENANT_ID)
            persister = CIPRowPersister(db, differ)
            for tid in batch:
                try:
                    for rec in conn._stream_ticket_comments(
                        ticket_source_id=tid
                    ):
                        total_comments_seen += 1
                        rows = list(mapper.map(rec))
                        for row in rows:
                            res = persister.persist(
                                row,
                                tenant_id=ECOMLEVER_TENANT_ID,
                                connector_id=conn.connector_id,
                                batch_id=batch_id,
                            )
                            total_created += res.created
                            total_updated += res.updated
                            total_skipped += res.skipped
                except Exception as e:  # noqa: BLE001
                    tickets_with_errors.append(
                        (tid, f"{type(e).__name__}: {e}")
                    )
            db.commit()
        # Progress every batch
        elapsed = time.monotonic() - start_ts
        done = min(batch_start + BATCH_TICKETS, len(ticket_ids))
        pct = 100.0 * done / max(1, len(ticket_ids))
        rate = done / max(elapsed, 0.001)
        eta = (len(ticket_ids) - done) / max(rate, 0.001)
        print(
            f"[comments-backfill] {done:>4d}/{len(ticket_ids)} tickets "
            f"({pct:5.1f}%) | comments seen={total_comments_seen} "
            f"created={total_created} updated={total_updated} skipped={total_skipped} "
            f"| {rate:.2f} tix/s ETA {eta/60:.1f}m"
        )

    # Backfill client_id on any rows that landed NULL
    updated_map = set_wayward_client_id_on_null_rows(engine)
    cc_updated = updated_map.get("cip_ticket_comments", 0)
    print(f"[comments-backfill] client_id backfilled on {cc_updated} comment rows")

    # Final row count
    with Session(engine) as db:
        apply_tenant_context(db, ECOMLEVER_TENANT_ID)
        final_count = db.execute(
            text(
                "SELECT COUNT(*) FROM cip_ticket_comments "
                "WHERE tenant_id = :t AND source_connector = 'zendesk-v1'"
            ),
            {"t": str(ECOMLEVER_TENANT_ID)},
        ).scalar()
        public_count = db.execute(
            text(
                "SELECT COUNT(*) FROM cip_ticket_comments "
                "WHERE tenant_id = :t AND is_public = true"
            ),
            {"t": str(ECOMLEVER_TENANT_ID)},
        ).scalar()
        with_attach_count = db.execute(
            text(
                "SELECT COUNT(*) FROM cip_ticket_comments "
                "WHERE tenant_id = :t AND attachments_count > 0"
            ),
            {"t": str(ECOMLEVER_TENANT_ID)},
        ).scalar()

    elapsed = time.monotonic() - start_ts
    print(f"\n[comments-backfill] DONE in {elapsed/60:.1f}m")
    print(f"  Total comments seen:    {total_comments_seen}")
    print(f"  Created:                {total_created}")
    print(f"  Updated:                {total_updated}")
    print(f"  Skipped (unchanged):    {total_skipped}")
    print(f"  Errors on tickets:      {len(tickets_with_errors)}")
    print(f"  Final cip_ticket_comments rows: {final_count}")
    print(f"  is_public=true:                  {public_count}")
    print(f"  with attachments:                {with_attach_count}")
    if tickets_with_errors[:5]:
        print("\n  First 5 errors:")
        for tid, err in tickets_with_errors[:5]:
            print(f"    ticket {tid}: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
