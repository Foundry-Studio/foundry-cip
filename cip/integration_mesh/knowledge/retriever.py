# foundry: kind=service domain=client-intelligence-platform
"""Retriever — semantic search over cip_knowledge_chunks.

Per PM scope 2d6390fa (Layer 2 wiring v1, tenant-agnostic capability).

v1 retrieval: embed query → SQL cosine similarity (cip_cosine_similarity
function from cip_19) → top-N candidates → (optional) reranker pass.

This is the Path 2 entry point for any agent/dashboard query that
wants "find me CIP content semantically similar to X". For exact-match
SQL queries, callers should use Path 1 (lens views or direct table
queries) — much faster, no embedding cost.

Usage:
    from cip.integration_mesh.knowledge import KnowledgeRetriever
    from cip.integration_mesh.clients import EmbeddingClient, RerankerClient

    retriever = KnowledgeRetriever(
        engine, EmbeddingClient(),
        reranker_client=RerankerClient(),  # optional
    )
    hits = retriever.search(
        tenant_id=tenant_uuid,
        query="customer asking about Creator Connections billing",
        top_k=10,
        source_kinds=['cip_ticket_comment','cip_engagement_note'],
    )
    for h in hits:
        print(h.source_kind, h.source_id, h.score, h.content[:80])
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cip.integration_mesh.clients import (
    EmbeddingClient,
    PineconeClient,
    PineconeError,
    RerankerClient,
    namespace_for,
)
from cip.integration_mesh.tenant_context import apply_tenant_context

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    source_kind: str
    source_id: str
    chunk_index: int
    content: str
    similarity: float        # cosine similarity from pgsql
    score: float             # = similarity OR reranker score if reranked
    metadata: dict[str, Any]
    client_id: str | None
    reranked: bool


class KnowledgeRetriever:
    """Semantic search over cip_knowledge_chunks."""

    def __init__(
        self,
        engine: Engine,
        embedding_client: EmbeddingClient,
        *,
        reranker_client: RerankerClient | None = None,
        pinecone_client: PineconeClient | None = None,
        prefer_pinecone: bool = True,
    ) -> None:
        """
        Args:
            engine: SQLAlchemy engine for cip_knowledge_chunks fallback.
            embedding_client: required for query embedding.
            reranker_client: optional; if provided, used for cross-encoder
                re-ranking of candidates.
            pinecone_client: optional; if provided AND prefer_pinecone,
                CIP-Pinecone is the hot-retrieval path. Postgres remains
                the fallback (and the canonical source-of-truth).
            prefer_pinecone: if True (default), query CIP-Pinecone first
                and fall back to Postgres cosine on Pinecone failure.
                Set False to force Postgres-only (e.g., for backfill audits).
        """
        self.engine = engine
        self.client = embedding_client
        self.reranker = reranker_client
        # Count of reranker failures this instance has degraded through.
        # Degradation is legitimate; invisible degradation is not, and a
        # counter is the cheapest thing that makes it visible to a caller.
        self.rerank_failures = 0
        self.pinecone = pinecone_client
        self.prefer_pinecone = prefer_pinecone

    def search(
        self,
        *,
        tenant_id: UUID,
        query: str,
        top_k: int = 10,
        source_kinds: Sequence[str] | None = None,
        client_id: UUID | str | None = None,
        rerank: bool = True,
        prefetch_multiplier: int = 5,
    ) -> list[RetrievalResult]:
        """Run a semantic search.

        Args:
            tenant_id: required (RLS scope)
            query: natural-language query
            top_k: final number of results to return
            source_kinds: restrict to e.g. ['cip_ticket_comment']
            client_id: optionally restrict to one client inside tenant
            rerank: if True and a reranker is configured, re-rank the
                top (top_k * prefetch_multiplier) candidates with
                Qwen3-Reranker-4B for better precision
            prefetch_multiplier: how many candidates to fetch before
                reranker prunes to top_k
        """
        if not query or not query.strip():
            return []
        q_emb = self.client.embed(query)
        prefetch = top_k * prefetch_multiplier if rerank and self.reranker else top_k

        # Per CIP-SPEC-010 hard-split: CIP-Pinecone is the hot-retrieval
        # path; Postgres cosine remains the fallback + canonical store.
        if self.prefer_pinecone and self.pinecone is not None:
            try:
                return self._search_pinecone(
                    tenant_id=tenant_id, query=query, q_emb=q_emb,
                    top_k=top_k, source_kinds=source_kinds,
                    client_id=client_id, rerank=rerank,
                    prefetch=prefetch,
                )
            except PineconeError:
                # Graceful fallback to Postgres cosine
                pass

        # Build the SQL with optional source_kind / client_id filters
        where = [
            "tenant_id = :tenant_id",
        ]
        params: dict[str, object] = {
            "tenant_id": str(tenant_id),
            "q_emb": q_emb,
            "limit": prefetch,
        }
        if source_kinds:
            placeholders = ",".join(f":sk_{i}" for i in range(len(source_kinds)))
            where.append(f"source_kind IN ({placeholders})")
            for i, sk in enumerate(source_kinds):
                params[f"sk_{i}"] = sk
        if client_id is not None:
            where.append("client_id = :client_id")
            params["client_id"] = str(client_id)
        sql = f"""
            SELECT
                source_kind, source_id, chunk_index, content,
                cip_cosine_similarity(embedding, CAST(:q_emb AS double precision[])) AS sim,
                metadata, client_id
            FROM cip_knowledge_chunks
            WHERE {' AND '.join(where)}
            ORDER BY sim DESC NULLS LAST
            LIMIT :limit
        """
        with Session(self.engine) as db:
            apply_tenant_context(db, tenant_id)
            rows = db.execute(text(sql), params).mappings().all()

        candidates: list[RetrievalResult] = []
        for r in rows:
            candidates.append(RetrievalResult(
                source_kind=r["source_kind"],
                source_id=r["source_id"],
                chunk_index=r["chunk_index"],
                content=r["content"],
                similarity=float(r["sim"]) if r["sim"] is not None else 0.0,
                score=float(r["sim"]) if r["sim"] is not None else 0.0,
                metadata=dict(r["metadata"] or {}),
                client_id=str(r["client_id"]) if r["client_id"] else None,
                reranked=False,
            ))

        return self._apply_rerank(
            query=query, candidates=candidates, top_k=top_k,
            rerank=rerank, tenant_id=tenant_id, path="postgres",
        )

    def _apply_rerank(
        self,
        *,
        query: str,
        candidates: list[RetrievalResult],
        top_k: int,
        rerank: bool,
        tenant_id: UUID,
        path: str,
    ) -> list[RetrievalResult]:
        """Re-rank ``candidates``, degrading VISIBLY if the reranker is down.

        Both retrieval paths (Postgres cosine and Pinecone) had a byte-identical
        copy of this block, each ending in a bare ``except Exception: pass``.
        Unifying them is not just tidiness: two copies meant two places to
        forget, and the duplication is why one copy carried an explanatory
        comment and the other carried nothing at all.

        Degrading to similarity order when the reranker fails is deliberate and
        correct — a ranking refinement being unavailable should not fail a
        search. What was wrong was doing it silently. The caller received
        measurably worse ordering with no signal, so a reranker down for weeks
        was indistinguishable from one that was working. The counter and the
        WARNING are the minimum that makes the degradation observable.
        """
        if not (rerank and self.reranker and candidates):
            return candidates[:top_k]
        try:
            rer_input = [
                {
                    "id": f"{c.source_kind}|{c.source_id}|{c.chunk_index}",
                    "text": c.content,
                    "candidate": c,
                }
                for c in candidates
            ]
            ranked = self.reranker.rerank(
                query=query, candidates=rer_input, top_k=top_k,
            )
            out: list[RetrievalResult] = []
            for rk in ranked:
                cand = rk["candidate"]
                cand.score = float(rk["score"])
                cand.reranked = True
                out.append(cand)
            return out
        except Exception as e:  # noqa: BLE001
            self.rerank_failures += 1
            logger.warning(
                "reranker failed on the %s path; degrading to similarity "
                "order (tenant=%s, candidates=%d, failures_this_instance=%d): "
                "%s: %s",
                path, tenant_id, len(candidates), self.rerank_failures,
                type(e).__name__, str(e)[:200],
            )
            return candidates[:top_k]

    def _search_pinecone(
        self,
        *,
        tenant_id: UUID,
        query: str,
        q_emb: list[float],
        top_k: int,
        source_kinds: Sequence[str] | None,
        client_id: UUID | str | None,
        rerank: bool,
        prefetch: int,
    ) -> list[RetrievalResult]:
        """CIP-Pinecone-first retrieval path (CIP-SPEC-010 hot path).

        Namespace resolution:
          - If client_id provided: single namespace `cip__{tenant}__{client}`
          - Else: caller-app handles cross-client aggregation; for v1 we
            error out — semantic search needs explicit (tenant, client)
            scoping for Stage 2 multi-tenant safety. Future: cross-client
            queries inside a tenant via multiple namespace queries +
            client-side merge.
        """
        assert self.pinecone is not None
        if client_id is None:
            # Stage 1 conservative: require client_id for Pinecone path.
            # Postgres fallback will handle tenant-wide queries.
            raise PineconeError("client_id required for Pinecone retrieval (Stage 1)")
        ns = namespace_for(tenant_id, client_id)
        # Build optional filter on source_kind
        pc_filter: dict[str, Any] | None = None
        if source_kinds:
            pc_filter = {"source_kind": {"$in": list(source_kinds)}}
        matches = self.pinecone.query(
            namespace=ns, vector=q_emb, top_k=prefetch,
            filter=pc_filter, include_metadata=True,
        )
        candidates: list[RetrievalResult] = []
        for m in matches:
            meta = m.get("metadata") or {}
            candidates.append(RetrievalResult(
                source_kind=str(meta.get("source_kind", "")),
                source_id=str(meta.get("source_id", "")),
                chunk_index=int(meta.get("chunk_index", 0)),
                content=str(meta.get("content", "")),
                similarity=float(m.get("score", 0.0)),
                score=float(m.get("score", 0.0)),
                metadata={k: v for k, v in meta.items() if k not in {
                    "source_kind", "source_id", "chunk_index", "content",
                    "content_hash", "embedding_model", "total_chunks",
                    "content_chars", "tenant_id", "client_id",
                }},
                client_id=str(meta.get("client_id", "")) or None,
                reranked=False,
            ))

        # Reranker pass (same contract as the Postgres path)
        return self._apply_rerank(
            query=query, candidates=candidates, top_k=top_k,
            rerank=rerank, tenant_id=tenant_id, path="pinecone",
        )
