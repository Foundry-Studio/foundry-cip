# foundry: kind=migration domain=client-intelligence-platform
"""cip_54: the IDENTITY SPINE. wayward_brand_id everywhere money flows.

THE PRINCIPLE (Tim, 2026-07-13)
------------------------------
    "Make sure the FIELDS are correct, then make sure they are FILLED. If your fields are
     correct and the relationships are correct, the math will sort itself."

He is right, and the money bugs we just found were not math bugs — they were IDENTITY bugs:

  - the rate clock was keyed on client_id, so $1.25M of collected usage on brands that are
    not in cip_clients could not hold a productive date, could not get a rate, and priced
    to $0. The arithmetic was fine. The brand simply had no name the schema could use.

  - ps_partner_credit and ps_attribution have NO wayward_brand_id column at all. They are
    keyed purely on cip_clients.id — a CIP-internal SURROGATE that covers only 64% of our
    clients and nothing outside them.

WHY THE SURROGATE IS THE WRONG KEY
----------------------------------
cip_clients.id exists only for brands that arrived through the PS lens mirror. But every
other system speaks wayward_brand_id:

    Stripe            -> customer metadata.brandId
    Slack brand feed  -> "Brand ID"
    Jake's reports    -> BRAND_ID
    the frozen list   -> Brand ID
    Eric's sheets     -> Brand ID

wayward_brand_id is the ONE identifier every source agrees on. It is the natural key. Keying
money on cip_clients.id means silently dropping every brand the surrogate does not happen to
cover — which is exactly what happened.

So: add wayward_brand_id to the two tables that lack it, backfill it from cip_clients, and
index it. client_id stays as a convenience join, never as the identity.

This migration only fixes the FIELDS. Filling them (the remaining coverage gaps in
cip_clients and the Stripe customers with no brandId metadata) is a data job, not a schema
job — see scripts/repair_identity_spine.py.

Revision ID: cip_54_identity_spine
Revises: cip_53_clock_by_brand
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_54_identity_spine"
down_revision: str | Sequence[str] | None = "cip_53_clock_by_brand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for tbl in ("ps_partner_credit", "ps_attribution"):
        op.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS wayward_brand_id UUID")
        op.execute(
            f"""
            UPDATE {tbl} t
               SET wayward_brand_id = c.wayward_brand_id
              FROM cip_clients c
             WHERE c.id = t.client_id
               AND t.wayward_brand_id IS NULL
               AND c.wayward_brand_id IS NOT NULL
            """
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{tbl}_brand ON {tbl} "
            f"(tenant_id, wayward_brand_id, product_id)"
        )
        op.execute(
            f"COMMENT ON COLUMN {tbl}.wayward_brand_id IS "
            f"'THE identity. Every source speaks this id — Stripe (customer "
            f"metadata.brandId), the Slack brand feed, Jake''s reports, the frozen exclusion "
            f"list, Eric''s sheets. cip_clients.id is a CIP-internal SURROGATE covering only "
            f"the brands that came through the PS lens mirror, so keying money on it silently "
            f"drops everything else — that is how $1.25M of collected usage ended up priced "
            f"at $0. client_id is a convenience join; wayward_brand_id is the identity.'"
        )

    # A brand-level view of who is credited, keyed on the real identity.
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_identity_health AS
        SELECT 'cip_clients' AS relation,
               count(*) AS rows,
               count(wayward_brand_id) AS with_brand_id,
               round(100.0 * count(wayward_brand_id) / NULLIF(count(*),0), 1) AS pct
        FROM cip_clients
        UNION ALL SELECT 'ps_stripe_invoices', count(*), count(wayward_brand_id),
               round(100.0*count(wayward_brand_id)/NULLIF(count(*),0),1) FROM ps_stripe_invoices
        UNION ALL SELECT 'ps_stripe_invoice_lines', count(*), count(wayward_brand_id),
               round(100.0*count(wayward_brand_id)/NULLIF(count(*),0),1) FROM ps_stripe_invoice_lines
        UNION ALL SELECT 'ps_payment_events', count(*), count(wayward_brand_id),
               round(100.0*count(wayward_brand_id)/NULLIF(count(*),0),1) FROM ps_payment_events
        UNION ALL SELECT 'ps_product_subscriptions', count(*), count(wayward_brand_id),
               round(100.0*count(wayward_brand_id)/NULLIF(count(*),0),1) FROM ps_product_subscriptions
        UNION ALL SELECT 'ps_partner_credit', count(*), count(wayward_brand_id),
               round(100.0*count(wayward_brand_id)/NULLIF(count(*),0),1) FROM ps_partner_credit
        UNION ALL SELECT 'ps_attribution', count(*), count(wayward_brand_id),
               round(100.0*count(wayward_brand_id)/NULLIF(count(*),0),1) FROM ps_attribution
        UNION ALL SELECT 'ps_excluded_brands', count(*), count(wayward_brand_id),
               round(100.0*count(wayward_brand_id)/NULLIF(count(*),0),1) FROM ps_excluded_brands
        ORDER BY 4 NULLS LAST
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_identity_health IS "
        "'Is the identity spine intact? Every relation where money flows must carry "
        "wayward_brand_id. Anything below 100%% is revenue that CANNOT be joined, and "
        "therefore cannot be priced, claimed, or attributed to a partner. Check this BEFORE "
        "trusting any money number — a gap here shows up downstream as a $0, not as an error.'"
    )
    for r in ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk"):
        op.execute(f"GRANT SELECT ON lens_ps_identity_health TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_identity_health")
    for tbl in ("ps_partner_credit", "ps_attribution"):
        op.execute(f"DROP INDEX IF EXISTS idx_{tbl}_brand")
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS wayward_brand_id")
