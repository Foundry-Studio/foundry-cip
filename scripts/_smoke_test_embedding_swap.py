# foundry: kind=script domain=client-intelligence-platform
"""Smoke test — compare Ollama vs llama-server embeddings for Qwen3-Embedding-4B Q8.

Both servers must be hosting the SAME GGUF (verified by ollama blob digest
matching the path llama-server is loading). The test confirms:

  1. Each server returns a vector of the same dimension (Qwen3-Embedding-4B -> 2560)
  2. Cosine similarity between same-string embeddings from the two servers
     is >= 0.99 across all 5 reference strings.

If cosines are < 0.99, llama-server is producing meaningfully-different vectors
(usually: GGUF missing sentence-transformers dense modules per
https://gist.github.com/VooDisss/42bce4eb5c76d3c325633886c5e348ee, or wrong
pooling type, or missing <|endoftext|> token append).

Usage:
    # Phase 1 (baseline, ollama only):
    python _smoke_test_embedding_swap.py baseline

    # Phase 2 (after starting llama-server on port 8081):
    python _smoke_test_embedding_swap.py compare
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import httpx

OLLAMA_URL = "http://100.100.10.110:11434/api/embeddings"
OLLAMA_MODEL = "qwen3-embedding:4b-q8_0"

LLAMA_URL = "http://100.100.10.110:8081/v1/embeddings"
LLAMA_MODEL = "qwen3-embedding-4b"  # any string; llama-server only loads one model

BASELINE_PATH = Path(__file__).parent / "_smoke_baseline.json"

# Realistic CIP-shaped test strings: mix of short/long, technical/conversational.
TEST_STRINGS = [
    # 1. Short conversational
    "Hi there, just checking in on the status of my order.",
    # 2. Technical support ticket comment, medium length
    "Customer reports the integration is intermittently failing with a 504 gateway timeout when posting webhook events. Started after the recent deploy. Affected accounts: ACME-001, ACME-042. No errors in our logs but Cloudflare edge shows the upstream connection being reset. Recommend checking the connection pool config in the producer service.",
    # 3. Long meeting note, narrative
    "Met with the Wayward team to walk through Q3 priorities. Key points: (1) churn signal pipeline needs the new event source wired up by end of month, (2) the multi-tenant onboarding flow has a regression on the email verification step that we need to triage, (3) decision pending on whether to deprecate the legacy admin API or freeze it for another quarter. Action items captured in Linear. Follow-up next Thursday.",
    # 4. Mixed-case technical jargon (catches tokenizer issues)
    "POSTGRES query plan shows seq scan on cip_engagements where tenant_id matches. Adding partial index ON cip_engagements (tenant_id, engagement_type) WHERE body IS NOT NULL AND length(body) >= 50 should fix the layer-2 backfill latency.",
    # 5. Very short keyword-style content (edge case for last-token pooling)
    "refund request denied",
]


def embed_ollama(text: str) -> list[float]:
    r = httpx.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": text},
        timeout=60.0,
    )
    r.raise_for_status()
    emb = r.json()["embedding"]
    return [float(x) for x in emb]


def embed_llama(text: str) -> list[float]:
    """llama-server /v1/embeddings (OpenAI-compatible, auto-normalized)."""
    r = httpx.post(
        LLAMA_URL,
        json={"input": text, "model": LLAMA_MODEL, "encoding_format": "float"},
        timeout=60.0,
    )
    r.raise_for_status()
    data = r.json()
    emb = data["data"][0]["embedding"]
    return [float(x) for x in emb]


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return float("nan")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return float("nan")
    return dot / (na * nb)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"baseline", "compare"}:
        print("usage: python _smoke_test_embedding_swap.py [baseline|compare]", file=sys.stderr)
        return 2

    mode = sys.argv[1]

    if mode == "baseline":
        print(f"Embedding {len(TEST_STRINGS)} reference strings via Ollama at {OLLAMA_URL}")
        baseline = []
        for i, s in enumerate(TEST_STRINGS):
            try:
                vec = embed_ollama(s)
                print(f"  [{i}] dim={len(vec)} (first 4: {[round(x, 4) for x in vec[:4]]})  text='{s[:50]}{'...' if len(s) > 50 else ''}'")
                baseline.append({"text": s, "embedding": vec, "dim": len(vec)})
            except Exception as e:
                print(f"  [{i}] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
                return 1
        BASELINE_PATH.write_text(json.dumps(baseline, separators=(',', ':')))
        print(f"\nBaseline written to {BASELINE_PATH.name} ({BASELINE_PATH.stat().st_size:,} bytes)")
        return 0

    # mode == "compare"
    if not BASELINE_PATH.exists():
        print(f"ERROR: baseline file not found at {BASELINE_PATH}. Run with `baseline` first.", file=sys.stderr)
        return 2

    baseline = json.loads(BASELINE_PATH.read_text())
    print(f"Embedding same {len(TEST_STRINGS)} strings via llama-server at {LLAMA_URL}")
    cosines = []
    for i, entry in enumerate(baseline):
        text = entry["text"]
        ollama_vec = entry["embedding"]
        try:
            llama_vec = embed_llama(text)
        except Exception as e:
            print(f"  [{i}] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        if len(llama_vec) != len(ollama_vec):
            print(f"  [{i}] DIM MISMATCH: ollama={len(ollama_vec)} llama={len(llama_vec)}", file=sys.stderr)
            return 1
        c = cosine(ollama_vec, llama_vec)
        cosines.append(c)
        verdict = "PASS" if c >= 0.99 else ("LOW" if c >= 0.95 else "FAIL")
        print(f"  [{i}] cos={c:.6f} [{verdict}]  text='{text[:50]}{'...' if len(text) > 50 else ''}'")

    print()
    min_c = min(cosines)
    avg_c = sum(cosines) / len(cosines)
    print(f"Summary: min cosine = {min_c:.6f}, avg = {avg_c:.6f}, threshold = 0.99")
    if min_c >= 0.99:
        print("\n*** SMOKE TEST PASSED *** Safe to swap.")
        return 0
    print("\n*** SMOKE TEST FAILED *** Abort the swap; stay on ollama and investigate.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
