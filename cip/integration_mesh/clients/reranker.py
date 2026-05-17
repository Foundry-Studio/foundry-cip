# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Thin HTTP client for Qwen3-Reranker-4B via corsair-pc llama-server.

Per PM scope 2d6390fa (Layer 2 wiring v1) + option A decision
(2026-05-17): CIP keeps its own thin wrapper rather than importing
from the monorepo's src/services/reranker_client.

Primary backend: llama-server with Qwen3-Reranker-4B Q4_K_M on
corsair-pc RTX 3060, port 8082. Tunneled hostname
https://rerank-corsair.foundrytunnel.dev.

Per D-166 (2026-05-17): the monorepo migrated reranker calls from
in-process FlashRank + MiniLM to this HTTP endpoint. CIP follows the
same pattern.

Config via env vars:
  CIP_RERANKER_URL       Base URL (default
                         http://100.93.197.87:8082)
  CIP_RERANKER_TIMEOUT_S Per-request timeout (default 30)
"""
from __future__ import annotations

import os
from typing import Any

import httpx


class RerankerError(RuntimeError):
    """Raised when the reranker endpoint returns an error."""


class RerankerClient:
    """Cross-encoder re-rank candidates against a query.

    Usage:
        client = RerankerClient()
        scored = client.rerank(
            query="Wayward billing issue",
            candidates=[
                {"id": "c1", "text": "..."},
                {"id": "c2", "text": "..."},
            ],
        )
        # scored is list of {id, text, score} sorted by score desc
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.url = (
            url
            or os.environ.get("CIP_RERANKER_URL")
            or "http://100.93.197.87:8082"
        )
        self.timeout_s = float(
            timeout_s
            or os.environ.get("CIP_RERANKER_TIMEOUT_S")
            or 30.0
        )

    def rerank(
        self,
        *,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Re-rank ``candidates`` by relevance to ``query``.

        Each candidate must have a ``text`` field. Returns the same
        list with ``score`` added, sorted descending by score.
        Optionally truncated to ``top_k`` results.
        """
        if not query or not candidates:
            return []
        texts = [
            c.get("text", "") if isinstance(c, dict) else ""
            for c in candidates
        ]
        try:
            r = httpx.post(
                f"{self.url}/v1/rerank",
                json={
                    "model": "qwen3-reranker-4b",
                    "query": query,
                    "documents": texts,
                },
                timeout=self.timeout_s,
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise RerankerError(
                f"Reranker HTTP error: {type(exc).__name__}: {str(exc)[:200]}"
            ) from exc

        data = r.json()
        results = data.get("results") or []
        # llama-server /v1/rerank returns [{"index": int, "relevance_score": float}, ...]
        scored = []
        for entry in results:
            idx = entry.get("index")
            score = entry.get("relevance_score", 0.0)
            if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
                continue
            row = dict(candidates[idx])
            row["score"] = float(score)
            scored.append(row)
        scored.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        if top_k is not None and top_k > 0:
            scored = scored[:top_k]
        return scored
