# foundry: kind=script domain=client-intelligence-platform
"""Seed Wayward HubSpot pipelines (auto via API) + owners (manual roster).

Per PM scope cb6750f0 (HubSpot Owners + Pipelines resolver).

Pipelines: fully automated via /crm/v3/pipelines/deals (works for
Wayward PAT — no scope restriction).

Owners: 403 on /crm/v3/owners for Wayward's PAT (crm.objects.owners.read
scope not granted). Manually seeded from observed owner_source_ids in
cip_engagements with Tim's roster knowledge. When/if Wayward grants the
owners scope, this script can pivot to API-mode by replacing the manual
roster with a /crm/v3/owners fetch.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_HUBSPOT_TOKEN=... \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/seed_wayward_hubspot_pipelines_and_owners.py
"""
from __future__ import annotations

import os
import re
import sys
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text

from cip.integration_mesh.wayward_constants import (
    ECOMLEVER_TENANT_ID,
    WAYWARD_CLIENT_ID,
)

HUBSPOT_BASE = "https://api.hubapi.com"
SOURCE_CONNECTOR = "hubspot-v1"

# Observed owner_source_id values in cip_engagements + cip_deals.
# Top owner 78132035 has 2,890 engagements. Wayward HubSpot PAT can't
# fetch /crm/v3/owners (403 — scope not granted), so this roster is
# seeded manually. When Tim confirms names/emails, this list should
# be updated and the script re-run (UPSERT pattern via ON CONFLICT).
#
# UNKNOWN entries are filled with "(unknown — operator review)" as
# the name; Tim updates the roster as names become known.
OWNER_ROSTER: list[dict] = [
    # Format: {source_id, name, email, role, archived}
    {"source_id": "78132035", "name": "(unknown — top engagement owner; ~2,890 events)", "email": None, "role": None, "archived": False},
    {"source_id": "159288855", "name": "(unknown — 2nd ~1,574 events)", "email": None, "role": None, "archived": False},
    {"source_id": "161617282", "name": "(unknown — 3rd ~849 events)", "email": None, "role": None, "archived": False},
    {"source_id": "158955471", "name": "(unknown — 4th ~39 events)", "email": None, "role": None, "archived": False},
    {"source_id": "164512990", "name": "(unknown — 5th ~6 events)", "email": None, "role": None, "archived": False},
]


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
    print(f"[seed] target={host} (prod={is_prod})")
    return None


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    err = _safety_gate(url)
    if err is not None:
        return err

    token = os.environ.get("WAYWARD_HUBSPOT_TOKEN", "")
    if not token:
        print("ERROR: WAYWARD_HUBSPOT_TOKEN not set", file=sys.stderr)
        return 2

    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)
    headers = {"Authorization": f"Bearer {token}"}

    # ── Pipelines (API mode) ─────────────────────────────────────────
    print("\n[seed] Fetching HubSpot deal pipelines...")
    r = httpx.get(f"{HUBSPOT_BASE}/crm/v3/pipelines/deals", headers=headers, timeout=30)
    r.raise_for_status()
    pipelines = r.json().get("results", [])
    print(f"[seed] Got {len(pipelines)} pipelines")

    batch_id = uuid4()
    stage_rows = []
    for p in pipelines:
        pid = p.get("id", "")
        plabel = p.get("label", "")
        archived = p.get("archived", False)
        for s in p.get("stages", []):
            stage_rows.append({
                "tenant_id": str(ECOMLEVER_TENANT_ID),
                "client_id": str(WAYWARD_CLIENT_ID),
                "source_connector": SOURCE_CONNECTOR,
                "pipeline_id": pid,
                "pipeline_label": plabel,
                "stage_id": s.get("id", ""),
                "stage_label": s.get("label", ""),
                "probability": float(s.get("metadata", {}).get("probability") or 0) or None,
                "display_order": s.get("displayOrder"),
                "archived": archived or s.get("archived", False),
            })
    print(f"[seed] Flattened to {len(stage_rows)} pipeline-stage rows")

    with engine.begin() as conn:
        conn.execute(text(f"SELECT set_config('app.current_tenant','{ECOMLEVER_TENANT_ID}',true)"))
        for r in stage_rows:
            conn.execute(
                text("""
                    INSERT INTO cip_pipeline_stages (
                        tenant_id, client_id, source_connector,
                        pipeline_id, pipeline_label,
                        stage_id, stage_label, probability,
                        display_order, archived
                    ) VALUES (
                        :tenant_id, :client_id, :source_connector,
                        :pipeline_id, :pipeline_label,
                        :stage_id, :stage_label, :probability,
                        :display_order, :archived
                    )
                    ON CONFLICT (tenant_id, source_connector, pipeline_id, stage_id)
                    DO UPDATE SET
                        pipeline_label = EXCLUDED.pipeline_label,
                        stage_label = EXCLUDED.stage_label,
                        probability = EXCLUDED.probability,
                        display_order = EXCLUDED.display_order,
                        archived = EXCLUDED.archived,
                        updated_at = now()
                """),
                r,
            )
    print(f"[seed] UPSERTed {len(stage_rows)} pipeline_stage rows")

    # ── Owners (manual roster mode) ──────────────────────────────────
    print("\n[seed] Seeding HubSpot owners from manual roster...")
    print("[seed] NOTE: HubSpot PAT returns 403 on /crm/v3/owners.")
    print("[seed] Edit the OWNER_ROSTER constant when names become known.")

    with engine.begin() as conn:
        conn.execute(text(f"SELECT set_config('app.current_tenant','{ECOMLEVER_TENANT_ID}',true)"))
        for o in OWNER_ROSTER:
            conn.execute(
                text("""
                    INSERT INTO cip_owners (
                        tenant_id, client_id, source_connector, source_id,
                        name, email, role, archived, populated_by
                    ) VALUES (
                        :tenant_id, :client_id, :source_connector, :source_id,
                        :name, :email, :role, :archived, 'manual'
                    )
                    ON CONFLICT (tenant_id, source_connector, source_id)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        email = EXCLUDED.email,
                        role = EXCLUDED.role,
                        archived = EXCLUDED.archived,
                        updated_at = now()
                """),
                {
                    "tenant_id": str(ECOMLEVER_TENANT_ID),
                    "client_id": str(WAYWARD_CLIENT_ID),
                    "source_connector": SOURCE_CONNECTOR,
                    **o,
                },
            )
    print(f"[seed] UPSERTed {len(OWNER_ROSTER)} owner rows")

    # ── Verify ───────────────────────────────────────────────────────
    print("\n[seed] Verification:")
    with engine.connect() as conn:
        conn.execute(text(f"SELECT set_config('app.current_tenant','{ECOMLEVER_TENANT_ID}',true)"))
        n_pipelines = conn.execute(text("SELECT COUNT(DISTINCT pipeline_id) FROM cip_pipeline_stages")).scalar()
        n_stages = conn.execute(text("SELECT COUNT(*) FROM cip_pipeline_stages")).scalar()
        n_owners = conn.execute(text("SELECT COUNT(*) FROM cip_owners")).scalar()
        print(f"  cip_pipeline_stages: {n_pipelines} pipelines, {n_stages} stages")
        print(f"  cip_owners: {n_owners} rows")

        # Quick lens sanity check
        n_resolved = conn.execute(text("""
            SELECT COUNT(*) FROM lens_engagements_with_owners
            WHERE owner_name IS NOT NULL
        """)).scalar()
        n_unresolved = conn.execute(text("""
            SELECT COUNT(*) FROM lens_engagements_with_owners
            WHERE owner_source_id IS NOT NULL AND owner_name IS NULL
        """)).scalar()
        print(f"  lens_engagements_with_owners: {n_resolved} resolved, {n_unresolved} unresolved")

        n_deals_resolved = conn.execute(text("""
            SELECT COUNT(*) FROM lens_deals_with_stage_labels
            WHERE stage_label IS NOT NULL
        """)).scalar()
        n_deals_unresolved = conn.execute(text("""
            SELECT COUNT(*) FROM lens_deals_with_stage_labels
            WHERE stage_id IS NOT NULL AND stage_label IS NULL
        """)).scalar()
        print(f"  lens_deals_with_stage_labels: {n_deals_resolved} resolved, {n_deals_unresolved} unresolved")

    print("\n[seed] DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
