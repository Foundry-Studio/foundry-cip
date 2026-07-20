# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Operator CLI for the Slack brand-connections ingest (#amazon-brand-connections).

The logic now lives in ``cip.integration_mesh.sync.slack_brand_connections`` — a
proper scheduled, heartbeated CIP sync (connector ``slack-brand-connections-v1``).
This is a thin CLI for manual / backfill runs. Writes ONLY observations
(facts, never a nationality decision — see the module docstring).

Usage:
  SLACK_USER_TOKEN=xoxp-... DATABASE_URL=postgresql+psycopg://... \
      python scripts/ingest_slack_brand_connections.py [--full]

  --full   page the entire channel history (default: incremental, since the newest
           observation already ingested).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine

from cip.integration_mesh.sync.slack_brand_connections import ingest, resolve_token

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--token", default=None)
    ap.add_argument("--tenant", default=PS_TENANT)
    args = ap.parse_args(argv)

    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    try:
        token = resolve_token(args.token)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    engine = create_engine(url, pool_pre_ping=True)
    try:
        summary = ingest(engine, token, args.tenant, full=args.full)
    finally:
        engine.dispose()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
