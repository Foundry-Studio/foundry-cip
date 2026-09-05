# foundry: kind=test domain=client-intelligence-platform
"""EmbeddingClient must VALIDATE vector width, not merely record it.

WHY THIS EXISTS. ``EmbeddingClient.embed`` tries a local primary and, on any
exception, falls through to an OpenRouter fallback. Both paths used to end with

    self.vector_dim = len(vec)

which is an assignment where a comparison belongs. Nothing compared the two
paths' widths, so a fallback of a different width was accepted silently.

That mattered because the widths genuinely differ. The corpus in
``cip_knowledge_chunks`` is 2560-dimensional (Qwen3-Embedding-4B Q8_0, measured
2026-09-04 via ``array_length(embedding,1)`` across all 36,492 rows). The LLM
roster describes the OpenRouter fallback ``qwen/qwen3-embedding-4b`` as emitting
1024-dimensional MRL vectors.

The failure was silent in both stores at once:
  - ``cip_knowledge_chunks.embedding`` is ``double precision[]`` with no length
    constraint, so Postgres accepts a short vector without complaint.
  - Pinecone's index has a fixed dimension and would reject it, but Pinecone
    write failures are non-fatal in the indexer.
So a server-b outage during an embedding run would land incomparable vectors in
Postgres, drop them from Pinecone, and report success. Cosine similarity against
a 1024-wide row then either errors or returns nonsense.

These tests fail against the pre-fix code. That is the point: a regression test
that passes on the broken version is not testing the bug.
"""
from __future__ import annotations

import pytest

from cip.integration_mesh.clients.embedding import (
    DEFAULT_VECTOR_DIM,
    EmbeddingClient,
    EmbeddingError,
)


def _client(**kw: object) -> EmbeddingClient:
    """Construct without touching the network (healthcheck disabled)."""
    kw.setdefault("healthcheck", False)
    return EmbeddingClient(**kw)  # type: ignore[arg-type]


def test_default_expected_dim_matches_the_corpus() -> None:
    """The default must be the width the existing corpus actually is.

    Measured 2026-09-04: every one of the 36,492 rows in cip_knowledge_chunks
    is 2560 wide. A default that disagreed with the corpus would make the guard
    reject correct vectors.
    """
    assert DEFAULT_VECTOR_DIM == 2560
    assert _client().expected_dim == 2560


def test_primary_vector_of_expected_width_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client()
    monkeypatch.setattr(c, "_embed_primary", lambda _t: [0.1] * 2560)
    vec = c.embed("hello")
    assert len(vec) == 2560
    assert c.vector_dim == 2560
    assert c.primary_successes == 1


def test_fallback_of_wrong_width_raises_instead_of_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE BUG. Primary is down; the 1024-wide fallback must NOT be returned.

    Pre-fix this returned a 1024-long list and set vector_dim=1024, and the
    caller had no way to tell. Post-fix it raises.
    """
    c = _client()

    def _dead_primary(_t: str) -> list[float]:
        raise RuntimeError("server-b unreachable")

    monkeypatch.setattr(c, "_embed_primary", _dead_primary)
    monkeypatch.setattr(c, "_embed_fallback", lambda _t: [0.1] * 1024)

    with pytest.raises(EmbeddingError) as exc:
        c.embed("hello")

    msg = str(exc.value)
    assert "1024" in msg and "2560" in msg, (
        f"the error must name both the received and expected width; got: {msg}"
    )
    assert c.vector_dim is None, (
        "a rejected vector must not become the recorded dimension"
    )


def test_primary_of_wrong_width_also_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard is not fallback-only. A swapped GGUF on the primary is the
    same corruption by a different route."""
    c = _client()
    monkeypatch.setattr(c, "_embed_primary", lambda _t: [0.1] * 1024)
    monkeypatch.setattr(c, "_embed_fallback", lambda _t: [0.1] * 1024)
    with pytest.raises(EmbeddingError):
        c.embed("hello")


def test_width_is_enforced_across_calls_not_just_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that starts healthy and degrades mid-way is the realistic shape
    of a server-b outage. The second call must not silently change the width."""
    c = _client()
    widths = iter([2560, 1024])
    monkeypatch.setattr(c, "_embed_primary", lambda _t: [0.1] * next(widths))
    monkeypatch.setattr(c, "_embed_fallback", lambda _t: [0.1] * 1024)

    assert len(c.embed("first")) == 2560
    with pytest.raises(EmbeddingError):
        c.embed("second")
    assert c.vector_dim == 2560, "the good width must survive a rejected call"


def test_expected_dim_is_configurable_for_a_deliberate_model_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing embedding model is legitimate; doing it by accident is not.
    An explicit expected_dim is how a deliberate change is declared."""
    c = _client(expected_dim=1024)
    monkeypatch.setattr(c, "_embed_primary", lambda _t: [0.1] * 1024)
    assert len(c.embed("hello")) == 1024


def test_expected_dim_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIP_EMBEDDING_EXPECTED_DIM", "1024")
    assert _client().expected_dim == 1024


def test_empty_vector_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A backend that returns [] must not be read as a zero-width success."""
    c = _client()
    monkeypatch.setattr(c, "_embed_primary", lambda _t: [])
    monkeypatch.setattr(c, "_embed_fallback", lambda _t: [])
    with pytest.raises(EmbeddingError):
        c.embed("hello")


def test_batch_paths_enforce_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """embed_batch is what the ingest pipeline actually calls; a guard that
    only covers embed() would miss every real corruption."""
    c = _client()
    monkeypatch.setattr(c, "_embed_primary", lambda _t: [0.1] * 1024)
    monkeypatch.setattr(c, "_embed_fallback", lambda _t: [0.1] * 1024)
    with pytest.raises(EmbeddingError):
        c.embed_batch(["a", "b"])
