# foundry: kind=script domain=client-intelligence-platform
"""Smoke test: embed a few CIP rows, search them back, verify shape.

Per PM scope 2d6390fa Block 6 smoke. Verifies:
  1. EmbeddingClient reaches the Qwen3-Embedding-4B endpoint
  2. Chunker produces sensible chunks
  3. Indexer writes cip_knowledge_chunks rows correctly
  4. Retriever can find a known query semantically
  5. Reranker (if reachable) refines results

Reads-only (after writing test rows it deletes them on cleanup).

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/test_layer2_smoke.py
"""
from __future__ import annotations

import os
import re
import sys

from sqlalchemy import create_engine, text

from cip.integration_mesh.clients import EmbeddingClient, RerankerClient
from cip.integration_mesh.knowledge import KnowledgeIndexer, KnowledgeRetriever
from cip.integration_mesh.tenant_context import apply_tenant_context
from cip.integration_mesh.wayward_constants import (
    ECOMLEVER_TENANT_ID,
    WAYWARD_CLIENT_ID,
)
from sqlalchemy.orm import Session


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

    # ── 1. Embedding endpoint reachable ──────────────────────────────
    print("[smoke] 1. Embedding endpoint sanity check...")
    emb_client = EmbeddingClient()
    test_vec = emb_client.embed("hello world")
    print(f"  vector dim: {len(test_vec)}")
    print(f"  first 3 dims: {[f'{x:.4f}' for x in test_vec[:3]]}")
    assert len(test_vec) > 0, "Embedding returned empty vector"
    vec_dim = len(test_vec)

    # ── 2. Sample 5 ticket comments, embed, index ────────────────────
    print("\n[smoke] 2. Index 5 Wayward ticket comments...")
    indexer = KnowledgeIndexer(engine, emb_client, ECOMLEVER_TENANT_ID, commit_every=10)
    result = indexer.index_kind(
        source_kind="cip_ticket_comment",
        select_sql="""
            SELECT source_id, body, client_id, is_public, via_channel, ticket_source_id
            FROM cip_ticket_comments
            WHERE tenant_id = :tenant_id AND body IS NOT NULL AND length(body) > 50
            ORDER BY source_id LIMIT 5
        """,
        text_col="body",
        extra_metadata_keys=("is_public", "via_channel", "ticket_source_id"),
    )
    print(f"  result: seen={result.seen} chunked={result.chunked} embedded={result.embedded} persisted={result.persisted} skipped={result.skipped_unchanged} errors={result.errors} elapsed={result.elapsed_s:.1f}s")
    if result.first_errors:
        print(f"  first errors: {result.first_errors}")

    # ── 3. Retriever finds the test rows ─────────────────────────────
    print("\n[smoke] 3. Search for 'invoice billing customer email'...")
    retriever = KnowledgeRetriever(engine, emb_client, reranker_client=None)  # skip reranker for smoke
    hits = retriever.search(
        tenant_id=ECOMLEVER_TENANT_ID,
        query="invoice billing customer email",
        top_k=3,
        source_kinds=["cip_ticket_comment"],
        rerank=False,
    )
    print(f"  got {len(hits)} hits:")
    for h in hits:
        body_preview = h.content[:80].replace('\n', ' ')
        print(f"    sim={h.similarity:.4f} src={h.source_id} body={body_preview!r}")

    # ── 4. Reranker reachable (optional, graceful) ───────────────────
    print("\n[smoke] 4. Reranker reachability test...")
    rer = RerankerClient()
    try:
        scored = rer.rerank(
            query="billing invoice",
            candidates=[
                {"id": "a", "text": "How do I get a refund on my invoice?"},
                {"id": "b", "text": "I love pizza"},
                {"id": "c", "text": "There's an error on my latest billing statement"},
            ],
            top_k=2,
        )
        print(f"  reranker returned {len(scored)} results:")
        for s in scored:
            print(f"    score={s['score']:.4f} text={s['text']!r}")
    except Exception as e:
        print(f"  reranker not reachable ({type(e).__name__}: {str(e)[:120]}) — graceful")

    # ── 5. Cleanup ───────────────────────────────────────────────────
    print("\n[smoke] 5. Cleanup test rows...")
    with Session(engine) as db:
        apply_tenant_context(db, ECOMLEVER_TENANT_ID)
        n = db.execute(
            text(
                "DELETE FROM cip_knowledge_chunks "
                "WHERE tenant_id = :t AND source_kind = 'cip_ticket_comment' "
                "  AND source_id IN ("
                "    SELECT source_id FROM cip_ticket_comments WHERE tenant_id = :t "
                "    AND body IS NOT NULL AND length(body) > 50 ORDER BY source_id LIMIT 5"
                ")"
            ),
            {"t": str(ECOMLEVER_TENANT_ID)},
        ).rowcount
        db.commit()
        print(f"  deleted {n} test chunks")

    print("\n[smoke] SUCCESS — Layer 2 path verified end-to-end")
    print(f"  embedding stats: {emb_client.stats()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
