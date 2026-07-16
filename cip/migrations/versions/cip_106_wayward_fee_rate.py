# foundry: kind=migration domain=client-intelligence-platform
"""cip_106: surface Wayward's CLIENT fee rate per brand x product (Tim, 2026-07-16).

The rate Wayward charges the CLIENT (5% of GMV usage fee on Connect, ad-spend rate on Boost) already
arrives in the feed — `cip_deals.properties.usage_fee` (Connect) and `wayward_boosted_usage_fee_rate`
(Boost), negotiated per brand (0.01–0.06). It was buried in JSONB; this surfaces it per brand x
product in lens_ps_product_eligibility, feed-first with a CRM override.

- ps_product_eligibility gains `wayward_fee_rate_override` (numeric, nullable) — hand-set in the CRM.
- lens_ps_product_eligibility gains `wayward_client_fee_rate` + `wayward_fee_rate_basis`:
  COALESCE(override, the feed rate via the deduped deal->brand bridge, the standard default
  0.05 Connect / 0.10 Boost). NOTE: the feed dominates (2,963/3,695 deals carry it); the default only
  fills brands with no deal.

Additive: reads cip_deals (RLS-scoped, no triggers). The lens is dropped + recreated (nothing depends
on it — it's from cip_105).

Revision ID: cip_106_wayward_fee_rate
Revises: cip_105_product_eligibility
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_106_wayward_fee_rate"
down_revision: str | Sequence[str] | None = "cip_105_product_eligibility"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_LENS = """
CREATE VIEW lens_ps_product_eligibility AS
WITH prods AS (
    SELECT DISTINCT product_id FROM ps_products
),
china AS (
    SELECT wayward_brand_id FROM lens_ps_china_verdict WHERE verdict = 'china'
),
excl AS (
    SELECT wayward_brand_id,
           bool_or(disposition = 'flat_fee_era_eric') AS any_flat_fee,
           bool_or(disposition = 'excluded')          AS any_rev_share
    FROM ps_excluded_brands
    WHERE wayward_brand_id IS NOT NULL
    GROUP BY 1
),
-- Wayward's client fee rate from the feed: dedup cip_deals to current version, bridge to brand.
deal AS (
    SELECT DISTINCT ON (source_id) source_id,
           NULLIF(properties ->> 'usage_fee', '')::numeric                    AS connect_rate,
           NULLIF(properties ->> 'wayward_boosted_usage_fee_rate', '')::numeric AS boost_rate
    FROM cip_deals
    ORDER BY source_id, refreshed_at DESC NULLS LAST
),
feed_rate AS (
    SELECT o.wayward_brand_id,
           max(d.connect_rate) AS connect_rate,
           max(d.boost_rate)   AS boost_rate
    FROM ps_brand_observations o
    JOIN deal d ON d.source_id = o.value
    WHERE o.field = 'hubspot_deal_id' AND o.value <> ''
    GROUP BY 1
)
SELECT
    b.wayward_brand_id,
    b.brand_name,
    p.product_id,
    COALESCE(ov.ps_rev_share_eligible,
             CASE WHEN e.any_rev_share AND p.product_id = 'connect' THEN false ELSE true END)
        AS ps_rev_share_eligible,
    CASE WHEN ov.ps_rev_share_eligible IS NOT NULL THEN 'manual_override'
         WHEN e.wayward_brand_id IS NULL              THEN 'never_listed'
         WHEN e.any_rev_share AND p.product_id = 'connect' THEN 'rev_share_excl_connect'
         WHEN e.any_rev_share AND p.product_id <> 'connect' THEN 'rev_share_boost_open'
         WHEN e.any_flat_fee                          THEN 'flat_fee_era_eric'
         ELSE 'eligible' END AS basis,
    -- Wayward's client fee rate on this product: override -> feed -> standard default.
    COALESCE(ov.wayward_fee_rate_override,
             CASE WHEN p.product_id = 'connect' THEN fr.connect_rate
                  WHEN p.product_id = 'boosted' THEN fr.boost_rate END,
             CASE WHEN p.product_id = 'connect' THEN 0.05
                  WHEN p.product_id = 'boosted' THEN 0.10 END)
        AS wayward_client_fee_rate,
    CASE WHEN ov.wayward_fee_rate_override IS NOT NULL THEN 'override'
         WHEN (p.product_id = 'connect' AND fr.connect_rate IS NOT NULL)
           OR (p.product_id = 'boosted' AND fr.boost_rate IS NOT NULL) THEN 'feed'
         ELSE 'standard_default' END AS wayward_fee_rate_basis,
    (pc.partner_of_record IS NOT NULL AND pc.partner_of_record <> 'unassigned')
        AS ps_partner_rev_share_eligible,
    NULLIF(pc.partner_of_record, 'unassigned') AS partner_name,
    pc.partner_rate AS partner_rate_pct
FROM china cb
JOIN ps_brands b ON b.wayward_brand_id = cb.wayward_brand_id
CROSS JOIN prods p
LEFT JOIN excl e ON e.wayward_brand_id = b.wayward_brand_id
LEFT JOIN feed_rate fr ON fr.wayward_brand_id = b.wayward_brand_id
LEFT JOIN ps_partner_credit pc
       ON pc.wayward_brand_id = b.wayward_brand_id AND pc.product_id = p.product_id
LEFT JOIN ps_product_eligibility ov
       ON ov.wayward_brand_id = b.wayward_brand_id AND ov.product_id = p.product_id
"""


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_product_eligibility")
    op.execute("ALTER TABLE ps_product_eligibility ADD COLUMN wayward_fee_rate_override numeric")
    op.execute(
        "COMMENT ON COLUMN ps_product_eligibility.wayward_fee_rate_override IS "
        "$c$Hand-set (CRM) override of the client fee rate Wayward charges on this brand x product, "
        "as a fraction (0.05 = 5%). NULL = use the feed value, else the standard default.$c$"
    )
    op.execute(_LENS)
    op.execute(
        "COMMENT ON VIEW lens_ps_product_eligibility IS "
        "$c$Effective per-product PS eligibility + Wayward's client fee rate, per CHINA brand x "
        "product (Tim, cip_105/106). ps_rev_share_eligible: override else the rule (rev-share-excluded "
        "brands NOT eligible on Connect, eligible on Boost; flat-fee/never-listed eligible all). "
        "wayward_client_fee_rate: what WAYWARD charges the client on this product = override -> the "
        "feed (cip_deals.usage_fee / wayward_boosted_usage_fee_rate via the deal bridge) -> standard "
        "default 0.05 Connect / 0.10 Boost. partner_name/partner_rate_pct from ps_partner_credit. The "
        "reporting/eligibility interface; the money claim (lens_ps_claim) still gates on brand-level "
        "ownership until the ledger is rewired (a reviewed step).$c$"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_product_eligibility TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_product_eligibility")
    op.execute("ALTER TABLE ps_product_eligibility DROP COLUMN IF EXISTS wayward_fee_rate_override")
    # recreate the cip_105 version of the lens (without the fee-rate columns)
    op.execute(
        """
        CREATE VIEW lens_ps_product_eligibility AS
        WITH prods AS (SELECT DISTINCT product_id FROM ps_products),
        china AS (SELECT wayward_brand_id FROM lens_ps_china_verdict WHERE verdict = 'china'),
        excl AS (
            SELECT wayward_brand_id,
                   bool_or(disposition = 'flat_fee_era_eric') AS any_flat_fee,
                   bool_or(disposition = 'excluded')          AS any_rev_share
            FROM ps_excluded_brands WHERE wayward_brand_id IS NOT NULL GROUP BY 1)
        SELECT b.wayward_brand_id, b.brand_name, p.product_id,
            COALESCE(ov.ps_rev_share_eligible,
                     CASE WHEN e.any_rev_share AND p.product_id = 'connect' THEN false ELSE true END)
                AS ps_rev_share_eligible,
            CASE WHEN ov.ps_rev_share_eligible IS NOT NULL THEN 'manual_override'
                 WHEN e.wayward_brand_id IS NULL              THEN 'never_listed'
                 WHEN e.any_rev_share AND p.product_id = 'connect' THEN 'rev_share_excl_connect'
                 WHEN e.any_rev_share AND p.product_id <> 'connect' THEN 'rev_share_boost_open'
                 WHEN e.any_flat_fee                          THEN 'flat_fee_era_eric'
                 ELSE 'eligible' END AS basis,
            (pc.partner_of_record IS NOT NULL AND pc.partner_of_record <> 'unassigned')
                AS ps_partner_rev_share_eligible,
            NULLIF(pc.partner_of_record, 'unassigned') AS partner_name,
            pc.partner_rate AS partner_rate_pct
        FROM china cb
        JOIN ps_brands b ON b.wayward_brand_id = cb.wayward_brand_id
        CROSS JOIN prods p
        LEFT JOIN excl e ON e.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN ps_partner_credit pc
               ON pc.wayward_brand_id = b.wayward_brand_id AND pc.product_id = p.product_id
        LEFT JOIN ps_product_eligibility ov
               ON ov.wayward_brand_id = b.wayward_brand_id AND ov.product_id = p.product_id
        """
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_product_eligibility TO {r}")
