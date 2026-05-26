# foundry: kind=migration domain=client-intelligence-platform
"""cip_36: lens_china_deals_history — source-side history lens for ASK 6.

PM scope a0aebe06 ASK 6 (foundry-metabase, 2026-05-26). Unblocks
period-over-period revenue trending on the **PS-owned** copy of the
SCD-2 history table. Today:

  EC cip_deals_history     : 252,781 rows
  EC china subset (universe): 107,075 rows
  PS cip_deals_history     : 0 rows  ← gap this migration + backfill closes

The cip_29 `lens_deals_history` view is already a fully GUC-scoped
SELECT * over cip_deals_history; that lens stays as-is and serves the
*all-deals* history surface (ASK 1). This migration adds a sibling
lens scoped to the China subset — defined the same way as cip_18's
`lens_china_deals` / cip_24's china entity lenses: "the deal's source_id
appears in the set of china-attributed deals (current) for the same
tenant". This makes the China dashboard slice computable directly,
without a Metabase join to the current-deals table.

LENS BODY — JSONB attribution predicate, no source_connector filter
─────────────────────────────────────────────────────────────────

The dispatch's first-draft body included `AND d.source_connector =
'hubspot-v1'` in the china-subquery; we DROP that predicate here on
purpose. PS's mirrored cip_deals carry `source_connector =
'lens-mirror-deals-v1'` (the LensMirror connector identity), while
EC's source-of-truth deals carry `source_connector = 'hubspot-v1'`.
The `properties->>'source' LIKE 'China Referral%'` predicate is
sufficient and **tenant-agnostic** — it correctly identifies china
deals under either GUC. Cip_34's `lens_ps_china_commission` uses the
same predicate against PS deals and works, so the precedent is
established. Filtering on a specific connector would silently zero
the lens under one tenant and is the wrong constraint to bake into a
view that serves both the backfill (read under EC GUC) and Metabase
(read under PS GUC).

Tenant-pin via GUC ONLY (no hardcoded `WHERE tenant_id =
'<PS_UUID>'`) — the lens is reusable from EC for backfill reads and
from PS for ASK 6, just like cip_18/24.

Register in cip_views (D-121) so the lens is discoverable. GRANT
SELECT to:
  - cip_query_reader (cip_31 — agent / Foundry-CIP MCP query path)
  - cip_metabase_project_silk (cip_21 — PS Metabase consumer, ASK 6)

cip_metabase_role (Foundry-internal Metabase, cip_09) is intentionally
NOT granted — china attribution is PS / EcomLever business, not
Foundry-internal reporting. Mirrors cip_24's grant policy.

Revision ID: cip_36_lens_china_deals_history
Revises: cip_35_china_ticket_join_indexes
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_36_lens_china_deals_history"
down_revision: str | Sequence[str] | None = "cip_35_china_ticket_join_indexes"
branch_labels = None
depends_on = None

_VIEW = "lens_china_deals_history"
_SLUG = "china-deals-history"
_DESC = (
    "China-attributed deals — SCD-2 history snapshots. Tenant-pinned via GUC; "
    "subset defined by current cip_deals.properties->>'source' LIKE "
    "'China Referral%' for the active tenant."
)
_GRANT_ROLES = ("cip_query_reader", "cip_metabase_project_silk")


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_china_deals_history AS
        SELECT
            h.history_id,
            h.record_id,
            h.tenant_id,
            h.valid_from,
            h.valid_to,
            h.changed_by,
            h.change_reason,
            h.source_connector,
            h.source_id,
            h.ingested_at,
            h.refreshed_at,
            h.previous_version_id,
            h.ingestion_batch_id,
            h.authority,
            h.name,
            h.stage,
            h.amount,
            h.currency,
            h.close_date,
            h.pipeline,
            h.probability,
            h.tags,
            h.properties
        FROM cip_deals_history h
        WHERE h.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
          AND h.source_id IN (
            SELECT d.source_id
            FROM cip_deals d
            WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
              AND d.properties->>'source' LIKE 'China Referral%'
          )
        """
    )

    esc_desc = _DESC.replace("'", "''")
    # Register against the EcomLever tenant — that's where the lens was
    # first defined (china = wayward / EC business). PS reads the same
    # lens by SQL identifier; cip_views registration is for discovery,
    # not enforcement. Mirrors cip_24's registration pattern.
    op.execute(
        f"""
        INSERT INTO cip_views (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            view_name, description, filter_config,
            owner_type, owner_id, is_default, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'dec814db-722a-4730-8e60-51afc4a5dad9',
            '661ecab4-dddb-5924-a34d-af1c5133132d',
            'hubspot-v1',
            '{_SLUG}',
            NOW(), NOW(), gen_random_uuid(), 'validated',
            '{_VIEW}',
            '{esc_desc}',
            '{{"slug": "{_SLUG}", "sql_view": "{_VIEW}", "filter_kind": "china_attribution_history", "phase": "2.7"}}'::jsonb,
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
        "DELETE FROM cip_views WHERE source_connector='hubspot-v1' "
        f"AND source_id = '{_SLUG}'"
    )
    op.execute(f"DROP VIEW IF EXISTS {_VIEW}")
