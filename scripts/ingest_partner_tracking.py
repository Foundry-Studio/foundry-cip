# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Ingest the partner-tracking sheets (Jake's Eric-network reports) as OBSERVATIONS.

Two sources, both keyed on the Wayward brand id:

  eric-network-all-agreements.csv  (1,158 brands) — Jake's master tracking sheet,
      shared with Eric 2026-01-21. Carries Referrer, Referral Month (the kickoff
      anchor), 'Eligible for 10% Rev Share' (TRUE = rev-share brand / FALSE =
      flat-fee brand / NA = referred under Tim — Jake's own words), Status, nine
      months of month-by-month DB Status history, payment months, reversal flag.

  eric-referral-report-2026-01-20.csv — the narrower Jan-20 pull, which additionally
      carries the UTM campaign codes (xq, wd, we, wj, wx, wz, sj) — i.e. the actual
      per-partner attribution tags — plus 'Referral Source' like referral(xq),
      referral(Cassie), referral(Adina).

DESIGN RULE (Tim, 2026-07-09/13): this writes ONLY observations. Every cell becomes a
fact tagged with the file it came from. It NEVER writes nationality_class, exhibit_a,
partner_of_record, or any other decision column.

THIS MATTERS HERE especially: Tim flagged that these sheets WILL conflict with the
contract's Exhibit-A exclusion list — Eric's tracking may call a brand a flat-fee
referral where the signed exclusion list says something else. That disagreement is a
FINDING, not a bug. Both statements are recorded, each with its source, and the
decision layer resolves them (and surfaces the ones that can't be resolved). Nothing
silently overwrites anything.

Every column is carried through, not just the ones we currently use — the point is to
keep all the information, and let the decision layer choose.

Usage:
  DATABASE_URL=... python scripts/ingest_partner_tracking.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_DIR = (
    "c:/Users/Tim Jordan/code/venture-ecomlever/clients/wayward/data/partner-tracking"
)

# file -> (source_system, the column holding the wayward brand id)
SOURCES: dict[str, tuple[str, str]] = {
    "eric-network-all-agreements.csv": ("gsheet:eric-all-agreements", "Brand ID"),
    "eric-referral-report-2026-01-20.csv": ("gsheet:eric-referral-2026-01-20", "ID"),
}

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def _field(header: str) -> str:
    """'DB Status - December' -> 'db_status_december'. Keep the source's own naming;
    do not silently rename a source's concept into ours."""
    s = re.sub(r"[^a-z0-9]+", "_", (header or "").strip().lower())
    return s.strip("_")


_INSERT = text(
    """
    INSERT INTO ps_brand_observations (
        tenant_id, subject_type, wayward_brand_id, client_id,
        field, value, value_normalized, source_system, source_ref
    ) VALUES (:t, 'brand', :wbid, :cid, :field, :value, :norm, :src, :ref)
    ON CONFLICT (tenant_id, subject_type, wayward_brand_id, field,
                 source_system, source_ref) DO NOTHING
    """
)


def run(engine, *, dry_run: bool) -> dict:
    out = []
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
        )
        wbid_map = {
            str(w): str(c)
            for c, w in conn.execute(
                text(
                    "SELECT id, wayward_brand_id FROM cip_clients "
                    "WHERE wayward_brand_id IS NOT NULL"
                )
            ).fetchall()
        }

        for fname, (src, key_col) in SOURCES.items():
            path = Path(_DIR) / fname
            if not path.exists():
                out.append({"file": fname, "SKIPPED": "not found"})
                continue
            with path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            if not rows or key_col not in rows[0]:
                out.append({"file": fname, "REJECTED": f"missing key column {key_col}"})
                continue

            pending, brands, matched, skipped = [], set(), 0, 0
            for r in rows:
                wbid = (r.get(key_col) or "").strip()
                if not _UUID.match(wbid):
                    skipped += 1
                    continue
                brands.add(wbid)
                cid = wbid_map.get(wbid)
                if cid:
                    matched += 1
                for header, value in r.items():
                    if header == key_col or not header:
                        continue
                    v = (value or "").strip()
                    if not v:
                        continue  # an empty cell is not a fact
                    pending.append({
                        "t": PS_TENANT, "wbid": wbid, "cid": cid,
                        "field": _field(header), "value": v,
                        "norm": v.lower(), "src": src, "ref": fname,
                    })
            if not dry_run and pending:
                for i in range(0, len(pending), 1000):
                    conn.execute(_INSERT, pending[i:i + 1000])
            out.append({
                "file": fname, "source_system": src,
                "brands": len(brands),
                "matched_to_cip_clients": matched,
                "rows_without_valid_brand_id": skipped,
                "observations": len(pending),
            })

        totals = conn.execute(
            text(
                "SELECT source_system, count(*), count(DISTINCT wayward_brand_id) "
                "FROM ps_brand_observations WHERE tenant_id=:t GROUP BY 1 ORDER BY 1"
            ),
            {"t": PS_TENANT},
        ).fetchall() if not dry_run else []
        if dry_run:
            conn.execute(text("ROLLBACK"))

    return {
        "files": out,
        "observations_by_source": [
            {"source": r[0], "observations": r[1], "brands": r[2]} for r in totals
        ],
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
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
        print(json.dumps(run(engine, dry_run=args.dry_run), indent=2))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
