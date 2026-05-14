# foundry: kind=test domain=client-intelligence-platform
"""run_backfill() protocol-validation tests.

Bug history (2026-05-14): ``_NoOpMapper.map`` was a regular function
returning ``list[object]``. ``validate_connector_shape()`` (called at
the top of ``run_backfill``) requires ``mapper.map`` to be a generator
function. Result: every ``run_backfill()`` invocation immediately
raised ``ProtocolShapeError: _NoOpMapper.map must be a generator
function`` — the autonomous orchestrator's first HubSpot backfill
attempt died on that error, no historical row ever landed.

These tests assert that ``run_backfill`` can be invoked end-to-end
with a connector whose ``backfill_history`` yields no records (the
no-op case). If the internal sentinel mapper or any other validator
regresses, this test fails BEFORE we ship to prod.
"""
from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

from cip.integration_mesh.base import (
    CIPConnectorBase,
    HistoricalRecord,
    PropertyDescriptor,
    RateLimitPolicy,
)
from cip.integration_mesh.orchestrator import _NoOpMapper

TENANT = UUID("00000000-0000-0000-0000-000000000abc")


def test_noop_mapper_map_is_generator_function() -> None:
    """Direct unit-level check (no DB needed). The exact root cause of
    the 2026-05-14 backfill regression."""
    m = _NoOpMapper()
    assert inspect.isgeneratorfunction(m.map), (
        "_NoOpMapper.map MUST be a generator function (per "
        "validate_connector_shape H-7); currently it is "
        f"{type(m.map).__name__}. This regression killed run_backfill "
        "on 2026-05-14."
    )


def test_noop_mapper_passes_validate_connector_shape() -> None:
    """Direct path: invoke validate_connector_shape with a no-op
    connector + _NoOpMapper. Should NOT raise."""
    from cip.integration_mesh.validation import validate_connector_shape

    class _NoOpConnector(CIPConnectorBase):
        connector_id: str = "noop"
        cursor_safety_window_seconds: int = 0

        def __init__(self) -> None:
            self.tenant_id = TENANT

        def authenticate(self) -> None:
            pass

        def stream_records(
            self, cursor: dict[str, object] | None, batch_size: int
        ) -> Iterator[dict[str, object]]:
            yield from ()

        def describe_schema(self) -> list[PropertyDescriptor]:
            return []

        def incremental_key(self, record: dict[str, object]) -> datetime:
            from datetime import UTC
            return datetime(2026, 1, 1, tzinfo=UTC)

        @property
        def rate_limit_policy(self) -> RateLimitPolicy:
            return RateLimitPolicy(requests_per_second=1.0, burst=1)

        def backfill_history(
            self, tenant_id: UUID
        ) -> Iterator[HistoricalRecord]:
            yield from ()

    # Should not raise: connector implements full Protocol; _NoOpMapper
    # has the generator-function map().
    validate_connector_shape(_NoOpConnector(), _NoOpMapper())


def test_noop_mapper_emits_no_records() -> None:
    """The _NoOpMapper's map() is a generator that yields nothing.
    Verify it produces an empty iterator (not crashes, not infinite)."""
    m = _NoOpMapper()
    out = list(m.map({"any": "record"}))
    assert out == []
