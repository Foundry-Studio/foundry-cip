# foundry: kind=migration domain=client-intelligence-platform
"""cip_24: source-side China entity lenses (companies + contacts).

Per Atlas-locked design (docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md
§Q5 source-side correction) + Atlas's 2026-05-22 follow-up ruling on
data-shape (Option B — JSONB source-id joins). The original cip_18
`lens_china_*` views are deals-only; non-deal entities need their own
source-side lenses.

KEY DATA-SHAPE FACT (Atlas confirmed against
`connectors/hubspot/mapper.py` + `connectors/zendesk/mapper.py`):

  CIP's typed FK columns (`cip_deals.company_id`, `cip_contacts.company_id`,
  `cip_tickets.requester_id`) are **VESTIGIAL** — no connector writes
  them, by design. HubSpot/Zendesk mappers dump associations into
  `properties` JSONB. So lens joins MUST go via JSONB source-id refs.

  This is consistent across all current CIP connectors. Whether CIP
  should adopt typed-FK normalization as a contract is a separate
  Atlas-review-gated scope (filed under "Association contract" 2026-05-22).
  In the meantime, JSONB-source-id is the live joining contract.

Two lens views for the China subset, both joining via JSONB:

- `lens_china_companies` — cip_companies whose HubSpot id appears as
  `hs_primary_associated_company` on any China-attributed deal.
  Verified prod join: 1,404 of 1,428 china deals have the key
  populated; cleanly joins to cip_companies.source_id.

- `lens_china_contacts` — cip_contacts whose `associatedcompanyid`
  JSONB key resolves to a china company. Verified prod join: 1,014
  contacts.

`lens_china_tickets` is **DEFERRED out of Phase 2.6** (Atlas ruling):
tickets are Zendesk-sourced, and the "china" subset is defined by
HubSpot DEAL attribution. Linking Zendesk requesters to HubSpot
contacts requires cross-connector identity resolution by email —
that's a separate project, not a 2.6 lens. PS's mirror will receive
deals + companies + contacts (+ derived cip_clients) only.

Each view is GUC-filtered via `app.current_tenant` (mirrors cip_18).
Registered in cip_views per D-121. The cip_21 PS Metabase grant role
gets SELECT on the new views so the Stage 1 dashboard can slice by
company / contact.

Revision ID: cip_24_china_entity_lenses
Revises: cip_23_phase26_schema
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_24_china_entity_lenses"
down_revision: str | Sequence[str] | None = "cip_23_phase26_schema"
branch_labels = None
depends_on = None


# Wayward client_id under EcomLever tenant. Locked per PM decision
# c575c81c (matches cip_18's constants).
ECOMLEVER_TENANT = "dec814db-722a-4730-8e60-51afc4a5dad9"
WAYWARD_CLIENT = "661ecab4-dddb-5924-a34d-af1c5133132d"


# View registration metadata: (view_name, description, slug).
_VIEW_REGISTRATIONS = (
    (
        "lens_china_companies",
        "Wayward — companies appearing as hs_primary_associated_company on a China-Referral deal",
        "wayward-china-companies",
    ),
    (
        "lens_china_contacts",
        "Wayward — contacts whose associatedcompanyid resolves to a China company",
        "wayward-china-contacts",
    ),
)


def upgrade() -> None:
    # ── lens_china_companies (JSONB join via hs_primary_associated_company) ──
    # The subquery uses the GUC DIRECTLY (not a correlated reference to
    # `c.tenant_id`) so Postgres materializes the china company id list
    # once via hash, then probes cip_companies — instead of re-executing
    # the subquery per row. Without this, EXPLAIN ANALYZE timed out at
    # 60s on prod (verified 2026-05-22); with the rewrite it runs <0.5s.
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_china_companies AS
        SELECT c.*
        FROM cip_companies c
        WHERE c.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
          AND c.source_connector = 'hubspot-v1'
          AND c.source_id IN (
            SELECT DISTINCT d.properties->>'hs_primary_associated_company'
            FROM cip_deals d
            WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
              AND d.source_connector = 'hubspot-v1'
              AND d.properties->>'source' LIKE 'China Referral%'
              AND d.properties->>'hs_primary_associated_company' IS NOT NULL
          )
        """
    )

    # ── lens_china_contacts (JSONB join via associatedcompanyid → china companies) ──
    # Same uncorrelated-subquery pattern as lens_china_companies.
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_china_contacts AS
        SELECT ct.*
        FROM cip_contacts ct
        WHERE ct.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
          AND ct.source_connector = 'hubspot-v1'
          AND ct.properties->>'associatedcompanyid' IN (
            SELECT DISTINCT d.properties->>'hs_primary_associated_company'
            FROM cip_deals d
            WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
              AND d.source_connector = 'hubspot-v1'
              AND d.properties->>'source' LIKE 'China Referral%'
              AND d.properties->>'hs_primary_associated_company' IS NOT NULL
          )
        """
    )

    # Drop the deferred tickets view if it was created by a prior partial
    # run of this migration (the original cip_24 included it before the
    # 2026-05-22 Atlas scope-trim ruling). Idempotent.
    op.execute("DROP VIEW IF EXISTS lens_china_tickets")

    # Also clean up the stale cip_views row for tickets (if a prior run
    # registered it) BEFORE inserting the kept registrations so a
    # constraint-collision can't surface.
    op.execute(
        "DELETE FROM cip_views WHERE source_connector='hubspot-v1' "
        "AND source_id = 'wayward-china-tickets'"
    )

    # ── Register kept views in cip_views (D-121 discoverability) ────
    for view_name, description, slug in _VIEW_REGISTRATIONS:
        esc_desc = description.replace("'", "''")
        op.execute(
            f"""
            INSERT INTO cip_views (
                id, tenant_id, client_id, source_connector, source_id,
                ingested_at, refreshed_at, ingestion_batch_id, authority,
                view_name, description, filter_config,
                owner_type, owner_id, is_default,
                created_at, updated_at
            ) VALUES (
                gen_random_uuid(),
                '{ECOMLEVER_TENANT}',
                '{WAYWARD_CLIENT}',
                'hubspot-v1',
                '{slug}',
                NOW(), NOW(), gen_random_uuid(), 'validated',
                '{view_name}',
                '{esc_desc}',
                '{{"slug": "{slug}", "sql_view": "{view_name}", "filter_kind": "attribution_jsonb_join", "phase": "2.6"}}'::jsonb,
                'system',
                'cip',
                false,
                NOW(), NOW()
            )
            ON CONFLICT DO NOTHING
            """
        )

    # ── Extend cip_21 PS Metabase grant role to include the new views ──
    for view_name, _desc, _slug in _VIEW_REGISTRATIONS:
        op.execute(
            f"GRANT SELECT ON {view_name} TO cip_metabase_project_silk"
        )


def downgrade() -> None:
    for view_name, _desc, _slug in _VIEW_REGISTRATIONS:
        op.execute(
            f"REVOKE ALL ON {view_name} FROM cip_metabase_project_silk"
        )
    op.execute(
        "DELETE FROM cip_views WHERE source_connector='hubspot-v1' "
        "AND source_id IN ('wayward-china-companies','wayward-china-contacts')"
    )
    op.execute("DROP VIEW IF EXISTS lens_china_contacts")
    op.execute("DROP VIEW IF EXISTS lens_china_companies")
