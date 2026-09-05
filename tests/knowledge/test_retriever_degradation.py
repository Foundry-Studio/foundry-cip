# foundry: kind=test domain=client-intelligence-platform
"""A reranker failure must DEGRADE VISIBLY, not silently.

Both rerank sites in the retriever used to end with a bare::

    except Exception:
        pass

Degrading to similarity order when the reranker is down is the right call — a
search should not fail because a ranking refinement is unavailable. Doing it
silently was the defect: the caller received measurably worse ordering with no
signal, so a reranker down for weeks looked identical to one that was working.
That is the same shape as the four-month CI blackout and the two-day feed
outage: the machinery reports success while the quality is gone.

The two sites were byte-identical copies and are now one method, which is what
makes them testable without a live engine or Pinecone client.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import uuid4

import pytest

from cip.integration_mesh.knowledge.retriever import KnowledgeRetriever


@dataclass
class _Cand:
    source_kind: str = "cip_client_document"
    source_id: str = "s1"
    chunk_index: int = 0
    content: str = "Prescribed burn windows run November to April."
    score: float = 0.5
    similarity: float = 0.5
    reranked: bool = False
    metadata: dict | None = None
    client_id: str | None = None


class _BoomReranker:
    def rerank(self, **_kw: object) -> list[dict[str, object]]:
        raise RuntimeError("reranker connection refused")


class _GoodReranker:
    def rerank(self, *, query: str, candidates: list, top_k: int) -> list[dict]:
        # Reverse the input order so a successful rerank is distinguishable
        # from the degraded path, which preserves similarity order.
        return [
            {"candidate": c["candidate"], "score": float(i)}
            for i, c in enumerate(reversed(candidates))
        ][:top_k]


def _retriever(reranker: object) -> KnowledgeRetriever:
    """Build without __init__ — no engine or embedding client needed here."""
    r = KnowledgeRetriever.__new__(KnowledgeRetriever)
    r.engine = None  # type: ignore[assignment]
    r.client = None  # type: ignore[assignment]
    r.reranker = reranker  # type: ignore[assignment]
    r.rerank_failures = 0
    return r


def _call(r: KnowledgeRetriever, cands: list[_Cand], *, rerank: bool = True,
          path: str = "postgres") -> list:
    return r._apply_rerank(
        query="burn frequency", candidates=cands, top_k=10,
        rerank=rerank, tenant_id=uuid4(), path=path,
    )


def test_counter_starts_at_zero() -> None:
    assert _retriever(_BoomReranker()).rerank_failures == 0


def test_successful_rerank_does_not_touch_the_counter() -> None:
    r = _retriever(_GoodReranker())
    a, b = _Cand(source_id="a"), _Cand(source_id="b")
    out = _call(r, [a, b])
    assert [c.source_id for c in out] == ["b", "a"], "rerank should reorder"
    assert all(c.reranked for c in out)
    assert r.rerank_failures == 0


def test_failure_degrades_to_similarity_order_rather_than_raising() -> None:
    r = _retriever(_BoomReranker())
    a, b = _Cand(source_id="a"), _Cand(source_id="b")
    out = _call(r, [a, b])
    assert [c.source_id for c in out] == ["a", "b"], (
        "degraded path must preserve the incoming similarity order"
    )
    assert not any(c.reranked for c in out), (
        "a degraded result must not claim it was reranked"
    )


def test_failure_increments_the_counter() -> None:
    r = _retriever(_BoomReranker())
    _call(r, [_Cand()])
    _call(r, [_Cand()])
    assert r.rerank_failures == 2


def test_failure_emits_a_warning_naming_tenant_and_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    r = _retriever(_BoomReranker())
    with caplog.at_level(logging.WARNING):
        _call(r, [_Cand()], path="pinecone")
    warnings = [rec for rec in caplog.records if rec.levelno >= logging.WARNING]
    assert warnings, "degradation must be logged at WARNING or above"
    msg = warnings[0].getMessage()
    assert "pinecone" in msg, "the log must say WHICH retrieval path degraded"
    assert "RuntimeError" in msg, "the log must name the underlying failure"


def test_rerank_disabled_is_not_counted_as_a_failure() -> None:
    """Not asking for a rerank is not a degradation. Conflating the two would
    make the counter useless as a health signal."""
    r = _retriever(_GoodReranker())
    out = _call(r, [_Cand()], rerank=False)
    assert r.rerank_failures == 0
    assert not out[0].reranked


def test_no_reranker_configured_is_not_a_failure() -> None:
    r = _retriever(None)
    assert _call(r, [_Cand()]) and r.rerank_failures == 0


def test_no_bare_except_pass_remains_in_the_retriever() -> None:
    """Source guard: if someone reintroduces a silent swallow, fail now rather
    than discover it months later the way the original was discovered."""
    import inspect

    from cip.integration_mesh.knowledge import retriever as mod

    src = inspect.getsource(mod)
    assert "except Exception:\n                pass" not in src
    assert "except Exception:\n            pass" not in src
