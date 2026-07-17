# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Harvest every automatic China signal we already hold. Facts only — no decision, no guessing.

Tim: "determine the slack channel indicators, all the spreadsheets, etc and other signals you
have, and find us known Chinese brands that aren't listed as Chinese, and find us money they owe."

This is the OPERATOR-FACING WRAPPER. The logic lives in the installed package at
``cip.integration_mesh.sync.signal_harvest`` (review M9: the FAS scheduler imports executors from
the package, and ``scripts/`` is not importable from a wheel — so the harvester had to be lifted to
be schedulable). This wrapper only parses args, resolves the database URL, and prints the summary;
the module owns the SQL, the ``seen_in_*`` cache-maintenance pre-step, and the ``cip_sync_runs``
heartbeat. See the module docstring for what each signal means and why it is graded as it is.

The harvester writes SIGNALS, not verdicts. The verdict is derived in ``lens_ps_china_verdict``,
where CHINA WINS: one positive signal locks the brand. It is idempotent — a re-run inserts nothing
new (``ON CONFLICT DO NOTHING``).

Usage:
  DATABASE_URL=... python scripts/harvest_nationality_signals.py [--apply] [--tenant-id UUID]

  Without --apply this is a DRY RUN: the harvest + cache maintenance are rolled back and nothing is
  written to ps_nationality_signals / ps_brands. (The heartbeat still records that the run
  happened, with zero persisted rows.) Pass --apply to commit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine

from cip.integration_mesh.sync.signal_harvest import PS_TENANT, run_signal_harvest


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="commit; default is a dry run")
    ap.add_argument("--database-url", default=None)
    ap.add_argument(
        "--tenant-id", default=PS_TENANT, help="PS tenant UUID (defaults to Project Silk)"
    )
    args = ap.parse_args(argv)

    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = create_engine(url, pool_pre_ping=True)
    try:
        out = run_signal_harvest(engine, tenant_id=args.tenant_id, apply=args.apply)
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
