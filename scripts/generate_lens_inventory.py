# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Generate docs/LENS-INVENTORY.md from a live full-chain CIP database.

Ground-truth inventory of every ``lens_*`` view: which roles can read it,
whether it is tenant-pinned or GUC-only, and its registered description.

Sourcing from the live DB (not by parsing migrations) keeps the table honest —
CREATE OR REPLACE across migrations, helper-generated views (cip_18), and grant
repairs (cip_37) all land in one place: ``pg_views`` + the grant catalog.

Usage:
    DATABASE_URL=postgresql+psycopg://user:pw@host:5432/db \
        python scripts/generate_lens_inventory.py            # writes docs/LENS-INVENTORY.md
    ... python scripts/generate_lens_inventory.py -           # or print to stdout

Point it at a local ``postgres:16-alpine`` with ``alembic upgrade head`` applied
(NOT prod — this is a doc-gen convenience, read-only, but use a scratch DB).

The "Migration" column is resolved by grepping the migration sources for the
view name; if a view is created in more than one migration (CREATE OR REPLACE),
all creating revisions are listed.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

# Roles whose SELECT grant on a lens is meaningful (provisioned across
# cip_09/cip_21/cip_25/cip_28/cip_31). Absent roles are simply skipped.
_KNOWN_ROLES = (
    "cip_query_reader",
    "cip_metabase_role",
    "cip_metabase_project_silk",
    "cip_twenty_project_silk",
    "cip_sync_reader",
)

_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "cip" / "migrations" / "versions"


def _normalize_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _creating_migrations() -> dict[str, list[str]]:
    """Map view_name -> [revision ids that CREATE it], via source grep."""
    out: dict[str, list[str]] = {}
    pat = re.compile(r"CREATE (?:OR REPLACE )?VIEW\s+(lens_[a-z0-9_]+)", re.I)
    # cip_18 builds domain lenses from a _DOMAIN_LENSES tuple via a helper —
    # capture those names too.
    tuple_pat = re.compile(r'"(lens_[a-z0-9_]+)"')
    for path in sorted(_VERSIONS_DIR.glob("cip_*.py")):
        rev = path.stem  # e.g. cip_18_wayward_attr_lenses
        text_src = path.read_text(encoding="utf-8")
        names = set(pat.findall(text_src))
        if "_DOMAIN_LENSES" in text_src:
            names |= set(tuple_pat.findall(text_src))
        for name in names:
            out.setdefault(name, []).append(rev.split("_")[0] + "_" + rev.split("_")[1])
    return out


def _existing_roles(conn) -> set[str]:
    rows = conn.execute(text("SELECT rolname FROM pg_roles")).fetchall()
    return {r[0] for r in rows}


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1
    engine = create_engine(_normalize_url(url))
    creators = _creating_migrations()

    with engine.connect() as conn:
        roles = [r for r in _KNOWN_ROLES if r in _existing_roles(conn)]
        views = [
            r[0] for r in conn.execute(text(
                "SELECT viewname FROM pg_views "
                "WHERE schemaname='public' AND viewname LIKE 'lens_%' "
                "ORDER BY viewname"
            )).fetchall()
        ]
        rows = []
        for v in views:
            # Grants
            granted = [
                role for role in roles
                if conn.execute(text(
                    "SELECT has_table_privilege("
                    ":r, format('public.%I', CAST(:v AS text)), 'SELECT')"
                ), {"r": role, "v": v}).scalar()
            ]
            # Tenant-pinned (hardcoded UUID in the view body) vs GUC-only
            body = conn.execute(text(
                "SELECT pg_get_viewdef(format('public.%I', CAST(:v AS text))::regclass, true)"
            ), {"v": v}).scalar() or ""
            pinned = bool(re.search(r"tenant_id\s*=\s*'[0-9a-f-]{36}'", body))
            scope = "tenant-pinned + GUC" if pinned else "GUC-only"
            # Description from cip_views registration (best-effort)
            desc = conn.execute(text(
                "SELECT description FROM cip_views WHERE view_name = :v "
                "ORDER BY updated_at DESC LIMIT 1"
            ), {"v": v}).scalar() or "—"
            mig = ", ".join(sorted(set(creators.get(v, [])))) or "?"
            rows.append((v, mig, scope, ", ".join(granted) or "(none)", desc))

    # Build markdown
    lines = [
        "---",
        "doc_type: reference",
        "owner: tim",
        "status: active",
        "generated_by: scripts/generate_lens_inventory.py",
        "---",
        "# CIP Lens Inventory",
        "",
        "Every `lens_*` view in the CIP schema — the read surface exposed to Metabase, the Twenty",
        "CRM mirror, and the agent SQL bridge (`cip_query_reader`). Raw `cip_*` tables are never",
        "granted to these roles (P-21); all consumption goes through a lens.",
        "",
        "**This file is generated** — do not hand-edit. "
        "Regenerate against a full-chain scratch DB:",
        "",
        "```bash",
        "DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/cip \\",
        "    python scripts/generate_lens_inventory.py",
        "```",
        "",
        "Scope legend: **GUC-only** = tenant selected purely by the "
        "`app.current_tenant` session GUC",
        "(reusable across tenants); **tenant-pinned + GUC** = view body also hardcodes a specific",
        "tenant UUID (PS-owned lenses) *and* re-checks the GUC, so it "
        "yields rows only under that tenant.",
        "",
        "| Lens view | Migration | Tenant scope | Grants (SELECT) | Purpose |",
        "|---|---|---|---|---|",
    ]
    for v, mig, scope, grants, desc in rows:
        desc = desc.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{v}` | {mig} | {scope} | {grants} | {desc} |")
    lines.append("")
    lines.append(
        f"_{len(rows)} lens views. Roles: `cip_query_reader` (agent SQL / Path 1, cip_31), "
        "`cip_metabase_role` (Foundry-internal Metabase, cip_09), `cip_metabase_project_silk` "
        "(PS Metabase, cip_21), `cip_twenty_project_silk` (PS Twenty CRM mirror, cip_25)._"
    )
    content = "\n".join(lines) + "\n"

    dest = sys.argv[1] if len(sys.argv) > 1 else str(
        Path(__file__).resolve().parent.parent / "docs" / "LENS-INVENTORY.md"
    )
    if dest == "-":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stdout.write(content)
    else:
        Path(dest).write_text(content, encoding="utf-8")
        print(f"wrote {dest} ({len(rows)} lenses)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
