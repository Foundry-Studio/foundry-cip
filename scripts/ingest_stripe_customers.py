# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Ingest Stripe CUSTOMERS. Recovers the brand ids Wayward wrote into the wrong field.

We were calling /v1/customers, keeping metadata.brandId and email, and discarding everything
else on every run. This lands the whole object (cip_57) and, in doing so, recovers identities
we had written off:

  metadata.brandId is NULL for 474 customers -> but for 337 of them the brand UUID is sitting
  in the `description` field, where Wayward wrote it instead. 224 of those brands were not in
  our master at all. That is Wayward's own id, not an inference — it was simply in unstructured
  text, so nobody had looked.

ORDER MATTERS
  1. teach ps_brands every brand id (metadata AND description), or the cip_55 FK rejects the
     customer insert — a brand the master has never heard of may not receive money.
  2. write the customers.
  3. push the recovered ids down onto the invoices and lines that were unnameable.

Every identity records HOW it was learned (brand_id_source, cip_56/57):
  stripe_metadata     structured, Wayward-set                 -> fact
  stripe_description  Wayward's own UUID, in free text        -> fact, badly filed

Nothing here infers, computes, or decides. Unknown stays NULL.

Usage:
  STRIPE_API_KEY=rk_... DATABASE_URL=... python scripts/ingest_stripe_customers.py [--apply]
"""
from __future__ import annotations

import argparse
import datetime as dt
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


def fetch_customers(key: str) -> list[dict]:
    out: list[dict] = []
    after = None
    while True:
        p: dict = {"limit": 100}
        if after:
            p["starting_after"] = after
        url = "https://api.stripe.com/v1/customers?" + urllib.parse.urlencode(p)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req) as r:
            page = json.load(r)
        rows = page.get("data", [])
        if not rows:
            break
        out.extend(rows)
        if not page.get("has_more"):
            break
        after = rows[-1]["id"]
    return out


def shape(cu: dict) -> dict:
    """Stripe customer -> our row. Resolves identity, and records how."""
    meta = cu.get("metadata") or {}
    desc = (cu.get("description") or "").strip()

    brand = meta.get("brandId")
    source = "stripe_metadata" if brand and _UUID.match(brand) else None
    if not source:
        brand = None
    # Wayward wrote the id into `description` on the customers whose metadata is empty.
    if brand is None and _UUID.match(desc):
        brand, source = desc, "stripe_description"

    addr = cu.get("address") or {}
    locales = cu.get("preferred_locales") or []
    created = cu.get("created")

    return {
        "cid": cu["id"],
        "t": PS_TENANT,
        "brand": brand,
        "src": source,
        "auth0": meta.get("auth0id"),
        "ctype": meta.get("intCustomerType"),
        "email": (cu.get("email") or "").strip().lower() or None,
        "name": cu.get("name"),
        "desc": desc or None,
        "delinq": cu.get("delinquent"),
        # Stripe balance is integer cents; our column is dollars.
        "bal": (cu.get("balance") or 0) / 100.0,
        "cur": cu.get("currency"),
        "country": addr.get("country"),
        "phone": cu.get("phone"),
        "loc": ",".join(locales) or None,
        "created": (
            dt.datetime.fromtimestamp(created, tz=dt.UTC) if created else None
        ),
        "live": cu.get("livemode"),
    }


UPSERT = text("""
    INSERT INTO ps_stripe_customers (
        stripe_customer_id, tenant_id, wayward_brand_id, brand_id_source, auth0_id,
        customer_type, email, customer_name, description_raw, delinquent, balance,
        currency, address_country, phone, preferred_locales, created_at_stripe,
        livemode, ingested_at)
    VALUES (
        :cid, CAST(:t AS uuid), CAST(:brand AS uuid), :src, :auth0,
        :ctype, :email, :name, :desc, :delinq, :bal,
        :cur, :country, :phone, :loc, :created,
        :live, now())
    ON CONFLICT (stripe_customer_id) DO UPDATE SET
        wayward_brand_id = EXCLUDED.wayward_brand_id,
        brand_id_source  = EXCLUDED.brand_id_source,
        auth0_id         = EXCLUDED.auth0_id,
        customer_type    = EXCLUDED.customer_type,
        email            = EXCLUDED.email,
        customer_name    = EXCLUDED.customer_name,
        description_raw  = EXCLUDED.description_raw,
        delinquent       = EXCLUDED.delinquent,
        balance          = EXCLUDED.balance,
        currency         = EXCLUDED.currency,
        address_country  = EXCLUDED.address_country,
        phone            = EXCLUDED.phone,
        preferred_locales= EXCLUDED.preferred_locales,
        created_at_stripe= EXCLUDED.created_at_stripe,
        livemode         = EXCLUDED.livemode,
        ingested_at      = now()
""")

TEACH_MASTER = text("""
    INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name, seen_in_stripe)
    VALUES (CAST(:brand AS uuid), CAST(:t AS uuid), :name, true)
    ON CONFLICT (wayward_brand_id) DO UPDATE
       SET seen_in_stripe = true,
           brand_name = COALESCE(ps_brands.brand_name, EXCLUDED.brand_name),
           updated_at = now()
""")

# Push recovered identities down onto the invoices/lines that had none.
PROPAGATE_INV = text("""
    UPDATE ps_stripe_invoices i
       SET wayward_brand_id = c.wayward_brand_id,
           brand_id_source  = c.brand_id_source
      FROM ps_stripe_customers c
     WHERE c.stripe_customer_id = i.stripe_customer_id
       AND i.tenant_id = :t
       AND i.wayward_brand_id IS NULL
       AND c.wayward_brand_id IS NOT NULL
""")

PROPAGATE_LINES = text("""
    UPDATE ps_stripe_invoice_lines l
       SET wayward_brand_id = c.wayward_brand_id,
           brand_id_source  = c.brand_id_source
      FROM ps_stripe_invoices i
      JOIN ps_stripe_customers c ON c.stripe_customer_id = i.stripe_customer_id
     WHERE i.stripe_invoice_id = l.stripe_invoice_id
       AND l.tenant_id = :t
       AND l.wayward_brand_id IS NULL
       AND c.wayward_brand_id IS NOT NULL
""")


def run(conn, key: str, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    raw = fetch_customers(key)
    rows = [shape(c) for c in raw]

    out: dict = {
        "stripe_customers": len(rows),
        "id_from_metadata": sum(1 for r in rows if r["src"] == "stripe_metadata"),
        "id_RECOVERED_from_description": sum(
            1 for r in rows if r["src"] == "stripe_description"
        ),
        "no_id_anywhere": sum(1 for r in rows if not r["brand"]),
        "delinquent": sum(1 for r in rows if r["delinq"]),
    }

    if apply:
        # 1. master first — the FK forbids money pointing at an unknown brand.
        named = [r for r in rows if r["brand"]]
        conn.execute(TEACH_MASTER, named)
        # 2. the customers themselves
        conn.execute(UPSERT, rows)
        # 3. push identity down to the money rows that lacked it
        out["invoices_named"] = conn.execute(PROPAGATE_INV, {"t": PS_TENANT}).rowcount
        out["invoice_lines_named"] = conn.execute(
            PROPAGATE_LINES, {"t": PS_TENANT}
        ).rowcount

    out["identity_health"] = [
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
