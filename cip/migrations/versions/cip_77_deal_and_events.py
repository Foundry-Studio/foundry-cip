# foundry: kind=migration domain=client-intelligence-platform
"""cip_77: the DEAL is the unit. Two lead sources. And the date pipeline, modelled as a pipeline.

TIM, 2026-07-14: "The unit is the DEAL — a brand on a PRODUCT."

Roborock is TWO deals: Connect (Eric's — he earns an ongoing 10%) and Boost (a separate,
contestable product). Each has its own first sale, its own 10/6/3 clock, its own lead source, and
its own answer to "is this ours?". The old schema kept most of this per brand x product already,
but it had NO WAY TO SAY WHO BROUGHT THE DEAL — which is the fact the whole contested-Boost book
now turns on.

TWO LEAD SOURCES, BECAUSE A DEAL CAN CHANGE HANDS
-------------------------------------------------
    lead_source_initial      who brought the brand TO THIS PRODUCT originally
    lead_source_activation   who REVIVED it after it went dormant

Eric brings a brand to Connect -> it dies -> WE reactivate it. Both facts are true. The
ACTIVATION is what decides who earns going forward (doc 15 §5, rules 3, 4 and 7).

    Rule 7 (Boost on the contract-10% book): OURS with activation evidence. THEIRS if the
    evidence points to them — OR IF NOBODY KNOWS.

So `lead_source_activation IS NULL` is not a cosmetic gap. **Silence hands the revenue to Eric.**

That makes this a BUSINESS PROCESS, not a schema change. There is almost no historical evidence
for who reactivated what; the column starts filling the day the team begins logging. Hence
EVIDENCE DISCIPLINE: every cross-sell and reactivation gets logged AT THE MOMENT IT HAPPENS, into
ps_added_facts, with a link. Contemporaneous evidence wins attribution. Reconstructed evidence
does not.

THE DATE PIPELINE, MODELLED AS A PIPELINE
------------------------------------------
Five different events, with real and DIFFERENT lags:

    usage month -> Wayward reconciles -> invoice to the brand -> brand pays -> WAYWARD PAYS US

Measured, not assumed: Wayward's payment to us lands ~2 MONTHS after the usage it settles (794
brand-matches at a 2-month lag; some at 1, some at 3+). Collapsing these into one date is what
made owed-vs-paid month-matching wrong no matter how the join was written.

Plus the brand lifecycle, per deal: onboarded -> first billed sale -> dormant (90d) -> reactivated.

Revision ID: cip_77_deal_and_events
Revises: cip_76_contacts_bridge
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_77_deal_and_events"
down_revision: str | Sequence[str] | None = "cip_76_contacts_bridge"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # ── the two lead sources, per DEAL ──────────────────────────────────────
    op.execute(
        "ALTER TABLE ps_partner_credit ADD COLUMN IF NOT EXISTS lead_source_initial TEXT"
    )
    op.execute(
        "ALTER TABLE ps_partner_credit ADD COLUMN IF NOT EXISTS lead_source_activation TEXT"
    )
    op.execute(
        "ALTER TABLE ps_partner_credit "
        "ADD COLUMN IF NOT EXISTS activation_evidence_ref TEXT"
    )
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.lead_source_initial IS "
        "'Who brought the brand TO THIS PRODUCT originally. Derivable from Wayward''s own data "
        "(deal_source / referral_source in the onboarding feed, Eric''s sheets).'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.lead_source_activation IS "
        "'Who REVIVED this deal after it went dormant. *** THIS DECIDES WHO EARNS GOING FORWARD "
        "(doc 15 §5, rules 3/4/7). *** On the contract-10%% book, Boost and reactivation are "
        "CONTESTED: ours with activation evidence, theirs if the evidence points to them OR IF "
        "NOBODY KNOWS. So a NULL here is not a cosmetic gap — SILENCE HANDS THE REVENUE TO ERIC. "
        "There is almost no historical evidence for this; the column fills from the day the team "
        "starts logging. Contemporaneous evidence wins attribution; reconstructed evidence does "
        "not.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.activation_evidence_ref IS "
        "'The PROOF: a Slack permalink, an email, a ps_added_facts id. Without it, "
        "lead_source_activation is an assertion — and on a brand another partner is being paid "
        "on, an assertion loses.'"
    )

    # Backfill the INITIAL lead source from Wayward's own data. (The ACTIVATION source cannot be
    # backfilled — it does not exist yet. That is the point.)
    op.execute(
        """
        UPDATE ps_partner_credit pc
           SET lead_source_initial = COALESCE(
                 NULLIF(pc.partner_of_record, 'unassigned'),
                 CASE
                   WHEN pc.deal_source LIKE 'China Referral - %'
                     THEN lower(replace(pc.deal_source, 'China Referral - ', ''))
                   ELSE NULL
                 END)
         WHERE pc.lead_source_initial IS NULL
        """
    )

    # ── the date pipeline, per DEAL ─────────────────────────────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_deal_timeline")
    op.execute(
        """
        CREATE VIEW lens_ps_deal_timeline AS
        WITH billing AS (
            SELECT wayward_brand_id, product_id,
                   min(billing_month)                                        AS first_usage_month,
                   max(billing_month)                                        AS last_usage_month,
                   min(billing_month) FILTER (WHERE invoice_status = 'paid') AS first_collected_month,
                   max(billing_month) FILTER (WHERE invoice_status = 'paid') AS last_collected_month,
                   count(DISTINCT billing_month)                             AS months_with_usage
            FROM ps_stripe_invoice_lines
            WHERE is_ps_base AND amount > 0 AND billing_month IS NOT NULL
              AND wayward_brand_id IS NOT NULL AND product_id IS NOT NULL
            GROUP BY 1, 2
        ),
        wayward_paid AS (
            -- What Wayward paid US, and WHEN. NOTE the axis: payment_date is when THEY PAID,
            -- roughly two months after the usage it settles. Never compare it to a usage month.
            SELECT wayward_brand_id,
                   min(payment_date) AS first_paid_to_us,
                   max(payment_date) AS last_paid_to_us
            FROM ps_payment_events
            WHERE rev_share_stated > 0 AND wayward_brand_id IS NOT NULL
            GROUP BY 1
        )
        SELECT
            s.wayward_brand_id,
            b.brand_name,
            s.product_id,
            -- lifecycle
            br.signup_date                    AS onboarded,
            br.signup_date_source             AS onboarded_source,
            s.productive_date                 AS first_billed_sale,
            s.dormant_since,
            s.reactivated_at,
            s.reactivation_qualifies,
            -- the money pipeline, stage by stage
            bi.first_usage_month,
            bi.last_usage_month,
            bi.first_collected_month,
            bi.last_collected_month,
            bi.months_with_usage,
            wp.first_paid_to_us,
            wp.last_paid_to_us,
            -- the measured lag: how long from a brand's LAST usage to Wayward paying us
            CASE WHEN wp.last_paid_to_us IS NOT NULL AND bi.last_collected_month IS NOT NULL
                 THEN (EXTRACT(YEAR  FROM age(wp.last_paid_to_us, bi.last_collected_month)) * 12
                     + EXTRACT(MONTH FROM age(wp.last_paid_to_us, bi.last_collected_month)))::int
            END                               AS payment_lag_months,
            -- attribution
            pc.lead_source_initial,
            pc.lead_source_activation,
            pc.activation_evidence_ref,
            pc.partner_of_record,
            pc.deal_type,
            st.is_excluded,
            st.someone_else_earning,
            st.is_winnable
        FROM ps_product_subscriptions s
        JOIN ps_brands b            ON b.wayward_brand_id = s.wayward_brand_id
        JOIN ps_brands br           ON br.wayward_brand_id = s.wayward_brand_id
        LEFT JOIN billing bi        ON bi.wayward_brand_id = s.wayward_brand_id
                                   AND bi.product_id = s.product_id
        LEFT JOIN wayward_paid wp   ON wp.wayward_brand_id = s.wayward_brand_id
        LEFT JOIN ps_partner_credit pc ON pc.wayward_brand_id = s.wayward_brand_id
                                      AND pc.product_id = s.product_id
        LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = s.wayward_brand_id
        WHERE s.wayward_brand_id IS NOT NULL
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_deal_timeline IS "
        "'ONE ROW PER DEAL (brand x PRODUCT) — the unit Tim actually works in. Roborock appears "
        "TWICE: Connect (Eric''s) and Boost (contested). "
        "*** THE DATE PIPELINE HAS FIVE STAGES WITH DIFFERENT LAGS: *** usage month -> Wayward "
        "reconciles -> invoice to the brand -> brand pays -> WAYWARD PAYS US (~2 months after the "
        "usage it settles; measured, not assumed). NEVER compare a usage month to a payment "
        "month — that mismatch is why owed-vs-paid kept coming out wrong however the join was "
        "written. Reconcile at BRAND level, or shift by the observed lag.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_deal_timeline.payment_lag_months IS "
        "'Months between this deal''s last COLLECTED usage and Wayward''s last payment to us. "
        "Typically 2. It is the single most misunderstood number in this dataset.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_deal_timeline TO {r}")

    # ── the attribution gap, priced by what it risks ────────────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_attribution_at_risk")
    op.execute(
        """
        CREATE VIEW lens_ps_attribution_at_risk AS
        SELECT
            t.wayward_brand_id,
            t.brand_name,
            t.product_id,
            t.reactivated_at,
            t.lead_source_initial,
            t.lead_source_activation,
            t.activation_evidence_ref,
            t.someone_else_earning,
            t.is_winnable,
            CASE
                WHEN t.someone_else_earning AND t.lead_source_activation IS NULL
                     THEN 'SILENCE DEFAULTS TO THE INCUMBENT — log who drove this, or lose it'
                WHEN t.someone_else_earning AND t.activation_evidence_ref IS NULL
                     THEN 'claimed, but NO EVIDENCE REF — an assertion loses to a signed contract'
                ELSE 'ok'
            END AS risk
        FROM lens_ps_deal_timeline t
        WHERE t.reactivated_at IS NOT NULL
           OR (t.product_id = 'boosted' AND t.someone_else_earning)
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_attribution_at_risk IS "
        "'Deals where WHO DROVE IT decides who gets paid — and we have not written it down. On the "
        "contract-10%% book, Boost and reactivation are CONTESTED and SILENCE DEFAULTS TO THE "
        "INCUMBENT. Every row here is revenue we may be handing to Eric by not logging a Slack "
        "link. This view exists to make that loss visible BEFORE it happens, not after.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_attribution_at_risk TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_attribution_at_risk")
    op.execute("DROP VIEW IF EXISTS lens_ps_deal_timeline")
    for col in ("lead_source_initial", "lead_source_activation", "activation_evidence_ref"):
        op.execute(f"ALTER TABLE ps_partner_credit DROP COLUMN IF EXISTS {col}")
