# foundry: kind=migration domain=client-intelligence-platform
"""cip_33: cip_identity_links table + lens_china_tickets (PM 08b4ce7d).

Cross-connector identity resolution — the missing edge for the deferred
ticket lens (Metabase ASK 2). A Zendesk ticket has no HubSpot key; the
chain is:

  cip_tickets (zendesk-v1) → properties->>'requester_id' (Zendesk user id)
    → cip_contacts WHERE source_connector='zendesk-v1' AND source_id=requester_id
    → cip_identity_links (zendesk contact ↔ hubspot contact, by email)   ← THIS
    → cip_contacts (hubspot-v1) → properties->>'associatedcompanyid'
    → cip_companies.source_id → china-referral filter (cip_18/cip_24 predicate)

Atlas-locked policy (CIP-FW-004 §5 + identity-resolution-policy-design.md,
Tim sign-off 2026-05-24). Grounded on prod 2026-05-24 (EcomLever):
2,890 Zendesk tickets all carry requester_id (requester_email NULL);
20,152 distinct Zendesk contact emails, 19,783 (98.2%) exact-match a
HubSpot contact email, 0 ambiguity. DETERMINISTIC email match — NOT a
fuzzy/ML matcher (v3, out of scope).

Two objects:

(a) Table cip_identity_links — the resolved edge, cached + curatable.
    The unique key includes `method` so a `manual`/`operator:` row can
    coexist with a `deterministic-email-v1` row; the deterministic pass
    never clobbers a human override.

(b) View lens_china_tickets — the ASK 2 deliverable. Walks the chain,
    consumes only links with confidence >= 0.9 (exact + role) plus
    manual, reuses the cip_24 china-referral predicate.

The resolver that POPULATES the table is scripts/resolve_identity_links.py
(run per-tenant, GUC-scoped, idempotent upsert).

Revision ID: cip_33_identity_links
Revises: cip_32_ps_deal_financials_lens
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_33_identity_links"
down_revision: str | Sequence[str] | None = "cip_32_ps_deal_financials_lens"
branch_labels = None
depends_on = None


_TENANT_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
)

# Roles that read the identity links + the ticket lens.
_GRANT_ROLES = ("cip_query_reader", "cip_metabase_project_silk")


def upgrade() -> None:
    # ── (a) cip_identity_links table ────────────────────────────────────
    op.create_table(
        "cip_identity_links",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            primary_key=True, server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("left_connector", sa.Text(), nullable=False),
        sa.Column("left_source_id", sa.Text(), nullable=False),
        sa.Column("right_connector", sa.Text(), nullable=False),
        sa.Column("right_source_id", sa.Text(), nullable=False),
        sa.Column("link_type", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        # `method` in the unique key lets a manual/operator row coexist
        # with the deterministic row — deterministic pass never clobbers
        # a human override (consumption rule prefers manual).
        sa.UniqueConstraint(
            "tenant_id", "left_connector", "left_source_id",
            "right_connector", "right_source_id", "method",
            name="uq_cip_identity_links_edge_method",
        ),
    )
    op.create_index(
        "idx_cip_identity_links_left",
        "cip_identity_links",
        ["tenant_id", "left_connector", "left_source_id"],
    )
    op.create_index(
        "idx_cip_identity_links_right",
        "cip_identity_links",
        ["tenant_id", "right_connector", "right_source_id"],
    )

    # ── RLS (cip_tenant_scope, FORCE, USING + WITH CHECK per cip_30) ─────
    op.execute("ALTER TABLE cip_identity_links ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_identity_links FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON cip_identity_links "
        f"USING ({_TENANT_PREDICATE}) "
        f"WITH CHECK ({_TENANT_PREDICATE})"
    )

    # ── Grants ──────────────────────────────────────────────────────────
    for role in _GRANT_ROLES:
        op.execute(f"GRANT SELECT ON cip_identity_links TO {role}")

    # ── (b) lens_china_tickets ──────────────────────────────────────────
    # Walk the §1 chain. Consume only links with confidence >= 0.9
    # (email-exact + email-role-account) plus any manual/operator link.
    # China-referral predicate reused from cip_24's lens_china_companies.
    # GUC-scoped like the other lens_china_* views (no hardcoded tenant —
    # these are EcomLever-side source lenses driven by the GUC).
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_china_tickets AS
        SELECT
            tk.id            AS ticket_id,
            tk.tenant_id,
            tk.source_id     AS zendesk_ticket_id,
            tk.subject,
            tk.status,
            tk.priority,
            zc.source_id     AS zendesk_contact_id,
            hc.source_id     AS hubspot_contact_id,
            hc.properties->>'associatedcompanyid' AS hubspot_company_id,
            co.id            AS cip_company_id,
            co.name          AS brand_name,
            il.link_type,
            il.confidence
        FROM cip_tickets tk
        JOIN cip_contacts zc
          ON zc.tenant_id = tk.tenant_id
         AND zc.source_connector = 'zendesk-v1'
         AND zc.source_id = tk.properties->>'requester_id'
        JOIN cip_identity_links il
          ON il.tenant_id = tk.tenant_id
         AND il.left_connector = 'zendesk-v1'
         AND il.left_source_id = zc.source_id
         AND il.right_connector = 'hubspot-v1'
         AND (il.confidence >= 0.9 OR il.method LIKE 'operator:%' OR il.link_type = 'manual')
        JOIN cip_contacts hc
          ON hc.tenant_id = tk.tenant_id
         AND hc.source_connector = 'hubspot-v1'
         AND hc.source_id = il.right_source_id
        JOIN cip_companies co
          ON co.tenant_id = tk.tenant_id
         AND co.source_connector = 'hubspot-v1'
         AND co.source_id = hc.properties->>'associatedcompanyid'
        WHERE tk.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
          AND tk.source_connector = 'zendesk-v1'
          AND co.source_id IN (
            SELECT DISTINCT d.properties->>'hs_primary_associated_company'
            FROM cip_deals d
            WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
              AND d.source_connector = 'hubspot-v1'
              AND d.properties->>'source' LIKE 'China Referral%'
              AND d.properties->>'hs_primary_associated_company' IS NOT NULL
          )
        """
    )

    # Register lens_china_tickets in cip_views (D-121). EcomLever-side
    # source lens (mirrors cip_24's registration shape).
    op.execute(
        """
        INSERT INTO cip_views (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            view_name, description, filter_config,
            owner_type, owner_id, is_default,
            created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'dec814db-722a-4730-8e60-51afc4a5dad9',
            '661ecab4-dddb-5924-a34d-af1c5133132d',
            'hubspot-v1',
            'wayward-china-tickets',
            NOW(), NOW(), gen_random_uuid(), 'validated',
            'lens_china_tickets',
            'Wayward — Zendesk tickets whose requester resolves (>=0.9) via cip_identity_links to a China-Referral brand',
            '{"slug": "wayward-china-tickets", "sql_view": "lens_china_tickets", "filter_kind": "identity_link_ticket_join", "phase": "3-prep"}'::jsonb,
            'system',
            'cip',
            false,
            NOW(), NOW()
        )
        ON CONFLICT DO NOTHING
        """
    )

    for role in _GRANT_ROLES:
        op.execute(f"GRANT SELECT ON lens_china_tickets TO {role}")


def downgrade() -> None:
    for role in _GRANT_ROLES:
        op.execute(f"REVOKE ALL ON lens_china_tickets FROM {role}")
    op.execute(
        "DELETE FROM cip_views WHERE source_connector='hubspot-v1' "
        "AND source_id = 'wayward-china-tickets'"
    )
    op.execute("DROP VIEW IF EXISTS lens_china_tickets")

    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_identity_links")
    op.execute("ALTER TABLE cip_identity_links NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS cip_identity_links")
