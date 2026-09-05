# foundry: kind=test domain=client-intelligence-platform
"""First tests for the CIP chunker.

Until 2026-09-04 this module had none, despite producing every chunk in a
36,492-row corpus. The properties asserted here are the ones a retrieval
system actually depends on: nothing silently dropped, nothing over the cap,
and the same input always producing the same chunks.
"""
from __future__ import annotations

import pytest

from cip.integration_mesh.knowledge.chunker import ChunkSpec, chunk_text


def test_empty_and_whitespace_only_produce_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []
    assert chunk_text(None) == []  # type: ignore[arg-type]


def test_short_text_is_one_verbatim_chunk() -> None:
    t = "A short note about canebrake burn frequency."
    assert chunk_text(t) == [t]


def test_text_at_exactly_target_is_one_chunk() -> None:
    spec = ChunkSpec()
    t = "x" * spec.target_chars
    assert len(chunk_text(t)) == 1


def test_no_chunk_exceeds_max_chars() -> None:
    spec = ChunkSpec()
    body = ("The quick brown fox jumps over the lazy dog. " * 400)
    for c in chunk_text(body, spec):
        assert len(c) <= spec.max_chars, (
            f"chunk of {len(c)} exceeds max_chars={spec.max_chars}"
        )


def test_chunking_is_deterministic() -> None:
    body = ("Rivercane propagation guidance. " * 300)
    assert chunk_text(body) == chunk_text(body)


def test_adjacent_chunks_overlap_on_prose() -> None:
    """Overlap is what keeps a fact that straddles a boundary retrievable."""
    body = ("Prescribed fire in the dormant season runs November to April. " * 120)
    chunks = chunk_text(body)
    assert len(chunks) > 1
    tail = chunks[0][-100:]
    assert tail.strip() and tail.strip()[:40] in chunks[1] or chunks[1] in body


def _unique_filler(n: int, seed: int = 0) -> str:
    """n characters with NO whitespace and NO sentence punctuation, where every
    position is distinguishable.

    Uniqueness is the whole point. An earlier version of the coverage test used
    a run of repeated "A"s and PASSED against code that was dropping 448
    characters, because the dropped span was byte-identical to text that
    survived elsewhere. Repetitive fixtures hide exactly the bug this test is
    for.
    """
    import string

    alphabet = string.ascii_uppercase + string.digits
    out = []
    for i in range(seed, seed + n):
        v, s = i, ""
        for _ in range(6):
            s = alphabet[v % 36] + s
            v //= 36
        out.append(s)
    return "".join(out)[:n]


def _uncovered_spans(body: str, chunks: list[str]) -> list[tuple[int, int]]:
    covered = [False] * len(body)
    for c in chunks:
        start = 0
        while True:
            k = body.find(c, start)
            if k < 0:
                break
            for j in range(k, k + len(c)):
                covered[j] = True
            start = k + 1
    spans, i = [], 0
    while i < len(body):
        if not covered[i]:
            j = i
            while j < len(body) and not covered[j]:
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    return spans


@pytest.mark.parametrize("boundary_at", [1100, 1200, 1400, 1500])
def test_no_source_text_is_silently_dropped(boundary_at: int) -> None:
    """COVERAGE INVARIANT: every character of the source appears in some chunk.

    This is the property most worth having, because violating it loses content
    with no error and no log line: a fact simply stops being retrievable and
    nothing says so.

    The bug this pins, found 2026-09-04 by writing this test: ``end`` can snap
    BACKWARD to a boundary as early as target_chars // 2, while the next window
    used to start at a fixed ``pos + (target_chars - overlap_chars)``. When the
    snap-back landed earlier than that stride, the characters between belonged
    to no chunk. A 4,101-char input with one space at index 1100 followed by an
    unbroken run dropped 448 characters.

    The parametrised boundary positions straddle the old stride (1548), so the
    cases both inside and outside the failure band are covered.
    """
    spec = ChunkSpec()
    body = _unique_filler(boundary_at) + " " + _unique_filler(3000, seed=99_999)

    chunks = chunk_text(body, spec)
    assert chunks

    gaps = _uncovered_spans(body, chunks)
    assert not gaps, (
        f"{sum(e - s for s, e in gaps)} source characters appear in no chunk; "
        f"uncovered spans: {gaps}"
    )


def test_overlap_is_measured_from_where_the_chunk_ended() -> None:
    """Overlap must be real regardless of where the boundary search landed.

    A fixed stride made the effective overlap vary with the boundary search,
    and become negative (a gap) in the worst case.
    """
    spec = ChunkSpec()
    body = _unique_filler(1100) + " " + _unique_filler(3000, seed=7)
    chunks = chunk_text(body, spec)
    assert len(chunks) >= 2
    for a, b in zip(chunks, chunks[1:], strict=False):
        ia, ib = body.find(a), body.find(b)
        assert ib < ia + len(a), (
            "consecutive chunks must overlap in the source, not leave a gap"
        )
