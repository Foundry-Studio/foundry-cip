# foundry: kind=service domain=client-intelligence-platform touches=knowledge
"""Write ``KnowledgeText`` from a connector run into both knowledge stores.

This is the body behind ``knowledge_hook.ingest_texts_noop``. Until 2026-09-04
that hook was an unconditional no-op: a connector could emit perfectly valid
KnowledgeText, the orchestrator would finalize and validate it, and then
nothing wrote anything. This is what makes document ingestion actually happen.

RELATIONSHIP TO KnowledgeIndexer. ``KnowledgeIndexer`` does the same
embed-and-dual-write but is driven the other way round: it PULLS rows out of
CIP tables, chunks them itself, and writes. This sink is PUSHED chunks that a
mapper already produced. They are two entry points to the same destination, not
two implementations of it, and the one thing that must never diverge between
them is the Pinecone vector id — so both call ``tombstone.vector_id_for``.
Getting that wrong would leave vectors no delete can ever find.

WHY IT COUNTS EVERYTHING. Per D-067 the orchestrator treats a non-validation
exception from this hook as NON-FATAL: it logs one warning and the run still
reports success. So anything this sink drops quietly is dropped for good. Every
partial failure is therefore counted on the result and logged at WARNING, and
the caller is expected to read those counts rather than trust that the run
finishing means the chunks landed.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from cip.integration_mesh.base import KnowledgeText
from cip.integration_mesh.clients.embedding import EmbeddingClient
from cip.integration_mesh.clients.pinecone import (
    PineconeClient,
    VectorUpsert,
    namespace_for,
)
from cip.integration_mesh.knowledge.tombstone import vector_id_for

logger = logging.getLogger(__name__)

_INSERT = text(
    "INSERT INTO cip_knowledge_chunks ("
    "  id, tenant_id, client_id, source_kind, source_id, chunk_index,"
    "  total_chunks, content, content_hash, content_chars, embedding,"
    "  embedding_dim, embedding_model, metadata, embedded_at, created_at,"
    "  updated_at"
    ") VALUES ("
    "  gen_random_uuid(), :tenant_id, :client_id, :source_kind, :source_id,"
    "  :chunk_index, :total_chunks, :content, :content_hash, :content_chars,"
    "  :embedding, :embedding_dim, :embedding_model, CAST(:metadata AS jsonb),"
    "  now(), now(), now()"
    ")"
)


@dataclass
class SinkResult:
    """What the sink actually did. Read these; do not infer success from the
    run completing."""

    received: int = 0
    embedded: int = 0
    postgres_written: int = 0
    pinecone_upserted: int = 0
    embed_failures: int = 0
    pinecone_failures: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return (
            self.embed_failures == 0
            and self.pinecone_failures == 0
            and self.postgres_written == self.received
        )


class KnowledgeChunkSink:
    """Callable sink for ``knowledge_hook.set_knowledge_sink``."""

    def __init__(
        self,
        *,
        db: Session,
        tenant_id: UUID,
        embedding_client: EmbeddingClient,
        source_kind: str,
        client_id: UUID | None = None,
        pinecone: PineconeClient | None = None,
    ) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.client = embedding_client
        self.source_kind = source_kind
        self.client_id = client_id
        self.pinecone = pinecone
        self.result = SinkResult()

    def __call__(self, texts: list[KnowledgeText]) -> None:
        if not texts:
            return
        self.result.received += len(texts)

        pending: list[VectorUpsert] = []
        for kt in texts:
            meta = dict(kt.metadata)
            source_id = str(meta.get("source_id", ""))
            chunk_index = int(str(meta.get("chunk_index", 0)))
            total_chunks = int(str(meta.get("total_chunks", len(texts))))

            try:
                vec = self.client.embed(kt.text)
            except Exception as e:  # noqa: BLE001
                # Counted and logged rather than skipped. A chunk missing from
                # both stores is indistinguishable from one that was never
                # meant to exist, which is why silence here is unacceptable.
                self.result.embed_failures += 1
                self._note(f"embed {source_id}#{chunk_index}: "
                           f"{type(e).__name__}: {str(e)[:200]}")
                logger.warning(
                    "embedding failed, chunk NOT indexed (tenant=%s source=%s "
                    "chunk=%d): %s", self.tenant_id, source_id, chunk_index, e,
                )
                continue
            self.result.embedded += 1

            self.db.execute(
                _INSERT,
                {
                    "tenant_id": str(self.tenant_id),
                    "client_id": str(self.client_id) if self.client_id else None,
                    "source_kind": self.source_kind,
                    "source_id": source_id,
                    "chunk_index": chunk_index,
                    "total_chunks": total_chunks,
                    "content": kt.text,
                    "content_hash": _content_hash(kt.text),
                    "content_chars": len(kt.text),
                    "embedding": vec,
                    "embedding_dim": len(vec),
                    "embedding_model": self.client.model_id,
                    "metadata": json.dumps(_jsonable(meta)),
                },
            )
            self.result.postgres_written += 1

            if self.pinecone is not None:
                pending.append(
                    VectorUpsert(
                        id=vector_id_for(self.source_kind, source_id, chunk_index),
                        values=[float(x) for x in vec],
                        metadata={
                            "tenant_id": str(self.tenant_id),
                            "client_id": str(self.client_id) if self.client_id else "",
                            "source_kind": self.source_kind,
                            "source_id": source_id,
                            "chunk_index": chunk_index,
                            "total_chunks": total_chunks,
                            "content_chars": len(kt.text),
                        },
                    )
                )

        if pending and self.pinecone is not None:
            ns = namespace_for(self.tenant_id, self.client_id)
            try:
                self.pinecone.upsert(namespace=ns, vectors=pending)
                self.result.pinecone_upserted += len(pending)
            except Exception as e:  # noqa: BLE001
                # The rows are already in Postgres. Saying so plainly matters:
                # the two stores now disagree, and count_disagreements() is the
                # check that will surface it.
                self.result.pinecone_failures += len(pending)
                self._note(f"pinecone upsert ns={ns} n={len(pending)}: "
                           f"{type(e).__name__}: {str(e)[:200]}")
                logger.warning(
                    "Pinecone upsert failed for %d vectors; those chunks are in "
                    "Postgres but NOT searchable by vector (tenant=%s ns=%s): %s",
                    len(pending), self.tenant_id, ns, e,
                )

    def _note(self, msg: str) -> None:
        if len(self.result.errors) < 20:
            self.result.errors.append(msg)


def _content_hash(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _jsonable(meta: dict[str, object]) -> dict[str, object]:
    """Metadata carries UUIDs and datetimes the orchestrator finalized."""
    out: dict[str, object] = {}
    for k, v in meta.items():
        out[k] = v if isinstance(v, str | int | float | bool | type(None)) else str(v)
    return out
