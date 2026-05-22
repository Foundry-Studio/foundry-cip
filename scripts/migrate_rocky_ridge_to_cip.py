# foundry: kind=script domain=client-intelligence-platform
"""Migrate Rocky Ridge Research Library from Foundry-Knowledge into CIP.

Per D-d83c7e1d (CIP Hard Split, 2026-05-19) + PM scope a6c7d04b:
Rocky Ridge's 132-doc / 10,790-chunk research library currently lives
on the Foundry side (R2 prefix `80252ad9.../knowledge/`, `knowledge_chunks`
table with `source_type=document_library`, Foundry-Pinecone at 1024d).
Under the Hard Split this is CIP-shaped data and must move.

This script does a FULL PROPER REINGEST — no shortcut copies of text.
The flow per document:

    R2 download  ─►  sha256 + mime detect  ─►  text extract (PDF/docx/txt)
        │                                              │
        ▼                                              ▼
    re-upload to                                  chunk_text (D-055)
    cip-originals/                                     │
    {tenant}/{client}/manual_upload/                   ▼
    {file_uuid}/{name}                            embed each chunk
        │                                          (Qwen3-Embedding-4B
        ▼                                          Q8_0 @ 2560d via
    INSERT cip_files                               llama-server tunnel)
                                                       │
                                                       ▼
                                                  INSERT cip_knowledge_chunks
                                                  UPSERT CIP-Pinecone
                                                  (namespace
                                                   cip__{tenant}__{client})

Idempotency:
  - cip_files dedupes by (tenant_id, client_id, sha256)
  - cip_knowledge_chunks dedupes by (tenant_id, source_kind, source_id,
    chunk_index)
  - R2 re-upload skips if destination key already exists (HEAD check)
  - Pinecone upsert overwrites on matching vector id

The OLD Foundry-side state (knowledge_chunks rows, knowledge_sources row,
foundry-Pinecone vectors, original R2 prefix) is left alone here.
Purging happens in a separate `purge_rocky_ridge_foundry_state.py` script
that runs only after the acceptance gate passes on this migration.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        CIP_PINECONE_API_KEY=... \\
        CIP_PINECONE_INDEX_HOST=... \\
        LLAMA_SERVER_API_KEY=... \\
        CIP_R2_BUCKET=foundry-agent-system \\
        CIP_R2_ACCESS_KEY_ID=... \\
        CIP_R2_SECRET_ACCESS_KEY=... \\
        CIP_R2_ENDPOINT=https://...r2.cloudflarestorage.com \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/migrate_rocky_ridge_to_cip.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID, uuid4, uuid5

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from cip.integration_mesh.clients import (
    EmbeddingClient,
    PineconeClient,
    VectorUpsert,
    namespace_for,
)
from cip.integration_mesh.knowledge.chunker import chunk_text, ChunkSpec
from cip.integration_mesh.tenant_context import apply_tenant_context

# -- Constants ---------------------------------------------------------------

ROCKY_RIDGE_TENANT_ID: UUID = UUID("80252ad9-72d5-4c5a-b273-af804224872e")
ROCKY_RIDGE_CLIENT_ID: UUID = uuid5(ROCKY_RIDGE_TENANT_ID, "rocky-ridge")
ROCKY_RIDGE_CLIENT_NAME = "Rocky Ridge"
ROCKY_RIDGE_CLIENT_SLUG = "rocky-ridge"
ROCKY_RIDGE_CLIENT_INDUSTRY = "land-management"

# Old (Foundry-side) R2 location — read source
OLD_R2_PREFIX = f"{ROCKY_RIDGE_TENANT_ID}/knowledge/"

# New (CIP-side) R2 path: cip-originals/{tenant}/{client}/manual_upload/{file_uuid}/{name}
def _new_r2_key(file_uuid: UUID, filename: str) -> str:
    return (
        f"cip-originals/{ROCKY_RIDGE_TENANT_ID}/{ROCKY_RIDGE_CLIENT_ID}/"
        f"manual_upload/{file_uuid}/{filename}"
    )

SOURCE_KIND = "cip_client_document"

PINECONE_BATCH_SIZE = 100
EMBED_CONCURRENCY = 4
SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".txt", ".md"}

# Pinecone metadata: keep content slice + identity. Pinecone metadata
# caps individual values at 40 KB; we cap content at 30 KB for safety.
PINECONE_CONTENT_CAP = 30_000


# -- Helpers -----------------------------------------------------------------

@dataclass
class FileResult:
    r2_key: str
    cip_file_id: UUID
    sha256: str
    size_bytes: int
    chunks_inserted: int = 0
    chunks_embedded: int = 0
    chunks_upserted: int = 0
    skipped_existing: bool = False
    error: str | None = None


@dataclass
class RunStats:
    files_seen: int = 0
    files_processed: int = 0
    files_skipped_unsupported: int = 0
    files_skipped_existing: int = 0
    files_errored: int = 0
    chunks_inserted: int = 0
    chunks_embedded: int = 0
    chunks_upserted: int = 0
    errors: list[str] = field(default_factory=list)


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
    print(f"[migrate-rr] target={host} (prod={is_prod})")
    return None


def _mime_for(filename: str) -> str | None:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }.get(ext)


def _extract_text(filename: str, blob: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == ".pdf":
        import pymupdf  # type: ignore
        with pymupdf.open(stream=blob, filetype="pdf") as doc:
            pages: list[str] = []
            for page in doc:
                pages.append(page.get_text("text") or "")
            return "\n\n".join(pages).strip()
    if ext == ".docx":
        import docx  # type: ignore
        d = docx.Document(io.BytesIO(blob))
        return "\n\n".join(p.text for p in d.paragraphs if p.text and p.text.strip()).strip()
    if ext in (".txt", ".md"):
        try:
            return blob.decode("utf-8", errors="replace").strip()
        except Exception:  # noqa: BLE001
            return blob.decode("latin-1", errors="replace").strip()
    # .doc legacy — PyMuPDF doesn't read; skip with warning
    raise ValueError(f"unsupported extension: {ext!r}")


def _ensure_rocky_ridge_client(db: Session, batch_id: UUID) -> None:
    """Insert cip_clients row for Rocky Ridge if missing. Idempotent."""
    existing = db.execute(
        text(
            """
            SELECT id FROM cip_clients
            WHERE tenant_id = :t AND source_connector = 'manual' AND source_id = :sid
            """
        ),
        {"t": str(ROCKY_RIDGE_TENANT_ID), "sid": ROCKY_RIDGE_CLIENT_SLUG},
    ).first()
    if existing:
        print(f"[migrate-rr] cip_clients row exists for Rocky Ridge (client_id={ROCKY_RIDGE_CLIENT_ID})")
        return
    db.execute(
        text(
            """
            INSERT INTO cip_clients (
                id, tenant_id, client_id, source_connector, source_id,
                ingested_at, refreshed_at, ingestion_batch_id, authority,
                name, slug, industry, metadata, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), :tenant_id, :client_id, 'manual', :source_id,
                NOW(), NOW(), :batch, 'validated',
                :name, :slug, :industry, :metadata, NOW(), NOW()
            )
            """
        ),
        {
            "tenant_id": str(ROCKY_RIDGE_TENANT_ID),
            "client_id": str(ROCKY_RIDGE_CLIENT_ID),
            "source_id": ROCKY_RIDGE_CLIENT_SLUG,
            "batch": str(batch_id),
            "name": ROCKY_RIDGE_CLIENT_NAME,
            "slug": ROCKY_RIDGE_CLIENT_SLUG,
            "industry": ROCKY_RIDGE_CLIENT_INDUSTRY,
            "metadata": json.dumps({
                "seed_origin": "migrate_rocky_ridge_to_cip.py",
                "hard_split_decision": "d83c7e1d",
            }),
        },
    )
    db.commit()
    print(f"[migrate-rr] cip_clients row created (client_id={ROCKY_RIDGE_CLIENT_ID})")


# -- Main --------------------------------------------------------------------

def main() -> int:
    # Heartbeat marker — see PM scope 0f15a060.
    print(f"RUN_BEGAN tag=migrate_rocky_ridge_to_cip at={datetime.now(timezone.utc).isoformat()}")

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    err = _safety_gate(url)
    if err is not None:
        return err

    # Engines / clients
    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)
    embed = EmbeddingClient()
    pc = PineconeClient()
    print(f"[migrate-rr] Pinecone: {pc.index_host}")
    print(f"[migrate-rr] Embedder: {embed.primary_url} (protocol={embed.protocol})")

    bucket = os.environ.get("CIP_R2_BUCKET", "foundry-agent-system")
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["CIP_R2_ENDPOINT"],
        aws_access_key_id=os.environ["CIP_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["CIP_R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    print(f"[migrate-rr] R2 bucket: {bucket}, source prefix: {OLD_R2_PREFIX}")

    # One ingestion_batch_id for the whole run — every cip_files / cip_clients
    # row this script creates is tagged with it for trace.
    batch_id = uuid4()
    print(f"[migrate-rr] ingestion_batch_id: {batch_id}")

    # Ensure Rocky Ridge client exists
    with Session(engine) as db:
        apply_tenant_context(db, ROCKY_RIDGE_TENANT_ID)
        _ensure_rocky_ridge_client(db, batch_id)

    # Enumerate source objects
    print("[migrate-rr] Walking R2…")
    keys: list[tuple[str, int]] = []  # (key, size)
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=OLD_R2_PREFIX):
        for obj in page.get("Contents", []):
            keys.append((obj["Key"], obj["Size"]))
    print(f"[migrate-rr] Found {len(keys)} R2 objects under {OLD_R2_PREFIX}")

    stats = RunStats()
    pending_vectors: list[VectorUpsert] = []
    ns = namespace_for(ROCKY_RIDGE_TENANT_ID, ROCKY_RIDGE_CLIENT_ID)

    def _flush_pinecone() -> None:
        nonlocal pending_vectors
        if not pending_vectors:
            return
        try:
            pc.upsert(namespace=ns, vectors=pending_vectors)
            stats.chunks_upserted += len(pending_vectors)
        except Exception as e:  # noqa: BLE001
            stats.errors.append(f"pinecone upsert {len(pending_vectors)}: {type(e).__name__}: {e}")
        pending_vectors = []

    started = time.monotonic()

    for idx, (src_key, src_size) in enumerate(keys, start=1):
        stats.files_seen += 1
        # Skip dotfiles, manifests, anything not a knowledge artifact
        filename = src_key.rsplit("/", 1)[-1]
        if not filename or filename.startswith("."):
            stats.files_skipped_unsupported += 1
            continue
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in SUPPORTED_EXTS:
            stats.files_skipped_unsupported += 1
            print(f"  [{idx}/{len(keys)}] SKIP unsupported {filename}")
            continue

        # Download
        try:
            obj = s3.get_object(Bucket=bucket, Key=src_key)
            blob = obj["Body"].read()
        except ClientError as e:
            stats.files_errored += 1
            stats.errors.append(f"r2 get {src_key}: {e}")
            continue

        sha256 = hashlib.sha256(blob).hexdigest()

        # Dedupe by (tenant, client, sha256) in cip_files
        with Session(engine) as db:
            apply_tenant_context(db, ROCKY_RIDGE_TENANT_ID)
            existing_file = db.execute(
                text(
                    """
                    SELECT id::text FROM cip_files
                    WHERE tenant_id = :t AND client_id = :c AND sha256 = :sha
                    LIMIT 1
                    """
                ),
                {
                    "t": str(ROCKY_RIDGE_TENANT_ID),
                    "c": str(ROCKY_RIDGE_CLIENT_ID),
                    "sha": sha256,
                },
            ).first()
            if existing_file:
                cip_file_id = UUID(existing_file[0])
                # We still ensure chunks exist below; just mark "skipped existing"
                # at the *file* level for reporting purposes.
                stats.files_skipped_existing += 1
            else:
                cip_file_id = uuid4()

        # Extract text
        try:
            txt = _extract_text(filename, blob)
        except Exception as e:  # noqa: BLE001
            stats.files_errored += 1
            stats.errors.append(f"extract {filename}: {type(e).__name__}: {e}")
            continue
        if not txt.strip():
            stats.files_skipped_unsupported += 1
            print(f"  [{idx}/{len(keys)}] EMPTY text {filename}")
            continue

        # Re-upload to CIP prefix (idempotent — HEAD first)
        dest_key = _new_r2_key(cip_file_id, filename)
        try:
            s3.head_object(Bucket=bucket, Key=dest_key)
            r2_uploaded = False
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                s3.put_object(
                    Bucket=bucket,
                    Key=dest_key,
                    Body=blob,
                    ContentType=_mime_for(filename) or "application/octet-stream",
                    Metadata={
                        "sha256": sha256,
                        "tenant_id": str(ROCKY_RIDGE_TENANT_ID),
                        "client_id": str(ROCKY_RIDGE_CLIENT_ID),
                        "source_connector": "manual_upload",
                        "source_origin_key": src_key,
                    },
                )
                r2_uploaded = True
            else:
                stats.files_errored += 1
                stats.errors.append(f"r2 head {dest_key}: {e}")
                continue

        # Persist cip_files row if new
        with Session(engine) as db:
            apply_tenant_context(db, ROCKY_RIDGE_TENANT_ID)
            file_row = db.execute(
                text("SELECT id::text FROM cip_files WHERE id = :id"),
                {"id": str(cip_file_id)},
            ).first()
            if not file_row:
                db.execute(
                    text(
                        """
                        INSERT INTO cip_files (
                            id, tenant_id, client_id, source_connector, source_id,
                            ingested_at, refreshed_at, ingestion_batch_id, authority,
                            r2_path, filename, mime_type, size_bytes, sha256,
                            properties, created_at, updated_at
                        ) VALUES (
                            :id, :t, :c, 'manual_upload', :src,
                            NOW(), NOW(), :batch, 'validated',
                            :r2, :fn, :mime, :sz, :sha,
                            :props, NOW(), NOW()
                        )
                        """
                    ),
                    {
                        "id": str(cip_file_id),
                        "t": str(ROCKY_RIDGE_TENANT_ID),
                        "c": str(ROCKY_RIDGE_CLIENT_ID),
                        "src": src_key,  # source_id = origin R2 key (provenance)
                        "batch": str(batch_id),
                        "r2": dest_key,
                        "fn": filename,
                        "mime": _mime_for(filename) or "application/octet-stream",
                        "sz": len(blob),
                        "sha": sha256,
                        "props": json.dumps({
                            "origin_r2_prefix": OLD_R2_PREFIX,
                            "origin_r2_key": src_key,
                            "migration_run": "rocky_ridge_hard_split_2026_05",
                            "hard_split_decision": "d83c7e1d",
                        }),
                    },
                )
                db.commit()
                print(f"  [{idx}/{len(keys)}] new cip_files {cip_file_id} ({len(blob)/1024:.0f} KB){' + R2 re-upload' if r2_uploaded else ''}")
            elif r2_uploaded:
                print(f"  [{idx}/{len(keys)}] cip_files existed; R2 re-uploaded {dest_key}")

        # Chunk
        chunks = chunk_text(txt)
        if not chunks:
            print(f"  [{idx}/{len(keys)}] no chunks produced for {filename}")
            continue

        # Skip chunks already present in cip_knowledge_chunks (idempotent rerun)
        source_id_str = str(cip_file_id)
        with Session(engine) as db:
            apply_tenant_context(db, ROCKY_RIDGE_TENANT_ID)
            existing_idx_rows = db.execute(
                text(
                    """
                    SELECT chunk_index FROM cip_knowledge_chunks
                    WHERE tenant_id = :t AND source_kind = :sk AND source_id = :si
                    """
                ),
                {"t": str(ROCKY_RIDGE_TENANT_ID), "sk": SOURCE_KIND, "si": source_id_str},
            ).all()
            existing_idx = {r[0] for r in existing_idx_rows}
        to_process = [(i, c) for i, c in enumerate(chunks) if i not in existing_idx]
        if not to_process:
            stats.files_processed += 1
            continue

        # Embed in batches
        texts_to_embed = [c for _, c in to_process]
        try:
            vectors = embed.embed_batch_concurrent(
                texts_to_embed, max_workers=EMBED_CONCURRENCY
            )
        except Exception as e:  # noqa: BLE001
            stats.files_errored += 1
            stats.errors.append(f"embed {filename}: {type(e).__name__}: {e}")
            continue
        stats.chunks_embedded += len(vectors)

        # Persist + queue pinecone upserts
        with Session(engine) as db:
            apply_tenant_context(db, ROCKY_RIDGE_TENANT_ID)
            for (ci, content), vec in zip(to_process, vectors, strict=True):
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                db.execute(
                    text(
                        """
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
                        """
                    ),
                    {
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
                            "source_filename": filename,
                            "cip_files_id": str(cip_file_id),
                            "migration_run": "rocky_ridge_hard_split_2026_05",
                        }),
                    },
                )
                stats.chunks_inserted += 1

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
                        "source_filename": filename,
                        "content": content[:PINECONE_CONTENT_CAP],
                    },
                ))
                if len(pending_vectors) >= PINECONE_BATCH_SIZE:
                    _flush_pinecone()
            db.commit()

        stats.files_processed += 1
        elapsed = time.monotonic() - started
        rate = stats.chunks_embedded / max(elapsed, 0.001)
        print(
            f"  [{idx}/{len(keys)}] {filename}: chunks={len(chunks)} new={len(to_process)} "
            f"| total embedded={stats.chunks_embedded:,} | {rate:.1f} emb/s | "
            f"files: proc={stats.files_processed} skip={stats.files_skipped_unsupported} err={stats.files_errored}",
            flush=True,
        )

    # Final pinecone flush
    _flush_pinecone()

    elapsed = time.monotonic() - started
    print()
    print(f"[migrate-rr] DONE in {elapsed/60:.1f}m")
    print(f"  files seen:               {stats.files_seen}")
    print(f"  files processed:          {stats.files_processed}")
    print(f"  files skipped (existed):  {stats.files_skipped_existing}")
    print(f"  files skipped (unsupp):   {stats.files_skipped_unsupported}")
    print(f"  files errored:            {stats.files_errored}")
    print(f"  chunks inserted (PG):     {stats.chunks_inserted}")
    print(f"  chunks embedded:          {stats.chunks_embedded}")
    print(f"  chunks upserted (PC):     {stats.chunks_upserted}")
    if stats.errors:
        print(f"  first 10 errors:")
        for e in stats.errors[:10]:
            print(f"    - {e}")

    time.sleep(3)
    post = pc.describe_index_stats()
    ns_info = (post.get("namespaces") or {}).get(ns, {})
    print()
    print(f"[migrate-rr] CIP-Pinecone namespace {ns}: {ns_info.get('vectorCount', 0):,} vectors")
    print(f"RUN_ENDED tag=migrate_rocky_ridge_to_cip at={datetime.now(timezone.utc).isoformat()}")
    return 0 if stats.files_errored == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
