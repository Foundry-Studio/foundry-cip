# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Runtime connector / mapper Protocol shape validation (M2 §4.11 binding).

Closes QC C-5: ``isinstance(x, CIPConnector)`` only checks method
existence, not signatures or return-types. ``validate_connector_shape()``
adds:
  1. ``isinstance`` against the @runtime_checkable Protocols.
  2. Required class attributes (``connector_id``, ``rate_limit_policy``,
     ``cursor_safety_window_seconds``, ``object_type``, ``target_table``).
  3. Method arity (positional parameter count).
  4. ``stream_records`` and ``map`` MUST be generator functions.

v5 PATCH-Q3 (Round-4 panel SEV-5, mandatory): use ``inspect.unwrap()``
to walk the entire ``__wrapped__`` chain before checking generator-ness.
Connectors using ``functools.wraps``-correct decorators now pass; broken
decorators still fail with a clear error message.

Type annotation verification is intentionally NOT performed here — that
would force a beartype/typeguard runtime dependency. The conformance
harness covers annotation correctness via end-to-end run_sync execution.
"""
from __future__ import annotations

import inspect
from typing import Any

from .base import CIPConnector, CIPMapper


class ProtocolShapeError(TypeError):
    """Raised when a connector / mapper instance fails shape validation."""


# Method → (positional_arg_count_including_self, required_kwargs).
# `1` means just self; `2` means self + one arg; etc.
_CONNECTOR_SHAPE: dict[str, tuple[int, frozenset[str]]] = {
    "authenticate": (1, frozenset()),
    "stream_records": (3, frozenset()),  # self, cursor, batch_size
    "describe_schema": (1, frozenset()),
    "incremental_key": (2, frozenset()),  # self, record
}

_MAPPER_SHAPE: dict[str, tuple[int, frozenset[str]]] = {
    "map": (2, frozenset()),  # self, record
    "overflow_fields": (1, frozenset()),
    "ingest_as_knowledge": (2, frozenset()),  # self, record
}

# v4 (Round-3 panel HIGH): cursor_safety_window_seconds is a required
# Protocol member; ``isinstance`` won't catch its absence on stubs that
# happen to define the other methods, so check explicitly here.
_CONNECTOR_ATTRS: frozenset[str] = frozenset(
    {"connector_id", "rate_limit_policy", "cursor_safety_window_seconds"}
)
_MAPPER_ATTRS: frozenset[str] = frozenset({"object_type", "target_table"})


def validate_connector_shape(connector: Any, mapper: Any) -> None:
    """Raise ``ProtocolShapeError`` if connector / mapper don't satisfy CIP shape.

    Checks (in order):
      1. ``isinstance`` against the @runtime_checkable Protocols.
      2. Required class attributes exist.
      3. Each method's positional-parameter count matches the spec.
      4. ``stream_records`` MUST be a generator function (after unwrapping
         decorators).
      5. ``map`` MUST be a generator function (after unwrapping).

    Does NOT verify type annotations — the conformance harness covers that.
    """
    # (1) + (2) connector
    if not isinstance(connector, CIPConnector):
        raise ProtocolShapeError(
            f"{type(connector).__name__} does not satisfy CIPConnector "
            "(missing one of: authenticate, stream_records, describe_schema, "
            "incremental_key, connector_id, rate_limit_policy, "
            "cursor_safety_window_seconds)"
        )
    for attr in _CONNECTOR_ATTRS:
        if not hasattr(connector, attr):
            raise ProtocolShapeError(
                f"{type(connector).__name__} missing required attribute {attr!r}"
            )

    # (1) + (2) mapper
    if not isinstance(mapper, CIPMapper):
        raise ProtocolShapeError(
            f"{type(mapper).__name__} does not satisfy CIPMapper"
        )
    for attr in _MAPPER_ATTRS:
        if not hasattr(mapper, attr):
            raise ProtocolShapeError(
                f"{type(mapper).__name__} missing required attribute {attr!r}"
            )

    # (3) method arity
    _check_arity("connector", connector, _CONNECTOR_SHAPE)
    _check_arity("mapper", mapper, _MAPPER_SHAPE)

    # (4) stream_records generator check
    # v5 PATCH-Q3: inspect.unwrap() walks the __wrapped__ chain so
    # decorator-wrapped generator functions (using @functools.wraps) pass.
    sr = (
        connector.stream_records.__func__
        if hasattr(connector.stream_records, "__func__")
        else connector.stream_records
    )
    if not inspect.isgeneratorfunction(inspect.unwrap(sr)):
        raise ProtocolShapeError(
            f"{type(connector).__name__}.stream_records must be a generator "
            "function (use `yield`, not `return [...]`). If using a "
            "decorator, ensure it preserves __wrapped__ via "
            "functools.wraps and yields from the inner generator."
        )

    # (5) map generator check
    mp = (
        mapper.map.__func__
        if hasattr(mapper.map, "__func__")
        else mapper.map
    )
    if not inspect.isgeneratorfunction(inspect.unwrap(mp)):
        raise ProtocolShapeError(
            f"{type(mapper).__name__}.map must be a generator function"
        )


def _check_arity(
    role: str,
    obj: Any,
    shape: dict[str, tuple[int, frozenset[str]]],
) -> None:
    for name, (expected_pos, required_kwargs) in shape.items():
        method = getattr(obj, name)
        sig = inspect.signature(method)
        # Bound methods have ``self`` already removed from the signature;
        # subtract 1 from the spec's positional count to compare.
        expected = expected_pos - 1
        actual_positional = [
            p
            for p in sig.parameters.values()
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if len(actual_positional) != expected:
            raise ProtocolShapeError(
                f"{role} {type(obj).__name__}.{name} has "
                f"{len(actual_positional)} positional parameter(s); "
                f"expected {expected}"
            )
        for kw in required_kwargs:
            if kw not in sig.parameters:
                raise ProtocolShapeError(
                    f"{role} {type(obj).__name__}.{name} missing "
                    f"required keyword argument {kw!r}"
                )
