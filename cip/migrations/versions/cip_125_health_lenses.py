# foundry: kind=migration domain=client-intelligence-platform
"""cip_125: reporting lenses — lens_ps_coverage + lens_ps_invariants for Data Health.

The reporting Data Health screen (REPORTING-REBUILD-PLAN §7.1 — the shipped Freshness
extended) needs two dimensions the reader can't compute today: data-COVERAGE % and
INVARIANT status. Both are exposed as read-only views granted to ps_reporting_reader.
The third dimension (heartbeat/mode freshness) reuses the shipped lens_ps_source_freshness.

Two lenses (not one UNION): coverage status is a BAND (a 60%-ruled book is a healthy
"warn", not a defect) while an invariant is BINARY (any violation is an engine bug) —
different semantics, so they get different lenses. The reporting DAL composes both in one
round-trip. (Deliberately NOT adding lens_ps_information_gaps — §6.1 G1 is closed:
lens_ps_open_questions already covers the ask-queue; a row-level gaps lens, if ever needed,
is an Exceptions §7.8 item, not Data Health.)

INVARIANTS police the money engine (MATH-SPEC §5), evaluated live:
  1 mgmt_fee_nonneg    mgmt_fee_owed >= 0                         (lens_ps_commission_ledger)
  2 claimable_is_china claimable ⇒ verdict='china'                (…) — IS DISTINCT FROM catches NULL
  3 rate_ladder_domain mgmt_rate ∈ {0.03,0.06,0.10}              (…) — strict, no 0
  4 partner_le_mgmt    partner_fee_owed <= mgmt_fee_owed          (…) — a fail = investigate the engine
  5 claim_floor        ps_claim_owed = GREATEST(mgmt-paid, 0)     (lens_ps_claim, ±0.01 rounding tol)
  6 ledger_grain_unique  one row per brand×product×month         (lens_ps_commission_ledger)

Verified live 2026-07-22 (dry-run before build): coverage nationality 59.8% / fee_rate
54.3% (whole-PS, the real gap) / contacts 46.3%; invariants 4/6 clean, mgmt_fee_nonneg +
partner_le_mgmt each show 9 violations (9 tiny negative-usage_collected cells, −$3.06 mgmt
total; the claim-floor invariant passes so the headline recovery is unaffected — a surfaced
engine edge, not a lens bug).

Additive + reversible; runs as owner.

Revision ID: cip_125_health_lenses
Revises: cip_124_refund_events

(Revision id kept short — alembic_version_cip is VARCHAR(32); this = 21 chars.)
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_125_health_lenses"
down_revision: str | Sequence[str] | None = "cip_124_refund_events"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"


def upgrade() -> None:
    # --- Coverage: data-completeness bands (ok >= 90% / warn >= 50% / fail) ---
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_coverage AS
        WITH cov AS (
          SELECT 'coverage.nationality'::text AS check_key, 'nationality'::text AS category,
                 'Nationality ruled'::text AS label,
                 count(*) FILTER (WHERE verdict IN ('china','not_china')) AS passed,
                 count(*) AS total,
                 'Brands with a china/not-china ruling; the rest are unknown (queued, never denied)'::text AS detail
          FROM lens_ps_china_verdict
          UNION ALL
          SELECT 'coverage.fee_rate', 'billing', 'Client fee-rate resolved',
                 count(*) FILTER (WHERE NOT rate_missing), count(*),
                 'Revenue rows (all PS) with a client fee-rate — feeds derived GMV/ad-spend, NOT the money claim'
          FROM lens_ps_brand_revenue
          UNION ALL
          SELECT 'coverage.contacts', 'contacts', 'China brands with a contact',
                 (SELECT count(DISTINCT c.wayward_brand_id)
                    FROM lens_ps_brand_contact_book c
                    JOIN (SELECT wayward_brand_id FROM lens_ps_china_verdict WHERE verdict='china') ch
                      USING (wayward_brand_id)
                    WHERE nullif(c.email,'') IS NOT NULL
                       OR nullif(c.phone,'') IS NOT NULL
                       OR nullif(c.wechat_id,'') IS NOT NULL),
                 (SELECT count(*) FROM lens_ps_china_verdict WHERE verdict='china'),
                 'Distinct china brands with an email, phone or WeChat on file'
        )
        SELECT check_key, 'coverage'::text AS check_type, category, label,
               passed, total, (total - passed) AS failed,
               CASE WHEN total = 0 THEN NULL ELSE round(100.0 * passed / total, 1) END AS pct,
               CASE WHEN total = 0 THEN 'ok'
                    WHEN passed::numeric / total >= 0.90 THEN 'ok'
                    WHEN passed::numeric / total >= 0.50 THEN 'warn'
                    ELSE 'fail' END AS status,
               detail
        FROM cov;
        """
    )

    # --- Invariants: MATH-SPEC §5 engine police (binary: any violation = fail) ---
    op.execute(
        """
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
    )

    op.execute(f'GRANT SELECT ON lens_ps_coverage TO {_READER};')
    op.execute(f'GRANT SELECT ON lens_ps_invariants TO {_READER};')
    print(f"cip_125: created + granted lens_ps_coverage, lens_ps_invariants to {_READER}")


def downgrade() -> None:
    op.execute('DROP VIEW IF EXISTS lens_ps_coverage;')
    op.execute('DROP VIEW IF EXISTS lens_ps_invariants;')
