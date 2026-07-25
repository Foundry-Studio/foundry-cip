# foundry: kind=migration domain=client-intelligence-platform
"""cip_135: staff-rate skeleton (BE-4) — a ready-but-EMPTY, flexible staff-comp store.

Design of record: WORKBENCH/china-audit/REPORTING-BACKEND-CHECKPOINT.md §5. Staff comp is DEFERRED /
UNDESIGNED (Tim, 2026-07-25: "we haven't set staff commissions, and not every staff gets commission").
So this is an intentionally FLEXIBLE, empty skeleton — no seed, no backfill — that can hold any staff-comp
shape without a schema change once the model is designed. It keys to ps_staff (cip_134).

WHY FLEXIBLE: `basis` is OPEN text (NO check) — what a person earns on isn't decided yet. `params` (jsonb)
+ scope_ref_{type,id} let a plan attach to any dimension. `rate_type` is bounded to a small set;
`rate_value` is the number. All effective-dated like the partner rate (cip_131).

SELF-SCOPED READ (pack §9): a person sees only THEIR OWN comp — enforced by the app DAL filtering
`WHERE staff_email = ctx.email` (or staff_id), NOT by a lens (a lens would expose the whole table to the
reader role). So this migration creates NO lens; the reporting reader gets SELECT for the future
self-scoped DAL, and the FAS writer gets INSERT/UPDATE for the future governed staff-rate write.

Additive; no money lens touched → zero money-movement.

Revision ID: cip_135_staff_rate   (18 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_134_people_assignments
APPLY-TIME (not in file): export FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS="solo_kimi_k3_engine_dir".
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_135_staff_rate"
down_revision: str | Sequence[str] | None = "cip_134_people_assignments"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
_READER = "ps_reporting_reader"
_WRITER = "ps_reporting_writer"

_DDL_STAFF_RATE = """
    CREATE TABLE ps_staff_rate (
        id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id      UUID NOT NULL,
        staff_id       UUID REFERENCES ps_staff(staff_id),   -- link to the person (cip_134); nullable hook
        staff_email    TEXT,                                 -- the self-scoped read key (DAL: WHERE staff_email = ctx.email)
        basis          TEXT,                                 -- OPEN text (no CHECK): what they earn on (undesigned)
        scope_ref_type TEXT,                                 -- e.g. 'party' | 'client' | 'company' (flexible)
        scope_ref_id   TEXT,
        params         JSONB,                                -- any extra shape the plan needs, no migration
        rate_type      TEXT CHECK (rate_type IN ('percent','flat','tiered','other')),
        rate_value     NUMERIC,
        effective_from DATE NOT NULL DEFAULT current_date,
        effective_to   DATE,
        set_by         TEXT,
        set_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        write_id       UUID,
        note           TEXT
    )"""

_INDEX = (
    "CREATE INDEX idx_ps_staff_rate_lookup "
    "ON ps_staff_rate (tenant_id, staff_email, effective_from DESC)"
)


def upgrade() -> None:
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")
    op.execute(_DDL_STAFF_RATE)
    op.execute(_INDEX)
    # FK covering index (a person's comp rows).
    op.execute("CREATE INDEX idx_ps_staff_rate_staff ON ps_staff_rate (tenant_id, staff_id)")
    # RLS is tenant-scoped; per-PERSON comp privacy is the app DAL's job (WHERE staff_email = ctx.email).
    # So SELECT goes ONLY to ps_reporting_reader (the DAL role) — NOT the analytics roles
    # (metabase / twenty / query_reader), which query DIRECTLY and would bypass the DAL filter and read
    # everyone's comp. (Empty today; add per-person RLS via a per-user GUC when comp is designed.)
    op.execute("ALTER TABLE ps_staff_rate ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_staff_rate FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY cip_tenant_scope ON ps_staff_rate USING ({_PRED}) WITH CHECK ({_PRED})")
    op.execute(f"GRANT SELECT ON ps_staff_rate TO {_READER}")
    op.execute(f"GRANT INSERT, UPDATE, SELECT ON ps_staff_rate TO {_WRITER}")
    op.execute(
        "COMMENT ON TABLE ps_staff_rate IS $c$BE-4 (cip_135): flexible, effective-dated staff-comp store — "
        "READY-BUT-EMPTY (staff comp is undesigned; no seed/backfill). basis is OPEN text; params jsonb + "
        "scope_ref_* give any shape without a migration. Self-scoped read = app DAL WHERE staff_email = "
        "ctx.email (NOT a lens — a lens would expose everyone's comp). Keys to ps_staff (cip_134).$c$"
    )
    for _col, _doc in (
        ("basis", "OPEN text (no CHECK): what a person earns on — undesigned; free-text until comp is modeled"),
        ("params", "jsonb — any extra plan shape without a migration"),
        ("staff_email", "the self-scoped read key (app DAL: WHERE staff_email = ctx.email); NOT DB-enforced"),
        ("staff_id", "optional link to ps_staff (cip_134); nullable hook until the person-key is decided"),
    ):
        op.execute(f"COMMENT ON COLUMN ps_staff_rate.{_col} IS '{_doc}'")
    print("cip_135: created ps_staff_rate (empty flexible skeleton; RLS + reader-only SELECT + writer)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ps_staff_rate CASCADE")
