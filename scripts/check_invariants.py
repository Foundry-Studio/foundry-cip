# foundry: kind=script domain=client-intelligence-platform
"""Run the Project Silk invariants. The manual entry point; the scheduler uses the module.

    python scripts/check_invariants.py

Exit 0 = every invariant holds. Exit 1 = a number somewhere is lying.

These are the fifteen defects four adversarial audits found on 2026-07-13, turned into tripwires.
Not one of them raised an error at the time — they produced confident, WRONG numbers, and a human
found them by reading SQL at one in the morning. That is the job this script exists to take over.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine

from cip.integration_mesh.ps_invariants import (
    INVARIANTS,
    InvariantViolationError,
    run_ps_invariants,
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            try:
                out = run_ps_invariants(conn)
            except InvariantViolationError as exc:
                print("\n*** INVARIANTS FAILED ***\n")
                print(str(exc))
                print("\nA violated invariant is not a warning. It means a number is lying.")
                return 1
    finally:
        engine.dispose()

    print(f"ALL {out['checked']} INVARIANTS HOLD\n")
    for inv in INVARIANTS:
        print(f"  OK  {inv.key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
