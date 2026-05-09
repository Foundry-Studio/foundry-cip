# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Compile ``filter_config`` JSONB → SQLAlchemy WHERE clause (M4 §4.3 binding).

v1 (M4): equality-only. ``{"<field>": <value>}`` → ``WHERE <field> = <value>``.
Empty ``{}`` → no predicate (returns ``sa.true()``).

Supported value types: ``str``, ``int``, ``bool``, ``None``.
Unsupported: ``list``, ``dict`` (nested), ``date``, sequence operators
(``$eq``, ``$in``, etc.).

v2+ (M6 / Phase 2): operator extensibility. ``{"$eq", "$ne", "$in", "$gt"}``
pattern. v1 dicts remain compatible — ``{"region": "eu-west"}`` reads
identically as ``{"region": {"$eq": "eu-west"}}`` once operators ship.

Security boundary defenses (per M4 v2 QC1 hardening):
- ``_RESERVED_COLUMNS`` allow-list (Senior [3] + Gap [8]) — provenance / SCD /
  tenancy columns are ineligible for filtering. Defense-in-depth on top of
  RLS; prevents footgun lens definitions.
- ``_FORBIDDEN_OPERATOR_TOKENS`` (Stress [9]) — preempts MongoDB-class CVEs.
  v1 doesn't support operators at all, but reserves the ``$``-prefix.
- ``_MAX_FILTER_CONFIG_KEYS = 32`` DoS guard (Stress [8]) — JSONB allows ~1GB;
  a malicious row with thousands of keys would explode AND-chain compile.
- Type-check before falsy short-circuit (Gap [3]) — empty-string / 0 / False /
  empty-list inputs raise loud instead of silently returning ``sa.true()``.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.sql import ColumnElement

from .exceptions import LensCompilationError

_SUPPORTED_VALUE_TYPES = (str, int, bool, type(None))


# v2 (Senior [3] + Gap [8]): security-boundary allow-list. Reject filter
# fields that target provenance / SCD / tenancy columns. RLS is the primary
# guard; this is defense-in-depth + foot-gun prevention.
_RESERVED_COLUMNS: frozenset[str] = frozenset(
    {
        # Provenance (every cip_<entity> table has these)
        "id",
        "tenant_id",
        "client_id",
        "source_connector",
        "source_id",
        "ingested_at",
        "refreshed_at",
        "previous_version_id",
        "ingestion_batch_id",
        "authority",
        # Standard timestamps
        "created_at",
        "updated_at",
        # Bitemporal SCD-2 history columns (cip_<entity>_history tables)
        "valid_from",
        "valid_to",
        "_valid_from",
        "_valid_to",
        "is_current",
        "history_id",
        "record_id",
        "changed_by",
        "change_reason",
    }
)


# v2 (Stress [9]): preempt MongoDB-class operator-injection CVEs. v1 doesn't
# support operators at all, but v2+ will add ``$op`` syntax. Reject these
# tokens NOW so future v2 dispatch can never accidentally enable them.
# The bare ``$`` entry catches any ``$``-prefixed key (compiler also checks
# ``startswith('$')`` defensively).
_FORBIDDEN_OPERATOR_TOKENS: frozenset[str] = frozenset(
    {
        "$where",
        "$function",
        "$expr",
        "$accumulator",
        "$",
    }
)


# v2 (Stress [8]): DoS guard. A malicious lens row with thousands of keys
# would explode AND-chain compile + SQL parse. JSONB column allows ~1GB.
_MAX_FILTER_CONFIG_KEYS: int = 32


def compile_filter(
    filter_config: Any,
    target_table: sa.Table,
) -> ColumnElement[bool]:
    """Compile ``filter_config`` dict to SQLAlchemy WHERE clause.

    v1 (M4): equality-only. ``{"<field>": <value>}`` → ``WHERE <field> = <value>``.
    Empty ``{}`` → no predicate (returns ``sa.true()``).

    Args:
        filter_config: value from ``cip_views.filter_config`` JSONB column.
            MUST be a dict; non-dict inputs raise ``LensCompilationError``
            (per v2 fix — type-check BEFORE falsy short-circuit).
        target_table: SQLAlchemy ``Table`` to validate column names against.

    Returns:
        SQLAlchemy ``ColumnElement`` (boolean expression). Compose with
        ``sa.and_()`` for AND-composition with other predicates (e.g., RLS
        already-applied).

    Raises:
        LensCompilationError: ``filter_config`` malformed, references unknown
            column, references reserved column (provenance/SCD/tenancy),
            references forbidden operator token, or exceeds size cap.
    """
    # v2 (Gap [3]): type-check BEFORE falsy short-circuit. v1 had ``if not
    # filter_config: return sa.true()`` first, which let "" / 0 / False / [] /
    # {} all pass — masking corrupt cip_views.filter_config rows as no-op.
    if not isinstance(filter_config, dict):
        raise LensCompilationError(
            f"filter_config must be a dict, got "
            f"{type(filter_config).__name__}: {filter_config!r}"
        )

    if not filter_config:
        return sa.true()

    # v2 (Stress [8]): DoS guard.
    if len(filter_config) > _MAX_FILTER_CONFIG_KEYS:
        raise LensCompilationError(
            f"filter_config has {len(filter_config)} keys, exceeds cap of "
            f"{_MAX_FILTER_CONFIG_KEYS}"
        )

    # v2 (Gap [4]): explicit empty-table guard.
    table_columns = {col.name for col in target_table.columns}
    if not table_columns:
        raise LensCompilationError(
            f"target_table {target_table.name!r} has no columns; "
            f"likely a stub Table or cross-metadata mismatch"
        )

    predicates: list[ColumnElement[bool]] = []

    for field_name, value in filter_config.items():
        if not isinstance(field_name, str):
            raise LensCompilationError(
                f"filter_config keys must be str, got "
                f"{type(field_name).__name__}: {field_name!r}"
            )

        # v2 (Stress [9]): forbidden operator token check. Reject anything
        # starting with '$' OR exact-matching the forbidden set.
        if field_name.startswith("$") or field_name in _FORBIDDEN_OPERATOR_TOKENS:
            raise LensCompilationError(
                f"filter_config field {field_name!r} uses '$'-prefix or "
                f"forbidden operator token; v1 supports equality-only on plain "
                f"field names; v2 operator extensibility deferred"
            )

        # v2 (Senior [3] + Gap [8]): reserved-column allow-list.
        if field_name in _RESERVED_COLUMNS:
            raise LensCompilationError(
                f"filter_config field {field_name!r} is a reserved column "
                f"(provenance/SCD/tenancy); reserved set: "
                f"{sorted(_RESERVED_COLUMNS)}"
            )

        if field_name not in table_columns:
            raise LensCompilationError(
                f"filter_config field {field_name!r} not a column of "
                f"{target_table.name!r}; available columns "
                f"(excluding reserved): "
                f"{sorted(table_columns - _RESERVED_COLUMNS)}"
            )

        # v2 (Stress [9]): reject operator-shaped values too. v1 must
        # fail-fast on accidental v2 syntax like ``{"region": {"$eq": "X"}}``.
        if isinstance(value, dict):
            raise LensCompilationError(
                f"filter_config value for field {field_name!r} is a dict "
                f"(looks like v2 operator syntax); v1 supports equality-only "
                f"with str/int/bool/None values; got {value!r}"
            )

        # bool is a subclass of int; check bool first so ``True``/``False``
        # are accepted explicitly (and excluded from the int branch's surprise).
        if not isinstance(value, _SUPPORTED_VALUE_TYPES):
            raise LensCompilationError(
                f"filter_config value type {type(value).__name__} for field "
                f"{field_name!r} unsupported in v1; v1 supports "
                f"{[t.__name__ for t in _SUPPORTED_VALUE_TYPES]}; got {value!r}"
            )

        col = target_table.c[field_name]
        if value is None:
            predicates.append(col.is_(None))
        else:
            predicates.append(col == value)

    return sa.and_(*predicates)
