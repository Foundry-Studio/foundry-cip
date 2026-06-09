# foundry: kind=module domain=client-intelligence-platform
"""Project Silk (PS) — EcomLever → PS china-subset LensMirror runner.

PM scope 8d47e809 (2026-06-09). Lifts the Pass-1 + Pass-2 orchestration
from ``scripts/orchestrate_ps_lens_mirror.py`` into a callable so it can
be driven from anywhere (scheduler, ad-hoc CLI, tests). The script
remains as the operator-facing wrapper.

Two passes:

  PASS 1 — derive PS ``cip_clients`` from ``lens_china_companies``
    Read EcomLever's china companies lens under EC GUC. For each, build a
    deterministic PS client_id via ``uuid5(ps_tenant, "wayward-china:<id>")``
    and upsert into ``cip_clients`` under PS GUC. Then backfill
    ``initial_intake_route='wayward'`` for any PS rows where it was NULL
    (insert-only — Atlas C-2).

  PASS 2 — mirror entities (deals, companies, contacts)
    For each entity, instantiate ``LensMirrorConnector`` + the per-entity
    ``LensMirrorMapper`` and call ``run_sync(..., sync_mode='lens-mirror')``.
    The orchestrator's existing pipeline handles the writes; the mapper's
    ``client_id_lookup`` resolves each row's PS client_id from Pass 1.

Tickets are NOT mirrored (Atlas Q5 scope-trim 2026-05-22: tickets are
Zendesk-sourced and need cross-connector identity resolution, separate
project).

Public API:
  ``run_ps_china_mirror(*, engine, ps_tenant_id, dry_run=False, database_url=None)``
    Returns a JSON-safe summary dict (see function docstring for shape).

The function:
  - does NOT print to stdout (logs via stdlib logger)
  - does NOT read env vars (caller passes everything)
  - does NOT call ``sys.exit`` (raises ``ValueError`` on precondition failures)
  - is safe to call from a scheduler executor or from a script
"""
from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.engine import Engine

from cip.integration_mesh.connectors.lens_mirror import (
    LensMirrorCompanyMapper,
    LensMirrorConnector,
    LensMirrorContactMapper,
    LensMirrorDealMapper,
)
from cip.integration_mesh.orchestrator import run_sync
from cip.integration_mesh.wayward_constants import ECOMLEVER_TENANT_ID

logger = logging.getLogger(__name__)

# DESIGN NOTE: the OLD scripts/orchestrate_ps_lens_mirror.py verified the
# PS tenant existed in the FAS-owned `tenants` table before running. That
# check is **caller-side**: CIP must not depend on a FAS schema. Callers
# (the operator script + the FAS subsystem_scheduler wrapper) own the
# precondition. This module does the work; it doesn't pre-flight FAS-side
# invariants.


def _pass1_upsert_clients(
    engine: Engine, ps_tenant: UUID, *, dry_run: bool
) -> tuple[dict[str, UUID], dict[str, int]]:
    """Read source china companies, derive deterministic PS client_ids,
    upsert into cip_clients (PS tenant).

    Returns a tuple of (lookup, counters) where lookup is the source_id →
    ps_client_id dict and counters is a small dict matching the
    ``pass_1`` shape documented on ``run_ps_china_mirror``.
    """
    lookup: dict[str, UUID] = {}
    counters = {
        "source_china_companies": 0,
        "inserted": 0,
        "updated": 0,
        "intake_route_backfilled": 0,
    }
    batch_id = uuid4()

    with engine.begin() as c:
        c.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(ECOMLEVER_TENANT_ID)},
        )
        rows = c.execute(
            text("SELECT source_id, name FROM lens_china_companies")
        ).mappings().all()

    counters["source_china_companies"] = len(rows)
    if not rows:
        logger.info("ps-mirror Pass 1: lens_china_companies empty; abort")
        return lookup, counters

    # Build the lookup deterministically — no DB needed.
    for r in rows:
        hubspot_id = r["source_id"]
        if not hubspot_id:
            continue
        ps_client = uuid5(ps_tenant, f"wayward-china:{hubspot_id}")
        lookup[str(hubspot_id)] = ps_client

    if dry_run:
        logger.info(
            "ps-mirror Pass 1 DRY-RUN: would upsert %d cip_clients rows",
            len(lookup),
        )
        return lookup, counters

    # Upsert into cip_clients (PS tenant). Idempotent via
    # uq_cip_clients_source (tenant_id, source_connector, source_id).
    inserted = 0
    updated = 0
    with engine.begin() as c:
        c.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(ps_tenant)},
        )
        for r in rows:
            hubspot_id = r["source_id"]
            if not hubspot_id:
                continue
            ps_client = lookup[str(hubspot_id)]
            res = c.execute(
                text(
                    """
                    INSERT INTO cip_clients (
                        id, tenant_id, client_id, source_connector, source_id,
                        ingested_at, refreshed_at, ingestion_batch_id, authority,
                        name, slug, industry, metadata,
                        created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), :t, :c, 'lens-mirror', :src,
                        NOW(), NOW(), :batch, 'ingested',
                        :name, :slug, NULL, :meta,
                        NOW(), NOW()
                    )
                    ON CONFLICT (tenant_id, source_connector, source_id) DO UPDATE
                      SET refreshed_at = NOW(),
                          name = EXCLUDED.name,
                          slug = EXCLUDED.slug,
                          updated_at = NOW()
                    RETURNING (xmax = 0) AS inserted_flag
                    """
                ),
                {
                    "t": str(ps_tenant),
                    "c": str(ps_client),
                    "src": str(hubspot_id),
                    "batch": str(batch_id),
                    "name": r["name"] or f"Wayward China brand {hubspot_id}",
                    "slug": f"wayward-china-{hubspot_id}",
                    "meta": (
                        '{"mirror_source":"wayward","mirror_kind":"lens-mirror",'
                        '"upstream_company_id":"' + str(hubspot_id) + '"}'
                    ),
                },
            ).first()
            if res and res.inserted_flag:
                inserted += 1
            else:
                updated += 1

    # Post-Pass-1 NULL backfill (Atlas C-2): set initial_intake_route='wayward'
    # for any PS cip_clients row that doesn't yet have a route. Never
    # overwrites a later route, never goes through the persister.
    with engine.begin() as c:
        c.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(ps_tenant)},
        )
        backfill_result = c.execute(
            text(
                "UPDATE cip_clients SET initial_intake_route='wayward', updated_at=NOW() "
                "WHERE tenant_id=:t AND initial_intake_route IS NULL"
            ),
            {"t": str(ps_tenant)},
        )
        backfilled = backfill_result.rowcount or 0

    counters["inserted"] = inserted
    counters["updated"] = updated
    counters["intake_route_backfilled"] = backfilled
    logger.info(
        "ps-mirror Pass 1: inserted=%d updated=%d intake_route_backfilled=%d",
        inserted, updated, backfilled,
    )
    return lookup, counters


# (source_lens, mapper_class, connector_id_suffix, entity_label_for_summary)
_PASS2_ENTITIES: list[tuple[str, type, str, str]] = [
    ("lens_china_clients", LensMirrorDealMapper, "deals", "deals"),
    ("lens_china_companies", LensMirrorCompanyMapper, "companies", "companies"),
    ("lens_china_contacts", LensMirrorContactMapper, "contacts", "contacts"),
]


def _pass2_mirror_entities(
    *,
    engine: Engine,
    ps_tenant: UUID,
    lookup: dict[str, UUID],
    database_url: str,
    dry_run: bool,
) -> dict[str, dict[str, Any]]:
    """For each entity, instantiate the right LensMirrorConnector + Mapper
    and drive ``run_sync``. Returns a per-entity summary dict.
    """
    per_entity: dict[str, dict[str, Any]] = {}

    for source_lens, mapper_cls, suffix, label in _PASS2_ENTITIES:
        if dry_run:
            per_entity[label] = {"status": "dry_run", "source_lens": source_lens}
            continue

        logger.info("ps-mirror Pass 2: mirroring %s -> cip_%s", source_lens, suffix)
        t0 = time.monotonic()
        connector = LensMirrorConnector(
            tenant_id=ps_tenant,
            source_tenant_id=ECOMLEVER_TENANT_ID,
            source_lens=source_lens,
            source_engine=engine,
            connector_id=f"lens-mirror-{suffix}-v1",
        )
        mapper = mapper_cls(client_id_lookup=lookup)
        state = run_sync(
            connector,
            mapper,
            engine,
            tenant_id=ps_tenant,
            sync_mode="lens-mirror",
            batch_size=500,
            database_url=database_url,
        )
        elapsed = time.monotonic() - t0
        per_entity[label] = {
            "status": state.status,
            "received": int(state.rows_received),
            "created": int(state.rows_created),
            "updated": int(state.rows_updated),
            "skipped_unchanged": int(state.rows_skipped_unchanged),
            "skipped_drift": int(state.rows_skipped_drift),
            "history": int(state.rows_history),
            "duration_sec": round(elapsed, 2),
        }
        logger.info(
            "ps-mirror %s: status=%s received=%d created=%d updated=%d "
            "skipped_unchanged=%d skipped_drift=%d history=%d (%.1fs)",
            label, state.status, state.rows_received, state.rows_created,
            state.rows_updated, state.rows_skipped_unchanged,
            state.rows_skipped_drift, state.rows_history, elapsed,
        )

    return per_entity


def run_ps_china_mirror(
    *,
    engine: Engine,
    ps_tenant_id: UUID,
    dry_run: bool = False,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Run the EcomLever → Project Silk china-subset LensMirror.

    Args:
      engine: SQLAlchemy Engine pointed at the shared CIP Postgres.
        Must use the ``postgresql+psycopg://`` dialect (psycopg v3).
      ps_tenant_id: UUIDv4 of the Project Silk tenant in ``tenants``.
      dry_run: If True, derive the Pass-1 lookup and skip all writes.
      database_url: Optional explicit URL passed to ``run_sync`` as the
        advisory-lock-holder URL. Required when the ``engine`` is built
        atop a non-default pool (e.g. NullPool from the scheduler wrapper).
        If omitted, ``run_sync`` derives the URL from the engine.

    Returns:
        dict with this shape (JSON-safe — no datetimes, no UUIDs):

        ```
        {
          "ps_tenant": "<uuid>",
          "dry_run": bool,
          "pass_1": {
            "source_china_companies": int,
            "inserted": int,
            "updated": int,
            "intake_route_backfilled": int,
          },
          "pass_2": {
            "deals":     {"status": str, "received": int, "created": int,
                          "updated": int, "skipped_unchanged": int,
                          "skipped_drift": int, "history": int,
                          "duration_sec": float},
            "companies": {...},
            "contacts":  {...},
          },
        }
        ```

    Precondition (caller-side): the PS tenant row must already exist + be
    active in the FAS-owned ``tenants`` table. This module does not
    verify that — see the DESIGN NOTE at the top of the file.
    """
    logger.info(
        "ps-mirror starting ps_tenant=%s dry_run=%s",
        ps_tenant_id, dry_run,
    )

    lookup, pass1 = _pass1_upsert_clients(
        engine, ps_tenant_id, dry_run=dry_run
    )

    if not lookup:
        logger.info("ps-mirror Pass 1 lookup empty; skipping Pass 2")
        return {
            "ps_tenant": str(ps_tenant_id),
            "dry_run": dry_run,
            "pass_1": pass1,
            "pass_2": {},
        }

    # If caller didn't supply an explicit database_url, derive it from the
    # engine. The run_sync orchestrator needs to build a NullPool lock
    # holder engine via this URL; the psycopg dialect must be preserved.
    if database_url is None:
        database_url = str(engine.url)

    pass2 = _pass2_mirror_entities(
        engine=engine,
        ps_tenant=ps_tenant_id,
        lookup=lookup,
        database_url=database_url,
        dry_run=dry_run,
    )

    return {
        "ps_tenant": str(ps_tenant_id),
        "dry_run": dry_run,
        "pass_1": pass1,
        "pass_2": pass2,
    }
