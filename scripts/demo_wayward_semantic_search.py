# foundry: kind=script domain=client-intelligence-platform
"""Demo — run real Wayward semantic-search queries against
cip_knowledge_chunks (Layer 2 / Path 2 of the four-access-paths).

Per PM scope d46f4b37 (Wayward Layer 2 instance). Useful for:
  - Sanity-check that Layer 2 actually returns relevant content
    after a backfill
  - Demo material for "what can we now ask CIP that we couldn't before"
  - Smoke regression — runs identically on each invocation

Reads-only. Safe to run against prod anytime.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        python scripts/demo_wayward_semantic_search.py
"""
from __future__ import annotations

import os
import sys
import textwrap

from sqlalchemy import create_engine

from cip.integration_mesh.clients import EmbeddingClient, RerankerClient
from cip.integration_mesh.knowledge import KnowledgeRetriever
from cip.integration_mesh.wayward_constants import ECOMLEVER_TENANT_ID


# Realistic-ish business questions a user might ask of Wayward data.
DEMO_QUERIES: list[tuple[str, str | None]] = [
    # (query_text, restrict_to_source_kind or None for all)
    (
        "customer asking about Creator Connections billing or invoices",
        "cip_ticket_comment",
    ),
    (
        "campaign performance review with brand partner",
        "cip_engagement_note",
    ),
    (
        "scheduled discovery call with a potential agency partner",
        "cip_engagement_meeting",
    ),
    (
        "customer complaint about credit card processing fees",
        None,  # any kind
    ),
    (
        "China referral introducing a new brand to Wayward",
        None,
    ),
]


def _safe_print(s: str) -> None:
    """Print, falling back to ASCII-replace for terminals (Windows cp1252)
    that can't encode some Unicode characters in CIP body content
    (e.g., U+034F COMBINING GRAPHEME JOINER from email signatures)."""
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "replace").decode("ascii"))


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)

    emb_client = EmbeddingClient()
    rer_client = RerankerClient()
    retriever = KnowledgeRetriever(
        engine, emb_client, reranker_client=rer_client,
    )

    for query, kind in DEMO_QUERIES:
        _safe_print("=" * 72)
        _safe_print(f"QUERY: {query!r}")
        if kind:
            _safe_print(f"  (restricted to source_kind={kind!r})")
        kinds = [kind] if kind else None
        hits = retriever.search(
            tenant_id=ECOMLEVER_TENANT_ID,
            query=query,
            top_k=5,
            source_kinds=kinds,
            rerank=True,
        )
        if not hits:
            _safe_print("  (no hits — table may not be backfilled for this kind yet)")
            continue
        for i, h in enumerate(hits, 1):
            body_preview = textwrap.shorten(
                h.content.replace("\n", " ").strip(),
                width=200, placeholder="...",
            )
            sim_str = f"{h.similarity:.4f}"
            score_str = f"{h.score:.4f}" if h.reranked else "-"
            _safe_print(
                f"  [{i}] sim={sim_str} rer={score_str} "
                f"kind={h.source_kind} src={h.source_id} "
                f"chunk={h.chunk_index}"
            )
            _safe_print(f"      {body_preview}")
            if h.metadata:
                meta = {k: v for k, v in h.metadata.items() if v}
                if meta:
                    _safe_print(f"      meta: {meta}")
        _safe_print("")
    _safe_print(f"\nEmbedding client stats: {emb_client.stats()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
