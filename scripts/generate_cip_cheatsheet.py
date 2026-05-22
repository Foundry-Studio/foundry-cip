# foundry: kind=script domain=client-intelligence-platform
"""Generate docs/CIP-CHEATSHEET.md — the cross-tenant "what's in CIP" index.

Per Tim's directive (2026-05-22) and PM scope 9cd4071c (CIP Inventory +
Discovery System design call). One scannable Markdown file at the top of
the docs tree. Plain text, in git, regenerates on every sync run + nightly.

Layout (mirrors the design Tim signed off on):

    # CIP Cheatsheet — generated <UTC>
    Tenants:N  Clients:N  Chunks:N  Vectors:N  R2: ...
    Status:    green/yellow/red one-liners per active tenant

    ## <Tenant name>
      Clients: ...
      Structured: cip_companies N  cip_contacts N  cip_tickets N  ...
      Derived:    cip_knowledge_chunks N   CIP-Pinecone vectors N (parity ✓/⚠)
                  embed: <model> @ <dim>d
      Originals:  cip_files N    CIP-R2 N MB
      Sync runs:  last <date>, errors=N
      Drift:      ✓ clean  |  ⚠ <description>

    ## Drift summary
      ⚠ Foundry-Knowledge has X chunks tagged Y for tenant Z

Exit code:
  0 = clean (no drift flagged)
  3 = drift flagged AND --strict is set (for CI gating)
  0 otherwise — drift goes into the cheatsheet but does not fail the script.

Run:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        CIP_PINECONE_API_KEY=... \\
        CIP_PINECONE_INDEX_HOST=... \\
        CIP_R2_BUCKET=... \\
        CIP_R2_ACCESS_KEY_ID=... \\
        CIP_R2_SECRET_ACCESS_KEY=... \\
        CIP_R2_ENDPOINT=... \\
        python scripts/generate_cip_cheatsheet.py [--strict]

The file written is `docs/CIP-CHEATSHEET.md`. If `--strict` is passed and
drift is found, exit 3 (intended for CI). The pre-commit / CI gate that
runs this script in --strict mode will fail the build when CIP-shaped
data is detected in places it doesn't belong.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from cip.integration_mesh.clients import PineconeClient


# -- DTOs --------------------------------------------------------------------

@dataclass
class TenantBlock:
    tenant_id: str
    tenant_name: str
    tenant_type: str
    tenant_status: str
    clients: list[dict[str, str]] = field(default_factory=list)
    # Structured layer — cip_* tables
    structured_counts: dict[str, int] = field(default_factory=dict)
    # Derived knowledge
    chunks_pg: int = 0
    chunks_pg_by_kind: dict[str, int] = field(default_factory=dict)
    pinecone_vectors: int = 0           # sum across all namespaces for this tenant
    pinecone_namespaces: list[tuple[str, int]] = field(default_factory=list)
    embedding_model: str | None = None
    embedding_dim: int | None = None
    # Originals
    cip_files_count: int = 0
    cip_r2_files: int = 0
    cip_r2_bytes: int = 0
    # Drift
    foundry_kn_chunks: int = 0
    foundry_kn_sources: list[tuple[str, str, int]] = field(default_factory=list)  # (source_id, name+type, chunks)
    legacy_r2_bytes: int = 0    # bytes under non-cip-originals tenant prefixes
    legacy_r2_files: int = 0


# -- Data fetchers -----------------------------------------------------------

STRUCTURED_TABLES = [
    "cip_clients", "cip_companies", "cip_contacts", "cip_deals",
    "cip_tickets", "cip_ticket_comments", "cip_engagements",
    "cip_owners", "cip_pipeline_stages", "cip_files",
    "cip_marketing_emails", "cip_contact_lists",
]


def _tenants(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(text(
        "SELECT tenant_id::text, name, type, status FROM tenants "
        "ORDER BY name"
    )).mappings().all()
    return [dict(r) for r in rows]


def _structured_counts(db: Session, tenant_id: str) -> dict[str, int]:
    """Returns {table_name: row_count}, skipping tables that don't exist."""
    out: dict[str, int] = {}
    for tbl in STRUCTURED_TABLES:
        try:
            n = db.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = :t"),
                {"t": tenant_id},
            ).scalar() or 0
            out[tbl] = int(n)
        except Exception:  # noqa: BLE001
            # Table missing in this env — skip silently
            pass
    return out


def _clients(db: Session, tenant_id: str) -> list[dict[str, str]]:
    rows = db.execute(text(
        "SELECT client_id::text AS client_id, name, slug, industry "
        "FROM cip_clients WHERE tenant_id = :t ORDER BY slug"
    ), {"t": tenant_id}).mappings().all()
    return [dict(r) for r in rows]


def _chunks_breakdown(db: Session, tenant_id: str) -> tuple[int, dict[str, int], str | None, int | None]:
    rows = db.execute(text(
        "SELECT source_kind, COUNT(*) AS n, "
        "       MAX(embedding_model) AS model, MAX(embedding_dim) AS dim "
        "FROM cip_knowledge_chunks WHERE tenant_id = :t "
        "GROUP BY source_kind"
    ), {"t": tenant_id}).mappings().all()
    total = 0
    by_kind: dict[str, int] = {}
    model: str | None = None
    dim: int | None = None
    for r in rows:
        n = int(r["n"])
        total += n
        by_kind[r["source_kind"]] = n
        if r["model"] and not model:
            model = r["model"]
        if r["dim"] and not dim:
            dim = int(r["dim"])
    return total, by_kind, model, dim


def _foundry_kn_drift(db: Session, tenant_id: str) -> tuple[int, list[tuple[str, str, int]]]:
    """Count chunks in Foundry-side knowledge_chunks for this tenant + name the sources."""
    try:
        total = db.execute(text(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE tenant_id = :t"
        ), {"t": tenant_id}).scalar() or 0
    except Exception:  # noqa: BLE001
        return 0, []
    if int(total) == 0:
        return 0, []
    rows = db.execute(text(
        "SELECT ks.source_id::text, ks.name, ks.source_type, COUNT(kc.chunk_id) AS n "
        "FROM knowledge_chunks kc "
        "JOIN knowledge_sources ks ON ks.source_id = kc.source_id "
        "WHERE kc.tenant_id = :t "
        "GROUP BY ks.source_id, ks.name, ks.source_type "
        "ORDER BY n DESC"
    ), {"t": tenant_id}).mappings().all()
    out = [(r["source_id"], f"{r['name']} ({r['source_type']})", int(r["n"])) for r in rows]
    return int(total), out


def _pinecone_inventory(pc: PineconeClient) -> dict[str, int]:
    """Returns {namespace: vectorCount} across the whole CIP-Pinecone index."""
    stats = pc.describe_index_stats()
    ns_map = stats.get("namespaces") or {}
    return {ns: int((info or {}).get("vectorCount", 0)) for ns, info in ns_map.items()}


def _r2_inventory(s3, bucket: str) -> dict[str, dict[str, dict[str, int]]]:
    """
    Returns nested dict:
      {
        "cip": {"<tenant_id>": {"files": N, "bytes": N}},
        "legacy": {"<tenant_id>": {"files": N, "bytes": N}},
      }
    "cip" counts objects under cip-originals/{tenant}/... ; "legacy" counts
    every other top-level prefix that LOOKS LIKE a UUID tenant prefix.
    """
    cip: dict[str, dict[str, int]] = {}
    legacy: dict[str, dict[str, int]] = {}
    paginator = s3.get_paginator("list_objects_v2")

    # CIP slice
    for page in paginator.paginate(Bucket=bucket, Prefix="cip-originals/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # cip-originals/{tenant}/{client}/...
            parts = key.split("/", 3)
            if len(parts) < 3:
                continue
            t = parts[1]
            cip.setdefault(t, {"files": 0, "bytes": 0})
            cip[t]["files"] += 1
            cip[t]["bytes"] += int(obj["Size"])

    # Legacy slice (top-level UUID prefixes)
    delim = paginator.paginate(Bucket=bucket, Delimiter="/")
    legacy_prefixes: list[str] = []
    for page in delim:
        for cp in page.get("CommonPrefixes", []):
            p = cp.get("Prefix", "")
            stripped = p.rstrip("/")
            if len(stripped) == 36 and stripped.count("-") == 4:  # crude UUID shape check
                legacy_prefixes.append(p)
    for lp in legacy_prefixes:
        files = 0
        size_total = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=lp):
            for obj in page.get("Contents", []):
                files += 1
                size_total += int(obj["Size"])
        legacy[lp.rstrip("/")] = {"files": files, "bytes": size_total}

    return {"cip": cip, "legacy": legacy}


# -- Rendering ---------------------------------------------------------------

def _human_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f} {unit}" if unit != "B" else f"{int(f)} B"
        f /= 1024
    return f"{f:.1f} TB"  # unreachable


def _render(blocks: list[TenantBlock], generated_at: datetime) -> tuple[str, bool]:
    """Render the cheatsheet. Returns (markdown_text, drift_present)."""
    lines: list[str] = []
    # Frontmatter (CIP-DIAG-103 to slot beside the per-tenant manifests)
    lines.append("---")
    lines.append("id: CIP-DIAG-103")
    lines.append("uuid: 6b4e8d12-7a2c-4b9e-9f3a-8d2c4e5f6a7b")
    lines.append("title: CIP Cheatsheet — cross-tenant data-plane inventory")
    lines.append("type: diagnostic")
    lines.append("owner: tim")
    lines.append(
        "solve_for: Single scannable surface answering 'what is in CIP right now' "
        "across tenants — structured / derived / originals + drift flags. "
        "Regenerated by scripts/generate_cip_cheatsheet.py."
    )
    lines.append("stage_label: adopt")
    lines.append("domain: meta")
    lines.append("version: '1.0'")
    today = generated_at.strftime("%Y-%m-%d")
    lines.append(f"created: '{today}'")
    lines.append(f"last_modified: '{today}'")
    lines.append(f"last_reviewed: '{today}'")
    lines.append("review_cadence: 1")
    lines.append(f"last_generated_at: {generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("generator: scripts/generate_cip_cheatsheet.py (PM scope 9cd4071c)")
    lines.append("---")
    lines.append("")
    lines.append("# CIP Cheatsheet")
    lines.append("")
    lines.append(f"> **Generated:** {generated_at.strftime('%Y-%m-%d %H:%M UTC')}  ")
    lines.append(
        "> **Do not edit by hand** — re-run `python scripts/generate_cip_cheatsheet.py`. "
        "Pass `--strict` for CI to exit 3 if drift is flagged."
    )
    lines.append("")

    # Scoreboard
    total_tenants = sum(1 for b in blocks if b.tenant_status == "active")
    total_clients = sum(len(b.clients) for b in blocks)
    total_chunks = sum(b.chunks_pg for b in blocks)
    total_vectors = sum(b.pinecone_vectors for b in blocks)
    total_files = sum(b.cip_files_count for b in blocks)
    total_r2_bytes = sum(b.cip_r2_bytes for b in blocks)

    # Drift classification per CIP-SPEC-010 §3:
    #   - type='foundry' tenants own their own data plane (Foundry-Knowledge,
    #     Foundry-R2 etc.) — their non-CIP-shaped content stays put. Do not
    #     flag Foundry-tenant data as drift.
    #   - For venture tenants, any data on the Foundry side IS drift.
    def _is_drift(b: TenantBlock) -> bool:
        if b.tenant_type == "foundry":
            return False
        return b.foundry_kn_chunks > 0 or b.legacy_r2_files > 0
    drift_present = any(_is_drift(b) for b in blocks)

    lines.append("## Scoreboard")
    lines.append("")
    lines.append(f"- **Active tenants:** {total_tenants}")
    lines.append(f"- **Clients:** {total_clients}")
    lines.append(f"- **Postgres chunks (`cip_knowledge_chunks`):** {total_chunks:,}")
    lines.append(f"- **CIP-Pinecone vectors:** {total_vectors:,}")
    lines.append(f"- **`cip_files` rows:** {total_files:,}")
    lines.append(f"- **CIP-R2 (`cip-originals/`):** {_human_bytes(total_r2_bytes)}")
    lines.append("")
    lines.append("### Status")
    lines.append("")
    for b in blocks:
        if b.tenant_status != "active":
            continue
        if b.tenant_type == "foundry":
            status = "⬜ foundry-side (exempt)"
        elif _is_drift(b):
            status = "🟡 drift detected"
        else:
            status = "🟢 clean"
        lines.append(f"- {status} — **{b.tenant_name}** ({b.tenant_type})")
    lines.append("")

    # Per-tenant blocks
    for b in blocks:
        if b.tenant_status != "active":
            continue
        lines.append(f"## {b.tenant_name}")
        lines.append("")
        lines.append(f"- `tenant_id` = `{b.tenant_id}`  ·  type = {b.tenant_type}  ·  status = {b.tenant_status}")
        # Clients
        if b.clients:
            lines.append(f"- **Clients ({len(b.clients)}):**")
            for c in b.clients:
                indus = f" · *{c.get('industry') or 'n/a'}*"
                lines.append(
                    f"  - `{c['slug']}` — {c['name']}{indus} — `{c['client_id']}`"
                )
        else:
            lines.append("- **Clients:** (none yet)")
        # Structured
        struct_items = [
            f"`{tbl}`={n:,}"
            for tbl, n in b.structured_counts.items()
            if n > 0
        ]
        if struct_items:
            lines.append("- **Structured:** " + "  ·  ".join(struct_items))
        else:
            lines.append("- **Structured:** (no rows)")
        # Derived
        parity = "✓" if b.chunks_pg == b.pinecone_vectors else "⚠"
        embed_line = (
            f" · embed: `{b.embedding_model}` @ {b.embedding_dim}d"
            if b.embedding_model and b.embedding_dim
            else ""
        )
        lines.append(
            f"- **Derived:** `cip_knowledge_chunks` {b.chunks_pg:,}  ·  "
            f"CIP-Pinecone {b.pinecone_vectors:,}  ·  parity {parity}{embed_line}"
        )
        if b.chunks_pg_by_kind:
            kinds = "  ·  ".join(
                f"`{k}`={v:,}" for k, v in sorted(b.chunks_pg_by_kind.items())
            )
            lines.append(f"  - by source_kind: {kinds}")
        if b.pinecone_namespaces:
            for ns, n in b.pinecone_namespaces:
                lines.append(f"  - Pinecone ns `{ns}`: {n:,} vectors")
        # Originals
        lines.append(
            f"- **Originals:** `cip_files` {b.cip_files_count:,}  ·  "
            f"CIP-R2 {_human_bytes(b.cip_r2_bytes)} across {b.cip_r2_files:,} files"
        )
        # Drift — Foundry-type tenants own their own data plane (CIP-SPEC-010 §3)
        if b.tenant_type == "foundry":
            note_lines = ["- **Drift:** ⬜ foundry-side (exempt — owns its own data plane per CIP-SPEC-010)"]
            if b.foundry_kn_chunks > 0:
                note_lines.append(
                    f"  - holds {b.foundry_kn_chunks:,} chunks in `knowledge_chunks` "
                    f"(Foundry-internal, legitimately not in CIP)"
                )
            if b.legacy_r2_files > 0:
                note_lines.append(
                    f"  - holds {b.legacy_r2_files:,} R2 objects under `{b.tenant_id}/` "
                    f"({_human_bytes(b.legacy_r2_bytes)}; consultations/system_prompts/etc — stays put)"
                )
            for nl in note_lines:
                lines.append(nl)
        else:
            drift_items: list[str] = []
            if b.foundry_kn_chunks > 0:
                sources_desc = "; ".join(
                    f"{name} ({n:,} chunks)" for _, name, n in b.foundry_kn_sources[:3]
                )
                drift_items.append(
                    f"⚠ Foundry-Knowledge holds {b.foundry_kn_chunks:,} chunks for "
                    f"this tenant — {sources_desc}"
                )
            if b.legacy_r2_files > 0:
                drift_items.append(
                    f"⚠ Legacy R2 prefix `{b.tenant_id}/` holds {b.legacy_r2_files:,} "
                    f"objects ({_human_bytes(b.legacy_r2_bytes)}) — not under `cip-originals/`"
                )
            if drift_items:
                lines.append("- **Drift:**")
                for d in drift_items:
                    lines.append(f"  - {d}")
            else:
                lines.append("- **Drift:** ✓ clean")
        lines.append("")

    # Drift summary
    lines.append("## Drift summary")
    lines.append("")
    if not drift_present:
        lines.append("✓ No drift across any venture tenant. CIP holds CIP-shaped data; Foundry-Knowledge holds Foundry-shaped data.")
    else:
        lines.append("⚠ One or more venture tenants have CIP-shaped data on the Foundry side:")
        lines.append("")
        for b in blocks:
            if b.tenant_type == "foundry":
                continue
            if b.foundry_kn_chunks > 0 or b.legacy_r2_files > 0:
                lines.append(f"- **{b.tenant_name}** (`{b.tenant_id}`):")
                if b.foundry_kn_chunks > 0:
                    for sid, name, n in b.foundry_kn_sources:
                        lines.append(
                            f"  - `knowledge_chunks` {n:,} chunks under `{name}` "
                            f"(source_id `{sid}`) — migrate via foundry-cip "
                            f"`scripts/migrate_rocky_ridge_to_cip.py` pattern"
                        )
                if b.legacy_r2_files > 0:
                    lines.append(
                        f"  - R2 legacy: {b.legacy_r2_files:,} objects under "
                        f"`{b.tenant_id}/` — copy into `cip-originals/{b.tenant_id}/<client>/...` "
                        f"or leave as cold backup"
                    )
        lines.append("")
        lines.append(
            "**For CI:** run `python scripts/generate_cip_cheatsheet.py --strict` "
            "to fail the build when drift is detected."
        )
    lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("Generated by `scripts/generate_cip_cheatsheet.py` per CIP-SPEC-010 "
                 "(Hard Split) + PM scope `9cd4071c`. Pre-tenant drilldown lives in "
                 "`docs/tenants/{tenant_uuid}/MANIFEST.md`.")
    return "\n".join(lines) + "\n", drift_present


# -- Main --------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/CIP-CHEATSHEET.md",
                    help="Output path (default docs/CIP-CHEATSHEET.md)")
    ap.add_argument("--strict", action="store_true",
                    help="Exit 3 if any drift is flagged (intended for CI)")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)

    pc = PineconeClient()
    pc_ns = _pinecone_inventory(pc)

    bucket = os.environ.get("CIP_R2_BUCKET", "foundry-agent-system")
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["CIP_R2_ENDPOINT"],
        aws_access_key_id=os.environ["CIP_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["CIP_R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    r2 = _r2_inventory(s3, bucket)

    blocks: list[TenantBlock] = []
    with Session(engine) as db:
        tenants = _tenants(db)
        for t in tenants:
            tid = t["tenant_id"]
            block = TenantBlock(
                tenant_id=tid,
                tenant_name=t["name"],
                tenant_type=t["type"],
                tenant_status=t["status"],
                clients=_clients(db, tid),
                structured_counts=_structured_counts(db, tid),
            )
            chunks, by_kind, model, dim = _chunks_breakdown(db, tid)
            block.chunks_pg = chunks
            block.chunks_pg_by_kind = by_kind
            block.embedding_model = model
            block.embedding_dim = dim

            # Pinecone — sum all namespaces that start with cip__{tid}__
            for ns, n in pc_ns.items():
                if ns.startswith(f"cip__{tid}__"):
                    block.pinecone_namespaces.append((ns, n))
                    block.pinecone_vectors += n
            # Files
            block.cip_files_count = block.structured_counts.get("cip_files", 0)
            # R2
            cip_t = r2["cip"].get(tid, {})
            block.cip_r2_files = int(cip_t.get("files", 0))
            block.cip_r2_bytes = int(cip_t.get("bytes", 0))
            # Drift
            fk_total, fk_sources = _foundry_kn_drift(db, tid)
            block.foundry_kn_chunks = fk_total
            block.foundry_kn_sources = fk_sources
            legacy = r2["legacy"].get(tid, {})
            block.legacy_r2_files = int(legacy.get("files", 0))
            block.legacy_r2_bytes = int(legacy.get("bytes", 0))
            blocks.append(block)

    md, drift = _render(blocks, datetime.now(timezone.utc))
    out_path = args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md)
    print(f"[cip-cheatsheet] wrote {out_path} ({len(md):,} chars, drift={drift})")

    if drift and args.strict:
        print("[cip-cheatsheet] DRIFT FLAGGED + --strict set → exit 3", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
