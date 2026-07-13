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

    # Sources disagree about the country itself -> a human decides. Never auto-resolve.
    if len(countries) > 1:
        return (
            "unknown", "escalated",
            f"CONFLICT: sources disagree on country {sorted(countries)}. "
            f"Not auto-resolved — a determination here would be a guess. "
            f"Corroborating signals: {corroborating or 'none'}.",
        )

    if countries == {"CN"}:
        extra = f" Corroborated by: {', '.join(corroborating)}." if corroborating else ""
        return (
            "chinese_confirmed", "confirmed",
            f"Wayward's own onboarding country = CN (slack:amazon-brand-connections)."
            f"{extra}",
        )

    if countries and "CN" not in countries:
        c = sorted(countries)[0]
        if corroborating:
            return (
                "unknown", "escalated",
                f"CONFLICT: Wayward's country says {c}, but {len(corroborating)} China "
                f"signal(s) disagree ({'; '.join(corroborating)}). A China-referred brand "
                f"declaring {c} needs a human, not a rule.",
            )
        return (
            "non_chinese", "confirmed",
            f"Wayward's own onboarding country = {c}, and no China signal contradicts it.",
        )

    # No country field at all — fall back to corroboration only.
    if len(corroborating) >= 2:
        return (
            "chinese_suspected", "pending",
            f"No country on file. {len(corroborating)} independent China signals agree: "
            f"{'; '.join(corroborating)}. SUSPECTED, not confirmed — needs review.",
        )
    if corroborating:
        return (
            "unknown", "pending",
            f"No country on file. Only one weak China signal ({corroborating[0]}) — "
            f"insufficient to determine. Left unknown deliberately.",
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
