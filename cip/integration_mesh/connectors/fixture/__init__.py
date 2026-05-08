# foundry: kind=service domain=client-intelligence-platform touches=integration
"""FixtureConnector — canonical reference implementation of CIPConnector.

Deterministic synthetic-data connector. Implements every CIPConnector +
CIPMapper Protocol method. Generates a Phase-1-spec corpus (~1150 rows
across 5 active object types — companies, contacts, deals, tickets,
documents; notes intentionally 0 per M3 v2 #2) from a fixed Faker seed for
byte-identical reproducibility within a single Python version + Faker pin
+ ``PYTHONHASHSEED=0``.

Faker is an OPTIONAL extra (``pip install foundry-cip[fixture]``); raising
a friendly error here on missing-Faker keeps the framework's core import
path Faker-free for production ventures that never use FixtureConnector.

Usage::

    from cip.integration_mesh.connectors.fixture import (
        FixtureConnector, FixtureMapper, CorpusSize,
    )
    connector = FixtureConnector(tenant_id=tid, seed=42)
    mapper = FixtureMapper()
    result = run_sync(connector, mapper, engine, tenant_id=tid)
"""
from __future__ import annotations

try:
    import faker as _faker  # noqa: F401
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "FixtureConnector requires the 'fixture' optional extra. "
        "Install with: pip install 'foundry-cip[fixture]'"
    ) from exc

from .connector import FixtureConnector
from .corpus import CorpusSize
from .mapper import FixtureMapper

__all__ = ["FixtureConnector", "FixtureMapper", "CorpusSize"]
