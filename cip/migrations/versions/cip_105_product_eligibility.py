# foundry: kind=migration domain=client-intelligence-platform
"""cip_105: per-product PS eligibility model (Tim, 2026-07-16).

Ownership eligibility used to be PER-BRAND (ps_excluded_brands has no product_id), which wrongly
blocked a rev-share-era brand on ALL products. Tim's model: nationality (china) is the only gate;
then eligibility is PER PRODUCT. The pre-Project-Silk REV-SHARE exclusion list is Connect-only — so
those brands are NOT PS-eligible on Connect (a partner earns the rev-share there) but ARE eligible on
Boost (open; we can sell it, earn the management fee, and split with a partner who brings it).
FLAT-FEE brands stay OURS on all products (Wayward pays us). Never-listed = ours on all products.

Two objects, additive (the commission ledger is NOT rewired here — that's a reviewed money step):
- ps_product_eligibility (table)  — the backfill/override surface, per brand x product. Sparse; holds
  manual corrections. `ps_rev_share_eligible` yes/no + basis + source.
- lens_ps_product_eligibility (view) — per CHINA brand x product, the effective eligibility: the
  override if present, else the default rule above; plus the partner split (partner + rate from
  ps_partner_credit). The intuitive interface for reporting / Metabase / DB viewing:
  filter china -> china + ps_rev_share_eligible -> + ps_partner_rev_share_eligible (partner, rate).

Revision ID: cip_105_product_eligibility
Revises: cip_104_commission_engine
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_105_product_eligibility"
down_revision: str | Sequence[str] | None = "cip_104_commission_engine"
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
)
SELECT
    b.wayward_brand_id,
    b.brand_name,
    p.product_id,
    -- PS eligible for the management rev-share on THIS product? override wins, else the rule.
    COALESCE(ov.ps_rev_share_eligible,
             CASE WHEN e.any_rev_share AND p.product_id = 'connect' THEN false ELSE true END)
        AS ps_rev_share_eligible,
    CASE WHEN ov.ps_rev_share_eligible IS NOT NULL THEN 'manual_override'
         WHEN e.wayward_brand_id IS NULL              THEN 'never_listed'
         WHEN e.any_rev_share AND p.product_id = 'connect' THEN 'rev_share_excl_connect'
         WHEN e.any_rev_share AND p.product_id <> 'connect' THEN 'rev_share_boost_open'
         WHEN e.any_flat_fee                          THEN 'flat_fee_era_eric'
         ELSE 'eligible' END AS basis,
    -- partner split (from ps_partner_credit, already per brand x product)
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


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ps_product_eligibility (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL,
            wayward_brand_id uuid NOT NULL,
            product_id text NOT NULL,
            ps_rev_share_eligible boolean NOT NULL,
            basis text,
            source_ref text,
            notes text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "ALTER TABLE ps_product_eligibility ADD CONSTRAINT ps_product_eligibility_uq "
        "UNIQUE (tenant_id, wayward_brand_id, product_id)"
    )
    op.execute(
        "ALTER TABLE ps_product_eligibility ADD CONSTRAINT ps_product_eligibility_brand_fk "
        "FOREIGN KEY (wayward_brand_id) REFERENCES ps_brands (wayward_brand_id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE ps_product_eligibility ADD CONSTRAINT ps_product_eligibility_product_fk "
        "FOREIGN KEY (tenant_id, product_id) REFERENCES ps_products (tenant_id, product_id) "
        "ON DELETE RESTRICT"
    )
    op.execute("ALTER TABLE ps_product_eligibility ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_product_eligibility FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON ps_product_eligibility "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )
    op.execute(
        "COMMENT ON TABLE ps_product_eligibility IS "
        "$c$Manual per-brand x product override of PS rev-share eligibility (the backfill surface). "
        "SPARSE — only rows that override the default rule in lens_ps_product_eligibility. Use it to "
        "record, e.g., a rev-share brand whose Boost we've decided is ours, or a Connect we've won "
        "back. ps_rev_share_eligible = may PS earn the management rev-share on this product. The "
        "PARTNER split (who we pass a % to) lives in ps_partner_credit, not here.$c$"
    )
    op.execute("COMMENT ON COLUMN ps_product_eligibility.ps_rev_share_eligible IS "
               "$c$TRUE = PS may earn the management rev-share on this brand x product. Overrides the "
               "default rule (china + not rev-share-excluded-on-this-product).$c$")
    op.execute("COMMENT ON COLUMN ps_product_eligibility.basis IS "
               "$c$Why this override exists (free text, e.g. 'won back', 'boost sold via Snowball').$c$")
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_product_eligibility TO {r}")
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cip_rls_test_role') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON ps_product_eligibility TO cip_rls_test_role;
            END IF;
        END $$;
        """
    )

    op.execute(_LENS)
    op.execute(
        "COMMENT ON VIEW lens_ps_product_eligibility IS "
        "$c$Effective per-product PS eligibility for CHINA brands (Tim's model, cip_105). One row per "
        "china brand x product. ps_rev_share_eligible = override (ps_product_eligibility) if present, "
        "else the rule: rev-share-excluded brands are NOT eligible on Connect (a partner earns the "
        "rev-share) but ARE eligible on Boost (open); flat-fee-era + never-listed are eligible on all "
        "products. ps_partner_rev_share_eligible + partner_name + partner_rate come from "
        "ps_partner_credit. Filter path: china -> + ps_rev_share_eligible -> + partner split. NOTE: "
        "this is the reporting/eligibility interface; the money claim (lens_ps_claim) still gates on "
        "brand-level ownership until the ledger is rewired to consume this (a reviewed step).$c$"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_product_eligibility TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_product_eligibility")
    op.execute("DROP TABLE IF EXISTS ps_product_eligibility")
