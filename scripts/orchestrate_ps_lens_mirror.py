# foundry: kind=script domain=client-intelligence-platform
"""Two-pass Project Silk lens-mirror orchestrator (Phase 2.6).

Per Atlas-locked design (docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md
C-1 / C-2) for PM scope 280a2f20.

PASS 1 — derive PS cip_clients
  Read `lens_china_companies` under EcomLever GUC. For each company,
  upsert one cip_clients row in PS tenant. PS client_id is
  `uuid5(PS_TENANT_NS, hubspot_company_id)` — deterministic so
  re-running this script yields the same client_ids, and the lookup
  table for Pass 2 can be rebuilt by re-reading the lens.
  After upserts: backfill `initial_intake_route='wayward'` for any
  PS cip_clients row whose route is NULL (insert-only semantics — Atlas C-2).

PASS 2 — mirror entities (deals, companies, contacts)
  For each entity, instantiate `LensMirrorConnector` + the per-entity
  `LensMirrorMapper` and call `run_sync(..., sync_mode='lens-mirror')`.
  The orchestrator's existing pipeline handles the writes; the mapper's
  `client_id_lookup` resolves each row's PS client_id.

  Skipped entities (Atlas Q5 ruling):
  - tickets — cross-connector identity resolution (Zendesk requester
    ↔ HubSpot contact by email) needed; out of 2.6 scope.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        PS_TENANT_ID=<uuidv4> \\
        python scripts/orchestrate_ps_lens_mirror.py [--dry-run]

The PS_TENANT_ID is REQUIRED — there is no default. Provisioning the PS
tenant is a separate one-shot (see scope 240); this script assumes the
PS tenants row exists in `tenants` table before running.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from cip.integration_mesh.connectors.lens_mirror import (
    LensMirrorCompanyMapper,
    LensMirrorConnector,
    LensMirrorContactMapper,
    LensMirrorDealMapper,
)
from cip.integration_mesh.orchestrator import run_sync

# Canonical UUIDs locked per PM decision c575c81c (see cip_18).
ECOMLEVER_TENANT_ID: UUID = UUID("dec814db-722a-4730-8e60-51afc4a5dad9")
WAYWARD_CLIENT_ID: UUID = UUID("661ecab4-dddb-5924-a34d-af1c5133132d")


def _safety_gate(url: str) -> int | None:
    m = re.search(r"@([^/:?]+)", url)
    host = m.group(1) if m else "<unknown>"
    is_prod = bool(re.search(r"\.rlwy\.net|\.railway\.app", host))
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if not is_local:
        expected = "YES_I_KNOW_THIS_IS_PROD" if is_prod else "YES_I_KNOW_THIS_IS_REMOTE"
        if os.environ.get("SEED_CONFIRM") != expected:
            print(f"ABORTED: re-run with SEED_CONFIRM={expected}", file=sys.stderr)
            return 3
    print(f"[ps-mirror] target={host} (prod={is_prod})")
    return None


def _resolve_ps_tenant_id() -> UUID:
    raw = os.environ.get("PS_TENANT_ID", "").strip()
    if not raw:
        print(
            "ERROR: PS_TENANT_ID env var required. Provision the Project Silk "
            "tenant first (scope 240) and pass its UUIDv4 here.",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        return UUID(raw)
    except ValueError:
        print(f"ERROR: PS_TENANT_ID='{raw}' is not a valid UUID", file=sys.stderr)
        sys.exit(2)


def _verify_ps_tenant_exists(engine: Engine, ps_tenant: UUID) -> None:
    with engine.begin() as c:
        row = c.execute(
            text("SELECT name, type, status FROM tenants WHERE tenant_id = :t"),
            {"t": str(ps_tenant)},
        ).first()
        if not row:
            print(
                f"ERROR: PS_TENANT_ID={ps_tenant} not found in `tenants`. "
                "Provision it first (scope 240).",
                file=sys.stderr,
            )
            sys.exit(2)
        if row.status != "active":
            print(
                f"ERROR: PS tenant exists but status={row.status!r}. Activate first.",
                file=sys.stderr,
            )
            sys.exit(2)
        print(
            f"[ps-mirror] PS tenant verified: {row.name} (type={row.type})"
        )


def _pass1_upsert_clients(
    engine: Engine, ps_tenant: UUID, dry_run: bool
) -> dict[str, UUID]:
    """Read source china companies, derive deterministic PS client_ids,
    upsert into cip_clients (PS tenant). Returns the lookup dict.
    """
    print("[ps-mirror] PASS 1 — derive PS cip_clients from lens_china_companies")
    lookup: dict[str, UUID] = {}
    batch_id = uuid4()

    with engine.begin() as c:
        # Read lens under EcomLever GUC
        c.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(ECOMLEVER_TENANT_ID)},
        )
        rows = c.execute(
            text("SELECT source_id, name FROM lens_china_companies")
        ).mappings().all()

    print(f"  source china companies: {len(rows)}")
    if not rows:
        print("  nothing to mirror; abort Pass 1")
        return lookup

    # Build the lookup deterministically — no DB needed.
    for r in rows:
        hubspot_id = r["source_id"]
        if not hubspot_id:
            continue
        ps_client = uuid5(ps_tenant, f"wayward-china:{hubspot_id}")
        lookup[str(hubspot_id)] = ps_client

    if dry_run:
        print(f"  DRY-RUN: would upsert {len(lookup)} cip_clients rows")
        return lookup

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
        r = c.execute(
            text(
                "UPDATE cip_clients SET initial_intake_route='wayward', updated_at=NOW() "
                "WHERE tenant_id=:t AND initial_intake_route IS NULL"
            ),
            {"t": str(ps_tenant)},
        )
        backfilled = r.rowcount

    print(
        f"  upserts: inserted={inserted} updated={updated} "
        f"intake_route backfilled={backfilled}"
    )
    return lookup


def _pass2_mirror_entities(
    *,
    engine: Engine,
    ps_tenant: UUID,
    lookup: dict[str, UUID],
    database_url: str,
    dry_run: bool,
) -> None:
    """For each entity (deals, companies, contacts), instantiate the
    appropriate LensMirrorConnector + Mapper and drive `run_sync`.
    """
    print("[ps-mirror] PASS 2 — mirror entities (deals + companies + contacts)")

    # Each (source_lens, mapper_class, connector_id_suffix).
    entity_runs: list[tuple[str, type, str]] = [
        ("lens_china_clients", LensMirrorDealMapper, "deals"),
        ("lens_china_companies", LensMirrorCompanyMapper, "companies"),
        ("lens_china_contacts", LensMirrorContactMapper, "contacts"),
    ]

    for source_lens, mapper_cls, suffix in entity_runs:
        if dry_run:
            print(f"  DRY-RUN: skipping run_sync for {source_lens} -> {suffix}")
            continue
        print(f"  --- mirroring {source_lens} -> cip_{suffix} ---")
        t0 = time.monotonic()
        connector = LensMirrorConnector(
            tenant_id=ps_tenant,
            source_tenant_id=ECOMLEVER_TENANT_ID,
            source_lens=source_lens,
            source_engine=engine,  # same DB for source + dest in Stage 1
            connector_id=f"lens-mirror-{suffix}-v1",
        )
        mapper = mapper_cls(client_id_lookup=lookup)
        try:
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
            print(
                f"    DONE in {elapsed:.1f}s: status={state.status} "
                f"received={state.rows_received} "
                f"created={state.rows_created} updated={state.rows_updated} "
                f"skipped_unchanged={state.rows_skipped_unchanged} "
                f"skipped_drift={state.rows_skipped_drift} "
                f"history={state.rows_history}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"    ERROR {source_lens}: {type(e).__name__}: {e}", file=sys.stderr)
            raise


def main() -> int:
    print(
        f"RUN_BEGAN tag=orchestrate_ps_lens_mirror at="
        f"{datetime.now(UTC).isoformat()}"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Build the Pass 1 lookup + describe Pass 2 without writing.",
    )
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    err = _safety_gate(url)
    if err is not None:
        return err

    ps_tenant = _resolve_ps_tenant_id()
    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)

    _verify_ps_tenant_exists(engine, ps_tenant)

    lookup = _pass1_upsert_clients(engine, ps_tenant, dry_run=args.dry_run)
    if not lookup:
        print("[ps-mirror] lookup is empty — no PS clients to mirror against.")
        print(
            f"RUN_ENDED tag=orchestrate_ps_lens_mirror at="
            f"{datetime.now(UTC).isoformat()}"
        )
        return 0

    # run_sync's _make_lock_holder_engine creates a fresh engine from
    # database_url. If we pass the raw postgresql:// URL, SQLAlchemy
    # defaults to the psycopg2 driver — which isn't installed in the
    # foundry-cip venv (we use psycopg v3). Force the v3 driver by
    # passing the postgresql+psycopg:// form.
    psycopg_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    _pass2_mirror_entities(
        engine=engine,
        ps_tenant=ps_tenant,
        lookup=lookup,
        database_url=psycopg_url,
        dry_run=args.dry_run,
    )

    print(
        f"RUN_ENDED tag=orchestrate_ps_lens_mirror at="
        f"{datetime.now(UTC).isoformat()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
