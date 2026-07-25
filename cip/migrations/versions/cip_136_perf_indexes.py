# foundry: kind=migration domain=client-intelligence-platform
"""cip_136: perf indexes for the money-lens hot path (BE-8). INDEX-ONLY — zero doctrine cost.

Design of record: WORKBENCH/china-audit/REPORTING-BACKEND-CHECKPOINT.md §6 (BE-8 = indexes-first, matview
gated/deferred — materializing the money lenses would break BE-2's free retro-recompute).

Four money/dimension lenses independently scan + aggregate the SAME shape over ps_stripe_invoice_lines
(the money spine, ~85k rows / ~37k is_ps_base):

    WHERE is_ps_base AND wayward_brand_id IS NOT NULL AND product_id IS NOT NULL AND billing_month IS NOT NULL
    GROUP BY wayward_brand_id, product_id, billing_month   -- sum(amount) FILTER (invoice_status)

scanners: lens_ps_commission_ledger.collected, lens_ps_china_verdict.money, lens_ps_refund_allocation (x3),
lens_ps_brand_revenue.billed. The two existing indexes carry neither product_id nor the aggregated amount and
are not in GROUP BY order, so every read heap-fetches + hash-aggregates. This adds a PARTIAL COVERING index
so the pure-rollup scans become index-only GroupAggregates (no hash, no sort; the "no heap" fully lands once
autovacuum marks the hourly-synced pages all-visible), plus a per-invoice covering index for the refund
proration (its alloc CTE also joins per-invoice → a partial-index benefit, not fully index-only). (A 3rd index on ps_nationality_signals in the BE-8 draft was DROPPED after QC —
its key duplicated the existing idx_ps_nat_signals_brand and it wasn't actually covering; dead weight on
a small table.)

ADDITIVE + REVERSIBLE. No lens/table body changed → the recovery number (sum ps_claim_owed china) is
penny-identical BY CONSTRUCTION. Money stays LIVE VIEWS — this does NOT materialize anything, so BE-2's free
retro/forward rate recompute is untouched.

APPLY-TIME (Batch 5): plain CREATE INDEX (NOT CONCURRENTLY) — CONCURRENTLY cannot run inside alembic's single
migration transaction, and the table is ~85k rows so the build is sub-second. Each build takes a SHARE lock (blocks writes, allows reads), held CUMULATIVELY until the chain txn commits
(sub-second total at ~85k rows); apply behind lock_timeout=5s off the hourly Stripe-sync minute so lock
acquisition fails fast rather than queueing. RLS is unaffected (the leading tenant_id column aligns with the FORCE-RLS predicate).

Revision ID: cip_136_perf_indexes   (20 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_135_staff_rate
APPLY-TIME (not in file): export FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS="solo_kimi_k3_engine_dir".
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_136_perf_indexes"
down_revision: str | Sequence[str] | None = "cip_135_staff_rate"
branch_labels = None
depends_on = None

# (name, CREATE). IF NOT EXISTS keeps re-runs idempotent; DROP IF EXISTS on downgrade.
_INDEXES: tuple[tuple[str, str], ...] = (
    # 1. THE hot rollup. Partial (is_ps_base) + covering (amount, invoice_status), keyed in GROUP BY order
    #    → index-only GroupAggregate for ledger.collected, verdict.money, refund gross, brand_revenue.billed.
    (
        "idx_ps_stripe_lines_rollup",
        "CREATE INDEX IF NOT EXISTS idx_ps_stripe_lines_rollup ON ps_stripe_invoice_lines "
        "(tenant_id, wayward_brand_id, product_id, billing_month) "
        "INCLUDE (amount, invoice_status) WHERE is_ps_base",
    ),
    # 2. Per-invoice grouping for lens_ps_refund_allocation (groups paid lines by stripe_invoice_id).
    (
        "idx_ps_stripe_lines_invoice",
        "CREATE INDEX IF NOT EXISTS idx_ps_stripe_lines_invoice ON ps_stripe_invoice_lines "
        "(tenant_id, stripe_invoice_id) INCLUDE (amount, invoice_status, is_ps_base)",
    ),
    # (The BE-8 draft had a 3rd index on ps_nationality_signals — DROPPED after QC: its key duplicated the
    #  existing idx_ps_nat_signals_brand, it omitted the lens's evidence/asserted_by columns so it wasn't
    #  actually covering, and on the ~11k-row table the planner seq-scans regardless → pure dead weight.)
)


def upgrade() -> None:
    # Bake the lock guard into the migration (don't depend on operator memory): fail fast rather than
    # queue behind a long write if applied on a busy window. SET LOCAL scopes it to this txn.
    op.execute("SET LOCAL lock_timeout = '5s'")
    for _name, create_sql in _INDEXES:
        op.execute(create_sql)
    op.execute("ANALYZE ps_stripe_invoice_lines")
    print("cip_136: added 2 covering perf indexes on ps_stripe_invoice_lines (hot rollup + per-invoice)")


def downgrade() -> None:
    for name, _create_sql in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
