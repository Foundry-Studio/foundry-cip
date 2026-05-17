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
from dataclasses import dataclass, field
from typing import Iterable, Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cip.integration_mesh.clients import EmbeddingClient
from cip.integration_mesh.knowledge.chunker import chunk_text, ChunkSpec
from cip.integration_mesh.tenant_context import apply_tenant_context


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
    ) -> None:
        self.engine = engine
        self.client = embedding_client
        self.tenant_id = tenant_id
        self.chunk_spec = chunk_spec or ChunkSpec()
        self.commit_every = commit_every

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

        with Session(self.engine) as db:
            apply_tenant_context(db, self.tenant_id)
            rows = db.execute(
                text(select_sql), {"tenant_id": str(self.tenant_id)}
            ).mappings().all()
            result.seen = len(rows)

            pending = 0
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
                        # Skip-unchanged check
                        existing = db.execute(
                            text(
                                "SELECT 1 FROM cip_knowledge_chunks "
                                "WHERE tenant_id = :t AND source_kind = :k "
                                "AND source_id = :s AND chunk_index = :i "
                                "AND content_hash = :h"
                            ),
                            {
                                "t": str(self.tenant_id),
                                "k": source_kind,
                                "s": src_id,
                                "i": idx,
                                "h": ch_hash,
                            },
                        ).first()
                        if existing:
                            result.skipped_unchanged += 1
                            continue
                        # Embed
                        emb = self.client.embed(chunk_content)
                        result.embedded += 1
                        # Upsert (delete+insert keeps it simple)
                        db.execute(
                            text(
                                "DELETE FROM cip_knowledge_chunks "
                                "WHERE tenant_id = :t AND source_kind = :k "
                                "AND source_id = :s AND chunk_index = :i"
                            ),
                            {
                                "t": str(self.tenant_id),
                                "k": source_kind,
                                "s": src_id,
                                "i": idx,
                            },
                        )
                        db.execute(
                            text(
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
                            ),
                            {
                                "tenant_id": str(self.tenant_id),
                                "client_id": str(client_id) if client_id else None,
                                "source_kind": source_kind,
                                "source_id": src_id,
                                "chunk_index": idx,
                                "total_chunks": total,
                                "content": chunk_content,
                                "content_hash": ch_hash,
                                "content_chars": len(chunk_content),
                                "embedding": emb,
                                "embedding_dim": len(emb),
                                "embedding_model": self.client.model_id,
                                "metadata": _to_json(extra_meta),
                            },
                        )
                        result.persisted += 1
                        pending += 1
                        if pending >= self.commit_every:
                            db.commit()
                            apply_tenant_context(db, self.tenant_id)
                            pending = 0
                except Exception as e:  # noqa: BLE001
                    result.errors += 1
                    if len(result.first_errors) < 5:
                        result.first_errors.append(
                            f"{src_id}: {type(e).__name__}: {str(e)[:200]}"
                        )
                    db.rollback()
                    apply_tenant_context(db, self.tenant_id)

            db.commit()

        result.elapsed_s = time.monotonic() - start
        return result


def _to_json(d: Mapping) -> str:
    import json
    def _default(o):
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return str(o)
    return json.dumps(d, default=_default)
