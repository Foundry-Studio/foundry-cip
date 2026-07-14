# foundry: kind=migration domain=client-intelligence-platform
"""cip_53: key the rate clock on wayward_brand_id. Fixes $1.25M of unpriced revenue.

THE BUG (found in QC of cip_50/51, quantified before fixing)
------------------------------------------------------------
ps_product_subscriptions is keyed on (client_id, product_id) and has NO wayward_brand_id
column. But cip_clients only holds brands that came through the PS lens mirror — Stripe
invoices EVERY brand Wayward has. So:

    brand not in cip_clients  ->  client_id NULL
                              ->  cannot hold a productive_date at all
                              ->  no clock
                              ->  ps_rate_pct NULL
                              ->  ps_gross_owed = $0

98% of the NULL rates in ps_monthly_earnings were exactly this. The money sitting on those
rows: $1,250,769.50 of COLLECTED usage fees, earning us nothing — not because we are not
owed it, but because the schema could not name the brand.

wayward_brand_id is the real identity here. It is what Stripe carries (customer
metadata.brandId), what the Slack feed carries, what the frozen exclusion list carries, and
what Jake's reports carry. cip_clients.id is a CIP-internal surrogate that only exists for a
subset. Keying money on the surrogate silently drops every brand the surrogate does not cover.

So: add wayward_brand_id, and make (tenant, wayward_brand_id, product_id) the natural key for
the clock. client_id stays as a convenience join, not as the identity.

Revision ID: cip_53_clock_by_brand
Revises: cip_52_elig_on_billing
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_53_clock_by_brand"
down_revision: str | Sequence[str] | None = "cip_52_elig_on_billing"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ps_product_subscriptions "
        "ADD COLUMN IF NOT EXISTS wayward_brand_id UUID"
    )
    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.wayward_brand_id IS "
        "'THE identity for this table. cip_clients.id is a CIP-internal surrogate that only "
        "covers brands which came through the PS lens mirror — but Stripe invoices EVERY "
        "brand Wayward has. Keying the rate clock on client_id silently dropped every brand "
        "the surrogate did not cover: $1.25M of collected usage fees sat unpriced because the "
        "schema could not name the brand. wayward_brand_id is what Stripe, the Slack feed, "
        "the frozen exclusion list and Jake''s reports all carry. Key money on it.'"
    )
    # backfill from the existing client_id links
    op.execute(
        """
        UPDATE ps_product_subscriptions s
           SET wayward_brand_id = c.wayward_brand_id
          FROM cip_clients c
         WHERE c.id = s.client_id
           AND s.wayward_brand_id IS NULL
           AND c.wayward_brand_id IS NOT NULL
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ps_subs_brand_product "
        "ON ps_product_subscriptions (tenant_id, wayward_brand_id, product_id) "
        "WHERE wayward_brand_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ps_subs_brand "
        "ON ps_product_subscriptions (tenant_id, wayward_brand_id)"
    )

    # The rate-clock lens must expose the brand id too, or it inherits the same blindness.
    op.execute("DROP VIEW IF EXISTS lens_ps_rate_clock")
    op.execute(
        """
        CREATE VIEW lens_ps_rate_clock AS
        SELECT
            s.tenant_id,
            s.wayward_brand_id,
            s.client_id,
            s.product_id,
            s.productive_date,
            s.productive_date_source,
            s.productive_date_confidence,
            s.rate_10_expires,
            s.rate_6_expires,
            s.partner_credit_expires,
            CASE
                WHEN s.productive_date IS NULL          THEN NULL
                WHEN CURRENT_DATE <= s.rate_10_expires  THEN 10
                WHEN CURRENT_DATE <= s.rate_6_expires   THEN 6
                ELSE 3
            END                                                  AS current_rate_pct,
            (s.productive_date IS NOT NULL
             AND CURRENT_DATE <= s.partner_credit_expires)       AS partner_still_earning,
            CASE WHEN s.productive_date IS NULL THEN NULL
                 ELSE (s.rate_10_expires - CURRENT_DATE) END     AS days_until_10_drops
        FROM ps_product_subscriptions s
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_rate_clock IS "
        "'What rate we are on TODAY, per brand x PRODUCT (10/6/3), and when it drops. "
        "current_rate_pct is computed at READ time because it depends on today''s date — a "
        "stored tier would be wrong the morning after it changed. Connect and Boost have "
        "SEPARATE clocks: a brand can be at 6%% on Connect and 10%% on Boost.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_rate_clock TO {r}")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_ps_subs_brand_product")
    op.execute("DROP INDEX IF EXISTS idx_ps_subs_brand")
    op.execute("DROP VIEW IF EXISTS lens_ps_rate_clock")
    op.execute(
        "ALTER TABLE ps_product_subscriptions DROP COLUMN IF EXISTS wayward_brand_id"
    )
