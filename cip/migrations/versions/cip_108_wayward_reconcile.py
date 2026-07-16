# foundry: kind=migration domain=client-intelligence-platform
"""cip_108: Wayward reconciliation lens — our claim vs their acknowledgment vs paid (Tim, 2026-07-16).

The third axis Tim wanted: does WAYWARD acknowledge owing us? Per brand, line up (1) our claim
(lens_ps_claim), (2) Wayward's own record (cip_deals attribution_source / attribution_active /
lifetime_commissions_generated), (3) what Wayward paid. Surfaces the strongest ask: brands Wayward's
OWN CRM credits to "China Referral - Tim", marks active, generates commission on — and has paid $0.

Subagent-validated build (two would-be bugs avoided):
- cip_deals.source_id is NOT unique (version mirror) -> DISTINCT ON (source_id) ORDER BY refreshed_at.
- cip_deals.company_id is 100% NULL -> bridge on properties->>'hs_primary_associated_company'.
- Bridge = hubspot_deal_id UNION company; no brand carries conflicting attribution (aggregation trivial).
- The ASK is Wayward's lifetime_commissions_generated, NOT our floored ps_claim_owed (which reads ~$0
  for these newer brands). Both are surfaced; delta_status flags the state.

Additive, read-only. Reuses lens_ps_claim for owed/paid (single source of money truth).

Revision ID: cip_108_wayward_reconcile
Revises: cip_107_per_product_ledger
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_108_wayward_reconcile"
down_revision: str | Sequence[str] | None = "cip_107_per_product_ledger"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_LENS = """
CREATE VIEW lens_ps_wayward_reconciliation AS
WITH deal AS (
    SELECT DISTINCT ON (source_id) source_id,
           NULLIF(properties ->> 'attribution_source', '')                       AS attr_source,
           NULLIF(properties ->> 'attribution_active', '')                       AS attr_active,
           NULLIF(properties ->> 'average_attribution_commission_rate', '')::numeric AS avg_rate,
           NULLIF(properties ->> 'lifetime_commissions_generated', '')::numeric   AS lifetime_comm,
           NULLIF(properties ->> 'lifetime_gmv', '')::numeric                      AS lifetime_gmv,
           properties ->> 'hs_primary_associated_company'                         AS company_hid
    FROM cip_deals
    ORDER BY source_id, refreshed_at DESC NULLS LAST
),
brand_deal AS (
    SELECT o.wayward_brand_id, d.attr_source, d.attr_active, d.avg_rate, d.lifetime_comm, d.lifetime_gmv
    FROM ps_brand_observations o JOIN deal d ON d.source_id = o.value
    WHERE o.field = 'hubspot_deal_id' AND o.value <> ''
    UNION ALL
    SELECT o.wayward_brand_id, d.attr_source, d.attr_active, d.avg_rate, d.lifetime_comm, d.lifetime_gmv
    FROM ps_brand_observations o JOIN deal d ON d.company_hid = o.value
    WHERE o.field = 'hubspot_company_id' AND o.value <> ''
),
wattr AS (
    SELECT wayward_brand_id,
           bool_or(attr_source ILIKE '%Tim%')      AS wayward_credits_ps,
           max(attr_source)                        AS wayward_attribution_source,
           bool_or(attr_active = 'true')           AS wayward_attribution_active,
           max(avg_rate)                           AS wayward_ack_rate,
           max(lifetime_comm)                      AS wayward_ack_commission,
           max(lifetime_gmv)                       AS wayward_ack_gmv
    FROM brand_deal
    GROUP BY 1
)
SELECT
    cl.wayward_brand_id,
    cl.brand_name,
    cl.verdict,
    cl.mgmt_fee_owed  AS ps_mgmt_fee_owed,
    cl.ps_claim_owed,
    cl.wayward_paid,
    COALESCE(w.wayward_credits_ps, false)      AS wayward_credits_ps,
    w.wayward_attribution_source,
    COALESCE(w.wayward_attribution_active, false) AS wayward_attribution_active,
    w.wayward_ack_commission,
    w.wayward_ack_rate,
    w.wayward_ack_gmv,
    CASE
        WHEN cl.wayward_paid > 0 AND cl.ps_claim_owed = 0 THEN 'paid_settled'
        WHEN cl.wayward_paid > 0                          THEN 'paid_partial'
        WHEN w.wayward_credits_ps AND w.wayward_attribution_active THEN 'acknowledged_unpaid'
        WHEN w.wayward_attribution_source IS NOT NULL AND NOT w.wayward_credits_ps
            THEN 'credited_other_unpaid'
        WHEN cl.ps_claim_owed > 0                         THEN 'unacknowledged_unpaid'
        ELSE 'no_claim' END AS delta_status
FROM lens_ps_claim cl
LEFT JOIN wattr w ON w.wayward_brand_id = cl.wayward_brand_id
WHERE cl.verdict = 'china'
"""


def upgrade() -> None:
    op.execute(_LENS)
    op.execute(
        "COMMENT ON VIEW lens_ps_wayward_reconciliation IS "
        "$c$Our claim vs Wayward's acknowledgment vs paid, per china brand (Tim, cip_108). "
        "ps_mgmt_fee_owed / ps_claim_owed / wayward_paid come from lens_ps_claim (our engine). "
        "wayward_* come from cip_deals (deduped current version, bridged deal-id UNION company): "
        "credits_ps = attribution_source ILIKE '%%Tim%%'; wayward_ack_commission = Wayward's OWN "
        "lifetime_commissions_generated (the ASK measure, NOT our floored ps_claim_owed). "
        "delta_status: paid_settled/paid_partial; acknowledged_unpaid (Wayward credits Tim + active + "
        "$0 paid — the strongest ask); credited_other_unpaid (we claim, Wayward credits Eric/Adina); "
        "unacknowledged_unpaid (we claim, no Wayward attribution); no_claim. Reconciliation/negotiation "
        "view — NOT a claim input.$c$"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_wayward_reconciliation TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_wayward_reconciliation")
