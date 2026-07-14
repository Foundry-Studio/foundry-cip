# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Populate the partner economics that were never filled in: rate + credit window.

THE GAP THIS CLOSES
-------------------
ps_partner_credit knew WHO the partner was (partner_of_record) but not WHAT THEY ARE OWED:
partner_rate, credit_start and credit_end were entirely NULL across all 1,310 rows. So
partner_owed came out $0.00 everywhere in ps_monthly_earnings — not because partners are owed
nothing, but because we had never recorded the number.

WHAT IT WRITES (all of it a DECISION, so each row records determined_by + a note)

  partner_rate  = the partner's %% of the SAME usage-fee base we are paid on. Out of our 10,
                  not on top of it. Default 5 (Tim, 2026-07-13: "5% is automatic ... we split
                  the 10% total"), overridable per partner x product via ps_partner_terms.

                  ZERO when:
                    - deal_type = 'flat_fee'  -> the partner was paid ONCE. Eric's book. He
                      earns nothing ongoing, and neither do we. partner_rate MUST be ignored
                      for these, so we set it to 0 rather than leave it ambiguous.
                    - partner_of_record = 'unassigned' -> an explicit decision that nobody is
                      credited; PS keeps the full 10%.

  credit_start  = the brand's productive date ON THAT PRODUCT (§1.5 / §3.1 — the same anchor
                  the 10/6/3 step-down runs from).
  credit_end    = credit_start + 12 months. The partner rolls off HERE.

                  Note the consequence, which is not intuitive: our NET goes UP at credit_end.
                  A 5%% partner expiring at month 12 takes us from netting 5%% to netting 6%%,
                  because our own rate only steps down to 6%% at exactly the same moment. The
                  two clocks are aligned by design — it is why our net can never go negative.

Usage:
  DATABASE_URL=... python scripts/populate_partner_economics.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
DECIDER = "rule:partner_economics_v1"

UPDATE = text("""
    WITH clock AS (
        -- Keyed on wayward_brand_id, NOT client_id. Joining the clock on the cip_clients
        -- surrogate (65% coverage) left 1,722 credit rows with a rate but NO 12-month window,
        -- so partners silently earned nothing on them. Same identity bug, one more place.
        SELECT wayward_brand_id, product_id, productive_date
        FROM ps_product_subscriptions
        WHERE tenant_id = :t
          AND productive_date IS NOT NULL
          AND wayward_brand_id IS NOT NULL
    ),
    terms AS (
        -- Partner-specific rate if one exists, else the '_default' row (5%).
        SELECT DISTINCT ON (partner_id, product_id)
               partner_id, product_id, commission_pct
        FROM ps_partner_terms
        WHERE tenant_id = :t
        ORDER BY partner_id, product_id, effective_from DESC
    )
    UPDATE ps_partner_credit pc SET
        partner_rate = CASE
            -- Flat fee: paid once. Earns NOTHING ongoing. Not ambiguous — zero.
            WHEN pc.deal_type = 'flat_fee'                THEN 0
            -- 'unassigned' is a DECISION that nobody is credited; PS keeps the full 10%.
            WHEN pc.partner_of_record IS NULL
              OR pc.partner_of_record = 'unassigned'      THEN 0
            ELSE COALESCE(
                (SELECT commission_pct FROM terms
                  WHERE terms.partner_id = pc.partner_of_record
                    AND terms.product_id = pc.product_id),
                (SELECT commission_pct FROM terms
                  WHERE terms.partner_id = '_default'
                    AND terms.product_id = pc.product_id),
                5)                                        -- the default split
        END,
        credit_start = c.productive_date,
        credit_end   = c.productive_date + 365,
        match_status = COALESCE(pc.match_status, 'probable'),
        determined_by = :by,
        determined_at = now(),
        determination_note = COALESCE(pc.determination_note, '') ||
            CASE
              WHEN pc.deal_type = 'flat_fee' THEN
                ' | ECONOMICS: partner_rate=0 — flat-fee brand, the partner was paid ONCE and'
                ' earns nothing ongoing (and neither do we). Attribution is kept for'
                ' performance tracking only.'
              WHEN pc.partner_of_record = 'unassigned' THEN
                ' | ECONOMICS: partner_rate=0 — nobody credited; PS keeps the full 10%.'
              ELSE
                ' | ECONOMICS: partner_rate from ps_partner_terms (default 5% of the'
                ' usage-fee base, OUT OF our 10 — we split it). credit window = productive'
                ' date + 12 months, the same anchor as the 10/6/3 step-down; our NET rises'
                ' 5%->6% when the partner rolls off.'
            END
    FROM clock c
    WHERE pc.tenant_id = :t
      AND c.wayward_brand_id = pc.wayward_brand_id
      AND c.product_id = pc.product_id
""")

# Rows with no productive date yet: still set the rate, leave the window null.
UPDATE_NO_CLOCK = text("""
    UPDATE ps_partner_credit pc SET
        partner_rate = CASE
            WHEN pc.deal_type = 'flat_fee'           THEN 0
            WHEN pc.partner_of_record IS NULL
              OR pc.partner_of_record = 'unassigned' THEN 0
            ELSE 5
        END,
        match_status = COALESCE(pc.match_status, 'probable'),
        determined_by = :by,
        determined_at = now()
    WHERE pc.tenant_id = :t AND pc.partner_rate IS NULL
""")


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    r1 = conn.execute(UPDATE, {"t": PS_TENANT, "by": DECIDER})
    r2 = conn.execute(UPDATE_NO_CLOCK, {"t": PS_TENANT, "by": DECIDER})

    out = {
        "rows_with_clock": r1.rowcount,
        "rows_without_clock": r2.rowcount,
        "breakdown": [
            dict(zip(("deal_type", "partner_rate", "rows", "with_window"), row, strict=False))
            for row in conn.execute(text("""
                SELECT COALESCE(deal_type,'(null)'), partner_rate, count(*),
                       count(credit_start)
                FROM ps_partner_credit WHERE tenant_id=:t
                GROUP BY 1,2 ORDER BY 3 DESC
            """), {"t": PS_TENANT}).fetchall()
        ],
        "applied": apply,
    }
    if not apply:
        conn.execute(text("ROLLBACK"))
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
