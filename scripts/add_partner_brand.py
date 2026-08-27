# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Attach a brand to a partner by hand — a PS-staff manual attribution override.

The client ask: "PS employees can add a brand to the Partner section in case some
brands are not properly included." In CIP terms, "a brand belongs to a partner" is
the row in ps_partner_credit (partner_of_record) — the same row the automated
rebuild_partner_attribution.py derives from Wayward's referral fields. This tool
lets a human assert that link when the automation missed it or got it wrong.

TWO DELIBERATE BOUNDARIES
-------------------------
1. It does NOT mint brands. Brand identity (wayward_brand_id) originates upstream
   in Wayward; fabricating one here would create an id that never lines up with the
   real one. If a brand is genuinely absent, it must enter through the Wayward feed
   first — this tool only links brands CIP already knows.
2. It does NOT create partners. The partner must already be in ps_partner_registry
   (seed it via scripts/seed_partner_aliases.py first).

HOW THE OVERRIDE STICKS
-----------------------
Rows written here carry determined_by='ps_manual'. rebuild_partner_attribution.py
skips rows with that provenance (its DO UPDATE has WHERE determined_by IS DISTINCT
FROM 'ps_manual'), so a human decision survives the next automated rebuild instead
of being silently overwritten. Attribution is per brand-product, so this credits
ALL of the brand's currently-billed products to the partner.

Usage:
  DATABASE_URL=... python scripts/add_partner_brand.py \
      --partner kerry --brand-name "Roborock" [--apply]
  DATABASE_URL=... python scripts/add_partner_brand.py \
      --partner kerry --wayward-brand-id <uuid> --note "confirmed 2026-08" [--apply]

Dry-run by default (prints what it would write); pass --apply to commit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
MANUAL_DECIDER = "ps_manual"  # rebuild_partner_attribution.py preserves rows with this provenance.

_RESOLVE_BY_ID = text(
    "SELECT wayward_brand_id, brand_name FROM ps_brands "
    "WHERE tenant_id = :t AND wayward_brand_id = CAST(:wbid AS uuid)"
)
_RESOLVE_BY_NAME = text(
    "SELECT wayward_brand_id, brand_name FROM ps_brands "
    "WHERE tenant_id = :t AND lower(brand_name) = lower(:name)"
)
_PARTNER_EXISTS = text(
    "SELECT 1 FROM ps_partner_registry WHERE tenant_id = :t AND partner_id = :p"
)
_BRAND_PRODUCTS = text(
    "SELECT DISTINCT product_id FROM ps_stripe_invoice_lines "
    "WHERE tenant_id = :t AND wayward_brand_id = CAST(:wbid AS uuid) "
    "  AND product_id IS NOT NULL AND is_ps_base "
    "ORDER BY product_id"
)
# Mirrors the brand-keyed conflict target rebuild_partner_attribution.py uses
# (partial unique index uq_ps_partner_credit_brand_product). Touches only the
# attribution columns; leaves deal_source/deal_type/rate for the pipeline + economics.
_UPSERT = text("""
    INSERT INTO ps_partner_credit (
        tenant_id, wayward_brand_id, client_id, product_id,
        partner_of_record, determined_by, determined_at, determination_note, match_status)
    VALUES (
        CAST(:t AS uuid), CAST(:wbid AS uuid),
        (SELECT id FROM cip_clients WHERE wayward_brand_id = CAST(:wbid AS uuid) LIMIT 1),
        :product, :partner, :by, now(), :note, 'confirmed')
    ON CONFLICT (tenant_id, wayward_brand_id, product_id)
        WHERE wayward_brand_id IS NOT NULL
    DO UPDATE SET
        partner_of_record  = EXCLUDED.partner_of_record,
        determined_by      = EXCLUDED.determined_by,
        determined_at      = now(),
        determination_note = EXCLUDED.determination_note,
        match_status       = EXCLUDED.match_status
""")


def resolve_brand(
    conn,
    *,
    wayward_brand_id: str | None = None,
    brand_name: str | None = None,
) -> tuple[str, str]:
    """Resolve an input to an existing (wayward_brand_id, brand_name).

    Never mints a brand: raises ValueError if the brand is not found (or a name is
    ambiguous). Brand identity is Wayward's; unknown brands enter upstream first.
    """
    if wayward_brand_id:
        rows = conn.execute(_RESOLVE_BY_ID, {"t": PS_TENANT, "wbid": wayward_brand_id}).fetchall()
        needle = wayward_brand_id
    elif brand_name:
        rows = conn.execute(_RESOLVE_BY_NAME, {"t": PS_TENANT, "name": brand_name}).fetchall()
        needle = brand_name
    else:
        raise ValueError("provide --brand-name or --wayward-brand-id")

    if not rows:
        raise ValueError(
            f"brand not found in ps_brands: {needle!r}. Brands originate upstream in "
            "Wayward; add it to the feed first — this tool does not mint brands."
        )
    if len(rows) > 1:
        raise ValueError(
            f"brand name {needle!r} is ambiguous ({len(rows)} matches); "
            "disambiguate with --wayward-brand-id."
        )
    return str(rows[0].wayward_brand_id), rows[0].brand_name


def run(
    conn,
    *,
    partner_id: str,
    wayward_brand_id: str | None = None,
    brand_name: str | None = None,
    note: str | None = None,
    apply: bool,
) -> dict:
    """Attribute all of a brand's billed products to a partner (manual override).

    Caller owns the transaction (mirrors rebuild_partner_attribution.run). apply=False
    rolls back after resolving, so the summary is a safe preview.
    """
    conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT})

    if not conn.execute(_PARTNER_EXISTS, {"t": PS_TENANT, "p": partner_id}).first():
        raise ValueError(
            f"partner_id {partner_id!r} is not in ps_partner_registry. Add the partner "
            "first (scripts/seed_partner_aliases.py); this tool does not create partners."
        )

    wbid, bname = resolve_brand(conn, wayward_brand_id=wayward_brand_id, brand_name=brand_name)
    products = [
        r.product_id
        for r in conn.execute(_BRAND_PRODUCTS, {"t": PS_TENANT, "wbid": wbid}).fetchall()
    ]

    reason = (
        f"Manual attribution by PS staff: brand {bname!r} ({wbid}) credited to partner "
        f"{partner_id!r}." + (f" Note: {note}." if note else "")
        + " Overrides automated attribution and is protected from the attribution "
        "rebuild (determined_by='ps_manual')."
    )
    rows = [
        {"t": PS_TENANT, "wbid": wbid, "product": p, "partner": partner_id,
         "by": MANUAL_DECIDER, "note": reason}
        for p in products
    ]

    out: dict = {
        "partner_id": partner_id,
        "wayward_brand_id": wbid,
        "brand_name": bname,
        "products": products,
        "rows_written": len(rows),
        "applied": apply,
    }
    if not products:
        out["warning"] = (
            "brand has no billed products in ps_stripe_invoice_lines — nothing to "
            "attribute yet. Attribution is per brand-product; re-run once the brand is billed."
        )

    if apply and rows:
        conn.execute(_UPSERT, rows)
    elif not apply:
        conn.execute(text("ROLLBACK"))
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Attach a brand to a partner (manual attribution).")
    ap.add_argument("--partner", required=True, help="partner_id (in ps_partner_registry)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--brand-name", help="brand name to resolve against ps_brands")
    g.add_argument("--wayward-brand-id", help="brand's wayward_brand_id (UUID)")
    ap.add_argument("--note", default=None, help="optional reason recorded on the row")
    ap.add_argument("--apply", action="store_true", help="commit (default: dry-run)")
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
            out = run(
                conn,
                partner_id=args.partner,
                wayward_brand_id=args.wayward_brand_id,
                brand_name=args.brand_name,
                note=args.note,
                apply=args.apply,
            )
    except ValueError as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
