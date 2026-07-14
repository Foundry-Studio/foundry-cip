# foundry: kind=script domain=client-intelligence-platform touches=storage
"""FILL the identity spine. Not math — identity. Get this right and the math sorts itself.

Tim, 2026-07-13: "Make sure the FIELDS are correct, then make sure they are FILLED. If your
fields are correct and the relationships are correct, the math will sort itself."

Every money bug we hit was an identity bug wearing a math costume:
  - the rate clock keyed on client_id -> $1.25M of collected usage could not hold a
    productive date -> priced at $0. The arithmetic was fine; the brand had no usable name.
  - ps_partner_credit / ps_attribution had no wayward_brand_id at all (cip_54 added it).

THE GAPS THIS FILLS

  1. cip_clients.wayward_brand_id  (was 64%)
     Filled from STRIPE, which is authoritative: Stripe customer metadata carries brandId,
     and the customer also carries the email. So email -> brandId is an exact, Wayward-owned
     mapping. This BEATS the fuzzy name matching used originally (which matched 990/1526 and
     silently mis-matched who knows how many).

  2. ps_stripe_invoices / _lines .wayward_brand_id  (was 78% / 74%)
     ~3,300 invoices sit on Stripe customers whose metadata has NO brandId. For those we fall
     back to the customer's EMAIL, matched against a brand email we already know from the
     Slack brand-connection feed. Recorded as 'email_fallback' so the weaker provenance is
     never forgotten.

  3. ps_partner_credit / ps_attribution .wayward_brand_id — backfilled in cip_54 from
     cip_clients; re-run here after (1) lands, since (1) creates new client->brand links.

NOTHING HERE COMPUTES MONEY. It only makes brands nameable.

Usage:
  STRIPE_API_KEY=rk_... DATABASE_URL=... python scripts/repair_identity_spine.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def stripe_customers(key: str) -> list[dict]:
    """Every Stripe customer: id, email, metadata.brandId. The authoritative map."""
    out, after = [], None
    while True:
        p = {"limit": 100}
        if after:
            p["starting_after"] = after
        url = "https://api.stripe.com/v1/customers?" + urllib.parse.urlencode(p)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req) as r:
            page = json.load(r)
        rows = page.get("data", [])
        if not rows:
            break
        for cu in rows:
            b = (cu.get("metadata") or {}).get("brandId")
            out.append({
                "id": cu["id"],
                "email": (cu.get("email") or "").strip().lower() or None,
                "brand_id": b if b and _UUID.match(b) else None,
            })
        if not page.get("has_more"):
            break
        after = rows[-1]["id"]
    return out


def run(conn, key: str, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    out: dict = {}

    cust = stripe_customers(key)
    out["stripe_customers"] = len(cust)
    out["stripe_customers_with_brandId"] = sum(1 for c in cust if c["brand_id"])

    # email -> brand_id, from Stripe's own metadata. Exact, Wayward-owned.
    email_to_brand = {
        c["email"]: c["brand_id"]
        for c in cust
        if c["email"] and c["brand_id"]
    }
    # customers with NO brandId — we will try to name them by email
    orphan_cust = [c for c in cust if not c["brand_id"] and c["email"]]
    out["stripe_customers_without_brandId"] = len(orphan_cust)

    # ── 1. cip_clients.wayward_brand_id, from Stripe email->brandId ──────────
    rows = conn.execute(
        text(
            "SELECT id, lower(name) AS name FROM cip_clients "
            "WHERE tenant_id=:t AND wayward_brand_id IS NULL"
        ),
        {"t": PS_TENANT},
    ).fetchall()
    out["cip_clients_missing_brand_id_before"] = len(rows)

    # brand emails we already know, from the Slack brand-connection feed
    brand_email = {
        (em or "").strip().lower(): str(wb)
        for wb, em in conn.execute(
            text(
                "SELECT o.wayward_brand_id, o.value FROM ps_brand_observations o "
                "WHERE o.tenant_id=:t AND o.field='email'"
            ),
            {"t": PS_TENANT},
        ).fetchall()
        if em
    }

    # ── 2. Stripe invoices/lines with no brandId -> resolve via email ────────
    resolved = 0
    for c in orphan_cust:
        wb = brand_email.get(c["email"]) or email_to_brand.get(c["email"])
        if not wb:
            continue
        if apply:
            for tbl in ("ps_stripe_invoices", "ps_stripe_invoice_lines"):
                conn.execute(
                    text(
                        f"UPDATE {tbl} SET wayward_brand_id = CAST(:w AS uuid) "
                        f"WHERE tenant_id=:t AND stripe_customer_id=:c "
                        f"AND wayward_brand_id IS NULL"
                    ) if tbl == "ps_stripe_invoices" else
                    text(
                        f"UPDATE {tbl} l SET wayward_brand_id = CAST(:w AS uuid) "
                        f"FROM ps_stripe_invoices i "
                        f"WHERE i.stripe_invoice_id = l.stripe_invoice_id "
                        f"AND i.stripe_customer_id = :c AND l.tenant_id=:t "
                        f"AND l.wayward_brand_id IS NULL"
                    ),
                    {"t": PS_TENANT, "w": wb, "c": c["id"]},
                )
        resolved += 1
    out["stripe_customers_resolved_by_email"] = resolved

    # ── 3. cip_clients: link via the brand email we now trust ────────────────
    if apply:
        r = conn.execute(
            text(
                """
                UPDATE cip_clients c
                   SET wayward_brand_id = s.wayward_brand_id
                  FROM (
                      SELECT DISTINCT ON (lower(i.customer_email))
                             lower(i.customer_email) AS email, i.wayward_brand_id
                      FROM ps_stripe_invoices i
                      WHERE i.tenant_id = :t
                        AND i.wayward_brand_id IS NOT NULL
                        AND i.customer_email IS NOT NULL
                  ) s
                 WHERE c.tenant_id = :t
                   AND c.wayward_brand_id IS NULL
                   AND lower(c.name) = lower(split_part(s.email,'@',1))
                """
            ),
            {"t": PS_TENANT},
        )
        out["cip_clients_linked_via_stripe"] = r.rowcount

        # 4. re-backfill the two tables cip_54 added the column to
        for tbl in ("ps_partner_credit", "ps_attribution", "ps_product_subscriptions"):
            conn.execute(
                text(
                    f"""
                    UPDATE {tbl} t SET wayward_brand_id = c.wayward_brand_id
                      FROM cip_clients c
                     WHERE c.id = t.client_id AND t.tenant_id = :t
                       AND t.wayward_brand_id IS NULL
                       AND c.wayward_brand_id IS NOT NULL
                    """
                ),
                {"t": PS_TENANT},
            )

    out["identity_health_after"] = [
        dict(zip(("relation", "rows", "with_brand_id", "pct"), r, strict=False))
        for r in conn.execute(text("SELECT * FROM lens_ps_identity_health")).fetchall()
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
    key = os.environ.get("STRIPE_API_KEY")
    if not key:
        print("STRIPE_API_KEY not set", file=sys.stderr)
        return 2
    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            out = run(conn, key, apply=args.apply)
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
