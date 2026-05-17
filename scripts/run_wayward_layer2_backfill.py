# foundry: kind=script domain=client-intelligence-platform
"""Wayward Layer 2 backfill — embed all conversational content.

Per PM scope d46f4b37 (Wayward Layer 2 instance) + capability 2d6390fa.

Embeds (in order, idempotent via content_hash skip-unchanged):
  1. Zendesk ticket comments (10,971 rows, body field)
  2. HubSpot engagement notes (5,065 rows, hs_note_body in overflow)
  3. HubSpot engagement meetings (2,946 rows with body)
  4. (skipped) tasks — bodies too short for semantic embedding (median 41 chars)

Estimated total: ~25,000 chunks at ~3 chunks/sec (Ollama serial calls)
= ~140 minutes. Run in background or accept the long elapsed time.

Idempotent: existing rows with matching content_hash are skipped.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/run_wayward_layer2_backfill.py
"""
from __future__ import annotations

import os
import re
import sys
import time

from sqlalchemy import create_engine, text

from cip.integration_mesh.clients import EmbeddingClient
from cip.integration_mesh.knowledge import KnowledgeIndexer
from cip.integration_mesh.wayward_constants import ECOMLEVER_TENANT_ID
from sqlalchemy.orm import Session

# Optional: cap rows-per-kind for faster runs (set to None for full)
LIMIT_PER_KIND = int(os.environ.get("CIP_LAYER2_LIMIT", "0")) or None


def _safety_gate(url: str) -> int | None:
    m = re.search(r"@([^/:?]+)", url)
    host = m.group(1) if m else "<unknown>"
    is_prod = bool(re.search(r"\.rlwy\.net|\.railway\.app", host))
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if not is_local:
        expected = "YES_I_KNOW_THIS_IS_PROD" if is_prod else "YES_I_KNOW_THIS_IS_REMOTE"
        if os.environ.get("SEED_CONFIRM") != expected:
            print(f"ABORTED: re-run with SEED_CONFIRM={expected}", file=sys.stderr)
            return 3
    print(f"[layer2-backfill] target={host} (prod={is_prod})")
    return None


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    err = _safety_gate(url)
    if err is not None:
        return err

    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)
    emb_client = EmbeddingClient()

    print(f"[layer2-backfill] Embedding endpoint: {emb_client.primary_url}")
    print(f"[layer2-backfill] Primary model: {emb_client.primary_model}")
    print(f"[layer2-backfill] Limit per kind: {LIMIT_PER_KIND or 'all'}")

    indexer = KnowledgeIndexer(
        engine, emb_client, ECOMLEVER_TENANT_ID, commit_every=50,
    )
    limit_sql = f"LIMIT {LIMIT_PER_KIND}" if LIMIT_PER_KIND else ""
    start = time.monotonic()
    results = []

    # ── Pass 1: Zendesk ticket comments ──────────────────────────────
    print("\n[layer2-backfill] PASS 1: ticket comments")
    pass1 = indexer.index_kind(
        source_kind="cip_ticket_comment",
        select_sql=f"""
            SELECT source_id, body, client_id, is_public, via_channel, ticket_source_id
            FROM cip_ticket_comments
            WHERE tenant_id = :tenant_id
              AND body IS NOT NULL AND length(body) >= 50
            ORDER BY source_id::bigint
            {limit_sql}
        """,
        text_col="body",
        extra_metadata_keys=("is_public", "via_channel", "ticket_source_id"),
    )
    results.append(pass1)
    print(f"  seen={pass1.seen} chunked={pass1.chunked} persisted={pass1.persisted} "
          f"skipped={pass1.skipped_unchanged} errors={pass1.errors} elapsed={pass1.elapsed_s/60:.1f}m")

    # ── Pass 2: HubSpot engagement notes ─────────────────────────────
    print("\n[layer2-backfill] PASS 2: engagement notes")
    pass2 = indexer.index_kind(
        source_kind="cip_engagement_note",
        select_sql=f"""
            SELECT source_id, body, client_id,
                   engagement_at, owner_source_id,
                   array_to_string(contact_source_ids, ',') AS contacts_csv,
                   array_to_string(deal_source_ids, ',') AS deals_csv
            FROM cip_engagements
            WHERE tenant_id = :tenant_id AND engagement_type = 'note'
              AND body IS NOT NULL AND length(body) >= 50
            ORDER BY source_id::bigint
            {limit_sql}
        """,
        text_col="body",
        extra_metadata_keys=(
            "engagement_at", "owner_source_id", "contacts_csv", "deals_csv",
        ),
    )
    results.append(pass2)
    print(f"  seen={pass2.seen} chunked={pass2.chunked} persisted={pass2.persisted} "
          f"skipped={pass2.skipped_unchanged} errors={pass2.errors} elapsed={pass2.elapsed_s/60:.1f}m")

    # ── Pass 3: HubSpot engagement meetings ──────────────────────────
    print("\n[layer2-backfill] PASS 3: engagement meetings")
    pass3 = indexer.index_kind(
        source_kind="cip_engagement_meeting",
        select_sql=f"""
            SELECT source_id, body, client_id,
                   engagement_at, owner_source_id, title, start_time, end_time,
                   array_to_string(contact_source_ids, ',') AS contacts_csv,
                   array_to_string(deal_source_ids, ',') AS deals_csv
            FROM cip_engagements
            WHERE tenant_id = :tenant_id AND engagement_type = 'meeting'
              AND body IS NOT NULL AND length(body) >= 50
            ORDER BY source_id::bigint
            {limit_sql}
        """,
        text_col="body",
        extra_metadata_keys=(
            "engagement_at", "owner_source_id", "title", "start_time", "end_time",
            "contacts_csv", "deals_csv",
        ),
    )
    results.append(pass3)
    print(f"  seen={pass3.seen} chunked={pass3.chunked} persisted={pass3.persisted} "
          f"skipped={pass3.skipped_unchanged} errors={pass3.errors} elapsed={pass3.elapsed_s/60:.1f}m")

    # ── Summary ──────────────────────────────────────────────────────
    elapsed = time.monotonic() - start
    print(f"\n[layer2-backfill] DONE in {elapsed/60:.1f}m")
    print(f"  total seen:      {sum(r.seen for r in results):>6,}")
    print(f"  total chunked:   {sum(r.chunked for r in results):>6,}")
    print(f"  total persisted: {sum(r.persisted for r in results):>6,}")
    print(f"  total skipped:   {sum(r.skipped_unchanged for r in results):>6,}")
    print(f"  total errors:    {sum(r.errors for r in results):>6,}")
    print(f"  embedding stats: {emb_client.stats()}")

    # Final DB coverage
    with Session(engine) as db:
        from cip.integration_mesh.tenant_context import apply_tenant_context
        apply_tenant_context(db, ECOMLEVER_TENANT_ID)
        for kind in ("cip_ticket_comment", "cip_engagement_note", "cip_engagement_meeting"):
            n = db.execute(
                text(
                    "SELECT COUNT(*) FROM cip_knowledge_chunks "
                    "WHERE tenant_id = :t AND source_kind = :k"
                ),
                {"t": str(ECOMLEVER_TENANT_ID), "k": kind},
            ).scalar()
            print(f"  cip_knowledge_chunks[{kind}]: {n:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
