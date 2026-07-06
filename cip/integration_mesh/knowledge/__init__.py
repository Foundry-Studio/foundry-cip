# foundry: kind=service domain=client-intelligence-platform
"""CIP semantic-search / Layer 2 pipeline.

Per PM scope 2d6390fa (tenant-agnostic capability):
  - chunker: split long text into ~500-token windows with overlap
  - indexer: read CIP rows, chunk, embed, upsert into cip_knowledge_chunks
  - retriever: hybrid BM25 + cosine-similarity + optional reranker

For v1 storage decision (cip_19_knowledge_chunks): Postgres-native
double precision[] columns. Cosine similarity via cip_cosine_similarity
SQL function (also defined in cip_19). pgvector / Pinecone are
deferred upgrades.
"""
from cip.integration_mesh.knowledge.chunker import ChunkSpec, chunk_text
from cip.integration_mesh.knowledge.indexer import (
    IndexResult,
    KnowledgeIndexer,
)
from cip.integration_mesh.knowledge.retriever import (
    KnowledgeRetriever,
    RetrievalResult,
)

__all__ = [
    "chunk_text",
    "ChunkSpec",
    "KnowledgeIndexer",
    "IndexResult",
    "KnowledgeRetriever",
    "RetrievalResult",
]
