# foundry: kind=migration domain=client-intelligence-platform
"""cip_147 — lens_ps_email_party (customer-only) + the contact_book reader grant (RDL 1.5b, P5/P2).

CLEAN-BUILD-PLAN Phase 1.5b. EXPAND-ONLY (one new view + one additive GRANT).

1) lens_ps_email_party (SHRUNK per the probes, QC S5): the ONLY email source is ps_brand_contacts.email
   (1,400), brand contacts with no party_id; the bridge to a party is ps_customer_party on
   COALESCE(canonical_brand_id, wayward_brand_id) (cip_130), which yields CUSTOMER parties only. So v1 =
   email -> brand -> ps_customer_party -> customer party_id, emitting party_kind (from ps_party_kind).
   The "resolve a PARTNER from an email" arm (Partner 360) is UNSOURCED and descoped v1 (a partner-email
   ingestion is a future item). `ambiguous` flags an email that maps to >1 party.

2) Grant fix (QC N1): lens_ps_brand_contact_book (cip_100, serves the contacts cells) was granted ONLY
   to query/metabase/twenty, NOT ps_reporting_reader, so the app could not read contacts. Add the
   ps_reporting_reader grant (additive).

nameZh (R12, 1.5a residual): probed cip_companies (hubspot) 2026-07-30 — NO Chinese-name property
exists (0 keyed; 130 companies carry CJK in the latin `name`, already surfaced as brand_name). So
"latin-only stands (R12)": no nameZh column added, BrandName renders brand_name (latin or CJK), nameZh
stays null. Nothing to build.

Revision ID: cip_147_email_party_grants (26 chars <= 32)
Revises: cip_146_cohorts
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_147_email_party_grants"
down_revision: str | Sequence[str] | None = "cip_146_cohorts"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_VIEW = r"""
CREATE VIEW lens_ps_email_party AS
WITH bc AS (
    SELECT DISTINCT lower(btrim(email)) AS email, wayward_brand_id
    FROM ps_brand_contacts
    WHERE btrim(COALESCE(email, '')) <> ''
),
canon AS (
    SELECT wayward_brand_id, COALESCE(canonical_brand_id, wayward_brand_id) AS canon
    FROM lens_ps_brand_header
),
resolved AS (
    SELECT bc.email, bc.wayward_brand_id, cp.party_id, pk.kind AS party_kind
    FROM bc
    LEFT JOIN canon b               ON b.wayward_brand_id  = bc.wayward_brand_id
    LEFT JOIN ps_customer_party cp  ON cp.canonical_brand_id = b.canon
    LEFT JOIN ps_party_kind pk      ON pk.party_id = cp.party_id
),
amb AS (
    SELECT email, count(DISTINCT party_id) AS n_party
    FROM resolved GROUP BY email
)
SELECT r.email, r.wayward_brand_id, r.party_id, r.party_kind,
       (a.n_party > 1) AS ambiguous
FROM resolved r
JOIN amb a ON a.email = r.email;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_VIEW)
    op.execute(f'GRANT SELECT ON lens_ps_email_party TO {_READER};')
    for role in _READ_ROLES:
        op.execute(f'GRANT SELECT ON lens_ps_email_party TO {role};')
    # QC N1 grant fix: the contacts lens was missing the reporting reader.
    op.execute(f'GRANT SELECT ON lens_ps_brand_contact_book TO {_READER};')
    print("cip_147: lens_ps_email_party created + granted; contact_book reader grant added")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_email_party;")
    op.execute(f'REVOKE SELECT ON lens_ps_brand_contact_book FROM {_READER};')
