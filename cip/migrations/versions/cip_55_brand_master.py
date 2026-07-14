# foundry: kind=migration domain=client-intelligence-platform
"""cip_55: ps_brands — the brand MASTER. Plus FKs, and NULL stops meaning zero.

THREE STRUCTURAL FIXES. No data is computed here; this makes bad states unrepresentable.

────────────────────────────────────────────────────────────────────────────────
1. THE BRAND MASTER (ps_brands)

wayward_brand_id is the one identifier every source agrees on — Stripe (customer
metadata.brandId), the Slack brand feed, Jake's reports, the frozen exclusion list, Eric's
sheets. And yet there was NO TABLE WHERE IT IS THE PRIMARY KEY. It was a loose UUID column
scattered across eight tables with no foreign keys, so nothing enforced that a brand exists
or that two tables meant the same brand.

That is WHY coverage sat at 65% / 78% / 75% and nobody noticed: a missing brand id was not
an error, it was just... nothing. And "nothing" then priced to $0.

ps_brands is the registry. Every wayward_brand_id we have ever seen, from any source, gets a
row. Everything else FKs to it. A brand that is not in the master can no longer be
referenced, and a bad id fails loudly at write time instead of silently at read time.

cip_clients.id stays as the CIP-internal surrogate for lens-mirror joins. It is NOT the
identity and must never again be used as one.

────────────────────────────────────────────────────────────────────────────────
2. NULL STOPS MEANING ZERO  (the $1.25M bug, fixed at the root)

ps_monthly_earnings computed:

    ps_gross_owed = ROUND(usage_collected * COALESCE(ps_rate_pct, 0) / 100, 2)

That COALESCE turns "we do not know the rate" into "the rate is zero", which turns into "we
are owed nothing" — a CONFIDENT $0 where the honest answer was UNKNOWN. $1.25M of collected
usage priced to zero and looked like a fact.

Fixed: drop the COALESCE. NULL now PROPAGATES through the arithmetic, so an unknown rate
yields an unknown amount, which is the truth. A sum() will skip it (and the row count will
not lie about it), instead of quietly adding a fake zero.

Partner is different and stays COALESCE'd to 0 — because there we DO know: 'unassigned'
means a partner rate of zero as a DECISION, not as a gap. That asymmetry is the whole point:
  NULL     = we don't know          -> must not become a number
  sentinel = we know there is none  -> is legitimately zero

────────────────────────────────────────────────────────────────────────────────
3. CONSTRAINTS THAT MAKE THE BROKEN STATES IMPOSSIBLE

Not "discouraged" — impossible. credit_end must follow credit_start; a partner rate cannot
exceed the 10 points we are paid; a period_month must be the 1st.

Revision ID: cip_55_brand_master
Revises: cip_54_identity_spine
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_55_brand_master"
down_revision: str | Sequence[str] | None = "cip_54_identity_spine"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# Tables carrying wayward_brand_id that should FK to the master.
FK_TABLES = (
    "ps_stripe_invoices",
    "ps_stripe_invoice_lines",
    "ps_payment_events",
    "ps_product_subscriptions",
    "ps_partner_credit",
    "ps_attribution",
    "ps_excluded_brands",
    "ps_brand_observations",
    "ps_monthly_earnings",
    "ps_information_gaps",
    "ps_brand_contacts",
    "ps_reactivation_rights",
)


def upgrade() -> None:
    # ── 1. The master ───────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE ps_brands (
            wayward_brand_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,

            brand_name TEXT,
            client_id UUID,              -- the CIP surrogate, when one exists. NOT the identity.

            -- where we have ever seen this brand (provenance, not truth)
            seen_in_stripe BOOLEAN NOT NULL DEFAULT false,
            seen_in_slack_feed BOOLEAN NOT NULL DEFAULT false,
            seen_in_payment_reports BOOLEAN NOT NULL DEFAULT false,
            seen_in_exclusion_list BOOLEAN NOT NULL DEFAULT false,
            seen_in_eric_sheets BOOLEAN NOT NULL DEFAULT false,

            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ps_brands IS "
        "'THE BRAND MASTER. One row per wayward_brand_id — the ONE identifier every source "
        "agrees on (Stripe customer.metadata.brandId, the Slack brand feed, Jake''s reports, "
        "the frozen exclusion list, Eric''s sheets). "
        "Before this table existed, wayward_brand_id was a loose UUID scattered across eight "
        "tables with NO foreign keys, so nothing enforced that a brand existed or that two "
        "tables meant the same brand. A missing id was not an error — it was nothing. And "
        "nothing priced to $0: that is how $1.25M of collected usage silently disappeared. "
        "Everything now FKs here. cip_clients.id remains a CIP-internal SURROGATE for "
        "lens-mirror joins; it is NOT the identity and must never be used as one again.'"
    )
    op.execute("ALTER TABLE ps_brands ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_brands FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON ps_brands "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_brands TO {r}")

    # Seed it from EVERY source we hold. Union, not intersection — a brand we have only
    # ever seen in one place is still a brand.
    op.execute(
        f"""
        INSERT INTO ps_brands (wayward_brand_id, tenant_id)
        SELECT DISTINCT wayward_brand_id, '{PS_TENANT}'::uuid FROM (
            SELECT wayward_brand_id FROM ps_stripe_invoices        WHERE wayward_brand_id IS NOT NULL
            UNION SELECT wayward_brand_id FROM ps_payment_events    WHERE wayward_brand_id IS NOT NULL
            UNION SELECT wayward_brand_id FROM ps_brand_observations WHERE wayward_brand_id IS NOT NULL
            UNION SELECT wayward_brand_id FROM ps_excluded_brands   WHERE wayward_brand_id IS NOT NULL
            UNION SELECT wayward_brand_id FROM cip_clients          WHERE wayward_brand_id IS NOT NULL
        ) s
        ON CONFLICT (wayward_brand_id) DO NOTHING
        """
    )
    # Name + surrogate + provenance flags, from what we already hold.
    op.execute(
        """
        UPDATE ps_brands b SET
            brand_name = COALESCE(b.brand_name, o.name),
            client_id  = COALESCE(b.client_id, c.id),
            seen_in_stripe          = EXISTS (SELECT 1 FROM ps_stripe_invoices     x WHERE x.wayward_brand_id = b.wayward_brand_id),
            seen_in_payment_reports = EXISTS (SELECT 1 FROM ps_payment_events      x WHERE x.wayward_brand_id = b.wayward_brand_id),
            seen_in_exclusion_list  = EXISTS (SELECT 1 FROM ps_excluded_brands     x WHERE x.wayward_brand_id = b.wayward_brand_id),
            seen_in_slack_feed      = EXISTS (SELECT 1 FROM ps_brand_observations  x WHERE x.wayward_brand_id = b.wayward_brand_id AND x.source_system LIKE 'slack:%'),
            seen_in_eric_sheets     = EXISTS (SELECT 1 FROM ps_brand_observations  x WHERE x.wayward_brand_id = b.wayward_brand_id AND x.source_system LIKE 'gsheet:%'),
            updated_at = now()
        FROM (
            SELECT wayward_brand_id, max(value) AS name
            FROM ps_brand_observations WHERE field='brand_name' GROUP BY 1
        ) o
        FULL OUTER JOIN cip_clients c ON c.wayward_brand_id = o.wayward_brand_id
        WHERE b.wayward_brand_id = COALESCE(o.wayward_brand_id, c.wayward_brand_id)
        """
    )
    op.execute("CREATE INDEX idx_ps_brands_client ON ps_brands (tenant_id, client_id)")

    # ── 2. FKs — a bad id now fails at WRITE time, not silently at read time ─
    for tbl in FK_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns
                            WHERE table_name = '{tbl}' AND column_name = 'wayward_brand_id')
                THEN
                    -- orphans must not block the FK; park them as brands in their own right
                    EXECUTE 'INSERT INTO ps_brands (wayward_brand_id, tenant_id)
                             SELECT DISTINCT wayward_brand_id, ''{PS_TENANT}''::uuid
                             FROM {tbl} WHERE wayward_brand_id IS NOT NULL
                             ON CONFLICT (wayward_brand_id) DO NOTHING';
                    EXECUTE 'ALTER TABLE {tbl}
                             ADD CONSTRAINT fk_{tbl}_brand
                             FOREIGN KEY (wayward_brand_id)
                             REFERENCES ps_brands (wayward_brand_id)
                             ON DELETE RESTRICT';
                END IF;
            END $$;
            """
        )

    # ── 3. NULL stops meaning zero ──────────────────────────────────────────
    # The dashboards read these generated columns, so they must be dropped and rebuilt
    # around the change.
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_performance")
    op.execute("DROP VIEW IF EXISTS lens_ps_client_performance")
    # Drop and rebuild the generated columns without COALESCE on the RATE.
    op.execute(
        """
        ALTER TABLE ps_monthly_earnings
            DROP COLUMN IF EXISTS variance,
            DROP COLUMN IF EXISTS ps_net_owed,
            DROP COLUMN IF EXISTS ps_gross_owed
        """
    )
    op.execute(
        """
        ALTER TABLE ps_monthly_earnings
            ADD COLUMN ps_gross_owed NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * ps_rate_pct / 100.0, 2)
                ) STORED,
            ADD COLUMN ps_net_owed NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * ps_rate_pct / 100.0, 2)
                    - ROUND(usage_collected * COALESCE(partner_rate_pct, 0) / 100.0, 2)
                ) STORED,
            ADD COLUMN variance NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * ps_rate_pct / 100.0, 2)
                    - ROUND(usage_collected * COALESCE(partner_rate_pct, 0) / 100.0, 2)
                    - ps_actually_paid
                ) STORED
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.ps_gross_owed IS "
        "'NULL when ps_rate_pct is NULL — deliberately. The previous version wrapped the rate "
        "in COALESCE(rate, 0), which turned ''we do not know the rate'' into ''the rate is "
        "zero'' into ''we are owed nothing'': a CONFIDENT $0 where the honest answer was "
        "UNKNOWN. $1.25M of collected usage priced to zero and looked like a fact. "
        "NULL now PROPAGATES: an unknown rate yields an unknown amount. sum() skips it rather "
        "than adding a fake zero. "
        "Contrast partner_rate_pct, which IS still COALESCE''d to 0 — because there we KNOW: "
        "''unassigned'' means zero as a DECISION, not as a gap. "
        "NULL = we do not know (must never become a number). "
        "Sentinel = we know there is none (legitimately zero).'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.variance IS "
        "'THE CLAIM: what we should have been paid minus what we were. NULL when the rate is "
        "unknown — an unknown claim is not a zero claim. POSITIVE = they underpaid. "
        "Remember §4.4: Wayward''s records are ''conclusive and controlling'' with a 30-DAY "
        "dispute window.'"
    )

    # Rebuild the dashboards on the corrected columns.
    op.execute(
        """
        CREATE VIEW lens_ps_partner_performance AS
        SELECT
            e.tenant_id, e.partner_id,
            r.name AS partner_name, r.company_name,
            e.period_month, e.product_id,
            count(DISTINCT e.wayward_brand_id)  AS brands,
            sum(e.usage_billed)                 AS usage_billed,
            sum(e.usage_collected)              AS usage_collected,
            sum(e.usage_outstanding)            AS usage_outstanding,
            sum(e.ps_gross_owed)                AS ps_gross,
            sum(e.partner_owed)                 AS partner_earned,
            sum(e.ps_net_owed)                  AS ps_net,
            sum(e.variance)                     AS variance,
            count(*) FILTER (WHERE e.ps_rate_pct IS NULL) AS rows_with_unknown_rate
        FROM ps_monthly_earnings e
        LEFT JOIN ps_partner_registry r
               ON r.tenant_id = e.tenant_id AND r.partner_id = e.partner_id
        WHERE e.partner_id IS NOT NULL AND e.partner_id <> 'unassigned'
        GROUP BY 1,2,3,4,5,6
        """
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_partner_performance.rows_with_unknown_rate IS "
        "'How many brand-months in this total had an UNKNOWN rate and therefore contributed "
        "NOTHING to it. If this is above zero, the money figures beside it are INCOMPLETE — "
        "they are a floor, not a total. Surfaced deliberately: the old schema hid exactly "
        "this behind a COALESCE and turned unknowns into confident zeros.'"
    )
    op.execute(
        """
        CREATE VIEW lens_ps_client_performance AS
        SELECT
            e.tenant_id, e.client_id, e.wayward_brand_id, e.brand_name,
            e.period_month, e.product_id,
            e.eligibility, e.excluded_bucket, e.is_chinese,
            e.usage_billed, e.usage_collected, e.usage_outstanding,
            e.ps_rate_pct, e.months_since_productive,
            e.ps_gross_owed,
            e.partner_id, e.partner_owed,
            e.ps_net_owed, e.ps_actually_paid, e.variance,
            (e.ps_rate_pct IS NULL) AS rate_unknown
        FROM ps_monthly_earnings e
        """
    )
    for v in ("lens_ps_partner_performance", "lens_ps_client_performance"):
        for r in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {v} TO {r}")

    # ── 4. Constraints that make the broken states impossible ───────────────
    op.execute(
        """
        ALTER TABLE ps_partner_credit
            ADD CONSTRAINT ck_partner_credit_window
                CHECK (credit_end IS NULL OR credit_start IS NULL
                       OR credit_end > credit_start),
            ADD CONSTRAINT ck_partner_credit_rate
                CHECK (partner_rate IS NULL OR (partner_rate >= 0 AND partner_rate <= 10))
        """
    )
    op.execute(
        """
        ALTER TABLE ps_monthly_earnings
            ADD CONSTRAINT ck_earnings_month_is_first
                CHECK (period_month = date_trunc('month', period_month)::date),
            ADD CONSTRAINT ck_earnings_rate
                CHECK (ps_rate_pct IS NULL OR ps_rate_pct IN (3, 6, 10)),
            ADD CONSTRAINT ck_earnings_partner_rate
                CHECK (partner_rate_pct IS NULL
                       OR (partner_rate_pct >= 0 AND partner_rate_pct <= 10))
        """
    )
    op.execute(
        "COMMENT ON CONSTRAINT ck_earnings_rate ON ps_monthly_earnings IS "
        "'The contract knows exactly three rates: 10 (months 1-12), 6 (13-18), 3 (19+). "
        "Anything else is a bug, not a business case.'"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE ps_monthly_earnings
            DROP CONSTRAINT IF EXISTS ck_earnings_partner_rate,
            DROP CONSTRAINT IF EXISTS ck_earnings_rate,
            DROP CONSTRAINT IF EXISTS ck_earnings_month_is_first
        """
    )
    op.execute(
        """
        ALTER TABLE ps_partner_credit
            DROP CONSTRAINT IF EXISTS ck_partner_credit_rate,
            DROP CONSTRAINT IF EXISTS ck_partner_credit_window
        """
    )
    # The dashboards read the generated columns — drop them first or the ALTER fails.
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_performance")
    op.execute("DROP VIEW IF EXISTS lens_ps_client_performance")
    op.execute(
        """
        ALTER TABLE ps_monthly_earnings
            DROP COLUMN IF EXISTS variance,
            DROP COLUMN IF EXISTS ps_net_owed,
            DROP COLUMN IF EXISTS ps_gross_owed
        """
    )
    op.execute(
        """
        ALTER TABLE ps_monthly_earnings
            ADD COLUMN ps_gross_owed NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * COALESCE(ps_rate_pct,0) / 100.0, 2)) STORED,
            ADD COLUMN ps_net_owed NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * COALESCE(ps_rate_pct,0) / 100.0, 2)
                    - ROUND(usage_collected * COALESCE(partner_rate_pct,0) / 100.0, 2)) STORED,
            ADD COLUMN variance NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * COALESCE(ps_rate_pct,0) / 100.0, 2)
                    - ROUND(usage_collected * COALESCE(partner_rate_pct,0) / 100.0, 2)
                    - ps_actually_paid) STORED
        """
    )
    for tbl in FK_TABLES:
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS fk_{tbl}_brand")
    op.execute("DROP TABLE IF EXISTS ps_brands CASCADE")
