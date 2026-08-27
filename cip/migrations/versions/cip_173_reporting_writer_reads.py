# foundry: kind=migration domain=client-intelligence-platform
"""cip_173: grant ps_reporting_writer SELECT on the brand + billing source tables.

The governed FAS reporting-write endpoint gains a partner.add_brand handler that
resolves a brand (ps_brands), enumerates its billed products
(ps_stripe_invoice_lines), and joins cip_clients for the client_id surrogate,
BEFORE it writes the manual attribution row into ps_partner_credit. It writes as
ps_reporting_writer (NOBYPASSRLS) -- cip_127 granted that role write on
ps_partner_credit but NO read on these source tables, so the handler cannot
re-validate server-side (the endpoint never trusts the app's numbers). Grant the
three SELECTs it needs. Read-only, additive, reversible; no schema change.

Revision ID: cip_173_reporting_writer_reads
Revises: cip_172_lens_comments
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cip_173_reporting_writer_reads"
down_revision: str | None = "cip_172_lens_comments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE = "ps_reporting_writer"
# Source tables the add-brand handler must SELECT to re-validate server-side.
_READ_TABLES = ("ps_brands", "ps_stripe_invoice_lines", "cip_clients")


def upgrade() -> None:
    # GRANT SELECT is idempotent (re-granting is a no-op). ps_reporting_writer is
    # created by cip_127, which runs earlier in the chain.
    for t in _READ_TABLES:
        op.execute(f"GRANT SELECT ON {t} TO {_ROLE};")


def downgrade() -> None:
    for t in _READ_TABLES:
        op.execute(f"REVOKE SELECT ON {t} FROM {_ROLE};")
