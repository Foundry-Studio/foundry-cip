# foundry: kind=service domain=client-intelligence-platform touches=integration
"""SCD Type 2 differ for the CIP persister (M2 §4.6 binding).

Decides:
  1. Are the new ``CIPRow.fields`` materially different from the current
     DB row's domain columns?
  2. If yes, should a history row be written too (depends on target table)?

Per D-135, SCD Type 2 diffing is performed at the application layer — not
via a Postgres trigger — because app-layer is testable against the canonical
fixture corpus and doesn't require per-table DDL.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

# Tables updated in-place — no history sibling.
NO_HISTORY_TABLES: frozenset[str] = frozenset(
    {
        "cip_connector_property_registry",
        "cip_sync_runs",
    }
)

# Provenance / SCD-metadata columns that should never count as "changes"
# even if the differ encounters them.
METADATA_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "ingested_at",
        "refreshed_at",
        "previous_version_id",
        "ingestion_batch_id",
    }
)


@dataclass
class DiffResult:
    """Result of one diff. ``changed_columns`` is logged at DEBUG by the
    orchestrator on every history-write decision."""

    changed: bool
    changed_columns: list[str]
    write_history: bool


class SCDDiffer:
    """Pure-function differ wrapped in a class for injection / testing."""

    def should_write_history(self, target_table: str) -> bool:
        """Return ``True`` iff a history row should be written when the
        domain columns change."""
        return target_table not in NO_HISTORY_TABLES

    def diff(
        self,
        *,
        target_table: str,
        current_row: dict[str, object],
        new_fields: dict[str, object],
        new_overflow: dict[str, object],
    ) -> DiffResult:
        """Compare ``new_fields`` + ``new_overflow`` against ``current_row``.

        Note: keys in ``new_fields`` that don't exist in ``current_row`` are
        treated as additions (changed). Keys in ``current_row`` that don't
        exist in ``new_fields`` are treated as no-change (per §4.5 edge
        case "Null vs missing: if ``row.fields`` omits a column, treat as
        'no change'").
        """
        changed_columns: list[str] = []

        # Compare domain columns the mapper emitted.
        for key, new_val in new_fields.items():
            if key in METADATA_COLUMNS:
                continue
            if self._normalize(current_row.get(key)) != self._normalize(new_val):
                changed_columns.append(key)

        # Compare overflow via canonical JSON to dodge key-order false
        # positives. Both sides default to ``{}``.
        cur_overflow_obj = current_row.get("overflow") or {}
        cur_of = self._canonical(cur_overflow_obj if isinstance(cur_overflow_obj, dict) else {})
        new_of = self._canonical(new_overflow or {})
        if cur_of != new_of:
            changed_columns.append("overflow")

        changed = bool(changed_columns)
        return DiffResult(
            changed=changed,
            changed_columns=changed_columns,
            write_history=changed and self.should_write_history(target_table),
        )

    @staticmethod
    def _normalize(v: object) -> object:
        # Normalize containers via canonical JSON; primitives untouched.
        if isinstance(v, (dict, list)):
            return json.dumps(v, sort_keys=True, default=str)
        return v

    @staticmethod
    def _canonical(d: dict[str, object]) -> str:
        return json.dumps(d, sort_keys=True, default=str)
