# foundry: kind=fixture domain=client-intelligence-platform
"""Canonical fixture records for the connector-conformance harness (M2 §5.1.1).

A fixed corpus used across the §5 conformance tests so the property registry,
SCD-2, and incremental-key paths all key off the same input. Three of the
six tests construct their own inline records in a v1-style design; the
canonical corpus catches regressions where one test's expected shape drifts
from another's.

Record shape: dict (matches what real connectors yield from paginated APIs).
Timestamps: tz-aware UTC ISO-8601 (per PATCH-NR-7 — naive datetimes are
rejected at the framework boundary).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _ts(h: int) -> str:
    """Deterministic timestamps: 2026-04-20 00:00:00+00:00 + h hours."""
    return datetime(2026, 4, 20, h, 0, 0, tzinfo=UTC).isoformat()


def _contact(
    id_: str, first: str, last: str, email: str, hour: int
) -> dict[str, Any]:
    return {
        "id": id_,
        "source_id": id_,
        "first_name": first,
        "last_name": last,
        "email": email,
        "updated_at": _ts(hour),
    }


# Baseline corpus (T0..T9) for incremental-sync first-run.
CANONICAL_CONTACTS: list[dict[str, Any]] = [
    _contact("c001", "Alice",  "Ng",     "alice@ex.com",  0),
    _contact("c002", "Bob",    "Patel",  "bob@ex.com",    1),
    _contact("c003", "Carlos", "Reyes",  "carlos@ex.com", 2),
    _contact("c004", "Dana",   "Singh",  "dana@ex.com",   3),
    _contact("c005", "Elena",  "Torres", "elena@ex.com",  4),
    _contact("c006", "Farouk", "Umar",   "farouk@ex.com", 5),
    _contact("c007", "Greta",  "Vargas", "greta@ex.com",  6),
    _contact("c008", "Hiro",   "Watts",  "hiro@ex.com",   7),
    _contact("c009", "Inez",   "Xu",     "inez@ex.com",   8),
    _contact("c010", "Juno",   "Yoo",    "juno@ex.com",   9),
]

# Delta corpus for the incremental-sync second-run portion.
# c003 is a cross-corpus duplicate (same source_id as baseline) with mutated email
# → tests SCD-2 archive behavior on real-record-mutation.
DELTA_CONTACTS: list[dict[str, Any]] = [
    _contact("c011", "Kai",    "Zhao",  "kai@ex.com",        10),
    _contact("c012", "Lena",   "Ade",   "lena@ex.com",       11),
    _contact("c003", "Carlos", "Reyes", "carlos-v2@ex.com",  12),
]


def _schema_entry(
    name: str,
    *,
    is_custom: bool,
    storage: str,
    column_name: str | None,
    description: str,
) -> dict[str, Any]:
    return {
        "object_type": "contact",
        "property_name": name,
        "data_type": "string",
        "is_custom": is_custom,
        "storage_location": storage,
        "column_name": column_name,
        "description": description,
    }


# 5 PropertyDescriptor source dicts: 3 column-stored + 2 overflow-stored.
# Note: plan §5.1.1 omits ``connector`` and ``cip_table``; MockConnector adds them.
CANONICAL_SCHEMA: list[dict[str, Any]] = [
    _schema_entry(
        "first_name", is_custom=False, storage="column",
        column_name="first_name", description="Given name.",
    ),
    _schema_entry(
        "last_name", is_custom=False, storage="column",
        column_name="last_name", description="Family name.",
    ),
    _schema_entry(
        "email", is_custom=False, storage="column",
        column_name="email", description="Primary email.",
    ),
    _schema_entry(
        "mock_extra_1", is_custom=True, storage="overflow",
        column_name=None, description="Tenant-defined custom property 1.",
    ),
    _schema_entry(
        "mock_extra_2", is_custom=True, storage="overflow",
        column_name=None, description="Tenant-defined custom property 2.",
    ),
]

# v3 (R2-H2) fixture-count invariants (assert at top of first importing test).
assert len(CANONICAL_CONTACTS) == 10, "baseline corpus must be 10 records"
assert len(DELTA_CONTACTS) == 3, "delta corpus must be 3 records (2 new + 1 mutated)"
# v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 13, 2026-05-05):
# Plan §5.1.1 asserts ``len({r['source_id'] for r in DELTA_CONTACTS}) == 2``
# with text "(c011, c012, + duplicate c003)" — but c003 in DELTA is a cross-corpus
# duplicate of baseline's c003, not an intra-batch duplicate, so the SET of
# distinct source_ids in DELTA is {c011, c012, c003} = 3. Plan-text bug.
# Reconciliation: count DELTA distinct == 3; assert NEW (not in baseline) == 2.
# Atlas v5.4 TODO: fix plan §5.1.1 assertion text + count.
assert (
    len({r["source_id"] for r in DELTA_CONTACTS}) == 3
), "delta has 3 distinct source_ids (c011, c012, mutated-c003)"
_baseline_sids = {r["source_id"] for r in CANONICAL_CONTACTS}
_new_in_delta = {r["source_id"] for r in DELTA_CONTACTS} - _baseline_sids
assert len(_new_in_delta) == 2, "delta has 2 source_ids not in baseline (c011, c012)"
assert len(CANONICAL_SCHEMA) == 5, "schema must be 5 descriptors (3 column + 2 overflow)"
