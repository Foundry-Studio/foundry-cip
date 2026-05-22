# foundry: kind=test domain=client-intelligence-platform
"""Top-level pytest fixtures for foundry-cip.

M2 work expands this with the connector_conformance harness fixtures.
For now: a no-op placeholder so `pytest` runs without errors in an empty repo.

The CIP-specific Postgres + RLS fixtures live in tests/migrations/conftest.py
(the file moved from monorepo at extraction time per Q2 of the extraction plan).
"""
from __future__ import annotations

import os

# Per PM scope 0f15a060 (Hardening — 2026-05-22): EmbeddingClient runs a
# startup healthcheck against the primary embedding endpoint by default
# to fail fast on stale URLs. Tests construct EmbeddingClient without
# expecting network access; disable the healthcheck repo-wide unless a
# test opts in.
os.environ.setdefault("CIP_EMBEDDING_SKIP_HEALTHCHECK", "1")
