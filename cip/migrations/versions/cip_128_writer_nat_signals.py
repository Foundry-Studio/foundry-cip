# foundry: kind=migration domain=client-intelligence-platform
"""cip_128: correct the ps_reporting_writer nationality grant — ps_nationality_signals, not ps_added_facts.

cip_127 followed the FAS-WRITE-CONTRACT spec, which named ps_added_facts as the nationality.rule target.
Verified against the LIVE code: lens_ps_china_verdict (which flips claim eligibility) reads
ps_nationality_signals (signal='manual_review', points_to=china/not_china) — NOT ps_added_facts. All 1,195
existing human rulings live in ps_nationality_signals and persist through the harvest; ps_added_facts is a
separate/older mechanism the verdict does not read. So a ruling written to ps_added_facts would be a silent
no-op. This migration moves the grant to the table that actually takes effect.

  GRANT  INSERT, SELECT ON ps_nationality_signals TO ps_reporting_writer  (the real, effective target)
  REVOKE INSERT, SELECT ON ps_added_facts         FROM ps_reporting_writer (spec-wrong, unused → least-priv)

ps_nationality_signals is forced-RLS on app.current_tenant (same as the other targets), so the FAS handler
sets_config the PS tenant and inserts tenant_id = PS. Append-only by convention (§11.5); no UPDATE/DELETE.

Revision ID: cip_128_writer_nat_signals
Revises: cip_127_reporting_writer
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_128_writer_nat_signals"
down_revision: str | Sequence[str] | None = "cip_127_reporting_writer"
branch_labels = None
depends_on = None

_ROLE = "ps_reporting_writer"


def upgrade() -> None:
    op.execute(f"GRANT INSERT, SELECT ON ps_nationality_signals TO {_ROLE};")
    op.execute(f"REVOKE INSERT, SELECT ON ps_added_facts FROM {_ROLE};")
    print(f"cip_128: {_ROLE} nationality target corrected to ps_nationality_signals (revoked ps_added_facts)")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT, SELECT ON ps_nationality_signals FROM {_ROLE};")
    op.execute(f"GRANT INSERT, SELECT ON ps_added_facts TO {_ROLE};")
