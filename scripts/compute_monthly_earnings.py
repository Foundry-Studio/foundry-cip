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
#
# KEYED ON wayward_brand_id, NOT client_id. This is the whole fix. client_id is the cip_clients
# surrogate and covers only ~65% of brands, so keying the clock on it meant a brand outside that
# set could not hold a productive date, could not be assigned a rate, and priced to nothing. The
# arithmetic was never wrong; the brand simply had no name the schema could use. Stripe now
# carries wayward_brand_id on 99.9% of usage-fee lines, so the clock finally reaches every brand
# that has ever been billed.
PRODUCTIVE = text("""
    INSERT INTO ps_product_subscriptions (
        tenant_id, wayward_brand_id, client_id, product_id,
        productive_date, productive_date_source, productive_date_confidence,
        first_billed_month, productive_date_note
    )
    SELECT :t, l.wayward_brand_id,
           max(l.client_id::text)::uuid,     -- convenience join only; never the identity
           l.product_id,
           min(l.billing_month),
           'stripe', 'confirmed',
           min(l.billing_month),
           'Earliest Stripe billing month carrying a USAGE-FEE line for this brand x '
           || 'product. Contract §1.5: the first tracked sale included in a payable '
           || 'invoice. Stripe gives us the MONTH, so per Tim the 1st of it governs.'
    FROM ps_stripe_invoice_lines l
    WHERE l.tenant_id = :t
      AND l.is_ps_base
      AND l.wayward_brand_id IS NOT NULL
      AND l.product_id IS NOT NULL
      AND l.billing_month IS NOT NULL
      AND l.amount > 0                 -- a negative reconciliation line is not a first sale
    GROUP BY l.wayward_brand_id, l.product_id
    ON CONFLICT (tenant_id, wayward_brand_id, product_id)
        WHERE wayward_brand_id IS NOT NULL
    DO UPDATE SET
        productive_date = LEAST(
            ps_product_subscriptions.productive_date, EXCLUDED.productive_date
        ),
        client_id = COALESCE(ps_product_subscriptions.client_id, EXCLUDED.client_id),
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
        usage_billed, usage_collected, usage_voided,
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
               -- BILLED = LIVE invoices only. A VOIDED invoice was cancelled — never billed to
               -- anybody, never owed, never collectable. Counting voids inflated billed by
               -- $561,209 and, on 73 brand-months, dragged BILLED below COLLECTED (Zyllion:
               -- billed -$57.78 against collected $470.80). A brand cannot pay us more than we
               -- ever invoiced it.
               COALESCE(sum(l.amount) FILTER (
                    WHERE l.invoice_status IN ('paid','open')), 0)  AS billed,
               -- COLLECTED = cash actually received. §3.1 pays PS on "Usage Fees actually
               -- received" — this, and ONLY this, is the base for the 10/6/3%.
               sum(l.amount) FILTER (WHERE l.invoice_status='paid') AS collected,
               -- kept visible rather than folded away: a spike in voids is how a brand disputes
               -- its bill, which makes it a leading indicator of revenue about to vanish.
               COALESCE(sum(l.amount) FILTER (
                    WHERE l.invoice_status IN ('void','uncollectible')), 0) AS voided
        FROM ps_stripe_invoice_lines l
        WHERE l.tenant_id = :t AND l.is_ps_base
          AND l.billing_month IS NOT NULL AND l.product_id IS NOT NULL
          AND l.wayward_brand_id IS NOT NULL
        GROUP BY 1,2,3
    ),
    clock AS (
        -- Keyed on the BRAND, not the client surrogate. See PRODUCTIVE above.
        SELECT wayward_brand_id, product_id, productive_date
        FROM ps_product_subscriptions
        WHERE tenant_id = :t
          AND productive_date IS NOT NULL
          AND wayward_brand_id IS NOT NULL
    ),
    partner AS (
        -- One partner per brand x product. deal_type='flat_fee' earns them NOTHING
        -- ongoing, so their rate is zero regardless of any partner_rate on the row.
        SELECT DISTINCT ON (wayward_brand_id, product_id)
               wayward_brand_id, product_id, partner_of_record, deal_type, partner_rate
        FROM ps_partner_credit
        WHERE tenant_id = :t AND wayward_brand_id IS NOT NULL
        ORDER BY wayward_brand_id, product_id, determined_at DESC NULLS LAST, created_at DESC
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
        -- The eligibility lens only knows names Wayward's OWN feed supplied. Brands that reached
        -- us only through Stripe have a name in ps_brands and NULL here — which is why the single
        -- largest claim in the book once displayed as "?" (it was Apolosign, a HK company).
        COALESCE(el.brand_name, (SELECT brand_name FROM ps_brands b
                                  WHERE b.wayward_brand_id = u.wayward_brand_id)),
        u.product_id,
        u.billing_month,
        u.billed,
        COALESCE(u.collected, 0),
        u.voided,

        -- The tier that applied in THAT month, on THAT product's own clock.
        --
        -- CALENDAR MONTHS, not day counts. The 6->3 step used `+ 365 + 183` = 548 days, but
        -- eighteen calendar months from the 1st is 546-549 days depending on the start month.
        -- When it lands on 546 or 547, month NINETEEN falls inside the boundary and keeps 6%:
        -- 46 brands were booked at 6% while owed 3%, overstating the claim by $217.32. It is
        -- systematic and it grows — every brand crosses month 19 exactly once.
        CASE
            WHEN c.productive_date IS NULL THEN NULL
            WHEN u.billing_month < c.productive_date THEN NULL   -- before it went productive
            WHEN u.billing_month < c.productive_date + INTERVAL '12 months' THEN 10
            WHEN u.billing_month < c.productive_date + INTERVAL '18 months' THEN 6
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
            -- Calendar months, matching the 10->6 step EXACTLY. If the partner's expiry and
            -- our own step-down use different arithmetic they drift apart, and our NET dips
            -- below 6% for whatever month falls in the gap.
            WHEN u.billing_month >= c.productive_date + INTERVAL '12 months' THEN 0
            ELSE COALESCE(p.partner_rate, 0)
        END,

        COALESCE(pd.paid, 0),

        el.eligibility,
        el.excluded_bucket,

        -- *** is_chinese HAS EXACTLY ONE HOME, AND IT IS lens_ps_china_verdict. ***
        -- It used to come from lens_ps_eligibility, which carries a LEGACY nationality signal.
        -- The two disagreed on 498 brands and $48,652.77 of gross owed. Six of them said FALSE
        -- while the verdict said china — every one carrying a +86 phone or sitting on the frozen
        -- exclusion list (COOLIFE, Heyvalue, Gelrova, Neathova, Jarkyfine, MOSDART). Two
        -- authoritative-looking answers to "is this brand Chinese", on the money table itself.
        --
        -- NULL where we do not know. `probable` and `unknown` are NOT false — that is the cip_72
        -- lesson, and treating "we have not decided" as "not Chinese" silently drops brands out of
        -- the book. NULL propagates; it does not lie.
        CASE cv.verdict
            WHEN 'china'     THEN true
            WHEN 'not_china' THEN false
            ELSE NULL                    -- 'probable' / 'unknown' / no row
        END
    FROM usage u
    LEFT JOIN clock  c  ON c.wayward_brand_id = u.wayward_brand_id
                       AND c.product_id = u.product_id
    LEFT JOIN partner p ON p.wayward_brand_id = u.wayward_brand_id
                       AND p.product_id = u.product_id
    -- lens_ps_eligibility is one row per brand, but guard the join anyway: a fan-out here
    -- would duplicate money rows, and a duplicated brand double-counts revenue.
    LEFT JOIN LATERAL (
        SELECT brand_name, eligibility, excluded_bucket
        FROM lens_ps_eligibility x
        WHERE x.wayward_brand_id = u.wayward_brand_id
        LIMIT 1
    ) el ON true
    -- the ONLY source of nationality. Same fan-out guard, same reason.
    LEFT JOIN LATERAL (
        SELECT verdict
        FROM lens_ps_china_verdict y
        WHERE y.wayward_brand_id = u.wayward_brand_id
        LIMIT 1
    ) cv ON true
    -- Jake's reports carry no product split, so the payment must land on exactly ONE row per
    -- brand-month or it double-counts. It used to require a CONNECT row, and silently DROPPED
    -- $4,012.06 of cash we have already received when the month existed only as Boost, or not at
    -- all. Dropping received cash inflates the claim 1:1 — the one direction §4.4 punishes.
    -- Now: land it on the brand-month's alphabetically-first product, which always exists.
    LEFT JOIN paid pd ON pd.wayward_brand_id = u.wayward_brand_id
                     AND pd.m = u.billing_month
                     AND u.product_id = (
                          SELECT min(l2.product_id) FROM ps_stripe_invoice_lines l2
                           WHERE l2.wayward_brand_id = u.wayward_brand_id
                             AND l2.billing_month = u.billing_month
                             AND l2.is_ps_base AND l2.product_id IS NOT NULL)
    ON CONFLICT (tenant_id, wayward_brand_id, product_id, period_month) DO UPDATE SET
        -- brand_name was missing from this list, so rows written before the name was known kept
        -- their NULL forever. The single largest claim in the book displayed as "?" because of it.
        brand_name = COALESCE(EXCLUDED.brand_name, ps_monthly_earnings.brand_name),
        usage_billed = EXCLUDED.usage_billed,
        usage_collected = EXCLUDED.usage_collected,
        usage_voided = EXCLUDED.usage_voided,
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


# 0. The spine is DERIVED. It must be a pure function of its source — which means it has to be
#    able to SHRINK, not just grow.
#
#    This script only ever INSERTed and UPDATEd. So when cip_72 correctly RETRACTED 829 usage-fee
#    lines whose brand identity had been resolved from an ambiguous email (a coin flip — 531
#    emails map to more than one brand), the source rows lost their brand id and the spine kept
#    192 ORPHANED rows carrying $32,693 of phantom billing. Nothing errored. The invariant suite
#    caught it; a human had not.
#
#    A derived table that cannot shrink is not derived. It is a cache with no eviction.
PRUNE_ORPHANS = text("""
    DELETE FROM ps_monthly_earnings e
     WHERE e.tenant_id = :t
       AND NOT EXISTS (
            SELECT 1 FROM ps_stripe_invoice_lines l
             WHERE l.tenant_id = e.tenant_id
               AND l.wayward_brand_id = e.wayward_brand_id
               AND l.product_id       = e.product_id
               AND l.billing_month    = e.period_month
               AND l.is_ps_base
       )
""")


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    out: dict = {}

    out["orphan_rows_pruned"] = conn.execute(PRUNE_ORPHANS, {"t": PS_TENANT}).rowcount

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
