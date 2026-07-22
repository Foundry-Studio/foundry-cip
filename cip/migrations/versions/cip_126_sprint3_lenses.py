# foundry: kind=migration domain=client-intelligence-platform
"""cip_126: reporting lenses — lens_ps_brand_header (G6) + lens_ps_statements_history (G7).

Gates the Sprint-3 reporting screens (REPORTING-REBUILD-PLAN §6.1 G6/G7). Two read-only
views granted to ps_reporting_reader:

G6 lens_ps_brand_header — one row per brand (ps_brands ⨝ china_verdict ⨝ exclusion_status ⨝
   product_eligibility): name, signup, nationality verdict + strength + conflict, excluded
   status + buckets + takeable, partner + rate. The header band for Brand 360 (§7.7). Verified
   1:1 (5,396 rows = ps_brands; the partner join is DISTINCT ON so it can't fan out).

G7 lens_ps_statements_history — a thin view over ps_claim_statements (the pinned statements handed
   to Wayward), grain = one row PER STATEMENT PER BRAND: label, generated_at, the pinned
   mgmt/paid/claim figures, notes. Brand 360 filters it by wayward_brand_id; the Statements
   "what was sent" screen aggregates it by statement_label in the DAL (one row per statement batch
   with a brand count + total — the reporting DAL groups, not the lens). 0 rows today (no statement
   pinned yet) — screens render an empty state. The pinned-vs-live DRIFT stays on the existing
   lens_ps_statement_drift; the WRITE path (pinning) goes through the FAS API (§10.1), NEVER the
   reader role — this lens is read-only.

Additive + reversible; runs as owner. Verified live 2026-07-22.

Revision ID: cip_126_sprint3_lenses
Revises: cip_125_health_lenses

(Revision id kept short — alembic_version_cip is VARCHAR(32); this = 23 chars.)
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_126_sprint3_lenses"
down_revision: str | Sequence[str] | None = "cip_125_health_lenses"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_brand_header AS
        SELECT
          b.wayward_brand_id,
          b.brand_name,
          b.signup_date,
          b.signup_date_source,
          b.first_seen_at,
          b.canonical_brand_id,
          cv.verdict,
          cv.verdict_strength,
          cv.has_conflict,
          cv.manual_rationale,
          es.is_excluded,
          es.buckets            AS excluded_buckets,
          es.takeable,
          es.someone_else_earning,
          pe.partner_name,
          pe.partner_rate_pct
        FROM ps_brands b
        LEFT JOIN lens_ps_china_verdict cv   ON cv.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN lens_ps_exclusion_status es ON es.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN (
          SELECT DISTINCT ON (wayward_brand_id) wayward_brand_id, partner_name, partner_rate_pct
          FROM lens_ps_product_eligibility
          WHERE partner_name IS NOT NULL
          ORDER BY wayward_brand_id, partner_rate_pct DESC NULLS LAST
        ) pe ON pe.wayward_brand_id = b.wayward_brand_id;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_statements_history AS
        SELECT
          id AS statement_id,
          statement_label,
          generated_at,
          wayward_brand_id,
          brand_name,
          verdict,
          ownership,
          mgmt_fee_owed,
          wayward_paid,
          ps_claim_owed,
          as_of_note,
          source_ref
        FROM ps_claim_statements;
        """
    )

    op.execute(f'GRANT SELECT ON lens_ps_brand_header TO {_READER};')
    op.execute(f'GRANT SELECT ON lens_ps_statements_history TO {_READER};')
    print(f"cip_126: created + granted lens_ps_brand_header, lens_ps_statements_history to {_READER}")


def downgrade() -> None:
    op.execute('DROP VIEW IF EXISTS lens_ps_brand_header;')
    op.execute('DROP VIEW IF EXISTS lens_ps_statements_history;')
