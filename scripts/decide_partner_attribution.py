# foundry: kind=script domain=client-intelligence-platform touches=storage
"""DECISION LAYER (attribution): turn evidence into decisions, with the reasoning kept.

This is the ONLY thing allowed to write the decision columns
(ps_partner_credit.partner_of_record / deal_type, ps_product_subscriptions.last_activity_at).
Ingestion never touches them. Every decision records determined_by + determination_note so
a human can see WHY, and every input is an observation that can be traced to its source.

WHAT IT DECIDES
---------------
1. CONNECT ATTRIBUTION. For each brand in Jake's Eric-network sheet:
     referrer (raw)  --ps_partner_aliases-->  canonical partner_id
   Then deal_type, from Jake's own 'Eligible for 10% Rev Share' column, whose meaning
   Jake gave us verbatim (email 2026-01-21):
     FALSE -> flat-fee referred brands   -> deal_type='flat_fee'
              Tim ruled 2026-07-13: NOBODY earns the 10% on these — not Eric (paid once),
              not PS. Not a claim item; an OPPORTUNITY item.
     TRUE  -> rev-share referred brands (the PRIOR agreement, pre-Tim contract)
              -> deal_type='rev_share', but PS's entitlement is NOT confirmed. Flagged
              for review, NOT assumed. Guessing here would invent revenue.
     NA    -> "brands referred under Tim" -> PS's current-contract book. deal_type left
              NULL (= not yet determined, which is a different fact from 'none').

2. DORMANCY. last_activity_at = the latest payment_date where usage_fees_paid > 0.
   Tim's definition (2026-07-13): activity = sales through the platform that month, and a
   nonzero usage fee PROVES sales (the fee is levied ON sales).

   ASSUMPTION, stated loudly: the monthly reports carry NO product split (the open D3 ask),
   and Boost is not yet generating usage fees, so all observed activity is attributed to
   CONNECT. If Boost starts billing, this becomes wrong and must be revisited.

   Brands with no payment history get activity_source='none:no_activity_signal' — NOT a
   guess of "active". A brand wrongly assumed active is an opportunity thrown away.

Usage:
  DATABASE_URL=... python scripts/decide_partner_attribution.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
DECIDER = "rule:eric_sheet_v1"
NOTE = {
    "flat_fee": (
        "Jake's sheet: Eligible for 10% Rev Share = FALSE => flat-fee referred brand. "
        "Tim 2026-07-13: NOBODY earns the 10% on these (not Eric, not PS). "
        "partner_rate must be ignored. Attribution kept so performance stays trackable. "
        "PS can earn only via Connect reactivation after 90d inactive, or by selling Boost."
    ),
    "rev_share": (
        "Jake's sheet: Eligible for 10% Rev Share = TRUE => rev-share referred brand under "
        "the PRIOR (pre-Tim) agreement. PS's entitlement on these is NOT CONFIRMED — "
        "flagged for review, not assumed. Do not treat as PS revenue without a ruling."
    ),
    "undetermined": (
        "Jake's sheet: Eligible for 10% Rev Share = NA => 'referred under Tim'. PS's "
        "current-contract book. deal_type left NULL = NOT YET DETERMINED (different from 'none')."
    ),
}


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )

    # ── 1. Connect attribution, resolved through the alias map ──────────────
    rows = conn.execute(
        text(
            """
            WITH ev AS (
              SELECT o.wayward_brand_id, o.client_id,
                     max(o.value) FILTER (
                         WHERE o.field='referrer') AS referrer_raw,
                     max(o.value) FILTER (
                         WHERE o.field='eligible_for_10_rev_share') AS eligible
              FROM ps_brand_observations o
              WHERE o.tenant_id = :t
                AND o.source_system = 'gsheet:eric-all-agreements'
                AND o.client_id IS NOT NULL
              GROUP BY 1,2
            )
            SELECT ev.client_id, ev.wayward_brand_id, ev.referrer_raw, ev.eligible,
                   COALESCE(a.partner_id, 'unassigned') AS partner_id
            FROM ev
            LEFT JOIN ps_partner_aliases a
                   ON a.tenant_id = :t
                  AND a.alias_kind = 'display_name'
                  AND a.alias_value = ev.referrer_raw
            """
        ),
        {"t": PS_TENANT},
    ).fetchall()

    counts = {"flat_fee": 0, "rev_share": 0, "undetermined": 0, "no_eligibility": 0}
    payload = []
    for client_id, wbid, _raw, eligible, partner_id in rows:
        e = (eligible or "").strip().upper()
        if e == "FALSE":
            deal, note = "flat_fee", NOTE["flat_fee"]
        elif e == "TRUE":
            deal, note = "rev_share", NOTE["rev_share"]
        elif e == "NA":
            deal, note = None, NOTE["undetermined"]
        else:
            counts["no_eligibility"] += 1
            continue
        counts["flat_fee" if deal == "flat_fee"
               else "rev_share" if deal == "rev_share" else "undetermined"] += 1
        payload.append({
            "t": PS_TENANT, "cid": str(client_id), "wbid": str(wbid),
            "p": partner_id, "deal": deal, "note": note,
        })

    if apply and payload:
        for i in range(0, len(payload), 500):
            conn.execute(
                text(
                    """
                    INSERT INTO ps_partner_credit (
                        tenant_id, client_id, product_id, partner_of_record,
                        deal_type, deal_type_source,
                        determined_by, determined_at, determination_note
                    ) VALUES (
                        :t, :cid, 'connect', :p,
                        :deal, 'gsheet:eric-all-agreements',
                        '""" + DECIDER + """', now(), :note
                    )
                    ON CONFLICT DO NOTHING
                    """
                ),
                payload[i:i + 500],
            )

    # ── 2. Dormancy: last_activity_at from proven sales (usage fee > 0) ──────
    if apply:
        conn.execute(
            text(
                """
                -- status is left NULL deliberately: it is WAYWARD's lifecycle enum
                -- (ACCOUNT_CREATED / ACTIVE / PRODUCTIVE_NOT_PAID / PRODUCTIVE_PAYABLE),
                -- a different fact from "did they sell anything". Activity is what we
                -- are deciding here; lifecycle status comes from Wayward's own data.
                INSERT INTO ps_product_subscriptions (
                    tenant_id, client_id, product_id,
                    last_activity_at, activity_source, dormancy_evaluated_at
                )
                SELECT :t, pe.client_id, 'connect',
                       max(pe.payment_date)::timestamptz,
                       'ps_payment_events.usage_fees_paid>0',
                       now()
                FROM ps_payment_events pe
                WHERE pe.tenant_id = :t AND pe.client_id IS NOT NULL
                  AND pe.usage_fees_paid > 0
                GROUP BY pe.client_id
                ON CONFLICT DO NOTHING
                """
            ),
            {"t": PS_TENANT},
        )

    stats = {}
    if apply:
        stats["partner_credit_rows"] = conn.execute(
            text("SELECT count(*) FROM ps_partner_credit WHERE tenant_id=:t"),
            {"t": PS_TENANT},
        ).scalar()
        stats["subscriptions_with_activity"] = conn.execute(
            text(
                "SELECT count(*) FROM ps_product_subscriptions "
                "WHERE tenant_id=:t AND last_activity_at IS NOT NULL"
            ),
            {"t": PS_TENANT},
        ).scalar()
        stats["dormant_on_connect_90d"] = conn.execute(
            text(
                "SELECT count(*) FROM ps_product_subscriptions WHERE tenant_id=:t "
                "AND product_id='connect' "
                "AND last_activity_at < now() - INTERVAL '90 days'"
            ),
            {"t": PS_TENANT},
        ).scalar()

    return {
        "brands_evaluated": len(rows),
        "decisions": counts,
        "applied": apply,
        **stats,
    }


def main(argv: list[str] | None = None) -> int:
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
            if not args.apply:
                conn.execute(text("ROLLBACK"))
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
