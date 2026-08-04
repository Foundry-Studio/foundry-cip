# foundry: kind=migration domain=client-intelligence-platform
"""cip_153_fix_connector_literals: repoint the Wayward china / attribution lenses off the dead 'hubspot-v1' literal.

The HubSpot entity data was re-mirrored under new source_connector values. As of this migration the three base
tables carry ONLY the mirror connectors and zero 'hubspot-v1' rows:

    cip_deals      -> 'lens-mirror-deals-v1'
    cip_companies  -> 'lens-mirror-companies-v1'
    cip_contacts   -> 'lens-mirror-contacts-v1'

Ten reporting lenses still filter source_connector = 'hubspot-v1', so every one of them now returns zero rows.
This migration is a surgical literal fix: CREATE OR REPLACE each lens with the SAME definition (identical
columns, joins, grain, and every other filter) and change ONLY the source_connector WHERE literal, swapped by
the base table it constrains. CREATE OR REPLACE VIEW keeps the existing column list, so it preserves all
existing grants and needs no re-GRANT.

Per-view swap (literal -> new connector, by table context):

    lens_adina_attributed_deals        cip_deals     'hubspot-v1' -> 'lens-mirror-deals-v1'
    lens_eric_attributed_deals         cip_deals     'hubspot-v1' -> 'lens-mirror-deals-v1'
    lens_jeremy_attributed_deals       cip_deals     'hubspot-v1' -> 'lens-mirror-deals-v1'
    lens_openlight_attributed_deals    cip_deals     'hubspot-v1' -> 'lens-mirror-deals-v1'
    lens_tim_attributed_deals          cip_deals     'hubspot-v1' -> 'lens-mirror-deals-v1'
    lens_wayward_attribution_summary   cip_deals     'hubspot-v1' -> 'lens-mirror-deals-v1'
    lens_hyphen_migration_deals        cip_deals     'hubspot-v1' -> 'lens-mirror-deals-v1'
    lens_china_clients                 cip_deals     'hubspot-v1' -> 'lens-mirror-deals-v1'
    lens_china_contacts                cip_contacts  'hubspot-v1' -> 'lens-mirror-contacts-v1'   (main filter)
                                       cip_deals     'hubspot-v1' -> 'lens-mirror-deals-v1'      (subquery)
    lens_china_companies               cip_companies 'hubspot-v1' -> 'lens-mirror-companies-v1'  (main filter)
                                       cip_deals     'hubspot-v1' -> 'lens-mirror-deals-v1'      (subquery)

NOTE on lens_china_contacts: it is a TWO-occurrence view (a cip_contacts main filter plus a cip_deals subquery),
not a single deals swap. Its main filter is repointed to the contacts mirror so the lens returns rows again;
sending that filter to the deals mirror (or leaving it on hubspot-v1) would leave the lens empty, because all
cip_contacts rows now live under 'lens-mirror-contacts-v1'.

EXCLUDED: lens_china_tickets. Its path is cip_tickets (zendesk-v1) joined through cip_identity_links to HubSpot
contacts and companies, plus a cip_deals subquery. The source tables for that path are empty, so it is left
exactly as-is; its 'hubspot-v1' and 'zendesk-v1' literals are intentionally untouched.

Reversible: downgrade() CREATE OR REPLACEs every lens back to its verbatim 'hubspot-v1' definition. Each forward
swap is guarded, the exact literal fragment must occur exactly once in the captured definition or the migration
aborts before touching anything, so nothing else in a view body can drift.

Revision ID: cip_153_fix_connector_literals   (30 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_152_own_partner_rate
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_153_fix_connector_literals"
down_revision: str | Sequence[str] | None = "cip_152_own_partner_rate"
branch_labels = None
depends_on = None

# --------------------------------------------------------------------------------------------------------------
# Connector literals. The old value is the dead one every lens still filters on; the new values are the mirror
# connectors the base tables actually carry now (verified: each base table holds ONLY its mirror connector).
# --------------------------------------------------------------------------------------------------------------
_HUBSPOT = "hubspot-v1"
_MIRROR_DEALS = "lens-mirror-deals-v1"
_MIRROR_COMPANIES = "lens-mirror-companies-v1"
_MIRROR_CONTACTS = "lens-mirror-contacts-v1"

# --------------------------------------------------------------------------------------------------------------
# Verbatim current (hubspot-v1) view bodies, exactly as returned by pg_get_viewdef(<view>, true). downgrade()
# restores these byte-for-byte; upgrade() applies only the guarded connector swaps below. Do not reformat: the
# forward swap asserts each anchor occurs exactly once, so any drift here fails the migration loudly.
# --------------------------------------------------------------------------------------------------------------
_ORIG: dict[str, str] = {
    "lens_adina_attributed_deals": """ SELECT d.id,
    d.tenant_id,
    d.client_id,
    d.source_connector,
    d.source_id,
    d.name AS deal_name,
    d.amount,
    d.currency,
    d.close_date,
    d.stage AS stage_id,
    s.stage_label,
    s.pipeline_id,
    s.pipeline_label,
    s.probability AS stage_probability,
    d.probability AS deal_probability,
    d.properties ->> 'source'::text AS attribution_source,
    d.properties ->> 'segment'::text AS segment,
    d.properties ->> 'rev_share_partner'::text AS rev_share_partner,
    d.properties ->> 'paid_referral'::text AS paid_referral,
    d.company_id,
    d.contact_id,
    d.tags,
    d.properties,
    d.ingested_at,
    d.refreshed_at,
    d.created_at,
    d.updated_at
   FROM cip_deals d
     LEFT JOIN cip_pipeline_stages s ON s.tenant_id = d.tenant_id AND s.source_connector = d.source_connector AND s.stage_id = d.stage
  WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND d.source_connector = 'hubspot-v1'::text AND (d.properties ->> 'source'::text) = 'China Referral - Adina'::text;""",
    "lens_eric_attributed_deals": """ SELECT d.id,
    d.tenant_id,
    d.client_id,
    d.source_connector,
    d.source_id,
    d.name AS deal_name,
    d.amount,
    d.currency,
    d.close_date,
    d.stage AS stage_id,
    s.stage_label,
    s.pipeline_id,
    s.pipeline_label,
    s.probability AS stage_probability,
    d.probability AS deal_probability,
    d.properties ->> 'source'::text AS attribution_source,
    d.properties ->> 'segment'::text AS segment,
    d.properties ->> 'rev_share_partner'::text AS rev_share_partner,
    d.properties ->> 'paid_referral'::text AS paid_referral,
    d.company_id,
    d.contact_id,
    d.tags,
    d.properties,
    d.ingested_at,
    d.refreshed_at,
    d.created_at,
    d.updated_at
   FROM cip_deals d
     LEFT JOIN cip_pipeline_stages s ON s.tenant_id = d.tenant_id AND s.source_connector = d.source_connector AND s.stage_id = d.stage
  WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND d.source_connector = 'hubspot-v1'::text AND (d.properties ->> 'source'::text) = 'China Referral - Eric'::text;""",
    "lens_jeremy_attributed_deals": """ SELECT d.id,
    d.tenant_id,
    d.client_id,
    d.source_connector,
    d.source_id,
    d.name AS deal_name,
    d.amount,
    d.currency,
    d.close_date,
    d.stage AS stage_id,
    s.stage_label,
    s.pipeline_id,
    s.pipeline_label,
    s.probability AS stage_probability,
    d.probability AS deal_probability,
    d.properties ->> 'source'::text AS attribution_source,
    d.properties ->> 'segment'::text AS segment,
    d.properties ->> 'rev_share_partner'::text AS rev_share_partner,
    d.properties ->> 'paid_referral'::text AS paid_referral,
    d.company_id,
    d.contact_id,
    d.tags,
    d.properties,
    d.ingested_at,
    d.refreshed_at,
    d.created_at,
    d.updated_at
   FROM cip_deals d
     LEFT JOIN cip_pipeline_stages s ON s.tenant_id = d.tenant_id AND s.source_connector = d.source_connector AND s.stage_id = d.stage
  WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND d.source_connector = 'hubspot-v1'::text AND (d.properties ->> 'source'::text) = 'China Referral - Jeremy Dai'::text;""",
    "lens_openlight_attributed_deals": """ SELECT d.id,
    d.tenant_id,
    d.client_id,
    d.source_connector,
    d.source_id,
    d.name AS deal_name,
    d.amount,
    d.currency,
    d.close_date,
    d.stage AS stage_id,
    s.stage_label,
    s.pipeline_id,
    s.pipeline_label,
    s.probability AS stage_probability,
    d.probability AS deal_probability,
    d.properties ->> 'source'::text AS attribution_source,
    d.properties ->> 'segment'::text AS segment,
    d.properties ->> 'rev_share_partner'::text AS rev_share_partner,
    d.properties ->> 'paid_referral'::text AS paid_referral,
    d.company_id,
    d.contact_id,
    d.tags,
    d.properties,
    d.ingested_at,
    d.refreshed_at,
    d.created_at,
    d.updated_at
   FROM cip_deals d
     LEFT JOIN cip_pipeline_stages s ON s.tenant_id = d.tenant_id AND s.source_connector = d.source_connector AND s.stage_id = d.stage
  WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND d.source_connector = 'hubspot-v1'::text AND (d.properties ->> 'source'::text) = 'China Referral - OpenLight'::text;""",
    "lens_tim_attributed_deals": """ SELECT d.id,
    d.tenant_id,
    d.client_id,
    d.source_connector,
    d.source_id,
    d.name AS deal_name,
    d.amount,
    d.currency,
    d.close_date,
    d.stage AS stage_id,
    s.stage_label,
    s.pipeline_id,
    s.pipeline_label,
    s.probability AS stage_probability,
    d.probability AS deal_probability,
    d.properties ->> 'source'::text AS attribution_source,
    d.properties ->> 'segment'::text AS segment,
    d.properties ->> 'rev_share_partner'::text AS rev_share_partner,
    d.properties ->> 'paid_referral'::text AS paid_referral,
    d.company_id,
    d.contact_id,
    d.tags,
    d.properties,
    d.ingested_at,
    d.refreshed_at,
    d.created_at,
    d.updated_at
   FROM cip_deals d
     LEFT JOIN cip_pipeline_stages s ON s.tenant_id = d.tenant_id AND s.source_connector = d.source_connector AND s.stage_id = d.stage
  WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND d.source_connector = 'hubspot-v1'::text AND (d.properties ->> 'source'::text) = 'China Referral - Tim'::text;""",
    "lens_wayward_attribution_summary": """ SELECT d.tenant_id,
    COALESCE(d.properties ->> 'source'::text, '(unattributed)'::text) AS attribution_source,
    count(*) AS deal_count,
    count(*) FILTER (WHERE s.stage_label = 'Closed Won - Active Customer'::text OR s.stage_label = 'Closed Won - Invoice Paid'::text OR s.stage_label ~~ 'Closed Won%'::text) AS closed_won_count,
    count(*) FILTER (WHERE s.stage_label ~~ 'Closed Lost%'::text OR s.stage_label ~~ 'Closed%lost%'::text) AS closed_lost_count,
    count(*) FILTER (WHERE s.probability IS NOT NULL AND s.probability < 1.0 AND s.probability > 0.0) AS in_pipeline_count,
    COALESCE(sum(d.amount) FILTER (WHERE s.stage_label ~~ 'Closed Won%'::text), 0::numeric) AS closed_won_amount,
    COALESCE(sum(d.amount) FILTER (WHERE s.probability IS NOT NULL AND s.probability < 1.0 AND s.probability > 0.0), 0::numeric) AS in_pipeline_amount,
    min(d.created_at) AS first_deal_at,
    max(d.created_at) AS last_deal_at
   FROM cip_deals d
     LEFT JOIN cip_pipeline_stages s ON s.tenant_id = d.tenant_id AND s.source_connector = d.source_connector AND s.stage_id = d.stage
  WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND d.source_connector = 'hubspot-v1'::text
  GROUP BY d.tenant_id, (COALESCE(d.properties ->> 'source'::text, '(unattributed)'::text))
  ORDER BY (count(*)) DESC;""",
    "lens_hyphen_migration_deals": """ SELECT d.id,
    d.tenant_id,
    d.client_id,
    d.source_connector,
    d.source_id,
    d.name AS deal_name,
    d.amount,
    d.currency,
    d.close_date,
    d.stage AS stage_id,
    s.stage_label,
    s.pipeline_id,
    s.pipeline_label,
    s.probability AS stage_probability,
    d.probability AS deal_probability,
    d.properties ->> 'source'::text AS attribution_source,
    d.properties ->> 'segment'::text AS segment,
    d.properties ->> 'rev_share_partner'::text AS rev_share_partner,
    d.properties ->> 'paid_referral'::text AS paid_referral,
    d.company_id,
    d.contact_id,
    d.tags,
    d.properties,
    d.ingested_at,
    d.refreshed_at,
    d.created_at,
    d.updated_at
   FROM cip_deals d
     LEFT JOIN cip_pipeline_stages s ON s.tenant_id = d.tenant_id AND s.source_connector = d.source_connector AND s.stage_id = d.stage
  WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND d.source_connector = 'hubspot-v1'::text AND (d.properties ->> 'source'::text) = 'Hyphen Social Migration'::text;""",
    "lens_china_clients": """ SELECT d.id,
    d.tenant_id,
    d.client_id,
    d.source_connector,
    d.source_id,
    d.name AS deal_name,
    d.amount,
    d.currency,
    d.close_date,
    d.stage AS stage_id,
    s.stage_label,
    s.pipeline_id,
    s.pipeline_label,
    s.probability AS stage_probability,
    d.probability AS deal_probability,
    d.properties ->> 'source'::text AS attribution_source,
    d.properties ->> 'segment'::text AS segment,
    d.properties ->> 'rev_share_partner'::text AS rev_share_partner,
    d.properties ->> 'paid_referral'::text AS paid_referral,
    d.company_id,
    d.contact_id,
    d.tags,
    d.properties,
    d.ingested_at,
    d.refreshed_at,
    d.created_at,
    d.updated_at
   FROM cip_deals d
     LEFT JOIN cip_pipeline_stages s ON s.tenant_id = d.tenant_id AND s.source_connector = d.source_connector AND s.stage_id = d.stage
  WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND d.source_connector = 'hubspot-v1'::text AND (d.properties ->> 'source'::text) ~~ 'China Referral%'::text;""",
    "lens_china_contacts": """ SELECT id,
    tenant_id,
    client_id,
    source_connector,
    source_id,
    ingested_at,
    refreshed_at,
    previous_version_id,
    ingestion_batch_id,
    authority,
    email,
    phone,
    first_name,
    last_name,
    company_name,
    company_id,
    title,
    country,
    city,
    tags,
    lifecycle_stage,
    properties,
    created_at,
    updated_at,
    companion_data
   FROM cip_contacts ct
  WHERE tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND source_connector = 'hubspot-v1'::text AND (properties ->> 'associatedcompanyid'::text IN ( SELECT DISTINCT d.properties ->> 'hs_primary_associated_company'::text
           FROM cip_deals d
          WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND d.source_connector = 'hubspot-v1'::text AND (d.properties ->> 'source'::text) ~~ 'China Referral%'::text AND (d.properties ->> 'hs_primary_associated_company'::text) IS NOT NULL));""",
    "lens_china_companies": """ SELECT id,
    tenant_id,
    client_id,
    source_connector,
    source_id,
    ingested_at,
    refreshed_at,
    previous_version_id,
    ingestion_batch_id,
    authority,
    name,
    domain,
    industry,
    region,
    language,
    country,
    city,
    employee_count,
    annual_revenue,
    tags,
    properties,
    created_at,
    updated_at,
    companion_data
   FROM cip_companies c
  WHERE tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND source_connector = 'hubspot-v1'::text AND (source_id IN ( SELECT DISTINCT d.properties ->> 'hs_primary_associated_company'::text
           FROM cip_deals d
          WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid AND d.source_connector = 'hubspot-v1'::text AND (d.properties ->> 'source'::text) ~~ 'China Referral%'::text AND (d.properties ->> 'hs_primary_associated_company'::text) IS NOT NULL));""",
}

# --------------------------------------------------------------------------------------------------------------
# Surgical swaps: (unique_anchor_with_old_literal, same_anchor_with_new_literal). Each anchor is chosen so it
# occurs EXACTLY ONCE in the captured body, so the replace touches only that one source_connector WHERE literal
# and nothing else. The cip_deals filter is always the alias-qualified d.source_connector = ...; the main-table
# filter is the unqualified source_connector = ..., disambiguated from the subquery by the clause that follows.
# --------------------------------------------------------------------------------------------------------------
_DEALS_SWAP = (
    f"d.source_connector = '{_HUBSPOT}'::text",
    f"d.source_connector = '{_MIRROR_DEALS}'::text",
)
_CONTACTS_MAIN_SWAP = (
    f"AND source_connector = '{_HUBSPOT}'::text AND (properties ->> 'associatedcompanyid'::text IN",
    f"AND source_connector = '{_MIRROR_CONTACTS}'::text AND (properties ->> 'associatedcompanyid'::text IN",
)
_COMPANIES_MAIN_SWAP = (
    f"AND source_connector = '{_HUBSPOT}'::text AND (source_id IN",
    f"AND source_connector = '{_MIRROR_COMPANIES}'::text AND (source_id IN",
)

# One entry per view, in the same order the statements execute. Views with a cip_deals subquery list the main
# filter first, then the subquery filter; the two anchors are disjoint so order does not matter for the result.
_SWAPS: dict[str, list[tuple[str, str]]] = {
    "lens_adina_attributed_deals": [_DEALS_SWAP],
    "lens_eric_attributed_deals": [_DEALS_SWAP],
    "lens_jeremy_attributed_deals": [_DEALS_SWAP],
    "lens_openlight_attributed_deals": [_DEALS_SWAP],
    "lens_tim_attributed_deals": [_DEALS_SWAP],
    "lens_wayward_attribution_summary": [_DEALS_SWAP],
    "lens_hyphen_migration_deals": [_DEALS_SWAP],
    "lens_china_clients": [_DEALS_SWAP],
    "lens_china_contacts": [_CONTACTS_MAIN_SWAP, _DEALS_SWAP],
    "lens_china_companies": [_COMPANIES_MAIN_SWAP, _DEALS_SWAP],
}

assert set(_SWAPS) == set(_ORIG), "cip_153: _SWAPS and _ORIG must cover the same views"


def _swapped(view: str) -> str:
    """Return the view body with only its connector literal(s) swapped, guarded to be surgical."""
    sql = _ORIG[view]
    for old, new in _SWAPS[view]:
        found = sql.count(old)
        if found != 1:
            raise AssertionError(
                f"cip_153: expected exactly one occurrence of {old!r} in {view}, found {found}; "
                "captured view text drifted, refusing to swap"
            )
        sql = sql.replace(old, new)
    if _HUBSPOT in sql:
        raise AssertionError(f"cip_153: {view} still references '{_HUBSPOT}' after swap")
    return sql


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for view in _ORIG:
        # CREATE OR REPLACE keeps the identical column list, so grants are preserved (no re-GRANT needed).
        op.execute(f"CREATE OR REPLACE VIEW {view} AS {_swapped(view)}")
    print(
        f"cip_153: repointed {len(_ORIG)} lenses off '{_HUBSPOT}' onto the lens-mirror-* connectors by table "
        "context (grants preserved by CREATE OR REPLACE); lens_china_tickets intentionally untouched."
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for view in _ORIG:
        op.execute(f"CREATE OR REPLACE VIEW {view} AS {_ORIG[view]}")
    print(f"cip_153 downgrade: restored the '{_HUBSPOT}' connector literal on {len(_ORIG)} lenses.")
