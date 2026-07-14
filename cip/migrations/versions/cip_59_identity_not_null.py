# foundry: kind=migration domain=client-intelligence-platform
"""cip_59: stop REQUIRING the surrogate and PERMITTING the identity to be missing.

THE INVERSION
-------------
Three tables that money flows through were declared like this:

    client_id         NOT NULL     -- the cip_clients surrogate. Covers ~65% of brands.
    wayward_brand_id  NULL         -- the real identity. Covers 99.9% of billed lines.

The schema REQUIRED the weak key and PERMITTED the strong one to be absent. That is backwards,
and it is the structural root of every money bug in this audit — not a symptom of them:

  * a brand with no cip_clients row could not be inserted at all, so it could not hold a
    productive date, so it had no rate, so it earned nothing. $1.25M of collected usage fees
    sat unpriced for exactly this reason. Nothing errored. The brand simply could not exist.

  * rebuilding the money spine on the correct key (wayward_brand_id) fails outright against
    this constraint: "null value in column client_id violates not-null constraint". The
    schema was actively preventing the fix.

So: client_id becomes nullable — it is a convenience join, and always was. And a CHECK now
requires that every row carry AT LEAST ONE identity, so "nullable" does not decay into "a row
nobody can name".

WHY NOT wayward_brand_id NOT NULL OUTRIGHT
------------------------------------------
27 rows in ps_partner_credit, 27 in ps_attribution and 1 in ps_product_subscriptions have a
client_id but no brand id — legacy rows for clients that never got a Wayward brand id. Forcing
NOT NULL would mean deleting them, and they carry real partner attribution. They are kept,
nameable by client_id, and the CHECK holds the line: a row must have SOME identity, never none.

Revision ID: cip_59_identity_not_null
Revises: cip_58_data_dictionary
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_59_identity_not_null"
down_revision: str | Sequence[str] | None = "cip_58_data_dictionary"
branch_labels = None
depends_on = None

_TABLES = ("ps_product_subscriptions", "ps_partner_credit", "ps_attribution")


def upgrade() -> None:
    for tbl in _TABLES:
        op.execute(f"ALTER TABLE {tbl} ALTER COLUMN client_id DROP NOT NULL")
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS ck_{tbl}_has_identity")
        op.execute(
            f"""
            ALTER TABLE {tbl} ADD CONSTRAINT ck_{tbl}_has_identity CHECK (
                wayward_brand_id IS NOT NULL OR client_id IS NOT NULL
            )
            """
        )
        op.execute(
            f"COMMENT ON CONSTRAINT ck_{tbl}_has_identity ON {tbl} IS "
            f"'Every row must be nameable by SOMETHING. client_id was NOT NULL and "
            f"wayward_brand_id was nullable — the schema required the weak key (65%% coverage) "
            f"and permitted the real one (99.9%%) to be absent, which is why brands outside "
            f"cip_clients could not hold a productive date and priced to nothing. Inverted here. "
            f"wayward_brand_id is not itself NOT NULL only because a handful of legacy rows "
            f"carry real partner attribution for clients Wayward never issued a brand id for, "
            f"and deleting them to satisfy a constraint would destroy evidence.'"
        )


def downgrade() -> None:
    for tbl in _TABLES:
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS ck_{tbl}_has_identity")
        # Restoring NOT NULL would fail on any row written since — which is the point of the
        # migration. Delete the unnameable-by-client rows first if you truly must go back.
        op.execute(
            f"DELETE FROM {tbl} WHERE client_id IS NULL"
        )
        op.execute(f"ALTER TABLE {tbl} ALTER COLUMN client_id SET NOT NULL")
