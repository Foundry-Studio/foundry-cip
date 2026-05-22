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


def _human_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f} {unit}" if unit != "B" else f"{int(f)} B"
        f /= 1024
    return f"{f:.1f} TB"


def _pinecone_stats_for_tenant(tenant_uuid: str) -> tuple[dict[str, int], int] | None:
    """Returns ({namespace: vectorCount}, total) for namespaces matching this
    tenant. Returns None if CIP_PINECONE_* env vars are not set (offline mode)."""
    if not os.environ.get("CIP_PINECONE_API_KEY") or not os.environ.get("CIP_PINECONE_INDEX_HOST"):
        return None
    try:
        from cip.integration_mesh.clients import PineconeClient
        pc = PineconeClient()
        stats = pc.describe_index_stats()
        ns_map = stats.get("namespaces") or {}
        tenant_ns = {
            ns: int((info or {}).get("vectorCount", 0))
            for ns, info in ns_map.items()
            if ns.startswith(f"cip__{tenant_uuid}__")
        }
        return tenant_ns, sum(tenant_ns.values())
    except Exception:  # noqa: BLE001
        return None


def _r2_stats_for_tenant(tenant_uuid: str) -> tuple[int, int, int, int] | None:
    """Returns (cip_files_count, cip_bytes, legacy_files_count, legacy_bytes)
    for this tenant. Returns None if CIP_R2_* env vars are not set."""
    needed = ("CIP_R2_BUCKET", "CIP_R2_ACCESS_KEY_ID", "CIP_R2_SECRET_ACCESS_KEY", "CIP_R2_ENDPOINT")
    if not all(os.environ.get(k) for k in needed):
        return None
    try:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ["CIP_R2_ENDPOINT"],
            aws_access_key_id=os.environ["CIP_R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["CIP_R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
        bucket = os.environ["CIP_R2_BUCKET"]
        paginator = s3.get_paginator("list_objects_v2")

        cip_files = 0
        cip_bytes = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=f"cip-originals/{tenant_uuid}/"):
            for obj in page.get("Contents", []):
                cip_files += 1
                cip_bytes += int(obj["Size"])

        legacy_files = 0
        legacy_bytes = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{tenant_uuid}/"):
            for obj in page.get("Contents", []):
                legacy_files += 1
                legacy_bytes += int(obj["Size"])

        return cip_files, cip_bytes, legacy_files, legacy_bytes
    except Exception:  # noqa: BLE001
        return None


def _foundry_drift_for_tenant(c, tenant_uuid: str) -> tuple[int, list[tuple[str, str, int]]]:
    """Returns (total_chunks, [(source_id, name+type, n)]) for Foundry-side
    knowledge_chunks belonging to this tenant. Empty list if no drift."""
    try:
        total = c.execute(text(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE tenant_id = :t"
        ), {"t": tenant_uuid}).scalar() or 0
        if int(total) == 0:
            return 0, []
        rows = c.execute(text(
            "SELECT ks.source_id::text, ks.name, ks.source_type, COUNT(kc.chunk_id) AS n "
            "FROM knowledge_chunks kc "
            "JOIN knowledge_sources ks ON ks.source_id = kc.source_id "
            "WHERE kc.tenant_id = :t "
            "GROUP BY ks.source_id, ks.name, ks.source_type "
            "ORDER BY n DESC"
        ), {"t": tenant_uuid}).mappings().all()
        return int(total), [
            (r["source_id"], f"{r['name']} ({r['source_type']})", int(r["n"]))
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        return 0, []


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
    # JOS-conformant frontmatter (per CIP-K01 contract). UUID is
    # deterministic per-tenant so re-generations don't change the JOS
    # identity. Required fields: id/uuid/title/type/owner/solve_for/
    # stage_label/domain/version/created/last_modified/last_reviewed/
    # review_cadence.
    import uuid as _uuid
    tenant_manifest_uuid = str(_uuid.uuid5(
        _uuid.UUID(tenant_uuid), "cip-manifest"
    ))
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append("---")
    lines.append(f"id: CIP-DIAG-102")
    lines.append(f"uuid: {tenant_manifest_uuid}")
    lines.append(f"title: Tenant Manifest — {tenant_uuid}")
    lines.append("type: diagnostic")
    lines.append("owner: tim")
    lines.append(
        "solve_for: Auto-generated tenant data directory — tables, "
        "sync health, property catalog, lenses. Regenerated by "
        "scripts/generate_tenant_manifest.py after data changes."
    )
    lines.append("stage_label: adopt")
    lines.append("domain: dat")
    lines.append(f"version: '1.0'")
    lines.append(f"created: '{today_iso}'")
    lines.append(f"last_modified: '{today_iso}'")
    lines.append(f"last_reviewed: '{today_iso}'")
    lines.append("review_cadence: 90")
    lines.append(f"tenant_uuid: {tenant_uuid}")
    lines.append(f"last_generated_at: {now}")
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
            "cip_ticket_comments", "cip_engagements",
            "cip_owners", "cip_pipeline_stages",
            "cip_knowledge_chunks", "cip_files",
            "cip_companies_history", "cip_contacts_history",
            "cip_deals_history", "cip_tickets_history",
            "cip_ticket_comments_history", "cip_engagements_history",
        ):
            # SAVEPOINT-isolate each per-table query — a missing table
            # (e.g., cip_engagements pre-cip_16 application) shouldn't
            # poison the outer transaction for downstream queries.
            sp = c.begin_nested()
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
                sp.commit()
            except Exception as e:  # noqa: BLE001
                sp.rollback()
                lines.append(f"| `{tbl}` | ERR | {e.__class__.__name__} |")
        lines.append("")

        # ── CIP Hard Split layers (CIP-Pinecone + CIP-R2) ────────────────
        # PM scope 835c5072: extended 2026-05-22 with the Hard Split layers.
        lines.append("## CIP Hard Split — Derived (Pinecone) + Originals (R2)")
        lines.append("")
        lines.append(
            "Per `CIP-SPEC-010` (CIP Hard Split, D-d83c7e1d): CIP owns its "
            "own Pinecone index (`foundry-cip`, 2,560-dim) and R2 prefix "
            "(`cip-originals/`). The counts below reflect what's currently "
            "in those stores for this tenant."
        )
        lines.append("")

        # Derived knowledge — cip_knowledge_chunks (per source_kind) + CIP-Pinecone
        chunks_by_kind = c.execute(text(
            "SELECT source_kind, COUNT(*) AS n, MAX(embedding_model) AS model, "
            "       MAX(embedding_dim) AS dim "
            "FROM cip_knowledge_chunks WHERE tenant_id = :t "
            "GROUP BY source_kind ORDER BY n DESC"
        ), {"t": tenant_uuid}).all()
        total_chunks = sum(int(r[1]) for r in chunks_by_kind)
        embed_model = next((r[2] for r in chunks_by_kind if r[2]), None)
        embed_dim = next((r[3] for r in chunks_by_kind if r[3]), None)
        pc_result = _pinecone_stats_for_tenant(tenant_uuid)

        lines.append("### Derived knowledge (chunks + embeddings)")
        lines.append("")
        lines.append(f"- **`cip_knowledge_chunks` rows (Postgres canonical):** {total_chunks:,}")
        if embed_model and embed_dim:
            lines.append(f"- **Embedding model:** `{embed_model}` @ {embed_dim}d")
        if pc_result is not None:
            ns_map, pc_total = pc_result
            parity = "✓" if pc_total == total_chunks else "⚠"
            lines.append(f"- **CIP-Pinecone vectors:** {pc_total:,}  ·  parity {parity}")
            for ns, n in sorted(ns_map.items()):
                lines.append(f"  - `{ns}`: {n:,}")
        else:
            lines.append("- **CIP-Pinecone vectors:** _(skipped — CIP_PINECONE_* env vars not set)_")
        if chunks_by_kind:
            lines.append("")
            lines.append("| source_kind | rows |")
            lines.append("|---|---|")
            for r in chunks_by_kind:
                lines.append(f"| `{r[0]}` | {int(r[1]):,} |")
        lines.append("")

        # Originals — cip_files + CIP-R2
        lines.append("### Originals (files)")
        lines.append("")
        cip_files_n = c.execute(text(
            "SELECT COUNT(*) FROM cip_files WHERE tenant_id = :t"
        ), {"t": tenant_uuid}).scalar() or 0
        lines.append(f"- **`cip_files` rows:** {int(cip_files_n):,}")
        r2_result = _r2_stats_for_tenant(tenant_uuid)
        if r2_result is not None:
            cip_n, cip_b, leg_n, leg_b = r2_result
            lines.append(
                f"- **CIP-R2 (`cip-originals/{tenant_uuid}/`):** "
                f"{cip_n:,} files / {_human_bytes(cip_b)}"
            )
            if leg_n > 0:
                lines.append(
                    f"- **Legacy R2 prefix (`{tenant_uuid}/`):** "
                    f"{leg_n:,} files / {_human_bytes(leg_b)} "
                    "_(pre-Hard-Split holdovers — see Drift section)_"
                )
        else:
            lines.append("- **CIP-R2:** _(skipped — CIP_R2_* env vars not set)_")
        # cip_files breakdown by source_connector
        cf_by_conn = c.execute(text(
            "SELECT source_connector, COUNT(*), SUM(size_bytes) "
            "FROM cip_files WHERE tenant_id = :t "
            "GROUP BY source_connector ORDER BY COUNT(*) DESC"
        ), {"t": tenant_uuid}).all()
        if cf_by_conn:
            lines.append("")
            lines.append("| source_connector | files | total bytes |")
            lines.append("|---|---|---|")
            for r in cf_by_conn:
                lines.append(f"| `{r[0]}` | {int(r[1]):,} | {_human_bytes(int(r[2] or 0))} |")
        lines.append("")

        # Drift (Foundry-side knowledge_chunks for this tenant)
        lines.append("### Hard Split drift")
        lines.append("")
        drift_n, drift_sources = _foundry_drift_for_tenant(c, tenant_uuid)
        if drift_n == 0 and r2_result is not None and r2_result[2] == 0:
            lines.append("✓ Clean — no CIP-shaped content on the Foundry side.")
        else:
            if drift_n > 0:
                lines.append(
                    f"⚠ Foundry-Knowledge `knowledge_chunks` holds **{drift_n:,} "
                    f"chunks** for this tenant (CIP-shaped data on the wrong side):"
                )
                lines.append("")
                for sid, name, n in drift_sources:
                    lines.append(f"- `{sid}` — {name} — {n:,} chunks")
                lines.append("")
            if r2_result is not None and r2_result[2] > 0:
                lines.append(
                    f"⚠ Legacy R2 prefix `{tenant_uuid}/` holds "
                    f"**{r2_result[2]:,} files** ({_human_bytes(r2_result[3])}) "
                    "outside `cip-originals/` — kept as cold backup; "
                    "migration is optional."
                )
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
