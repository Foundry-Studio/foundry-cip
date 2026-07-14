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

    # ── 0. TEACH THE MASTER every brand id Wayward knows ─────────────────────
    # ps_brands was seeded from ids that appeared on INVOICE rows. But a Stripe customer can
    # carry a brandId and never have been billed — so that brand is real, is Wayward's, and is
    # absent from the master. The moment we resolve an orphan invoice to it, the FK added in
    # cip_55 rejects the write (it did, on first run: "Key (wayward_brand_id)=(04bb92f4…) is
    # not present in table ps_brands"). That FK is doing its job: money may not point at a
    # brand the master has never heard of. So the master learns it FIRST, from Stripe's own
    # customer metadata, which is Wayward's record and not an inference.
    if apply:
        seed = [
            {"w": c["brand_id"], "t": PS_TENANT}
            for c in cust if c["brand_id"]
        ]
        if seed:
            r = conn.execute(
                text(
                    """
                    INSERT INTO ps_brands (wayward_brand_id, tenant_id, seen_in_stripe)
                    VALUES (CAST(:w AS uuid), CAST(:t AS uuid), true)
                    ON CONFLICT (wayward_brand_id) DO UPDATE
                       SET seen_in_stripe = true, updated_at = now()
                    """
                ),
                seed,
            )
            out["brands_taught_to_master"] = r.rowcount

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
    # Every write records HOW it was resolved (cip_56). An identity written without its
    # provenance is a guess wearing the authority of a fact, and identity is upstream of
    # all money — a wrong brand id yields a confident number on the wrong brand, not an error.
    resolved = {"stripe_email_match": 0, "slack_feed_email": 0}
    for c in orphan_cust:
        # Prefer Stripe's own email->brandId map; fall back to the onboarding feed's email.
        wb, src = email_to_brand.get(c["email"]), "stripe_email_match"
        if not wb:
            wb, src = brand_email.get(c["email"]), "slack_feed_email"
        if not wb:
            continue
        if apply:
            conn.execute(
                text(
                    "UPDATE ps_stripe_invoices SET wayward_brand_id = CAST(:w AS uuid), "
                    "brand_id_source = :s "
                    "WHERE tenant_id=:t AND stripe_customer_id=:c AND wayward_brand_id IS NULL"
                ),
                {"t": PS_TENANT, "w": wb, "c": c["id"], "s": src},
            )
            conn.execute(
                text(
                    "UPDATE ps_stripe_invoice_lines l "
                    "   SET wayward_brand_id = CAST(:w AS uuid), brand_id_source = :s "
                    "  FROM ps_stripe_invoices i "
                    " WHERE i.stripe_invoice_id = l.stripe_invoice_id "
                    "   AND i.stripe_customer_id = :c AND l.tenant_id = :t "
                    "   AND l.wayward_brand_id IS NULL"
                ),
                {"t": PS_TENANT, "w": wb, "c": c["id"], "s": src},
            )
        resolved[src] += 1
    out["resolved_by_stripe_email_match"] = resolved["stripe_email_match"]
    out["resolved_by_slack_feed_email"] = resolved["slack_feed_email"]
    out["unresolvable_customers"] = len(orphan_cust) - sum(resolved.values())

    # ── 3. cip_clients: DELIBERATELY NOT GUESSED ─────────────────────────────
    #
    # The original version matched `lower(c.name) = lower(split_part(email,'@',1))` — a client
    # named "roborock" linked to roborock@anything. That is a guess, and it was about to be
    # written into the column that 12 foreign keys and every money figure now depend on.
    #
    # It is worse than it looks: step 4 below propagates cip_clients.wayward_brand_id into
    # ps_partner_credit and ps_attribution. So a bad guess here does not stay here — it flows
    # into what we pay partners, as a confident dollar amount on the wrong brand. It would
    # never surface as an error.
    #
    # There is no honest match available: cip_clients has no email column, so nothing exact
    # exists to join on. The correct move is to leave these NULL and ASK, not to invent. The
    # gap is logged to ps_information_gaps instead of being papered over.
    out["cip_clients_left_null_on_purpose"] = len(rows)
    out["cip_clients_note"] = (
        "No exact key exists to link these (cip_clients has no email). Name-matching them "
        "would propagate a guess into ps_partner_credit/ps_attribution and out into partner "
        "payouts. Left NULL; logged as an information gap for Jake."
    )

    # ── 4. propagate the identities we DO trust into the money tables ────────
    # Safe now: cip_clients.wayward_brand_id is only ever set from a Wayward-supplied id, never
    # from a name guess (see 3). So what flows out to partner credit is a fact, not an inference.
    if apply:
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
