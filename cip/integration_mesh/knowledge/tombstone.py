# foundry: kind=service domain=client-intelligence-platform touches=knowledge
"""Remove a file's derived chunks when the file is tombstoned.

CIP-SPEC-014 ruling 3, as amended by Tim 2026-09-04 (PM decision 7d1c0148,
option (a)): tombstoning a file DELETES its derived chunks from both stores.
The ``cip_files`` row survives with ``tombstoned_at``, ``r2_path`` and
``sha256``, so the audit trail records exactly what was removed and when.

WHY DELETION RATHER THAN A RETRIEVAL FILTER. The contract originally said
"every retrieval path filters tombstoned chunks". That was unimplementable:
the retriever queries ``cip_knowledge_chunks`` directly and never joins
``cip_files``, where ``tombstoned_at`` lives, so there was no predicate to add.
Deleting the derived rows makes the property STRUCTURAL instead — retrieval
needs no change, and no retrieval path written in future can forget to honour
it. Chunks are derived data; if the file comes back, re-ingest regenerates
them.

TWO THINGS THIS MODULE EXISTS TO GET RIGHT, both of which look fine in a
happy-path test:

1. SCOPE. ``cip_knowledge_chunks`` has a second producer writing row-derived
   chunks under cip_ticket_comment / cip_engagement_* / cip_ticket. Every
   statement here is scoped by ``source_kind`` as well as ``source_id``. An
   unscoped delete would destroy that producer's rows.

2. ORDER. Pinecone is deleted BEFORE Postgres, deliberately. The two stores
   are separate calls and the Pinecone one is the one that gets forgotten or
   fails. Deleting Postgres first would, on a Pinecone failure, leave the
   database saying the chunks are gone while a vector search still returns
   them — retrievable content that nothing knows about, which is worse than
   not deleting at all because it looks correct. This order fails safe: both
   stores keep the rows, the error is raised, and a retry is well-defined.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from cip.integration_mesh.clients.pinecone import PineconeClient, namespace_for

logger = logging.getLogger(__name__)


@dataclass
class PurgeResult:
    """What a purge actually did. Counted, so a run can report rather than
    merely finish."""

    source_id: str
    source_kind: str
    chunks_found: int = 0
    pinecone_deleted: int = 0
    postgres_deleted: int = 0
    vector_ids: list[str] = field(default_factory=list)


def vector_id_for(source_kind: str, source_id: str, chunk_index: int) -> str:
    """The id KnowledgeIndexer upserts under.

    Deletion has to reconstruct exactly what upsert produced. The convention
    lives here so the two cannot drift apart silently; a mismatch would leave
    orphaned vectors that no delete ever finds.
    """
    return f"cip-{source_kind}-{source_id}-{chunk_index}"


def purge_file_chunks(
    db: Session,
    *,
    tenant_id: UUID,
    source_kind: str,
    source_id: str,
    client_id: UUID | None = None,
    pinecone: PineconeClient | None = None,
) -> PurgeResult:
    """Delete every chunk derived from one file, from both stores.

    Args:
        db: session already carrying tenant context.
        tenant_id: owning tenant.
        source_kind: the DOCUMENT source_kind. Scoping by it is what keeps this
            from touching the row-derived producer's chunks.
        source_id: the file's identifier as stored on the chunks.
        client_id: used to resolve the Pinecone namespace.
        pinecone: when None, Postgres is cleaned and the caller is told no
            vectors were touched. That is honest, not silent: ``PurgeResult``
            reports ``pinecone_deleted=0`` and the log line says so, because a
            Postgres-only purge leaves the vectors retrievable and somebody has
            to know that.

    Raises:
        Whatever the Pinecone client raises. Deliberately not swallowed: this
        runs before the Postgres delete, so a raise here leaves both stores
        consistent and the operation safely retryable.
    """
    rows = db.execute(
        text(
            "SELECT chunk_index FROM cip_knowledge_chunks "
            "WHERE tenant_id = :t AND source_kind = :sk AND source_id = :si "
            "ORDER BY chunk_index"
        ),
        {"t": str(tenant_id), "sk": source_kind, "si": source_id},
    ).all()

    result = PurgeResult(source_id=source_id, source_kind=source_kind,
                         chunks_found=len(rows))
    if not rows:
        return result

    result.vector_ids = [
        vector_id_for(source_kind, source_id, int(r[0])) for r in rows
    ]

    # Pinecone FIRST. See the module docstring: this order is what makes a
    # partial failure safe rather than invisible.
    if pinecone is not None:
        pinecone.delete(
            namespace=namespace_for(tenant_id, client_id),
            ids=result.vector_ids,
        )
        result.pinecone_deleted = len(result.vector_ids)
    else:
        logger.warning(
            "purging %d chunks for %s without a Pinecone client; vectors are "
            "NOT deleted and remain retrievable (tenant=%s, source_kind=%s)",
            len(rows), source_id, tenant_id, source_kind,
        )

    deleted = db.execute(
        text(
            "DELETE FROM cip_knowledge_chunks "
            "WHERE tenant_id = :t AND source_kind = :sk AND source_id = :si"
        ),
        {"t": str(tenant_id), "sk": source_kind, "si": source_id},
    )
    result.postgres_deleted = int(getattr(deleted, "rowcount", 0) or 0)

    logger.info(
        "purged chunks for %s: found=%d pinecone_deleted=%d postgres_deleted=%d "
        "(tenant=%s, source_kind=%s)",
        source_id, result.chunks_found, result.pinecone_deleted,
        result.postgres_deleted, tenant_id, source_kind,
    )
    return result


def count_disagreements(
    db: Session,
    *,
    tenant_id: UUID,
    pinecone: PineconeClient,
    client_id: UUID | None = None,
) -> dict[str, int]:
    """Compare chunk count in Postgres against vector count in Pinecone.

    The invariant is that for a tenant's namespace the two agree. Drift means
    one store has content the other does not, which shows up as either a
    retrieval result pointing at a chunk that no longer exists, or a chunk that
    can never be retrieved. Both are silent.

    Returns both numbers and their difference rather than a boolean, because
    the SIZE of the drift is what tells you whether it is a single failed write
    or a whole run that half-landed.
    """
    pg = int(
        db.execute(
            text(
                "SELECT count(*) FROM cip_knowledge_chunks WHERE tenant_id = :t"
            ),
            {"t": str(tenant_id)},
        ).scalar()
        or 0
    )
    stats = pinecone.describe_index_stats()
    ns = namespace_for(tenant_id, client_id)
    namespaces = stats.get("namespaces") or {}
    vectors = int((namespaces.get(ns) or {}).get("vectorCount", 0))

    out = {"postgres_chunks": pg, "pinecone_vectors": vectors, "difference": pg - vectors}
    if pg != vectors:
        logger.warning(
            "chunk/vector disagreement for tenant=%s namespace=%s: "
            "postgres=%d pinecone=%d difference=%d",
            tenant_id, ns, pg, vectors, pg - vectors,
        )
    return out
