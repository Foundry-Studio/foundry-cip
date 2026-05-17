# foundry: kind=script domain=client-intelligence-platform
"""Detect property-catalog drift between live vendor schema + registry.

Per PM scope 6e7f08bb (Schema drift detector, Tier 2).

For each (connector, entity) pair currently in
cip_connector_property_registry:
  - Pull the vendor's live property catalog
  - Diff against the registry
  - Emit a drift report covering:
    * NEW (vendor has, registry doesn't) -- should be auto-added with
      confidence='tentative'; flagged for operator review
    * REMOVED (registry has, vendor doesn't) -- should be marked archived
    * TYPE_CHANGED (data_type mismatch) -- demotes confidence to
      'inferred' until re-verified
    * LABEL_DRIFT (label changed in vendor) -- informational; refresh
      registry to reflect new label

Output: markdown report at evidence/drift-<timestamp>.md AND
optional auto-apply mode to update the registry.

Per the PROPERTY-GLOSSARY-PATTERN.md doc: this is the
"schema drift detector" referenced as the thing that auto-demotes
confidence when source-system schema changes.

Usage (report-only):

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_HUBSPOT_TOKEN=... \\
        WAYWARD_ZENDESK_TOKEN=... \\
        WAYWARD_ZENDESK_SUBDOMAIN=waywardsupport \\
        WAYWARD_ZENDESK_USER=jake@wayward.com \\
        python scripts/detect_property_drift.py

With --apply to auto-update the registry (idempotent; only inserts
NEW + updates TYPE_CHANGED/LABEL_DRIFT; never deletes):

    python scripts/detect_property_drift.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

from cip.integration_mesh.wayward_constants import ECOMLEVER_TENANT_ID

T = str(ECOMLEVER_TENANT_ID)

# Map (connector, entity) -> (vendor properties endpoint, type field)
_HUBSPOT_BASE = "https://api.hubapi.com"
HUBSPOT_ENTITIES = [
    ("companies", "company"),
    ("contacts", "contact"),
    ("deals", "deal"),
    ("tickets", "ticket"),
    ("notes", "engagement_note"),
    ("meetings", "engagement_meeting"),
    ("tasks", "engagement_task"),
]
ZENDESK_ENTITIES = [
    ("ticket_fields", "ticket"),  # Zendesk's custom ticket fields
    ("organization_fields", "company"),
    ("user_fields", "contact"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Update registry in place")
    parser.add_argument("--report-path", default=None)
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)

    findings_by_entity: dict[tuple[str, str], dict[str, list]] = defaultdict(
        lambda: {"new": [], "removed": [], "type_changed": [], "label_drift": []}
    )

    # ── HubSpot drift ────────────────────────────────────────────────
    token = os.environ.get("WAYWARD_HUBSPOT_TOKEN", "")
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        for endpoint, entity in HUBSPOT_ENTITIES:
            print(f"[drift] HubSpot/{endpoint} -> object_type={entity}")
            try:
                r = httpx.get(
                    f"{_HUBSPOT_BASE}/crm/v3/properties/{endpoint}",
                    headers=headers, timeout=30,
                )
                if r.status_code == 403:
                    print(f"  skip (403): no scope for {endpoint}")
                    continue
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001
                print(f"  error: {type(e).__name__}: {str(e)[:120]}")
                continue
            vendor = {
                p["name"]: p for p in r.json().get("results", [])
                if isinstance(p, dict) and p.get("name") and not p.get("calculated")
            }
            registry = _registry_props_for(engine, "hubspot-v1", entity)
            _diff_into(findings_by_entity[("hubspot-v1", entity)], vendor, registry)

    # ── Zendesk drift (custom fields only -- system fields are stable) ─
    z_token = os.environ.get("WAYWARD_ZENDESK_TOKEN", "")
    z_subdomain = os.environ.get("WAYWARD_ZENDESK_SUBDOMAIN", "")
    z_user = os.environ.get("WAYWARD_ZENDESK_USER", "")
    if z_token and z_subdomain and z_user:
        import base64
        auth = base64.b64encode(f"{z_user}/token:{z_token}".encode()).decode()
        z_base = f"https://{z_subdomain}.zendesk.com"
        z_headers = {"Authorization": f"Basic {auth}"}
        for endpoint, entity in ZENDESK_ENTITIES:
            print(f"[drift] Zendesk/{endpoint} -> object_type={entity}")
            try:
                r = httpx.get(
                    f"{z_base}/api/v2/{endpoint}.json",
                    headers=z_headers, timeout=30,
                )
                if r.status_code in (401, 403, 404):
                    print(f"  skip ({r.status_code}): no scope")
                    continue
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001
                print(f"  error: {type(e).__name__}: {str(e)[:120]}")
                continue
            # ticket_fields uses 'ticket_fields' as the key; org/user use 'organization_fields'/'user_fields'
            list_key = endpoint
            vendor_list = r.json().get(list_key, [])
            # Zendesk fields don't have a `calculated` flag; use 'key' as the property name
            vendor = {
                p.get("key") or p.get("id") and f"field_{p['id']}": p
                for p in vendor_list
                if isinstance(p, dict)
            }
            vendor = {k: v for k, v in vendor.items() if k}
            registry = _registry_props_for(engine, "zendesk-v1", entity)
            _diff_into(findings_by_entity[("zendesk-v1", entity)], vendor, registry)

    # ── Render report ────────────────────────────────────────────────
    report = _render_report(findings_by_entity)
    report_path = Path(args.report_path) if args.report_path else (
        Path("evidence") / f"drift-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"\n[drift] Wrote report: {report_path}")
    print(f"  total NEW:          {sum(len(f['new']) for f in findings_by_entity.values())}")
    print(f"  total REMOVED:      {sum(len(f['removed']) for f in findings_by_entity.values())}")
    print(f"  total TYPE_CHANGED: {sum(len(f['type_changed']) for f in findings_by_entity.values())}")
    print(f"  total LABEL_DRIFT:  {sum(len(f['label_drift']) for f in findings_by_entity.values())}")

    if args.apply:
        print("\n[drift] --apply: updating registry...")
        n_inserted, n_updated = _apply_drift(engine, findings_by_entity)
        print(f"  INSERTed (NEW as 'tentative'): {n_inserted}")
        print(f"  UPDATEd (label/type drift): {n_updated}")
    else:
        print("\n[drift] (report-only -- re-run with --apply to update the registry)")
    return 0


def _registry_props_for(engine, connector: str, object_type: str) -> dict:
    """Fetch current registry rows for (connector, entity)."""
    with engine.connect() as conn:
        conn.execute(text(f"SELECT set_config('app.current_tenant','{T}',true)"))
        rows = conn.execute(
            text(
                "SELECT property_name, label, group_name, property_type, "
                "       confidence, plain_english_meaning "
                "FROM cip_connector_property_registry "
                "WHERE tenant_id = :t AND connector = :c AND object_type = :o"
            ),
            {"t": T, "c": connector, "o": object_type},
        ).mappings().all()
    return {r["property_name"]: dict(r) for r in rows}


def _diff_into(bucket: dict, vendor: dict, registry: dict) -> None:
    vendor_names = set(vendor.keys())
    registry_names = set(registry.keys())
    # NEW = vendor has, registry doesn't
    for name in sorted(vendor_names - registry_names):
        p = vendor[name]
        bucket["new"].append({
            "name": name, "label": p.get("label") or p.get("title"),
            "vendor_type": p.get("type") or p.get("dataType"),
            "group_name": p.get("groupName"),
        })
    # REMOVED = registry has, vendor doesn't
    for name in sorted(registry_names - vendor_names):
        bucket["removed"].append({
            "name": name, "confidence": registry[name]["confidence"],
            "label": registry[name].get("label"),
        })
    # In both -- check type + label
    for name in sorted(vendor_names & registry_names):
        v = vendor[name]
        r = registry[name]
        v_type = v.get("type") or v.get("dataType")
        v_label = v.get("label") or v.get("title")
        if v_type and r["property_type"] and v_type != r["property_type"]:
            bucket["type_changed"].append({
                "name": name,
                "registry_type": r["property_type"], "vendor_type": v_type,
                "confidence": r["confidence"],
            })
        if v_label and r.get("label") and v_label != r["label"]:
            bucket["label_drift"].append({
                "name": name,
                "registry_label": r.get("label"), "vendor_label": v_label,
            })


def _render_report(findings_by_entity: dict) -> str:
    lines: list[str] = []
    lines.append(f"# Property catalog drift report\n")
    lines.append(f"_Generated: {datetime.now(timezone.utc).isoformat()}_\n")
    lines.append(f"Tenant: `{T}` (EcomLever / Wayward)\n")
    lines.append("\n## Summary\n")
    lines.append("| Connector | Entity | NEW | REMOVED | TYPE_CHANGED | LABEL_DRIFT |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for (connector, entity), buckets in sorted(findings_by_entity.items()):
        lines.append(
            f"| `{connector}` | `{entity}` "
            f"| {len(buckets['new'])} | {len(buckets['removed'])} "
            f"| {len(buckets['type_changed'])} | {len(buckets['label_drift'])} |"
        )
    lines.append("")
    for (connector, entity), buckets in sorted(findings_by_entity.items()):
        if not any(buckets.values()):
            continue
        lines.append(f"\n## `{connector}` / `{entity}`\n")
        if buckets["new"]:
            lines.append("### NEW (vendor has, registry doesn't)\n")
            lines.append("Recommend: auto-add to registry with `confidence='tentative'`; operator review.\n")
            lines.append("| Name | Vendor label | Vendor type | Group |")
            lines.append("|---|---|---|---|")
            for p in buckets["new"][:50]:
                lines.append(f"| `{p['name']}` | {p.get('label') or '--'} | {p.get('vendor_type') or '--'} | {p.get('group_name') or '--'} |")
            if len(buckets["new"]) > 50:
                lines.append(f"\n_...and {len(buckets['new']) - 50} more_\n")
        if buckets["removed"]:
            lines.append("\n### REMOVED (registry has, vendor doesn't)\n")
            lines.append("Recommend: mark archived in registry (do not delete history).\n")
            lines.append("| Name | Registry confidence | Registry label |")
            lines.append("|---|---|---|")
            for p in buckets["removed"][:50]:
                lines.append(f"| `{p['name']}` | `{p['confidence']}` | {p.get('label') or '--'} |")
        if buckets["type_changed"]:
            lines.append("\n### TYPE_CHANGED\n")
            lines.append("Recommend: demote confidence to `inferred` until re-verified.\n")
            lines.append("| Name | Registry type | Vendor type | Confidence |")
            lines.append("|---|---|---|---|")
            for p in buckets["type_changed"]:
                lines.append(
                    f"| `{p['name']}` | `{p['registry_type']}` | `{p['vendor_type']}` "
                    f"| `{p['confidence']}` |"
                )
        if buckets["label_drift"]:
            lines.append("\n### LABEL_DRIFT\n")
            lines.append("Recommend: refresh registry label (informational; meaning unlikely to have changed).\n")
            lines.append("| Name | Registry label | Vendor label |")
            lines.append("|---|---|---|")
            for p in buckets["label_drift"][:50]:
                lines.append(f"| `{p['name']}` | {p['registry_label']} | {p['vendor_label']} |")
    return "\n".join(lines) + "\n"


def _apply_drift(engine, findings_by_entity: dict) -> tuple[int, int]:
    inserted = 0
    updated = 0
    with engine.begin() as conn:
        conn.execute(text(f"SELECT set_config('app.current_tenant','{T}',true)"))
        for (connector, entity), buckets in findings_by_entity.items():
            # NEW -> INSERT with 'tentative'
            for p in buckets["new"]:
                conn.execute(
                    text("""
                        INSERT INTO cip_connector_property_registry (
                            tenant_id, connector, object_type, property_name,
                            property_type, storage_location, cip_table,
                            label, group_name, confidence
                        ) VALUES (
                            :t, :c, :o, :n, :pt, 'overflow', :ct, :l, :g, 'tentative'
                        )
                        ON CONFLICT (tenant_id, connector, object_type, property_name)
                        DO NOTHING
                    """),
                    {
                        "t": T, "c": connector, "o": entity, "n": p["name"],
                        "pt": p.get("vendor_type") or "string",
                        "ct": _ct_for(entity),
                        "l": p.get("label"), "g": p.get("group_name"),
                    },
                )
                inserted += 1
            # LABEL_DRIFT -> update label
            for p in buckets["label_drift"]:
                r = conn.execute(
                    text(
                        "UPDATE cip_connector_property_registry "
                        "SET label = :l, last_synced_schema_at = now() "
                        "WHERE tenant_id = :t AND connector = :c "
                        "  AND object_type = :o AND property_name = :n"
                    ),
                    {"l": p["vendor_label"], "t": T, "c": connector, "o": entity, "n": p["name"]},
                )
                updated += r.rowcount or 0
            # TYPE_CHANGED -> demote confidence + update type
            for p in buckets["type_changed"]:
                r = conn.execute(
                    text(
                        "UPDATE cip_connector_property_registry "
                        "SET property_type = :pt, confidence = "
                        "    CASE WHEN confidence = 'verified' THEN 'inferred' ELSE confidence END, "
                        "    last_synced_schema_at = now() "
                        "WHERE tenant_id = :t AND connector = :c "
                        "  AND object_type = :o AND property_name = :n"
                    ),
                    {"pt": p["vendor_type"], "t": T, "c": connector, "o": entity, "n": p["name"]},
                )
                updated += r.rowcount or 0
    return inserted, updated


def _ct_for(entity: str) -> str:
    return {
        "company": "cip_companies", "contact": "cip_contacts",
        "deal": "cip_deals", "ticket": "cip_tickets",
        "engagement_note": "cip_engagements",
        "engagement_meeting": "cip_engagements",
        "engagement_task": "cip_engagements",
    }.get(entity, "cip_companies")


if __name__ == "__main__":
    sys.exit(main())
