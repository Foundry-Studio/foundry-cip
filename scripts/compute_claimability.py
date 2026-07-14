# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Detect reactivations, then decide claimability per brand x product x MONTH.

Tim's rulings (2026-07-13; Ali confirmed verbally, ratification deliberately deferred):
  1. BOOST is ours on every Chinese brand — including Excluded / Eric / Lysoatur ones. Boost is
     a net-new product and does not inherit a brand's excluded status.
  2. REACTIVATION wins a brand back, regardless of who referred it, but ONLY when
       (a) the reactivation happened AFTER 2025-11-01 — when PS restarted the China push. We
           claim the ones we caused, not the ones that happened anyway; and
       (b) the brand is FLAT-FEE. Never a brand where another partner still earns an ongoing
           10% — you cannot win back a brand somebody else is being paid on.

CLAIM RULES, in precedence order. Every row gets exactly one, and says which.

    boost_all_brands        product = boost, brand is Chinese.       (ruling 1)
    rule_a_post_takeover    not excluded, onboarded > 2025-11-18.
    rule_b_december         not excluded, month >= 2025-12-01.
    reactivation_flat_fee   flat-fee bucket, reactivated after 2025-11-01, month >= that. (ruling 2)
    not_claimable_*         and WHY.

REACTIVATION IS DETECTED FROM BILLING, NOT ASSERTED
  A gap of 3+ months with no usage-fee line on that product = 90 days dark. The first month it
  bills again is the reactivation. Stripe billing months are the only continuous activity signal
  we hold — Jake has not sent per-brand sales, so "no invoice" is the closest thing to "no sale"
  we can observe. That is a real limitation and it is logged as an open question, not papered over.

Usage:
  DATABASE_URL=... python scripts/compute_claimability.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
PUSH_RESTART = "2025-11-01"
FREEZE = "2025-11-18"
RULE_B = "2025-12-01"
FLAT_FEE_BUCKET = "Eric Flat Fee Brands"

# 1. Reactivation: first billing month after a 90+ day (3 month) gap, per brand x product.
REACTIVATION = text(f"""
    WITH months AS (
        SELECT DISTINCT wayward_brand_id, product_id, billing_month
        FROM ps_stripe_invoice_lines
        WHERE tenant_id = :t AND is_ps_base AND amount > 0
          AND billing_month IS NOT NULL
          AND wayward_brand_id IS NOT NULL AND product_id IS NOT NULL
    ),
    gaps AS (
        SELECT wayward_brand_id, product_id, billing_month,
               lag(billing_month) OVER (PARTITION BY wayward_brand_id, product_id
                                        ORDER BY billing_month) AS prev
        FROM months
    ),
    react AS (
        SELECT wayward_brand_id, product_id, min(billing_month) AS reactivated_at
        FROM gaps
        WHERE prev IS NOT NULL
          AND billing_month >= prev + INTERVAL '3 months'   -- 90+ days dark
        GROUP BY 1, 2
    )
    UPDATE ps_product_subscriptions s
       SET reactivated_at = r.reactivated_at,
           reactivation_qualifies = (
                r.reactivated_at >= DATE '{PUSH_RESTART}'
                AND x.bucket = '{FLAT_FEE_BUCKET}'
           ),
           updated_at = now()
      FROM react r
      LEFT JOIN ps_excluded_brands x ON x.wayward_brand_id = r.wayward_brand_id
     WHERE s.tenant_id = :t
       AND s.wayward_brand_id = r.wayward_brand_id
       AND s.product_id = r.product_id
""")

# 2. Claimability, per brand x product x month.
#
# Nationality is THREE-VALUED, not two. "We have not established where this brand is from" is
# NOT "this brand is not Chinese". Collapsing them writes off 1,044 brands and ~$141k of PS
# commission as a settled negative — the same COALESCE-to-zero failure cip_55 removed from the
# rate, reappearing one level up on the flag that gates every claim.
CLAIM = text(f"""
    WITH ctry AS (
        -- ISO-2 only. One brand's `country` is the string "Impersonate Account button  View
        -- Contact in Intercom button *Hubspot Sync Information*" — Slack-parser debris scraped
        -- off the page, not a country. It carries $11,524 of collected usage, and treating it
        -- as a foreign country would silently disqualify the brand.
        SELECT wayward_brand_id,
               max(value) FILTER (WHERE value ~ '^[A-Z]{{2}}$') AS country
        FROM ps_brand_observations
        WHERE tenant_id = :t AND field = 'country'
        GROUP BY wayward_brand_id
    ),
    elig AS (
        SELECT g.wayward_brand_id,
               g.is_excluded,
               g.onboarded,
               CASE
                 WHEN g.nationality_class IN ('chinese_confirmed','chinese_suspected')
                   OR c.country = 'CN'                THEN 'yes'
                 WHEN c.country IS NOT NULL           THEN 'no'      -- Wayward states a country
                 WHEN g.nationality_class IS NOT NULL
                  AND g.nationality_class <> 'unknown' THEN 'no'
                 ELSE 'unknown'                                       -- never established
               END AS chinese
        FROM lens_ps_eligibility g
        LEFT JOIN ctry c ON c.wayward_brand_id = g.wayward_brand_id
    )
    UPDATE ps_monthly_earnings e
       SET claim_basis = CASE
            -- Unknown is a QUEUE, not a verdict. It must never read as a denial.
            WHEN g.chinese = 'unknown'                 THEN 'unknown_nationality'
            WHEN g.chinese = 'no'                      THEN 'not_claimable_not_chinese'
            -- Ruling 1: Boost is ours on every Chinese brand, excluded or not.
            WHEN e.product_id = 'boosted'              THEN 'boost_all_brands'
            -- Ruling 2: won back by reactivation (flat-fee only, post-2025-11-01 only).
            WHEN EXISTS (SELECT 1 FROM ps_product_subscriptions s
                          WHERE s.tenant_id = e.tenant_id
                            AND s.wayward_brand_id = e.wayward_brand_id
                            AND s.product_id = e.product_id
                            AND s.reactivation_qualifies
                            AND e.period_month >= s.reactivated_at)
                                                       THEN 'reactivation_flat_fee'
            -- Excluded on Connect and never won back: we earn nothing.
            WHEN COALESCE(g.is_excluded, false)        THEN 'not_claimable_excluded'
            -- Rule A: onboarded after the freeze. Ours outright.
            WHEN g.onboarded > DATE '{FREEZE}'         THEN 'rule_a_post_takeover'
            -- Rule B: onboarded before it, but billing in our era. We run the CS.
            WHEN e.period_month >= DATE '{RULE_B}'     THEN 'rule_b_december'
            ELSE 'not_claimable_pre_takeover'
           END,
           is_claimable = CASE
            WHEN g.chinese <> 'yes'                    THEN false
            WHEN e.product_id = 'boosted'              THEN true
            WHEN EXISTS (SELECT 1 FROM ps_product_subscriptions s
                          WHERE s.tenant_id = e.tenant_id
                            AND s.wayward_brand_id = e.wayward_brand_id
                            AND s.product_id = e.product_id
                            AND s.reactivation_qualifies
                            AND e.period_month >= s.reactivated_at)
                                                       THEN true
            WHEN COALESCE(g.is_excluded, false)        THEN false
            WHEN g.onboarded > DATE '{FREEZE}'         THEN true
            WHEN e.period_month >= DATE '{RULE_B}'     THEN true
            ELSE false
           END,
           computed_at = now()
      FROM elig g
     WHERE e.tenant_id = :t
       AND g.wayward_brand_id = e.wayward_brand_id
""")


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    out: dict = {}
    out["reactivations_detected"] = conn.execute(REACTIVATION, {"t": PS_TENANT}).rowcount
    out["earnings_rows_classified"] = conn.execute(CLAIM, {"t": PS_TENANT}).rowcount

    out["reactivation_qualifying"] = conn.execute(
        text(
            "SELECT count(*) FROM ps_product_subscriptions "
            "WHERE tenant_id = :t AND reactivation_qualifies"
        ),
        {"t": PS_TENANT},
    ).scalar()

    out["by_basis"] = [
        dict(zip(
            ("claim_basis", "product", "brands", "months", "collected", "owed", "paid",
             "shortfall"),
            r, strict=False,
        ))
        for r in conn.execute(text("""
            SELECT claim_basis, product_id,
                   count(DISTINCT wayward_brand_id), count(*),
                   round(sum(usage_collected), 2),
                   round(sum(ps_gross_owed), 2),
                   round(sum(ps_actually_paid), 2),
                   round(sum(ps_gross_owed) - sum(ps_actually_paid), 2)
            FROM ps_monthly_earnings WHERE tenant_id = :t
            GROUP BY 1, 2 ORDER BY 8 DESC NULLS LAST
        """), {"t": PS_TENANT}).fetchall()
    ]
    out["headline"] = [
        dict(zip(("metric", "value"), r, strict=False))
        for r in conn.execute(text("""
            SELECT 'CLAIMABLE: usage collected', round(sum(usage_collected), 2)::text
              FROM ps_monthly_earnings WHERE tenant_id = :t AND is_claimable
            UNION ALL SELECT 'CLAIMABLE: PS owed (gross)', round(sum(ps_gross_owed), 2)::text
              FROM ps_monthly_earnings WHERE tenant_id = :t AND is_claimable
            UNION ALL SELECT 'CLAIMABLE: PS actually paid', round(sum(ps_actually_paid), 2)::text
              FROM ps_monthly_earnings WHERE tenant_id = :t AND is_claimable
            UNION ALL SELECT 'SHORTFALL (owed - paid)',
                   round(sum(ps_gross_owed) - sum(ps_actually_paid), 2)::text
              FROM ps_monthly_earnings WHERE tenant_id = :t AND is_claimable
            UNION ALL SELECT '  ...rows w/ UNKNOWN rate (contributed $0)', count(*)::text
              FROM ps_monthly_earnings WHERE tenant_id = :t AND is_claimable
                AND ps_rate_pct IS NULL
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
