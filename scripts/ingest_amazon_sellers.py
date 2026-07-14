# foundry: kind=script domain=client-intelligence-platform
"""Amazon seller of record -> China verdict. One fact in, one verdict out.

TIM, 2026-07-14: "I want them to check the amazon storefronts, and determine if the seller identity
is chinese, thats the easiest way. LEts ONLY do that."

He is right, and everything before this was me overcomplicating it.

WHY THIS IS THE ONLY SOURCE WE NEED
-----------------------------------
The INFORM Consumers Act (US, 2023) legally COMPELS Amazon to verify and publish the business name
and registered address of every high-volume third-party seller. Every brand in this book is one. So
the answer to "who is this company and where are they" is a legally-mandated public disclosure,
sitting on a page.

    Business Name:    SHENZHENWEIERCHUANGXINYOUXIANGONGSI
    Business Address: ... Shenzhen, Guangdong, CN

There is nothing to infer. The researcher reads two strings. WE do the classifying, mechanically,
here — so there is nowhere for anyone (them or me) to drift.

    address in China / Hong Kong / Macau  ->  CHINA
    address anywhere else                 ->  NOT CHINA
    no seller page found                  ->  unchanged. unknown is a fine answer.

THE ONE EXCEPTION, AND IT DOES NOT DECIDE ANYTHING
--------------------------------------------------
A registered-agent MAIL DROP is not a real address. `30 N Gould St, Sheridan WY` is a mailbox
service used by thousands of shell companies — aloderma's Amazon seller is registered there while
its trademark is owned by Taishan AGHG Aloe Products Co., Ltd. of Guangdong.

So a mail-drop address does NOT clear a brand. It is HELD and listed for Tim. It is never
auto-cleared and never auto-flipped. It is a question.

Usage:
    python scripts/ingest_amazon_sellers.py            # dry run
    python scripts/ingest_amazon_sellers.py --apply
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

import psycopg

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
DEFAULT_DIR = (
    r"c:\Users\Tim Jordan\code\venture-ecomlever\clients\wayward"
    r"\china-commission-audit\research-handoff\findings"
)

# Tim, 2026-07-14: "hong kong IS chinese based." Macau likewise.
_CHINA_ADDRESS = re.compile(
    r"\b(china|hong\s*kong|macau|macao)\b|,\s*(cn|hk|mo)\s*$|\b(cn|hk)\s+\d{5,6}\b"
    r"|\b(shenzhen|guangzhou|dongguan|hangzhou|ningbo|yiwu|foshan|zhongshan|xiamen|quanzhou"
    r"|wenzhou|shanghai|beijing|guangdong|zhejiang|fujian|jiangsu|shandong|kowloon|wan\s*chai"
    r"|sheung\s*wan|tsim\s*sha\s*tsui)\b",
    re.I,
)
# a Chinese legal entity, spelled out. Amazon does not translate these.
_CHINA_ENTITY = re.compile(
    r"youxiangongsi|有限公司|\bco\.?,?\s*ltd\b.*\b(shenzhen|guangzhou|dongguan|guangdong)\b"
    r"|\b(shenzhen|guangzhou|dongguan|hangzhou|ningbo|yiwu|foshan)\b.*\bco\.?,?\s*ltd\b",
    re.I,
)
# Registered-agent mail drops. NOT a real address, and NOT a clearance. These go to Tim.
_MAIL_DROPS = (
    "30 n gould", "1309 coffeen", "124 broadkill", "8 the green",
    "1712 pioneer", "16192 coastal", "651 n broad",
)


def _load(folder: str) -> list[dict]:
    out: list[dict] = []
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))
                       + glob.glob(os.path.join(folder, "*.jsonl"))):
        with open(path, encoding="utf-8-sig") as f:
            text = f.read().strip()
        if not text:
            continue
        try:
            doc = json.loads(text)
            out += doc if isinstance(doc, list) else [doc]
            continue
        except json.JSONDecodeError:
            pass
        for line in text.splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def classify(name: str, addr: str) -> tuple[str, str]:
    """(verdict, why). The whole decision, in one place, mechanically."""
    blob = f"{name or ''} {addr or ''}"
    low = (addr or "").lower()

    if any(m in low for m in _MAIL_DROPS):
        return "MAILDROP", (
            "The Amazon seller is registered at a REGISTERED-AGENT MAIL DROP, which is not a real "
            "address and does not tell us who owns this company. Held for Tim."
        )
    if _CHINA_ENTITY.search(blob):
        return "CHINA", "The Amazon seller of record is a Chinese legal entity."
    if _CHINA_ADDRESS.search(blob):
        return "CHINA", (
            "The Amazon seller of record's registered business address is in China, Hong Kong or "
            "Macau. (Tim, 2026-07-14: 'hong kong IS chinese based.')"
        )
    if addr and addr.strip():
        return "NOT_CHINA", (
            "The Amazon seller of record's registered business address is outside China. This is a "
            "legally-compelled disclosure under the INFORM Consumers Act, not a self-declaration."
        )
    return "UNKNOWN", "No seller address found."


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dir", default=DEFAULT_DIR)
    args = ap.parse_args()

    rows = _load(args.dir)
    print(f"Loaded {len(rows)} seller records from {args.dir}\n")

    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    buckets: dict[str, list] = {"CHINA": [], "NOT_CHINA": [], "MAILDROP": [],
                                "UNKNOWN": [], "UNMATCHED": [], "JUNK": []}

    with psycopg.connect(url) as conn:
        conn.execute("SELECT set_config('app.current_tenant', %s, false)", (PS_TENANT,))

        for r in rows:
            brand = (r.get("brand") or "").strip()
            name = (r.get("seller_name") or "").strip()
            addr = (r.get("seller_address") or "").strip()
            src = r.get("seller_url") or ""
            if not brand:
                continue

            ids = conn.execute(
                """SELECT r.wayward_brand_id, r.reality FROM lens_ps_brand_reality r
                   WHERE lower(btrim(r.brand_name)) = lower(%s)""",
                (brand,),
            ).fetchall()
            if not ids:
                buckets["UNMATCHED"].append(brand)
                continue
            if all(x[1] == "JUNK" for x in ids):
                buckets["JUNK"].append(brand)
                continue

            verdict, why = classify(name, addr)
            buckets[verdict].append((brand, name, addr, src))

            if verdict not in ("CHINA", "NOT_CHINA") or not args.apply:
                continue

            points = "china" if verdict == "CHINA" else "not_china"
            value = "confirmed_yes" if verdict == "CHINA" else "confirmed_no"
            ev = (f"Amazon seller of record — Business Name: '{name}' — "
                  f"Business Address: '{addr}'. {why} Source: {src}")
            for bid, reality in ids:
                if reality == "JUNK":
                    continue
                # ONE signal: amazon_seller_entity. It is a LEGAL RECORD and an approved
                # confirming/legal indicator on its own (cip_88) — it carries the verdict with no
                # help. The old code ALSO wrote a companion manual_review row, which is the exact
                # "a machine wearing a human's authority" defect W1 (cip_87) removed: manual_review
                # is read first in the verdict and reads as "a person investigated this". A research
                # agent is not a person. Do not write it.
                conn.execute(
                    """INSERT INTO ps_nationality_signals
                         (tenant_id, wayward_brand_id, signal, strength, points_to,
                          evidence, source_system, asserted_by)
                       VALUES (%s,%s,'amazon_seller_entity','confirmed',%s,%s,
                               'amazon:seller_of_record','research agent')
                       ON CONFLICT DO NOTHING""",
                    (PS_TENANT, bid, points, ev),
                )
                conn.execute(
                    """INSERT INTO ps_added_facts
                         (tenant_id, subject_type, subject_id, field, value, rationale,
                          asserted_by, source_ref, pinned)
                       VALUES (%s,'brand',%s,'china_status',%s,%s,'research agent',%s,true)
                       ON CONFLICT DO NOTHING""",
                    (PS_TENANT, str(bid), value, ev, src or "amazon seller page"),
                )
        if args.apply:
            conn.commit()

    for k in ("CHINA", "NOT_CHINA"):
        print(f"{k} ({len(buckets[k])}):")
        for b, n, a, _s in buckets[k][:15]:
            print(f"   {b[:24]:<26}{n[:30]:<32}{a[:44]}")
        if len(buckets[k]) > 15:
            print(f"   ... and {len(buckets[k]) - 15} more")
        print()

    if buckets["MAILDROP"]:
        print("!" * 76)
        print(f"HELD FOR TIM — REGISTERED-AGENT MAIL DROP ({len(buckets['MAILDROP'])}).")
        print("Not a real address. Does NOT clear the brand. Nothing written.")
        print("!" * 76)
        for b, n, a, _s in buckets["MAILDROP"]:
            print(f"   {b[:24]:<26}{n[:30]:<32}{a}")
        print()

    for k in ("UNKNOWN", "UNMATCHED", "JUNK"):
        if buckets[k]:
            names = [x[0] if isinstance(x, tuple) else x for x in buckets[k]]
            print(f"{k} ({len(names)}): {', '.join(names[:20])}"
                  + (" ..." if len(names) > 20 else ""))

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
