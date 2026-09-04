# foundry: kind=migration domain=client-intelligence-platform
"""cip_176: close the three tenant-isolation gaps found by measurement.

Every table carrying ``tenant_id`` is supposed to be ENABLE + FORCE row level
security with a tenant policy. Measured against production 2026-09-04, 79 of 82
were. These three were not:

  ps_nationality_review_state   ENABLEd, NOT FORCEd, 1 policy
  ps_nationality_request_log    no RLS at all, 0 policies
  ps_readout_editions           no RLS at all, 0 policies

WHAT EACH HALF ACTUALLY BUYS, stated precisely because it is easy to overclaim.

Postgres exempts the table OWNER from row security unless FORCE is set, and
exempts superusers and BYPASSRLS roles ALWAYS, FORCE or not. Measured in
production 2026-09-04: all three tables are owned by `postgres`, which is both
`rolsuper` and `rolbypassrls`.

  ENABLE + policy on the two unprotected tables is the REAL fix. It fences the
  non-superuser reader roles (cip_query_reader, ps_reporting_reader,
  cip_metabase_project_silk, cip_twenty_project_silk, metabase_reader_foundry),
  none of which is superuser or BYPASSRLS. Those tables previously had no row
  security at all, so those roles saw every tenant's rows.

  FORCE on ps_nationality_review_state is BELT AND BRACES, not a live fix. With
  a superuser/BYPASSRLS owner it changes nothing today. It matters if ownership
  ever moves to a non-superuser role, and it makes the posture uniform so the
  enumerative invariant can assert one rule across every table instead of
  carrying an exception.

`cip_01_clients` established ENABLE + FORCE together as the canonical pattern;
`cip_119_reporting_labels` already retro-forced three tables that shipped
ENABLE-only. This is the same repair for the one that got missed (`cip_150`)
plus two that shipped with no RLS at all (`cip_164`, `cip_149`).

The gap was not invisible. `test_no_ps_table_is_rls_enabled_but_unforced` has
been failing on ps_nationality_review_state, but foundry-cip's CI has been red
since 2026-05-11, so a true finding sat inside a red suite nobody could read.
Note that test is CONDITIONAL by construction: it only catches
enabled-but-unforced, so a table shipped with NO RLS passes it silently. That is
exactly how the other two got through, and why the accompanying test change
makes the check unconditional over every table that carries tenant_id.

SAFETY, per table rather than in aggregate, because the three differ.

  ps_nationality_request_log (0 rows) and ps_readout_editions (0 rows) gain row
  security for the first time. Nothing can regress on data that is not there.
  The known consumers all set app.current_tenant already: the FAS write router
  wraps every handler in a transaction that calls set_config, and the reports
  app routes every query through its withTenant helper. A future writer must
  stamp tenant_id or the WITH CHECK will reject the insert.

  ps_nationality_review_state is NOT empty. It holds 3,320 rows and feeds
  lens_ps_china_pools then lens_ps_collection_queue, so a mistake here would
  empty the money queue rather than degrade a column. It is safe only because
  FORCE is inert against a BYPASSRLS owner (see above) and because the table was
  already ENABLEd, so the non-superuser readers were already subject to the same
  policy. This migration does not change what any existing reader sees.

Policies use the canonical NULLIF form, which returns zero rows when
app.current_tenant is unset rather than raising on a ''::uuid cast.

A consequence worth stating: ps_reporting_write_log's writer path must set
app.current_tenant before inserting into ps_nationality_request_log. That action
(`nationality.mark_requested`) is ALREADY non-functional for a separate reason,
a missing GRANT, so this changes nothing that currently works. Tracked
separately.

Revision ID: cip_176_rls_tenant_gaps
Revises: cip_175_writer_contacts
"""
from __future__ import annotations

from alembic import op

# Revision identifiers.
# NOTE: keep this id <= 32 chars. alembic_version_cip.version_num is
# VARCHAR(32) and cip_123 was renamed after a 40-char id overflowed it.
revision: str = "cip_176_rls_tenant_gaps"
down_revision: str | None = "cip_175_writer_contacts"
branch_labels: str | None = None
depends_on: str | None = None

# Tables that already have RLS + a policy and only need the owner fence closed.
_FORCE_ONLY = ("ps_nationality_review_state",)

# Tables carrying tenant_id that shipped with no row security at all.
# (policy_name, table)
_NEEDS_RLS = (
    ("ps_nationality_request_log_tenant", "ps_nationality_request_log"),
    ("ps_readout_editions_tenant", "ps_readout_editions"),
)

_POLICY_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    for table in _FORCE_ONLY:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    for policy, table in _NEEDS_RLS:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # DROP first so the migration is re-runnable against a database where a
        # policy was created out of band.
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"USING ({_POLICY_PREDICATE}) "
            f"WITH CHECK ({_POLICY_PREDICATE})"
        )

    print(
        "cip_176: forced RLS on "
        f"{len(_FORCE_ONLY)} table(s) and enabled+forced+policied "
        f"{len(_NEEDS_RLS)} previously unprotected table(s). "
        "Every table carrying tenant_id is now ENABLE + FORCE with a policy."
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    for policy, table in _NEEDS_RLS:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for table in _FORCE_ONLY:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

    print(
        "cip_176 downgrade: restored the pre-migration RLS posture "
        "(ps_nationality_review_state unforced; request_log and readout_editions "
        "without row security)."
    )
