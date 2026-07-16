# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Manual China determinations — 2026-07-16. Tim's rulings, written INTO the CIP, not a chat window.

Three brands sat on the PROGRAM HOLD list (nationality judgment calls). Tim ruled all three
not_china on 2026-07-16. Each lands in ps_nationality_signals as signal='manual_review',
points_to='not_china', with the reasoning in `evidence` and Tim named in `asserted_by` — so the call
can be audited, overturned, re-run against new data, and DEFENDED TO WAYWARD line by line. A named
human's not_china is the top authority tier (lens_ps_china_verdict reads it FIRST); no machine
signal can overturn it.

Idempotent: ON CONFLICT (tenant, brand, signal, source_system) updates in place. Dry-run by default;
pass --apply to commit.

    .venv/Scripts/python.exe scripts/manual_china_review_2026_07_16.py            # dry-run
    .venv/Scripts/python.exe scripts/manual_china_review_2026_07_16.py --apply    # commit
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
BY = "Tim Jordan"
SOURCE = "manual:review_2026_07_16"

# (exact brand_name in ps_brands, Tim's rationale). Exact match only — never fuzzy-match a ruling.
NOT_CHINA: list[tuple[str, str]] = [
    ("Solid Gold",
     "US pet-food brand (Chesterfield, MO). Parent H&H Group is Hong-Kong-listed, but this is a "
     "genuine US operating brand, not a shell — nationality follows the operating brand, as with "
     "Kate Farms under Danone. Tim ruling, 2026-07-16."),
    ("NORDMOND",
     "Tim ruling, 2026-07-16: not_china. Signals were conflicted (one batch likely-China; another "
     "a Romanian privacy entity, self-flagged thin) — Tim's determination is authoritative."),
    ("Intent Brands",
     "Named founder (Janco Bronkhorst); a US LLC holds the trademarks. The sole Sheridan, WY "
     "address is a mail-drop, not a clearance-blocker against a founder + trademark ownership. Tim "
     "ruling, 2026-07-16."),
]

_INS = text("""
    INSERT INTO ps_nationality_signals
        (tenant_id, wayward_brand_id, signal, strength, points_to, evidence, source_system,
         asserted_by)
    SELECT CAST(:t AS uuid), b.wayward_brand_id, 'manual_review', 'negative', 'not_china',
           :evidence, :source, :by
    FROM ps_brands b
    WHERE b.tenant_id = CAST(:t AS uuid) AND b.brand_name = :name
    ON CONFLICT (tenant_id, wayward_brand_id, signal, source_system) DO UPDATE
       SET evidence = EXCLUDED.evidence, points_to = EXCLUDED.points_to,
           strength = EXCLUDED.strength, asserted_by = EXCLUDED.asserted_by
""")

_VERDICT = text("""
    SELECT v.verdict, v.verdict_strength
    FROM ps_brands b JOIN lens_ps_china_verdict v ON v.wayward_brand_id = b.wayward_brand_id
    WHERE b.tenant_id = CAST(:t AS uuid) AND b.brand_name = :name
""")


def run(conn) -> dict:
    conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT})
    out: dict = {"determinations": [], "not_matched": []}
    for name, why in NOT_CHINA:
        before = conn.execute(_VERDICT, {"t": PS_TENANT, "name": name}).fetchone()
        r = conn.execute(_INS, {"t": PS_TENANT, "name": name, "evidence": why,
                                "source": SOURCE, "by": BY})
        if r.rowcount == 0:
            out["not_matched"].append(name)
            continue
        after = conn.execute(_VERDICT, {"t": PS_TENANT, "name": name}).fetchone()
        out["determinations"].append({
            "brand": name, "rows": r.rowcount,
            "verdict_before": before[0] if before else None,
            "verdict_after": after[0] if after else None,
            "strength_after": after[1] if after else None,
        })
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
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
        with engine.connect() as conn:
            out = run(conn)
            if args.apply:
                conn.commit()
                out["applied"] = True
            else:
                conn.rollback()
                out["applied"] = False
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
