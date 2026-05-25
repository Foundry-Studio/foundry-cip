# foundry: kind=script domain=client-intelligence-platform

"""Backfill PS China attribution companion_data (cip_34, one-time seed).

PM cip_34 (china-commission-audit, Tim sign-off 2026-05-25). Seeds the
initial state of three attribution keys on PS-tenant cip_clients,
DERIVED entirely from PS's own china-referral data (no EcomLever CSV /
deal-id / Wayward-Brand-ID hop):

  Per PS brand (cip_clients), read its deals' attribution sourcer
  (cip_deals.properties->>'source' = 'China Referral - <name>'):

    sourcer 'Tim'                       → ps_attribution_owner = PS
                                          ps_lead_source       = PS
                                          (ps_conditional blank)
    sourcer <partner>                   → ps_attribution_owner = <partner>
      (Eric/Adina/OpenLight/             ps_lead_source       = <partner>
       Jeremy Dai/Shallow/Oceanwing)     ps_conditional = 'finders_fee'
                                            IFF brand normalized-name NOT in
                                            Exhibit A; else blank (excluded).
    no china-referral source            → ps_attribution_owner = unclassified

  ps_sales_lead / ps_cs_lead are NOT seeded here — the CRM fills them
  going forward.

Exhibit A membership = normalized-name match (lowercase, alphanumeric-only)
against the 225 distinct names in EXCLUSION-LIST-EXHIBIT-A.md.

Split-deal tiebreak: a brand whose deals carry >1 distinct sourcer is
resolved by the sourcer with the largest summed deal amount (then
alphabetical); such brands are counted in the summary for review.

Idempotent: merge via `companion_data || :managed::jsonb WHERE id=:id AND
(... ) IS DISTINCT FROM companion_data` (same pattern as Leg B) — a
re-run with no change is a true no-op. NEVER overwrites a key the CRM
already set differently? — it DOES overwrite the three derived keys
(this is the authoritative initial seed); but it only writes the three
attribution keys, never sales/cs lead or any other companion key.

Usage:
    CIP_DATABASE_URL=postgresql://… \
    EXHIBIT_A_PATH=<path to EXCLUSION-LIST-EXHIBIT-A.md> \
        python scripts/backfill_ps_china_attribution.py [--dry-run]

Idempotent: yes
Category: migrate
Owner: tim
Lifecycle: active
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass, field

from sqlalchemy import create_engine, text

log = logging.getLogger("cip.backfill_ps_china_attribution")

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

# sourcer → attribution. 'Tim' = PS. Partners pass through by name.
_PS_SOURCERS = frozenset({"Tim"})
_PARTNER_SOURCERS = frozenset(
    {"Eric", "Adina", "OpenLight", "Oceanwing", "Jeremy Dai", "Shallow"}
)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _load_exhibit_a(path: str) -> set[str]:
    """Parse the markdown tables → normalized brand-name set."""
    with open(path, encoding="utf-8") as f:
        md = f.read()
    names: set[str] = set()
    for line in md.splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*`[0-9a-f-]{36}`\s*\|", line)
        if m:
            nm = m.group(1).strip()
            if nm and nm.lower() != "brand name":
                names.add(_norm(nm))
    return names


@dataclass
class BackfillSummary:
    brands_total: int = 0
    set_ps: int = 0
    set_partner_finders_fee: int = 0
    set_partner_excluded: int = 0  # partner, Exhibit-A → conditional blank
    set_unclassified: int = 0
    split_brands: int = 0
    updated: int = 0
    unchanged: int = 0
    exhibit_a_names: int = 0
    split_brand_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# Per brand: the dominant china-referral sourcer (max summed amount), plus
# whether the brand had >1 distinct sourcer (split flag) + brand name.
_BRAND_SOURCER_SQL = text(
    """
    WITH deal_src AS (
        SELECT d.client_id,
               substring(d.properties->>'source' from 'China Referral - (.+)$') AS sourcer,
               COALESCE(d.amount, 0) AS amount
        FROM cip_deals d
        WHERE d.tenant_id = :tid
          AND d.properties->>'source' LIKE 'China Referral - %'
    ),
    agg AS (
        SELECT client_id, sourcer,
               SUM(amount) AS amt,
               COUNT(*) AS deals,
               ROW_NUMBER() OVER (
                   PARTITION BY client_id
                   ORDER BY SUM(amount) DESC, sourcer ASC
               ) AS rn,
               COUNT(*) OVER (PARTITION BY client_id) AS distinct_sourcers
        FROM deal_src
        GROUP BY client_id, sourcer
    )
    SELECT cl.id            AS cip_id,
           cl.client_id,
           cl.name          AS brand_name,
           a.sourcer        AS dominant_sourcer,
           a.distinct_sourcers
    FROM cip_clients cl
    LEFT JOIN agg a ON a.client_id = cl.client_id AND a.rn = 1
    WHERE cl.tenant_id = :tid
    """
)

_MERGE_SQL = text(
    """
    UPDATE cip_clients
       SET companion_data = companion_data || CAST(:managed AS jsonb)
     WHERE id = :cip_id
       AND (companion_data || CAST(:managed AS jsonb)) IS DISTINCT FROM companion_data
    """
)


def _attribution_for(
    sourcer: str | None, brand_name: str, exhibit_a: set[str]
) -> dict[str, str]:
    """Compute the three derived keys for one brand."""
    if not sourcer:
        return {"ps_attribution_owner": "unclassified"}
    if sourcer in _PS_SOURCERS:  # 'Tim' → PS
        return {"ps_attribution_owner": "PS", "ps_lead_source": "PS"}
    if sourcer in _PARTNER_SOURCERS:
        managed = {
            "ps_attribution_owner": sourcer,
            "ps_lead_source": sourcer,
        }
        # finders_fee unless the brand is on Exhibit A (contractually excluded).
        if _norm(brand_name) not in exhibit_a:
            managed["ps_conditional"] = "finders_fee"
        return managed
    # Unknown sourcer name — be conservative, mark unclassified.
    return {"ps_attribution_owner": "unclassified"}


def run_backfill(engine, exhibit_a: set[str], *, dry_run: bool = False) -> BackfillSummary:
    s = BackfillSummary(exhibit_a_names=len(exhibit_a))
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :tid, true)"),
            {"tid": PS_TENANT},
        )
        rows = conn.execute(_BRAND_SOURCER_SQL, {"tid": PS_TENANT}).mappings().all()
        for r in rows:
            s.brands_total += 1
            if (r["distinct_sourcers"] or 0) > 1:
                s.split_brands += 1
                s.split_brand_ids.append(str(r["cip_id"]))
            managed = _attribution_for(r["dominant_sourcer"], r["brand_name"] or "", exhibit_a)

            owner = managed["ps_attribution_owner"]
            if owner == "PS":
                s.set_ps += 1
            elif owner == "unclassified":
                s.set_unclassified += 1
            elif "ps_conditional" in managed:
                s.set_partner_finders_fee += 1
            else:
                s.set_partner_excluded += 1

            if dry_run:
                continue
            res = conn.execute(_MERGE_SQL, {
                "cip_id": str(r["cip_id"]),
                "managed": json.dumps(managed),
            })
            if (res.rowcount or 0) == 1:
                s.updated += 1
            else:
                s.unchanged += 1
    return s


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Backfill PS China attribution companion_data (PS-derived)"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = (
        os.environ.get("CIP_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("DATABASE_PUBLIC_URL")
    )
    if not url:
        log.error("CIP_DATABASE_URL / DATABASE_URL not set")
        return 2
    exa_path = os.environ.get("EXHIBIT_A_PATH")
    if not exa_path or not os.path.exists(exa_path):
        log.error("EXHIBIT_A_PATH not set or missing: %r", exa_path)
        return 2

    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    exhibit_a = _load_exhibit_a(exa_path)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        summary = run_backfill(engine, exhibit_a, dry_run=args.dry_run)
    finally:
        engine.dispose()

    print("BACKFILL_PS_CHINA_ATTRIBUTION_SUMMARY " + json.dumps(summary.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
