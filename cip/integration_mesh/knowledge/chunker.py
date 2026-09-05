# foundry: kind=service domain=client-intelligence-platform
"""Text chunking for CIP semantic-search ingestion.

Mirrors the Foundry knowledge subsystem's chunk shape (D-055):
  - Target ~512 tokens per chunk
  - Max ~640 tokens
  - Overlap ~125 tokens between adjacent chunks

We approximate tokens via characters (~4 chars per token for English),
which is good enough for retrieval-quality chunks without pulling in
tokenizer dependencies. Short texts (< target) become a single chunk.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkSpec:
    """Configuration for chunking.

    Defaults match the Foundry knowledge subsystem (D-055) approximated
    by character count: 1 token ≈ 4 chars.
    """
    target_chars: int = 2048  # ≈ 512 tokens
    max_chars: int = 2560     # ≈ 640 tokens
    overlap_chars: int = 500  # ≈ 125 tokens


def chunk_text(text: str, spec: ChunkSpec | None = None) -> list[str]:
    """Split ``text`` into overlapping chunks per ``spec``.

    Strategy:
      - Short text (≤ target_chars): return [text] verbatim.
      - Long text: greedy windowing — start at 0, and after each chunk
        resume overlap_chars before that chunk ACTUALLY ended, until we
        cover everything. Try to break on paragraph/sentence boundaries
        near the end of each window.

    Resuming from the real end (rather than a fixed stride) is what
    guarantees full coverage: the boundary search can pull a chunk's end
    backward, and a fixed stride would then skip the difference. See the
    comment at the advance step.

    Returns a list of strings (raw chunks). Caller is responsible
    for embedding + persistence.
    """
    spec = spec or ChunkSpec()
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= spec.target_chars:
        return [text]

    chunks: list[str] = []
    pos = 0
    while pos < len(text):
        end = min(pos + spec.target_chars, len(text))
        # Try to break on a paragraph boundary (\n\n) near end, then \n,
        # then sentence (. ? !), then whitespace.
        if end < len(text):
            window = text[pos:end + spec.max_chars - spec.target_chars]
            # Search backwards from `target_chars` for a good break
            best_break = -1
            for boundary in ("\n\n", "\n", ". ", "? ", "! ", " "):
                idx = window.rfind(boundary, spec.target_chars // 2)
                if idx > best_break:
                    best_break = idx
                    if boundary in ("\n\n", "\n"):
                        break  # paragraph break is best, take it
            if best_break > 0:
                end = pos + best_break + 1
        chunks.append(text[pos:end].strip())
        if end >= len(text):
            break
        # Advance from where this chunk ACTUALLY ended, not by a fixed step.
        #
        # This used to be ``pos = pos + step``. When the boundary search above
        # snapped ``end`` backward (it can land as early as target_chars // 2),
        # the next window still started at pos + step, and every character
        # between the two belonged to no chunk at all. Measured 2026-09-04 on a
        # 4,101-char input with a single space at index 1100 followed by an
        # unbroken run: 448 characters silently absent from every chunk.
        #
        # It needs a long boundary-free run to trigger, which is what an
        # unbroken identifier, a base64 blob, or a dense table of NRCS
        # ecological site codes looks like. Nothing errored and nothing logged;
        # the text simply stopped being retrievable.
        #
        # Anchoring to ``end`` also makes the overlap mean what it says: the
        # next chunk begins overlap_chars before this one finished, whatever
        # the boundary search decided. max(..., pos + 1) is belt-and-braces
        # against a non-advancing window; in practice end >= pos + 1025 and
        # overlap is 500, so progress is always >= ~525 chars.
        pos = max(end - spec.overlap_chars, pos + 1)
        if pos >= len(text):
            break
    return [c for c in chunks if c]
