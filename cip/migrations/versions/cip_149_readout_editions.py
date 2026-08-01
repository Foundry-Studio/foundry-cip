# foundry: kind=migration domain=client-intelligence-platform
"""cip_149 — readout editions store + reader lenses (RDL 1.5c back-end, WRITER-STUBBED).

The STORAGE + READ side of the readouts (readback) capability. The WRITER (the FAS agent that
generates + audits + files editions) is deliberately OUT of scope here (Tim 2026-08-01: it will be
built with real FAS agents in a separate conversation). This migration only creates the slots the app
reads and the agent will later write. With no writer, the reader lenses return nothing and the app's
masthead readback slot renders empty (screen-intent §0.5: the page renders without a readback) - it
lights up the moment an edition is filed.

Model (Tim 2026-08-01):
- ps_readout_editions: one row per (surface, role, grain, generated_at) carrying the 4 SECTIONS in one
  row - short_en / long_en / short_zh / long_zh - plus model/run_id/status. surface in
  home|operations|partners; role ops|cs|all; grain daily|monthly.
- lens_ps_readout_current: the latest FILED daily edition per (surface, role) = what the masthead reads,
  with generated_at for the "last updated N ago" indicator (turns red past ~14h, app-side).
- lens_ps_readout_history: the HOT WINDOW for an agent look-back = the last 35 DAYS of full daily editions
  (all 4 sections) PLUS the rolling ~2 MONTHLY summary editions. 35d (not 14) so a month-review always has
  the full current month; monthlies give month-over-month. Older raw editions age out (the agents log their
  own runs = the deep archive; nothing bespoke here).

Additive (new table + 2 views + grants). Downgrade drops all three. Revision ID <=32 chars.

Revision ID: cip_149_readout_editions
Revises: cip_148_r10_line_grain
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_149_readout_editions"
down_revision: str | Sequence[str] | None = "cip_148_r10_line_grain"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_TABLE = r"""
CREATE TABLE IF NOT EXISTS ps_readout_editions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL,
    surface       text NOT NULL,                 -- home | operations | partners
    role          text NOT NULL DEFAULT 'all',   -- ops | cs | all (role-swapped surfaces differ)
    grain         text NOT NULL DEFAULT 'daily',  -- daily | monthly
    period        date,                           -- the reporting period the readout covers
    generated_at  timestamptz NOT NULL,           -- the as-of / time-slot the run produced it
    short_en      text,
    long_en       text,
    short_zh      text,
    long_zh       text,
    model         text,                           -- which model produced it (writer-owned; null while stubbed)
    run_id        text,                           -- the FAS run id (writer-owned; null while stubbed)
    status        text NOT NULL DEFAULT 'filed',  -- draft | filed (only filed is read)
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_readout_surface CHECK (surface IN ('home', 'operations', 'partners')),
    CONSTRAINT ck_readout_role    CHECK (role IN ('ops', 'cs', 'all')),
    CONSTRAINT ck_readout_grain   CHECK (grain IN ('daily', 'monthly')),
    CONSTRAINT ck_readout_status  CHECK (status IN ('draft', 'filed'))
);
CREATE INDEX IF NOT EXISTS ix_readout_editions_lookup
    ON ps_readout_editions (surface, role, grain, generated_at DESC);
"""

# Latest FILED daily edition per (surface, role) -> the masthead reads this + generated_at.
_LENS_CURRENT = r"""
CREATE VIEW lens_ps_readout_current AS
SELECT DISTINCT ON (surface, role)
       surface, role, grain, period, generated_at,
       short_en, long_en, short_zh, long_zh, model, run_id
FROM ps_readout_editions
WHERE status = 'filed' AND grain = 'daily'
ORDER BY surface, role, generated_at DESC;
"""

# Hot window for an agent look-back: last 35 days of full daily editions + rolling ~2 monthly summaries.
_LENS_HISTORY = r"""
CREATE VIEW lens_ps_readout_history AS
SELECT surface, role, grain, period, generated_at,
       short_en, long_en, short_zh, long_zh, model, run_id
FROM ps_readout_editions
WHERE status = 'filed'
  AND (
        (grain = 'daily'   AND generated_at > (now() - interval '35 days'))
     OR (grain = 'monthly' AND period       > (date_trunc('month', now())::date - interval '2 months'))
      )
ORDER BY surface, role, generated_at DESC;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_TABLE)
    op.execute(_LENS_CURRENT)
    op.execute(_LENS_HISTORY)
    for lens in ("lens_ps_readout_current", "lens_ps_readout_history"):
        op.execute(f"GRANT SELECT ON {lens} TO {_READER};")
        for role in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {lens} TO {role};")
    print("cip_149: ps_readout_editions + lens_ps_readout_current/history created + granted (writer stubbed)")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_readout_history;")
    op.execute("DROP VIEW IF EXISTS lens_ps_readout_current;")
    op.execute("DROP TABLE IF EXISTS ps_readout_editions;")
