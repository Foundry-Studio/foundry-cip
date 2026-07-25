# foundry: kind=migration domain=client-intelligence-platform
"""cip_134: people & assignments (BE-10) — the CRM foundation, CIP-native.

Design of record: WORKBENCH/china-audit/REPORTING-BACKEND-CHECKPOINT.md §6b. The coming CRM is built to
work with CIP directly (NOT the reporting app), so owners + assignments live here as `ps_*` FAS-governed
tables — the future CRM owns/extends them; the reporting engine only READS them (lens_ps_assignment_current).
This is "the information a CRM needs" (owners, effective-dated ownership history) without being a CRM.

WHAT THIS ADDS (all additive; nothing renamed/altered/dropped; no money lens touched → zero money-movement):
  1. ps_staff       — the humans/owners (the future CRM's users). Seeded with ONE row: Rhea.
  2. ps_assignment  — party × role{partnership_manager|sales_rep|cs_rep} × staff, EFFECTIVE-DATED. A
                      reassignment = a new row (the writer closes the prior with effective_to); the as-of
                      read (latest open row) picks the live owner. Full history → later revenue/KPI splits.
  3. lens_ps_assignment_current — current staff per (party, role), for the reporting reads.
  BACKFILL: partnership_manager = Rhea for the ~19 referral partners (DISTINCT ps_partner_credit.party_id,
  set by cip_130). The platform/product counterparty + customer parties are NOT assigned; sales_rep / cs_rep
  get NO rows (structurally ready, unassigned — "ready to split the book later"). cip_owners is EMPTY for PS,
  so ps_staff is standalone (cip_owner_id is a nullable future link).

Staff comp is DEFERRED (cip_135 is an empty skeleton). The staff KPIs this enables (revenue per client
assigned to a rep, revenue by a partner, net-new clients under an employee) are a future layer riding on
ps_assignment — none are in CIP today.

The FAS governed `assign` write (INSERT ps_assignment, close prior) is DEFERRED to the Batch-5 FAS step
(WORKBENCH/china-audit/FAS-WRITES-TODO.md); this migration grants the writer so that path can land.

Revision ID: cip_134_people_assignments   (26 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_133_customer_payments
APPLY-TIME (not in file): export FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS="solo_kimi_k3_engine_dir".
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_134_people_assignments"
down_revision: str | Sequence[str] | None = "cip_133_customer_payments"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
_READER = "ps_reporting_reader"
_WRITER = "ps_reporting_writer"

_RHEA = "Rhea"                      # the one seeded owner (all 19 partners' partnership manager today)
_PROGRAM_ANCHOR = "2025-10-01"     # backfill effective_from — the china program's ownership anchor

_DDL_STAFF = """
    CREATE TABLE ps_staff (
        staff_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id    UUID NOT NULL,
        display_name TEXT NOT NULL,
        email        TEXT,
        status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
        cip_owner_id TEXT,                       -- future link to cip_owners (EMPTY for PS today)
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    )"""

_DDL_ASSIGNMENT = """
    CREATE TABLE ps_assignment (
        id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id      UUID NOT NULL,
        party_id       UUID NOT NULL REFERENCES ps_party(party_id) ON DELETE CASCADE,
        role           TEXT NOT NULL CHECK (role IN ('partnership_manager','sales_rep','cs_rep')),
        staff_id       UUID NOT NULL REFERENCES ps_staff(staff_id),
        effective_from DATE NOT NULL DEFAULT current_date,
        effective_to   DATE,
        set_by         TEXT NOT NULL,
        set_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        write_id       UUID,
        note           TEXT,
        UNIQUE (tenant_id, party_id, role, effective_from)
    )"""

_INDEX_ASOF = (
    "CREATE INDEX idx_ps_assignment_asof "
    "ON ps_assignment (tenant_id, party_id, role, effective_from DESC)"
)

# current owner per (party, role): latest open effective row, + the staff display name.
_LENS_CURRENT = """
CREATE OR REPLACE VIEW lens_ps_assignment_current AS
SELECT DISTINCT ON (a.party_id, a.role)
       a.party_id, a.role, a.staff_id, s.display_name AS staff_name, a.effective_from
FROM ps_assignment a
JOIN ps_staff s ON s.staff_id = a.staff_id
WHERE a.effective_from <= current_date
  AND (a.effective_to IS NULL OR a.effective_to > current_date)
ORDER BY a.party_id, a.role, a.effective_from DESC
"""


def _rls_and_read_grants(table: str) -> None:
    """Repo RLS pattern (cip_39/130): FORCE tenant-scoped RLS + GRANT SELECT to the 3 read roles + the
    reporting reader. Migrations run as owner (BYPASSRLS), so the seed/backfill DML is unaffected."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY cip_tenant_scope ON {table} USING ({_PRED}) WITH CHECK ({_PRED})")
    for role in (*_READ_ROLES, _READER):
        op.execute(f"GRANT SELECT ON {table} TO {role}")


def _grant_lens_reads(view: str) -> None:
    for role in (*_READ_ROLES, _READER):
        op.execute(f"GRANT SELECT ON {view} TO {role}")


def upgrade() -> None:
    # Tenant GUC so the FORCE-RLS WITH CHECK passes for the seed/backfill DML (defensive; owner bypasses).
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")

    # 1. Tables + as-of index + RLS/read grants + writer grants (the future FAS `assign` write path).
    op.execute(_DDL_STAFF)
    op.execute(_DDL_ASSIGNMENT)
    op.execute(_INDEX_ASOF)
    # Enforce ONE OPEN row per (party, role): a party has exactly one current owner per role, so a
    # reassignment MUST close the prior (set effective_to) before opening the new. The backfill's
    # one-open-row-per-party satisfies this; a direct-join history consumer can't double-count a current owner.
    op.execute(
        "CREATE UNIQUE INDEX uq_ps_assignment_open ON ps_assignment (tenant_id, party_id, role) "
        "WHERE effective_to IS NULL"
    )
    # FK covering index for the reverse lookup (a staff member's book of parties).
    op.execute("CREATE INDEX idx_ps_assignment_staff ON ps_assignment (tenant_id, staff_id)")
    _rls_and_read_grants("ps_staff")
    _rls_and_read_grants("ps_assignment")
    for tbl in ("ps_staff", "ps_assignment"):
        op.execute(f"GRANT INSERT, UPDATE, SELECT ON {tbl} TO {_WRITER}")

    # 2. Seed the one owner (Rhea), idempotently (display_name is the seed key).
    op.execute(
        f"""
        INSERT INTO ps_staff (tenant_id, display_name, status)
        SELECT '{PS_TENANT}'::uuid, '{_RHEA}', 'active'
        WHERE NOT EXISTS (
            SELECT 1 FROM ps_staff WHERE tenant_id = '{PS_TENANT}'::uuid AND display_name = '{_RHEA}')
        """
    )

    # 3. Backfill: partnership_manager = Rhea for every referral partner cip_130 linked (DISTINCT party_id).
    #    Counterparty + customer parties are NOT assigned; sales_rep / cs_rep get no rows (ready-unassigned).
    op.execute(
        f"""
        INSERT INTO ps_assignment (tenant_id, party_id, role, staff_id, effective_from, set_by, note)
        SELECT DISTINCT pc.tenant_id, pc.party_id, 'partnership_manager',
               (SELECT staff_id FROM ps_staff
                WHERE tenant_id = '{PS_TENANT}'::uuid AND display_name = '{_RHEA}' LIMIT 1),
               DATE '{_PROGRAM_ANCHOR}', 'backfill:cip_134', 'all partners -> Rhea at program start'
        FROM ps_partner_credit pc
        WHERE pc.tenant_id = '{PS_TENANT}'::uuid AND pc.party_id IS NOT NULL
        ON CONFLICT (tenant_id, party_id, role, effective_from) DO NOTHING
        """
    )

    # 4. Current-assignment lens for the reporting reads.
    op.execute(_LENS_CURRENT)
    _grant_lens_reads("lens_ps_assignment_current")

    # 5. Docs.
    op.execute(
        "COMMENT ON VIEW lens_ps_assignment_current IS $c$BE-10 (cip_134): the CURRENT owner per (party, "
        "role) — the latest OPEN ps_assignment row (effective_from <= today, effective_to null-or-future), "
        "with the staff display name. For the reporting reads (a partner's manager; later revenue-by-rep).$c$"
    )
    op.execute(
        "COMMENT ON TABLE ps_staff IS $c$BE-10 (cip_134): people/owners — the future CRM's users. "
        "Standalone (cip_owners is empty for PS; cip_owner_id is a future link). Seeded: Rhea.$c$"
    )
    for _col, _doc in (
        ("display_name", "mutable human name; the seed/idempotency key for Rhea (people may share names, so no UNIQUE)"),
        ("email", "nullable; the future self-scoped comp key (ps_staff_rate.staff_email) — set at comp-design time"),
        ("cip_owner_id", "nullable future link to cip_owners (empty for PS today)"),
    ):
        op.execute(f"COMMENT ON COLUMN ps_staff.{_col} IS '{_doc}'")
    op.execute(
        "COMMENT ON TABLE ps_assignment IS $c$BE-10 (cip_134): effective-dated ownership — party x "
        "role{partnership_manager|sales_rep|cs_rep} x staff. Reassign = new row + close prior (effective_to); "
        "as-of read (lens_ps_assignment_current) picks the latest open row. Backfilled partnership_manager=Rhea "
        "for the referral partners; sales_rep/cs_rep ready-but-unassigned. Governed FAS `assign` write is "
        "deferred (FAS-WRITES-TODO).$c$"
    )
    for _col, _doc in (
        ("party_id", "the assigned party (ps_party): a partner (partnership_manager) or a client (sales_rep/cs_rep)"),
        ("staff_id", "the owning person (ps_staff)"),
        ("role", "partnership_manager (partners) | sales_rep | cs_rep (clients) — the ownership relation"),
        ("effective_from", "as-of date this assignment takes effect (inclusive); as-of read picks the latest <= today"),
        ("effective_to", "exclusive end of the assignment; NULL = current owner. Writer sets it on reassignment"),
        ("write_id", "governed-write correlation id (FAS assign); NULL for the cip_134 backfill"),
    ):
        op.execute(f"COMMENT ON COLUMN ps_assignment.{_col} IS '{_doc}'")

    print(
        "cip_134: created ps_staff (seed Rhea) + ps_assignment (RLS + reads + writer) + "
        "lens_ps_assignment_current; backfilled partnership_manager=Rhea for all referral partners"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_assignment_current")
    op.execute("DROP TABLE IF EXISTS ps_assignment CASCADE")
    op.execute("DROP TABLE IF EXISTS ps_staff CASCADE")
