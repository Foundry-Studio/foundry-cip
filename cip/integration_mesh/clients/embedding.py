# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Thin HTTP client for Qwen3-Embedding-4B with OpenRouter fallback.

Primary backend: llama-server hosting Qwen3-Embedding-4B Q8_0 on server-b
(2026-05-19 Track B Phase 3 cutover from Ollama). Speaks the OpenAI-style
/v1/embeddings shape. Default URL: the cloudflared tunnel
https://embedding-serverb.foundrytunnel.dev. Requires LLAMA_SERVER_API_KEY
(or CIP_EMBEDDING_PRIMARY_API_KEY) for Bearer auth on the tunnel.

Fallback: OpenRouter's qwen/qwen3-embedding-4b model when primary fails
(timeout, 5xx, model-not-loaded). Requires OPENROUTER_API_KEY.

For local-only smoke (Ollama still installed on server-b, retained for
rollback per inventory note), set CIP_EMBEDDING_PROTOCOL=ollama to flip
to the legacy /api/embeddings shape.

Config via env vars:
  CIP_EMBEDDING_PRIMARY_URL       Base URL (default
                                  https://embedding-serverb.foundrytunnel.dev)
  CIP_EMBEDDING_PRIMARY_MODEL     Model id reported in request (default
                                  Qwen3-Embedding-4B-Q8_0.gguf for openai;
                                  qwen3-embedding:4b-q8_0 for ollama)
  CIP_EMBEDDING_PRIMARY_API_KEY   Bearer token for tunnel (falls back to
                                  LLAMA_SERVER_API_KEY)
  CIP_EMBEDDING_PROTOCOL          'openai' (default) | 'ollama'
  CIP_EMBEDDING_FALLBACK_MODEL    OpenRouter model id
                                  (default qwen/qwen3-embedding-4b)
  OPENROUTER_API_KEY              Required only when fallback activates
  CIP_EMBEDDING_TIMEOUT_S         Per-request timeout (default 60)
  CIP_EMBEDDING_SKIP_HEALTHCHECK  '1' to skip startup healthcheck (e.g.
                                  for offline tests / mocks)
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
        primary_api_key: str | None = None,
        protocol: str | None = None,
        fallback_model: str | None = None,
        timeout_s: float | None = None,
        openrouter_api_key: str | None = None,
        healthcheck: bool | None = None,
    ) -> None:
        self.protocol = (
            protocol
            or os.environ.get("CIP_EMBEDDING_PROTOCOL")
            or "openai"
        ).lower()
        if self.protocol not in {"openai", "ollama"}:
            raise ValueError(
                f"protocol must be 'openai' or 'ollama', got {self.protocol!r}"
            )
        # Defaults differ by protocol — OpenAI is the new normal (Track B Phase 3
        # 2026-05-19 cutover from Ollama). Ollama path retained for the rollback
        # case the inventory note describes.
        default_url = (
            "https://embedding-serverb.foundrytunnel.dev"
            if self.protocol == "openai"
            else "http://100.100.10.110:11434"
        )
        default_model = (
            "Qwen3-Embedding-4B-Q8_0.gguf"
            if self.protocol == "openai"
            else "qwen3-embedding:4b-q8_0"
        )
        self.primary_url = (
            primary_url
            or os.environ.get("CIP_EMBEDDING_PRIMARY_URL")
            or default_url
        )
        self.primary_model = (
            primary_model
            or os.environ.get("CIP_EMBEDDING_PRIMARY_MODEL")
            or default_model
        )
        self.primary_api_key = (
            primary_api_key
            or os.environ.get("CIP_EMBEDDING_PRIMARY_API_KEY")
            or os.environ.get("LLAMA_SERVER_API_KEY", "")
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

        # Startup healthcheck — fail fast if primary endpoint is unreachable.
        # Without this, the failure surfaces deep in the first embed call
        # (often inside a long-running migration), wasting setup time
        # before the real problem becomes visible. The 2026-05-22
        # server-b Ollama-decommissioning incident is the cautionary
        # tale: silent URL staleness ran for 3 days because no startup
        # check existed.
        skip_env = os.environ.get("CIP_EMBEDDING_SKIP_HEALTHCHECK", "").strip()
        if healthcheck is None:
            healthcheck = skip_env not in {"1", "true", "yes"}
        if healthcheck:
            self._startup_healthcheck()

    def _startup_healthcheck(self) -> None:
        """Probe the primary endpoint at construction time.

        Uses a fast non-embedding endpoint (`/v1/models` for OpenAI-style,
        `/api/tags` for Ollama-style). Network or 5xx → EmbeddingError
        immediately so callers know to investigate before they've queued
        an hour of work behind the bad URL.
        """
        if self.protocol == "openai":
            probe_path = "/v1/models"
        else:
            probe_path = "/api/tags"
        url = f"{self.primary_url}{probe_path}"
        headers = {}
        if self.protocol == "openai" and self.primary_api_key:
            headers["Authorization"] = f"Bearer {self.primary_api_key}"
        try:
            r = httpx.get(url, headers=headers, timeout=min(self.timeout_s, 10.0))
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise EmbeddingError(
                f"Embedding healthcheck failed for {url}: "
                f"{type(e).__name__}: {str(e)[:200]}. "
                f"If you intend to skip this check, set "
                f"CIP_EMBEDDING_SKIP_HEALTHCHECK=1."
            ) from e

    @property
    def model_id(self) -> str:
        """Canonical model identifier recorded with each embedding."""
        return f"qwen/qwen3-embedding-4b (primary={self.primary_model}, protocol={self.protocol})"

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
        """Primary embedding call — OpenAI-style by default, Ollama if configured."""
        if self.protocol == "openai":
            return self._embed_primary_openai(text)
        return self._embed_primary_ollama(text)

    def _embed_primary_openai(self, text: str) -> list[float]:
        """llama-server /v1/embeddings — Bearer-auth, OpenAI-compatible."""
        headers = {"Content-Type": "application/json"}
        if self.primary_api_key:
            headers["Authorization"] = f"Bearer {self.primary_api_key}"
        r = httpx.post(
            f"{self.primary_url}/v1/embeddings",
            headers=headers,
            json={"model": self.primary_model, "input": text},
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        arr = data.get("data") or []
        if not arr or "embedding" not in arr[0]:
            raise EmbeddingError(
                f"Primary returned no embedding (model={self.primary_model})"
            )
        return [float(x) for x in arr[0]["embedding"]]

    def _embed_primary_ollama(self, text: str) -> list[float]:
        """Legacy Ollama /api/embeddings — retained for rollback per Track B Phase 3 note."""
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
