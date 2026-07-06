# foundry: kind=service domain=client-intelligence-platform
"""Indexer — pulls CIP rows, chunks, embeds, upserts into cip_knowledge_chunks.

Per PM scope 2d6390fa (Layer 2 wiring v1, tenant-agnostic capability).

Usage:
    from cip.integration_mesh.knowledge import KnowledgeIndexer
    from cip.integration_mesh.clients import EmbeddingClient

    indexer = KnowledgeIndexer(engine, EmbeddingClient(), tenant_id)
    result = indexer.index_kind(
        source_kind='cip_ticket_comment',
        select_sql=\"\"\"
            SELECT source_id, body, client_id
            FROM cip_ticket_comments
            WHERE tenant_id = :tenant_id
              AND body IS NOT NULL AND length(body) > 0
        \"\"\",
        text_col='body',
    )
    print(result)  # IndexResult(seen=10971, chunked=12345, embedded=12345, persisted=12345)
"""
from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cip.integration_mesh.clients import (
    EmbeddingClient,
    PineconeClient,
    PineconeError,
    VectorUpsert,
    namespace_for,
)
from cip.integration_mesh.knowledge.chunker import ChunkSpec, chunk_text
from cip.integration_mesh.tenant_context import apply_tenant_context

# Pinecone metadata cap (40 KB per value; we cap content at 30 KB for safety).
_PINECONE_CONTENT_CAP = 30_000


@dataclass
class IndexResult:
    source_kind: str
    seen: int = 0          # rows the SELECT returned
    chunked: int = 0       # chunks produced (incl. multi-chunk rows)
    embedded: int = 0      # chunks that got an embedding
    persisted: int = 0     # chunks INSERTed
    skipped_unchanged: int = 0  # content_hash matched existing row
    errors: int = 0
    elapsed_s: float = 0.0
    first_errors: list[str] = field(default_factory=list)
    # Pinecone parity tracking (cip_22 wiring 2026-05-22).
    pinecone_upserted: int = 0
    pinecone_errors: int = 0


class KnowledgeIndexer:
    """Embed-and-store pipeline for one CIP source kind at a time."""

    def __init__(
        self,
        engine: Engine,
        embedding_client: EmbeddingClient,
        tenant_id: UUID,
        *,
        chunk_spec: ChunkSpec | None = None,
        commit_every: int = 100,
        embed_concurrency: int = 4,
        embed_batch_size: int = 32,
        pinecone_client: PineconeClient | None = None,
    ) -> None:
        self.engine = engine
        self.client = embedding_client
        self.tenant_id = tenant_id
        self.chunk_spec = chunk_spec or ChunkSpec()
        self.commit_every = commit_every
        # Pinecone wiring (PM scope ed653420, 2026-05-22). When supplied,
        # every persisted chunk is ALSO upserted into CIP-Pinecone under
        # `cip__{tenant}__{client}` so search parity stays automatic
        # rather than depending on a separate backfill script. Pinecone
        # failures are NON-fatal: Postgres is the canonical store, the
        # Pinecone-side backfill script can repair drift after the fact.
        self.pinecone = pinecone_client
        # Parallelism for the embed step. Embedding is the slow hop;
        # batching K chunks and issuing K embeds in parallel against an
        # ollama server with OLLAMA_NUM_PARALLEL>=K cuts wall-time
        # ~K-fold (bounded by GPU memory bandwidth). DB writes stay
        # sequential through the single SQLAlchemy session for
        # transactional simplicity. Bench 2026-05-18: embed_concurrency=4
        # + embed_batch_size=32 against OLLAMA_NUM_PARALLEL=4 lifted
        # throughput from ~0.7 emb/sec to ~2.5-3 emb/sec on Wayward.
        self.embed_concurrency = embed_concurrency
        self.embed_batch_size = embed_batch_size

    def index_kind(
        self,
        *,
        source_kind: str,
        select_sql: str,
        text_col: str = "body",
        source_id_col: str = "source_id",
        client_id_col: str = "client_id",
        extra_metadata_keys: Iterable[str] = (),
    ) -> IndexResult:
        """Run the embed-and-store pipeline for one source_kind.

        Args:
            source_kind: e.g. 'cip_ticket_comment', 'cip_engagement_note'
            select_sql: SQL SELECT that yields the source rows. Must
                bind :tenant_id parameter. Must include text_col,
                source_id_col, client_id_col, and any extra_metadata_keys.
            text_col: column name carrying the text to embed
            source_id_col: column name carrying the row's source_id
            client_id_col: column name carrying the row's client_id
            extra_metadata_keys: extra columns to include in chunk metadata
        """
        result = IndexResult(source_kind=source_kind)
        start = time.monotonic()

        # Buffer of pending-to-embed chunk descriptors. Filled by the row
        # loop; drained by flush_batch(). Batching is what unlocks the
        # ThreadPoolExecutor in embed_batch_concurrent — without buffering,
        # each chunk would still go through the slow serial embed() path.
        batch: list[dict[str, Any]] = []

        # SQL pulled out so flush_batch can reuse without re-formatting.
        delete_sql = text(
            "DELETE FROM cip_knowledge_chunks "
            "WHERE tenant_id = :t AND source_kind = :k "
            "AND source_id = :s AND chunk_index = :i"
        )
        insert_sql = text(
            "INSERT INTO cip_knowledge_chunks ("
            "  tenant_id, client_id, source_kind, source_id, "
            "  chunk_index, total_chunks, content, content_hash, "
            "  content_chars, embedding, embedding_dim, "
            "  embedding_model, metadata"
            ") VALUES ("
            "  :tenant_id, :client_id, :source_kind, :source_id, "
            "  :chunk_index, :total_chunks, :content, :content_hash, "
            "  :content_chars, CAST(:embedding AS double precision[]), "
            "  :embedding_dim, :embedding_model, "
            "  CAST(:metadata AS jsonb)"
            ")"
        )
        skip_sql = text(
            "SELECT 1 FROM cip_knowledge_chunks "
            "WHERE tenant_id = :t AND source_kind = :k "
            "AND source_id = :s AND chunk_index = :i "
            "AND content_hash = :h"
        )

        with Session(self.engine) as db:
            apply_tenant_context(db, self.tenant_id)
            rows = db.execute(
                text(select_sql), {"tenant_id": str(self.tenant_id)}
            ).mappings().all()
            result.seen = len(rows)

            # Mutable counter the flush closure mutates. Tracked via a
            # one-element list because Python closures can't rebind locals.
            pending = [0]

            def flush_batch() -> None:
                """Embed buffered chunks in parallel, then write sequentially."""
                if not batch:
                    return
                texts = [b["content"] for b in batch]
                # Try parallel embed first; on batch-level failure (e.g.
                # network blip, single-text triggering server error), fall
                # back to per-item embed so the rest of the batch still lands.
                # ``None`` is the per-item failure sentinel in the fallback
                # path (skipped at the zip below), so vecs is a union list.
                # Declared up front + .extend() on success (Iterable is
                # covariant, so list[list[float]] extends cleanly — a bare
                # assignment wouldn't, list being invariant).
                vecs: list[list[float] | None] = []
                try:
                    vecs.extend(
                        self.client.embed_batch_concurrent(
                            texts, max_workers=self.embed_concurrency
                        )
                    )
                except Exception:  # noqa: BLE001
                    vecs = []
                    for t in texts:
                        try:
                            vecs.append(self.client.embed(t))
                        except Exception as ie:  # noqa: BLE001
                            vecs.append(None)
                            result.errors += 1
                            if len(result.first_errors) < 5:
                                result.first_errors.append(
                                    f"embed-fallback: {type(ie).__name__}: {str(ie)[:200]}"
                                )

                # Pinecone upserts are grouped by namespace (tenant+client)
                # within the batch — Pinecone's upsert API takes one
                # namespace per call.
                pinecone_pending: dict[str, list[VectorUpsert]] = {}

                # strict=True: batch and vecs are equal-length by construction
                # (texts is 1:1 with batch; embed_batch_concurrent returns one
                # vector per text in order, and the fallback appends one entry
                # per text). A length mismatch would silently misalign
                # embeddings to the wrong chunk — fail loud instead.
                for item, emb in zip(batch, vecs, strict=True):
                    if emb is None:
                        continue
                    try:
                        result.embedded += 1
                        db.execute(delete_sql, {
                            "t": str(self.tenant_id),
                            "k": source_kind,
                            "s": item["src_id"],
                            "i": item["chunk_index"],
                        })
                        db.execute(insert_sql, {
                            "tenant_id": str(self.tenant_id),
                            "client_id": str(item["client_id"]) if item["client_id"] else None,
                            "source_kind": source_kind,
                            "source_id": item["src_id"],
                            "chunk_index": item["chunk_index"],
                            "total_chunks": item["total_chunks"],
                            "content": item["content"],
                            "content_hash": item["content_hash"],
                            "content_chars": len(item["content"]),
                            "embedding": emb,
                            "embedding_dim": len(emb),
                            "embedding_model": self.client.model_id,
                            "metadata": _to_json(item["extra_meta"]),
                        })
                        result.persisted += 1
                        pending[0] += 1
                        # Queue Pinecone upsert for this chunk.
                        if self.pinecone is not None:
                            ns = namespace_for(self.tenant_id, item["client_id"])
                            pinecone_pending.setdefault(ns, []).append(VectorUpsert(
                                id=f"cip-{source_kind}-{item['src_id']}-{item['chunk_index']}",
                                values=[float(x) for x in emb],
                                metadata={
                                    "tenant_id": str(self.tenant_id),
                                    "client_id": (
                                        str(item["client_id"])
                                        if item["client_id"] else ""
                                    ),
                                    "source_kind": source_kind,
                                    "source_id": item["src_id"],
                                    "chunk_index": int(item["chunk_index"]),
                                    "total_chunks": int(item["total_chunks"]),
                                    "content_chars": len(item["content"]),
                                    "content_hash": item["content_hash"],
                                    "embedding_model": self.client.model_id,
                                    "content": item["content"][:_PINECONE_CONTENT_CAP],
                                },
                            ))
                        if pending[0] >= self.commit_every:
                            db.commit()
                            apply_tenant_context(db, self.tenant_id)
                            pending[0] = 0
                    except Exception as e:  # noqa: BLE001
                        result.errors += 1
                        if len(result.first_errors) < 5:
                            result.first_errors.append(
                                f"db-write {item['src_id']}#{item['chunk_index']}: "
                                f"{type(e).__name__}: {str(e)[:200]}"
                            )
                        db.rollback()
                        apply_tenant_context(db, self.tenant_id)

                # Pinecone upsert pass — fire once per namespace per
                # batch. Failures here are NON-fatal: Postgres is the
                # canonical store; the backfill script can repair drift.
                if self.pinecone is not None and pinecone_pending:
                    for ns, vectors in pinecone_pending.items():
                        try:
                            self.pinecone.upsert(namespace=ns, vectors=vectors)
                            result.pinecone_upserted += len(vectors)
                        except (PineconeError, Exception) as pe:  # noqa: BLE001
                            result.pinecone_errors += len(vectors)
                            if len(result.first_errors) < 5:
                                result.first_errors.append(
                                    f"pinecone-upsert ns={ns} batch={len(vectors)}: "
                                    f"{type(pe).__name__}: {str(pe)[:200]}"
                                )
                batch.clear()

            for row in rows:
                src_id = str(row[source_id_col])
                content = row[text_col]
                if not isinstance(content, str) or not content.strip():
                    continue
                client_id = row.get(client_id_col)
                extra_meta = {
                    k: row[k] for k in extra_metadata_keys
                    if k in row and row[k] is not None
                }
                try:
                    chunks = chunk_text(content, self.chunk_spec)
                    if not chunks:
                        continue
                    result.chunked += len(chunks)
                    total = len(chunks)
                    for idx, chunk_content in enumerate(chunks):
                        ch_hash = hashlib.sha256(
                            chunk_content.encode("utf-8")
                        ).hexdigest()
                        # Skip-unchanged check (DB SELECT, fast).
                        existing = db.execute(skip_sql, {
                            "t": str(self.tenant_id),
                            "k": source_kind,
                            "s": src_id,
                            "i": idx,
                            "h": ch_hash,
                        }).first()
                        if existing:
                            result.skipped_unchanged += 1
                            continue
                        batch.append({
                            "src_id": src_id,
                            "client_id": client_id,
                            "chunk_index": idx,
                            "total_chunks": total,
                            "content": chunk_content,
                            "content_hash": ch_hash,
                            "extra_meta": extra_meta,
                        })
                        if len(batch) >= self.embed_batch_size:
                            flush_batch()
                except Exception as e:  # noqa: BLE001
                    result.errors += 1
                    if len(result.first_errors) < 5:
                        result.first_errors.append(
                            f"row {src_id}: {type(e).__name__}: {str(e)[:200]}"
                        )
                    db.rollback()
                    apply_tenant_context(db, self.tenant_id)

            # Final flush — any chunks still buffered.
            flush_batch()
            db.commit()

        result.elapsed_s = time.monotonic() - start
        return result


def _to_json(d: Mapping[str, Any]) -> str:
    import json

    def _default(o: object) -> object:
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return str(o)
    return json.dumps(d, default=_default)
