# foundry: kind=test domain=client-intelligence-platform
"""Tests for ``validate_connector_shape`` (M2 §4.11 binding).

Plan §4.11 acceptance + §9 #16 (acceptance criterion):
  - valid pair passes
  - stream_records returning a list (not generator) raises
  - incremental_key wrong arity raises
  - mapper missing overflow_fields raises
  - PATCH-Q3: decorator-wrapped generator with @functools.wraps passes
  - broken decorator (no __wrapped__) still fails clearly
  - ProtocolShapeError IS-A TypeError
"""
from __future__ import annotations

import functools
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest

from cip.integration_mesh.base import (
    DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS,
    DEFAULT_RATE_LIMIT,
    CIPRow,
    KnowledgeText,
    PropertyDescriptor,
    RateLimitPolicy,
)
from cip.integration_mesh.validation import (
    ProtocolShapeError,
    validate_connector_shape,
)

# ── Reference good shapes ─────────────────────────────────────────────────


class GoodConnector:
    connector_id = "good-connector"

    def __init__(self) -> None:
        self.tenant_id: UUID = uuid4()

    @property
    def rate_limit_policy(self) -> RateLimitPolicy:
        return DEFAULT_RATE_LIMIT

    @property
    def cursor_safety_window_seconds(self) -> int:
        return DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS

    def authenticate(self) -> None:
        pass

    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        yield {"id": "rec-1", "updated_at": "2026-04-20T00:00:00+00:00"}

    def describe_schema(self) -> list[PropertyDescriptor]:
        return []

    def incremental_key(self, record: dict[str, object]) -> datetime:
        return datetime.fromisoformat(str(record["updated_at"]))


class GoodMapper:
    object_type = "contact"
    target_table = "cip_contacts"

    def map(self, record: dict[str, object]) -> Iterable[CIPRow]:
        yield CIPRow(
            target_table="cip_contacts",
            source_id=str(record["id"]),
            fields={},
        )

    def overflow_fields(self) -> list[str]:
        return []

    def authority(
        self,
    ) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        return []


def test_valid_pair_passes() -> None:
    validate_connector_shape(GoodConnector(), GoodMapper())


# ── Bad shapes ────────────────────────────────────────────────────────────


class BadConnectorStreamReturnsList(GoodConnector):
    def stream_records(  # type: ignore[override]
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> list[dict[str, object]]:
        return [{"id": "x"}]


def test_stream_records_not_generator_raises() -> None:
    with pytest.raises(
        ProtocolShapeError, match="stream_records must be a generator"
    ):
        validate_connector_shape(
            BadConnectorStreamReturnsList(), GoodMapper()
        )


class BadConnectorWrongIncrementalKeyArity(GoodConnector):
    def incremental_key(self) -> datetime:  # type: ignore[override]
        return datetime.fromisoformat("2026-04-20T00:00:00+00:00")


def test_incremental_key_wrong_arity_raises() -> None:
    with pytest.raises(ProtocolShapeError, match="incremental_key"):
        validate_connector_shape(
            BadConnectorWrongIncrementalKeyArity(), GoodMapper()
        )


class BadMapperMissingOverflowFields:
    object_type = "contact"
    target_table = "cip_contacts"

    def map(self, record: dict[str, object]) -> Iterable[CIPRow]:
        yield CIPRow(target_table="cip_contacts", source_id="x", fields={})

    def authority(
        self,
    ) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        return []
    # NB: overflow_fields method intentionally absent.


def test_mapper_missing_overflow_fields_raises() -> None:
    with pytest.raises(ProtocolShapeError):
        validate_connector_shape(GoodConnector(), BadMapperMissingOverflowFields())


# ── PATCH-Q3 (v5 SEV-5): inspect.unwrap walks __wrapped__ chain ──────────


def _trace_decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)

    return wrapper


class DecoratedConnector(GoodConnector):
    @_trace_decorator
    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        yield {"id": "rec-1", "updated_at": "2026-04-20T00:00:00+00:00"}


def test_decorator_with_functools_wraps_passes() -> None:
    # PATCH-Q3: @functools.wraps preserves __wrapped__; inspect.unwrap()
    # walks the chain so generator detection works correctly.
    validate_connector_shape(DecoratedConnector(), GoodMapper())


def _broken_decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
    # Broken on purpose: no @functools.wraps → __wrapped__ NOT set, so
    # inspect.unwrap() can't see that the inner fn is a generator. The
    # outer wrapper preserves arity (matches stream_records' signature)
    # so it passes the arity check and reaches the generator check.
    def wrapper(
        self: Any,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Any:
        return fn(self, cursor, batch_size)

    return wrapper


class BadDecoratedConnector(GoodConnector):
    @_broken_decorator
    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        yield {"id": "rec-1", "updated_at": "2026-04-20T00:00:00+00:00"}


def test_broken_decorator_fails_clearly() -> None:
    with pytest.raises(ProtocolShapeError, match="generator"):
        validate_connector_shape(BadDecoratedConnector(), GoodMapper())


# ── Misc ─────────────────────────────────────────────────────────────────


def test_protocol_shape_error_is_type_error() -> None:
    assert issubclass(ProtocolShapeError, TypeError)
