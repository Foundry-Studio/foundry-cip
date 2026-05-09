# foundry: kind=service domain=client-intelligence-platform touches=integration
"""SCD Type 2 differ for the CIP persister (M2 §4.6 binding).

Decides:
  1. Are the new ``CIPRow.fields`` materially different from the current
     DB row's domain columns?
  2. If yes, should a history row be written too (depends on target table)?

Per D-135, SCD Type 2 diffing is performed at the application layer — not
via a Postgres trigger — because app-layer is testable against the canonical
fixture corpus and doesn't require per-table DDL.

M3 Δ7 PLAN-VS-REALITY RECONCILIATION (2026-05-08, M3 step 7).
The original ``_normalize`` returned non-container primitives untouched,
which causes ``Decimal != float`` comparisons to spuriously flag NUMERIC
columns as changed on every re-sync (Python disables Decimal-vs-float
equality for non-binary-exact values like 12345.67). M2 didn't surface
this because cip_contacts has no NUMERIC columns; M3's cip_deals.amount
(NUMERIC) trips it on ~95% of records. ``_normalize`` now coerces all
numeric primitives (int/float/Decimal — excluding bool) to ``Decimal(str(v))``
so DB round-trips compare semantically, not by Python type identity.
Atlas v3.1 plan-hygiene TODO: M3 §4.6 should call out the numeric-equality
contract for the differ when DB columns are NUMERIC/BIGINT.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

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
        # Containers → canonical JSON.
        if isinstance(v, (dict, list)):
            return json.dumps(v, sort_keys=True, default=str)
        # Δ7: numeric scalars → Decimal(str(v)) for cross-type comparability.
        # ``str()`` avoids float-binary loss (str(0.1) == '0.1', not '0.1000...').
        # ``isinstance(True, int)`` is True, so guard against bool first.
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float, Decimal)):
            return Decimal(str(v))
        return v

    @staticmethod
    def _canonical(d: dict[str, object]) -> str:
        return json.dumps(d, sort_keys=True, default=str)
