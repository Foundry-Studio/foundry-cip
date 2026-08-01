# foundry: kind=migration domain=client-intelligence-platform
"""cip_150 - ps_nationality_review_state: the "needs more info" review marker (RDL, #47).

Nationality review (#30) has a THIRD action beyond china/not_china: "need more info" - a marker that KEEPS
the brand in the review queue without asserting a nationality. It must NOT touch ps_nationality_signals:
that table's CHECK forbids a non-china/not_china points_to, and lens_ps_china_verdict reads it, so a marker
written there would corrupt the verdict (this is exactly the bounce that sent #47 back to planning). So this
is a DEDICATED, isolated review-state table - workflow state, NOT a nationality assertion. The verdict/trail
pipeline is untouched: the brand's verdict stays whatever it was, so it never leaves lens_ps_china_contention
(the review queue). The queue simply LEFT JOINs the reader lens to show a "needs info" badge.

- ps_nationality_review_state: append-only (tenant_id, wayward_brand_id, state needs_info|cleared, note,
  asserted_by, created_at). Tenant-RLS'd exactly like the other FAS-write targets (cip_128); INSERT+SELECT
  granted to ps_reporting_writer so the governed FAS need_info handler can write it. Append-only: "cleared"
  is a NEW row, latest-wins via the lens (no UPDATE/DELETE - mirrors the ps_nationality_signals convention).
- lens_ps_nationality_review_state: the latest state per brand -> the #30 queue reads this. Granted to the
  reader set (mirrors cip_149).

Additive (new table + 1 view + grants). Downgrade drops both. Revision id <=32 chars (this = 25).

Revision ID: cip_150_natl_review_state
Revises: cip_149_readout_editions
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_150_natl_review_state"
down_revision: str | Sequence[str] | None = "cip_149_readout_editions"
branch_labels = None
depends_on = None

_WRITER = "ps_reporting_writer"
_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_TABLE = r"""
CREATE TABLE IF NOT EXISTS ps_nationality_review_state (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL,
    wayward_brand_id uuid NOT NULL,
    state            text NOT NULL,                 -- needs_info | cleared
    note             text,                          -- reviewer rationale (handler requires it for needs_info)
    asserted_by      text,                          -- actor email (from the capability token)
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_natl_review_state CHECK (state IN ('needs_info', 'cleared'))
);
CREATE INDEX IF NOT EXISTS ix_natl_review_state_brand
    ON ps_nationality_review_state (wayward_brand_id, created_at DESC);
"""

# Tenant RLS, same shape as ps_nationality_signals (cip_128): the writer is NOBYPASSRLS and set_configs the
# PS tenant, so it inserts/reads only its own rows. DROP-then-CREATE the policy for a re-runnable upgrade.
_RLS = r"""
ALTER TABLE ps_nationality_review_state ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ps_nationality_review_state_tenant ON ps_nationality_review_state;
CREATE POLICY ps_nationality_review_state_tenant ON ps_nationality_review_state
    USING (tenant_id = (current_setting('app.current_tenant', true))::uuid)
    WITH CHECK (tenant_id = (current_setting('app.current_tenant', true))::uuid);
"""

# Latest state per brand -> the Nationality review queue (#30) LEFT JOINs this for the "needs info" badge.
_LENS = r"""
CREATE OR REPLACE VIEW lens_ps_nationality_review_state AS
SELECT DISTINCT ON (wayward_brand_id)
       wayward_brand_id, state, note, asserted_by, created_at
FROM ps_nationality_review_state
ORDER BY wayward_brand_id, created_at DESC;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_TABLE)
    op.execute(_RLS)
    # The governed FAS writer inserts the marker (append-only: INSERT + SELECT, never UPDATE/DELETE).
    op.execute(f"GRANT INSERT, SELECT ON ps_nationality_review_state TO {_WRITER};")
    op.execute(_LENS)
    op.execute(f"GRANT SELECT ON lens_ps_nationality_review_state TO {_READER};")
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_nationality_review_state TO {role};")
    print("cip_150: ps_nationality_review_state (RLS) + lens_ps_nationality_review_state created + granted")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_nationality_review_state;")
    op.execute("DROP TABLE IF EXISTS ps_nationality_review_state;")
