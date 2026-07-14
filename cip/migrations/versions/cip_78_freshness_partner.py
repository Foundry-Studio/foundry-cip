# foundry: kind=migration domain=client-intelligence-platform
"""cip_78: a freshness board that tells the truth, and partner performance that tells it too.

FRESHNESS — because a stale number is a wrong number that looks fine
--------------------------------------------------------------------
Three of our sources sync hourly and have done all along (HubSpot, Zendesk and the lens mirror, with a freshness watchdog twice an hour). Three of OURS — Stripe, the Slack brand feed, and
Jake's monthly reports — are MANUAL. Somebody has to remember. Nobody will.

lens_ps_source_freshness puts every source on one board with a staleness SLA, so "when was this
last true?" is a question with an answer rather than an assumption. A manual source with no
schedule is shown as exactly that: an unowned risk, not a green tick.

PARTNER PERFORMANCE — the question Tim actually asks
----------------------------------------------------
"Who brings brands that PRODUCE, versus who brings brands that sign and die?"

A partner who refers 100 brands that never make a sale has referred nothing. The count of brands
is vanity; the count that go PRODUCTIVE is the number. And the ones that produced and then went
dormant are the win-back list — which is a performance signal about the partner AND a work queue
for the team, at the same time.

NB: a revision id must be <= 32 CHARACTERS. alembic_version.version_num is varchar(32), so a
longer id lets the migration RUN and then fails to RECORD that it ran — the most confusing
failure available. 'cip_78_freshness_and_partner_perf' was 33.

Revision ID: cip_78_freshness_partner
Revises: cip_77_deal_and_events
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_78_freshness_partner"
down_revision: str | Sequence[str] | None = "cip_77_deal_and_events"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # ── FRESHNESS: every source, one board, with its SLA ─────────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_source_freshness")
    op.execute(
        """
        CREATE VIEW lens_ps_source_freshness AS
        WITH scheduled AS (
            -- the connectors that already run on the FAS scheduler.
            -- CAST TO TEXT: a UNION takes its column type from the FIRST branch, and
            -- cip_sync_runs.connector_name is varchar(32) — long enough for 'HubSpotConnector',
            -- too short for the literal source names below.
            SELECT DISTINCT ON (connector_name)
                   connector_name::text                    AS source,
                   'scheduled'::text                       AS mode,
                   ended_at                                AS last_success,
                   rows_ingested,
                   status::text                            AS status
            FROM cip_sync_runs
            WHERE status = 'success'
            ORDER BY connector_name, started_at DESC
        ),
        manual AS (
            -- OUR ingests. No schedule. Somebody has to remember, and nobody will.
            SELECT 'Stripe (invoices/lines/customers)'::text AS source, 'MANUAL'::text AS mode,
                   (SELECT max(ingested_at) FROM ps_stripe_invoice_lines) AS last_success,
                   (SELECT count(*) FROM ps_stripe_invoice_lines)         AS rows_ingested,
                   'no schedule'::text                                    AS status
            UNION ALL
            SELECT 'Slack brand feed'::text, 'MANUAL'::text,
                   (SELECT max(ingested_at) FROM ps_brand_observations
                     WHERE source_system LIKE 'slack:%'),
                   (SELECT count(*) FROM ps_brand_observations
                     WHERE source_system LIKE 'slack:%'),
                   'no schedule'::text
            UNION ALL
            SELECT 'Jake monthly payment reports'::text, 'MANUAL'::text,
                   (SELECT max(ingested_at) FROM ps_payment_events),
                   (SELECT count(*) FROM ps_payment_events),
                   'no schedule'::text
            UNION ALL
            SELECT 'ADDED (human knowledge)'::text, 'ON DEMAND'::text,
                   (SELECT max(asserted_at) FROM ps_added_facts),
                   (SELECT count(*) FROM ps_added_facts WHERE superseded_by IS NULL),
                   'human'::text
        ),
        all_sources AS (
            SELECT source, mode, last_success, rows_ingested, status FROM scheduled
            UNION ALL
            SELECT source, mode, last_success, rows_ingested, status FROM manual
        )
        SELECT
            source,
            mode,
            last_success,
            rows_ingested,
            status,
            CASE WHEN last_success IS NULL THEN NULL
                 ELSE round(EXTRACT(EPOCH FROM (now() - last_success)) / 3600.0, 1)
            END                                                  AS hours_since,
            -- the SLA: what "stale" means for THIS source
            CASE
                WHEN mode = 'MANUAL'    THEN 'no schedule — an UNOWNED RISK, not a green tick'
                WHEN mode = 'ON DEMAND' THEN 'human-driven; staleness is not a fault'
                WHEN last_success IS NULL THEN 'NEVER RUN'
                WHEN now() - last_success > INTERVAL '3 hours' THEN 'STALE — hourly source, >3h old'
                ELSE 'fresh'
            END                                                  AS freshness
        FROM all_sources
        ORDER BY
            CASE WHEN mode = 'MANUAL' THEN 0 ELSE 1 END,   -- unowned risks first
            last_success DESC NULLS FIRST
        """
    )
    # NB: no ":17"-style text in these comments — SQLAlchemy reads a colon-number as a bind param.
    op.execute(
        "COMMENT ON VIEW lens_ps_source_freshness IS "
        "'WHEN WAS EACH SOURCE LAST TRUE? A stale number is a wrong number that looks fine. "
        "HubSpot, Zendesk and the lens mirror run HOURLY on the FAS scheduler (past 17, 47 and 37 "
        "minutes respectively) and have done all along. Stripe, the Slack brand feed and Jake''s "
        "reports are MANUAL — somebody has to remember, and nobody will. Those are shown as "
        "UNOWNED RISKS rather than green ticks, and they sort to the top.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_source_freshness TO {r}")

    # ── PARTNER PERFORMANCE: who brings brands that PRODUCE? ─────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_performance CASCADE")
    op.execute(
        """
        CREATE VIEW lens_ps_partner_performance AS
        WITH deals AS (
            SELECT
                COALESCE(NULLIF(pc.lead_source_initial, ''), 'unattributed') AS partner,
                pc.wayward_brand_id,
                pc.product_id,
                s.productive_date,
                s.dormant_since,
                s.reactivated_at,
                br.signup_date,
                -- did this deal ever actually SELL anything?
                EXISTS (SELECT 1 FROM ps_stripe_invoice_lines l
                         WHERE l.wayward_brand_id = pc.wayward_brand_id
                           AND l.product_id = pc.product_id
                           AND l.is_ps_base AND l.amount > 0)                AS produced,
                COALESCE((SELECT sum(l.amount) FILTER (WHERE l.invoice_status = 'paid')
                          FROM ps_stripe_invoice_lines l
                          WHERE l.wayward_brand_id = pc.wayward_brand_id
                            AND l.product_id = pc.product_id
                            AND l.is_ps_base), 0)                            AS usage_generated
            FROM ps_partner_credit pc
            JOIN ps_brands br ON br.wayward_brand_id = pc.wayward_brand_id
            LEFT JOIN ps_product_subscriptions s
                   ON s.wayward_brand_id = pc.wayward_brand_id
                  AND s.product_id = pc.product_id
            WHERE pc.wayward_brand_id IS NOT NULL
        )
        SELECT
            d.partner,
            r.name                                                       AS partner_name,
            r.company_name,
            count(*)                                                     AS deals_referred,
            count(*) FILTER (WHERE d.produced)                           AS deals_that_produced,
            count(*) FILTER (WHERE NOT d.produced)                       AS signed_and_died,
            round(100.0 * count(*) FILTER (WHERE d.produced)
                  / NULLIF(count(*), 0), 1)                              AS production_rate_pct,
            count(*) FILTER (WHERE d.produced AND d.dormant_since IS NOT NULL)
                                                                         AS produced_then_went_quiet,
            count(*) FILTER (WHERE d.reactivated_at IS NOT NULL)         AS reactivated,
            round(sum(d.usage_generated), 2)                             AS usage_fees_generated,
            round(avg(d.usage_generated) FILTER (WHERE d.produced), 2)   AS avg_per_producing_deal,
            -- how long from signup to the first sale? A partner who brings brands that take a
            -- year to sell is not the same as one whose brands sell in a month.
            round(avg(
                CASE WHEN d.productive_date IS NOT NULL AND d.signup_date IS NOT NULL
                     THEN (d.productive_date - d.signup_date)::numeric END), 0)
                                                                         AS avg_days_to_first_sale
        FROM deals d
        LEFT JOIN ps_partner_registry r ON r.partner_id = d.partner
        GROUP BY d.partner, r.name, r.company_name
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_partner_performance IS "
        "'WHO BRINGS BRANDS THAT PRODUCE, versus who brings brands that SIGN AND DIE. A partner "
        "who refers 100 brands that never make a sale has referred nothing — deals_referred is "
        "vanity, production_rate_pct is the number. produced_then_went_quiet is both a performance "
        "signal about the partner AND the win-back queue for the team. Keyed on "
        "lead_source_initial (who brought the brand to THIS product), because the unit is the "
        "DEAL, not the brand.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_partner_performance TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_performance CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_source_freshness")
