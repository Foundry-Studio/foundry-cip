# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Ingest a Wayward monthly Rev Share Report (xlsx) into ps_wayward_remittance.

The cash-basis retention store for the two-layer claim model (cip_169). Reads the
"Rev Share Calc" tab verbatim and stores exactly what Wayward stated -- their number is
never recomputed. Idempotent per report_month: deletes the tenant's existing rows for that
month, then inserts the whole month in one transaction. Re-running is safe.

Usage:
    DATABASE_URL=... python scripts/ingest_wayward_remittance.py \
        --file "path/to/Tim Rev Share Report - July 2026.xlsx" \
        --report-month 2026-07-01 \
        [--tenant 078a37d6-6ae2-4e22-869e-cc08f6cb2787] [--dry-run]

If --report-month is omitted it is derived from the modal PAYMENT_DATE month.
DATABASE_URL falls back to DATABASE_PUBLIC_URL. FORCE RLS requires the tenant GUC, which
this script sets (app.current_tenant) before the delete/insert.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import date, datetime

import openpyxl
import psycopg

TAB = "Rev Share Calc"
DEFAULT_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"  # Project Silk

# Column index -> (db_column, coercer). Order matches the report header row.
NUM = lambda v: float(v) if isinstance(v, (int, float)) else None  # noqa: E731
TXT = lambda v: str(v) if v is not None else None                  # noqa: E731


def _to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def _to_uuid(v):
    s = (str(v).strip() if v is not None else "")
    return s or None


def parse_rows(path: str):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[TAB]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    hdr = [str(h).strip() if h is not None else "" for h in rows[0]]
    # Guard: the layout this loader was written against. Fail loud if Wayward reshuffles columns.
    expected = ["CUSTOMER_ID", "BRAND_ID", "BRAND_NAME", "PAYMENT_DATE", "SIGNUP_DATE",
                "STRIPE_INVOICE_IDS", "STRIPE_INVOICE_LINKS", "COMMISSION_FEES_PAID",
                "USAGE_FEES_PAID", "SAAS_FEES_PAID", "CC_PROCESSING_FEES_PAID",
                "TOTAL_AMOUNT_PAID", "REV_SHARE_OWED", "MONTHS_FROM_SIGNUP_TO_PAYMENT"]
    if hdr[:14] != expected:
        raise SystemExit(f"UNEXPECTED HEADER LAYOUT.\n expected {expected}\n got      {hdr[:14]}")
    out = []
    for r in rows[1:]:
        if not r[1]:  # no BRAND_ID -> not a data row (totals/blank)
            continue
        out.append({
            "customer_id": TXT(r[0]),
            "wayward_brand_id": _to_uuid(r[1]),
            "brand_name": TXT(r[2]),
            "payment_date": _to_date(r[3]),
            "signup_raw": TXT(r[4]),
            "stripe_invoice_ids": TXT(r[5]),
            "stripe_invoice_links": TXT(r[6]),
            "commission_fees_paid": NUM(r[7]),
            "usage_fees_paid": NUM(r[8]),
            "saas_fees_paid": NUM(r[9]),
            "cc_processing_fees_paid": NUM(r[10]),
            "total_amount_paid": NUM(r[11]),
            "rev_share_owed_stated": NUM(r[12]),
            "months_from_signup": NUM(r[13]),
            "days_from_signup": NUM(r[14]) if len(r) > 14 else None,
        })
    return out


def derive_report_month(recs) -> date:
    months = Counter(
        (rec["payment_date"].year, rec["payment_date"].month)
        for rec in recs if rec["payment_date"]
    )
    (y, m), _ = months.most_common(1)[0]
    return date(y, m, 1)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--report-month", default=None, help="YYYY-MM-DD (first of month); derived if omitted")
    ap.add_argument("--tenant", default=DEFAULT_TENANT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    recs = parse_rows(args.file)
    report_month = (
        datetime.strptime(args.report_month, "%Y-%m-%d").date()
        if args.report_month else derive_report_month(recs)
    )
    src = os.path.basename(args.file)
    total_rev = sum(r["rev_share_owed_stated"] or 0 for r in recs)
    print(f"parsed {len(recs)} rows | report_month={report_month} | "
          f"sum rev_share_owed_stated={total_rev:.3f} | source={src}")

    if args.dry_run:
        print("DRY RUN - no writes.")
        return

    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
    if not url:
        raise SystemExit("DATABASE_URL / DATABASE_PUBLIC_URL not set.")

    cols = ["tenant_id", "report_month", "customer_id", "wayward_brand_id", "brand_name",
            "payment_date", "signup_raw", "stripe_invoice_ids", "stripe_invoice_links",
            "commission_fees_paid", "usage_fees_paid", "saas_fees_paid",
            "cc_processing_fees_paid", "total_amount_paid", "rev_share_owed_stated",
            "months_from_signup", "days_from_signup", "source_file"]
    placeholders = ", ".join(["%s"] * len(cols))
    insert_sql = f"INSERT INTO ps_wayward_remittance ({', '.join(cols)}) VALUES ({placeholders})"

    with psycopg.connect(url, autocommit=False) as conn:
        with conn.cursor() as cur:
            # FORCE RLS: set the tenant GUC so the INSERT WITH CHECK + DELETE policy pass.
            cur.execute("SELECT set_config('app.current_tenant', %s, false)", (args.tenant,))
            cur.execute(
                "DELETE FROM ps_wayward_remittance WHERE tenant_id = %s AND report_month = %s",
                (args.tenant, report_month),
            )
            deleted = cur.rowcount
            params = [
                (args.tenant, report_month, r["customer_id"], r["wayward_brand_id"], r["brand_name"],
                 r["payment_date"], r["signup_raw"], r["stripe_invoice_ids"], r["stripe_invoice_links"],
                 r["commission_fees_paid"], r["usage_fees_paid"], r["saas_fees_paid"],
                 r["cc_processing_fees_paid"], r["total_amount_paid"], r["rev_share_owed_stated"],
                 r["months_from_signup"], r["days_from_signup"], src)
                for r in recs
            ]
            cur.executemany(insert_sql, params)
            conn.commit()
            print(f"OK: deleted {deleted} prior rows, inserted {len(params)} for {report_month}.")


if __name__ == "__main__":
    main()
