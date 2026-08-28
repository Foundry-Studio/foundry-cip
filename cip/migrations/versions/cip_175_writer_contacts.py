# foundry: kind=migration domain=client-intelligence-platform
"""cip_175: grant ps_reporting_writer SELECT/INSERT/UPDATE on ps_partner_contacts.

reports #5 Slice 2 (edit): the governed partner.add_contact handler writes a
contact (name/role/email/phone/wechat) into ps_partner_contacts. cip_127 never
granted the reporting writer access to that table (contacts were read-only detail
until now). Grant the three verbs it needs: SELECT (dedup + re-read the
primary-flag), INSERT (add), UPDATE (edit / clear the old primary). Read/write
grant only, no schema change; reversible.

Revision ID: cip_175_writer_contacts
Revises: cip_174_partner_detail
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cip_175_writer_contacts"
down_revision: str | None = "cip_174_partner_detail"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE = "ps_reporting_writer"


def upgrade() -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ps_partner_contacts TO {_ROLE};")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON ps_partner_contacts FROM {_ROLE};")
