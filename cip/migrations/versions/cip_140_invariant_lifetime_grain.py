# foundry: kind=migration domain=client-intelligence-platform
"""cip_140 — re-grain the two fee invariants to brand x product LIFETIME (the -$3.06 edge).

CLEAN-BUILD-PLAN.md Phase 1.5a; ruled Option B by Tim 2026-07-29 (RDL 90cf3929).

THE EDGE: 9 (brand x product x month) ledger cells net a negative usage_collected from LEGITIMATE
standalone Wayward usage-reconciliation credit LINES ("Attribution Reconciliation Usage",
"Associates Usage Fee" corrections, "ACC Bonus Reconciliation"): -$12,595 of such base credits
exist, almost all netting POSITIVE within their own month against fresh usage; only $3.06 spills
into 9 net-negative cells. On those cells mgmt_fee_owed < 0, tripping the PER-ROW invariants
mgmt_fee_nonneg + partner_le_mgmt (cip_125). Because `invariants_clean` is a HARD, GLOBAL close
gate (cip_138/139), those 9 cells wedge EVERY month-close today.

THE FIX (Option B): a monthly cell CAN legitimately net a usage credit — the per-ROW
non-negativity assumption is the false positive, not the data. So re-grain ONLY those two
invariants to check the SUM per (wayward_brand_id, product_id) at LIFETIME: mgmt_fee >= 0 and
partner_fee <= mgmt_fee over the brand's whole life. The monthly ledger is UNTOUCHED (monthly
figures stay honest cash for the R5 status model + the R10 tie-out; no money moves). Option A
(backward absorption) was rejected: it distorts the status model + R10 AND re-rates credits at the
down-stepping 10/6/3 fee tier.

CORRECTNESS AT BOTH ENDS: the re-grained check stops firing on a benign monthly credit but STILL
fires on a genuinely negative-LIFETIME fee (a real anomaly, e.g. a claimable brand fully refunded)
— that is the exceptions route, not a hole. PROBED 2026-07-29: 0 brand x product have negative
lifetime mgmt_fee and 0 have lifetime partner > mgmt today, so this ships clean.

Live-lens REPLACE of lens_ps_invariants (a health lens; NOT on live-read-lenses.md, no money
consumer beyond the gate). The other 4 invariants (claimable_is_china, rate_ladder_domain,
claim_floor, ledger_grain_unique) are PRESERVED byte-for-byte. Downgrade restores the cip_125 body
verbatim (captured below). Grants unchanged (the view keeps cip_125's grants).

Revision ID: cip_140_invariant_lifetime_grain (33 chars -> TRUNCATE check: alembic_version is
VARCHAR(32), so the id MUST be <= 32; using cip_140_invariant_lifetime = 26 chars.)
Revises: cip_139_signals_materialize
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_140_invariant_lifetime"
down_revision: str | Sequence[str] | None = "cip_139_signals_materialize"
branch_labels = None
depends_on = None

# The re-grained view. ONLY mgmt_fee_nonneg + partner_le_mgmt change (per-row -> per brand x product
# lifetime SUM); the other 4 invariants are copied verbatim from cip_125.
_INVARIANTS_V2 = r"""
CREATE OR REPLACE VIEW lens_ps_invariants AS
WITH life AS (
    SELECT wayward_brand_id, product_id,
           sum(mgmt_fee_owed)    AS life_mgmt,
           sum(partner_fee_owed) AS life_partner
    FROM lens_ps_commission_ledger
    GROUP BY wayward_brand_id, product_id
),
inv AS (
    -- RE-GRAINED (cip_140): fee non-negativity is a LIFETIME truth per brand x product, not per
    -- month — a monthly cell may net a legitimate usage-reconciliation credit.
    SELECT 'invariant.mgmt_fee_nonneg'::text AS check_key, 'ledger'::text AS category,
           'Management fee never negative (brand x product lifetime)'::text AS label,
           count(*) FILTER (WHERE life_mgmt < 0) AS violations, count(*) AS total,
           'lens_ps_commission_ledger'::text AS source
    FROM life
    UNION ALL
    SELECT 'invariant.partner_le_mgmt', 'partner', 'Partner cut never exceeds our fee (lifetime)',
           count(*) FILTER (WHERE life_partner > life_mgmt + 0.01), count(*),
           'lens_ps_commission_ledger'
    FROM life
    UNION ALL
    -- PRESERVED verbatim from cip_125 (per-row; these are not affected by monthly credits):
    SELECT 'invariant.claimable_is_china', 'nationality', 'Claimable implies china verdict',
           count(*) FILTER (WHERE claimable AND verdict IS DISTINCT FROM 'china'), count(*),
           'lens_ps_commission_ledger'
    FROM lens_ps_commission_ledger
    UNION ALL
    SELECT 'invariant.rate_ladder_domain', 'ledger', 'Rate on the 10/6/3 ladder',
           count(*) FILTER (WHERE mgmt_rate IS NOT NULL AND mgmt_rate NOT IN (0.03,0.06,0.10)), count(*),
           'lens_ps_commission_ledger'
    FROM lens_ps_commission_ledger
    UNION ALL
    SELECT 'invariant.claim_floor', 'ledger', 'Claim floored at zero',
           count(*) FILTER (WHERE abs(ps_claim_owed - GREATEST(mgmt_fee_owed - wayward_paid, 0)) > 0.01), count(*),
           'lens_ps_claim'
    FROM lens_ps_claim
    UNION ALL
    SELECT 'invariant.ledger_grain_unique', 'ledger', 'Ledger grain unique (brand×product×month)',
           (SELECT count(*) FROM (SELECT 1 FROM lens_ps_commission_ledger
              GROUP BY wayward_brand_id, product_id, period_month HAVING count(*) > 1) d),
           (SELECT count(*) FROM lens_ps_commission_ledger),
           'lens_ps_commission_ledger'
)
SELECT check_key, 'invariant'::text AS check_type, category, label,
       (total - violations) AS passed, total, violations AS failed,
       CASE WHEN total = 0 THEN NULL ELSE round(100.0 * (total - violations) / total, 1) END AS pct,
       CASE WHEN violations = 0 THEN 'ok' ELSE 'fail' END AS status,
       source AS detail
FROM inv;
"""

# The exact cip_125 body, restored on downgrade (per-row mgmt_fee_nonneg + partner_le_mgmt).
_INVARIANTS_V1 = r"""
CREATE OR REPLACE VIEW lens_ps_invariants AS
WITH inv AS (
    SELECT 'invariant.mgmt_fee_nonneg'::text AS check_key, 'ledger'::text AS category,
           'Management fee never negative'::text AS label,
           count(*) FILTER (WHERE mgmt_fee_owed < 0) AS violations, count(*) AS total,
           'lens_ps_commission_ledger'::text AS source
    FROM lens_ps_commission_ledger
    UNION ALL
    SELECT 'invariant.claimable_is_china', 'nationality', 'Claimable implies china verdict',
           count(*) FILTER (WHERE claimable AND verdict IS DISTINCT FROM 'china'), count(*),
           'lens_ps_commission_ledger'
    FROM lens_ps_commission_ledger
    UNION ALL
    SELECT 'invariant.rate_ladder_domain', 'ledger', 'Rate on the 10/6/3 ladder',
           count(*) FILTER (WHERE mgmt_rate IS NOT NULL AND mgmt_rate NOT IN (0.03,0.06,0.10)), count(*),
           'lens_ps_commission_ledger'
    FROM lens_ps_commission_ledger
    UNION ALL
    SELECT 'invariant.partner_le_mgmt', 'partner', 'Partner cut never exceeds our fee',
           count(*) FILTER (WHERE partner_fee_owed > mgmt_fee_owed + 0.01), count(*),
           'lens_ps_commission_ledger'
    FROM lens_ps_commission_ledger
    UNION ALL
    SELECT 'invariant.claim_floor', 'ledger', 'Claim floored at zero',
           count(*) FILTER (WHERE abs(ps_claim_owed - GREATEST(mgmt_fee_owed - wayward_paid, 0)) > 0.01), count(*),
           'lens_ps_claim'
    FROM lens_ps_claim
    UNION ALL
    SELECT 'invariant.ledger_grain_unique', 'ledger', 'Ledger grain unique (brand×product×month)',
           (SELECT count(*) FROM (SELECT 1 FROM lens_ps_commission_ledger
              GROUP BY wayward_brand_id, product_id, period_month HAVING count(*) > 1) d),
           (SELECT count(*) FROM lens_ps_commission_ledger),
           'lens_ps_commission_ledger'
)
SELECT check_key, 'invariant'::text AS check_type, category, label,
       (total - violations) AS passed, total, violations AS failed,
       CASE WHEN total = 0 THEN NULL ELSE round(100.0 * (total - violations) / total, 1) END AS pct,
       CASE WHEN violations = 0 THEN 'ok' ELSE 'fail' END AS status,
       source AS detail
FROM inv;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_INVARIANTS_V2)
    print("cip_140: re-grained mgmt_fee_nonneg + partner_le_mgmt to brand x product lifetime")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_INVARIANTS_V1)
