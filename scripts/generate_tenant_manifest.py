# foundry: kind=script domain=client-intelligence-platform
"""Generate `docs/tenants/<uuid>/MANIFEST.md` from the tenant manifest views.

Per PM scope `bfc3d5d0`: auto-generated human-readable summary of
what's in CIP for a tenant. Reads `lens_tenant_manifest_properties`
+ `lens_tenant_manifest_sync_health` + a few direct row-count
queries, writes a markdown file in the tenant's docs folder.

v1: invoked manually. v1.5 (separate scope): post-sync hook auto-runs
after every connector run.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        python -u scripts/generate_tenant_manifest.py <tenant_uuid>
    # Default tenant = EcomLever
    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        python -u scripts/generate_tenant_manifest.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, text

DEFAULT_TENANT = "dec814db-722a-4730-8e60-51afc4a5dad9"  # EcomLever


def _connect() -> object:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)
    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    return create_engine(sa_url, pool_pre_ping=True)


def main() -> int:
    tenant_uuid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TENANT
    repo_root = Path(__file__).parent.parent
    out_dir = repo_root / "docs" / "tenants" / tenant_uuid
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "MANIFEST.md"

    engine = _connect()

    lines: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append("---")
    lines.append("kind: doc")
    lines.append("domain: client-intelligence-platform")
    lines.append(f"tenant_uuid: {tenant_uuid}")
    lines.append("status: auto-generated")
    lines.append(f"last_updated: {now}")
    lines.append(
        "generator: scripts/generate_tenant_manifest.py "
        "(PM scope bfc3d5d0 — Tenant Manifest)"
    )
    lines.append("---")
    lines.append("")
    lines.append(f"# Tenant Manifest — `{tenant_uuid}`")
    lines.append("")
    lines.append(
        f"Auto-generated {now}. **Do not edit by hand** — re-run "
        "`scripts/generate_tenant_manifest.py <tenant_uuid>` after data "
        "changes. The editable source-of-truth for property descriptions is "
        f"`docs/tenants/{tenant_uuid}/GLOSSARY.md`, which "
        "`scripts/seed_glossary_into_registry.py` materializes into the "
        "registry table that this MANIFEST queries."
    )
    lines.append("")

    with engine.connect() as c:
        c.execute(text(f"SELECT set_config('app.current_tenant','{tenant_uuid}',true)"))

        # ── Tenant identity ──────────────────────────────────────────────
        tenant_row = c.execute(
            text(
                "SELECT name, type, status, parent_tenant_id, created_at "
                "FROM tenants WHERE tenant_id = :t"
            ),
            {"t": tenant_uuid},
        ).first()
        if tenant_row:
            lines.append("## Tenant identity")
            lines.append("")
            lines.append(f"- **Name:** {tenant_row[0]}")
            lines.append(f"- **Type:** {tenant_row[1]}")
            lines.append(f"- **Status:** {tenant_row[2]}")
            lines.append(f"- **Parent tenant:** {tenant_row[3] or '(none)'}")
            lines.append(f"- **Created:** {tenant_row[4]}")
            lines.append("")

        # ── Clients ──────────────────────────────────────────────────────
        client_rows = c.execute(
            text(
                "SELECT client_id, name, slug, industry "
                "FROM cip_clients WHERE tenant_id = :t ORDER BY name"
            ),
            {"t": tenant_uuid},
        ).all()
        lines.append(f"## Clients ({len(client_rows)})")
        lines.append("")
        if client_rows:
            lines.append("| Client name | Slug | client_id | Industry |")
            lines.append("|---|---|---|---|")
            for r in client_rows:
                lines.append(f"| {r[1]} | `{r[2]}` | `{r[0]}` | {r[3] or '—'} |")
        else:
            lines.append("*(no clients seeded yet — tenant data may live without a client_id scope)*")
        lines.append("")

        # ── Table row counts ─────────────────────────────────────────────
        lines.append("## Tables populated")
        lines.append("")
        lines.append("| Table | Rows | Per-client breakdown |")
        lines.append("|---|---|---|")
        for tbl in (
            "cip_companies", "cip_contacts", "cip_deals", "cip_tickets",
            "cip_files", "cip_companies_history", "cip_contacts_history",
            "cip_deals_history", "cip_tickets_history",
        ):
            try:
                n = c.execute(
                    text(f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = :t"),
                    {"t": tenant_uuid},
                ).scalar()
                # Check if table has client_id
                has_cid = c.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = :t AND column_name = 'client_id'"
                    ),
                    {"t": tbl},
                ).first()
                breakdown = ""
                if has_cid:
                    bd_rows = c.execute(
                        text(
                            f"SELECT client_id, COUNT(*) FROM {tbl} "
                            f"WHERE tenant_id = :t GROUP BY 1 ORDER BY 2 DESC"
                        ),
                        {"t": tenant_uuid},
                    ).all()
                    parts = []
                    for bd in bd_rows:
                        cid = str(bd[0])[:8] if bd[0] else "NULL"
                        parts.append(f"{cid}={bd[1]:,}")
                    breakdown = ", ".join(parts)
                lines.append(f"| `{tbl}` | {n:,} | {breakdown or '—'} |")
            except Exception as e:  # noqa: BLE001
                lines.append(f"| `{tbl}` | ERR | {e.__class__.__name__} |")
        lines.append("")

        # ── Connector sync health ────────────────────────────────────────
        lines.append("## Connector sync health")
        lines.append("")
        sync_rows = c.execute(
            text(
                "SELECT connector_id, sync_mode, last_success_at, "
                "       last_attempt_at, total_runs, freshness "
                "FROM lens_tenant_manifest_sync_health "
                "ORDER BY connector_id, sync_mode"
            )
        ).all()
        if sync_rows:
            lines.append("| Connector | Mode | Last success | Total runs | Freshness |")
            lines.append("|---|---|---|---|---|")
            for r in sync_rows:
                last_success = str(r[2])[:19] if r[2] else "never"
                freshness_emoji = {
                    "fresh": "✓ fresh",
                    "stale_gt_24h": "⚠ stale (>24h)",
                    "stale_gt_7d": "✗ stale (>7d)",
                    "never_succeeded": "✗ never succeeded",
                }.get(r[5], r[5])
                lines.append(f"| `{r[0]}` | {r[1]} | {last_success} | {r[4]} | {freshness_emoji} |")
        else:
            lines.append("*(no sync runs yet)*")
        lines.append("")

        # ── Property catalog (one section per object_type) ───────────────
        lines.append("## Property catalog")
        lines.append("")
        lines.append(
            "Per-property meaning + confidence level. `verified` = "
            "human-confirmed; `inferred` = AI inferred from values + name; "
            "`tentative` = auto-baseline only; `unknown` = exists but no "
            "meaning yet. See [`PROPERTY-GLOSSARY-PATTERN.md`]"
            "(../../PROPERTY-GLOSSARY-PATTERN.md)."
        )
        lines.append("")
        prop_rows = c.execute(
            text(
                "SELECT connector, object_type, property_name, label, "
                "       confidence, plain_english_meaning, watch_out_for, "
                "       aliases, is_custom, storage_location "
                "FROM lens_tenant_manifest_properties "
                "ORDER BY object_type, "
                "  CASE confidence WHEN 'verified' THEN 0 WHEN 'inferred' "
                "       THEN 1 WHEN 'tentative' THEN 2 ELSE 3 END, "
                "  property_name"
            )
        ).all()

        # Group by (object_type)
        from collections import defaultdict
        by_obj: dict[str, list] = defaultdict(list)
        for r in prop_rows:
            by_obj[r[1]].append(r)

        for object_type in sorted(by_obj.keys()):
            lines.append(f"### Object type: `{object_type}`")
            lines.append("")
            confidence_counts = defaultdict(int)
            for r in by_obj[object_type]:
                confidence_counts[r[4]] += 1
            cc_parts = [f"{k}={v}" for k, v in sorted(confidence_counts.items())]
            lines.append(f"_Properties tracked: **{len(by_obj[object_type])}** ({', '.join(cc_parts)})_")
            lines.append("")
            lines.append("| Property | Confidence | Custom? | Storage | Meaning / Aliases / Watch out for |")
            lines.append("|---|---|---|---|---|")
            for r in by_obj[object_type]:
                prop = f"`{r[2]}`"
                if r[3]:
                    prop += f" ({r[3]})"
                conf = r[4]
                custom = "✓" if r[8] else ""
                storage = r[9]
                cell = ""
                if r[5]:
                    cell = r[5]
                if r[7]:
                    aliases = ", ".join(r[7])
                    cell = f"{cell}<br/>**Aliases:** {aliases}" if cell else f"**Aliases:** {aliases}"
                if r[6]:
                    cell = f"{cell}<br/>**Watch out:** {r[6]}" if cell else f"**Watch out:** {r[6]}"
                if not cell:
                    cell = "_(no description yet — confidence is `tentative`; populate via `docs/tenants/<uuid>/GLOSSARY.md` + re-run seeding)_"
                lines.append(f"| {prop} | `{conf}` | {custom} | {storage} | {cell} |")
            lines.append("")

        # ── Lenses defined ───────────────────────────────────────────────
        lines.append("## Lenses defined")
        lines.append("")
        try:
            lens_rows = c.execute(
                text(
                    "SELECT name, slug, source_connector, properties "
                    "FROM cip_views WHERE tenant_id = :t ORDER BY name"
                ),
                {"t": tenant_uuid},
            ).all()
            if lens_rows:
                lines.append("| Lens | Slug | Source |")
                lines.append("|---|---|---|")
                for r in lens_rows:
                    lines.append(f"| {r[0]} | `{r[1]}` | {r[2]} |")
            else:
                lines.append(
                    "*(no lens views defined yet — when Phase 2 ships the "
                    "Wayward-specific lenses like `lens_china_clients`, "
                    "`lens_tim_attributed_deals`, they appear here.)*"
                )
        except Exception as e:  # noqa: BLE001
            lines.append(f"*(error querying lenses: {e.__class__.__name__})*")
        lines.append("")

        # ── Cross-references ─────────────────────────────────────────────
        lines.append("## Cross-references")
        lines.append("")
        lines.append(f"- [`docs/tenants/{tenant_uuid}/GLOSSARY.md`](GLOSSARY.md) — editable source-of-truth for property meanings (per PM scope `0246851d`)")
        lines.append("- [`docs/PROPERTY-GLOSSARY-PATTERN.md`](../../PROPERTY-GLOSSARY-PATTERN.md) — the glossary pattern explained")
        lines.append("- [`docs/ONBOARDING-A-NEW-TENANT.md`](../../ONBOARDING-A-NEW-TENANT.md) — runbook for adding new tenants")
        lines.append("- [`docs/HUBSPOT-CONNECTOR-GUIDE.md`](../../HUBSPOT-CONNECTOR-GUIDE.md) + [`docs/ZENDESK-CONNECTOR-GUIDE.md`](../../ZENDESK-CONNECTOR-GUIDE.md) — per-connector operator guides")
        lines.append(f"- PM scope `bfc3d5d0` — Tenant Manifest")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Wrote: {out_path}")
    print(f"  ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
