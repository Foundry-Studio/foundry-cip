# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Thin HTTP client for Qwen3-Embedding-4B with OpenRouter fallback.

Per PM scope 2d6390fa (Layer 2 wiring v1, tenant-agnostic capability)
+ option A decision (2026-05-17): CIP keeps its own thin wrapper
rather than importing from the monorepo's src/services/embedding_client.

Primary backend: Ollama on the Foundry fleet (server-b at
http://100.100.10.110:11434 by default; tunneled hostname
https://ollama-gpu.foundrytunnel.dev for remote callers).

Fallback: OpenRouter's qwen/qwen3-embedding-4b model when primary
fails (timeout, 5xx, model-not-loaded). OpenRouter requires
OPENROUTER_API_KEY env.

Config via env vars:
  CIP_EMBEDDING_PRIMARY_URL    Ollama base URL (default
                               http://100.100.10.110:11434)
  CIP_EMBEDDING_PRIMARY_MODEL  Model name on Ollama
                               (default qwen3-embedding:4b-q8_0)
  CIP_EMBEDDING_FALLBACK_MODEL OpenRouter model id
                               (default qwen/qwen3-embedding-4b)
  OPENROUTER_API_KEY           Required only when fallback activates
  CIP_EMBEDDING_TIMEOUT_S      Per-request timeout (default 60)
"""
from __future__ import annotations

import concurrent.futures
import os
import time
from typing import Any

import httpx


class EmbeddingError(RuntimeError):
    """Raised when both primary and fallback embedding backends fail."""


class EmbeddingClient:
    """Generate embeddings for short text via Ollama primary + OpenRouter fallback.

    Usage:
        client = EmbeddingClient()
        vec = client.embed("Some text content")  # list[float]
        # vec dim == client.vector_dim (set after first successful call)
    """

    def __init__(
        self,
        *,
        primary_url: str | None = None,
        primary_model: str | None = None,
        fallback_model: str | None = None,
        timeout_s: float | None = None,
        openrouter_api_key: str | None = None,
    ) -> None:
        self.primary_url = (
            primary_url
            or os.environ.get("CIP_EMBEDDING_PRIMARY_URL")
            or "http://100.100.10.110:11434"
        )
        self.primary_model = (
            primary_model
            or os.environ.get("CIP_EMBEDDING_PRIMARY_MODEL")
            or "qwen3-embedding:4b-q8_0"
        )
        self.fallback_model = (
            fallback_model
            or os.environ.get("CIP_EMBEDDING_FALLBACK_MODEL")
            or "qwen/qwen3-embedding-4b"
        )
        self.timeout_s = float(
            timeout_s
            or os.environ.get("CIP_EMBEDDING_TIMEOUT_S")
            or 60.0
        )
        self.openrouter_api_key = (
            openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "")
        )
        # Populated on first successful call so callers can validate
        # downstream storage allocates the right column size
        self.vector_dim: int | None = None
        # Stats — bumped per call; useful for backfill scripts
        self.primary_successes = 0
        self.primary_failures = 0
        self.fallback_successes = 0
        self.fallback_failures = 0

    @property
    def model_id(self) -> str:
        """Canonical model identifier recorded with each embedding."""
        return f"qwen/qwen3-embedding-4b (primary={self.primary_model})"

    def embed(self, text: str) -> list[float]:
        """Return a single embedding vector for ``text``.

        Tries primary (Ollama) first; on any failure, falls back to
        OpenRouter. Raises EmbeddingError if both fail.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("EmbeddingClient.embed requires non-empty text")
        try:
            vec = self._embed_primary(text)
            self.primary_successes += 1
            self.vector_dim = len(vec)
            return vec
        except Exception as primary_exc:  # noqa: BLE001
            self.primary_failures += 1
            primary_err = (
                f"{type(primary_exc).__name__}: {str(primary_exc)[:200]}"
            )
            # Fall through to fallback
        try:
            vec = self._embed_fallback(text)
            self.fallback_successes += 1
            self.vector_dim = len(vec)
            return vec
        except Exception as fallback_exc:  # noqa: BLE001
            self.fallback_failures += 1
            raise EmbeddingError(
                f"Both embedding backends failed. primary: {primary_err}; "
                f"fallback: {type(fallback_exc).__name__}: "
                f"{str(fallback_exc)[:200]}"
            ) from fallback_exc

    def _embed_primary(self, text: str) -> list[float]:
        """Ollama /api/embeddings endpoint."""
        r = httpx.post(
            f"{self.primary_url}/api/embeddings",
            json={"model": self.primary_model, "prompt": text},
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        emb = data.get("embedding")
        if not isinstance(emb, list) or not emb:
            raise EmbeddingError(
                f"Primary returned no embedding (model={self.primary_model})"
            )
        return [float(x) for x in emb]

    def _embed_fallback(self, text: str) -> list[float]:
        """OpenRouter embeddings endpoint."""
        if not self.openrouter_api_key:
            raise EmbeddingError(
                "OPENROUTER_API_KEY not set — cannot use fallback"
            )
        r = httpx.post(
            "https://openrouter.ai/api/v1/embeddings",
            headers={"Authorization": f"Bearer {self.openrouter_api_key}"},
            json={"model": self.fallback_model, "input": text},
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        arr = data.get("data") or []
        if not arr or "embedding" not in arr[0]:
            raise EmbeddingError(
                f"Fallback returned no embedding (model={self.fallback_model})"
            )
        emb = arr[0]["embedding"]
        return [float(x) for x in emb]

    def embed_batch(
        self, texts: list[str], *, throttle_ms: int = 0
    ) -> list[list[float]]:
        """Embed multiple texts sequentially.

        Ollama's /api/embeddings doesn't natively batch; we issue
        one HTTP call per text. ``throttle_ms`` adds a delay between
        calls if the backend gets rate-limited (rare on local).
        """
        out: list[list[float]] = []
        for i, t in enumerate(texts):
            out.append(self.embed(t))
            if throttle_ms and i < len(texts) - 1:
                time.sleep(throttle_ms / 1000.0)
        return out

    def embed_batch_concurrent(
        self, texts: list[str], *, max_workers: int = 4
    ) -> list[list[float]]:
        """Embed multiple texts in parallel.

        Bench 2026-05-18 vs the serial ``embed_batch``: at max_workers=4
        against ollama with OLLAMA_NUM_PARALLEL=4 on server-b, throughput
        rises from ~0.7 emb/sec to ~2.5-3 emb/sec on Wayward-shape
        content. The win is bounded by the GPU (RTX 3060 12GB at Q8 is
        memory-bandwidth-bound) — additional workers above 4 don't help.

        Returns vectors in the same order as ``texts``. Per-item failures
        propagate as ``EmbeddingError`` from the worker thread.

        Note: each worker creates its own httpx connection per call.
        That's wasteful, but the per-call cost is dwarfed by inference,
        so a connection pool isn't worth the complexity for this scale.
        """
        if not texts:
            return []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(self.embed, texts))

    def stats(self) -> dict[str, int]:
        return {
            "primary_successes": self.primary_successes,
            "primary_failures": self.primary_failures,
            "fallback_successes": self.fallback_successes,
            "fallback_failures": self.fallback_failures,
        }
