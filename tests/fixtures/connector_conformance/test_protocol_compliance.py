# foundry: kind=test domain=client-intelligence-platform
"""Conformance test §5.2 — Protocol shape compliance.

Cheapest end-to-end signal: do MockConnector + MockMapper satisfy the CIP
Protocols both at the @runtime_checkable layer (isinstance) AND the
shape-validator layer (validate_connector_shape — arity, generator-fn,
required attrs).

No DB writes — pure Protocol structural compliance.
"""
from __future__ import annotations

from cip.integration_mesh import (
    CIPConnector,
    CIPMapper,
    validate_connector_shape,
)
from tests.fixtures.connector_conformance.conftest import (
    MockConnector,
    MockMapper,
)
from tests.fixtures.connector_conformance.fixtures.records import (
    CANONICAL_CONTACTS,
    CANONICAL_SCHEMA,
    DELTA_CONTACTS,
)


# v3 (R2-H2): assert fixture-corpus invariants once per harness.
def test_canonical_corpus_invariants() -> None:
    assert len(CANONICAL_CONTACTS) == 10
    assert len(DELTA_CONTACTS) == 3
    # Delta 13 fix: DELTA has 3 distinct source_ids, 2 of which are new.
    assert len({r["source_id"] for r in DELTA_CONTACTS}) == 3
    baseline_sids = {r["source_id"] for r in CANONICAL_CONTACTS}
    new_in_delta = {r["source_id"] for r in DELTA_CONTACTS} - baseline_sids
    assert len(new_in_delta) == 2  # c011, c012
    assert len(CANONICAL_SCHEMA) == 5


def test_mock_connector_isinstance_protocol() -> None:
    """@runtime_checkable Protocol method-existence check."""
    from uuid import uuid4

    c = MockConnector(
        tenant_id=uuid4(),
        records=CANONICAL_CONTACTS,
        schema=CANONICAL_SCHEMA,
    )
    assert isinstance(c, CIPConnector)


def test_mock_mapper_isinstance_protocol() -> None:
    m = MockMapper()
    assert isinstance(m, CIPMapper)


def test_validate_connector_shape_passes_against_canonical_pair() -> None:
    """End-to-end shape check: arity, generator-functions, required
    attrs. Returns None on conforming pair; raises ProtocolShapeError
    otherwise."""
    from uuid import uuid4

    c = MockConnector(
        tenant_id=uuid4(),
        records=CANONICAL_CONTACTS,
        schema=CANONICAL_SCHEMA,
    )
    m = MockMapper()
    validate_connector_shape(c, m)


def test_describe_schema_returns_five_descriptors() -> None:
    from uuid import uuid4

    c = MockConnector(
        tenant_id=uuid4(),
        records=CANONICAL_CONTACTS,
        schema=CANONICAL_SCHEMA,
    )
    descriptors = c.describe_schema()
    assert len(descriptors) == 5
    # Structural: 3 column + 2 overflow.
    column_count = sum(
        1 for d in descriptors if d.storage_location == "column"
    )
    overflow_count = sum(
        1 for d in descriptors if d.storage_location == "overflow"
    )
    assert column_count == 3
    assert overflow_count == 2
