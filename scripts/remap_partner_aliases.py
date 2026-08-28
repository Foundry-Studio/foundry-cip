# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Remap stale partner_of_record aliases onto their canonical partner (reports #5 accuracy).

THE INACCURACY: the reports partner list shows duplicate partners because some
ps_partner_credit rows carry an ALIAS in partner_of_record instead of the canonical
partner:
  - 'xq'  is Kerry  (xq / xueqiu / 雪球 / snowball -> kerry, per rebuild_partner_attribution.PARTNER_MAP)
  - 'sj'  is Sarah  (sj / sjwayward -> sarah)
rebuild_partner_attribution.py already knows these mappings, but it only reprocesses
BILLED brands (ps_stripe_invoice_lines is_ps_base), so churned/unbilled brands kept
their old un-merged attribution. This is a one-time correction over ALL rows.

SAFE ON THE UNIQUE KEYS: ps_partner_credit is unique on (tenant, client_id, product_id)
and (tenant, wayward_brand_id, product_id) -- NOT on partner_of_record -- so changing
partner_of_record cannot create a duplicate. It IS a money change (partner_of_record
drives commission): xq's brands start earning for Kerry, sj's for Sarah. Flagged to Tim.

NOT TOUCHED: Eric's two-letter codes (we / wt / wx / vy / wg / ma / wj / wd / wr / wn) are
partners we "do not know who they are" (rebuild docstring) -- reported here as an open
question for Eric/Jake, never auto-remapped.

Usage:
  DATABASE_URL=... python scripts/remap_partner_aliases.py [--apply]

Dry-run by default (prints what it would change); pass --apply to commit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

# Known aliases -> canonical partner_id (subset of rebuild_partner_attribution.PARTNER_MAP
# that currently appears as a stale partner_of_record).
KNOWN_MERGES = {"xq": "kerry", "sj": "sarah"}

# Eric's codes: real partners in his sheet, identity unknown. Reported, NEVER remapped.
UNKNOWN_CODES = ("we", "wt", "wx", "vy", "wg", "ma", "wj", "wd", "wr", "wn")

_COUNT = text(
    "SELECT count(*) FROM ps_partner_credit WHERE tenant_id = :t AND partner_of_record = :a"
)
_REMAP = text("""
    UPDATE ps_partner_credit
       SET partner_of_record = :c,
           determined_at = now(),
           determination_note = coalesce(determination_note, '')
               || ' [remap_partner_aliases: ' || :a || '->' || :c || ']'
     WHERE tenant_id = :t AND partner_of_record = :a
""")


def run(conn, *, apply: bool) -> dict:
    conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT})

    merges: dict[str, int] = {}
    for alias, canonical in KNOWN_MERGES.items():
        n = conn.execute(_COUNT, {"t": PS_TENANT, "a": alias}).scalar() or 0
        merges[f"{alias}->{canonical}"] = int(n)
        if apply and n:
            conn.execute(_REMAP, {"t": PS_TENANT, "a": alias, "c": canonical})

    unknown: dict[str, int] = {}
    for code in UNKNOWN_CODES:
        n = conn.execute(_COUNT, {"t": PS_TENANT, "a": code}).scalar() or 0
        if n:
            unknown[code] = int(n)

    out = {
        "known_merges_credit_rows": merges,
        "unknown_eric_codes_left": unknown,
        "unknown_note": "Eric's codes are NOT remapped — identity unknown; open question for Eric/Jake.",
        "applied": apply,
    }
    if not apply:
        conn.execute(text("ROLLBACK"))
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Remap stale partner_of_record aliases to canonical partners.")
    ap.add_argument("--apply", action="store_true", help="commit (default: dry-run)")
    ap.add_argument("--database-url", default=None)
    args = ap.parse_args(argv)
    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            out = run(conn, apply=args.apply)
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
