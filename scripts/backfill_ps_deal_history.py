# foundry: kind=script domain=client-intelligence-platform

"""Backfill EcomLever china deal-history into the PS tenant (cip_36 / ASK 6).

PM scope a0aebe06 ASK 6 (foundry-metabase, 2026-05-26). The PS Metabase
period-revenue dashboard needs SCD-2 history snapshots of the China deals;
PS currently has 0 rows in cip_deals_history because the LensMirror has
only ever INSERTed (its archive-on-update path only fires on the
*second* sync of a changed deal, and the current PS mirror is the first
sync). The 107,075 EC china history rows hold the same business history
on the source side — copy them into PS so the period trending is
computable today, while the forward-path archive (`_archive_to_history`
in cip/integration_mesh/persister.py) keeps PS history fresh going
forward.

Pattern: two short-lived connections on one engine, never one connection
holding two GUCs (Phase 2.6 §Q4 idiom):

  1. EC-GUC read: SELECT * FROM lens_china_deals_history → in-memory list.
     lens_china_deals_history (cip_36) selects from cip_deals_history
     under the active GUC and filters to the china subset via the
     properties->>'source' LIKE 'China Referral%' predicate on current
     cip_deals. Under EC GUC this is the 107k EC china history rows.

  2. PS-GUC lookup + write: for each batch, resolve PS cip_deals.id by
     source_id (PS deals carry the same HubSpot source_ids as EC's, the
     mirror preserves them), then INSERT into cip_deals_history with the
     resolved record_id (cip_deals_history.record_id is NOT NULL so
     unmatched source_ids are *skipped*, not NULLed).

What's preserved verbatim:
  - valid_from, valid_to (the temporal envelope IS the business value)
  - ingested_at, refreshed_at (original observation timestamps)
  - authority (validation tier on the source-of-truth row)
  - name, stage, amount, currency, close_date, pipeline, probability,
    tags, properties (the domain snapshot)

What's rewritten:
  - history_id          → new uuid4 per row (PS tenant's row identity)
  - record_id           → looked up: PS cip_deals.id where source_id matches
  - tenant_id           → PS_TENANT_ID
  - source_connector    → 'lens-mirror-deals-v1' (matches PS current
                          cip_deals so PS history is internally
                          consistent with PS current — the forward-path
                          archive will write this same connector going
                          forward)
  - previous_version_id → NULL (we don't remap the EC history chain — PS
                          history chain re-starts here; cip_deals_history
                          schema lets previous_version_id be NULL)
  - ingestion_batch_id  → one fresh uuid4 for the run (so the backfill
                          set is identifiable in cip_sync_runs)
  - changed_by          → 'atlas-ask6-backfill'
  - change_reason       → 'ASK6 historical backfill from ecomlever'

Idempotency: per-batch INSERT … SELECT WHERE NOT EXISTS keyed on
(tenant_id, source_id, valid_from). cip_deals_history has no UNIQUE on
that triple — the cheap WHERE NOT EXISTS is the right primitive here.
Re-running produces 0 inserts and the same skip counts.

Audit: one cip_sync_runs row per run (PS tenant, connector_id =
'lens-mirror-deals-v1-backfill', sync_mode='full'); the run's
batch_id is the same uuid4 used as ingestion_batch_id on the rows.

Usage:
    CIP_DATABASE_URL=postgresql://… \\
        python scripts/backfill_ps_deal_history.py [--dry-run]

Idempotent: yes
Category: migrate
Owner: tim
Lifecycle: active
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

log = logging.getLogger("cip.backfill_ps_deal_history")

EC_TENANT = "dec814db-722a-4730-8e60-51afc4a5dad9"
PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

# How many EC rows per PS write transaction. The 107k universe takes ~20-40
# txns at this batch size; small enough that a transient connection blip
# only loses one batch, large enough that we're not paying round-trip
# overhead per row.
BATCH_SIZE = 2000

PS_CONNECTOR = "lens-mirror-deals-v1"
CHANGED_BY = "atlas-ask6-backfill"
CHANGE_REASON = "ASK6 historical backfill from ecomlever"


@dataclass
class BackfillSummary:
    ec_history_rows: int = 0           # universe read from EC lens
    distinct_source_ids: int = 0       # distinct source_ids across the read
    ps_deals_matched: int = 0          # source_ids resolved to a PS cip_deal.id
    ps_deals_unmatched: int = 0        # source_ids with no PS deal (skip-record-id)
    rows_inserted: int = 0             # new rows written to PS cip_deals_history
    rows_skipped_existing: int = 0     # idempotency hits (NOT EXISTS short-circuit)
    rows_skipped_no_record: int = 0    # row dropped because PS deal not found
    batches: int = 0
    batch_id: str | None = None
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _set_guc(conn: Any, tenant_id: str) -> None:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :tid, false)"),
        {"tid": tenant_id},
    )


def _read_ec_history(engine: Engine) -> list[dict[str, Any]]:
    """Phase 1: read the EC china history universe via lens_china_deals_history.

    One short-lived connection under EC GUC. Returns a list of dict rows
    (decoded by SQLA mappings). Memory: 107k rows × ~1KB ≈ 100MB worst case,
    acceptable for a one-shot.
    """
    with engine.connect() as conn:
        _set_guc(conn, EC_TENANT)
        rows = conn.execute(text(
            """
            SELECT
                history_id, record_id, tenant_id, valid_from, valid_to,
                changed_by, change_reason, source_connector, source_id,
                ingested_at, refreshed_at, previous_version_id,
                ingestion_batch_id, authority,
                name, stage, amount, currency, close_date,
                pipeline, probability, tags, properties
            FROM lens_china_deals_history
            ORDER BY source_id, valid_from
            """
        )).mappings().all()
    return [dict(r) for r in rows]


def _resolve_ps_record_ids(
    engine: Engine, source_ids: list[str]
) -> dict[str, UUID]:
    """Phase 2a: PS-GUC lookup of cip_deals.id by source_id.

    One short-lived connection under PS GUC. Returns a dict source_id → PS
    cip_deals.id. Source_ids with no PS match are absent from the dict;
    callers treat absence as "skip this row".
    """
    if not source_ids:
        return {}
    with engine.connect() as conn:
        _set_guc(conn, PS_TENANT)
        rows = conn.execute(
            text(
                "SELECT id, source_id FROM cip_deals "
                "WHERE tenant_id = :tid AND source_id = ANY(:sids)"
            ),
            {"tid": PS_TENANT, "sids": source_ids},
        ).all()
    return {r.source_id: r.id for r in rows}


# Idempotent INSERT — short-circuits via NOT EXISTS keyed on the natural
# triple (tenant_id, source_id, valid_from). rowcount on a multi-execute
# is the count of rows actually inserted, so we get inserted vs skipped
# directly.
_INSERT_SQL = text(
    """
    INSERT INTO cip_deals_history (
        history_id, record_id, tenant_id, valid_from, valid_to,
        changed_by, change_reason, source_connector, source_id,
        ingested_at, refreshed_at, previous_version_id, ingestion_batch_id,
        authority, name, stage, amount, currency, close_date,
        pipeline, probability, tags, properties
    )
    SELECT
        :history_id, :record_id, :tenant_id, :valid_from, :valid_to,
        :changed_by, :change_reason, :source_connector, :source_id,
        :ingested_at, :refreshed_at, :previous_version_id, :ingestion_batch_id,
        :authority, :name, :stage, :amount, :currency, :close_date,
        :pipeline, :probability, CAST(:tags AS text[]), CAST(:properties AS jsonb)
    WHERE NOT EXISTS (
        SELECT 1 FROM cip_deals_history h
        WHERE h.tenant_id = :tenant_id
          AND h.source_id = :source_id
          AND h.valid_from = :valid_from
    )
    """
)


def _build_row_params(
    row: dict[str, Any], *, ps_record_id: UUID, batch_id: UUID
) -> dict[str, Any]:
    """Map an EC history row → PS insert params. See module docstring for the
    'preserved verbatim' vs 'rewritten' fields."""
    return {
        "history_id": str(uuid4()),
        "record_id": str(ps_record_id),
        "tenant_id": PS_TENANT,
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "changed_by": CHANGED_BY,
        "change_reason": CHANGE_REASON,
        "source_connector": PS_CONNECTOR,
        "source_id": row["source_id"],
        "ingested_at": row["ingested_at"],
        "refreshed_at": row["refreshed_at"],
        "previous_version_id": None,
        "ingestion_batch_id": str(batch_id),
        "authority": row["authority"],
        "name": row["name"],
        "stage": row["stage"],
        "amount": row["amount"],
        "currency": row["currency"],
        "close_date": row["close_date"],
        "pipeline": row["pipeline"],
        "probability": row["probability"],
        # tags: ARRAY(text) — psycopg accepts a Python list; we pass the
        # raw list (None → NULL).
        "tags": row["tags"],
        "properties": json.dumps(row["properties"] or {}),
    }


def _audit_sync_run(
    engine: Engine,
    *,
    batch_id: UUID,
    status: str,
    summary: BackfillSummary,
) -> None:
    """Write a cip_sync_runs audit row under PS GUC. Mirrors the connector
    audit shape so this backfill shows up in the run history alongside
    live LensMirror runs."""
    with engine.begin() as conn:
        _set_guc(conn, PS_TENANT)
        conn.execute(
            text(
                """
                INSERT INTO cip_sync_runs (
                    id, tenant_id, client_id, connector_id, connector_name,
                    batch_id, sync_mode, status,
                    rows_ingested, rows_history, rows_created, rows_updated, rows_skipped,
                    started_at, ended_at, metadata
                ) VALUES (
                    gen_random_uuid(), :tid, NULL,
                    'lens-mirror-deals-v1-backfill', 'ASK6 deal-history backfill',
                    :bid, 'full', :status,
                    0, :rows_history, :rows_history, 0, :rows_skipped,
                    NOW(), NOW(), CAST(:meta AS jsonb)
                )
                """
            ),
            {
                "tid": PS_TENANT,
                "bid": str(batch_id),
                "status": status,
                "rows_history": summary.rows_inserted,
                "rows_skipped": (
                    summary.rows_skipped_existing + summary.rows_skipped_no_record
                ),
                "meta": json.dumps({
                    "scope": "a0aebe06-ASK6",
                    "summary": summary.to_dict(),
                }),
            },
        )


def run_backfill(engine: Engine, *, dry_run: bool = False) -> BackfillSummary:
    s = BackfillSummary(dry_run=dry_run)
    batch_id = uuid4()
    s.batch_id = str(batch_id)

    log.info("Phase 1: reading EC china history via lens_china_deals_history")
    ec_rows = _read_ec_history(engine)
    s.ec_history_rows = len(ec_rows)
    distinct_sids = sorted({r["source_id"] for r in ec_rows})
    s.distinct_source_ids = len(distinct_sids)
    log.info("ec_history_rows=%d distinct_source_ids=%d", s.ec_history_rows, s.distinct_source_ids)

    log.info("Phase 2a: resolving PS cip_deals.id for %d source_ids", len(distinct_sids))
    ps_id_by_src = _resolve_ps_record_ids(engine, distinct_sids)
    s.ps_deals_matched = len(ps_id_by_src)
    s.ps_deals_unmatched = len(distinct_sids) - len(ps_id_by_src)
    log.info(
        "ps_deals_matched=%d ps_deals_unmatched=%d",
        s.ps_deals_matched, s.ps_deals_unmatched,
    )

    if dry_run:
        log.info("--dry-run: skipping inserts")
        # Compute would-be inserted vs skipped-no-record without writing.
        for row in ec_rows:
            if row["source_id"] not in ps_id_by_src:
                s.rows_skipped_no_record += 1
        return s

    log.info("Phase 2b: writing PS cip_deals_history in batches of %d", BATCH_SIZE)
    for i in range(0, len(ec_rows), BATCH_SIZE):
        chunk = ec_rows[i : i + BATCH_SIZE]
        params_list: list[dict[str, Any]] = []
        skipped_no_record_this_batch = 0
        for row in chunk:
            ps_record_id = ps_id_by_src.get(row["source_id"])
            if ps_record_id is None:
                skipped_no_record_this_batch += 1
                continue
            params_list.append(_build_row_params(
                row, ps_record_id=ps_record_id, batch_id=batch_id,
            ))

        s.rows_skipped_no_record += skipped_no_record_this_batch

        if not params_list:
            s.batches += 1
            continue

        with engine.begin() as conn:
            _set_guc(conn, PS_TENANT)
            # executemany returns cumulative rowcount across all parameter
            # sets — which here is the inserted-count because the WHERE
            # NOT EXISTS clause short-circuits dupes to a 0-row insert.
            res = conn.execute(_INSERT_SQL, params_list)
            inserted_this_batch = res.rowcount if res.rowcount is not None else len(params_list)

        s.rows_inserted += inserted_this_batch
        s.rows_skipped_existing += len(params_list) - inserted_this_batch
        s.batches += 1
        log.info(
            "batch %d: inserted=%d skipped_existing=%d skipped_no_record=%d "
            "(running totals: inserted=%d skipped_existing=%d skipped_no_record=%d)",
            s.batches, inserted_this_batch,
            len(params_list) - inserted_this_batch, skipped_no_record_this_batch,
            s.rows_inserted, s.rows_skipped_existing, s.rows_skipped_no_record,
        )

    _audit_sync_run(engine, batch_id=batch_id, status="success", summary=s)
    return s


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Backfill EcomLever china deal-history into PS (ASK 6)"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = (
        os.environ.get("CIP_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("DATABASE_PUBLIC_URL")
    )
    if not url:
        log.error("CIP_DATABASE_URL / DATABASE_URL not set")
        return 2
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = create_engine(url, pool_pre_ping=True)
    try:
        summary = run_backfill(engine, dry_run=args.dry_run)
    finally:
        engine.dispose()

    print("BACKFILL_PS_DEAL_HISTORY_SUMMARY " + json.dumps(summary.to_dict(), sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
