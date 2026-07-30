# foundry: kind=migration domain=client-intelligence-platform
"""cip_141 — lens_ps_brand_tickets: per-brand Zendesk ticket counts (RDL 1.5b, P2 Brand 360).

CLEAN-BUILD-PLAN Phase 1.5b. EXPAND-ONLY: one new view, no existing lens touched.

Source spine (verified live 2026-07-30): cip_tickets(zendesk-v1).properties->>'requester_id'
-> cip_contacts(zendesk-v1, source_id=requester_id) -> cip_identity_links (zendesk-v1 left ->
hubspot-v1 right, confidence>=0.9 OR method='manual'; all 19,205 links are email-deterministic,
conf 1.0) -> cip_contacts(hubspot-v1).properties->>'associatedcompanyid' -> lens_ps_brand_hubspot
(cip_76: hubspot_company_id -> wayward_brand_id). 924 brands resolve >=1 ticket live.

Built from the RAW chain + lens_ps_brand_hubspot, NOT by reusing lens_china_tickets (whose
China-Referral deal filter would wrongly exclude non-china brands). Grain = brand; anchored on the
PS brands in lens_ps_brand_hubspot and LEFT JOINed to ticket counts so a 0-ticket brand shows 0.
Zendesk tickets carry NO status property (verified: 0/3906 have 'status'), so the lens emits a
TOTAL count, not open/closed. Coverage ~2,297 hubspot-mapped brands (the DTO acknowledges the gap).

Tenant scoping is IMPLICIT (matches lens_ps_brand_hubspot / house pattern): the PS-scoped brand
anchor (ps_brands via lens_ps_brand_hubspot) scopes the view to PS; owner=postgres, so the reader
reads the view without a raw cip_tickets grant. Granted to ps_reporting_reader + the cip_129 read set.

Revision ID: cip_141_brand_tickets (21 chars <= 32)
Revises: cip_140_invariant_lifetime
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_141_brand_tickets"
down_revision: str | Sequence[str] | None = "cip_140_invariant_lifetime"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_VIEW = r"""
CREATE VIEW lens_ps_brand_tickets AS
WITH brands AS (
    SELECT wayward_brand_id, max(brand_name) AS brand_name
    FROM lens_ps_brand_hubspot
    GROUP BY wayward_brand_id
),
bh AS (SELECT DISTINCT hubspot_company_id, wayward_brand_id FROM lens_ps_brand_hubspot),
tix AS (
    SELECT bh.wayward_brand_id, count(DISTINCT t.id) AS ticket_count
    FROM cip_tickets t
    JOIN cip_contacts zc
      ON zc.source_connector = 'zendesk-v1' AND zc.source_id = t.properties->>'requester_id'
    JOIN cip_identity_links il
      ON il.left_connector = 'zendesk-v1' AND il.left_source_id = zc.source_id
     AND il.right_connector = 'hubspot-v1' AND (il.confidence >= 0.9 OR il.method = 'manual')
    JOIN cip_contacts hc
      ON hc.source_connector = 'hubspot-v1' AND hc.source_id = il.right_source_id
    JOIN bh ON bh.hubspot_company_id = hc.properties->>'associatedcompanyid'
    WHERE t.source_connector = 'zendesk-v1'
    GROUP BY bh.wayward_brand_id
)
SELECT b.wayward_brand_id,
       b.brand_name,
       COALESCE(tix.ticket_count, 0)::int AS ticket_count,
       (COALESCE(tix.ticket_count, 0) > 0)  AS has_tickets
FROM brands b
LEFT JOIN tix ON tix.wayward_brand_id = b.wayward_brand_id;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_VIEW)
    op.execute(f'GRANT SELECT ON lens_ps_brand_tickets TO {_READER};')
    for role in _READ_ROLES:
        op.execute(f'GRANT SELECT ON lens_ps_brand_tickets TO {role};')
    print("cip_141: lens_ps_brand_tickets created + granted to the reporting read set")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_tickets;")
