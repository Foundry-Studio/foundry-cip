# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Thin HTTP client for Qwen3-Embedding-4B with OpenRouter fallback.

Per PM scope 2d6390fa (Layer 2 wiring v1, tenant-agnostic capability)
+ option A decision (2026-05-17): CIP keeps its own thin wrapper
rather than importing from the monorepo's src/services/embedding_client.

Primary backend (post 2026-05-18 swap): llama-server in embedding mode
on server-b, port 8081, serving the same Qwen3-Embedding-4B Q8_0 GGUF
that ollama was serving before. The switch unlocks --parallel 2
concurrent slots (vs ollama's effective serial path) for ~2-3x
backfill throughput. Smoke test 2026-05-18 confirmed cosine >= 0.9996
on 5 reference strings vs the prior ollama baseline (same GGUF, same
--pooling last) — the vector space is preserved, so previously-embedded
chunks remain compatible.

Endpoint: /v1/embeddings (OpenAI-compatible, auto-normalized via
Euclidean norm per llama-server convention).

Fallback: OpenRouter's qwen/qwen3-embedding-4b model when primary
fails (timeout, 5xx, model-not-loaded). OpenRouter requires
OPENROUTER_API_KEY env.

Config via env vars:
  CIP_EMBEDDING_PRIMARY_URL    llama-server base URL (default
                               http://100.100.10.110:8081)
  CIP_EMBEDDING_PRIMARY_MODEL  Model alias on llama-server
                               (default qwen3-embedding-4b — must match
                               the --alias flag on the systemd unit)
  CIP_EMBEDDING_FALLBACK_MODEL OpenRouter model id
                               (default qwen/qwen3-embedding-4b)
  OPENROUTER_API_KEY           Required only when fallback activates
  CIP_EMBEDDING_TIMEOUT_S      Per-request timeout (default 60)
"""
from __future__ import annotations

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
            or "http://100.100.10.110:8081"
        )
        self.primary_model = (
            primary_model
            or os.environ.get("CIP_EMBEDDING_PRIMARY_MODEL")
            or "qwen3-embedding-4b"
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
        """llama-server /v1/embeddings endpoint (OpenAI-compatible).

        Per the 2026-05-18 swap from ollama, the primary backend speaks
        the OpenAI embeddings shape: request body is
        ``{"input": <str>, "model": ..., "encoding_format": "float"}``,
        response is ``{"data": [{"embedding": [...]}]}``.

        llama-server normalises the returned vector using Euclidean norm
        when pooling != none (which we use, --pooling last), so callers
        get a unit-length vector without extra work.
        """
        r = httpx.post(
            f"{self.primary_url}/v1/embeddings",
            json={
                "input": text,
                "model": self.primary_model,
                "encoding_format": "float",
            },
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        try:
            emb = data["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as e:
            raise EmbeddingError(
                f"Primary returned malformed embedding response "
                f"(model={self.primary_model}): {type(e).__name__}: {e}"
            ) from e
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

    def stats(self) -> dict[str, int]:
        return {
            "primary_successes": self.primary_successes,
            "primary_failures": self.primary_failures,
            "fallback_successes": self.fallback_successes,
            "fallback_failures": self.fallback_failures,
        }
