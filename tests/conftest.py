# foundry: kind=test domain=client-intelligence-platform
"""Top-level pytest fixtures for foundry-cip.

M2 work expands this with the connector_conformance harness fixtures.
For now: a no-op placeholder so `pytest` runs without errors in an empty repo.

The CIP-specific Postgres + RLS fixtures live in tests/migrations/conftest.py
(the file moved from monorepo at extraction time per Q2 of the extraction plan).
"""
from __future__ import annotations
