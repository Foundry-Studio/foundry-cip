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
    # ── the four an adversarial audit found on 2026-07-14 ────────────────────
    Invariant(
        key="money_on_a_brand_graded_junk",
        sql="""SELECT count(*) FROM lens_ps_brand_reality r
               WHERE r.reality = 'JUNK'
                 AND EXISTS (SELECT 1 FROM ps_monthly_earnings e
                              WHERE e.wayward_brand_id = r.wayward_brand_id
                                AND (e.usage_collected > 0 OR e.usage_billed > 0))""",
        why="cip_83 graded a brand JUNK if its Stripe mailbox was @wayward.com — and GCI Outdoors, "
            "a real American company with $23,345.23 collected, was junked because a Wayward "
            "EMPLOYEE set its Stripe account up on its behalf. EMAIL IS NEVER A KEY. A paid "
            "invoice is the strongest evidence of existence there is; if a JUNK row has money, "
            "the grader "
            "is wrong, not the money. Catches it in both directions.",
    ),
    Invariant(
        key="stale_seen_in_flags",
        sql="""SELECT count(*) FROM ps_brands b
               WHERE b.seen_in_exclusion_list <> EXISTS (
                       SELECT 1 FROM ps_excluded_brands x
                        WHERE x.wayward_brand_id = b.wayward_brand_id)
                  OR b.seen_in_eric_sheets <> EXISTS (
                       SELECT 1 FROM ps_brand_observations o
                        WHERE o.wayward_brand_id = b.wayward_brand_id
                          AND o.source_system = 'gsheet:eric-all-agreements')""",
        why="The seen_in_* flags are a denormalised cache that cip_55 filled once and NOTHING has "
            "maintained since. By 2026-07-14 seen_in_exclusion_list was FALSE on 26 brands that "
            "were on the frozen list — $41,743.82 collected, including CrownShade (bucket "
            "'Shallow', where another partner is still being paid). "
            "`WHERE NOT seen_in_exclusion_list` is the natural way to ask 'who does nobody "
            "else have a claim on?' and it returned brands somebody else earns on. "
            "seen_in_eric_sheets is worse: harvest_nationality_signals.py reads it to emit a "
            "DEFINITIONAL china signal, so drift there corrupts the nationality verdict itself.",
    ),
    Invariant(
        key="china_needs_a_confirming_indicator_or_a_human",
        sql="""SELECT count(*) FROM lens_ps_china_verdict v
               WHERE v.verdict = 'china'
                 AND NOT EXISTS (
                       SELECT 1 FROM ps_nationality_signals s
                        WHERE s.wayward_brand_id = v.wayward_brand_id
                          AND s.points_to = 'china'
                          AND s.signal IN ('on_exclusion_list','eric_sheet','wayward_country_cn',
                                           'chinese_email_domain','cjk_in_name','phone_+86',
                                           'qq_handle','cn_mobile_handle','cn_company_name_pinyin',
                                           'shared_owner_mailbox','amazon_seller_entity',
                                           'uspto_trademark_owner','tim_batch_approval',
                                           'chinese_partner'))
                 AND NOT EXISTS (
                       SELECT 1 FROM ps_nationality_signals s
                        WHERE s.wayward_brand_id = v.wayward_brand_id
                          AND s.signal = 'manual_review' AND s.points_to = 'china')""",
        why="Tim's rule: a brand is CONFIRMED Chinese on ANY approved indicator, or on a named "
            "human. Nothing else. This catches a NAME being promoted to a verdict — a Chinese NAME "
            "is not a Chinese COMPANY (Bob and Brad is Chinese; Lifepro is Los Angeles). Names "
            "belong in `probable`, a queue for a human, not an answer. The old view had no "
            "strength floor at all: an ingest wrote UNRESOLVED research findings as weak china "
            "signals and 'Aiming Fluid Golf' — a Chico, California business — came out Chinese. "
            "NOTE `chinese_partner` IS on this list (cip_89). Tim: 'if they were refered by "
            "tsoe chinese partners, yes they are chinese.' Our China partners source Chinese "
            "brands — "
            "that is the job. BruMate is the exception that proves the rule, and she is protected "
            "structurally: a human's not_china is read FIRST and no rule change can overturn it.",
    ),
    Invariant(
        key="not_china_requires_a_human_or_a_legal_record",
        sql="""SELECT count(*) FROM lens_ps_china_verdict v
               WHERE v.verdict = 'not_china'
                 AND NOT EXISTS (
                       SELECT 1 FROM ps_nationality_signals s
                        WHERE s.wayward_brand_id = v.wayward_brand_id
                          AND s.signal = 'manual_review' AND s.points_to = 'not_china')
                 AND NOT EXISTS (
                       SELECT 1 FROM ps_nationality_signals s
                        WHERE s.wayward_brand_id = v.wayward_brand_id
                          AND s.points_to = 'not_china'
                          AND s.signal IN ('amazon_seller_entity', 'uspto_trademark_owner'))""",
        why="TIM: 'DONT ASSUME THAT WAYAWARD DATA IS CORRECT.' Only a named HUMAN or a LEGAL "
            "RECORD may clear a brand. Wayward's country flag used to do it — and it is the least "
            "reliable field we hold, because a Chinese seller behind a US-registered shell "
            "reports "
            "as US. That IS the pattern this audit exists to find: 104 CONFIRMED-CHINESE brands "
            "carry it. The legal records are amazon_seller_entity (Amazon is compelled by the "
            "INFORM Consumers Act to publish a seller's business name and address) and "
            "uspto_trademark_owner (a Chinese company must file a US trademark under its real "
            "entity). A US LLC in a website footer is NOT a clearance — Chinese sellers register "
            "Delaware and Wyoming shells by the thousand.",
    ),
    Invariant(
        key="company_rollup_is_one_row_per_company",
        sql="""SELECT count(*) - count(DISTINCT company_id) FROM lens_ps_china_companies""",
        why="lens_ps_china_companies is the ONLY place headline counts may come from, and its "
            "whole job is to be one row per real company. A fan-out here would inflate exactly the "
            "number we quote out loud — which is how a raw join to ps_excluded_brands once "
            "inflated every summary by 8.6%.",
    ),
    Invariant(
        key="company_rollup_never_overrules_a_human",
        sql="""SELECT count(*) FROM lens_ps_china_companies c
               WHERE c.verdict <> 'not_china'
                 AND EXISTS (
                       SELECT 1 FROM ps_brands b
                       JOIN ps_nationality_signals s USING (wayward_brand_id)
                       WHERE COALESCE(b.canonical_brand_id, b.wayward_brand_id) = c.company_id
                         AND s.signal = 'manual_review' AND s.points_to = 'not_china')""",
        why="If a named human pinned not_china on ANY row of a company, the company is "
            "not_china. Full stop. The obvious roll-up design — take the row verdicts and let "
            "china beat not_china — would hand the company to a MACHINE SIGNAL sitting on a "
            "sibling row. Zero conflicts exist today, and that is exactly how every bug in this "
            "dataset started. "
            "The roll-up unions the SIGNALS and re-applies the constitution, so the human tier "
            "survives identity resolution. This tripwire proves it stays that way.",
    ),
    Invariant(
        key="stored_rate_clock_is_a_day_count",
        sql="""SELECT count(*) FROM ps_product_subscriptions
               WHERE productive_date IS NOT NULL
                 AND (rate_10_expires        <> (productive_date + INTERVAL '12 months')::date
                   OR partner_credit_expires <> (productive_date + INTERVAL '12 months')::date
                   OR rate_6_expires         <> (productive_date + INTERVAL '18 months')::date)""",
        why="NEVER COUNT MONTHS IN DAYS. rate_6_expires was GENERATED AS "
            "((productive_date + 365) + 183) — 548 days standing in for 18 calendar months, which "
            "is 546-549 days depending on the start month. It was wrong on 2,371 of 2,829 deals, "
            "and 1,539 of them KEPT 6% TOO LONG, billing into month 19. "
            "compute_monthly_earnings.py had been fixed to use real INTERVAL months, so the money "
            "SPINE was right while these stored columns and lens_ps_rate_clock were wrong: one "
            "fact, two computations. partner_credit_expires decides when a PARTNER STOPS BEING "
            "PAID, and it carried the same bug — right today only because no current deal spans a "
            "leap day. That is luck, not correctness.",
    ),
    Invariant(
        key="spine_is_chinese_matches_verdict",
        sql="""SELECT count(*) FROM ps_monthly_earnings m
               LEFT JOIN lens_ps_china_verdict v USING (wayward_brand_id)
               WHERE m.is_chinese IS DISTINCT FROM CASE v.verdict
                                                       WHEN 'china'     THEN true
                                                       WHEN 'not_china' THEN false
                                                       ELSE NULL
                                                   END""",
        why="is_chinese has ONE home — lens_ps_china_verdict — and the money spine must agree with "
            "it. It used to be written from lens_ps_eligibility's LEGACY nationality signal, and "
            "the two disagreed on 498 brands / $48,652.77 of gross owed. SIX of them said FALSE "
            "while the verdict said CHINA (COOLIFE, Heyvalue, Gelrova, Neathova, Jarkyfine, "
            "MOSDART) — each carrying a +86 phone or sitting on the frozen exclusion list. Two "
            "authoritative-looking answers to the same question, on the money table itself. "
            "NULL is not FALSE: probable and unknown propagate as NULL, because 'we have not "
            "decided' is not 'not Chinese' (cip_72), and treating it as false silently drops "
            "brands out of the book.",
    ),
    Invariant(
        key="humans_live_and_opposed",
        sql="""SELECT count(*) FROM (
                 SELECT wayward_brand_id FROM ps_nationality_signals
                 WHERE signal = 'manual_review'
                 GROUP BY wayward_brand_id
                 HAVING count(*) FILTER (WHERE points_to = 'china') > 0
                    AND count(*) FILTER (WHERE points_to = 'not_china') > 0) d""",
        why="lens_ps_china_verdict checks `manual_not_china` FIRST, with no recency and no "
            "authority ordering — and the unique key is (tenant, brand, signal, source_system), "
            "so an old machine review and Tim's ruling can COEXIST on one brand. If both ever "
            "land, the older "
            "one silently wins and a brand Tim personally ruled Chinese renders as not_china, "
            "dropping out of the book. Zero today is luck; nothing prevents it.",
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
