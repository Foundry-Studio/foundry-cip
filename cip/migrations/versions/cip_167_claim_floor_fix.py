# foundry: kind=migration domain=client-intelligence-platform
"""cip_167: fix the claim_floor invariant to mirror the lens's actual floor.

lens_ps_claim floors the claim as GREATEST(mgmt_fee_owed - GREATEST(wayward_paid, 0), 0):
the inner GREATEST(wayward_paid, 0) stops a NEGATIVE net Wayward payment (refund-netting
dust) from inflating the claim. The claim_floor invariant in lens_ps_invariants re-derived
the floor WITHOUT that inner GREATEST -- GREATEST(mgmt_fee_owed - wayward_paid, 0) -- so on
any brand with a refund-driven negative wayward_paid it expected a phantom positive claim
and flagged the (correct) lens for not matching. 3 brands (BESTMOW -2.70, 100FIXEO -0.14,
somiliss -0.03; all mgmt_fee_owed = 0, served claim correctly 0) tripped it, and because
invariants_clean is a GLOBAL hard close gate, those 3 rows wedged all 27 periods into
`blocked`. No money figure is wrong -- the served claim is already correct; this fixes the
CHECK to use the same formula the lens uses. After this, claim_floor = ok and /close stops
reading all-red. CREATE OR REPLACE VIEW preserves grants.

Revision ID: cip_167_claim_floor_fix
Revises: cip_166_china_lens_hubspot
"""
from __future__ import annotations

from alembic import op

revision: str = "cip_167_claim_floor_fix"
down_revision: str | None = "cip_166_china_lens_hubspot"
branch_labels = None
depends_on = None


def _view(claim_floor_filter: str) -> str:
    return f"""CREATE OR REPLACE VIEW lens_ps_invariants AS
 WITH life AS (
   SELECT wayward_brand_id, product_id,
     sum(mgmt_fee_owed) AS life_mgmt,
     sum(partner_fee_owed) AS life_partner
   FROM lens_ps_commission_ledger
   GROUP BY wayward_brand_id, product_id
 ), inv AS (
   SELECT 'invariant.mgmt_fee_nonneg'::text AS check_key,
     'ledger'::text AS category,
     'Management fee never negative (brand x product lifetime)'::text AS label,
     count(*) FILTER (WHERE life.life_mgmt < 0::numeric) AS violations,
     count(*) AS total,
     'lens_ps_commission_ledger'::text AS source
   FROM life
   UNION ALL
   SELECT 'invariant.partner_le_mgmt'::text, 'partner'::text,
     'Partner cut never exceeds our fee (lifetime)'::text,
     count(*) FILTER (WHERE life.life_partner > (life.life_mgmt + 0.01)),
     count(*), 'lens_ps_commission_ledger'::text
   FROM life
   UNION ALL
   SELECT 'invariant.claimable_is_china'::text, 'nationality'::text,
     'Claimable implies china verdict'::text,
     count(*) FILTER (WHERE lens_ps_commission_ledger.claimable AND lens_ps_commission_ledger.verdict IS DISTINCT FROM 'china'::text),
     count(*), 'lens_ps_commission_ledger'::text
   FROM lens_ps_commission_ledger
   UNION ALL
   SELECT 'invariant.rate_ladder_domain'::text, 'ledger'::text,
     'Rate on the 10/6/3 ladder'::text,
     count(*) FILTER (WHERE lens_ps_commission_ledger.mgmt_rate IS NOT NULL AND (lens_ps_commission_ledger.mgmt_rate <> ALL (ARRAY[0.03, 0.06, 0.10]))),
     count(*), 'lens_ps_commission_ledger'::text
   FROM lens_ps_commission_ledger
   UNION ALL
   SELECT 'invariant.claim_floor'::text, 'ledger'::text,
     'Claim floored at zero'::text,
     count(*) FILTER (WHERE {claim_floor_filter}),
     count(*), 'lens_ps_claim'::text
   FROM lens_ps_claim
   UNION ALL
   SELECT 'invariant.ledger_grain_unique'::text, 'ledger'::text,
     'Ledger grain unique (brand×product×month)'::text,
     (SELECT count(*) FROM (SELECT 1 FROM lens_ps_commission_ledger GROUP BY wayward_brand_id, product_id, period_month HAVING count(*) > 1) d),
     (SELECT count(*) FROM lens_ps_commission_ledger),
     'lens_ps_commission_ledger'::text
 )
 SELECT check_key,
   'invariant'::text AS check_type,
   category, label,
   total - violations AS passed,
   total,
   violations AS failed,
   CASE WHEN total = 0 THEN NULL::numeric ELSE round(100.0 * (total - violations)::numeric / total::numeric, 1) END AS pct,
   CASE WHEN violations = 0 THEN 'ok'::text ELSE 'fail'::text END AS status,
   source AS detail
 FROM inv"""


# FIXED: the claim_floor check mirrors the lens's flooring (inner GREATEST on wayward_paid).
_FIXED_FILTER = "abs(lens_ps_claim.ps_claim_owed - GREATEST(lens_ps_claim.mgmt_fee_owed - GREATEST(lens_ps_claim.wayward_paid, 0::numeric), 0::numeric)) > 0.01"

# PRIOR: the original check, missing the inner GREATEST (the bug) -- restored on downgrade.
_PREV_FILTER = "abs(lens_ps_claim.ps_claim_owed - GREATEST(lens_ps_claim.mgmt_fee_owed - lens_ps_claim.wayward_paid, 0::numeric)) > 0.01"


def upgrade() -> None:
    op.execute(_view(_FIXED_FILTER))


def downgrade() -> None:
    op.execute(_view(_PREV_FILTER))
