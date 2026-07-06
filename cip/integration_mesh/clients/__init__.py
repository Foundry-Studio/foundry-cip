# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Thin HTTP clients for external services CIP depends on.

Per PM decision 2026-05-17 (Layer 2 wiring v1, option A): CIP keeps
its own thin HTTP wrappers rather than importing from the monorepo's
`src/services/`. Preserves foundry-cip's standalone library shape.

Clients:
  - embedding.EmbeddingClient — Qwen3-Embedding-4B via Ollama with
    OpenRouter fallback.
  - reranker.RerankerClient — Qwen3-Reranker-4B via local llama-server.
  - (future) pinecone.PineconeClient — if/when we add Pinecone storage.

For v1, vectors are stored in Postgres (cip_knowledge_chunks table,
double precision[] column). pgvector / Pinecone are deferred upgrades.
"""
from cip.integration_mesh.clients.embedding import EmbeddingClient, EmbeddingError
from cip.integration_mesh.clients.pinecone import (
    PineconeClient,
    PineconeError,
    VectorUpsert,
    namespace_for,
)
from cip.integration_mesh.clients.reranker import RerankerClient, RerankerError

__all__ = [
    "EmbeddingClient", "EmbeddingError",
    "RerankerClient", "RerankerError",
    "PineconeClient", "PineconeError", "VectorUpsert", "namespace_for",
]
