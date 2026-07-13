# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Seed ps_partner_aliases: every raw partner string a source ever wrote -> ONE partner.

Without this map the same human is credited more than once: XQ / xq / referral(xq) /
UTM 'xq' are four spellings of one person.

Tim's rulings (2026-07-13):
  1. 'Eric - Organic' / 'Eric - Social Media' / 'Eric - Event' are METADATA, not
     meaningful channel tags. They are ALL Eric.
  2. CJK names must NEVER be destroyed. (An earlier canonicalizer stripped non-ASCII and
     collapsed 同事 / 雪球 / 雪球站外分享 to an EMPTY id. That bug also HID a real merge:
     雪球 IS Xueqiu — the same partner already present as 'xueqiu'/'Xueqiu'. Destroying
     characters does not just lose data, it invents and hides identities.)
  3. Referral TYPES (friend, colleague, event, NA, ...) are not partners. They resolve to
     'unassigned' — a decision meaning nobody is credited and PS keeps the full 10%.
  4. UTM codes and display names of the same partner merge (utm 'we' == display 'WE').

The raw value is ALWAYS preserved verbatim in ps_brand_observations. This script only
builds the resolution layer on top, so both the raw truth and the resolved identity live.

Usage:
  DATABASE_URL=... python scripts/seed_partner_aliases.py [--apply]   (default: dry-run)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

# Referral TYPES, not people. -> 'unassigned' (nobody credited; PS keeps the full 10%).
TYPES = {
    "word-of-mouth", "social-media", "google/search-engine", "email-newsletter",
    "event-trade-show", "other", "online-forum-community", "referral", "referral(cc)",
    "friend", "colleague", "event", "na", "n/a", "c", "s", "cc",
    "同事",           # "colleague"
    "eric - organic",  # NOTE: overridden below — Tim ruled this IS Eric (rule 1)
}
TYPES.discard("eric - organic")

# Known CJK -> canonical identity. NEVER strip CJK; map it deliberately.
CJK_MAP = {
    "雪球": "xueqiu",             # Xueqiu — same partner as the ASCII 'xueqiu'/'Xueqiu'
    "雪球站外分享": "xueqiu",       # "Xueqiu off-site sharing" — still Xueqiu
    "同事": "_TYPE",               # "colleague" — a type, not a person
    "S姐": "s",                    # "Sister S"
}

_KIND_BY_FIELD = {
    "referrer": "display_name",
    "utm_campaign": "utm_campaign",
    "referral_source": "referral_tag",
}


def canon(raw: str) -> str:
    """Raw string -> canonical partner_id. NEVER returns empty (asserted)."""
    s = raw.strip()

    # referral(xq) -> xq
    m = re.fullmatch(r"referral\s*\((.*?)\)", s, re.I)
    if m:
        s = m.group(1).strip()

    if s in CJK_MAP:
        s = CJK_MAP[s]
    if s == "_TYPE" or s.strip().lower() in TYPES:
        return "unassigned"

    low = s.lower()

    # Rule 1 (Tim): every 'Eric - <anything>' is just Eric.
    if re.match(r"^eric\b", low):
        return "eric"

    # ASCII slug — but ONLY if that leaves something. Never destroy CJK.
    slug = re.sub(r"[^a-z0-9]+", "_", low).strip("_")
    if slug:
        return slug

    # Non-ASCII (CJK etc.) with no explicit mapping: KEEP IT. A partner we cannot
    # spell in ASCII is still a partner — losing them is worse than an odd-looking id.
    kept = unicodedata.normalize("NFKC", s).strip()
    if not kept:
        raise ValueError(f"canon() would return empty for {raw!r} — refusing to lose it")
    return kept


def main(argv: list[str] | None = None) -> int:
    # We deliberately carry CJK partner ids through; the Windows console defaults to
    # cp1252 and would raise on them. Force UTF-8 rather than mangle the names.
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
    groups: dict[str, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": PS_TENANT},
            )
            for field, kind in _KIND_BY_FIELD.items():
                rows = conn.execute(
                    text(
                        "SELECT value, count(DISTINCT wayward_brand_id) "
                        "FROM ps_brand_observations WHERE tenant_id=:t AND field=:f "
                        "GROUP BY 1"
                    ),
                    {"t": PS_TENANT, "f": field},
                ).fetchall()
                for raw, n in rows:
                    if not raw or not raw.strip():
                        continue
                    # a bare 'referral' with no name carries no identity
                    if field == "referral_source" and not re.match(
                        r"referral\s*\(", raw, re.I
                    ):
                        if raw.strip().lower() not in TYPES:
                            continue
                    groups[canon(raw)][(kind, raw.strip())] += n

            partners = {p: v for p, v in groups.items() if p != "unassigned"}

            if args.apply:
                for pid in partners:
                    conn.execute(
                        text(
                            "INSERT INTO ps_partner_registry "
                            "(tenant_id, partner_id, name, status, notes) "
                            "VALUES (:t,:p,:n,'active',:note) "
                            "ON CONFLICT (tenant_id, partner_id) DO NOTHING"
                        ),
                        {
                            "t": PS_TENANT, "p": pid, "n": pid,
                            "note": "auto-seeded from observed referrer/UTM values; "
                                    "confirm company + contacts",
                        },
                    )
                rows = [
                    {
                        "t": PS_TENANT, "p": pid, "v": raw, "k": kind,
                        "s": "seed_partner_aliases.py",
                    }
                    for pid, aliases in groups.items()
                    for (kind, raw) in aliases
                ]
                conn.execute(
                    text(
                        "INSERT INTO ps_partner_aliases "
                        "(tenant_id, partner_id, alias_value, alias_kind, source) "
                        "VALUES (:t,:p,:v,:k,:s) "
                        "ON CONFLICT (tenant_id, alias_kind, alias_value) DO NOTHING"
                    ),
                    rows,
                )
    finally:
        engine.dispose()

    ranked = sorted(groups.items(), key=lambda kv: -sum(kv[1].values()))
    print(json.dumps({
        "canonical_partners": len(partners),
        "alias_rows": sum(len(v) for v in groups.values()),
        "applied": args.apply,
        "top": [
            {
                "partner_id": pid,
                "brands": sum(a.values()),
                "aliases": sorted({f"{k}:{v}" for (k, v) in a}),
            }
            for pid, a in ranked[:12]
        ],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
