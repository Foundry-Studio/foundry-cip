# foundry: kind=script domain=client-intelligence-platform
"""Ingest China-determination findings from the external research agent.

Reads every *.json / *.jsonl in the findings folder and writes:

    the EVIDENCE   -> ps_nationality_signals (amazon_seller_entity / uspto_trademark_owner)
    the DECISION   -> ps_added_facts, PINNED   -- only when the finding is strong enough

WHAT IT WILL NOT DO
-------------------
It will not decide on `UNRESOLVED`, and it will not decide on `weak`. Those are recorded as
evidence and listed for Tim. The research agent saying "I could not determine this" is a RESULT,
not a gap to be papered over with a guess.

It also refuses to touch JUNK rows (Wayward/Artica staff test accounts) — see lens_ps_brand_reality.

DUPLICATE ROWS
--------------
One company routinely has several ps_brands rows. A decision is about the BRAND, not the row, so a
finding is applied to EVERY row of that brand name. Skipping this is how "Grownsy" ended up with the
ruling pinned to a "Selgrownsy" row and nothing on the row actually named Grownsy.

Usage:
    python scripts/ingest_research_findings.py                    # dry run
    python scripts/ingest_research_findings.py --apply
    python scripts/ingest_research_findings.py --dir <path>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import psycopg

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
DEFAULT_DIR = (
    r"c:\Users\Tim Jordan\code\venture-ecomlever\clients\wayward"
    r"\china-commission-audit\research-handoff\findings"
)

# the agent's confidence vocabulary drifts (High / definitive / strong / weak). Normalise it.
_STRONG = {"definitive", "strong", "high", "confirmed"}


def _load(folder: str) -> list[dict]:
    out: list[dict] = []
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))
                       + glob.glob(os.path.join(folder, "*.jsonl"))):
        with open(path, encoding="utf-8-sig") as f:
            text = f.read().strip()
        if not text:
            continue
        try:                                   # a JSON array, or a single object
            doc = json.loads(text)
            out += doc if isinstance(doc, list) else [doc]
            continue
        except json.JSONDecodeError:
            pass
        for line in text.splitlines():         # JSONL
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dir", default=DEFAULT_DIR)
    args = ap.parse_args()

    findings = _load(args.dir)
    print(f"Loaded {len(findings)} findings from {args.dir}\n")

    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    decided, evidence_only, unmatched, skipped_junk, needs_tim = [], [], [], [], []

    with psycopg.connect(url) as conn:
        conn.execute("SELECT set_config('app.current_tenant', %s, false)", (PS_TENANT,))

        for f in findings:
            brand = (f.get("brand") or "").strip()
            if not brand:
                continue
            rows = conn.execute(
                """SELECT r.wayward_brand_id, r.reality, v.verdict
                   FROM lens_ps_brand_reality r
                   JOIN lens_ps_china_verdict v USING (wayward_brand_id)
                   WHERE lower(btrim(r.brand_name)) = lower(%s)""",
                (brand,),
            ).fetchall()
            if not rows:
                unmatched.append(brand)
                continue
            if all(r[1] == "JUNK" for r in rows):
                skipped_junk.append(brand)
                continue

            verdict = (f.get("verdict") or "").upper()
            conf = (f.get("confidence") or "").lower()
            strong = conf in _STRONG

            # the evidence, whatever the verdict — a legal record is worth keeping even when the
            # agent could not conclude from it.
            ev_bits = []
            if f.get("amazon_seller_name"):
                ev_bits.append(
                    ("amazon_seller_entity",
                     f"Amazon seller (INFORM Consumers Act disclosure): "
                     f"{f['amazon_seller_name']} — {f.get('amazon_seller_address') or 'no address'}")
                )
            if f.get("owner_entity"):
                ev_bits.append(
                    ("uspto_trademark_owner",
                     f"Trademark / registry owner: {f['owner_entity']} — "
                     f"{f.get('owner_address') or 'no address'}")
                )

            if verdict == "CHINA" and strong:
                points, value = "china", "confirmed_yes"
            elif verdict == "NOT_CHINA" and strong:
                points, value = "not_china", "confirmed_no"
            else:
                # UNRESOLVED, or a weak call.
                #
                # *** DO NOT WRITE A NATIONALITY SIGNAL HERE. ***
                # An earlier version of this script wrote the entity as a 'weak' signal with
                # points_to hard-coded to 'china'. The verdict view treats ANY china signal as a
                # verdict, so 'Aiming Fluid Golf' — a Chico, California business owned by Glenn
                # Peter Albert Jr. — came out CHINESE. An UNRESOLVED finding means the researcher
                # could not tell. It must not vote.
                #
                # The entity IS worth keeping, so it goes to ps_brand_observations, which is a
                # bucket of FACTS about a brand and carries no nationality opinion at all.
                evidence_only.append((brand, verdict, conf))
                if f.get("owner_entity") or f.get("amazon_seller_name"):
                    needs_tim.append(f)
                if args.apply:
                    for bid, reality, _v in rows:
                        if reality == "JUNK":
                            continue
                        for field, val in (
                            ("trademark_owner_entity", f.get("owner_entity")),
                            ("trademark_owner_address", f.get("owner_address")),
                            ("amazon_seller_name", f.get("amazon_seller_name")),
                            ("amazon_seller_address", f.get("amazon_seller_address")),
                        ):
                            if not val or val in ("N/A", "None"):
                                continue
                            conn.execute(
                                """INSERT INTO ps_brand_observations
                                     (tenant_id, wayward_brand_id, field, value, source_system,
                                      observed_at)
                                   VALUES (%s,%s,%s,%s,'research:external_agent_2026_07_14', now())
                                   ON CONFLICT DO NOTHING""",
                                (PS_TENANT, bid, field, val),
                            )
                continue

            why = (f"External research, 2026-07-14. {f.get('evidence') or ''} "
                   f"[method: {f.get('method') or '?'}] [source: {f.get('source_url') or '-'}]")
            decided.append((brand, verdict, conf, f.get("owner_entity")))

            if args.apply:
                for bid, reality, _v in rows:
                    if reality == "JUNK":
                        continue
                    for sig, txt in ev_bits:
                        conn.execute(
                            """INSERT INTO ps_nationality_signals
                                 (tenant_id, wayward_brand_id, signal, strength, points_to,
                                  evidence, source_system, asserted_by)
                               VALUES (%s,%s,%s,'confirmed',%s,%s,
                                       'research:external_agent_2026_07_14','research agent')
                               ON CONFLICT DO NOTHING""",
                            (PS_TENANT, bid, sig, points, txt),
                        )
                    conn.execute(
                        """INSERT INTO ps_nationality_signals
                             (tenant_id, wayward_brand_id, signal, strength, points_to,
                              evidence, source_system, asserted_by)
                           VALUES (%s,%s,'manual_review','confirmed',%s,%s,
                                   'research:external_agent_2026_07_14','research agent')
                           ON CONFLICT DO NOTHING""",
                        (PS_TENANT, bid, points, why),
                    )
                    conn.execute(
                        """INSERT INTO ps_added_facts
                             (tenant_id, subject_type, subject_id, field, value, rationale,
                              asserted_by, source_ref, pinned)
                           VALUES (%s,'brand',%s,'china_status',%s,%s,'research agent',%s,true)""",
                        (PS_TENANT, str(bid), value, why,
                         f.get("source_url") or "external research 2026-07-14"),
                    )
        if args.apply:
            conn.commit()

    print(f"DECIDED ({len(decided)}):")
    for b, v, c, e in decided:
        print(f"   {v:<10}{c:<12}{b[:24]:<26}{(e or '')[:40]}")
    print(f"\nEVIDENCE ONLY — no decision made ({len(evidence_only)}):")
    for b, v, c in evidence_only:
        print(f"   {v:<12}{c:<8}{b}")
    if unmatched:
        print(f"\nBRAND NAME NOT FOUND IN ps_brands ({len(unmatched)}): {', '.join(unmatched)}")
    if skipped_junk:
        print(f"\nSKIPPED — JUNK rows ({len(skipped_junk)}): {', '.join(skipped_junk)}")

    if needs_tim:
        print("\n" + "=" * 78)
        print("UNRESOLVED, BUT THE ENTITY IS RIGHT THERE — Tim should look at these:")
        print("=" * 78)
        for f in needs_tim:
            print(f"\n   {f['brand']}")
            print(f"      trademark owner : {f.get('owner_entity')} — {f.get('owner_address')}")
            print(f"      amazon seller   : {f.get('amazon_seller_name')} — {f.get('amazon_seller_address')}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
