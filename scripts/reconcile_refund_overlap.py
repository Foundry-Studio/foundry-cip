# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Reconcile Stripe-native refund evidence against the negative is_ps_base lines (READ-ONLY).

AUTOMATIONS-PLAN §3, the reframed question (review C1): refund economics are ALREADY partially
inside "collected" as Wayward's negative paid ``is_ps_base`` reconciliation lines (777 lines /
−$10,543.11 at review time). So the danger is DOUBLE-SUBTRACTING. The right question is not "are
there refunds?" but **"which refund economics are NOT already represented as negative is_ps_base
lines?"**.

This report answers exactly that, per brand × invoice, bucketing each invoice that carries
Stripe-native refund/credit-note evidence:

  fully_covered      the paid negative is_ps_base lines on that invoice already account for
                     (>=) the Stripe-native refund + credit-note total. Nothing to add — it is
                     already inside collected.
  partially_covered  the negatives cover PART; the remainder (stripe_native − negatives) is a
                     candidate uncovered slice.
  uncovered          there is NO offsetting negative is_ps_base line at all — the whole
                     Stripe-native total is a candidate remainder.

Only a PROVEN-UNCOVERED remainder may EVER enter the money derivation later (as its own explicit
term, with the invariant suite re-baselined). This script writes NOTHING — it is the evidence a
human reads before any such decision. It runs for real in P4 once the evidence tables have data;
against an empty book it prints a clean empty report.

Note: the negative side is filtered to invoice_status='paid' to match the "collected" definition
(collected = paid usage), i.e. the negatives that are actually netted into the number today.

Usage:
  DATABASE_URL=... python scripts/reconcile_refund_overlap.py [--tenant UUID]
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

_RECONCILE = text("""
    WITH ev AS (
        SELECT invoice_id,
               sum(refund_total) AS refund_total,
               sum(cn_total)     AS cn_total
        FROM (
            SELECT invoice_id, amount AS refund_total, 0::numeric AS cn_total
            FROM ps_stripe_refunds
            WHERE tenant_id = CAST(:t AS uuid) AND status = 'succeeded'
              AND invoice_id IS NOT NULL
            UNION ALL
            SELECT invoice_id, 0::numeric, total
            FROM ps_stripe_credit_notes
            WHERE tenant_id = CAST(:t AS uuid) AND status = 'issued'
              AND invoice_id IS NOT NULL
        ) x
        GROUP BY invoice_id
    ),
    neg AS (
        SELECT stripe_invoice_id AS invoice_id, -sum(amount) AS neg_magnitude
        FROM ps_stripe_invoice_lines
        WHERE tenant_id = CAST(:t AS uuid) AND is_ps_base AND amount < 0
          AND invoice_status = 'paid'
        GROUP BY stripe_invoice_id
    )
    SELECT
        ev.invoice_id,
        i.wayward_brand_id                                   AS brand,
        ev.refund_total,
        ev.cn_total,
        (ev.refund_total + ev.cn_total)                      AS stripe_native,
        COALESCE(neg.neg_magnitude, 0)                       AS neg_magnitude,
        GREATEST(ev.refund_total + ev.cn_total
                 - COALESCE(neg.neg_magnitude, 0), 0)        AS uncovered_remainder,
        CASE
            WHEN COALESCE(neg.neg_magnitude, 0) >= ev.refund_total + ev.cn_total
                THEN 'fully_covered'
            WHEN COALESCE(neg.neg_magnitude, 0) > 0
                THEN 'partially_covered'
            ELSE 'uncovered'
        END                                                  AS bucket
    FROM ev
    LEFT JOIN ps_stripe_invoices i
           ON i.stripe_invoice_id = ev.invoice_id AND i.tenant_id = CAST(:t AS uuid)
    LEFT JOIN neg ON neg.invoice_id = ev.invoice_id
    ORDER BY uncovered_remainder DESC, stripe_native DESC
""")

_BUCKETS = ("fully_covered", "partially_covered", "uncovered")


def _d(v: object) -> Decimal:
    return Decimal(str(v or 0))


def run(conn, tenant: str) -> dict:
    conn.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": tenant})
    rows = conn.execute(_RECONCILE, {"t": tenant}).mappings().all()

    summary = {
        b: {"invoices": 0, "stripe_native": Decimal(0), "neg_magnitude": Decimal(0),
            "uncovered_remainder": Decimal(0)}
        for b in _BUCKETS
    }
    for r in rows:
        s = summary[r["bucket"]]
        s["invoices"] += 1
        s["stripe_native"] += _d(r["stripe_native"])
        s["neg_magnitude"] += _d(r["neg_magnitude"])
        s["uncovered_remainder"] += _d(r["uncovered_remainder"])

    total_native = sum((s["stripe_native"] for s in summary.values()), Decimal(0))
    total_uncovered = sum((s["uncovered_remainder"] for s in summary.values()), Decimal(0))
    return {"rows": rows, "summary": summary,
            "total_native": total_native, "total_uncovered": total_uncovered}


def _print_report(result: dict, tenant: str) -> None:
    rows = result["rows"]
    summary = result["summary"]
    print("=" * 78)
    print("REFUND-OVERLAP RECONCILIATION (read-only) — AUTOMATIONS-PLAN §3")
    print(f"tenant = {tenant}")
    print("=" * 78)
    if not rows:
        print("\nNo Stripe-native refund/credit-note evidence found — nothing to reconcile.")
        print("(Expected until the evidence tables are populated by ps_stripe_sync — P4.)")
        return

    print(f"\n{'bucket':<20}{'invoices':>10}{'stripe_native':>16}"
          f"{'covered_by_neg':>16}{'uncovered':>14}")
    print("-" * 76)
    for b in _BUCKETS:
        s = summary[b]
        print(f"{b:<20}{s['invoices']:>10}{_money(s['stripe_native']):>16}"
              f"{_money(s['neg_magnitude']):>16}{_money(s['uncovered_remainder']):>14}")
    print("-" * 76)
    print(f"{'TOTAL':<20}{len(rows):>10}{_money(result['total_native']):>16}"
          f"{'':>16}{_money(result['total_uncovered']):>14}")

    # The actionable list: invoices with a candidate uncovered remainder (top 25).
    candidates = [r for r in rows if _d(r["uncovered_remainder"]) > 0]
    if candidates:
        print(f"\nCandidate uncovered remainders (top {min(25, len(candidates))} of "
              f"{len(candidates)}) — refund economics NOT yet represented as negative lines:")
        print(f"\n  {'invoice':<28}{'brand':<38}{'bucket':<18}{'uncovered':>12}")
        print("  " + "-" * 94)
        for r in candidates[:25]:
            brand = str(r["brand"]) if r["brand"] else "(unknown invoice)"
            print(f"  {r['invoice_id']:<28}{brand:<38}{r['bucket']:<18}"
                  f"{_money(_d(r['uncovered_remainder'])):>12}")
    else:
        print("\nEvery Stripe-native refund is fully covered by an offsetting negative line — "
              "no uncovered remainder. Netting these tables in would double-subtract.")
    print(f"\nTOTAL candidate uncovered remainder = {_money(result['total_uncovered'])}. "
          "Only a PROVEN-uncovered slice may ever enter the derivation (§3).")


def _money(v: Decimal) -> str:
    return f"${v:,.2f}"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", default=PS_TENANT, help="tenant UUID (default: Project Silk)")
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
            result = run(conn, args.tenant)
    finally:
        engine.dispose()
    _print_report(result, args.tenant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
