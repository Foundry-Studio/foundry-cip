# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Operator wrapper — Stripe CUSTOMERS are now synced as part of the unified live sync.

THIN WRAPPER — no logic lives here. Customer ingestion (metadata.brandId + the
description-field brand recovery + the ps_brands teach + identity propagation onto
invoices/lines) is no longer a standalone pass: it is folded into
``cip.integration_mesh.sync.ps_stripe_sync`` (AUTOMATIONS-PLAN §3 / P2). ``customer.*``
events hydrate + upsert customers incrementally, and ``mode="full"`` re-pulls every
customer. The ``shape()`` identity kernel is reused VERBATIM from the module. This script
stays for operators who reach for it by name; it triggers a FULL sync (which includes the
customer pass), preserving the historical "ingest all customers" behaviour as a superset.

FLAG SEMANTICS CHANGED vs the pre-automation script:
  --apply   run the full sync (writes). Without it → PLAN ONLY (prints + exits, no writes),
            preserving the old apply-gate. The old default did a customers-only trial with a
            DB rollback; the live module has no rollback trial, so plan mode is print-only.

Usage:
  STRIPE_API_KEY=rk_... DATABASE_URL=... python scripts/ingest_stripe_customers.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine

from cip.integration_mesh.sync.ps_stripe_sync import PS_TENANT, run_ps_stripe_sync


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--apply", action="store_true",
        help="run the full sync (writes); without it, plan only (no writes)",
    )
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--tenant", default=PS_TENANT, help="tenant UUID (default: Project Silk)")
    args = ap.parse_args(argv)

    if not args.apply:
        print(json.dumps({
            "plan": "would run ps_stripe_sync mode=full (includes the customer pass)",
            "tenant": args.tenant,
            "note": "pass --apply to execute; no writes in plan mode",
        }, indent=2))
        return 0

    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = create_engine(url, pool_pre_ping=True)
    try:
        out = run_ps_stripe_sync(engine, tenant_id=args.tenant, mode="full")
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
