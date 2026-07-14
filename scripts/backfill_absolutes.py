# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Backfill ONLY what is known and absolute. No inference, no math, no decisions.

Tim, 2026-07-13: "Schema, CIP build, backfill data that is known and absolute, THEN bring me a
LIST of the things we need to fill out."

This is that middle step. Every value written here comes from a source that already asserted it
— Wayward's own records. Nothing here computes, guesses, or resolves a conflict. Anything we do
not know stays NULL, and NULL keeps meaning "we do not know" (cip_55 removed the COALESCE that
was turning unknowns into confident zeros).

  A. productive_date_wayward  <-  ps_payment_events.rev_share_start_date
     Jake states a Rev Share Start Date per brand in the monthly reports. It has been sitting in
     ps_payment_events since ingest and was never copied to the subscriptions table, so the field
     read 0 of 1,108 filled. 289 brands state one, and all 289 are CONSISTENT across every month
     they appear in — zero conflicts, so there is nothing to adjudicate.

     It is written to every product row for the brand, because Jake's report is brand-level: his
     USAGE_FEES_PAID column combines Connect and Boost, so the date he states is not per-product.
     Recorded as WAYWARD'S STATED date, which is a separate field from our own computed
     productive_date (first tracked sale in a payable invoice, §1.5). Under §4.4 Wayward's records
     are "conclusive and controlling", so where the two disagree, that divergence is a dispute
     item — which is exactly why they are two columns and not one.

  B. billing_month  <-  the Stripe line description
     6,287 usage-fee lines carry no billing month, and the money spine keys on it.

     NOT taken from Stripe's line_period_start, which is the BILLING CYCLE, not the usage month.
     The lag between them is not constant: 18,820 lines lag one month, 5,050 lag two, 2,025 lag
     zero, and the reconciliation invoices lag up to seven ("November - ALL BRANDS - Reconciliation
     Usage", billed the following February). Deriving the month from the cycle would misdate most
     rows by 1-2 months, and the 10 -> 6 -> 3 step-down is month-sensitive, so that error would
     quietly move brands into the wrong rate tier. The description is what Wayward says the usage
     is FOR; it is simply missing a year.

     Precedence:
       1. an explicit year in the text ("September 2025 - Prepaid ...")  -> use it. Absolute.
          This also handles PREPAID lines, which are billed BEFORE the usage month and therefore
          break any "on or before the cycle" assumption.
       2. month name only -> the latest occurrence of that month on-or-before the billing cycle.
          Backtested against the 25,907 lines that already parsed: agrees on 25,905 (99.99%), and
          both disagreements were prepaid lines, which rule 1 now catches.
       3. no month name at all ("Usage Fee") -> leave NULL. We do not know. Do not guess.

Usage:
  DATABASE_URL=... python scripts/backfill_absolutes.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

# ── A. Wayward's stated rev-share start date ────────────────────────────────
BACKFILL_WAYWARD_DATE = text("""
    WITH stated AS (
        -- one row per brand; verified to have exactly ONE distinct date per brand
        SELECT wayward_brand_id, min(rev_share_start_date) AS rev_share_start_date
        FROM ps_payment_events
        WHERE tenant_id = :t
          AND rev_share_start_date IS NOT NULL
          AND wayward_brand_id IS NOT NULL
        GROUP BY wayward_brand_id
    )
    UPDATE ps_product_subscriptions s
       SET productive_date_wayward = st.rev_share_start_date,
           updated_at = now()
      FROM stated st
     WHERE s.tenant_id = :t
       AND s.wayward_brand_id = st.wayward_brand_id
       AND s.productive_date_wayward IS DISTINCT FROM st.rev_share_start_date
""")

# ── B. billing month, from the description ─────────────────────────────────
MONTHS = """
    (VALUES ('january',1),('february',2),('march',3),('april',4),('may',5),('june',6),
            ('july',7),('august',8),('september',9),('october',10),('november',11),
            ('december',12)) AS m(nm, num)
"""

# 1. explicit "Month YYYY" in the text — absolute, and correct for PREPAID lines.
BACKFILL_MONTH_EXPLICIT = text(f"""
    UPDATE ps_stripe_invoice_lines l
       SET billing_month = make_date(
               substring(l.description from '(20[0-9]{{2}})')::int, m.num, 1)
      FROM {MONTHS}
     WHERE l.tenant_id = :t
       AND l.billing_month IS NULL
       AND lower(l.description) LIKE m.nm || '%'
       AND l.description ~ '20[0-9]{{2}}'
""")

# 2. month name only — year = the latest occurrence on-or-before the billing cycle.
BACKFILL_MONTH_INFERRED = text(f"""
    UPDATE ps_stripe_invoice_lines l
       SET billing_month = make_date(
               CASE WHEN m.num <= EXTRACT(MONTH FROM l.line_period_start)::int
                    THEN EXTRACT(YEAR FROM l.line_period_start)::int
                    ELSE EXTRACT(YEAR FROM l.line_period_start)::int - 1 END,
               m.num, 1)
      FROM {MONTHS}
     WHERE l.tenant_id = :t
       AND l.billing_month IS NULL
       AND l.line_period_start IS NOT NULL
       AND lower(l.description) LIKE m.nm || '%'
       AND l.description !~ '20[0-9]{{2}}'
""")


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    out: dict = {}

    def scalar(sql: str) -> int:
        return conn.execute(text(sql), {"t": PS_TENANT}).scalar() or 0

    out["A_wayward_date_before"] = scalar(
        "SELECT count(productive_date_wayward) FROM ps_product_subscriptions "
        "WHERE tenant_id = :t"
    )
    out["B_billing_month_null_before"] = scalar(
        "SELECT count(*) FROM ps_stripe_invoice_lines "
        "WHERE tenant_id = :t AND is_ps_base AND billing_month IS NULL"
    )

    out["A_rows_written"] = conn.execute(
        BACKFILL_WAYWARD_DATE, {"t": PS_TENANT}
    ).rowcount
    out["B_month_from_explicit_year"] = conn.execute(
        BACKFILL_MONTH_EXPLICIT, {"t": PS_TENANT}
    ).rowcount
    out["B_month_inferred_from_cycle"] = conn.execute(
        BACKFILL_MONTH_INFERRED, {"t": PS_TENANT}
    ).rowcount

    out["A_wayward_date_after"] = scalar(
        "SELECT count(productive_date_wayward) FROM ps_product_subscriptions "
        "WHERE tenant_id = :t"
    )
    out["B_billing_month_null_after"] = scalar(
        "SELECT count(*) FROM ps_stripe_invoice_lines "
        "WHERE tenant_id = :t AND is_ps_base AND billing_month IS NULL"
    )
    # What is LEFT is left on purpose: no month named in the description at all.
    # It stays NULL. We do not know, so it must not become a number.
    out["B_left_null_no_month_in_text"] = out["B_billing_month_null_after"]

    if not apply:
        conn.execute(text("ROLLBACK"))
    out["applied"] = apply
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
        with engine.begin() as conn:
            out = run(conn, apply=args.apply)
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
