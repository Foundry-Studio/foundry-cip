# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Ingest Wayward's Stripe invoices + LINES into CIP. Billed vs collected, per product.

This is the source. Everything else in CIP is Wayward telling us what Wayward paid us;
Stripe is what was actually BILLED to the brand and actually COLLECTED.

Pulls EVERY brand, not just PS's book (Tim: "it will be EVERYTHING, not just China, then
we will of course filter"). Filtering at ingest destroys the ability to ask new questions
later, so we never do it.

THE JOIN IS EXACT: Stripe customer metadata carries `brandId` = the wayward_brand_id.
We resolve customer -> brandId -> cip_clients. No email or name guessing.

LINE PARSING — the descriptions encode month + channel + fee type:
    "April 2026 - Wayward Connect - Attribution Usage Fee"
    "April 2026 - Amazon - Boosted Affiliate - ACC Bonus - Usage Fee"
    "March 2026 - Walmart - Affiliate - Commission Fee"
    "June 2026 - Credit Card Processing Fee"

is_ps_base is set ONLY for usage fees. Commission fees are creator pass-through and are
NOT PS's base — that misreading is the reason 11-MONEY-FLOW-EXPLAINER.md exists. Computed
here, once, so no downstream query has to get it right.

Usage:
  STRIPE_API_KEY=rk_live_... DATABASE_URL=... python scripts/ingest_stripe_invoices.py \
      [--full] [--since 2025-11-01] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
API = "https://api.stripe.com/v1/"
PAGE = 100
_BATCH = 500

_MONTH = re.compile(r"^([A-Z][a-z]+)\s+(\d{4})\s*-\s*(.*)$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def _api(path: str, key: str, **params) -> dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as ex:      # noqa: PERF203
            if ex.code == 429 and attempt < 4:    # rate limited — back off
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def _ts(v):
    return datetime.fromtimestamp(v, UTC) if v else None


def _money(cents):
    return None if cents is None else round(cents / 100.0, 2)


def classify(description: str) -> dict:
    """'April 2026 - Wayward Connect - Attribution Usage Fee' -> structured facts."""
    d = (description or "").strip()
    billing_month = None
    m = _MONTH.match(d)
    rest = d
    if m:
        try:
            billing_month = datetime.strptime(
                f"{m.group(1)} {m.group(2)}", "%B %Y"
            ).date()
            rest = m.group(3)
        except ValueError:
            pass
    low = rest.lower()

    if "walmart" in low:
        channel = "walmart"
    elif "boosted" in low:
        channel = "amazon_boosted"
    elif "amazon" in low and "connect" in low:
        channel = "amazon_connect"
    elif "wayward connect" in low:
        channel = "wayward_connect"
    else:
        channel = "other"

    recon = "reconciliation" in low
    if "processing fee" in low:
        fee_type = "cc_processing"
    elif "saas" in low or "subscription" in low:
        fee_type = "saas"
    elif "usage" in low:
        fee_type = "reconciliation_usage" if recon else "usage"
    elif "commission" in low:
        fee_type = "reconciliation_commission" if recon else "commission"
    else:
        fee_type = "other"

    product = (
        "boosted" if channel == "amazon_boosted"
        else "connect" if channel in ("wayward_connect", "amazon_connect")
        else None
    )
    # PS's base is USAGE ONLY. Commission is creator pass-through — never the base.
    is_ps_base = fee_type in ("usage", "reconciliation_usage")
    return {
        "billing_month": billing_month, "channel": channel,
        "fee_type": fee_type, "product_id": product, "is_ps_base": is_ps_base,
    }


_INV = text("""
    INSERT INTO ps_stripe_invoices (
        tenant_id, stripe_invoice_id, stripe_customer_id, wayward_brand_id, client_id,
        customer_email, customer_name, status, paid, collection_method,
        amount_due, amount_paid, amount_remaining, subtotal, total, currency,
        invoice_number, hosted_invoice_url, created_at_stripe,
        period_start, period_end, due_date
    ) VALUES (
        :t, :iid, :cid, CAST(:wbid AS uuid), CAST(:clid AS uuid),
        :email, :name, :status, :paid, :cm,
        :due, :paid_amt, :rem, :sub, :tot, :cur,
        :num, :url, :created, :ps, :pe, :dd
    )
    ON CONFLICT (tenant_id, stripe_invoice_id) DO UPDATE SET
        status = EXCLUDED.status,
        paid = EXCLUDED.paid,
        amount_paid = EXCLUDED.amount_paid,
        amount_remaining = EXCLUDED.amount_remaining,
        ingested_at = now()
""")

_LINE = text("""
    INSERT INTO ps_stripe_invoice_lines (
        tenant_id, stripe_invoice_id, stripe_line_id, wayward_brand_id, client_id,
        description, amount, currency, quantity,
        billing_month, channel, fee_type, product_id, is_ps_base,
        invoice_status, line_period_start, line_period_end
    ) VALUES (
        :t, :iid, :lid, CAST(:wbid AS uuid), CAST(:clid AS uuid),
        :desc, :amt, :cur, :qty,
        :bm, :ch, :ft, :pid, :base,
        :istatus, :lps, :lpe
    )
    ON CONFLICT (tenant_id, stripe_line_id) DO UPDATE SET
        invoice_status = EXCLUDED.invoice_status,
        amount = EXCLUDED.amount,
        ingested_at = now()
""")


def run(conn, key: str, *, since: date | None, dry_run: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    wbid_to_client = {
        str(w): str(c)
        for c, w in conn.execute(
            text(
                "SELECT id, wayward_brand_id FROM cip_clients "
                "WHERE wayward_brand_id IS NOT NULL"
            )
        ).fetchall()
    }

    # customer -> brandId. Cached; Stripe stores it on the CUSTOMER, not the invoice.
    cust_brand: dict[str, str | None] = {}

    def brand_of(cust_id: str | None) -> str | None:
        if not cust_id:
            return None
        if cust_id not in cust_brand:
            try:
                c = _api(f"customers/{cust_id}", key)
                b = (c.get("metadata") or {}).get("brandId")
                cust_brand[cust_id] = b if b and _UUID.match(b) else None
            except Exception:
                cust_brand[cust_id] = None
        return cust_brand[cust_id]

    params = {"limit": PAGE, "expand[]": "data.lines"}
    if since:
        params["created[gte]"] = int(
            datetime(since.year, since.month, since.day, tzinfo=UTC).timestamp()
        )

    invoices = lines = 0
    matched = 0
    inv_buf: list[dict] = []
    line_buf: list[dict] = []
    starting_after = None

    while True:
        p = dict(params)
        if starting_after:
            p["starting_after"] = starting_after
        page = _api("invoices", key, **p)
        data = page.get("data", [])
        if not data:
            break

        for iv in data:
            invoices += 1
            cust = iv.get("customer")
            wbid = brand_of(cust)
            clid = wbid_to_client.get(wbid) if wbid else None
            if wbid:
                matched += 1
            status = iv.get("status")

            inv_buf.append({
                "t": PS_TENANT, "iid": iv["id"], "cid": cust,
                "wbid": wbid, "clid": clid,
                "email": iv.get("customer_email"), "name": iv.get("customer_name"),
                "status": status, "paid": iv.get("paid"),
                "cm": iv.get("collection_method"),
                "due": _money(iv.get("amount_due")),
                "paid_amt": _money(iv.get("amount_paid")),
                "rem": _money(iv.get("amount_remaining")),
                "sub": _money(iv.get("subtotal")), "tot": _money(iv.get("total")),
                "cur": iv.get("currency"), "num": iv.get("number"),
                "url": iv.get("hosted_invoice_url"),
                "created": _ts(iv.get("created")),
                "ps": _ts(iv.get("period_start")), "pe": _ts(iv.get("period_end")),
                "dd": _ts(iv.get("due_date")),
            })

            for li in (iv.get("lines") or {}).get("data", []):
                c = classify(li.get("description"))
                per = li.get("period") or {}
                line_buf.append({
                    "t": PS_TENANT, "iid": iv["id"], "lid": li["id"],
                    "wbid": wbid, "clid": clid,
                    "desc": li.get("description"),
                    "amt": _money(li.get("amount")),
                    "cur": li.get("currency"), "qty": li.get("quantity"),
                    "bm": c["billing_month"], "ch": c["channel"],
                    "ft": c["fee_type"], "pid": c["product_id"],
                    "base": c["is_ps_base"], "istatus": status,
                    "lps": _ts(per.get("start")), "lpe": _ts(per.get("end")),
                })
                lines += 1

        if not dry_run and len(inv_buf) >= _BATCH:
            conn.execute(_INV, inv_buf)
            inv_buf.clear()
        if not dry_run and len(line_buf) >= _BATCH:
            conn.execute(_LINE, line_buf)
            line_buf.clear()

        if not page.get("has_more"):
            break
        starting_after = data[-1]["id"]

    if not dry_run:
        if inv_buf:
            conn.execute(_INV, inv_buf)
        if line_buf:
            conn.execute(_LINE, line_buf)

    out = {
        "invoices_seen": invoices,
        "lines_seen": lines,
        "invoices_with_brandId": matched,
        "distinct_stripe_customers": len(cust_brand),
        "dry_run": dry_run,
    }
    if not dry_run:
        r = conn.execute(
            text(
                "SELECT count(*), count(DISTINCT wayward_brand_id) "
                "FROM ps_stripe_invoices WHERE tenant_id=:t"
            ),
            {"t": PS_TENANT},
        ).fetchone()
        out["in_db_invoices"] = r[0]
        out["in_db_brands"] = r[1]
        out["in_db_lines"] = conn.execute(
            text("SELECT count(*) FROM ps_stripe_invoice_lines WHERE tenant_id=:t"),
            {"t": PS_TENANT},
        ).scalar()
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="all history")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
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

    since = None
    if args.since and not args.full:
        since = date.fromisoformat(args.since)

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            out = run(conn, key, since=since, dry_run=args.dry_run)
            if args.dry_run:
                conn.execute(text("ROLLBACK"))
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
