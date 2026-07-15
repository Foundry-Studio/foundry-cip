# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Turn every UNKNOWN and CONFLICT into a workable question, routed to who can answer it.

An unknown is not a dead end — it is a task (Tim, 2026-07-13). This sweeps the decision
layers for everything they could not resolve and files each one as a row in
ps_information_gaps: the question in words, who to ask, and which decision is stuck
behind it.

The output is designed to be worked three ways, all of which Tim named:
  - a filtered REPORT ("show me every brand needing info")
  - an LLM-rendered QUESTIONNAIRE (one sheet per person, all their brands at once)
  - a SLACK AGENT that DMs the right person and writes the answer back

Routing (who can actually answer):
  referrer_unknown / referrer_conflict -> the China ops team (Rhea) — they know who
                                          brought a brand; Wayward often does not.
  contact_missing (WeChat)             -> Jake (capture at onboarding)

Usage:
  DATABASE_URL=... python scripts/detect_information_gaps.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

# (gap_type, ask_who, ask_channel, priority, blocks, question_sql, context_sql, where)
DETECTORS: list[dict] = [
    {
        "gap_type": "referrer_conflict",
        "ask_who": "rhea",
        "ask_channel": "slack",
        "priority": 1,
        "blocks": "partner_of_record -> who we pay the 5%",
        "sql": """
            SELECT c.id, c.wayward_brand_id, c.name,
                   'Who actually referred ' || c.name || '? A partner claims it, but '
                   || 'Wayward credits someone else. We need the truth before we pay '
                   || 'anyone.' AS question,
                   'Partner claim on file: ' || string_agg(DISTINCT o.source_system, ', ')
                   AS context
            FROM cip_clients c
            JOIN ps_brand_observations o
              ON o.client_id = c.id AND o.source_system LIKE 'partner_claim:%'
             AND o.field = 'claimed_referrer'
            WHERE c.tenant_id = :t
              AND EXISTS (
                  SELECT 1 FROM ps_brand_observations w
                  WHERE w.wayward_brand_id = o.wayward_brand_id
                    AND w.field = 'referrer'
                    AND lower(w.value) NOT IN (
                        SELECT lower(a.alias_value) FROM ps_partner_aliases a
                        WHERE a.partner_id = o.value)
              )
            GROUP BY c.id, c.wayward_brand_id, c.name
        """,
    },
    {
        "gap_type": "referrer_unknown",
        "ask_who": "rhea",
        "ask_channel": "slack",
        "priority": 2,
        "blocks": "partner_of_record -> whether a partner is owed 5%",
        "sql": """
            SELECT c.id, c.wayward_brand_id, c.name,
                   'Who referred ' || c.name || '? Nobody has claimed it and Wayward has '
                   || 'no referrer on record.' AS question,
                   'A partner claimed it but Wayward shows no referrer at all.' AS context
            FROM cip_clients c
            JOIN ps_brand_observations o
              ON o.client_id = c.id AND o.source_system LIKE 'partner_claim:%'
            WHERE c.tenant_id = :t
              AND NOT EXISTS (
                  SELECT 1 FROM ps_brand_observations w
                  WHERE w.wayward_brand_id = o.wayward_brand_id AND w.field = 'referrer')
              AND NOT EXISTS (
                  SELECT 1 FROM ps_brand_observations d
                  WHERE d.wayward_brand_id = o.wayward_brand_id AND d.field = 'deal_source')
            GROUP BY c.id, c.wayward_brand_id, c.name
        """,
    },
]


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    found = {}
    for d in DETECTORS:
        rows = conn.execute(text(d["sql"]), {"t": PS_TENANT}).fetchall()
        found[d["gap_type"]] = {"count": len(rows), "ask_who": d["ask_who"]}
        if not apply or not rows:
            continue
        payload = [
            {
                "t": PS_TENANT, "cid": str(r[0]),
                "wbid": str(r[1]) if r[1] else None,
                "label": r[2], "q": r[3], "ctx": r[4],
                "gt": d["gap_type"], "who": d["ask_who"], "ch": d["ask_channel"],
                "pri": d["priority"], "blocks": d["blocks"],
            }
            for r in rows
        ]
        for i in range(0, len(payload), 500):
            conn.execute(
                text(
                    """
                    INSERT INTO ps_information_gaps (
                        tenant_id, client_id, wayward_brand_id, subject_label,
                        gap_type, question, context, ask_who, ask_channel,
                        priority, blocks
                    ) VALUES (
                        :t, CAST(:cid AS uuid), CAST(:wbid AS uuid), :label,
                        :gt, :q, :ctx, :who, :ch, :pri, :blocks
                    )
                    ON CONFLICT (tenant_id, wayward_brand_id, gap_type) DO NOTHING
                    """
                ),
                payload[i:i + 500],
            )

    out = {"detected": found, "applied": apply}
    if apply:
        out["worklist"] = [
            {"ask_who": r[0], "channel": r[1], "gap": r[2], "open": r[3]}
            for r in conn.execute(
                text(
                    "SELECT ask_who, ask_channel, gap_type, open_questions "
                    "FROM lens_ps_open_questions"
                )
            ).fetchall()
        ]
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
