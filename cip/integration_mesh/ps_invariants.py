# foundry: kind=service domain=client-intelligence-platform
"""Invariants for the Project Silk book. The machine catches the bugs, not Tim at 1am.

WHY THIS EXISTS
---------------
On 2026-07-13 four adversarial audits found fifteen defects in this dataset. Every one of them was
INVISIBLE IN THE TOTALS and every one was real money:

    a raw join to ps_excluded_brands fanned out and inflated every summary by 8.6%
    548 days was used as "18 months", so 46 brands kept 6% into month 19
    3,389 VOIDED invoices were counted as "billed" ($561,209), making collected > billed on 73 rows
    $4,012 of cash Wayward had ALREADY PAID was silently discarded by a join predicate
    an unknown rate became a confident $0.00; an unknown partner became a confident 5%
    a migration fixed data that the very next script run overwrote

Not one of them raised an error. They produced confident, wrong numbers — and a human found them
by reading SQL at one in the morning.

Every check below is one of those bugs, turned into a tripwire. They run after every sync. A
failure is not a warning to be triaged later; it means a number somewhere is lying.

CONTRACT (matches the FAS dispatcher: src/work_execution/task_queue/executors.py)
  - called as function(db, **params); returns a JSON-safe dict for tasks.result
  - raises on a FAILED invariant, so the scheduler records it and escalates
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

log = logging.getLogger(__name__)

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"


@dataclass(frozen=True)
class Invariant:
    """One thing that must never be true. `sql` must return a single count; 0 = healthy."""

    key: str
    sql: str
    why: str
    """What broke last time this was violated — so whoever sees the alert knows the stakes."""


INVARIANTS: tuple[Invariant, ...] = (
    # ── identity: a fan-out double-counts money and nobody notices ────────────
    Invariant(
        key="lens_verdict_fanout",
        sql="""SELECT count(*) - count(DISTINCT wayward_brand_id)
               FROM lens_ps_china_verdict""",
        why="A raw join to ps_excluded_brands (817 rows, 807 brands — ten sit in TWO buckets) "
            "duplicated brands and inflated every summary built on this view by $183,383 (8.6%). "
            "Roborock alone double-counted $172,379.",
    ),
    Invariant(
        key="lens_eligibility_fanout",
        sql="""SELECT count(*) - count(DISTINCT wayward_brand_id)
               FROM lens_ps_eligibility""",
        why="Same fan-out, same cause. Always join lens_ps_exclusion_status, never "
            "ps_excluded_brands directly.",
    ),
    Invariant(
        key="spine_grain_unique",
        sql="""SELECT count(*) FROM (
                 SELECT 1 FROM ps_monthly_earnings
                 GROUP BY tenant_id, wayward_brand_id, product_id, period_month
                 HAVING count(*) > 1) d""",
        why="The money spine is one row per brand x product x month. A duplicate is a "
            "double-counted month.",
    ),
    Invariant(
        key="orphan_money",
        sql="""SELECT count(*) FROM ps_stripe_invoice_lines l
               WHERE l.wayward_brand_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM ps_brands b
                                  WHERE b.wayward_brand_id = l.wayward_brand_id)""",
        why="Revenue pointing at a brand the master has never heard of. Before the FK existed "
            "this was a silent dangling identity.",
    ),
    # ── Tim's governing principle ────────────────────────────────────────────
    Invariant(
        key="claiming_where_someone_else_earns",
        sql="""SELECT count(*) FROM ps_monthly_earnings e
               JOIN lens_ps_exclusion_status st USING (wayward_brand_id)
               WHERE e.is_claimable AND st.someone_else_earning""",
        why="Tim's rule: you cannot take a brand somebody else is actively being paid on — on ANY "
            "product. We were invoicing Roborock's Boost revenue while Eric/Adina earn an ongoing "
            "10% on it. (Rules 3 and 7 allow it ONLY with activation evidence, which flips "
            "someone_else_earning off.)",
    ),
    Invariant(
        key="reactivation_regression",
        sql="""SELECT count(*) FROM ps_product_subscriptions s
               JOIN lens_ps_exclusion_status st USING (wayward_brand_id)
               WHERE s.reactivation_qualifies AND st.someone_else_earning""",
        why="cip_68 fixed this in DATA and left the old logic in the script; the very next --apply "
            "silently re-broke it. YOLIX and Nexiepoch were 'won back' from Shallow, who is still "
            "being paid on them. A migration a script overwrites is not a fix, it is a delay.",
    ),
    # ── NULL must never become a number ──────────────────────────────────────
    Invariant(
        key="unknown_rate_priced",
        sql="""SELECT count(*) FROM ps_monthly_earnings
               WHERE ps_rate_pct IS NULL AND ps_gross_owed IS NOT NULL""",
        why="COALESCE(rate, 0) turned 'we do not know the rate' into a confident $0.00 and "
            "reported it as fact. NULL means unknown and must propagate.",
    ),
    Invariant(
        key="unknown_partner_paid",
        sql="""SELECT count(*) FROM ps_monthly_earnings
               WHERE partner_rate_pct IS NULL AND partner_owed IS NOT NULL""",
        why="The same sin, relocated to deal_type: 457 rows where we did not know the partner's "
            "deal defaulted to 5% and paid out $1,054 of PS net anyway.",
    ),
    # ── the arithmetic ──────────────────────────────────────────────────────
    Invariant(
        key="rate_tier_18_months",
        sql="""SELECT count(*) FROM ps_monthly_earnings e
               JOIN ps_product_subscriptions s
                 ON s.wayward_brand_id = e.wayward_brand_id AND s.product_id = e.product_id
               WHERE e.period_month >= s.productive_date + INTERVAL '18 months'
                 AND e.ps_rate_pct = 6""",
        why="'+365+183' = 548 days, but 18 CALENDAR months is 546-549 depending on the start "
            "month. Month NINETEEN fell inside the boundary and kept 6% on 46 brands. Never use a "
            "day count for a month boundary.",
    ),
    Invariant(
        key="net_negative_on_positive_revenue",
        sql="""SELECT count(*) FROM ps_monthly_earnings
               WHERE ps_net_owed < 0 AND usage_collected > 0""",
        why="The partner cannot earn more than we do. (A negative net on NEGATIVE collected is "
            "legitimate — that is a refund month.)",
    ),
    Invariant(
        key="voided_counted_as_billed",
        sql="""SELECT count(*) FROM ps_monthly_earnings e
               WHERE e.usage_billed <> COALESCE((
                   SELECT sum(l.amount) FILTER (WHERE l.invoice_status IN ('paid','open'))
                   FROM ps_stripe_invoice_lines l
                   WHERE l.wayward_brand_id = e.wayward_brand_id
                     AND l.product_id = e.product_id
                     AND l.billing_month = e.period_month
                     AND l.is_ps_base), 0)""",
        why="A VOIDED invoice was CANCELLED — never billed, never owed, never collectable. "
            "Counting voids inflated 'billed' by $561,209 and made COLLECTED EXCEED BILLED on 73 "
            "brand-months. A brand cannot pay us more than we invoiced it.",
    ),
    # ── provenance: a decision nobody can explain is a decision nobody can defend ──
    Invariant(
        key="anonymous_added_fact",
        sql="""SELECT count(*) FROM ps_added_facts
               WHERE asserted_by IS NULL OR btrim(asserted_by) = ''
                  OR rationale IS NULL OR btrim(rationale) = ''""",
        why="ADDED outranks every machine signal, so it MUST name its author and its reason. An "
            "anonymous determination cannot be audited, revisited, or defended.",
    ),
    Invariant(
        key="identity_without_provenance",
        sql="""SELECT count(*) FROM ps_stripe_invoice_lines
               WHERE wayward_brand_id IS NOT NULL AND brand_id_source IS NULL""",
        why="Identity is upstream of all money. A brand id with no provenance cannot be "
            "distinguished from a guess — and a wrong one produces a confident number on the "
            "wrong brand, not an error.",
    ),
)


def run_ps_invariants(db: Any, *, ps_tenant_id: str = PS_TENANT) -> dict:
    """Run every invariant. Returns a JSON-safe dict; RAISES if any fails.

    Raising is deliberate: a violated invariant means a number somewhere is lying, and the
    scheduler's job is to make that loud rather than to file it politely.
    """
    db.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": ps_tenant_id}
    )

    passed: list[str] = []
    failed: list[dict] = []

    for inv in INVARIANTS:
        try:
            count = db.execute(text(inv.sql)).scalar() or 0
        except Exception as exc:  # a check that cannot RUN is itself a failure
            failed.append({"key": inv.key, "count": None, "error": str(exc)[:200],
                           "why": inv.why})
            continue
        if count:
            failed.append({"key": inv.key, "count": int(count), "why": inv.why})
        else:
            passed.append(inv.key)

    result = {
        "checked": len(INVARIANTS),
        "passed": len(passed),
        "failed": len(failed),
        "failures": failed,
        "passed_keys": passed,
    }

    if failed:
        lines = "\n".join(
            f"  [{f['key']}] {f.get('count', 'ERROR')} violations — {f['why']}" for f in failed
        )
        log.error("PS INVARIANTS FAILED (%d of %d):\n%s", len(failed), len(INVARIANTS), lines)
        raise InvariantViolationError(
            f"{len(failed)} of {len(INVARIANTS)} PS invariants FAILED. "
            f"A number somewhere is lying.\n{lines}"
        )

    log.info("PS invariants: all %d passed", len(INVARIANTS))
    return result


class InvariantViolationError(RuntimeError):
    """A thing that must never be true, is true. Some number is lying."""
