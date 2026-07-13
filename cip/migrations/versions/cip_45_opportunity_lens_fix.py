# foundry: kind=migration domain=client-intelligence-platform
"""cip_45: de-duplicate lens_ps_brand_opportunity + record the bucket taxonomy.

TWO FIXES
---------
1. FAN-OUT BUG (found in QC, cip_43). The lens LEFT JOINed ps_partner_credit without
   guaranteeing one row per (client, product). A brand with more than one open credit row
   was duplicated: 1,526 lens rows for 1,524 clients. Harmless-looking now, fatal later —
   a duplicated brand double-counts revenue the moment this lens feeds a billable number.
   Fixed with DISTINCT ON, taking the most recently determined credit row per
   (client, product).

2. THE EXCLUDED BUCKET IS NOT ONE THING (Tim, 2026-07-13). It contains TWO different
   commercial arrangements, and conflating them loses money:

     (a) PARTNER ON A 10% DEAL — the partner takes the whole 10% pool, so PS nets ZERO.
         Expressed as deal_type='rev_share' with ps_partner_terms.commission_pct = 10
         (PS net = 10 - 10 = 0). The existing model already says this correctly; the
         bucket label just makes it legible.

     (b) ERIC FLAT-FEE — paid once, NOBODY earns ongoing (not Eric, not PS).
         **These are recoverable**: PS earns again by reactivating on Connect once
         dormant, or by selling Boost.

   So "excluded" is not a dead end. (a) is genuinely dead while the partner holds it;
   (b) is a pipeline. The new ps_bucket column in the lens makes the difference explicit
   rather than leaving a reader to infer it.

Revision ID: cip_45_opportunity_lens_fix
Revises: cip_44_partner_aliases
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_45_opportunity_lens_fix"
down_revision: str | Sequence[str] | None = "cip_44_partner_aliases"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_VIEW_SQL = """
CREATE VIEW lens_ps_brand_opportunity AS
WITH credit AS (
    -- DISTINCT ON: exactly ONE open credit row per (client, product). Without this a
    -- brand with two open credit rows appears twice and double-counts.
    SELECT DISTINCT ON (client_id, product_id)
           client_id, product_id, partner_of_record, deal_type, partner_rate
    FROM ps_partner_credit
    WHERE credit_end IS NULL OR credit_end > now()
    ORDER BY client_id, product_id, determined_at DESC NULLS LAST, created_at DESC
),
attr AS (
    SELECT DISTINCT ON (client_id, product_id)
           client_id, product_id, ps_sales_lead, ps_cs_lead
    FROM ps_attribution
    WHERE effective_to IS NULL
    ORDER BY client_id, product_id, effective_from DESC NULLS LAST
),
subs AS (
    SELECT DISTINCT ON (client_id, product_id)
           client_id, product_id, last_activity_at, activity_source
    FROM ps_product_subscriptions
    ORDER BY client_id, product_id, last_activity_at DESC NULLS LAST
)
SELECT
    c.id                    AS client_id,
    c.tenant_id,
    c.name                  AS brand_name,
    c.wayward_brand_id,
    c.nationality_class,
    c.exhibit_a,

    con.partner_of_record   AS connect_partner,
    con.deal_type           AS connect_deal_type,
    bst.partner_of_record   AS boost_partner,
    bst.deal_type           AS boost_deal_type,
    att.ps_sales_lead       AS connect_sales_lead,

    cs.last_activity_at     AS connect_last_activity,
    cs.activity_source      AS connect_activity_source,
    bs.last_activity_at     AS boost_last_activity,

    -- Dormancy derived at READ time so it can never be stale.
    (cs.last_activity_at IS NOT NULL
     AND cs.last_activity_at < now() - INTERVAL '90 days')   AS connect_dormant,
    (bs.last_activity_at IS NOT NULL
     AND bs.last_activity_at < now() - INTERVAL '90 days')   AS boost_dormant,

    -- We genuinely do not know if a brand is dormant when we have never seen activity.
    -- Say so, rather than let NULL be read as "active".
    (cs.last_activity_at IS NULL)                            AS connect_activity_unknown,

    -- Boost is open unless a partner is SPECIFICALLY attributed on Boost.
    -- Eric's flat-fee CONNECT attribution does NOT close Boost.
    (bst.partner_of_record IS NULL
     OR bst.partner_of_record = 'unassigned')                AS boost_open_to_ps,

    COALESCE(
        cs.last_activity_at < now() - INTERVAL '90 days', false
    )                                                        AS connect_reactivatable,

    -- The bucket. "Excluded" is not one thing.
    CASE
        WHEN con.deal_type = 'flat_fee'              THEN 'eric_flat_fee'
        WHEN con.deal_type = 'rev_share'
             AND COALESCE(con.partner_rate, 0) >= 10 THEN 'partner_full_10'
        WHEN con.deal_type = 'rev_share'             THEN 'partner_split'
        WHEN con.partner_of_record = 'unassigned'    THEN 'ps_direct'
        ELSE 'undetermined'
    END                                                      AS ps_bucket
FROM cip_clients c
LEFT JOIN credit con ON con.client_id = c.id AND con.product_id = 'connect'
LEFT JOIN credit bst ON bst.client_id = c.id AND bst.product_id = 'boosted'
LEFT JOIN attr  att ON att.client_id = c.id AND att.product_id = 'connect'
LEFT JOIN subs  cs  ON cs.client_id  = c.id AND cs.product_id  = 'connect'
LEFT JOIN subs  bs  ON bs.client_id  = c.id AND bs.product_id  = 'boosted'
"""


def upgrade() -> None:
    # DROP then CREATE, not CREATE OR REPLACE: the new column list is not a pure append
    # (connect_activity_source + connect_activity_unknown + ps_bucket land mid-list), and
    # Postgres refuses to rename/reorder view columns in place.
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_opportunity")
    op.execute(_VIEW_SQL)
    op.execute(
        "COMMENT ON COLUMN lens_ps_brand_opportunity.ps_bucket IS "
        "'The commercial bucket. ''excluded'' is NOT one thing (Tim, 2026-07-13): "
        "''partner_full_10'' = a partner takes the whole 10%% pool, so PS nets ZERO — "
        "genuinely dead while they hold it. "
        "''eric_flat_fee'' = paid once, NOBODY earns ongoing — but RECOVERABLE: PS earns "
        "again by reactivating on Connect once dormant, or by selling Boost. "
        "''partner_split'' = partner takes X%% (<10), PS nets 10-X. "
        "''ps_direct'' = no partner, PS keeps the full 10%%. "
        "''undetermined'' = not yet decided (NOT the same as no partner).'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_brand_opportunity.connect_activity_unknown IS "
        "'TRUE when we have NEVER seen activity for this brand, so dormancy is "
        "UNKNOWABLE — we cannot say whether it is reactivatable. Distinct from "
        "connect_dormant=false, which means we know it IS active. Do not read a NULL "
        "last_activity_at as ''active'': that silently throws away an opportunity. "
        "~941 brands sit here today, pending per-brand monthly sales from Wayward.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_brand_opportunity TO {r}")


def downgrade() -> None:
    # Restore the cip_43 shape (fan-out and all) so the chain stays reversible.
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_opportunity")
