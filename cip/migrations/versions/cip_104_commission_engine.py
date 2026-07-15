# foundry: kind=migration domain=client-intelligence-platform
"""cip_104: the commission recovery engine — LENS-FIRST (Tim, 2026-07-15; P2 Phase B).

Live money math as a view stack (Decision of Record: "live math, not frozen"). A materialized/writer
approach was rejected — it reintroduces the exact staleness that retired the old writer. The formula
was recovered from that writer's git history and reconciled to the penny against the frozen
`ps_monthly_earnings` snapshot before this was written.

Objects (all VIEWS except the one pinned-statement TABLE):
- lens_ps_rate_schedule       — per brand x product, the 10/6/3 ladder anchor (re-anchored by a
                                qualifying reactivation: GREATEST(productive_date, reactivated_at)).
- lens_ps_commission_ledger   — the waterfall at brand x product x month: usage_billed/collected ->
                                mgmt_rate (ladder) -> mgmt_fee_owed (gated by nationality=china +
                                ownership + revenue-start) -> partner_fee_owed. Live off Stripe.
- lens_ps_claim               — brand-grain net: mgmt_fee_owed vs wayward_paid (ps_payment_events),
                                partner_fee_owed vs partner_paid (ps_partner_payouts) -> still-owed.
- ps_claim_statements (TABLE) — the ONE frozen thing: pinned as-of copies of a claim handed to
                                Wayward (a bank statement vs the live balance). RLS like the money tables.

DEFERRED (own follow-up): lens_ps_wayward_stated — the typed cross-check over cip_deals.properties
(Wayward's stated total_fees_paid) needs the non-trivial cip_deals -> wayward_brand_id mapping
(cip_deals has only client_id/company_id; one company = many brands). It's a P5 reconciliation
nicety, off the recovery path — worked out separately so a half-baked join doesn't ride into the
money engine.

Gates encoded (OWNERSHIP-RULES.md): nationality=china (unknown -> claim_status='unknown_nationality',
never $0/denied); ownership = never-listed OR flat_fee_era_eric (cip_103); revenue-start = 2025-10-01
never-listed / 2025-12-01 flat-fee (ours_revenue_from); ladder 10%/6%/3% at +12mo/+18mo from anchor.
The frozen `ps_monthly_earnings` stays authoritative until this reconciles; the writer-retire +
consumer-repoint (the on-rails swap) is a SEPARATE later step.

Revision ID: cip_104_commission_engine
Revises: cip_103_flat_fee_disposition
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_104_commission_engine"
down_revision: str | Sequence[str] | None = "cip_103_flat_fee_disposition"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_RATE_SCHEDULE = """
CREATE VIEW lens_ps_rate_schedule AS
SELECT
    s.wayward_brand_id,
    s.product_id,
    s.productive_date,
    s.reactivated_at,
    s.reactivation_qualifies,
    GREATEST(s.productive_date,
             CASE WHEN s.reactivation_qualifies THEN s.reactivated_at END) AS effective_anchor,
    (GREATEST(s.productive_date,
              CASE WHEN s.reactivation_qualifies THEN s.reactivated_at END)
        + INTERVAL '12 months')::date AS rate_10_until,
    (GREATEST(s.productive_date,
              CASE WHEN s.reactivation_qualifies THEN s.reactivated_at END)
        + INTERVAL '18 months')::date AS rate_6_until
FROM ps_product_subscriptions s
WHERE s.wayward_brand_id IS NOT NULL AND s.product_id IS NOT NULL
"""

_LEDGER = """
CREATE VIEW lens_ps_commission_ledger AS
WITH collected AS (
    SELECT wayward_brand_id, product_id, billing_month::date AS period_month,
           COALESCE(sum(amount) FILTER (WHERE invoice_status = 'paid'), 0) AS usage_collected,
           COALESCE(sum(amount) FILTER (WHERE invoice_status IN ('paid','open')), 0) AS usage_billed
    FROM ps_stripe_invoice_lines
    WHERE is_ps_base
      AND product_id IS NOT NULL
      AND wayward_brand_id IS NOT NULL
      AND billing_month IS NOT NULL
    GROUP BY 1, 2, 3
),
excl AS (
    SELECT wayward_brand_id,
           bool_or(disposition = 'flat_fee_era_eric') AS any_flat_fee,
           bool_or(disposition = 'excluded')          AS any_excluded,
           max(ours_revenue_from)                     AS ours_revenue_from
    FROM ps_excluded_brands
    WHERE wayward_brand_id IS NOT NULL
    GROUP BY 1
),
graded AS (
    SELECT
        c.wayward_brand_id, c.product_id, c.period_month,
        c.usage_collected, c.usage_billed,
        v.verdict,
        CASE WHEN e.wayward_brand_id IS NULL THEN 'never_listed'
             WHEN e.any_flat_fee AND NOT e.any_excluded THEN 'flat_fee_era_eric'
             ELSE 'excluded' END AS ownership,
        CASE WHEN e.wayward_brand_id IS NULL THEN DATE '2025-10-01'
             WHEN e.any_flat_fee AND NOT e.any_excluded THEN e.ours_revenue_from
             ELSE NULL END AS ours_revenue_from,
        CASE WHEN rs.effective_anchor IS NULL THEN 0.10
             WHEN c.period_month < rs.rate_10_until THEN 0.10
             WHEN c.period_month < rs.rate_6_until  THEN 0.06
             ELSE 0.03 END AS mgmt_rate,
        pc.partner_of_record,
        COALESCE(pc.partner_rate, 0) AS partner_rate_pct,
        pc.credit_start, pc.credit_end,
        (v.verdict = 'china'
         AND (e.wayward_brand_id IS NULL OR (e.any_flat_fee AND NOT e.any_excluded))
         AND c.period_month >= CASE WHEN e.wayward_brand_id IS NULL THEN DATE '2025-10-01'
                                    WHEN e.any_flat_fee AND NOT e.any_excluded THEN e.ours_revenue_from
                                    ELSE NULL END) AS claimable
    FROM collected c
    LEFT JOIN lens_ps_rate_schedule rs USING (wayward_brand_id, product_id)
    LEFT JOIN lens_ps_china_verdict v ON v.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN excl e ON e.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN ps_partner_credit pc
           ON pc.wayward_brand_id = c.wayward_brand_id AND pc.product_id = c.product_id
)
SELECT
    g.wayward_brand_id, g.product_id, g.period_month,
    g.usage_billed, g.usage_collected,
    g.verdict, g.ownership, g.ours_revenue_from, g.mgmt_rate, g.claimable,
    CASE WHEN g.claimable THEN round(g.usage_collected * g.mgmt_rate, 2) ELSE 0 END AS mgmt_fee_owed,
    g.partner_of_record, g.partner_rate_pct,
    CASE WHEN g.claimable
              AND g.period_month >= COALESCE(g.credit_start, g.period_month)
              AND g.period_month <= COALESCE(g.credit_end, g.period_month)
         THEN round(g.usage_collected * g.partner_rate_pct / 100.0, 2)
         ELSE 0 END AS partner_fee_owed,
    CASE WHEN g.verdict = 'china'   THEN 'claimable'
         WHEN g.verdict = 'unknown' THEN 'unknown_nationality'
         ELSE 'not_china' END AS claim_status
FROM graded g
"""

_CLAIM = """
CREATE VIEW lens_ps_claim AS
WITH owed AS (
    SELECT wayward_brand_id,
           max(verdict)  AS verdict,
           max(ownership) AS ownership,
           sum(mgmt_fee_owed)    AS mgmt_fee_owed,
           sum(partner_fee_owed) AS partner_fee_owed,
           max(partner_of_record) AS partner_of_record,
           bool_or(claim_status = 'unknown_nationality') AS any_unknown
    FROM lens_ps_commission_ledger
    GROUP BY wayward_brand_id
),
paid AS (
    SELECT wayward_brand_id, sum(rev_share_stated) AS wayward_paid
    FROM ps_payment_events
    WHERE wayward_brand_id IS NOT NULL
    GROUP BY wayward_brand_id
),
ppaid AS (
    SELECT wayward_brand_id, sum(amount_paid) AS partner_paid
    FROM ps_partner_payouts
    WHERE wayward_brand_id IS NOT NULL
    GROUP BY wayward_brand_id
)
SELECT
    o.wayward_brand_id,
    b.brand_name,
    o.verdict, o.ownership,
    round(o.mgmt_fee_owed, 2)              AS mgmt_fee_owed,
    round(COALESCE(p.wayward_paid, 0), 2)  AS wayward_paid,
    round(GREATEST(o.mgmt_fee_owed - COALESCE(p.wayward_paid, 0), 0), 2) AS ps_claim_owed,
    o.partner_of_record,
    round(o.partner_fee_owed, 2)           AS partner_fee_owed,
    round(COALESCE(pp.partner_paid, 0), 2) AS partner_paid,
    round(GREATEST(o.partner_fee_owed - COALESCE(pp.partner_paid, 0), 0), 2) AS partner_claim_owed
FROM owed o
JOIN ps_brands b ON b.wayward_brand_id = o.wayward_brand_id
LEFT JOIN paid p  ON p.wayward_brand_id = o.wayward_brand_id
LEFT JOIN ppaid pp ON pp.wayward_brand_id = o.wayward_brand_id
"""


def upgrade() -> None:
    op.execute(_RATE_SCHEDULE)
    op.execute(_LEDGER)
    op.execute(_CLAIM)

    op.execute(
        "COMMENT ON VIEW lens_ps_rate_schedule IS "
        "$c$The 10/6/3 commission ladder per brand x product. effective_anchor = the ladder start, "
        "re-anchored to a QUALIFYING reactivation (GREATEST(productive_date, reactivated_at)); the "
        "whole ladder restarts from there. rate_10_until = +12mo (10% before it), rate_6_until = +18mo "
        "(6% between), 3% after. Live from ps_product_subscriptions.$c$"
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_commission_ledger IS "
        "$c$The money waterfall, live, at brand x product x month. usage_collected = PS base-fee lines "
        "actually PAID (is_ps_base, invoice_status=paid, brand+product+month not null) — reconciles to "
        "the penny with the retired writer. mgmt_fee_owed = usage_collected x mgmt_rate, but ONLY when "
        "claimable: verdict=china AND ownership in (never_listed, flat_fee_era_eric) AND month >= "
        "revenue-start (2025-10-01 never-listed / 2025-12-01 flat-fee, cip_103). claim_status flags "
        "unknown-nationality (queued, never denied). partner_fee_owed = collected x partner_rate "
        "(flat_fee partners = 0) within the credit window. Money math is LIVE here; the frozen "
        "ps_monthly_earnings stays authoritative until this reconciles (P2 swap).$c$"
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_claim IS "
        "$c$Brand-grain net claim. ps_claim_owed = GREATEST(mgmt_fee_owed - wayward_paid, 0) where "
        "wayward_paid = ps_payment_events.rev_share_stated. partner_claim_owed = GREATEST(partner_fee_"
        "owed - partner_paid, 0) where partner_paid = ps_partner_payouts. Floored at 0 per brand — an "
        "overpaid brand is $0, never negative (never offsets another brand). THE recovery number lives "
        "here. A claim handed to Wayward is pinned into ps_claim_statements, not read live.$c$"
    )
    for v in ("lens_ps_rate_schedule", "lens_ps_commission_ledger", "lens_ps_claim"):
        for r in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {v} TO {r}")

    # ps_claim_statements — the ONE frozen thing: pinned as-of copies of a claim handed to Wayward.
    op.execute(
        """
        CREATE TABLE ps_claim_statements (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL,
            statement_label text NOT NULL,
            generated_at timestamptz NOT NULL DEFAULT now(),
            wayward_brand_id uuid,
            brand_name text,
            verdict text,
            ownership text,
            mgmt_fee_owed numeric,
            wayward_paid numeric,
            ps_claim_owed numeric,
            as_of_note text,
            source_ref text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE ps_claim_statements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_claim_statements FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON ps_claim_statements "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )
    op.execute(
        "COMMENT ON TABLE ps_claim_statements IS "
        "$c$Pinned AS-OF copies of a claim handed to Wayward — a bank statement vs the live balance "
        "(Decision of Record 2026-07-15). Populated by SELECT-ing lens_ps_claim INTO a labeled "
        "snapshot at statement time, so the number handed over cannot shift mid-negotiation. The LIVE "
        "number is lens_ps_claim; this is the frozen record.$c$"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_claim_statements TO {r}")
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cip_rls_test_role') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON ps_claim_statements TO cip_rls_test_role;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ps_claim_statements")
    op.execute("DROP VIEW IF EXISTS lens_ps_claim")
    op.execute("DROP VIEW IF EXISTS lens_ps_commission_ledger")
    op.execute("DROP VIEW IF EXISTS lens_ps_rate_schedule")
