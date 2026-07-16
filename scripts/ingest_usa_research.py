# foundry: kind=script domain=client-intelligence-platform
"""Ingest the ownership-research findings for the REVIEW_USA dwindle. One command per chunk.

TIM, 2026-07-14: "keep working like this, manually chunking... make sure the ones you are confident
as US or others are flipped confirmed to not chinese."

Each research chunk (a subagent) writes usa*_result_N.json — one object per brand with a verdict,
the owning entity, its country, and a SOURCE. This script classifies and applies them, with the
same discipline I have been doing by hand:

    CHINA        -> confirmed_yes   (a Chinese company, or a Chinese owner behind a US shell)
    NOT_CHINA    -> confirmed_no    (a real non-China corporate identity, WITH a source)
    borderline   -> HELD for Tim    (a bare Wyoming/Delaware mail-drop, or 'moderate confidence',
                                     or no source — a wrong not_china costs us money)
    UNRESOLVED   -> left unknown

WHY A SCRIPT AND NOT INLINE SQL EACH TIME
-----------------------------------------
Sixteen more chunks to go. Retyping the classify/flip/guard/re-derive logic by hand every time is
sixteen more chances for a typo mid-flip. This is the tested path.

THE TWO RULES IT ENFORCES MECHANICALLY
--------------------------------------
1. THE GUARD: the confirmed-China book may only GROW. If applying a chunk would REDUCE the number
   of china companies, it ROLLS BACK — a research chunk must never quietly un-China a brand. (Adding
   china or not_china to an UNKNOWN is fine; that is all these chunks do.)
2. RE-DERIVE is_chinese after every flip. The money spine's is_chinese is DERIVED from the verdict
   (cip_90); a flip leaves it stale until re-derived, and the spine_is_chinese_matches_verdict
   invariant will (correctly) fail if you forget. This does it for you.

    python scripts/ingest_usa_research.py "usa2_result_*.json"            # dry run
    python scripts/ingest_usa_research.py "usa2_result_*.json" --apply
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import psycopg

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
SCRATCH = (
    r"C:\Users\TIMJOR~1\AppData\Local\Temp\claude"
    r"\c--Users-Tim-Jordan-code--pytest-cache"
    r"\a43d95d1-18b1-4a9c-b75b-5b4da7efca8d\scratchpad"
)
_BORDERLINE = (
    "mail-drop", "mail drop", "moderate confidence", "registered-agent", "registered agent",
    "no address", "could not", "unable to", "shell with no",
)


def classify(x: dict) -> str:
    v = (x.get("verdict") or "").upper()
    src = (x.get("source_url") or "").strip()
    if v == "CHINA":
        return "china"
    if v == "NOT_CHINA":
        if not src or src in ("N/A", "None", "-"):
            return "hold"
        blob = f"{x.get('evidence','')} {x.get('hq','')} {x.get('owner_entity','')}".lower()
        if any(w in blob for w in _BORDERLINE):
            return "hold"
        return "not_china"
    return "skip"  # UNRESOLVED / anything else


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", help="glob of result files, e.g. 'usa2_result_*.json'")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    paths = sorted(glob.glob(args.pattern) or glob.glob(os.path.join(SCRATCH, args.pattern)))
    if not paths:
        print(f"no files matched {args.pattern}")
        return 1
    findings: list[dict] = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            findings += json.load(f)
    print(f"loaded {len(findings)} findings from {len(paths)} file(s)\n")

    buckets: dict[str, list] = {"china": [], "not_china": [], "hold": [], "skip": []}
    for x in findings:
        buckets[classify(x)].append(x)
    for k in ("china", "not_china", "hold", "skip"):
        names = [x.get("brand") for x in buckets[k]]
        shown = ", ".join(str(n) for n in names[:12]) + (" ..." if len(names) > 12 else "")
        print(f"   {k:<10}{len(names):>3}  {shown}")
    print()

    if not args.apply:
        print("DRY RUN — nothing written. Re-run with --apply")
        # still surface the hold list so Tim can see it
        if buckets["hold"]:
            print("\nHELD FOR TIM:")
            for x in buckets["hold"]:
                ev = (x.get("evidence") or "")[:80]
                print(f"   {x.get('brand'):<24}{x.get('owner_entity')}  — {ev}")
        return 0

    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        conn.execute("SELECT set_config('app.current_tenant', %s, false)", (PS_TENANT,))
        cn_before = conn.execute(
            "SELECT count(*) FROM lens_ps_china_companies "
            "WHERE reality='REAL' AND verdict='china'"
        ).fetchone()[0]

        def rows_for(name: str) -> list:
            return [r[0] for r in conn.execute(
                """SELECT DISTINCT b2.wayward_brand_id FROM ps_brands b
                   JOIN ps_brands b2
                     ON COALESCE(b2.canonical_brand_id, b2.wayward_brand_id)
                      = COALESCE(b.canonical_brand_id, b.wayward_brand_id)
                   WHERE lower(btrim(b.brand_name)) = lower(btrim(%s))""", (name,)).fetchall()]

        def decided(bid) -> bool:
            return bool(conn.execute(
                "SELECT 1 FROM ps_added_facts WHERE subject_id=%s::text "
                "AND field='china_status' AND superseded_by IS NULL", (str(bid),)).fetchone())

        applied = {"china": 0, "not_china": 0}
        unmatched: list[str] = []
        for pt, points, value, strength in (("china", "china", "confirmed_yes", "confirmed"),
                                            ("not_china", "not_china", "confirmed_no", "negative")):
            for x in buckets[pt]:
                ids = rows_for(x["brand"])
                if not ids:
                    unmatched.append(x["brand"])
                    continue
                shell = (" The US-facing entity is a shell over a Chinese owner."
                         if pt == "china" else "")
                why = (f"Web research 2026-07-14 (Tim-delegated). Operating entity: "
                       f"{x.get('owner_entity')} — {x.get('hq') or x.get('country')}.{shell} "
                       f"{x.get('evidence', '')} Source: {x.get('source_url')}")[:900]
                for bid in ids:
                    if decided(bid):
                        continue
                    conn.execute(
                        """INSERT INTO ps_nationality_signals
                             (tenant_id, wayward_brand_id, signal, strength, points_to,
                              evidence, source_system, asserted_by)
                           VALUES (%s,%s,'manual_review',%s,%s,%s,
                                   'web:usa_research_2026_07_14',
                                   'Claude (web research, Tim-delegated)')
                           ON CONFLICT DO NOTHING""",
                        (PS_TENANT, bid, strength, points, why))
                    conn.execute(
                        """INSERT INTO ps_added_facts
                             (tenant_id, subject_type, subject_id, field, value, rationale,
                              asserted_by, source_ref, pinned)
                           VALUES (%s,'brand',%s,'china_status',%s,%s,
                                   'Claude (web research, Tim-delegated)',%s,true)
                           ON CONFLICT DO NOTHING""",
                        (PS_TENANT, str(bid), value, why, x.get("source_url") or "web research"))
                applied[pt] += 1

        # (cip_110: the old "re-derive is_chinese on the ps_monthly_earnings spine" step is gone.
        #  The frozen spine was retired; is_chinese now has one LIVE home, lens_ps_china_verdict,
        #  recomputed off ps_nationality_signals as soon as a flip lands. Nothing to backfill.)

        cn_after = conn.execute(
            "SELECT count(*) FROM lens_ps_china_companies "
            "WHERE reality='REAL' AND verdict='china'"
        ).fetchone()[0]

        # THE GUARD: the china book may only grow.
        if cn_after < cn_before:
            conn.rollback()
            print(f"\n*** ROLLED BACK: china companies {cn_before} -> {cn_after}. A research chunk "
                  f"must never REDUCE the China book. ***")
            return 2
        conn.commit()

        print(f"applied: {applied['not_china']} -> not_china, {applied['china']} -> china")
        if unmatched:
            print(f"name not matched (check spelling vs ps_brands): {unmatched}")
        print(f"GUARD OK: china {cn_before} -> {cn_after} (grew by the CHINA flips)")
        for v, n in conn.execute(
            "SELECT verdict, count(*) FROM lens_ps_china_companies "
            "WHERE reality='REAL' GROUP BY 1 ORDER BY 2 DESC").fetchall():
            print(f"   {v:<12}{n}")
        if buckets["hold"]:
            hp = os.path.join(SCRATCH, "hold_for_tim.json")
            existing = []
            if os.path.exists(hp):
                with open(hp, encoding="utf-8") as f:
                    existing = json.load(f)
            seen = {h.get("brand") for h in existing}
            existing += [x for x in buckets["hold"] if x.get("brand") not in seen]
            with open(hp, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=1)
            print(f"   {len(buckets['hold'])} held -> {hp} ({len(existing)} total for Tim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
