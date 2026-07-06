# foundry: kind=migration domain=client-intelligence-platform
"""cip_40: PS China Book v2 — lens_ps_china_commission_v2 (S4).

PS China Book Schema v2, Phase 1 (build spec 12-CC-SCHEMA-HANDOFF.md §S4).
cip_34's lens_ps_china_commission (v1) is left untouched and keeps running.

Projects the PS China book from the Phase-1-populated tables: cip_clients
(classification + exhibit_a + wayward_brand_id + performance_tier), aggregated
ps_payment_events (fees + PS commission = 10% of usage fees, per doc 11),
ps_partner_credit (partner-of-record + 12-month credit-window state), and the
currently-effective ps_attribution row.

Grain note / deviation (reported to Tim): S4 asks for brand × product grain, but
Jake's May report carries NO Connect/Boosted split (D3 pending — a data ask to
Jake). So Phase 1 is **brand grain**; `product_id` is exposed from
ps_product_subscriptions where present but fees are not split per product yet.
When D3 lands, the per-product fee columns feed a product-grain revision without
touching this one.

Tenant-pinned to PS + GUC double-scope (copied from cip_34 so isolation is
identical). Registered in cip_views (D-121). Granted to cip_query_reader +
cip_metabase_project_silk.

Revision ID: cip_40_ps_china_lens_v2
Revises: cip_39_ps_china_book_tables
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_40_ps_china_lens_v2"
down_revision: str | Sequence[str] | None = "cip_39_ps_china_book_tables"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_VIEW = "lens_ps_china_commission_v2"
_SLUG = "ps-china-commission-v2"
_DESC = (
    "PS China book v2 (brand grain, Phase 1): classification + exhibit_a + "
    "partner-credit window + PS commission (10% of usage fees paid) aggregated "
    "from ps_payment_events. Product split deferred to D3."
)
_GRANT_ROLES = ("cip_query_reader", "cip_metabase_project_silk")


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_china_commission_v2 AS
        WITH pay AS (
            SELECT
                pe.tenant_id,
                pe.wayward_brand_id,
                count(*)                          AS payment_count,
                min(pe.payment_date)              AS first_payment,
                max(pe.payment_date)              AS latest_payment,
                sum(pe.usage_fees_paid)           AS usage_fees_paid_total,
                sum(pe.commission_fees_paid)      AS commission_fees_paid_total,
                sum(pe.total_amount_paid)         AS total_amount_paid,
                sum(pe.rev_share_stated)          AS commission_accrued,
                sum(pe.rev_share_computed)        AS commission_computed
            FROM ps_payment_events pe
            WHERE pe.tenant_id = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid
              AND pe.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
            GROUP BY pe.tenant_id, pe.wayward_brand_id
        )
        SELECT
            cl.id                 AS client_id,
            cl.tenant_id,
            cl.wayward_brand_id,
            cl.name               AS brand_name,
            cl.nationality_class,
            cl.exhibit_a,
            cl.exhibit_a_matched_name,
            cl.lifecycle_status,
            cl.performance_tier,
            attr.ps_attribution_owner,
            attr.ps_lead_source,
            attr.ps_conditional,
            pc.partner_of_record,
            pc.referral_detail_raw,
            pc.credit_start,
            pc.credit_end,
            CASE
                WHEN pc.partner_of_record IS NULL THEN 'none'
                WHEN pc.credit_end IS NOT NULL AND now()::date > pc.credit_end THEN 'expired'
                ELSE 'active'
            END                   AS credit_window_state,
            COALESCE(pay.payment_count, 0)          AS payment_count,
            pay.first_payment,
            pay.latest_payment,
            COALESCE(pay.usage_fees_paid_total, 0)       AS usage_fees_paid_total,
            COALESCE(pay.commission_fees_paid_total, 0)  AS commission_fees_paid_total,
            COALESCE(pay.total_amount_paid, 0)           AS total_amount_paid,
            COALESCE(pay.commission_accrued, 0)          AS commission_accrued,
            COALESCE(pay.commission_computed, 0)         AS commission_computed,
            COALESCE(pay.commission_accrued, 0) - COALESCE(pay.commission_computed, 0)
                                                          AS commission_variance
        FROM cip_clients cl
        LEFT JOIN pay
               ON pay.wayward_brand_id = cl.wayward_brand_id
        LEFT JOIN LATERAL (
            SELECT a.ps_attribution_owner, a.ps_lead_source, a.ps_conditional
            FROM ps_attribution a
            WHERE a.tenant_id = cl.tenant_id
              AND a.client_id = cl.id
              AND a.effective_to IS NULL
            ORDER BY a.effective_from DESC
            LIMIT 1
        ) attr ON true
        LEFT JOIN LATERAL (
            SELECT c.partner_of_record, c.referral_detail_raw, c.credit_start, c.credit_end
            FROM ps_partner_credit c
            WHERE c.tenant_id = cl.tenant_id
              AND c.client_id = cl.id
            ORDER BY c.credit_start DESC NULLS LAST
            LIMIT 1
        ) pc ON true
        WHERE cl.tenant_id = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid
          AND cl.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
          AND (cl.nationality_class = 'chinese_confirmed' OR pay.wayward_brand_id IS NOT NULL)
        """
    )

    esc = _DESC.replace("'", "''")
    op.execute(
        f"""
        INSERT INTO cip_views (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            view_name, description, filter_config,
            owner_type, owner_id, is_default, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), '{PS_TENANT}', NULL, 'lens-mirror', '{_SLUG}',
            NOW(), NOW(), gen_random_uuid(), 'validated',
            '{_VIEW}', '{esc}',
            '{{"slug": "{_SLUG}", "sql_view": "{_VIEW}", "filter_kind": "ps_china_commission_v2", "phase": "2.8"}}'::jsonb,
            'system', 'cip', false, NOW(), NOW()
        )
        ON CONFLICT DO NOTHING
        """
    )

    for role in _GRANT_ROLES:
        op.execute(f"GRANT SELECT ON {_VIEW} TO {role}")


def downgrade() -> None:
    for role in _GRANT_ROLES:
        op.execute(f"REVOKE ALL ON {_VIEW} FROM {role}")
    op.execute(
        "DELETE FROM cip_views WHERE source_connector='lens-mirror' "
        f"AND source_id = '{_SLUG}'"
    )
    op.execute(f"DROP VIEW IF EXISTS {_VIEW}")
