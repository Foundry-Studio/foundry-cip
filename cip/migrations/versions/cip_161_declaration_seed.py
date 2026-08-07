"""cip_161 declaration status seed (CDP BE-4)

Two moves, in order:
  1. Widen ck_natl_review_state to admit the declaration vocabulary. It currently allows only
     ('needs_info','cleared'); add 'investigate','declared_china','declared_not','request_sent'.
     Additive on an ENUM-by-CHECK column, run on 0 rows so the ACCESS EXCLUSIVE lock is instant.
  2. Seed OUR formal declaration state from lens_ps_china_verdict, one row per brand:
     china -> declared_china, not_china -> declared_not, and unknown WITH usable evidence
     (billed or has china_evidence, and not excluded) -> investigate. Evidence-less unknowns stay
     un-declared (no row -> in no pool). Idempotent: NOT EXISTS guard skips any brand that already
     has a review-state row, so re-runs and later human declares are never clobbered.

Grounded 2026-08-06 against prod: verdict lens = 5,445 brands, one row each (no multi-verdict brand),
so DISTINCT ON is a safety no-op. Expected seed = declared_china 2,362 + declared_not 878 +
investigate 80 = 3,320. Silk tenant + the exact constraint name confirmed from live catalog.

Downgrade removes ONLY the seeded rows (by asserted_by); it deliberately does NOT narrow the CHECK
back, because by then human declares in the new states may exist and narrowing would reject them.

Revision ID: cip_161_declaration_seed
Revises: cip_160_wayward_indicators
Create Date: 2026-08-06
"""
from alembic import op

revision = "cip_161_declaration_seed"
down_revision = "cip_160_wayward_indicators"
branch_labels = None
depends_on = None

_SEED = """
INSERT INTO ps_nationality_review_state (tenant_id, wayward_brand_id, state, asserted_by)
SELECT '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid, d.wayward_brand_id, d.state,
       'system:cip_161_declaration_seed'
FROM (
    SELECT DISTINCT ON (wayward_brand_id)
        wayward_brand_id,
        CASE
            WHEN verdict = 'china'     THEN 'declared_china'
            WHEN verdict = 'not_china' THEN 'declared_not'
            WHEN verdict = 'unknown'
                 AND NOT COALESCE(is_excluded, false)
                 AND (ever_billed OR COALESCE(china_evidence, '') <> '') THEN 'investigate'
        END AS state
    FROM lens_ps_china_verdict
    WHERE wayward_brand_id IS NOT NULL
    ORDER BY wayward_brand_id, verdict
) d
WHERE d.state IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM ps_nationality_review_state s
      WHERE s.wayward_brand_id = d.wayward_brand_id
        AND s.tenant_id = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid
  )
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE ps_nationality_review_state DROP CONSTRAINT IF EXISTS ck_natl_review_state")
    op.execute(
        "ALTER TABLE ps_nationality_review_state ADD CONSTRAINT ck_natl_review_state "
        "CHECK (state IN ('needs_info','cleared','investigate','declared_china','declared_not','request_sent'))"
    )
    op.execute(_SEED)


def downgrade() -> None:
    # Remove ONLY the seeded rows; leave the widened CHECK in place (human declares may now use it).
    op.execute(
        "DELETE FROM ps_nationality_review_state WHERE asserted_by = 'system:cip_161_declaration_seed'"
    )
