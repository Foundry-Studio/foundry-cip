# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Compute the money spine: ps_monthly_earnings, per brand x product x month.

Runs the whole chain in one place, so the arithmetic exists exactly once:

  1. PRODUCTIVE DATE, per brand x PRODUCT — the earliest billing_month carrying a USAGE-FEE
     line in Stripe. Contract §1.5 defines Productive as "the date of the first tracked sale
     ... included in a payable invoice", so Stripe is not a proxy for this — it IS it.
     Where we can only see the month (which is all Stripe's descriptions give us), Tim's
     rule applies: use the 1st of that month.

  2. THE RATE that applied in each month, from that product's own clock (§3.1):
        months 1-12 -> 10%,  13-18 -> 6%,  19+ -> 3%
     Connect and Boost step down INDEPENDENTLY. Boost launched later, so a brand is
     routinely mid-window on Connect while its Boost clock has barely started.

  3. THE PARTNER split — X% of the SAME usage-fee base, out of our 10, expiring 12 months
     from the same anchor.

  4. WHAT WAYWARD ACTUALLY PAID US (Jake's monthly reports), matched by brand x month.

  5. VARIANCE = what we should have been paid - what we were. The claim. (Generated in the
     DB, so it can never drift from its inputs.)

WHAT THIS DELIBERATELY DOES NOT DO
  - It does not compute anything from usage_BILLED. We are paid on cash ACTUALLY RECEIVED
    (§4.1(b)). Outstanding is pipeline, and treating it as owed would invent revenue.
  - It does not use COMMISSION fees. Those are creator pass-through, ~4x larger than the
    usage fee, and are NOT our base.

Usage:
  DATABASE_URL=... python scripts/compute_monthly_earnings.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

# 1. Productive date per brand x product, straight from Stripe.
PRODUCTIVE = text("""
    INSERT INTO ps_product_subscriptions (
        tenant_id, client_id, product_id,
        productive_date, productive_date_source, productive_date_confidence,
        first_billed_month, productive_date_note
    )
    SELECT :t, l.client_id, l.product_id,
           min(l.billing_month),
           'stripe', 'confirmed',
           min(l.billing_month),
           'Earliest Stripe billing month carrying a USAGE-FEE line for this brand x '
           || 'product. Contract §1.5: the first tracked sale included in a payable '
           || 'invoice. Stripe gives us the MONTH, so per Tim the 1st of it governs.'
    FROM ps_stripe_invoice_lines l
    WHERE l.tenant_id = :t
      AND l.is_ps_base
      AND l.client_id IS NOT NULL
      AND l.product_id IS NOT NULL
      AND l.billing_month IS NOT NULL
      AND l.amount > 0                 -- a negative reconciliation line is not a first sale
    GROUP BY l.client_id, l.product_id
    ON CONFLICT (tenant_id, client_id, product_id) DO UPDATE SET
        productive_date = LEAST(
            ps_product_subscriptions.productive_date, EXCLUDED.productive_date
        ),
        productive_date_source = 'stripe',
        productive_date_confidence = 'confirmed',
        first_billed_month = EXCLUDED.first_billed_month,
        productive_date_note = EXCLUDED.productive_date_note,
        updated_at = now()
""")

# 5. The spine.
EARNINGS = text("""
    INSERT INTO ps_monthly_earnings (
        tenant_id, client_id, wayward_brand_id, brand_name, product_id, period_month,
        usage_billed, usage_collected,
        ps_rate_pct, months_since_productive,
        partner_id, partner_rate_pct,
        ps_actually_paid,
        eligibility, excluded_bucket, is_chinese
    )
    WITH usage AS (
        -- The base: USAGE fees only, per brand x product x month.
        -- GRAIN MUST BE (brand, product, month) — NOT client_id. A single
        -- wayward_brand_id can resolve to more than one cip_clients row, and grouping by
        -- client_id produced two rows for the same brand/product/month, which the target's
        -- UNIQUE key then rejected. The brand id is the real identity here.
        SELECT l.wayward_brand_id, l.product_id, l.billing_month,
               max(l.client_id::text)::uuid                         AS client_id,
               sum(l.amount)                                        AS billed,
               sum(l.amount) FILTER (WHERE l.invoice_status='paid') AS collected
        FROM ps_stripe_invoice_lines l
        WHERE l.tenant_id = :t AND l.is_ps_base
          AND l.billing_month IS NOT NULL AND l.product_id IS NOT NULL
          AND l.wayward_brand_id IS NOT NULL
        GROUP BY 1,2,3
    ),
    clock AS (
        SELECT client_id, product_id, productive_date
        FROM ps_product_subscriptions
        WHERE tenant_id = :t AND productive_date IS NOT NULL
    ),
    partner AS (
        -- One partner per brand x product. deal_type='flat_fee' earns them NOTHING
        -- ongoing, so their rate is zero regardless of any partner_rate on the row.
        SELECT DISTINCT ON (client_id, product_id)
               client_id, product_id, partner_of_record, deal_type, partner_rate
        FROM ps_partner_credit
        WHERE tenant_id = :t
        ORDER BY client_id, product_id, determined_at DESC NULLS LAST, created_at DESC
    ),
    paid AS (
        -- What Jake actually paid us, by brand x month. His reports carry no product
        -- split, so this lands on the brand's CONNECT row (the D3 gap) — recorded, not hidden.
        SELECT wayward_brand_id,
               date_trunc('month', payment_date)::date AS m,
               sum(rev_share_stated)                   AS paid
        FROM ps_payment_events
        WHERE tenant_id = :t AND wayward_brand_id IS NOT NULL
        GROUP BY 1,2
    )
    SELECT
        :t,
        u.client_id,
        u.wayward_brand_id,
        el.brand_name,
        u.product_id,
        u.billing_month,
        u.billed,
        COALESCE(u.collected, 0),

        -- The tier that applied in THAT month, on THAT product's own clock.
        CASE
            WHEN c.productive_date IS NULL THEN NULL
            WHEN u.billing_month < c.productive_date THEN NULL   -- before it went productive
            WHEN u.billing_month < c.productive_date + 365 THEN 10
            WHEN u.billing_month < c.productive_date + 365 + 183 THEN 6
            ELSE 3
        END,
        CASE WHEN c.productive_date IS NULL THEN NULL
             ELSE (u.billing_month - c.productive_date) / 30 END,

        p.partner_of_record,
        -- Partner earns only while inside the 12-month window, and never on a flat-fee deal.
        CASE
            WHEN p.partner_of_record IS NULL
              OR p.partner_of_record = 'unassigned'          THEN 0
            WHEN p.deal_type = 'flat_fee'                    THEN 0
            WHEN c.productive_date IS NULL                   THEN 0
            WHEN u.billing_month >= c.productive_date + 365  THEN 0   -- partner rolled off
            ELSE COALESCE(p.partner_rate, 0)
        END,

        COALESCE(pd.paid, 0),

        el.eligibility,
        el.excluded_bucket,
        el.is_chinese
    FROM usage u
    LEFT JOIN clock  c  ON c.client_id = u.client_id AND c.product_id = u.product_id
    LEFT JOIN partner p ON p.client_id = u.client_id AND p.product_id = u.product_id
    -- lens_ps_eligibility is one row per brand, but guard the join anyway: a fan-out here
    -- would duplicate money rows, and a duplicated brand double-counts revenue.
    LEFT JOIN LATERAL (
        SELECT brand_name, eligibility, excluded_bucket, is_chinese
        FROM lens_ps_eligibility x
        WHERE x.wayward_brand_id = u.wayward_brand_id
        LIMIT 1
    ) el ON true
    LEFT JOIN paid pd ON pd.wayward_brand_id = u.wayward_brand_id
                     AND pd.m = u.billing_month
                     AND u.product_id = 'connect'   -- Jake's reports have no product split
    ON CONFLICT (tenant_id, wayward_brand_id, product_id, period_month) DO UPDATE SET
        usage_billed = EXCLUDED.usage_billed,
        usage_collected = EXCLUDED.usage_collected,
        ps_rate_pct = EXCLUDED.ps_rate_pct,
        months_since_productive = EXCLUDED.months_since_productive,
        partner_id = EXCLUDED.partner_id,
        partner_rate_pct = EXCLUDED.partner_rate_pct,
        ps_actually_paid = EXCLUDED.ps_actually_paid,
        eligibility = EXCLUDED.eligibility,
        excluded_bucket = EXCLUDED.excluded_bucket,
        is_chinese = EXCLUDED.is_chinese,
        computed_at = now()
""")


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    out: dict = {}

    r = conn.execute(PRODUCTIVE, {"t": PS_TENANT})
    out["productive_dates_set"] = r.rowcount

    r = conn.execute(EARNINGS, {"t": PS_TENANT})
    out["earnings_rows"] = r.rowcount

    out["summary"] = [
        dict(zip(
            ("product", "months", "brands", "usage_billed", "usage_collected",
             "ps_gross", "partner_owed", "ps_net", "actually_paid", "variance"),
            row, strict=False,
        ))
        for row in conn.execute(text("""
            SELECT product_id,
                   count(DISTINCT period_month),
                   count(DISTINCT wayward_brand_id),
                   round(sum(usage_billed),2),
                   round(sum(usage_collected),2),
                   round(sum(ps_gross_owed),2),
                   round(sum(partner_owed),2),
                   round(sum(ps_net_owed),2),
                   round(sum(ps_actually_paid),2),
                   round(sum(variance),2)
            FROM ps_monthly_earnings WHERE tenant_id=:t
            GROUP BY 1 ORDER BY 4 DESC
        """), {"t": PS_TENANT}).fetchall()
    ]

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
