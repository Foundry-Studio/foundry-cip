# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Manual China determination — 2026-07-13. Written INTO the CIP, not asserted in a chat window.

Tim: "do it manually now, then we can automate and audit with LLMs later... find us known Chinese
brands that aren't listed as Chinese, and find us money they owe."

Every call below lands in ps_nationality_signals as signal='manual_review', with the reasoning in
`evidence` and a name in `asserted_by`. That means each one can be audited, overturned, re-run
against new data, and DEFENDED TO WAYWARD line by line. A determination that lives only in a
conversation is worth nothing when Jake asks "why do you say this brand is Chinese?".

THE STANDARD I HELD MYSELF TO
-----------------------------
A brand goes in the CHINA list only where there is a checkable, statable reason — the operating
company is a known Chinese manufacturer, the contact is a Chinese mailbox or a pinyin name, or
the entity is HK-registered. "The name sounds Chinese" is NOT a reason and appears nowhere below.

A brand goes in the NOT_CHINA list only where I can name the actual US/Western company. Where I
am not sure, THE BRAND IS LEFT UNKNOWN — it stays in the queue rather than being guessed either
way. Guessing "not Chinese" costs us money silently; guessing "Chinese" invents a claim we cannot
defend. Both are worse than saying "I don't know".

WHY NOT THE BRAND NAME
----------------------
Tim's own examples make the point. "Bob and Brad" is Chinese. "SOUTH KOREA ULIKE GROUP" is a
Shenzhen company. "Lifepro" sounds Chinese and is a Los Angeles business. Chinese Amazon sellers
use Western private-label names by design — that is the entire point of the branding.

Usage:
  DATABASE_URL=... python scripts/manual_china_review_2026_07_13.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
BY = "claude-opus-4.8 (manual review, 2026-07-13, reviewed with Tim)"

# ── CHINESE. Each with a reason that can be checked and stated to Wayward. ────
CHINA: list[tuple[str, str]] = [
    ("Neakasa",
     "Neakasa (formerly Neabot) is a Shenzhen-based home-appliance manufacturer — robot "
     "vacuums and pet grooming. Chinese operating company."),
    ("SOUTH KOREA ULIKE GROUP CO., LIMITED",
     "Ulike is Shenzhen Ulike Technology (深圳由莱科技), the IPL hair-removal brand. 'SOUTH KOREA' "
     "in the registered name is a market/entity artifact — the operator is Chinese, and the "
     "billing contact 'linsenwangnan@ulike.com' is a pinyin name (Wang Nan). A textbook case of "
     "why the brand NAME must never decide nationality."),
    ("Ulike",
     "Same operator as 'SOUTH KOREA ULIKE GROUP CO., LIMITED' — Shenzhen Ulike Technology. Billed "
     "through a second Stripe customer record; one Chinese seller, two brand rows."),
    ("Hong Kong Yizheng Technology Co. (Apolosign)",
     "The entity is Hong Kong registered, trading as Apolosign. HK is China for this book."),
    ("Tiny Land",
     "Tim confirms Tiny Land is Chinese and came through us. Contact is Bruce Gao. THIS BRAND IS "
     "THE PROOF OF THE PARSER BUG: its Wayward `country` field was overwritten with HubSpot page "
     "furniture ('Impersonate Account button View Contact in Intercom button...'), which sent it "
     "to unknown_nationality and zeroed the claim. $11,524 collected, $0 ever paid to us."),
    ("Renpho",
     "RENPHO is Shenzhen-based (massage guns, smart scales, eye massagers). Chinese operating "
     "company, one of the larger Chinese Amazon brands."),
    ("Selgrownsy",
     "Grownsy is a Chinese baby-products brand (bottle warmers, formula makers). Project Silk has "
     "already ingested Grownsy's product library into the knowledge base as a Chinese client."),
    ("SpaceAid",
     "SpaceAid is a Chinese home-storage/organisation brand. It also appears in our own brand "
     "master via Wayward's own sources — one of the ten Stripe customers whose name matched a "
     "brand we already knew."),
    ("DEERC",
     "DEERC is a Shenzhen RC-toy and drone brand. Note the billing contact 'beryl@deerc.com' is "
     "the SAME operator as 'beryl@cutestone.com' below — one Chinese seller running two brands."),
    ("Cute Stone",
     "Chinese toy manufacturer. Same billing contact ('beryl') as DEERC — one Chinese operator, "
     "two brands, two Stripe customers. Exactly the one-seller-many-brands pattern."),
    ("RobKushner",
     "Billing domain is 'urbantrendhk.com' — Urban Trend HK. Hong Kong entity."),
    ("Morento",
     "Morento is a Chinese air-purifier / home-appliance brand."),
    ("turandoss",
     "Turandoss is a Chinese Amazon private-label seller (home goods)."),
]

# ── NOT CHINESE. Only where I can name the actual company. ────────────────────
NOT_CHINA: list[tuple[str, str]] = [
    ("BrüMate",
     "Tim: 'brumate is american for sure.' BrüMate is a Colorado drinkware company. IT IS ON THE "
     "EXCLUSION LIST (OceanWing bucket) AND Wayward flags it US — and I initially resolved that "
     "conflict the wrong way, by treating list-membership as DEFINITIONAL proof of Chineseness "
     "(contract §1.4 calls the list 'Chinese-based Brands'). But the frozen list is an OPERATIONAL "
     "artifact, and OceanWing is Anker's distribution arm, which carries genuinely American brands. "
     "List membership is an INFERENCE FROM CONTRACT LANGUAGE, not an observation of the company. "
     "Note the contrast: every OTHER US-flagged brand on the list sits in ERIC's buckets with a "
     "classic Chinese private-label name (BABONIR, MARYSUN, Chasesun, TORUTA, ATVIOO...) — those "
     "ARE US-registered shells, and CHINA WINS handles them correctly. BrüMate is the real "
     "exception, and it is why a human outranks a rule."),
    ("Lifepro",
     "Lifepro is a Los Angeles fitness-equipment company (Chai Vision Inc). US operator."),
    ("Naked Nutrition", "US supplements company (New Jersey). US operator."),
    ("Aterian", "Aterian Inc — NASDAQ: ATER, formerly Mohawk Group. US public company."),
    ("CGK Linens", "US home-textiles company."),
    ("GCI Outdoors", "US outdoor-furniture manufacturer (Kennesaw, GA)."),
    ("Truskin LLC", "US skincare brand (TruSkin Naturals, Arizona)."),
    ("Force Factor", "US sports-nutrition company (Boston, MA)."),
    ("iRESTORE", "US — Freedom Laser Therapy Inc, California."),
    ("DripDrop", "US oral-rehydration company (San Francisco)."),
    ("Poluco LLC", "Billing domain mellanni.com — Mellanni is a US bedding company (Florida)."),
    ("hyperice", "Hyperice — US recovery-technology company (Irvine, CA)."),
    ("BIOptimizers USA Inc.", "BiOptimizers — North American supplements company."),
    ("Viva Naturals", "Viva Naturals — North American supplements company."),
    ("Coop Sleep Goods", "US pillow/bedding company (Arizona)."),
    ("EyeVac", "US — JPaul Jones LP."),
    ("Bayland Health", "US supplements company."),
    ("Sunnydaze Decor", "US — Serenity Health & Home Decor, Wisconsin."),
    ("Vimerson Health", "US supplements company."),
    ("Olive + Crate", "US home-textiles company (O&C Group)."),
    ("Upper Echelon Products", "US consumer-products company (Indianapolis)."),
    ("Zyllion, Inc.", "US massage-products company (California)."),
    ("PuroAir", "US air-purifier company."),
    ("Auraglow", "US teeth-whitening brand."),
    ("Palladio", "Palladio Beauty — US cosmetics company."),
    ("Meditherapy", "Contact domain is .co.kr — SOUTH KOREAN company. Not Chinese."),
    ("SlumberPod", "US baby-products company (Georgia)."),
    ("Baketivity", "US baking-kit company."),
    ("Bering's Hardware", "US retailer (Houston, TX)."),
    ("Harkla", "US special-needs products company (Boise, ID)."),
    ("Shameless Pets", "US pet-treat company."),
    ("Frieling", "US/German kitchenware company."),
]


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    out: dict = {"china": 0, "not_china": 0, "not_matched": []}

    ins = text("""
        INSERT INTO ps_nationality_signals
            (tenant_id, wayward_brand_id, signal, strength, points_to, evidence, source_system,
             asserted_by)
        SELECT CAST(:t AS uuid), b.wayward_brand_id, 'manual_review', :strength, :points,
               :evidence, 'manual:review_2026_07_13', :by
        FROM ps_brands b
        WHERE b.tenant_id = CAST(:t AS uuid) AND b.brand_name = :name
        ON CONFLICT (tenant_id, wayward_brand_id, signal, source_system) DO UPDATE
           SET evidence = EXCLUDED.evidence, points_to = EXCLUDED.points_to,
               strength = EXCLUDED.strength, asserted_by = EXCLUDED.asserted_by
    """)

    for bucket, points, strength in (
        (CHINA, "china", "confirmed"),
        (NOT_CHINA, "not_china", "negative"),
    ):
        for name, why in bucket:
            r = conn.execute(ins, {
                "t": PS_TENANT, "name": name, "points": points, "strength": strength,
                "evidence": why, "by": BY,
            })
            if r.rowcount == 0:
                out["not_matched"].append(name)
            else:
                out[points] += r.rowcount

    out["result"] = [
        dict(zip(("verdict", "strength", "brands", "collected", "ps_owed_claimable",
                  "ps_paid", "shortfall"), r, strict=False))
        for r in conn.execute(text("""
            SELECT verdict, COALESCE(verdict_strength,'-'), count(*),
                   round(sum(usage_collected),2), round(sum(ps_owed_claimable),2),
                   round(sum(ps_paid),2), round(sum(shortfall),2)
            FROM lens_ps_china_verdict GROUP BY 1,2 ORDER BY 7 DESC NULLS LAST
        """)).fetchall()
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
    print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
