# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Rebuild partner attribution from Wayward's own referral fields. Keyed on the brand.

Tim: "Then the Eric's sheet info, the Slack referral fields."

THREE THINGS WERE WRONG
-----------------------
1. COVERAGE. ps_partner_credit held 969 brands; the money spine has 1,955. So 1,605 brand x
   product rows carried no attribution at all — not "no partner", but no ROW. They could never
   be credited to anyone, and nobody would ever see them missing.

2. THE PHANTOM PARTNER. 'xq' and 'kerry' are the same person. XQ = Xueqiu = 雪球 = Snowball =
   Kerry's company (Snow ball, CN). The alias map routed 'referral(xq)' to an auto-created
   partner_id 'xq' rather than to the real registry row, so 150 brands were credited to a
   partner who does not exist, while the real Kerry row sat beside it holding 3. This is the
   same CJK-canonicalisation failure that nearly deleted 雪球 outright — it was fixed in the
   registry and left unfixed in the routing.

3. ONE COLUMN FOR TWO FACTS. deal_source ("whose book") and referral_source ("who referred")
   are different questions. cip_60 gives each its own column. A brand can be in Tim's book AND
   owe Kerry a cut — 50 brands are.

WHAT COUNTS AS A PARTNER
------------------------
Only the real roster earns. The Slack referral field has a long tail of 645 named "referrers"
that are overwhelmingly NOT partners — individual people, agencies, 'friend', 'colleague',
'ChatGPT', 'Reddit', email addresses. Those are how the brand HEARD of Wayward, not someone we
owe money to. They are recorded verbatim in deal_source_raw and resolve to 'unassigned', which
is a DECISION meaning "nobody is credited, PS keeps the full 10%" — never a silent gap.

WHAT WE DO NOT KNOW, AND DO NOT GUESS
-------------------------------------
Eric's sheet credits ~157 brands to two-letter codes — WE (88), WT (25), WX (19), VY (11),
WG (8), MA (6). We do not know who they are. They are NOT invented into partners and NOT
silently dropped: they are left unresolved, kept raw, and raised as a question for Eric/Jake.

Usage:
  DATABASE_URL=... python scripts/rebuild_partner_attribution.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
DECIDER = "rule:partner_attribution_v2"

# The real roster. Everything else is noise or an open question.
# Keys are matched case-insensitively against the referral text inside referral(...)/other(...).
PARTNER_MAP: dict[str, str] = {
    # Kerry / Snow ball / 雪球. THE MERGE: xq, XQ, Xueqiu and 雪球 are all one partner.
    "xq": "kerry",
    "xueqiu": "kerry",
    "雪球": "kerry",
    "雪球联盟": "kerry",
    "雪球站外分享": "kerry",
    "snowball": "kerry",
    "snow ball": "kerry",
    "kerry": "kerry",
    "kerrey": "kerry",
    # Adina
    "adina": "adina",
    # Cassie / C姐说品牌
    "cassie": "cassie",
    "c姐说品牌": "cassie",
    "c姐讲联盟": "cassie",
    # Sarah / S姐联盟营销  (SJ / SJWAYWARD = Sarah)
    "sarah": "sarah",
    "sj": "sarah",
    "sjwayward": "sarah",
    "s姐讲联盟": "sarah",
    "s姐联盟营销": "sarah",
    # Shallow / Thraive
    "shallow": "shallow",
    # Openlight / Jackie / Bella
    "openlight": "openlight",
    "bella": "openlight",
    "jackie": "openlight",
    "openlight-ledo": "openlight",
    "ledo": "openlight",
    # Eric
    "eric": "eric",
    # Others seen with real volume in the China book
    "chen": "chen",
    "chenqi": "chen",
    "caspar": "caspar",
    "dbzw": "dbzw",
}

# Eric's two-letter codes. REAL partners in his sheet, but we do not know who they are.
# Not invented, not dropped — held as an explicit unknown.
UNKNOWN_ERIC_CODES = {"we", "wt", "wx", "vy", "wg", "ma", "wj", "wd", "wr", "wn"}

_TAG = re.compile(r"^\s*(?:referral|other)\s*\(\s*(.*?)\s*\)\s*$", re.I | re.S)


def canon(raw: str | None) -> tuple[str | None, str]:
    """raw referral text -> (canonical partner_id | None, why).

    Returns None for the partner when nobody is owed anything, with the reason recorded.
    """
    if not raw or not raw.strip():
        return None, "no referral recorded"
    s = raw.strip()
    m = _TAG.match(s)
    inner = (m.group(1) if m else s).strip()
    key = inner.casefold()

    if key in PARTNER_MAP:
        return PARTNER_MAP[key], f"matched the partner roster on {inner!r}"
    if key in UNKNOWN_ERIC_CODES:
        return None, (
            f"Eric's sheet credits this to code {inner!r}, which we cannot decode. NOT guessed "
            f"and NOT dropped — raised as an open question for Eric/Jake."
        )
    # A self-serve marketing channel is not a partner.
    if not m or key in {
        "friend", "friends", "colleague", "colleagues", "na", "n/a", "no", "not",
        "other", "--", "1", "ai", "chatgpt", "chat gpt", "reddit", "agency",
    }:
        return None, "not a referral partner — a marketing channel or self-serve signup"
    return None, (
        f"{inner!r} is a one-off referrer (an individual, agency or community), not a partner "
        f"on our roster. Nobody is owed a commission; PS keeps the full rate."
    )


EVIDENCE = text("""
    SELECT b.wayward_brand_id,
           max(o.value) FILTER (WHERE o.field = 'deal_source')       AS deal_source,
           max(o.value) FILTER (WHERE o.field = 'referral_source')   AS slack_referral,
           max(o.value) FILTER (WHERE o.field = 'referrer')          AS eric_referrer,
           max(o.value) FILTER (WHERE o.field = 'eligible_for_10_rev_share') AS eligible_10,
           max(o.value) FILTER (WHERE o.field = 'brand_name')        AS brand_name
    FROM (SELECT DISTINCT wayward_brand_id FROM ps_monthly_earnings
           WHERE tenant_id = :t AND wayward_brand_id IS NOT NULL) b
    LEFT JOIN ps_brand_observations o
           ON o.wayward_brand_id = b.wayward_brand_id AND o.tenant_id = :t
    GROUP BY b.wayward_brand_id
""")

PRODUCTS = text("""
    SELECT DISTINCT wayward_brand_id, product_id
    FROM ps_monthly_earnings WHERE tenant_id = :t AND wayward_brand_id IS NOT NULL
""")

UPSERT = text("""
    INSERT INTO ps_partner_credit (
        tenant_id, wayward_brand_id, client_id, product_id,
        partner_of_record, deal_source, deal_source_raw, referral_detail_raw,
        deal_type, determined_by, determined_at, determination_note, match_status)
    VALUES (
        CAST(:t AS uuid), CAST(:wbid AS uuid),
        (SELECT id FROM cip_clients WHERE wayward_brand_id = CAST(:wbid AS uuid) LIMIT 1),
        :product,
        :partner, :deal_source, :raw, :raw,
        :deal_type, :by, now(), :note, :match_status)
    ON CONFLICT (tenant_id, wayward_brand_id, product_id)
        WHERE wayward_brand_id IS NOT NULL
    DO UPDATE SET
        partner_of_record  = EXCLUDED.partner_of_record,
        deal_source        = EXCLUDED.deal_source,
        deal_source_raw    = EXCLUDED.deal_source_raw,
        referral_detail_raw= EXCLUDED.referral_detail_raw,
        deal_type          = COALESCE(ps_partner_credit.deal_type, EXCLUDED.deal_type),
        determined_by      = EXCLUDED.determined_by,
        determined_at      = now(),
        determination_note = EXCLUDED.determination_note,
        match_status       = EXCLUDED.match_status
""")


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    ev = {
        str(r.wayward_brand_id): r
        for r in conn.execute(EVIDENCE, {"t": PS_TENANT}).fetchall()
    }
    pairs = conn.execute(PRODUCTS, {"t": PS_TENANT}).fetchall()

    from collections import Counter

    partners: Counter = Counter()
    reasons: Counter = Counter()
    unknown_codes: Counter = Counter()
    rows = []

    for wbid, product in pairs:
        e = ev.get(str(wbid))
        if e is None:
            continue
        # Slack's referral field first (Wayward's own onboarding record); Eric's sheet second.
        partner, why = canon(e.slack_referral)
        raw = e.slack_referral
        if partner is None and e.eric_referrer:
            p2, why2 = canon(e.eric_referrer)
            if p2:
                partner, why, raw = p2, f"{why2} (from Eric's sheet)", e.eric_referrer
            elif (e.eric_referrer or "").strip().casefold() in UNKNOWN_ERIC_CODES:
                why, raw = why2, e.eric_referrer
                unknown_codes[e.eric_referrer.strip()] += 1

        # deal_type: Eric's 'Eligible for 10% Rev Share' column. FALSE => flat fee.
        deal_type = None
        if e.eligible_10 is not None:
            v = str(e.eligible_10).strip().casefold()
            if v in {"false", "no", "0"}:
                deal_type = "flat_fee"
            elif v in {"true", "yes", "1"}:
                deal_type = "rev_share"

        resolved = partner or "unassigned"
        partners[resolved] += 1
        reasons[why] += 1
        rows.append({
            "t": PS_TENANT,
            "wbid": str(wbid),
            "product": product,
            "partner": resolved,
            "deal_source": e.deal_source,
            "raw": raw,
            "deal_type": deal_type,
            "by": DECIDER,
            "match_status": "confirmed" if partner else "unknown",
            "note": (
                f"deal_source={e.deal_source!r} (whose book, per Wayward). "
                f"partner_of_record={resolved!r}: {why}. "
                f"'unassigned' means nobody is credited and PS keeps the full rate — a DECISION, "
                f"not a gap."
            ),
        })

    out = {
        "brand_product_rows": len(rows),
        "partners_credited": dict(partners.most_common(12)),
        "eric_codes_we_cannot_decode": dict(unknown_codes),
    }
    if apply:
        conn.execute(UPSERT, rows)
        out["coverage_after"] = [
            dict(zip(("metric", "value"), r, strict=False))
            for r in conn.execute(text("""
                SELECT 'brands with a partner_credit row',
                       count(DISTINCT wayward_brand_id)::text FROM ps_partner_credit
                 WHERE tenant_id = :t
                UNION ALL SELECT 'rows with deal_source',
                       count(deal_source)::text FROM ps_partner_credit WHERE tenant_id = :t
                UNION ALL SELECT 'rows credited to a real partner',
                       count(*)::text FROM ps_partner_credit
                 WHERE tenant_id = :t AND partner_of_record <> 'unassigned'
            """), {"t": PS_TENANT}).fetchall()
        ]
    else:
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
