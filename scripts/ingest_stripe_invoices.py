# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Operator wrapper for the Stripe live sync (invoices + lines + refunds + credit notes).

THIN WRAPPER — no logic lives here. classify(), the invoice/line/customer upsert kernels,
the Events-API cursor, the advisory lock, and the EVIDENCE-ONLY refund/credit-note ingest all
live in ``cip.integration_mesh.sync.ps_stripe_sync`` (AUTOMATIONS-PLAN §3 / P2). The FAS
scheduler drives that module directly; this script stays for ad-hoc operator runs. The penny-
reconciled parsing is reused VERBATIM from the module — never re-derived here.

FLAG SEMANTICS CHANGED vs the pre-automation one-shot (documented per the P2 brief):
  --full        mode="full": customers + invoices + refunds + credit notes re-pulled (line
                pagination fixed), cursor re-seeded from a fresh /v1/events probe. As before.
  --since DATE  RETAINED for CLI compatibility, now forces --full and prints a warning. The
                live module is cursor-based (it polls /v1/events), NOT created-since-bounded; a
                full pull is the idempotent superset of any date-bounded backfill.
  (default)     mode="incremental": poll /v1/events since the stored cursor. NOTE the first
                incremental with no cursor auto-escalates to full inside the module.
  --dry-run     PLAN ONLY. The old --dry-run did a full trial with a DB rollback; the live
                module commits per-event by design (many short txns), so there is no rollback
                trial. --dry-run now prints the resolved plan and exits WITHOUT calling Stripe
                or writing anything.

Usage:
  STRIPE_API_KEY=rk_... DATABASE_URL=... \
      python scripts/ingest_stripe_invoices.py [--full] [--since YYYY-MM-DD] [--dry-run]
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
    ap.add_argument("--full", action="store_true", help="full refresh (all history)")
    ap.add_argument(
        "--since", default=None, help="DEPRECATED: retained for compat; now forces --full"
    )
    ap.add_argument("--dry-run", action="store_true", help="print the plan and exit; no writes")
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--tenant", default=PS_TENANT, help="tenant UUID (default: Project Silk)")
    args = ap.parse_args(argv)

    mode = "full" if (args.full or args.since) else "incremental"
    if args.since:
        print(
            f"WARNING: --since {args.since} is deprecated and now forces --full "
            f"(the live module is cursor-based, not date-bounded).",
            file=sys.stderr,
        )

    if args.dry_run:
        print(json.dumps({
            "plan": "would run ps_stripe_sync",
            "mode": mode,
            "tenant": args.tenant,
            "note": "dry-run: no Stripe calls, no DB writes",
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
        out = run_ps_stripe_sync(engine, tenant_id=args.tenant, mode=mode)
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
