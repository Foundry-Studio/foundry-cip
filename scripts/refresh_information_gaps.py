# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Refresh the question queue against what we NOW know, then export it as a list.

Tim, 2026-07-13: "if there are questions, add to the question list and I will get from Jake."

Two jobs, in this order:

  1. ANSWER what we can answer ourselves. The queue held 218 questions of the form "has this
     brand generated any usage fees since December? It is Chinese, referred under PS, and has
     never appeared in a rev-share report — either it made no sales, or we are not being paid,
     and we cannot tell which." That WAS unanswerable when Stripe coverage sat at 78%. It is
     now 99.8%, so Stripe answers it directly:

        149 brands -> no usage fees exist. They made no sales. Nothing is owed. Close.
         69 brands -> usage fees WERE billed, and we were still never paid on them. Those stay
                      open, but they stop being a vague worry and become a specific, evidenced
                      question with a dollar figure attached.

     Asking Jake 218 questions we could have answered ourselves would have burned his goodwill
     on 149 non-issues and buried the 69 that matter.

  2. RAISE what is genuinely unknown, sized so it can be prioritised.

Nothing here decides anything. It turns unknowns into answerable questions, and closes the ones
that stopped being unknown.

Usage:
  DATABASE_URL=... python scripts/refresh_information_gaps.py [--apply] [--export PATH.md]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

# 1. Close the questions Stripe now answers: no usage fees exist, so there is nothing to pay.
CLOSE_ANSWERED = text("""
    UPDATE ps_information_gaps g
       SET status = 'answered',
           answered_at = now(),
           answered_by = 'stripe:usage_fee_lines',
           answer = 'ANSWERED FROM STRIPE, not from Jake. This brand has no usage-fee lines at '
                    'all since 2025-12-01, so it generated no sales and nothing is owed on it. '
                    'The question was only unanswerable while Stripe identity coverage sat at '
                    '78%; at 99.8% the absence of a line is now meaningful evidence rather than '
                    'a blind spot.',
           updated_at = now()
     WHERE g.tenant_id = :t
       AND g.status = 'open'
       AND g.gap_type = 'not_paid_verify'
       AND g.wayward_brand_id IS NOT NULL
       AND NOT EXISTS (
            SELECT 1 FROM ps_stripe_invoice_lines l
             WHERE l.wayward_brand_id = g.wayward_brand_id
               AND l.is_ps_base
               AND l.billing_month >= DATE '2025-12-01')
""")

# 2. Sharpen the ones that remain: they DID bill, and we still were not paid.
SHARPEN_REAL = text("""
    WITH billed AS (
        SELECT l.wayward_brand_id,
               round(sum(l.amount), 2)                                        AS billed,
               -- collected is NET of succeeded refunds (cip_113), like the ledger's usage_collected
               round(sum(l.amount) FILTER (WHERE l.invoice_status='paid')
                     - COALESCE((SELECT sum(ra.usage_refund_netted)
                                 FROM lens_ps_refund_allocation ra
                                 WHERE ra.wayward_brand_id = l.wayward_brand_id
                                   AND ra.period_month >= DATE '2025-12-01'), 0), 2) AS collected,
               min(l.billing_month)                                           AS first_month
        FROM ps_stripe_invoice_lines l
        WHERE l.is_ps_base AND l.billing_month >= DATE '2025-12-01'
        GROUP BY 1
    )
    UPDATE ps_information_gaps g
       SET question = 'Wayward BILLED ' || g.subject_label || ' $' || b.billed ||
                      ' in usage fees since ' || to_char(b.first_month, 'Mon YYYY') ||
                      ' (of which $' || COALESCE(b.collected, 0) || ' has been collected), but '
                      'this brand has never appeared in a rev-share report and Project Silk has '
                      'been paid $0 on it. Why?',
           context = 'Evidenced from Stripe invoice lines, which now cover 99.8% of brands. This '
                     'is no longer "we cannot see the sales" — we can see them. The usage fee is '
                     'the base our 10% is owed on.',
           priority = 1,
           updated_at = now()
      FROM billed b
     WHERE g.tenant_id = :t
       AND g.status = 'open'
       AND g.gap_type = 'not_paid_verify'
       AND g.wayward_brand_id = b.wayward_brand_id
       AND b.billed > 0
""")

# 3. New gaps discovered today.
NEW_GAPS = [
    {
        "gap_type": "other",
        "question": (
            "137 Stripe customers have NO brand id anywhere — not in metadata.brandId, not in "
            "the description field, nowhere. Which brands are they? (For the other 337 we "
            "recovered the id ourselves: Wayward had written it into the free-text description "
            "field instead of metadata.brandId. Worth fixing at your end so it stops happening.)"
        ),
        "context": (
            "These are the last customers we cannot name. Everything else is resolved: brand "
            "identity now covers 99.8% of Stripe invoice lines, up from 74.6%."
        ),
        "ask_who": "jake",
        "priority": 2,
        "subject_label": "137 unidentifiable Stripe customers",
    },
    {
        "gap_type": "contact_missing",
        "question": (
            "We have ZERO contacts on file for any brand — no email, no WeChat, no name. The "
            "ps_brand_contacts table is empty. Can you export what you hold, and start capturing "
            "WeChat at onboarding as discussed?"
        ),
        "context": (
            "Without a contact we cannot reach a brand directly, which blocks reactivation of "
            "dormant brands and any direct Boost pitch."
        ),
        "ask_who": "jake",
        "priority": 1,
        "subject_label": "brand contacts (table is empty)",
    },
    {
        "gap_type": "deal_terms_unknown",
        "question": (
            "Wayward states a Rev Share Start Date for only 289 brands. What is it for the rest? "
            "This date sets the 12-month clock on our 10% rate, so where it is missing we cannot "
            "say what rate we are on."
        ),
        "context": (
            "Under §4.4 Wayward's records are conclusive and controlling, so YOUR date is the one "
            "that governs — which is precisely why we need it stated for every brand."
        ),
        "ask_who": "jake",
        "priority": 1,
        "subject_label": "rev share start date — 289 of 1,108 stated",
    },
    {
        "gap_type": "no_activity_signal",
        "question": (
            "Please send per-brand monthly SALES (GMV), not just fees. We need it to tell a "
            "dormant brand from an active one — 90 days without a sale on Connect is what makes "
            "a brand winnable by another partner."
        ),
        "context": (
            "We can currently see fees billed, but not sales. A brand can be alive and simply "
            "not have been invoiced yet; we cannot distinguish that from genuinely dormant."
        ),
        "ask_who": "jake",
        "priority": 2,
        "subject_label": "per-brand monthly sales (dormancy)",
    },
]

INSERT_GAP = text("""
    INSERT INTO ps_information_gaps
        (id, tenant_id, subject_label, gap_type, question, context, ask_who, status, priority,
         created_at, updated_at)
    SELECT gen_random_uuid(), CAST(:t AS uuid), :subject_label, :gap_type, :question, :context,
           :ask_who, 'open', :priority, now(), now()
     WHERE NOT EXISTS (
        SELECT 1 FROM ps_information_gaps
         WHERE tenant_id = CAST(:t AS uuid) AND subject_label = :subject_label
           AND status <> 'answered')
""")

EXPORT = text("""
    SELECT priority, ask_who, gap_type, subject_label, question, context
    FROM ps_information_gaps
    WHERE tenant_id = :t AND status = 'open'
    ORDER BY priority, ask_who, gap_type, subject_label
""")


def to_markdown(rows) -> str:
    from collections import defaultdict

    by_who: dict = defaultdict(list)
    for r in rows:
        by_who[r.ask_who].append(r)

    who_title = {
        "jake": "Jake (Wayward)",
        "tim": "Tim — needs your judgement",
        "rhea": "Rhea",
        "ali": "Ali (Wayward)",
    }
    out = [
        "# Open Questions — Wayward / Project Silk China Audit",
        "",
        "Generated from `ps_information_gaps` in CIP. This file is a VIEW of that table, not the",
        "source of truth — re-run `scripts/refresh_information_gaps.py --export` to refresh it.",
        "",
        "Questions we could answer ourselves have already been closed. In particular, 149",
        "questions of the form *\"has this brand made any sales?\"* were answered directly from",
        "Stripe once brand-identity coverage reached 99.8% — asking those would have buried the",
        "ones that matter.",
        "",
    ]
    for who in sorted(by_who, key=lambda w: (w != "jake", w)):
        rows_w = by_who[who]
        out.append(f"## {who_title.get(who, who)} — {len(rows_w)} open")
        out.append("")
        for r in rows_w:
            flag = "**[HIGH]** " if r.priority == 1 else ""
            out.append(f"### {flag}{r.subject_label}")
            out.append("")
            out.append(f"{r.question}")
            if r.context:
                out.append("")
                out.append(f"> {r.context}")
            out.append("")
    return "\n".join(out)


def run(conn, *, apply: bool, export: str | None) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    out: dict = {}
    out["closed_answered_from_stripe"] = conn.execute(
        CLOSE_ANSWERED, {"t": PS_TENANT}
    ).rowcount
    out["sharpened_with_evidence"] = conn.execute(SHARPEN_REAL, {"t": PS_TENANT}).rowcount
    added = 0
    for g in NEW_GAPS:
        added += conn.execute(INSERT_GAP, {"t": PS_TENANT, **g}).rowcount
    out["new_gaps_raised"] = added

    rows = conn.execute(EXPORT, {"t": PS_TENANT}).fetchall()
    out["open_after"] = len(rows)
    out["open_by_who"] = {}
    for r in rows:
        out["open_by_who"][r.ask_who] = out["open_by_who"].get(r.ask_who, 0) + 1

    if export:
        with open(export, "w", encoding="utf-8") as fh:
            fh.write(to_markdown(rows))
        out["exported_to"] = export

    if not apply:
        conn.execute(text("ROLLBACK"))
    out["applied"] = apply
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--export", default=None)
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
            out = run(conn, apply=args.apply, export=args.export)
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
