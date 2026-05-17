# foundry: kind=service domain=client-intelligence-platform touches=integration,storage
"""CIP row persister with bitemporal SCD-2 history (M2 §4.5 binding).

Writes a ``CIPRow`` to ``cip_{entity}`` and (on change) ``cip_{entity}_history``.
Caller responsibilities:
  - ``apply_tenant_context()`` before ``persist()``.
  - Hold the transaction (persister does NOT commit).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .base import (
    ALLOWED_CIP_TABLES,
    HISTORY_TABLE_BY_CURRENT,
    CIPRow,
    HistoricalRecord,
    _assert_tz_aware,
)
from .exceptions import PersistenceError
from .scd_differ import SCDDiffer

# v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 4, 2026-04-29)
# Plan §4.5/§4.6 specifies: uniform `properties` overflow column across all 7 tables.
# Deployed schema (cip_03/04/05): cip_clients uses `metadata`, cip_views has none,
# the other 5 (cip_files/contacts/companies/deals/tickets) use `properties`.
# Reconciliation: per-table mapping driving the INSERT/UPDATE column list.
# Rationale: P-22 / D-123 — migrations are authoritative.
# Atlas v5.4 TODO: update plan §4.5/§4.6 to document per-table extras column.
EXTRAS_COLUMN_BY_TABLE: dict[str, str | None] = {
    "cip_clients": "metadata",
    "cip_views": None,
    "cip_files": "properties",
    "cip_contacts": "properties",
    "cip_companies": "properties",
    "cip_deals": "properties",
    "cip_tickets": "properties",
    "cip_ticket_comments": "properties",
    "cip_engagements": "properties",
    "cip_owners": "properties",
    "cip_pipeline_stages": "properties",
    "cip_marketing_emails": "properties",
    "cip_contact_lists": "properties",
    "cip_contact_list_memberships": None,
}


# ── Identifier safety ──────────────────────────────────────────────────────

_COLUMN_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def _safe_column_name(name: str) -> str:
    """Defense-in-depth identifier validator. Domain column names go into
    INSERT/UPDATE column lists via f-string interpolation (parameterized SQL
    can't bind identifiers); this guard rejects anything that doesn't match
    a snake_case identifier pattern.
    """
    if not _COLUMN_NAME_RE.match(name):
        raise PersistenceError(
            f"Unsafe column name {name!r}; CIP column names must match "
            f"[a-z_][a-z0-9_]*"
        )
    return name


@dataclass
class PersistResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    history: int = 0


class CIPRowPersister:
    """Writes a CIPRow into ``cip_{entity}`` and (on change) ``cip_{entity}_history``.

    Caller responsibilities (NOT this class's):
      - ``apply_tenant_context()`` BEFORE ``persist()``.
      - Hold the transaction (persister does NOT commit).
    """

    def __init__(self, db: Session, differ: SCDDiffer) -> None:
        self.db = db
        self.differ = differ
        # Lazy column-list cache — populated via reflection on first use.
        # Tests pre-populate with stub schemas to avoid DB roundtrips.
        self._col_cache: dict[str, list[str]] = {}

    # ── public API ─────────────────────────────────────────────────────────

    def persist(
        self,
        row: CIPRow,
        *,
        tenant_id: UUID,
        connector_id: str,
        batch_id: UUID,
    ) -> PersistResult:
        # M-18 / Senior #5: closed-enum allowlist. Refuse unknown table names
        # BEFORE any SQL interpolation. Stops a buggy or malicious mapper
        # writing to arbitrary tables.
        if row.target_table not in ALLOWED_CIP_TABLES:
            raise PersistenceError(
                f"Unknown target_table {row.target_table!r}; "
                f"allowed: {sorted(ALLOWED_CIP_TABLES)}"
            )

        # PATCH-NR-7: tz-naive datetime guard on every value in fields.
        for k, v in row.fields.items():
            _assert_tz_aware(v, f"CIPRow.fields[{k!r}]")

        # Defense-in-depth identifier validation on every domain column.
        domain_cols = [_safe_column_name(k) for k in row.fields]

        # v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 5, 2026-04-29)
        # Plan §4.5 specifies: every table has an `overflow` JSONB column.
        # Deployed schema (cip_02_views): cip_views has no extras column.
        # Reconciliation: fail loud when mapper emits overflow into a target
        # that has no extras column — catches mapper bugs the moment a real
        # connector hits it; M2's mock doesn't exercise this path.
        # Rationale: P-22 / D-123 — migrations are authoritative.
        # Atlas v5.4 TODO: update plan §4.5 to document the no-extras case.
        extras_col = EXTRAS_COLUMN_BY_TABLE.get(row.target_table)
        if row.overflow and extras_col is None:
            raise PersistenceError(
                f"table {row.target_table} has no overflow column but mapper "
                f"produced overflow keys: {sorted(row.overflow.keys())}"
            )

        history_table = HISTORY_TABLE_BY_CURRENT.get(row.target_table)

        try:
            return self._persist_with_scd(
                row=row,
                tenant_id=tenant_id,
                connector_id=connector_id,
                batch_id=batch_id,
                domain_cols=domain_cols,
                extras_col=extras_col,
                history_table=history_table,
            )
        except SQLAlchemyError as sqle:
            # H-8: translate SQLAlchemy errors so the orchestrator's
            # ``except PersistenceError`` block catches them.
            raise PersistenceError(str(sqle)) from sqle

    def persist_history_record(
        self,
        record: HistoricalRecord,
        *,
        tenant_id: UUID,
        connector_id: str,
        batch_id: UUID,
    ) -> bool:
        """Single-record D-159 backfill entry point.

        **Status (2026-05-16):** FALLBACK PATH. The orchestrator's
        run_backfill calls ``persist_history_records_batch()`` as the
        PRIMARY production path (one SELECT + one INSERT per flush).
        This method is the per-record SAVEPOINT fallback the orchestrator
        drops to on batch failure (cascade safety) — and a stable
        per-record entry point for tests + connectors that want to
        exercise the path directly.

        New connector authors / orchestrator integrations should call
        ``persist_history_records_batch()`` instead. See
        ``CONNECTOR-AUTHORING-GUIDE.md`` §13 and
        ``SYNC-ORCHESTRATOR-GUIDE.md`` §11.

        Writes a known-historical revision directly to
        ``cip_{entity}_history`` with explicit valid_from / valid_to from
        the source system. Bypasses the SCD-2 differ (the differ exists
        to DETECT changes; backfill records are known-historical, not
        change-detected).

        Looks up the current row's ``id`` by (tenant_id, source_connector,
        source_id) for the ``record_id`` FK. If the current row doesn't
        exist, returns ``False`` (current-state sync must run first).

        Caller responsibilities (SAME as persist()):
          - ``apply_tenant_context()`` BEFORE this call.
          - Hold the transaction.

        Returns:
            True if a history row was inserted; False if current row
            lookup miss (caller decides whether to warn or proceed).
        """
        if record.target_table not in ALLOWED_CIP_TABLES:
            raise PersistenceError(
                f"Unknown target_table {record.target_table!r}; "
                f"allowed: {sorted(ALLOWED_CIP_TABLES)}"
            )
        history_table = HISTORY_TABLE_BY_CURRENT.get(record.target_table)
        if history_table is None:
            raise PersistenceError(
                f"Table {record.target_table!r} has no history table "
                f"(per HISTORY_TABLE_BY_CURRENT)"
            )

        _assert_tz_aware(record.valid_from, "HistoricalRecord.valid_from")
        if record.valid_to is not None:
            _assert_tz_aware(record.valid_to, "HistoricalRecord.valid_to")
        for k, v in record.fields.items():
            _assert_tz_aware(v, f"HistoricalRecord.fields[{k!r}]")

        # Defense-in-depth identifier validation
        for k in record.fields:
            _safe_column_name(k)

        extras_col = EXTRAS_COLUMN_BY_TABLE.get(record.target_table)
        if record.overflow and extras_col is None:
            raise PersistenceError(
                f"table {record.target_table} has no overflow column but "
                f"backfill produced overflow keys: {sorted(record.overflow.keys())}"
            )

        try:
            return self._persist_history_with_lookup(
                record=record,
                tenant_id=tenant_id,
                connector_id=connector_id,
                batch_id=batch_id,
                history_table=history_table,
                extras_col=extras_col,
            )
        except SQLAlchemyError as sqle:
            raise PersistenceError(str(sqle)) from sqle

    def persist_history_records_batch(
        self,
        records: list[HistoricalRecord],
        *,
        tenant_id: UUID,
        connector_id: str,
        batch_id: UUID,
    ) -> dict[str, int]:
        """**PRIMARY D-159 historical backfill entry point.**

        First-class as of 2026-05-16 — the orchestrator's run_backfill
        calls this method on every flush. The single-record
        ``persist_history_record`` is the FALLBACK the orchestrator
        drops to on batch failure (cascade safety).

        For each (target_table, source_id) cohort in the batch:
          1. Single SELECT to look up all current-row ids by source_id
             (one round trip instead of N).
          2. Single INSERT to write all history rows (executemany — one
             round trip's worth of parameter sets instead of N statements).

        Why this matters: the per-record path issued ~2 DB roundtrips
        per HistoricalRecord (1 SELECT + 1 INSERT). For Wayward contacts
        with avg 65 history snapshots per contact, that meant 130
        roundtrips per contact = ~4 contacts/min sustained throughput
        on Railway prod (8-day projected total for 47K contacts).
        Batched path brings it down to 2 roundtrips per FLUSH (typically
        200 records), unlocking the HubSpot HTTP rate-limit ceiling
        (~22 records/sec at 11 req/sec × 50 records/page × 2 calls/page)
        as the binding constraint. ~100-200x speedup measured against
        Wayward prod.

        See ``CONNECTOR-AUTHORING-GUIDE.md`` §13 (the canonical pattern
        for authoring a new connector's backfill) and
        ``SYNC-ORCHESTRATOR-GUIDE.md`` §11 (the two-tier flush path
        documentation) for context.

        Returns counters dict {persisted, skipped_missing_current, failed}.

        Caller responsibilities (SAME as persist_history_record):
          - ``apply_tenant_context()`` BEFORE this call.
          - Hold the transaction.

        On INSERT failure: raises PersistenceError — caller's SAVEPOINT
        (db.begin_nested) rolls back the failed batch; the orchestrator
        retries record-by-record via persist_history_record as a
        fallback. The full-batch-vs-singletons split is the orchestrator's
        responsibility, not this method's.
        """
        counters = {"persisted": 0, "skipped_missing_current": 0, "failed": 0}
        if not records:
            return counters

        # Group by target_table since each table has its own column set +
        # extras_col + history_table mapping.
        by_target: dict[str, list[HistoricalRecord]] = {}
        for r in records:
            by_target.setdefault(r.target_table, []).append(r)

        for target_table, group in by_target.items():
            sub = self._persist_history_records_for_table(
                records=group,
                target_table=target_table,
                tenant_id=tenant_id,
                connector_id=connector_id,
                batch_id=batch_id,
            )
            counters["persisted"] += sub["persisted"]
            counters["skipped_missing_current"] += sub["skipped_missing_current"]
            counters["failed"] += sub["failed"]
        return counters

    def _persist_history_records_for_table(
        self,
        *,
        records: list[HistoricalRecord],
        target_table: str,
        tenant_id: UUID,
        connector_id: str,
        batch_id: UUID,
    ) -> dict[str, int]:
        """Single-table batched history insert. Used by
        persist_history_records_batch. See that method's docstring."""
        counters = {"persisted": 0, "skipped_missing_current": 0, "failed": 0}

        # Validation (defense-in-depth — mirrors persist_history_record).
        if target_table not in ALLOWED_CIP_TABLES:
            raise PersistenceError(
                f"Unknown target_table {target_table!r}; "
                f"allowed: {sorted(ALLOWED_CIP_TABLES)}"
            )
        history_table = HISTORY_TABLE_BY_CURRENT.get(target_table)
        if history_table is None:
            raise PersistenceError(
                f"Table {target_table!r} has no history table "
                f"(per HISTORY_TABLE_BY_CURRENT)"
            )
        extras_col = EXTRAS_COLUMN_BY_TABLE.get(target_table)

        for r in records:
            _assert_tz_aware(r.valid_from, "HistoricalRecord.valid_from")
            if r.valid_to is not None:
                _assert_tz_aware(r.valid_to, "HistoricalRecord.valid_to")
            for k, v in r.fields.items():
                _assert_tz_aware(v, f"HistoricalRecord.fields[{k!r}]")
                _safe_column_name(k)
            if r.overflow and extras_col is None:
                raise PersistenceError(
                    f"table {target_table} has no overflow column but "
                    f"backfill produced overflow keys: "
                    f"{sorted(r.overflow.keys())}"
                )

        # Step 1: batch lookup of current IDs.
        source_ids = sorted({r.source_id for r in records})
        try:
            lookup_rows = self.db.execute(
                sa.text(
                    f"SELECT id, source_id FROM {target_table} "
                    f"WHERE tenant_id = :tid "
                    f"  AND source_connector = :sc "
                    f"  AND source_id = ANY(:sids)"
                ),
                {
                    "tid": str(tenant_id),
                    "sc": connector_id,
                    "sids": source_ids,
                },
            ).all()
        except SQLAlchemyError as sqle:
            raise PersistenceError(str(sqle)) from sqle
        id_by_source: dict[str, object] = {row[1]: row[0] for row in lookup_rows}

        found_records: list[HistoricalRecord] = []
        for r in records:
            if r.source_id in id_by_source:
                found_records.append(r)
            else:
                counters["skipped_missing_current"] += 1

        if not found_records:
            return counters

        # Step 2: compute the union of domain columns present in this batch
        # AND on the history table. Columns missing from a given record's
        # fields → NULL in that row.
        history_cols = self._get_table_columns(history_table)
        history_col_set = set(history_cols)
        domain_cols_set: set[str] = set()
        for r in found_records:
            for f in r.fields:
                safe = _safe_column_name(f)
                if safe in history_col_set:
                    domain_cols_set.add(safe)
        domain_cols = sorted(domain_cols_set)

        # Step 3: build INSERT template with provenance + domain columns + extras.
        fixed_columns: list[tuple[str, str]] = [
            # (column_name, value_expression)
            ("history_id", "gen_random_uuid()"),
            ("record_id", ":record_id"),
            ("tenant_id", ":tenant_id"),
            ("valid_from", ":valid_from"),
            ("valid_to", ":valid_to"),
            ("changed_by", ":changed_by"),
            ("change_reason", ":change_reason"),
            ("source_connector", ":source_connector"),
            ("source_id", ":source_id"),
            ("ingested_at", ":ingested_at"),
            ("refreshed_at", ":refreshed_at"),
            ("ingestion_batch_id", ":ingestion_batch_id"),
            ("authority", ":authority"),
            ("previous_version_id", "NULL"),
        ]
        col_exprs: list[tuple[str, str]] = [
            (col, expr) for col, expr in fixed_columns if col in history_col_set
        ]
        for col in domain_cols:
            col_exprs.append((col, f":f_{col}"))
        if extras_col is not None and extras_col in history_col_set:
            col_exprs.append((extras_col, "CAST(:extras AS jsonb)"))

        cols_sql = ", ".join(c for c, _ in col_exprs)
        vals_sql = ", ".join(e for _, e in col_exprs)
        insert_sql = (
            f"INSERT INTO {history_table} ({cols_sql}) VALUES ({vals_sql})"
        )

        # Step 4: build per-row params dict.
        rows_params: list[dict[str, object]] = []
        for r in found_records:
            row_params: dict[str, object] = {
                "record_id": str(id_by_source[r.source_id]),
                "tenant_id": str(tenant_id),
                "valid_from": r.valid_from,
                "valid_to": r.valid_to,
                "changed_by": r.changed_by or connector_id,
                "change_reason": r.change_reason,
                "source_connector": connector_id,
                "source_id": r.source_id,
                "ingested_at": r.valid_from,
                "refreshed_at": r.valid_from,
                "ingestion_batch_id": str(batch_id),
                "authority": "ingested",
            }
            for col in domain_cols:
                row_params[f"f_{col}"] = r.fields.get(col)
            if extras_col is not None and extras_col in history_col_set:
                row_params["extras"] = (
                    json.dumps(r.overflow, sort_keys=True, default=str)
                    if r.overflow else None
                )
            rows_params.append(row_params)

        # Step 5: single executemany. SQLAlchemy + psycopg3 pipelines
        # this efficiently across the wire.
        try:
            self.db.execute(sa.text(insert_sql), rows_params)
        except SQLAlchemyError as sqle:
            # On batch failure, raise so caller's SAVEPOINT rolls back.
            # Caller is expected to retry one-by-one via
            # persist_history_record as a fallback.
            raise PersistenceError(str(sqle)) from sqle

        counters["persisted"] = len(found_records)
        return counters

    def _persist_history_with_lookup(
        self,
        *,
        record: HistoricalRecord,
        tenant_id: UUID,
        connector_id: str,
        batch_id: UUID,
        history_table: str,
        extras_col: str | None,
    ) -> bool:
        # 1. Look up current row's id by natural key. The cip_*_history
        #    `record_id` column is FK to main.id.
        lookup_sql = (
            f"SELECT id FROM {record.target_table} "
            f"WHERE tenant_id = :tid "
            f"  AND source_connector = :sc "
            f"  AND source_id = :sid"
        )
        cur_id_row = self.db.execute(
            sa.text(lookup_sql),
            {
                "tid": str(tenant_id),
                "sc": connector_id,
                "sid": record.source_id,
            },
        ).first()
        if cur_id_row is None:
            # Current row not yet materialized — caller must run_sync first.
            return False
        current_id = cur_id_row[0]

        # 2. Build INSERT into history table. Columns:
        #    history_id   = gen_random_uuid()
        #    record_id    = current_id
        #    tenant_id    = :tid
        #    valid_from   = :valid_from
        #    valid_to     = :valid_to (nullable)
        #    changed_by   = :changed_by
        #    change_reason = :change_reason (nullable)
        #    source_connector / source_id / ingested_at / refreshed_at /
        #      ingestion_batch_id / authority = explicit
        #    {extras_col}: JSONB cast from record.overflow
        #    + per-table domain columns from record.fields
        history_cols = self._get_table_columns(history_table)

        col_to_value_expr: dict[str, str] = {}
        params: dict[str, object] = {
            "tid": str(tenant_id),
            "sc": connector_id,
            "sid": record.source_id,
            "valid_from": record.valid_from,
            "valid_to": record.valid_to,
            "changed_by": record.changed_by or connector_id,
            "change_reason": record.change_reason,
            "current_id": str(current_id),
            "batch_id": str(batch_id),
            "ingested_at": record.valid_from,
            "refreshed_at": record.valid_from,
            "authority": "ingested",
        }

        # Provenance + history columns (deterministic SET):
        col_to_value_expr["history_id"] = "gen_random_uuid()"
        col_to_value_expr["record_id"] = ":current_id"
        col_to_value_expr["tenant_id"] = ":tid"
        col_to_value_expr["valid_from"] = ":valid_from"
        col_to_value_expr["valid_to"] = ":valid_to"
        col_to_value_expr["changed_by"] = ":changed_by"
        col_to_value_expr["change_reason"] = ":change_reason"
        col_to_value_expr["source_connector"] = ":sc"
        col_to_value_expr["source_id"] = ":sid"
        col_to_value_expr["ingested_at"] = ":ingested_at"
        col_to_value_expr["refreshed_at"] = ":refreshed_at"
        col_to_value_expr["ingestion_batch_id"] = ":batch_id"
        col_to_value_expr["authority"] = ":authority"
        # previous_version_id is optional (NULL on backfill — chain unknown).
        col_to_value_expr["previous_version_id"] = "NULL"

        # Domain columns from record.fields:
        for col_name, value in record.fields.items():
            safe = _safe_column_name(col_name)
            param_name = f"f_{safe}"
            col_to_value_expr[safe] = f":{param_name}"
            params[param_name] = value

        # Overflow → extras JSONB column:
        if extras_col is not None and record.overflow:
            col_to_value_expr[extras_col] = "CAST(:extras AS jsonb)"
            params["extras"] = json.dumps(record.overflow, sort_keys=True, default=str)

        # Filter to columns actually present in the history table; warn
        # silently on any extras we'd want but the schema doesn't have.
        history_col_set = set(history_cols)
        insertable = [
            (col, expr) for col, expr in col_to_value_expr.items()
            if col in history_col_set
        ]
        if not insertable:
            raise PersistenceError(
                f"No insertable columns matched for history table "
                f"{history_table}"
            )

        cols_sql = ", ".join(col for col, _ in insertable)
        vals_sql = ", ".join(expr for _, expr in insertable)
        insert_sql = (
            f"INSERT INTO {history_table} ({cols_sql}) "
            f"VALUES ({vals_sql})"
        )
        self.db.execute(sa.text(insert_sql), params)
        return True

    # ── internals ─────────────────────────────────────────────────────────

    def _persist_with_scd(
        self,
        *,
        row: CIPRow,
        tenant_id: UUID,
        connector_id: str,
        batch_id: UUID,
        domain_cols: list[str],
        extras_col: str | None,
        history_table: str | None,
    ) -> PersistResult:
        target_table = row.target_table

        # 1. SELECT FOR UPDATE the current row (locked).
        # v4 (Round-3 panel CRIT-2): explicit ORDER BY source_id ensures
        # concurrent batches that touch overlapping records acquire row
        # locks in the same order — prevents the deadlock class entirely.
        # v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 6, 2026-04-29)
        # Plan §4.5 SQL: WHERE source_id = :source_id (assumes NOT NULL).
        # Deployed schema (cip_04_files): source_id is nullable on cip_files.
        # Reconciliation: IS NOT DISTINCT FROM uniformly across all 7 tables;
        # standard Postgres idiom for SCD lookups against nullable natural keys.
        # The (tenant_id, source_connector, source_id) index handles either way.
        # Rationale: P-22 / D-123 — migrations are authoritative.
        # Atlas v5.4 TODO: update plan §4.5 to use IS NOT DISTINCT FROM.
        select_sql = (
            f"SELECT * FROM {target_table} "
            f"WHERE tenant_id = :tenant_id "
            f"  AND source_connector = :source_connector "
            f"  AND source_id IS NOT DISTINCT FROM :source_id "
            f"ORDER BY source_id "
            f"FOR UPDATE"
        )
        select_params: dict[str, object] = {
            "tenant_id": str(tenant_id),
            "source_connector": connector_id,
            "source_id": row.source_id,
        }
        current_full = (
            self.db.execute(sa.text(select_sql), select_params)
            .mappings()
            .first()
        )

        if current_full is None:
            return self._insert_new(
                row=row,
                tenant_id=tenant_id,
                connector_id=connector_id,
                batch_id=batch_id,
                domain_cols=domain_cols,
                extras_col=extras_col,
            )

        # 2. Diff new fields/overflow against current.
        current_dict = dict(current_full)
        current_id = current_dict["id"]

        # The SCDDiffer expects ``current_row["overflow"]`` as the framework
        # name; remap from the deployed extras column name.
        current_extras = current_dict.get(extras_col) if extras_col else {}
        current_for_diff = {**current_dict, "overflow": current_extras}
        diff = self.differ.diff(
            target_table=target_table,
            current_row=current_for_diff,
            new_fields=row.fields,
            new_overflow=row.overflow,
        )

        if not diff.changed:
            # 3a. Refresh-only update.
            self.db.execute(
                sa.text(
                    f"UPDATE {target_table} "
                    f"SET refreshed_at = now() "
                    f"WHERE id = :id"
                ),
                {"id": str(current_id)},
            )
            return PersistResult(skipped=1)

        # 3b. Changed — archive to history if applicable.
        history_id: UUID | None = None
        if diff.write_history and history_table is not None:
            history_id = self._archive_to_history(
                target_table=target_table,
                history_table=history_table,
                current_id=current_id,
                connector_id=connector_id,
            )

        # 3c. Update current with new values.
        self._update_current(
            row=row,
            target_table=target_table,
            current_id=current_id,
            batch_id=batch_id,
            domain_cols=domain_cols,
            extras_col=extras_col,
            new_history_id=history_id,
        )
        return PersistResult(
            updated=1,
            history=1 if history_id is not None else 0,
        )

    def _insert_new(
        self,
        *,
        row: CIPRow,
        tenant_id: UUID,
        connector_id: str,
        batch_id: UUID,
        domain_cols: list[str],
        extras_col: str | None,
    ) -> PersistResult:
        target_table = row.target_table

        # Provenance + scoping columns the persister always sets.
        col_list: list[str] = [
            "tenant_id",
            "client_id",
            "source_connector",
            "source_id",
            "ingestion_batch_id",
            "authority",
        ]
        val_list: list[str] = [
            ":tenant_id",
            ":client_id",
            ":source_connector",
            ":source_id",
            ":batch_id",
            ":authority",
        ]
        params: dict[str, object] = {
            "tenant_id": str(tenant_id),
            "client_id": str(row.client_id) if row.client_id else None,
            "source_connector": connector_id,
            "source_id": row.source_id,
            "batch_id": str(batch_id),
            "authority": row.authority,
        }
        # Domain columns the mapper emitted.
        for c in domain_cols:
            col_list.append(c)
            val_list.append(f":{c}")
            params[c] = row.fields[c]
        # Extras column — bound to whichever name the deployed table uses.
        if extras_col is not None:
            col_list.append(extras_col)
            val_list.append("CAST(:_extras AS jsonb)")
            params["_extras"] = json.dumps(row.overflow, default=str)

        insert_sql = (
            f"INSERT INTO {target_table} ({', '.join(col_list)}) "
            f"VALUES ({', '.join(val_list)})"
        )
        self.db.execute(sa.text(insert_sql), params)
        return PersistResult(created=1)

    def _update_current(
        self,
        *,
        row: CIPRow,
        target_table: str,
        current_id: object,
        batch_id: UUID,
        domain_cols: list[str],
        extras_col: str | None,
        new_history_id: UUID | None,
    ) -> None:
        set_parts: list[str] = [
            "refreshed_at = now()",
            "ingestion_batch_id = :batch_id",
        ]
        params: dict[str, object] = {
            "id": str(current_id),
            "batch_id": str(batch_id),
        }
        for c in domain_cols:
            set_parts.append(f"{c} = :{c}")
            params[c] = row.fields[c]
        if extras_col is not None:
            set_parts.append(f"{extras_col} = CAST(:_extras AS jsonb)")
            params["_extras"] = json.dumps(row.overflow, default=str)
        if new_history_id is not None:
            set_parts.append("previous_version_id = :prev_id")
            params["prev_id"] = str(new_history_id)
        update_sql = (
            f"UPDATE {target_table} "
            f"SET {', '.join(set_parts)} "
            f"WHERE id = :id"
        )
        self.db.execute(sa.text(update_sql), params)

    def _archive_to_history(
        self,
        *,
        target_table: str,
        history_table: str,
        current_id: object,
        connector_id: str,
    ) -> UUID:
        """Bitemporal SCD-2 archive: copy current → history.

        v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 2, 2026-04-29)
        Plan §4.5: simple ``archived_at`` history pattern.
        Deployed schema (cip_*_history): bitemporal SCD-2 with ``valid_from``,
        ``valid_to``, ``changed_by`` (NOT NULL), ``change_reason`` (nullable),
        ``record_id`` (FK → current.id, NOT ``id``). No ``client_id`` /
        ``created_at`` / ``updated_at`` in history.
        Reconciliation:
          - history_id   ← gen_random_uuid()
          - record_id    ← current.id
          - valid_from   ← current.refreshed_at (when it became current)
          - valid_to     ← now() (when it stops being current)
          - changed_by   ← :changed_by (the connector_id)
          - change_reason ← NULL (M2 leaves blank; Phase 3+ may populate)
          - everything else (provenance + domain + extras) ← copy from current
        Rationale: P-22 / D-123 — migrations are authoritative; the
        bitemporal model is the deployed truth.
        Atlas v5.4 TODO: update plan §4.5 to match deployed bitemporal SCD-2.
        """
        history_cols = self._get_table_columns(history_table)
        target_col_set = set(self._get_table_columns(target_table))

        select_exprs: list[str] = []
        for h in history_cols:
            if h == "history_id":
                select_exprs.append("gen_random_uuid()")
            elif h == "record_id":
                select_exprs.append("id")
            elif h == "valid_from":
                # When this revision became current — its refreshed_at on
                # the row we are about to supersede.
                select_exprs.append("refreshed_at")
            elif h == "valid_to":
                # When it stops being current — exactly now.
                select_exprs.append("now()")
            elif h == "changed_by":
                select_exprs.append(":changed_by")
            elif h == "change_reason":
                select_exprs.append("NULL")
            elif h in target_col_set:
                select_exprs.append(h)
            else:
                raise PersistenceError(
                    f"History table {history_table} has column {h!r} "
                    f"with no matching source in {target_table}"
                )

        sql = (
            f"INSERT INTO {history_table} ({', '.join(history_cols)}) "
            f"SELECT {', '.join(select_exprs)} "
            f"FROM {target_table} "
            f"WHERE id = :current_id "
            f"RETURNING history_id"
        )
        params: dict[str, object] = {
            "current_id": str(current_id),
            "changed_by": connector_id,
        }
        result = self.db.execute(sa.text(sql), params)
        # Defensive cast: scalar_one() returns Any; psycopg returns UUID
        # for as_uuid=True columns, but accept str fallback.
        return UUID(str(result.scalar_one()))

    def _get_table_columns(self, table_name: str) -> list[str]:
        """Return ordered column names of ``table_name``, lazily reflecting
        + caching. Tests pre-populate ``self._col_cache[table_name]`` to
        avoid DB roundtrips."""
        if table_name not in self._col_cache:
            bind = self.db.get_bind()
            inspector = sa.inspect(bind)
            self._col_cache[table_name] = [
                str(c["name"]) for c in inspector.get_columns(table_name)
            ]
        return self._col_cache[table_name]
