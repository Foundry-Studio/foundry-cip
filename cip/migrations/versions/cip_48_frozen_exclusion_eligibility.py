# foundry: kind=migration domain=client-intelligence-platform
"""cip_48: the FROZEN exclusion list + the eligibility rule. This is the money model.

THE ARTIFACT
------------
Recovered from Slack: the Excel Tim sent Ali and Jake on 2025-11-18 at 9:44-9:55 PM CST,
converted to `Exhibit_A_China_Brand_Buckets_Complete.pdf` and attached to the LOI's
DocuSign envelope. The LOI (§3) says of it: "This list is hereby frozen and binding upon
LOI execution and may not be modified."

807 unique brand IDs, in 7 buckets. This replaces the fuzzy NAME matching we were using
(which only ever matched 224 brands) with EXACT brand IDs. Names are ambiguous; ids are not.

THE ELIGIBILITY RULE (Tim, 2026-07-13) — encoded here, not scattered in scripts:

  A brand earns Project Silk revenue share if it is CHINESE and NOT on the frozen list.
  Two entry paths:

    RULE A - onboarded AFTER 2025-11-18 (the freeze / takeover date):
             FULL CREDIT AUTOMATICALLY, regardless of referral source. Wayward's
             `deal_source` tag ('China Referral - Eric', 'Other', anything) is PROVENANCE,
             NOT a gate. We keep it to pay partners correctly — never to decide what's ours.

    RULE B - onboarded BEFORE the takeover, and NOT on the frozen list:
             STILL OURS, from DECEMBER 2025 BILLINGS onward — because Project Silk took
             over CS and account management for them. Credit starts at the December
             billing, not at onboarding.

  The frozen list is the ONLY carve-out. Everything Chinese outside it is ours.

WIN-BACKS — the excluded list is not a graveyard. Per LOI §3 (and contract §3.2), most
buckets have a route back, and `winback_path` records it per bucket:
  - Eric Flat Fee     : raise fee to 5% (if <5%) or +1pt (if >=5%)  -> PS eligible
  - Eric Rev Share    : same fee trigger; PLUS if no productive sales within 3 months
                        post-onboarding, PS may engage + activate -> full schedule on the
                        first transaction.  (Tim: the 3-month rule is THIS, and it applies
                        to the excluded Connect book — it is NOT a general dormancy rule.)
  - OpenLight         : identical to Eric Rev Share
  - Heavy Producer    : negotiate >=1% fee increase -> typical schedule
  - Jeremy/Shallow    : fee increase, incremental only
  - OceanWing         : NO win-back, and future Oceanwing clients are auto-excluded too.

NOTE the contract-vs-reality gap, recorded not resolved: the EXECUTED Exhibit A (Jan 2026)
carries ~237 rows, while the FROZEN list carries 807 — the 582 Eric FLAT FEE brands do not
appear in the executed exhibit. Tim's operating rule treats the flat-fee list as excluded,
so we honour that here. The discrepancy goes on the Ali amendment list.

Revision ID: cip_48_frozen_exclusion
Revises: cip_47_information_gaps
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_48_frozen_exclusion"
down_revision: str | Sequence[str] | None = "cip_47_information_gaps"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

TAKEOVER_DATE = "2025-11-18"       # the freeze; brands after this are automatically ours
CREDIT_START = "2025-12-01"        # pre-takeover brands: credit begins at December billings


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE ps_excluded_brands (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            wayward_brand_id UUID NOT NULL,
            client_id UUID,
            brand_name TEXT,
            bucket TEXT NOT NULL,
            referrer TEXT,
            eligible_for_10_rev_share TEXT,
            winback_path TEXT,
            frozen_at DATE NOT NULL DEFAULT DATE '{TAKEOVER_DATE}',
            source_ref TEXT NOT NULL
                DEFAULT 'slack:F09U88RPGMP China Brands Buckets - TIM (exhibit).xlsx',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, wayward_brand_id, bucket)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_excluded_brand ON ps_excluded_brands "
        "(tenant_id, wayward_brand_id)"
    )
    op.execute(
        f"COMMENT ON TABLE ps_excluded_brands IS "
        f"'THE FROZEN EXCLUSION LIST — the single carve-out from Project Silk''s book. "
        f"Recovered from the Excel Tim sent Ali + Jake on {TAKEOVER_DATE} 9:44-9:55 PM CST "
        f"and attached to the LOI DocuSign as Exhibit A. LOI §3: ''This list is hereby "
        f"frozen and binding upon LOI execution and may not be modified.'' "
        f"807 exact brand IDs — this REPLACES fuzzy name matching, which only ever matched "
        f"224 brands. Names are ambiguous; ids are not. "
        f"Being on this list is NOT permanent: see winback_path.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_excluded_brands.winback_path IS "
        "'How PS earns on this brand DESPITE the exclusion. The excluded list is not a "
        "graveyard. Eric Flat Fee: raise the fee to 5%% (if <5%%) or +1pt (if >=5%%). "
        "Eric Rev Share / OpenLight: same fee trigger, PLUS if the brand had no productive "
        "sales within 3 months post-onboarding, PS may engage and activate it — full "
        "schedule from the first transaction. (That 3-month rule belongs HERE, to the "
        "excluded Connect book; it is not a general dormancy rule.) "
        "Heavy Producer / Jeremy / Shallow: negotiate a fee increase. "
        "OceanWing: no win-back at all.'"
    )
    op.execute("ALTER TABLE ps_excluded_brands ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_excluded_brands FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON ps_excluded_brands "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_excluded_brands TO {r}")

    # ── The eligibility lens: one place that answers "is this brand ours?" ───
    op.execute(
        f"""
        CREATE VIEW lens_ps_eligibility AS
        WITH obs AS (
            SELECT o.wayward_brand_id,
                   max(o.client_id::text)::uuid                                  AS client_id,
                   max(o.value) FILTER (WHERE o.field='brand_name')              AS brand_name,
                   max(o.value) FILTER (WHERE o.field='country')                 AS wayward_country,
                   max(o.value) FILTER (WHERE o.field='deal_source')             AS deal_source,
                   max(o.value) FILTER (WHERE o.field='connection_event_at')     AS onboarded_raw
            FROM ps_brand_observations o
            GROUP BY o.wayward_brand_id
        ),
        base AS (
            SELECT obs.*,
                   CASE WHEN obs.onboarded_raw IS NULL THEN NULL
                        ELSE to_date(split_part(obs.onboarded_raw,' at ',1),'FMMonth DD, YYYY')
                   END AS onboarded,
                   x.bucket        AS excluded_bucket,
                   x.winback_path  AS winback_path,
                   c.nationality_class
            FROM obs
            LEFT JOIN ps_excluded_brands x ON x.wayward_brand_id = obs.wayward_brand_id
            LEFT JOIN cip_clients c        ON c.id = obs.client_id
        )
        SELECT
            b.wayward_brand_id,
            b.client_id,
            b.brand_name,
            b.onboarded,
            b.deal_source,                 -- PROVENANCE ONLY. Never a gate on eligibility.
            b.wayward_country,
            b.nationality_class,
            b.excluded_bucket,
            b.winback_path,

            (b.excluded_bucket IS NOT NULL)                       AS is_excluded,
            (b.onboarded > DATE '{TAKEOVER_DATE}')                AS post_takeover,

            -- Chinese by EITHER our own determination OR Wayward's own country field.
            (b.nationality_class IN ('chinese_confirmed','chinese_suspected')
             OR b.wayward_country = 'CN')                         AS is_chinese,

            CASE
                WHEN b.excluded_bucket IS NOT NULL           THEN 'excluded'
                WHEN NOT (b.nationality_class IN ('chinese_confirmed','chinese_suspected')
                          OR b.wayward_country = 'CN')      THEN 'not_chinese'
                WHEN b.onboarded IS NULL                     THEN 'unknown_onboard_date'
                WHEN b.onboarded > DATE '{TAKEOVER_DATE}'    THEN 'eligible_rule_a'
                ELSE 'eligible_rule_b'
            END                                                   AS eligibility,

            -- When our credit starts. Rule A: from onboarding. Rule B: from Dec billings.
            CASE
                WHEN b.excluded_bucket IS NOT NULL          THEN NULL
                WHEN b.onboarded > DATE '{TAKEOVER_DATE}'   THEN b.onboarded
                ELSE DATE '{CREDIT_START}'
            END                                                   AS credit_starts
        FROM base b
        """
    )
    op.execute(
        f"COMMENT ON VIEW lens_ps_eligibility IS "
        f"'THE money model, in one place (Tim, 2026-07-13). A brand is ours if it is "
        f"CHINESE and NOT on the frozen exclusion list. "
        f"RULE A - onboarded after {TAKEOVER_DATE}: FULL credit automatically, REGARDLESS "
        f"of referral source. deal_source is provenance (so we pay partners correctly), "
        f"never a gate on what is ours. "
        f"RULE B - onboarded before the takeover and not excluded: still ours, with credit "
        f"starting at the {CREDIT_START} billings, because PS took over CS and account "
        f"management. "
        f"The frozen list is the ONLY carve-out — and even it has win-back paths.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_eligibility TO {r}")

    _d = (
        "The eligibility model: Chinese AND not on the frozen exclusion list. Rule A "
        "(post-2025-11-18) = automatic full credit regardless of source; Rule B "
        "(pre-takeover) = credit from December 2025 billings."
    ).replace("'", "''")
    op.execute(
        f"""
        INSERT INTO cip_views (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            view_name, description, filter_config,
            owner_type, owner_id, is_default, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), '{PS_TENANT}', NULL, 'lens-mirror', 'ps_eligibility',
            NOW(), NOW(), gen_random_uuid(), 'validated',
            'lens_ps_eligibility', '{_d}',
            '{{"slug": "ps_eligibility", "sql_view": "lens_ps_eligibility", "filter_kind": "ps_eligibility", "phase": "3.0"}}'::jsonb,
            'system', 'cip', false, NOW(), NOW()
        )
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM cip_views WHERE view_name='lens_ps_eligibility'")
    op.execute("DROP VIEW IF EXISTS lens_ps_eligibility")
    op.execute("DROP TABLE IF EXISTS ps_excluded_brands CASCADE")
