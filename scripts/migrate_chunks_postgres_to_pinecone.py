# foundry: kind=script domain=client-intelligence-platform
"""Migrate cip_knowledge_chunks vectors from Postgres-native to CIP-Pinecone.

Per PM decision d83c7e1d (CIP Hard Split, 2026-05-19): vectors live in
CIP-dedicated Pinecone index `foundry-cip` (2,560 dim). The Postgres
`cip_knowledge_chunks` table remains as the canonical source-of-truth
+ staging layer; Pinecone is the hot-retrieval store. Migration moves
historical embeddings into Pinecone so semantic search reaches them.

Idempotent: Pinecone upsert overwrites on matching ID, so re-running
this script is safe. Vector ID pattern:
    cip-{source_kind}-{source_id}-{chunk_index}

Namespace pattern: cip__{tenant_id}__{client_id} via namespace_for().

Metadata persisted on each vector:
    tenant_id, client_id, source_kind, source_id, chunk_index,
    total_chunks, content_chars, content_hash, content,
    + any extras from chunks.metadata JSONB

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        CIP_PINECONE_API_KEY=... \\
        CIP_PINECONE_INDEX_HOST=... \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/migrate_chunks_postgres_to_pinecone.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from cip.integration_mesh.clients import (
    PineconeClient,
    VectorUpsert,
    namespace_for,
)
from cip.integration_mesh.tenant_context import apply_tenant_context
from cip.integration_mesh.wayward_constants import ECOMLEVER_TENANT_ID

BATCH_SIZE = 100  # Pinecone upsert sweet spot


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
    print(f"[migrate-vectors] target={host} (prod={is_prod})")
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

    pc = PineconeClient()
    print(f"[migrate-vectors] Pinecone index: {pc.index_host}")

    # Stats before
    pre_stats = pc.describe_index_stats()
    print(f"[migrate-vectors] Pre-migration index stats: total={pre_stats.get('totalVectorCount', 0)}")

    # Count source rows
    with Session(engine) as db:
        apply_tenant_context(db, ECOMLEVER_TENANT_ID)
        total = db.execute(
            text("SELECT COUNT(*) FROM cip_knowledge_chunks WHERE tenant_id = :t"),
            {"t": str(ECOMLEVER_TENANT_ID)},
        ).scalar() or 0
    print(f"[migrate-vectors] {total} chunks to migrate")

    if total == 0:
        print("[migrate-vectors] Nothing to do.")
        return 0

    start = time.monotonic()
    migrated = 0
    by_ns: dict[str, int] = defaultdict(int)
    errors = 0

    start_offset = int(os.environ.get("START_OFFSET", "0"))
    if start_offset:
        print(f"[migrate-vectors] Resuming from offset={start_offset}")

    # Stream chunks in chunk_id ASC order, batch into 100, group by namespace
    with Session(engine) as db:
        apply_tenant_context(db, ECOMLEVER_TENANT_ID)
        offset = start_offset
        while offset < total:
            rows = db.execute(
                text(
                    """
                    SELECT id, tenant_id, client_id, source_kind, source_id,
                           chunk_index, total_chunks, content, content_hash,
                           content_chars, embedding, embedding_model, metadata
                    FROM cip_knowledge_chunks
                    WHERE tenant_id = :t
                    ORDER BY id
                    OFFSET :off LIMIT :lim
                    """
                ),
                {"t": str(ECOMLEVER_TENANT_ID), "off": offset, "lim": BATCH_SIZE},
            ).mappings().all()
            if not rows:
                break

            # Group by namespace within the batch (Pinecone requires one
            # namespace per upsert call).
            ns_batches: dict[str, list[VectorUpsert]] = defaultdict(list)
            for r in rows:
                ns = namespace_for(r["tenant_id"], r["client_id"])
                # Compose vector ID — stable + collision-safe
                vec_id = (
                    f"cip-{r['source_kind']}-{r['source_id']}-{r['chunk_index']}"
                )
                meta = dict(r["metadata"] or {})
                meta.update({
                    "tenant_id": str(r["tenant_id"]),
                    "client_id": str(r["client_id"]) if r["client_id"] else "",
                    "source_kind": r["source_kind"],
                    "source_id": r["source_id"],
                    "chunk_index": int(r["chunk_index"]),
                    "total_chunks": int(r["total_chunks"]),
                    "content_chars": int(r["content_chars"]),
                    "content_hash": r["content_hash"],
                    "embedding_model": r["embedding_model"],
                    "content": r["content"][:40000],  # Pinecone metadata cap
                })
                # Coerce all metadata values to Pinecone-safe types
                meta = _coerce_meta(meta)
                ns_batches[ns].append(VectorUpsert(
                    id=vec_id,
                    values=[float(x) for x in r["embedding"]],
                    metadata=meta,
                ))

            for ns, vecs in ns_batches.items():
                try:
                    pc.upsert(namespace=ns, vectors=vecs)
                    by_ns[ns] += len(vecs)
                    migrated += len(vecs)
                except Exception as e:  # noqa: BLE001
                    errors += 1
                    print(
                        f"  ERROR upsert ns={ns} batch={len(vecs)}: "
                        f"{type(e).__name__}: {str(e)[:200]}",
                        flush=True,
                    )

            offset += BATCH_SIZE
            elapsed = time.monotonic() - start
            rate = migrated / max(elapsed, 0.001)
            pct = 100.0 * offset / total
            eta = (total - offset) / max(rate, 0.001)
            print(
                f"  {offset:>5d}/{total} ({pct:5.1f}%) | migrated={migrated:,} | "
                f"{rate:.0f}/s | ETA {eta/60:.1f}m | errors={errors}",
                flush=True,
            )

    elapsed = time.monotonic() - start
    print(f"\n[migrate-vectors] DONE in {elapsed/60:.1f}m")
    print(f"  Migrated: {migrated:,}")
    print(f"  Errors: {errors}")
    print(f"  Per namespace:")
    for ns, n in sorted(by_ns.items()):
        print(f"    {ns}: {n:,}")

    # Stats after — give Pinecone a moment to update
    time.sleep(3)
    post_stats = pc.describe_index_stats()
    print(f"\n[migrate-vectors] Post-migration index stats:")
    print(f"  totalVectorCount: {post_stats.get('totalVectorCount', 0)}")
    namespaces = post_stats.get("namespaces", {})
    for ns, info in sorted(namespaces.items()):
        print(f"  {ns}: {info.get('vectorCount', 0):,}")
    return 0


def _coerce_meta(meta: dict) -> dict:
    """Pinecone metadata values must be string/number/bool/list-of-strings.
    Coerce non-conforming values to strings or drop them.
    """
    out = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            out[k] = v
        else:
            # Datetimes, UUIDs, complex objects -> str
            try:
                out[k] = str(v)
            except Exception:  # noqa: BLE001
                pass
    return out


if __name__ == "__main__":
    sys.exit(main())
