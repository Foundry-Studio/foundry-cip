# foundry: kind=migration domain=client-intelligence-platform
"""cip_174: partner detail -- entity_type (individual/agent) + lens_ps_partner_detail.

reports #5: "partner information is inaccurate / too little detail -- add contact
info, related details, and specify whether it belongs to an individual or an
agent." Contact info was already modeled (ps_partner_contacts, cip_42) but never
surfaced, and individual-vs-agent had no field. This adds
ps_partner_registry.entity_type ('individual'|'agent'|NULL) and creates
lens_ps_partner_detail -- one row per partner exposing the registry facts +
entity_type + primary contact + the full contact list -- so the reports partner
page can show real detail. Read-only lens (Slice 1); the write/edit path and the
source-accuracy fix are separate slices.

Revision ID: cip_174_partner_detail
Revises: cip_173_reporting_writer_reads
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cip_174_partner_detail"
down_revision: str | None = "cip_173_reporting_writer_reads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_LENS = """
CREATE OR REPLACE VIEW lens_ps_partner_detail AS
SELECT
    r.partner_id,
    a.party_id,       -- reports drills by party_id (UUID); handle alias bridges to the slug
    r.name            AS partner_name,
    r.entity_type,
    r.company_name,
    r.country,
    r.channel,
    r.payment_method,
    r.default_rate,
    r.status,
    r.notes,
    pc.name           AS primary_contact_name,
    pc.role           AS primary_contact_role,
    pc.email          AS primary_contact_email,
    pc.phone          AS primary_contact_phone,
    pc.wechat         AS primary_contact_wechat,
    coalesce(cl.contact_count, 0) AS contact_count,
    cl.contacts
FROM ps_partner_registry r
LEFT JOIN ps_party_alias a
    ON a.tenant_id = r.tenant_id AND a.alias_kind = 'handle' AND a.alias_value = r.partner_id
LEFT JOIN LATERAL (
    SELECT c.name, c.role, c.email, c.phone, c.wechat
    FROM ps_partner_contacts c
    WHERE c.tenant_id = r.tenant_id AND c.partner_id = r.partner_id
    ORDER BY c.is_primary DESC NULLS LAST, c.updated_at DESC
    LIMIT 1
) pc ON true
LEFT JOIN LATERAL (
    SELECT count(*) AS contact_count,
           jsonb_agg(jsonb_build_object(
               'name', c.name, 'role', c.role, 'email', c.email,
               'phone', c.phone, 'wechat', c.wechat, 'is_primary', c.is_primary
           ) ORDER BY c.is_primary DESC NULLS LAST, c.updated_at DESC) AS contacts
    FROM ps_partner_contacts c
    WHERE c.tenant_id = r.tenant_id AND c.partner_id = r.partner_id
) cl ON true;
"""


def upgrade() -> None:
    op.execute("ALTER TABLE ps_partner_registry ADD COLUMN IF NOT EXISTS entity_type TEXT")
    # 'individual' | 'agent' | NULL (unknown until set). Named constraint so the
    # write path (Slice 2) can rely on it and the downgrade can drop it cleanly.
    op.execute(
        "ALTER TABLE ps_partner_registry ADD CONSTRAINT ck_ps_partner_registry_entity_type "
        "CHECK (entity_type IS NULL OR entity_type IN ('individual', 'agent'))"
    )
    op.execute(_LENS)
    op.execute(f"GRANT SELECT ON lens_ps_partner_detail TO {_READER};")
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_partner_detail TO {role};")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_detail")
    op.execute(
        "ALTER TABLE ps_partner_registry DROP CONSTRAINT IF EXISTS ck_ps_partner_registry_entity_type"
    )
    op.execute("ALTER TABLE ps_partner_registry DROP COLUMN IF EXISTS entity_type")
