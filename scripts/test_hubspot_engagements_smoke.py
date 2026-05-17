# foundry: kind=script domain=client-intelligence-platform
"""Smoke test: pull a few engagements of each kind from HubSpot, verify
mapper produces clean CIPRow, persister writes to cip_engagements.

Per PM scope 9952dd26 Block 3d. Reads-only sample to validate the
Block 3 code path before the full backfill.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_HUBSPOT_TOKEN=... \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/test_hubspot_engagements_smoke.py
"""
from __future__ import annotations

import os
import sys
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
)

LIMIT_PER_TYPE = 3


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)

    conn = HubSpotConnector(tenant_id=ECOMLEVER_TENANT_ID)
    conn.authenticate()
    print(f"[smoke] HubSpot authenticated (portal {conn.portal_id or '?'})")

    mapper = HubSpotMapper()
    batch_id = uuid4()
    rows_to_persist = []
    counts_per_kind = {"engagement_note": 0, "engagement_meeting": 0, "engagement_task": 0}

    # Limit to a few of each kind from the streamer
    seen_per_kind: dict[str, int] = {k: 0 for k in counts_per_kind}
    for rec in conn.stream_engagements(batch_size=10):
        kind = rec.get("__cip_kind__")
        if not isinstance(kind, str) or kind not in seen_per_kind:
            continue
        if seen_per_kind[kind] >= LIMIT_PER_TYPE:
            # Skip if we already have enough of this kind, but keep iterating
            # so we can find other kinds
            if all(v >= LIMIT_PER_TYPE for v in seen_per_kind.values()):
                break
            continue
        seen_per_kind[kind] += 1
        counts_per_kind[kind] += 1

        print(f"\n  [{kind}] source_id={rec.get('source_id')}")
        # Show a few fields per kind
        for show_key in ("hs_note_body", "hs_meeting_title", "hs_meeting_body",
                          "hs_meeting_start_time", "hs_meeting_end_time",
                          "hs_task_subject", "hs_task_status", "hs_task_priority"):
            v = rec.get(show_key)
            if v is not None:
                preview = str(v).replace("\n", " ")[:80]
                print(f"    {show_key}: {preview!r}")
        for assoc_key in ("__cip_assoc_contact__", "__cip_assoc_deal__",
                           "__cip_assoc_company__", "__cip_assoc_ticket__"):
            v = rec.get(assoc_key)
            if v:
                print(f"    {assoc_key}: {v}")

        ciprows = list(mapper.map(rec))
        assert len(ciprows) == 1, f"expected 1 CIPRow, got {len(ciprows)}"
        row = ciprows[0]
        assert row.target_table == "cip_engagements"
        et_in_fields = row.fields.get("engagement_type")
        assert et_in_fields in ("note", "meeting", "task"), \
            f"unexpected engagement_type {et_in_fields!r}"
        rows_to_persist.append(row)

    print(f"\n[smoke] Streamed {sum(seen_per_kind.values())} engagement records")
    for k, v in seen_per_kind.items():
        print(f"  {k}: {v}")

    if not rows_to_persist:
        print("[smoke] No rows to persist — check HubSpot data + token scope")
        return 1

    with Session(engine) as db:
        apply_tenant_context(db, ECOMLEVER_TENANT_ID)
        differ = SCDDiffer()
        persister = CIPRowPersister(db, differ)
        created = updated = skipped = 0
        for row in rows_to_persist:
            res = persister.persist(
                row,
                tenant_id=ECOMLEVER_TENANT_ID,
                connector_id=conn.connector_id,
                batch_id=batch_id,
            )
            created += res.created
            updated += res.updated
            skipped += res.skipped
        db.commit()
        print(f"\n[smoke] Persisted: created={created} updated={updated} skipped={skipped}")

        # Backfill client_id
        n = db.execute(
            text(
                "UPDATE cip_engagements SET client_id = :c "
                "WHERE tenant_id = :t AND client_id IS NULL"
            ),
            {"c": str(WAYWARD_CLIENT_ID), "t": str(ECOMLEVER_TENANT_ID)},
        ).rowcount
        db.commit()
        print(f"[smoke] Backfilled client_id on {n} rows")

        # Sample shape from DB
        sample = db.execute(
            text(
                "SELECT engagement_type, title, "
                "       coalesce(length(body), 0) as body_len, "
                "       owner_source_id, engagement_at, "
                "       array_length(contact_source_ids, 1) as n_contacts, "
                "       array_length(deal_source_ids, 1) as n_deals "
                "FROM cip_engagements WHERE tenant_id = :t "
                "ORDER BY engagement_at DESC NULLS LAST LIMIT 5"
            ),
            {"t": str(ECOMLEVER_TENANT_ID)},
        ).all()
        print("\n[smoke] Sample rows from DB:")
        for r in sample:
            print(f"  type={r[0]} title={(r[1] or '')[:30]!r} body_len={r[2]} owner={r[3]} engagement_at={r[4]} contacts={r[5]} deals={r[6]}")

    print("\n[smoke] SUCCESS — Block 3 code path verified end-to-end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
