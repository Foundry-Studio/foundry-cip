# foundry: kind=migration domain=client-intelligence-platform
"""cip_109: reporting lenses for Metabase / downloads (Tim, 2026-07-16).

Thin read-surfaces over the money engine (cip_104-108) — no new data, no schema-of-record change.
Five views answering the business questions from the info-list riff:

- lens_ps_ar_aging                    — per owed china brand: still-owed + how long unpaid (aging bucket)
- lens_ps_partner_payout_summary      — per partner WE pay: owed / paid / still-owed / brands
- lens_ps_monthly_summary             — owed / partner-owed / NET by month x product (the trend line)
- lens_ps_excluded_partner_performance— SEPARATE view of the pre-PS rev-share exclusion book (Eric et
                                        al.): brands + collected revenue per bucket x product. Kept OUT
                                        of our owed (Tim: don't make me subtract in the UX).
- lens_ps_wayward_stated              — Wayward's OWN stated numbers (total_fees_paid / lifetime
                                        commissions / GMV) vs our recorded paid — the cross-check.

Additive, read-only. Grants match the lens_ps_* set.

Revision ID: cip_109_reporting_lenses
Revises: cip_108_wayward_reconcile
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_109_reporting_lenses"
down_revision: str | Sequence[str] | None = "cip_108_wayward_reconcile"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_VIEWS = {
    "lens_ps_ar_aging": """
CREATE VIEW lens_ps_ar_aging AS
WITH earliest AS (
    SELECT wayward_brand_id,
           min(period_month) FILTER (WHERE claimable AND mgmt_fee_owed > 0) AS oldest_owed_month
    FROM lens_ps_commission_ledger
    GROUP BY 1
)
SELECT
    cl.wayward_brand_id, cl.brand_name, cl.ps_claim_owed, cl.wayward_paid,
    e.oldest_owed_month,
    (EXTRACT(YEAR  FROM age(current_date, e.oldest_owed_month)) * 12
   + EXTRACT(MONTH FROM age(current_date, e.oldest_owed_month)))::int AS months_outstanding,
    CASE WHEN e.oldest_owed_month IS NULL                                  THEN 'no accrued fee'
         WHEN age(current_date, e.oldest_owed_month) < INTERVAL '1 month'  THEN '0-1 month'
         WHEN age(current_date, e.oldest_owed_month) < INTERVAL '3 months' THEN '1-3 months'
         WHEN age(current_date, e.oldest_owed_month) < INTERVAL '6 months' THEN '3-6 months'
         ELSE '6+ months' END AS aging_bucket
FROM lens_ps_claim cl
JOIN earliest e ON e.wayward_brand_id = cl.wayward_brand_id
WHERE cl.verdict = 'china' AND cl.ps_claim_owed > 0
""",
    "lens_ps_partner_payout_summary": """
CREATE VIEW lens_ps_partner_payout_summary AS
WITH owed AS (
    SELECT partner_of_record AS partner,
           round(sum(partner_fee_owed), 2)       AS partner_owed,
           count(DISTINCT wayward_brand_id)       AS brands
    FROM lens_ps_commission_ledger
    WHERE partner_fee_owed > 0
    GROUP BY 1
),
paid AS (
    SELECT partner_id AS partner, round(sum(amount_paid), 2) AS partner_paid
    FROM ps_partner_payouts
    GROUP BY 1
)
SELECT
    COALESCE(o.partner, p.partner)                 AS partner,
    COALESCE(o.partner_owed, 0)                    AS partner_owed,
    COALESCE(p.partner_paid, 0)                    AS partner_paid,
    GREATEST(COALESCE(o.partner_owed, 0) - COALESCE(p.partner_paid, 0), 0) AS partner_still_owed,
    COALESCE(o.brands, 0)                          AS brands
FROM owed o
FULL JOIN paid p ON o.partner = p.partner
""",
    "lens_ps_monthly_summary": """
CREATE VIEW lens_ps_monthly_summary AS
SELECT
    period_month,
    product_id,
    round(sum(usage_collected) FILTER (WHERE claimable), 2) AS collected_claimable,
    round(sum(mgmt_fee_owed), 2)    AS mgmt_fee_owed,
    round(sum(partner_fee_owed), 2) AS partner_fee_owed,
    round(sum(mgmt_fee_owed) - sum(partner_fee_owed), 2) AS net_owed,
    count(DISTINCT wayward_brand_id) FILTER (WHERE claimable) AS claimable_brands
FROM lens_ps_commission_ledger
GROUP BY 1, 2
""",
    "lens_ps_excluded_partner_performance": """
CREATE VIEW lens_ps_excluded_partner_performance AS
WITH excl AS (
    -- one bucket per brand: a brand listed in two buckets (data quirk, e.g. Roborock) must NOT have
    -- its revenue counted twice. Pick a deterministic single bucket.
    SELECT DISTINCT ON (wayward_brand_id) wayward_brand_id, bucket,
           COALESCE(NULLIF(referrer, ''), '(unattributed)') AS referrer
    FROM ps_excluded_brands
    WHERE disposition = 'excluded' AND wayward_brand_id IS NOT NULL
    ORDER BY wayward_brand_id, bucket
),
rev AS (
    SELECT wayward_brand_id, product_id, sum(usage_collected) AS collected
    FROM lens_ps_commission_ledger
    GROUP BY 1, 2
)
SELECT
    e.bucket,
    e.referrer,
    r.product_id,
    count(DISTINCT e.wayward_brand_id)          AS brands,
    round(sum(r.collected), 2)                  AS collected_revenue
FROM excl e
LEFT JOIN rev r ON r.wayward_brand_id = e.wayward_brand_id
GROUP BY 1, 2, 3
""",
    "lens_ps_wayward_stated": """
CREATE VIEW lens_ps_wayward_stated AS
WITH deal AS (
    SELECT DISTINCT ON (source_id) source_id,
           NULLIF(properties ->> 'total_fees_paid', '')::numeric               AS total_fees_paid,
           NULLIF(properties ->> 'lifetime_commissions_generated', '')::numeric AS lifetime_commissions,
           NULLIF(properties ->> 'lifetime_gmv', '')::numeric                   AS lifetime_gmv,
           properties ->> 'hs_primary_associated_company'                       AS company_hid
    FROM cip_deals
    ORDER BY source_id, refreshed_at DESC NULLS LAST
),
brand AS (
    SELECT o.wayward_brand_id,
           max(d.total_fees_paid)     AS wayward_stated_fees_paid,
           max(d.lifetime_commissions) AS wayward_lifetime_commission,
           max(d.lifetime_gmv)        AS wayward_lifetime_gmv
    FROM ps_brand_observations o
    JOIN deal d ON d.source_id = o.value
    WHERE o.field = 'hubspot_deal_id' AND o.value <> ''
    GROUP BY 1
)
SELECT
    b.wayward_brand_id, br2.brand_name,
    b.wayward_stated_fees_paid,
    b.wayward_lifetime_commission,
    b.wayward_lifetime_gmv,
    round(COALESCE(cl.wayward_paid, 0), 2) AS our_recorded_paid
FROM brand b
JOIN ps_brands br2 ON br2.wayward_brand_id = b.wayward_brand_id
LEFT JOIN lens_ps_claim cl ON cl.wayward_brand_id = b.wayward_brand_id
""",
}

_COMMENTS = {
    "lens_ps_ar_aging": "AR aging of our claim: per china brand still owed, how long the oldest owed "
                        "month has gone unpaid (months_outstanding + aging_bucket). Answers 'who's "
                        "overdue and by how long'.",
    "lens_ps_partner_payout_summary": "Per partner WE pay (post-cutover referral splits): partner_owed "
                                      "(from the ledger) vs partner_paid (ps_partner_payouts) -> "
                                      "still-owed. NOT the exclusion-list partners Wayward pays direct "
                                      "(see lens_ps_excluded_partner_performance).",
    "lens_ps_monthly_summary": "The trend line: per month x product, collected, mgmt_fee_owed, "
                               "partner_fee_owed, and NET (mgmt - partner) — what we keep.",
    "lens_ps_excluded_partner_performance": "SEPARATE view of the pre-PS rev-share EXCLUSION book "
                                            "(Eric et al., paid directly by Wayward): brands + "
                                            "collected revenue per bucket x referrer x product. Kept "
                                            "OUT of our owed on purpose — this is their book, not "
                                            "ours; look here to see what Eric's driving, don't "
                                            "subtract it from the claim.",
    "lens_ps_wayward_stated": "Wayward's OWN stated per-brand numbers from cip_deals (total_fees_paid, "
                              "lifetime_commissions_generated, lifetime_gmv, via the deduped deal "
                              "bridge) alongside our recorded paid — the reconciliation cross-check. "
                              "Their numbers, for comparison; never a claim input.",
}


def upgrade() -> None:
    for name, sql in _VIEWS.items():
        op.execute(sql)
        op.execute(f"COMMENT ON VIEW {name} IS $c${_COMMENTS[name]}$c$")
        for r in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {name} TO {r}")


def downgrade() -> None:
    for name in reversed(list(_VIEWS)):
        op.execute(f"DROP VIEW IF EXISTS {name}")
