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
      - Long text: greedy windowing — start at 0, slide by
        (target_chars - overlap_chars) each step, until we cover
        everything. Try to break on paragraph/sentence boundaries
        near the end of each window.

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
    step = spec.target_chars - spec.overlap_chars
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
        pos = pos + step
        if pos >= len(text):
            break
    return [c for c in chunks if c]
