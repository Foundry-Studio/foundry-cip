# foundry: kind=migration domain=client-intelligence-platform
"""cip_99: document the raw cip_* source tables (Tim, 2026-07-15 — readability).

The raw connector tables carried almost no comments — a human or agent reading `cip_companies`
directly had no idea it's the full 132k CRM population, not just PS brands, or that the real field
meanings live in `cip_connector_property_registry`. The ps_* audit tables are well-documented; this
brings the source layer up to the same bar. Column-level meanings intentionally stay in the property
registry (single source of truth, with coverage_pct + watch_out_for); these table comments point
there. Comments only — zero data/behaviour change.

Revision ID: cip_99_comment_source_tables
Revises: cip_98_drop_dead_tables
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_99_comment_source_tables"
down_revision: str | Sequence[str] | None = "cip_98_drop_dead_tables"
branch_labels = None
depends_on = None

_R = "Field meanings + watch-outs: cip_connector_property_registry. Connector-owned; do not hand-edit."

_COMMENTS = {
    "cip_companies":
        "RAW HubSpot + Zendesk companies (~132k — the FULL CRM population, NOT just PS brands; the "
        "PS subset is the lens-mirror in cip_clients). Typed: name, domain, country, region, city, "
        "industry, language; everything else in the properties JSONB. " + _R,
    "cip_contacts":
        "RAW HubSpot + Zendesk contacts (~87k). Typed: email, phone, firstname, lastname, jobtitle; "
        "extra in properties JSONB. " + _R,
    "cip_deals":
        "RAW HubSpot deals (~5.2k). Typed: name, amount, close_date, pipeline/stage. *** Wayward's "
        "OWN money numbers (total_fees_paid, lifetime_usage_fees_generated, lifetime_gmv, "
        "amazon_seller_type) live in the properties JSONB *** — P2 may promote them to typed columns "
        "(see WORKBENCH/china-audit/SCHEMA-AUDIT.md Finding 1). " + _R,
    "cip_engagements":
        "RAW HubSpot engagements — emails / calls / notes / meetings (~12.5k). Detail in properties "
        "JSONB. " + _R,
    "cip_tickets":
        "RAW Zendesk support tickets (~4.4k) — per-brand CS activity. Typed: subject, status, "
        "priority, requester/assignee, timestamps; via_channel + extra in properties JSONB. NOTE: "
        "dormancy is SALES-based, not ticket-based (see OWNERSHIP-RULES.md). " + _R,
    "cip_ticket_comments":
        "RAW Zendesk ticket comments/replies (~12.8k) — the per-ticket conversation. " + _R,
    "cip_files": "RAW HubSpot file/attachment metadata. " + _R,
    "cip_owners":
        "HubSpot owners — the sales/CS people who own deals/companies. Small reference table. " + _R,
    "cip_pipeline_stages":
        "HubSpot pipeline stage definitions — maps stage ids to labels/order. Reference table. " + _R,
    "cip_clients":
        "The Project-Silk lens-mirror of brands (client-scoped), synced hourly (37 min past the "
        "hour). Carries "
        "wayward_brand_id, exhibit_a, lifecycle_status, performance_tier. This is the CRM CLIENT "
        "view; the audit brand master is ps_brands.",
    "cip_identity_links":
        "A pre-existing cross-connector identity graph (~19k): left/right connector+source_id with "
        "confidence + method (links Zendesk <-> HubSpot). NOTE: a SECOND identity system alongside "
        "ps_brands.canonical_brand_id — consolidation is parked (WORKBENCH/china-audit/PARKING.md P3).",
    "cip_knowledge_chunks":
        "The knowledge base — ingested client document libraries (~36k chunks; e.g. Grownsy's "
        "Chinese product library), with embeddings for retrieval.",
    "cip_connector_property_registry":
        "THE FIELD DICTIONARY for every synced connector property: plain_english_meaning, "
        "coverage_pct, watch_out_for, and storage_location ('column' = typed, 'overflow' = in the "
        "properties JSONB). Read this before guessing what any HubSpot/Zendesk field means.",
    "cip_sync_runs":
        "FRESHNESS ledger — one row per connector sync run: connector, status, rows, timings, "
        "errors. The source of truth for 'did the last sync succeed'.",
    "cip_views":
        "Lens/view definitions for the lens engine — per-tenant filter configs that drive lens_* "
        "generation. Config, not data.",
    "cip_marketing_emails":
        "HubSpot marketing emails. SUPPORTED connector target (base.py ALLOWED_CIP_TABLES + "
        "persister) but NOT currently synced (0 rows) — empty by sync SCOPE, not dead. Do not drop "
        "without also removing it from the connector framework + its tests.",
    "cip_contact_lists":
        "HubSpot contact lists. SUPPORTED connector target but NOT currently synced (0 rows) — "
        "empty by sync scope, not dead. See cip_marketing_emails note.",
    "cip_contact_list_memberships":
        "HubSpot contact-list membership rows. SUPPORTED connector target but NOT currently synced "
        "(0 rows) — empty by sync scope, not dead. See cip_marketing_emails note.",
}


def upgrade() -> None:
    # exec_driver_sql: send DDL straight to psycopg, bypassing SQLAlchemy text() bind-param parsing
    # (a comment may contain ':' or other chars that text() would misread as a placeholder).
    bind = op.get_bind()
    for tbl, comment in _COMMENTS.items():
        bind.exec_driver_sql(f"COMMENT ON TABLE {tbl} IS $cmt${comment}$cmt$")


def downgrade() -> None:
    bind = op.get_bind()
    for tbl in _COMMENTS:
        bind.exec_driver_sql(f"COMMENT ON TABLE {tbl} IS NULL")
