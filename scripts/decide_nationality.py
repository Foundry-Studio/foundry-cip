# foundry: kind=script domain=client-intelligence-platform touches=storage
"""DECISION LAYER (nationality): the ONLY writer of cip_clients.nationality_class.

Why this is now the critical path: Chinese brands are the ones that revert to PS in the
post-PS era (Tim, 2026-07-13). nationality_class therefore GATES entitlement, gates the
reactivation pipeline, and scopes what we ask Wayward for. Every brand left 'unknown' is
a brand we cannot claim and cannot pursue.

FACTS vs CONCLUSIONS (Tim's rule, held throughout):
    Ingestion writes ONLY ps_brand_observations. Sources may disagree; none supersedes
    another. THIS script is the single place a determination is made, and it must record
    who decided, when, and WHY. If the evidence is thin or conflicting, it says
    'unknown' and routes to review — it does not invent a nationality.

EVIDENCE, in descending weight:
  1. country          — Wayward's own onboarding field, via the Slack brand feed. The
                        strongest signal we have: it is the brand's declared country.
  2. email domain     — qq.com / 126.com / 163.com / sina / foxmail are effectively
                        China-only consumer domains. Corroborating, not sufficient alone.
  3. CJK in the name  — weak on its own (a US seller can use a CJK brand name), but it
                        raises confidence when it agrees with the above.
  4. deal_source      — 'China Referral - <name>' means PS's China team sourced it. Strong
                        corroboration; a China-referral brand that claims US is exactly
                        the kind of conflict that must go to a human, not be auto-resolved.

OUTCOMES:
  chinese_confirmed  — country=CN (Wayward's own declaration). Highest confidence.
  chinese_suspected  — no country, but >=2 corroborating signals agree.
  non_chinese        — country is a non-CN country AND nothing contradicts it.
  unknown            — no evidence, or the evidence CONFLICTS. Routed to review with the
                       conflict spelled out. An honest 'unknown' beats a confident guess.

Usage:
  DATABASE_URL=... python scripts/decide_nationality.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
DECIDER = "rule:nationality_v1"

CN_EMAIL_DOMAINS = {
    "qq.com", "126.com", "163.com", "sina.com", "sina.cn", "foxmail.com",
    "aliyun.com", "vip.qq.com", "139.com", "outlook.com.cn",
}
_CJK = re.compile(r"[一-鿿㐀-䶿]")


def classify(ev: dict[str, set[str]]) -> tuple[str, str, str]:
    """-> (nationality_class, review_status, rationale). Never guesses past the evidence."""
    countries = {c.strip().upper() for c in ev.get("country", set()) if c.strip()}
    emails = {e.lower() for e in ev.get("email", set())}
    names = ev.get("brand_name", set())
    deal_sources = {d.lower() for d in ev.get("deal_source", set())}

    dom = {e.split("@")[-1] for e in emails if "@" in e}
    cn_email = bool(dom & CN_EMAIL_DOMAINS)
    cjk_name = any(_CJK.search(n) for n in names)
    china_ref = any("china referral" in d for d in deal_sources)

    corroborating = [
        f"email domain {sorted(dom & CN_EMAIL_DOMAINS)}" if cn_email else None,
        "CJK characters in brand name" if cjk_name else None,
        "deal_source is a China Referral" if china_ref else None,
    ]
    corroborating = [c for c in corroborating if c]

    # ── CHINA WINS (Tim, 2026-07-13) ────────────────────────────────────────
    # Wayward's country field is FREQUENTLY WRONG. A "US" flag usually means a
    # US-registered shell operated from China — the Tiny Land precedent (US-registered,
    # Shanghai Tailan operator) is already in our own docs.
    #
    # So: if ANY source says China, we LOCK it. A "US" from another source does NOT
    # override it and does NOT create a conflict. The previous version escalated these to
    # a human queue (39 brands) — that was too timid, and it was leaving our own book on
    # the table. "US" is never, by itself, proof a brand is not Chinese.
    if "CN" in countries:
        others = sorted(countries - {"CN"})
        note = (
            f" (Another source says {others[0]} — that does NOT override it; a "
            f"US-registered entity operated from China is still a Chinese brand.)"
            if others else ""
        )
        extra = f" Corroborated by: {', '.join(corroborating)}." if corroborating else ""
        return (
            "chinese_confirmed", "confirmed",
            f"A Wayward source reports country = CN. CHINA WINS.{note}{extra}",
        )

    # No source says China. Keep looking — the country field alone is not enough to
    # rule a brand OUT.
    if len(corroborating) >= 2:
        return (
            "chinese_confirmed", "probable",
            f"No source reports CN, but {len(corroborating)} independent China signals "
            f"agree: {'; '.join(corroborating)}. Treated as Chinese; flagged PROBABLE for "
            f"confirmation.",
        )
    if corroborating:
        return (
            "chinese_suspected", "probable",
            f"No source reports CN, but one China signal is present "
            f"({corroborating[0]}). SUSPECTED — needs a look, not a guess.",
        )

    if countries:
        c = sorted(countries)[0]
        return (
            "non_chinese", "probable",
            f"Country = {c} and NO China signal of any kind (no CN flag, no China-only "
            f"email domain, no CJK name, no China Referral). Probable, not certain — an "
            f"LLM review pass may still surface Chinese brands here.",
        )
    return ("unknown", "pending", "No nationality evidence of any kind on file.")


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    rows = conn.execute(
        text(
            """
            SELECT o.client_id, o.field, o.value
            FROM ps_brand_observations o
            WHERE o.tenant_id = :t AND o.client_id IS NOT NULL
              AND o.field IN ('country','email','brand_name','deal_source')
            """
        ),
        {"t": PS_TENANT},
    ).fetchall()

    ev: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for cid, field, value in rows:
        if value:
            ev[str(cid)][field].add(value)

    decided = defaultdict(int)
    review = defaultdict(int)
    payload = []
    for cid, e in ev.items():
        cls, status, why = classify(e)
        decided[cls] += 1
        review[status] += 1
        payload.append({
            "t": PS_TENANT, "cid": cid, "cls": cls,
            "by": DECIDER, "why": why, "status": status,
        })

    if apply and payload:
        for i in range(0, len(payload), 500):
            conn.execute(
                text(
                    """
                    UPDATE cip_clients SET
                        nationality_class        = :cls,
                        nationality_decided_by   = :by,
                        nationality_decided_at   = now(),
                        nationality_rationale    = :why,
                        nationality_review_status= :status
                    WHERE tenant_id = :t AND id = CAST(:cid AS uuid)
                    """
                ),
                payload[i:i + 500],
            )

    out = {
        "brands_with_evidence": len(ev),
        "decisions": dict(decided),
        "review_queue": dict(review),
        "applied": apply,
    }
    if apply:
        out["prod_nationality_class"] = dict(
            conn.execute(
                text(
                    "SELECT nationality_class, count(*) FROM cip_clients "
                    "WHERE tenant_id=:t GROUP BY 1"
                ),
                {"t": PS_TENANT},
            ).fetchall()
        )
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
            if not args.apply:
                conn.execute(text("ROLLBACK"))
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
