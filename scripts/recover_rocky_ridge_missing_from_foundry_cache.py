# foundry: kind=script domain=client-intelligence-platform
"""Recover Rocky Ridge files that exist in Foundry-Knowledge but not in CIP yet.

Per Tim 2026-05-22 directive (option B — recover missing content before
purging). The Foundry `files` table caches `textualized_content` for every
file it ingested. The R2-driven migration (migrate_rocky_ridge_to_cip.py)
covered 53 of 63 Foundry files via PDF/docx text extraction. This script
handles the residual 10:

  - 9 `image/jpeg` property maps with vision-extracted captions
    (~3-5 KB of text per image — annotated land-management photos)
  - 1 PDF that didn't match by filename (case / spacing differences
    between R2 key and Foundry original_filename — likely the same
    content, but treated as separate for safety)

For each unmatched Foundry file:
  1. Read `textualized_content` straight from Foundry's `files` table
  2. Insert a cip_files row with source_connector='foundry_knowledge_recovery'
     (distinct from 'manual_upload' so the provenance trail is durable)
  3. The Foundry s3_path is preserved in properties.origin_s3_path
  4. Chunk the cached text (CIP chunker, D-055 spec)
  5. Embed at 2,560d via the same llama-server endpoint
  6. Insert cip_knowledge_chunks + upsert CIP-Pinecone

Idempotent — the same dedupe rules as the main migration apply
(cip_files by sha256 of text, chunks by uq_cip_knowledge_chunks_source).

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        CIP_PINECONE_API_KEY=... \\
        CIP_PINECONE_INDEX_HOST=... \\
        LLAMA_SERVER_API_KEY=... \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/recover_rocky_ridge_missing_from_foundry_cache.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from cip.integration_mesh.clients import (
    EmbeddingClient,
    PineconeClient,
    VectorUpsert,
    namespace_for,
)
from cip.integration_mesh.knowledge.chunker import chunk_text
from cip.integration_mesh.tenant_context import apply_tenant_context

ROCKY_RIDGE_TENANT_ID: UUID = UUID("80252ad9-72d5-4c5a-b273-af804224872e")
ROCKY_RIDGE_CLIENT_ID: UUID = uuid5(ROCKY_RIDGE_TENANT_ID, "rocky-ridge")
FOUNDRY_RR_SOURCE_ID: UUID = UUID("52ad54c0-acfd-49db-b9b4-dc9c6098d9f6")
SOURCE_KIND = "cip_client_document"
SOURCE_CONNECTOR = "foundry_knowledge_recovery"
PINECONE_BATCH_SIZE = 100
PINECONE_CONTENT_CAP = 30_000


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
    print(f"[recover-rr] target={host} (prod={is_prod})")
    return None


def main() -> int:
    print(f"RUN_BEGAN tag=recover_rocky_ridge_missing_from_foundry_cache at={datetime.now(timezone.utc).isoformat()}")
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
    embed = EmbeddingClient()
    pc = PineconeClient()
    print(f"[recover-rr] Embedder: {embed.primary_url} (protocol={embed.protocol})")
    print(f"[recover-rr] Pinecone: {pc.index_host}")

    batch_id = uuid4()
    print(f"[recover-rr] ingestion_batch_id: {batch_id}")

    # Enumerate Foundry files that produced chunks for our source but are NOT
    # present (by filename) in cip_files for this tenant.
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                f.file_id::text AS file_id,
                f.original_filename,
                f.mime_type,
                f.s3_path,
                f.size_bytes,
                f.textualized_content,
                length(f.textualized_content) AS text_chars
            FROM files f
            WHERE f.file_id IN (
                SELECT DISTINCT source_file_id FROM knowledge_chunks
                WHERE source_id = :src
            )
            AND NOT EXISTS (
                SELECT 1 FROM cip_files cf
                WHERE cf.tenant_id = :tenant
                  AND cf.filename = f.original_filename
            )
            ORDER BY f.mime_type, f.original_filename
        """), {"src": str(FOUNDRY_RR_SOURCE_ID), "tenant": str(ROCKY_RIDGE_TENANT_ID)}).mappings().all()
    print(f"[recover-rr] {len(rows)} files to recover from Foundry textualized_content cache")

    if not rows:
        print("[recover-rr] Nothing to recover.")
        return 0

    ns = namespace_for(ROCKY_RIDGE_TENANT_ID, ROCKY_RIDGE_CLIENT_ID)
    pending_vectors: list[VectorUpsert] = []
    files_done = 0
    chunks_done = 0
    errors: list[str] = []

    def _flush() -> None:
        nonlocal pending_vectors
        if not pending_vectors:
            return
        try:
            pc.upsert(namespace=ns, vectors=pending_vectors)
        except Exception as e:  # noqa: BLE001
            errors.append(f"pinecone upsert {len(pending_vectors)}: {type(e).__name__}: {e}")
        pending_vectors = []

    started = time.monotonic()
    for r in rows:
        fname = r["original_filename"] or "<unknown>"
        text_content = (r["textualized_content"] or "").strip()
        if not text_content:
            print(f"  SKIP empty: {fname}")
            continue

        # Compute a stable cip_files.id and dedupe by sha256(text)
        sha = hashlib.sha256(text_content.encode("utf-8")).hexdigest()
        with Session(engine) as db:
            apply_tenant_context(db, ROCKY_RIDGE_TENANT_ID)
            existing = db.execute(text("""
                SELECT id::text FROM cip_files
                WHERE tenant_id = :t AND client_id = :c AND sha256 = :sha
                LIMIT 1
            """), {
                "t": str(ROCKY_RIDGE_TENANT_ID),
                "c": str(ROCKY_RIDGE_CLIENT_ID),
                "sha": sha,
            }).first()
            if existing:
                cip_file_id = UUID(existing[0])
                print(f"  RESUME: cip_files exists for {fname} ({cip_file_id})")
            else:
                cip_file_id = uuid4()
                db.execute(text("""
                    INSERT INTO cip_files (
                        id, tenant_id, client_id, source_connector, source_id,
                        ingested_at, refreshed_at, ingestion_batch_id, authority,
                        r2_path, filename, mime_type, size_bytes, sha256,
                        properties, created_at, updated_at
                    ) VALUES (
                        :id, :t, :c, :sc, :src,
                        NOW(), NOW(), :batch, 'validated',
                        :r2, :fn, :mime, :sz, :sha,
                        :props, NOW(), NOW()
                    )
                """), {
                    "id": str(cip_file_id),
                    "t": str(ROCKY_RIDGE_TENANT_ID),
                    "c": str(ROCKY_RIDGE_CLIENT_ID),
                    "sc": SOURCE_CONNECTOR,
                    # source_id encodes the Foundry origin pointer
                    "src": f"foundry_files:{r['file_id']}",
                    "batch": str(batch_id),
                    # r2_path is required NOT NULL — point at Foundry's original
                    # location (we are NOT copying the binary, just registering)
                    "r2": r["s3_path"] or "",
                    "fn": fname,
                    "mime": r["mime_type"],
                    "sz": r["size_bytes"] or len(text_content),
                    "sha": sha,
                    "props": json.dumps({
                        "recovery_source": "foundry_files.textualized_content",
                        "foundry_file_id": r["file_id"],
                        "foundry_knowledge_source_id": str(FOUNDRY_RR_SOURCE_ID),
                        "foundry_s3_path": r["s3_path"],
                        "migration_run": "rocky_ridge_recovery_2026_05_22",
                        "hard_split_decision": "d83c7e1d",
                    }),
                })
                db.commit()
                print(f"  NEW: {fname} ({cip_file_id}) text={r['text_chars']:,}c mime={r['mime_type']}")

        # Chunk
        chunks = chunk_text(text_content)
        if not chunks:
            continue

        # Skip already-present chunks
        source_id_str = str(cip_file_id)
        with Session(engine) as db:
            apply_tenant_context(db, ROCKY_RIDGE_TENANT_ID)
            existing_idx = {
                r2[0] for r2 in db.execute(text("""
                    SELECT chunk_index FROM cip_knowledge_chunks
                    WHERE tenant_id = :t AND source_kind = :sk AND source_id = :si
                """), {
                    "t": str(ROCKY_RIDGE_TENANT_ID),
                    "sk": SOURCE_KIND,
                    "si": source_id_str,
                }).all()
            }
        to_process = [(i, c) for i, c in enumerate(chunks) if i not in existing_idx]
        if not to_process:
            files_done += 1
            continue

        texts_to_embed = [c for _, c in to_process]
        try:
            vectors = embed.embed_batch_concurrent(texts_to_embed, max_workers=4)
        except Exception as e:  # noqa: BLE001
            errors.append(f"embed {fname}: {type(e).__name__}: {e}")
            continue

        with Session(engine) as db:
            apply_tenant_context(db, ROCKY_RIDGE_TENANT_ID)
            for (ci, content), vec in zip(to_process, vectors, strict=True):
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                db.execute(text("""
                    INSERT INTO cip_knowledge_chunks (
                        id, tenant_id, client_id, source_kind, source_id,
                        chunk_index, total_chunks, content, content_hash,
                        content_chars, embedding, embedding_dim, embedding_model,
                        metadata, embedded_at, created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), :t, :c, :sk, :si,
                        :idx, :total, :content, :hash,
                        :chars, CAST(:emb AS double precision[]), :dim, :model,
                        :meta, NOW(), NOW(), NOW()
                    )
                    ON CONFLICT DO NOTHING
                """), {
                    "t": str(ROCKY_RIDGE_TENANT_ID),
                    "c": str(ROCKY_RIDGE_CLIENT_ID),
                    "sk": SOURCE_KIND,
                    "si": source_id_str,
                    "idx": ci,
                    "total": len(chunks),
                    "content": content,
                    "hash": content_hash,
                    "chars": len(content),
                    "emb": [float(x) for x in vec],
                    "dim": len(vec),
                    "model": embed.primary_model,
                    "meta": json.dumps({
                        "source_filename": fname,
                        "cip_files_id": str(cip_file_id),
                        "recovery_source": "foundry_files.textualized_content",
                        "migration_run": "rocky_ridge_recovery_2026_05_22",
                    }),
                })
                chunks_done += 1
                pending_vectors.append(VectorUpsert(
                    id=f"cip-{SOURCE_KIND}-{source_id_str}-{ci}",
                    values=[float(x) for x in vec],
                    metadata={
                        "tenant_id": str(ROCKY_RIDGE_TENANT_ID),
                        "client_id": str(ROCKY_RIDGE_CLIENT_ID),
                        "source_kind": SOURCE_KIND,
                        "source_id": source_id_str,
                        "chunk_index": ci,
                        "total_chunks": len(chunks),
                        "content_chars": len(content),
                        "content_hash": content_hash,
                        "embedding_model": embed.primary_model,
                        "source_filename": fname,
                        "content": content[:PINECONE_CONTENT_CAP],
                        "recovery": True,
                    },
                ))
                if len(pending_vectors) >= PINECONE_BATCH_SIZE:
                    _flush()
            db.commit()
        files_done += 1
        print(f"    chunks={len(chunks)} new={len(to_process)} ({fname})")

    _flush()
    elapsed = time.monotonic() - started
    print()
    print(f"[recover-rr] DONE in {elapsed:.1f}s")
    print(f"  files recovered: {files_done}")
    print(f"  chunks added:    {chunks_done}")
    if errors:
        print(f"  errors: {len(errors)}")
        for e in errors[:10]:
            print(f"    - {e}")

    time.sleep(2)
    post = pc.describe_index_stats()
    ns_info = (post.get("namespaces") or {}).get(ns, {})
    print(f"\n[recover-rr] CIP-Pinecone namespace {ns}: {ns_info.get('vectorCount', 0):,} vectors")
    print(f"RUN_ENDED tag=recover_rocky_ridge_missing_from_foundry_cache at={datetime.now(timezone.utc).isoformat()}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
