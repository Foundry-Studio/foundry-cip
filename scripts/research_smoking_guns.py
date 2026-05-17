# foundry: kind=script domain=research
"""Smoking-gun pass: tickets that combine fee-change + complaint patterns."""
from __future__ import annotations
import os, re, sys
from collections import defaultdict
from datetime import datetime
from sqlalchemy import create_engine, text

from cip.integration_mesh.wayward_constants import ECOMLEVER_TENANT_ID
TID = str(ECOMLEVER_TENANT_ID)  # EcomLever tenant; Wayward client_id 661ecab4-...
DATE_LO = "2026-02-01"
DATE_HI = "2026-05-16"

# Pairs of (fee-change signal, complaint signal). A ticket hitting BOTH is a smoking-gun candidate.
FEE_SIGNALS = [
    "fee structure", "fee change", "rate change", "rate adjustment", "rate increase",
    "3% to 5%", "from 5% to 3%", "usage fee rate", "ACC usage fee",
    "boosted publisher",
]
COMPLAINT_SIGNALS = [
    "didn't know", "wasn't informed", "no notice", "without notice", "didn't receive",
    "want credit", "want refund", "overcharge", "overpayment", "overcharged",
    "inaccurate", "discrepancy",
]

def snippet(t: str, lo: int, hi: int, ctx: int = 250) -> str:
    s = max(0, lo - ctx); e = min(len(t), hi + ctx)
    out = re.sub(r"\s+", " ", t[s:e]).strip()
    return ("…" if s > 0 else "") + out + ("…" if e < len(t) else "")

def main() -> int:
    url = os.environ["DATABASE_URL"]
    url = url.replace("postgresql://", "postgresql+psycopg://").replace("postgres://", "postgresql+psycopg://")
    e = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})

    fee_pats = [(s, re.compile(re.escape(s), re.IGNORECASE)) for s in FEE_SIGNALS]
    comp_pats = [(s, re.compile(re.escape(s), re.IGNORECASE)) for s in COMPLAINT_SIGNALS]

    # Tickets hitting (fee, complaint) in same body
    candidates: dict[str, dict] = {}  # source_id -> {ts, body_snippets, fee_hit, comp_hit}

    with e.connect() as c:
        for r in c.execute(text("""
            SELECT source_id, subject, description, valid_from, 'history' AS layer
            FROM cip_tickets_history
            WHERE tenant_id = :t AND source_connector = 'zendesk-v1'
              AND valid_from BETWEEN CAST(:lo AS timestamptz) AND CAST(:hi AS timestamptz)
            UNION ALL
            SELECT source_id, subject, description, COALESCE(refreshed_at, ingested_at), 'current' AS layer
            FROM cip_tickets
            WHERE tenant_id = :t AND source_connector = 'zendesk-v1'
        """), {"t": TID, "lo": DATE_LO, "hi": DATE_HI}):
            sid, subj, desc, ts, layer = r
            body = f"{subj or ''}\n{desc or ''}"
            fee_match = None; comp_match = None
            for name, pat in fee_pats:
                m = pat.search(body)
                if m:
                    fee_match = (name, m.start(), m.end()); break
            if not fee_match:
                continue
            for name, pat in comp_pats:
                m = pat.search(body)
                if m:
                    comp_match = (name, m.start(), m.end()); break
            if not comp_match:
                continue
            # Both hit. Capture.
            existing = candidates.get(sid)
            if existing and existing.get("ts") and ts and ts >= existing["ts"]:
                # Use the newer snapshot — fresher context
                pass
            else:
                if existing:
                    continue
            fname, fs, fe = fee_match
            cname, cs, ce = comp_match
            # Snippet around whichever match is later (often the complaint)
            anchor_lo = min(fs, cs); anchor_hi = max(fe, ce)
            snip = snippet(body, anchor_lo, anchor_hi, ctx=300)
            candidates[sid] = {
                "ts": ts, "layer": layer, "fee": fname, "comp": cname,
                "snip": snip,
            }

    # Sort by date
    ordered = sorted(candidates.items(),
                     key=lambda kv: kv[1]["ts"] or datetime.min.replace(tzinfo=None) if isinstance(kv[1]["ts"], datetime) else datetime.min)

    print(f"Found {len(ordered)} smoking-gun candidates (tickets hitting BOTH a fee-change signal AND a complaint signal):", file=sys.stderr)
    print()
    for sid, info in ordered:
        ts = info["ts"]; datestr = ts.strftime("%Y-%m-%d") if ts else "unknown"
        print(f'### Ticket #{sid} — {datestr} ({info["layer"]})')
        print(f'- Fee signal: `{info["fee"]}`  +  Complaint signal: `{info["comp"]}`')
        print(f'- Quote: "{info["snip"]}"')
        print()
    return 0

if __name__ == "__main__":
    sys.exit(main())
