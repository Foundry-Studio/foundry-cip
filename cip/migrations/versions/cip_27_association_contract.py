# foundry: kind=migration domain=client-intelligence-platform
"""cip_27: lock JSONB-source-id as the canonical association contract.

Per Atlas review CIP-FW-004 (`docs/vision/ATLAS-REVIEW-ASSOCIATION-CONTRACT.md`),
2026-05-22. The decision (Option B hardened): join on `source_id` within
`(tenant_id, source_connector)`; the association key lives in `properties`
JSONB. Typed `*_source_id` columns are the legitimate promotion path
when a join warrants it. CIP-UUID FKs are REJECTED — the existing soft-FK
UUID columns (`cip_deals.company_id`, `cip_deals.contact_id`,
`cip_contacts.company_id`, `cip_tickets.requester_id`) are formally
deprecated.

Empirically verified (prod 2026-05-22):
  - cip_deals.company_id populated: 0 / 3,057
  - cip_contacts.company_id populated: 0 / 68,084
  - cip_tickets.requester_id populated: 0 / 3,390
  - cip_deals.properties->>'hs_primary_associated_company': ~98%
  - cip_contacts.properties->>'associatedcompanyid': most rows

This migration is purely additive + non-destructive:

1. Adds expression indexes on the hot JSONB joining keys so lens views
   that follow the new contract are index-backed. (Phase 2.6's cip_24
   lenses can stay as-is — they're sub-second already against this
   scale; the index helps future / larger joins.)

2. COMMENT-deprecates the four dead soft-FK UUID columns. Future agents
   reading the schema in psql / DataGrip / Postico see the DEPRECATED
   marker immediately. No risk to existing consumers — column still
   exists.

3. Drops `idx_cip_contacts_company` (a zero-row index on the dead
   column — Atlas explicitly flagged this).

4. NO column drops, NO renames, NO row mutations. Per-tenant blast
   radius ≈ 0.

The eventual cleanup (DROP the dead columns) is deferred to a separate
Tim-gated scope after a consumer audit (Atlas §7 / §8 — Metabase
questions / saved SQL may reference them by name).

Revision ID: cip_27_association_contract
Revises: cip_25_project_silk_twenty_role

(cip_26 is reserved for Phase 2.7 PS dest-side lens recut, which is
authored when Tim's design conversation closes. If cip_26 hasn't landed
yet when this migration applies, the chain is cip_25 → cip_27 directly;
cip_26 inserts later in its own slot when authored. Alembic supports
non-contiguous numbering — the chain is by Revises pointer, not by
numeric order.)
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_27_association_contract"
down_revision: str | Sequence[str] | None = "cip_25_project_silk_twenty_role"
branch_labels = None
depends_on = None


# (table, column, deprecation_comment).
_DEPRECATED_SOFT_FKS = [
    (
        "cip_deals", "company_id",
        "DEPRECATED (CIP-FW-004, 2026-05-22): vestigial soft-FK, never "
        "populated. Join via properties->>'hs_primary_associated_company' "
        "= cip_companies.source_id (scoped to (tenant_id, source_connector)). "
        "See CONNECTOR-AUTHORING-GUIDE.md §Associations.",
    ),
    (
        "cip_deals", "contact_id",
        "DEPRECATED (CIP-FW-004, 2026-05-22): vestigial soft-FK, never "
        "populated. HubSpot doesn't surface a stable primary contact id on "
        "deals; if a join is needed, promote a typed contact_source_id "
        "column populated from properties. CIP-UUID FK is rejected.",
    ),
    (
        "cip_contacts", "company_id",
        "DEPRECATED (CIP-FW-004, 2026-05-22): vestigial soft-FK, never "
        "populated. Join via properties->>'associatedcompanyid' = "
        "cip_companies.source_id. See CONNECTOR-AUTHORING-GUIDE.md §Associations.",
    ),
    (
        "cip_tickets", "requester_id",
        "DEPRECATED (CIP-FW-004, 2026-05-22): vestigial soft-FK, never "
        "populated. Zendesk requester_id lives in properties JSONB; "
        "cross-connector resolution to cip_contacts goes through the "
        "future cip_identity_links table (separate Atlas-gated scope).",
    ),
]


def upgrade() -> None:
    # 1. Expression indexes on hot JSONB joining keys.
    # NOT CONCURRENTLY: at our scale (<200k rows per table per tenant),
    # CREATE INDEX completes in seconds — and Alembic's transactional DDL
    # can't run CONCURRENTLY. Atlas §2 explicit guidance.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cip_deals_assoc_company "
        "ON cip_deals ((properties->>'hs_primary_associated_company')) "
        "WHERE properties->>'hs_primary_associated_company' IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cip_contacts_assoc_company "
        "ON cip_contacts ((properties->>'associatedcompanyid')) "
        "WHERE properties->>'associatedcompanyid' IS NOT NULL"
    )

    # 2. COMMENT-deprecate the soft-FK UUID columns.
    for tbl, col, comment in _DEPRECATED_SOFT_FKS:
        # Python-side single-quote escape (Postgres COMMENT requires
        # literal text). Comments are short + controlled — no injection
        # surface beyond migration source review.
        esc = comment.replace("'", "''")
        op.execute(f"COMMENT ON COLUMN {tbl}.{col} IS '{esc}'")

    # 3. Drop the dead idx_cip_contacts_company — covers zero rows under
    # the new contract.
    op.execute("DROP INDEX IF EXISTS idx_cip_contacts_company")


def downgrade() -> None:
    # Recreate the dropped index first (so its absence doesn't surprise
    # any downgrade-time tests that grep pg_indexes).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cip_contacts_company "
        "ON cip_contacts USING btree (tenant_id, company_id) "
        "WHERE (company_id IS NOT NULL)"
    )

    # Null the deprecation comments.
    for tbl, col, _comment in _DEPRECATED_SOFT_FKS:
        op.execute(f"COMMENT ON COLUMN {tbl}.{col} IS NULL")

    # Drop the new expression indexes.
    op.execute("DROP INDEX IF EXISTS idx_cip_contacts_assoc_company")
    op.execute("DROP INDEX IF EXISTS idx_cip_deals_assoc_company")
