# foundry: kind=migration domain=client-intelligence-platform
"""cip_35: expression indexes for the lens_china_tickets identity join.

PM scope 58dd8272 (perf follow-up to 08b4ce7d / cip_33). lens_china_tickets
is correct but timed out >15s — purely an indexing gap on the JSONB join
keys. Indexes only; ZERO behavior change.

EXPLAIN (ANALYZE) diagnosis on prod (EcomLever GUC, 2026-05-25):
execution 15.3s. The dominant cost was a **Seq Scan on cip_tickets run
810× (956k buffer hits, 2.34M rows removed by join filter)** — the join
`il.left_source_id = tk.properties->>'requester_id'` had no index on
requester_id, so the planner seq-scanned all Zendesk tickets per outer
row. The cip_27 expression indexes (idx_cip_deals_assoc_company,
idx_cip_contacts_assoc_company) + the cip_33 identity-link indexes were
already being used; this migration does NOT duplicate them.

Two indexes added (the non-redundant set the plan needs):

1. cip_tickets (tenant_id, (properties->>'requester_id'))
   WHERE source_connector = 'zendesk-v1'
   — THE fix: turns the 810× seq-scan into an index lookup of the
     ticket(s) whose requester_id matches the resolved Zendesk contact.

2. cip_deals (tenant_id, (properties->>'source') text_pattern_ops)
   WHERE source_connector = 'hubspot-v1'
   — supports the `properties->>'source' LIKE 'China Referral%'` prefix
     scan in the china-subquery (a one-time ~80ms seq scan today). Minor
     for tickets but a broad win — the same china predicate powers every
     lens_china_* view.

3. cip_contacts (tenant_id, source_connector, source_id)
   — added after the first-pass EXPLAIN: with #1 + #2 in place the new
     dominant cost (≈770k buffers / 810 loops) was the Zendesk-contact
     lookup `zc.source_id = il.left_source_id` falling back to
     uq_cip_contacts_source (tenant_id, client_id, source_connector,
     source_id) — whose `client_id` in position 2 breaks the
     source_connector+source_id prefix, forcing a per-tenant index scan.
     A (tenant_id, source_connector, source_id) index makes that a direct
     probe (serves both the zendesk-zc and hubspot-hc source_id lookups).
     NOT redundant with the unique (different column order).

4. cip_companies (tenant_id, source_connector, source_id)
   — added after the second-pass EXPLAIN: the final brand lookup
     `co.source_id = hc.properties->>'associatedcompanyid'` hit the same
     pattern — uq_cip_companies_source has client_id in position 2, so
     the (tenant_id, source_connector, source_id) probe fell back to a
     per-tenant index-only scan (~4.5s across the loop). The dedicated
     index makes it a direct probe. (Same fix as #3, companies side.)

Deliberately NOT added (already exist, cip_27; planner uses them):
  - cip_deals ((properties->>'hs_primary_associated_company'))
  - cip_contacts ((properties->>'associatedcompanyid'))

Migration mechanics: CREATE INDEX CONCURRENTLY to avoid locking the live
cip_deals table. CONCURRENTLY cannot run inside a transaction, so the
statements run in an autocommit block and the migration is flagged
non-transactional (disable_ddl_transaction). IF NOT EXISTS makes re-runs
safe; a failed CONCURRENTLY build leaves an INVALID index that the
re-run's IF NOT EXISTS would skip — operators should DROP any invalid
index before re-applying (noted in the runbook).

Revision ID: cip_35_china_ticket_join_indexes
Revises: cip_34_ps_china_commission_lens
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_35_china_ticket_join_indexes"
down_revision: str | Sequence[str] | None = "cip_34_ps_china_commission_lens"
branch_labels = None
depends_on = None

# CONCURRENTLY can't run inside a transaction. This repo's env.py wraps
# the whole run in one begin_transaction(), so we use op.get_context()
# .autocommit_block() in upgrade()/downgrade() — it exits the outer txn,
# runs each statement in autocommit, then re-enters. (A module-level
# disable_ddl_transaction flag is NOT honored by this env, so we don't
# rely on it.)

_INDEXES = (
    (
        "idx_cip_tickets_requester_id",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cip_tickets_requester_id "
        "ON cip_tickets (tenant_id, (properties->>'requester_id')) "
        "WHERE source_connector = 'zendesk-v1' "
        "AND properties->>'requester_id' IS NOT NULL",
    ),
    (
        "idx_cip_deals_source_prefix",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cip_deals_source_prefix "
        "ON cip_deals (tenant_id, (properties->>'source') text_pattern_ops) "
        "WHERE source_connector = 'hubspot-v1' "
        "AND properties->>'source' IS NOT NULL",
    ),
    (
        "idx_cip_contacts_tenant_conn_source",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cip_contacts_tenant_conn_source "
        "ON cip_contacts (tenant_id, source_connector, source_id)",
    ),
    (
        "idx_cip_companies_tenant_conn_source",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cip_companies_tenant_conn_source "
        "ON cip_companies (tenant_id, source_connector, source_id)",
    ),
)


def upgrade() -> None:
    # autocommit_block: each CONCURRENTLY runs in its own autocommit txn.
    with op.get_context().autocommit_block():
        for _name, ddl in _INDEXES:
            op.execute(ddl)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _ddl in _INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
