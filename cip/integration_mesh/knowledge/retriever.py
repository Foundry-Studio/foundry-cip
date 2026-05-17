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

import time
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cip.integration_mesh.clients import EmbeddingClient, RerankerClient
from cip.integration_mesh.tenant_context import apply_tenant_context


@dataclass
class RetrievalResult:
    source_kind: str
    source_id: str
    chunk_index: int
    content: str
    similarity: float        # cosine similarity from pgsql
    score: float             # = similarity OR reranker score if reranked
    metadata: dict
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
    ) -> None:
        self.engine = engine
        self.client = embedding_client
        self.reranker = reranker_client

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

        if rerank and self.reranker and candidates:
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
            except Exception:
                # Reranker failure → graceful degrade to similarity ranking
                pass
        return candidates[:top_k]
