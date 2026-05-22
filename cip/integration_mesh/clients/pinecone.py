# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Thin Pinecone client for CIP-dedicated index.

Per PM decision d83c7e1d (CIP Hard Split, 2026-05-19): CIP owns its
own Pinecone index — `foundry-cip` at 2,560 dimensions (matching the
native Qwen3-Embedding-4B output). Tenants isolated via namespace
pattern `cip__{tenant_id}__{client_id}` so a single Pinecone index
serves all CIP tenants while keeping data-plane separation clean.

Config via env vars:
  CIP_PINECONE_API_KEY      Pinecone API key
  CIP_PINECONE_INDEX_HOST   Index host URL
  CIP_PINECONE_INDEX_NAME   Logical name (default 'foundry-cip')
  CIP_PINECONE_TIMEOUT_S    Per-request timeout (default 30)

Bridge note: Foundry-Agent-System has its own Pinecone setup
(`foundry-agent-system` index, 1024d, used for agent knowledge +
memory). CIP does NOT share that index — hard split per decision
d83c7e1d. Foundry agents that need CIP content go through the
foundry_mcp_cip_semantic_search MCP tool (Bridge pattern).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx


class PineconeError(RuntimeError):
    """Raised on Pinecone API failure."""


@dataclass
class VectorUpsert:
    """One vector to upsert."""
    id: str
    values: list[float]
    metadata: dict[str, Any]


def namespace_for(tenant_id: UUID | str, client_id: UUID | str | None = None) -> str:
    """Canonical namespace pattern: cip__{tenant_id}__{client_id_or_default}.

    Tenants always have a namespace. When client_id is None (tenant-level
    content without client scoping), the namespace is
    `cip__{tenant_id}___tenant` to keep the pattern uniform.
    """
    if client_id is None:
        return f"cip__{tenant_id}___tenant"
    return f"cip__{tenant_id}__{client_id}"


class PineconeClient:
    """Thin HTTP client for the CIP Pinecone index."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        index_host: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("CIP_PINECONE_API_KEY", "")
        self.index_host = (
            index_host or os.environ.get("CIP_PINECONE_INDEX_HOST", "")
        ).rstrip("/")
        self.timeout_s = float(
            timeout_s or os.environ.get("CIP_PINECONE_TIMEOUT_S") or 30.0
        )
        if not self.api_key or not self.index_host:
            raise PineconeError(
                "CIP_PINECONE_API_KEY and CIP_PINECONE_INDEX_HOST must be set"
            )
        self._headers = {
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def upsert(
        self,
        *,
        namespace: str,
        vectors: list[VectorUpsert],
    ) -> dict[str, Any]:
        """Upsert a batch of vectors into a namespace.

        Pinecone upsert is idempotent on the vector id — re-running with
        the same id overwrites the previous vector + metadata.
        """
        if not vectors:
            return {"upsertedCount": 0}
        body = {
            "namespace": namespace,
            "vectors": [
                {"id": v.id, "values": v.values, "metadata": v.metadata}
                for v in vectors
            ],
        }
        try:
            r = httpx.post(
                f"{self.index_host}/vectors/upsert",
                headers=self._headers,
                json=body,
                timeout=self.timeout_s,
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise PineconeError(
                f"upsert failed: {type(exc).__name__}: {str(exc)[:300]}"
            ) from exc
        return r.json()

    def query(
        self,
        *,
        namespace: str,
        vector: list[float],
        top_k: int = 10,
        filter: dict[str, Any] | None = None,
        include_metadata: bool = True,
    ) -> list[dict[str, Any]]:
        """Query for nearest neighbors in a namespace.

        Returns list of {id, score, metadata} dicts ordered by score desc.
        """
        body: dict[str, Any] = {
            "namespace": namespace,
            "vector": vector,
            "topK": top_k,
            "includeMetadata": include_metadata,
        }
        if filter:
            body["filter"] = filter
        try:
            r = httpx.post(
                f"{self.index_host}/query",
                headers=self._headers,
                json=body,
                timeout=self.timeout_s,
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise PineconeError(
                f"query failed: {type(exc).__name__}: {str(exc)[:300]}"
            ) from exc
        return r.json().get("matches", [])

    def delete_namespace(self, namespace: str) -> dict[str, Any]:
        """Delete all vectors in a namespace (tenant offboarding)."""
        body = {"deleteAll": True, "namespace": namespace}
        try:
            r = httpx.post(
                f"{self.index_host}/vectors/delete",
                headers=self._headers,
                json=body,
                timeout=self.timeout_s,
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise PineconeError(
                f"delete_namespace failed: {type(exc).__name__}: {str(exc)[:300]}"
            ) from exc
        return r.json()

    def delete(self, *, namespace: str, ids: list[str]) -> dict[str, Any]:
        """Delete specific vector ids in a namespace.

        Used for surgical cleanup — e.g., removing orphan vectors when
        their backing cip_files row has been deleted. Pinecone accepts
        up to 1000 ids per call; chunks larger requests automatically.
        """
        if not ids:
            return {}
        all_results: list[dict[str, Any]] = []
        # 1000-id chunking per Pinecone limit
        for i in range(0, len(ids), 1000):
            batch = ids[i:i + 1000]
            body = {"ids": batch, "namespace": namespace}
            try:
                r = httpx.post(
                    f"{self.index_host}/vectors/delete",
                    headers=self._headers,
                    json=body,
                    timeout=self.timeout_s,
                )
                r.raise_for_status()
                all_results.append(r.json())
            except httpx.HTTPError as exc:
                raise PineconeError(
                    f"delete failed (batch of {len(batch)}): "
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {"batches": len(all_results), "ids_deleted": len(ids)}

    def describe_index_stats(
        self, *, filter: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Get index stats — per-namespace vector counts."""
        body: dict[str, Any] = {}
        if filter:
            body["filter"] = filter
        try:
            r = httpx.post(
                f"{self.index_host}/describe_index_stats",
                headers=self._headers,
                json=body,
                timeout=self.timeout_s,
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise PineconeError(
                f"describe_index_stats failed: {type(exc).__name__}: {str(exc)[:300]}"
            ) from exc
        return r.json()
