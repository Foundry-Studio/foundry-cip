# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Purge the questions built on a false premise. Phase 0 of the data-first reset.

Some of what we queued for Jake was WRONG TO ASK — not merely low-value, but embarrassing:

  "Can you export the country field for 625 brands?"
      ...while cip_companies holds 132,311 HubSpot company records WITH A COUNTRY FIELD, in this
      same database, synced hourly, and we had never read one of them. Asking a client for data
      you already hold is how you lose their patience and your credibility at the same time.

  "Please confirm the country for these 9 brands — 73% of our claim rests on them."
      ...money-framed (frozen), and built on the premise I invented: that a brand we could not
      corroborate FROM MY OWN TABLES was a brand we "could not prove". Tim's answer to that was
      the correct one.

  69 x "Was this brand billed but never paid?"
      ...money questions. Money work is frozen; the ownership rules have changed underneath them
      (doc 15 §5), so every one of these would be re-derived anyway.

WHAT SURVIVES — the questions that are about DATA WE GENUINELY DO NOT HAVE:
  - the 137 Stripe customers with no brandId anywhere (and the 337 where Wayward wrote the UUID
    into `description` instead of metadata.brandId — worth telling them so it stops)
  - Eric's undecodable two-letter referrer codes (WE / WT / WX / VY / WG / MA)
  - WeChat ids (Jake has been collecting them)
  - per-brand monthly SALES — needed for dormancy, which is a DATA question, not a money one
  - the 31 brands where Wayward's own country field contradicts their own exclusion list
    (this one we give BACK to them — a correction, not a request)

  - and the 39 nationality questions for Tim, which are exactly the PROBABLE research queue.

Usage:
  DATABASE_URL=... python scripts/purge_bad_questions_2026_07_14.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

# We ALREADY HOLD this data. Asking for it was the error, not the answer.
KILL_WE_ALREADY_HAVE_IT = text("""
    UPDATE ps_information_gaps
       SET status = 'abandoned',
           answered_at = now(),
           answered_by = 'internal:data-first-reset',
           answer =
             'WITHDRAWN — WE ALREADY HOLD THIS DATA. cip_companies contains 132,311 HubSpot '
             'company records WITH A COUNTRY FIELD, in this same database, synced hourly, and we '
             'had never read one of them. This question should never have been asked. The work is '
             'ours: bridge wayward_brand_id -> hubspot_company_id (we hold the HubSpot id for '
             '1,347 brands already) and harvest the country. Asking a client for data you already '
             'have is how you lose their patience and your credibility at once.',
           updated_at = now()
     WHERE tenant_id = :t
       AND status = 'open'
       AND subject_label ILIKE '%625 brands have none%'
""")

# Money-framed, and built on the "cannot be proven" premise Tim rejected.
KILL_MONEY_FRAMED = text("""
    UPDATE ps_information_gaps
       SET status = 'abandoned',
           answered_at = now(),
           answered_by = 'internal:data-first-reset',
           answer =
             'WITHDRAWN — money work is FROZEN, and this question rested on a premise Tim '
             'rejected: that a brand I could not corroborate FROM MY OWN TABLES was a brand we '
             '"could not prove". Absence of evidence was an INGESTION GAP (HubSpot, the knowledge '
             'base, Zendesk — all unread, all in this database), not a verdict. These brands are '
             'Chinese; the job is to evidence them ourselves, not to ask Wayward for permission. '
             'Nationality now runs on a 4-state model where probable = a research task.',
           updated_at = now()
     WHERE tenant_id = :t
       AND status = 'open'
       AND (subject_label ILIKE '%9 brands our whole claim rests on%'
            OR gap_type = 'not_paid_verify')
""")

# Re-frame: this one is a CORRECTION WE HAND THEM, not a request.
REFRAME_COUNTRY_CONFLICTS = text("""
    UPDATE ps_information_gaps
       SET question =
             'A correction for your records, not a request: 31 brands sit on the frozen exclusion '
             'list — which the contract defines as "Chinese-based Brands" — while your onboarding '
             'feed records their country as US (WhiteBite PRO, BABONIR, Frizzlife, MARYSUN, '
             'Chasesun, TORUTA, ATVIOO, Rormcheny, AIMTER, BEESHOP and others, all in Eric''s '
             'book). We read them as US-registered shells for Chinese operators. Separately: 137 '
             'of your Stripe customers carry no brandId at all, and for another 337 the brand '
             'UUID was written into the customer `description` field instead of '
             '`metadata.brandId`. Worth fixing at source.',
           context =
             'We are not blocked on this — we treat the exclusion list as authoritative over the '
             'country field, so it does not change our view. We are giving it back because your '
             'data currently contradicts itself, and we would rather be the reference dataset '
             'than the party that quietly worked around it.',
           priority = 3,
           updated_at = now()
     WHERE tenant_id = :t
       AND status = 'open'
       AND subject_label ILIKE '%contradicts your own exclusion list%'
""")


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    out = {
        "withdrawn_we_already_have_it": conn.execute(
            KILL_WE_ALREADY_HAVE_IT, {"t": PS_TENANT}
        ).rowcount,
        "withdrawn_money_framed": conn.execute(KILL_MONEY_FRAMED, {"t": PS_TENANT}).rowcount,
        "reframed_as_a_correction": conn.execute(
            REFRAME_COUNTRY_CONFLICTS, {"t": PS_TENANT}
        ).rowcount,
    }
    out["remaining_open"] = [
        dict(zip(("ask_who", "n"), r, strict=False))
        for r in conn.execute(text("""
            SELECT ask_who, count(*) FROM ps_information_gaps
            WHERE tenant_id = :t AND status = 'open' GROUP BY 1 ORDER BY 2 DESC
        """), {"t": PS_TENANT}).fetchall()
    ]
    out["surviving_jake_questions"] = [
        r[0] for r in conn.execute(text("""
            SELECT subject_label FROM ps_information_gaps
            WHERE tenant_id = :t AND status = 'open' AND ask_who = 'jake'
            ORDER BY priority, subject_label
        """), {"t": PS_TENANT}).fetchall()
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
