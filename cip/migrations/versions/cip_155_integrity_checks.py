# foundry: kind=migration domain=client-intelligence-platform
"""cip_155_integrity_checks: DI-6a. CREATE the read-only data-integrity lens lens_ps_integrity_checks.

This is a NEW lens, not an edit to lens_ps_invariants (which stays exactly as-is). Same output shape as
lens_ps_invariants (an inner UNION ALL of check arms wrapped by one outer pass/fail/pct SELECT), but a
different purpose: lens_ps_invariants asserts internal ledger math; this lens spot-checks things a human would
otherwise have to eyeball across many lenses at once (a raw-input sanity canary, lens non-emptiness, and a
couple of cross-lens money reconciliations), so a single SELECT gives a go/no-go read of the Wayward China book.

Output columns (identical shape to lens_ps_invariants):
    check_key text, check_type text, category text, label text, passed bigint, total bigint, failed bigint,
    pct numeric, status text ('ok'|'fail'), detail text.

check_type='canary' (category='gmv') - THE STAR, and it is EXPECTED to read status='fail' today:
    canary.gmv_total_sane   sum of cip_deals.properties->>'lifetime_gmv' (numeric-parseable rows only) must be
                            <= $100M. Grounded today at $629,179,234.63 (tenant-scoped, live-queried at authoring
                            time) -> FAILS. That failure is the point: it proves this canary is reading real,
                            current data rather than a stale or synthetic fixture. If this ever reads 'ok', the
                            underlying lifetime_gmv figures dropped by ~5x, which itself would be worth knowing.
    canary.gmv_deal_bound   no single deal's lifetime_gmv may exceed $50M. Grounded today: one deal carries
                            lifetime_gmv = $206,821,698.41 -> FAILS (1 of 1227 numeric-parseable deals).
    Both use the exact cip_deals RLS access pattern lifted from cip_153's captured view bodies
    (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid); no tenant UUID is hardcoded.
    The '^[0-9.]+$' filter used for "numeric-parseable" deliberately excludes the one negative-valued row seen
    at authoring time ('-2321.82'); a leading '-' does not match the character class, so that row is (correctly,
    for this check) not counted as numeric.

check_type='not_empty' (category='coverage'):
    not_empty.attribution_china_lenses   9 core China attribution/coverage lenses must each return > 0 rows:
                            lens_eric_attributed_deals, lens_tim_attributed_deals, lens_adina_attributed_deals,
                            lens_jeremy_attributed_deals, lens_openlight_attributed_deals,
                            lens_wayward_attribution_summary, lens_china_clients, lens_china_companies,
                            lens_china_contacts. Grounded row counts today: 801 / 526 / 199 / 24 / 6 / 6 / 1563 /
                            1560 / 1175 - all > 0. lens_hyphen_migration_deals and lens_china_tickets are
                            deliberately EXCLUDED: both are grounded at 0 rows today by design (cip_153's own
                            docstring: lens_china_tickets' source tables are empty; lens_hyphen_migration_deals
                            is a one-off migration-tag filter with nothing currently tagged), so folding either
                            in would make this check permanently red for a reason nobody needs alerting on.
    not_empty.china_verdict   lens_ps_china_verdict must return > 0 rows. Grounded today at 5445 rows.

check_type='reconciliation' (category='money'):
    recon.partner_rate_5pct   every active partner rate must be 5%. Source: lens_ps_partner_rate.current_rate_pct
                            (that lens already de-dupes ps_partner_rate down to one current-as-of-today row per
                            party/product via its own date-window CTE, so every row IT returns already IS the
                            "active" pair - reading it directly is simpler and more correct than re-deriving
                            "active" from the base table's raw effective_to IS NULL, and it avoids this lens
                            reaching around a view into ps_partner_rate). Grounded: rate_pct is stored as the
                            percentage number 5.0000, NOT the fraction 0.05 - the comparison below is `<> 5`,
                            matching the column's actual grounded magnitude. Grounded today: 27 of 27 active
                            pairs at exactly 5.0 (post cip_152) -> 0 violations.
    recon.china_claim_present   lens_ps_claim rows with verdict='china' must exist, sum to a nonzero amount, and
                            contain no negative ps_claim_owed. Grounded today: 1167 rows, sum = $16,868.26,
                            min = $0.00 -> 0 violations.

Deliberately NOT built (deferred, not authored, per this migration's own instructions: a wrong check is worse
than a missing one):
    - "cash rev_share ties to commission-paid" and "commission tier totals foot to the ledger" - both require
      cross-lens money semantics (which cash-side lens is the source of truth for rev_share, how tier totals are
      meant to foot against lens_ps_commission_ledger) that were not grounded with confidence at authoring time.
      A false-alarm reconciliation check is worse than no check; left for a follow-up DI-6b once that mapping is
      confirmed.

Verified by a transactional dry run against the live database at authoring time (CREATE OR REPLACE VIEW inside
a transaction that was always rolled back, never committed - no alembic_version_cip write, no persisted change)
to confirm the exact SQL below type-checks and reads the status values documented above. This migration itself
was not applied to any database; the guarded prod apply is done separately.

Revision ID: cip_155_integrity_checks   (24 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_154_mechanical_lens_fix
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_155_integrity_checks"
down_revision: str | Sequence[str] | None = "cip_154_mechanical_lens_fix"
branch_labels = None
depends_on = None

_VIEW = "lens_ps_integrity_checks"
# Reader roles that every sibling lens (lens_ps_invariants, lens_ps_brand_status, ...) grants SELECT to. A NEW
# view inherits NO grants (pg_default_acl carries only postgres on tables), so this must be explicit or the
# cip_query reader and the app's ps_reporting_reader get "permission denied" on the new lens.
_READER_ROLES = "cip_query_reader, ps_reporting_reader, cip_metabase_project_silk, cip_twenty_project_silk, metabase_reader_foundry"

# Inner UNION ALL of check arms, each yielding (check_key, check_type, category, label, violations, total,
# detail); the outer SELECT below derives passed/failed/pct/status from (violations, total), same shape as
# lens_ps_invariants. Every arm's (violations, total) pair is cast to bigint so the UNION ALL column types agree
# regardless of whether an arm computes them via count(*) or a literal/CASE expression.
_DEFINITION = """
WITH checks AS (

    SELECT
        'canary.gmv_total_sane'::text AS check_key,
        'canary'::text AS check_type,
        'gmv'::text AS category,
        'Sum of all deals lifetime_gmv is within sane bounds (<= 100000000)'::text AS label,
        (CASE WHEN gmv.total_gmv > 100000000 THEN 1 ELSE 0 END)::bigint AS violations,
        1::bigint AS total,
        ('total lifetime_gmv=$' || round(gmv.total_gmv, 0)::text) AS detail
    FROM (
        SELECT COALESCE(sum((d.properties ->> 'lifetime_gmv')::numeric), 0) AS total_gmv
        FROM cip_deals d
        WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid
          AND d.properties ->> 'lifetime_gmv' ~ '^[0-9.]+$'
    ) gmv

    UNION ALL

    SELECT
        'canary.gmv_deal_bound'::text,
        'canary'::text,
        'gmv'::text,
        'No single deal lifetime_gmv exceeds 50000000'::text,
        count(*) FILTER (WHERE (d.properties ->> 'lifetime_gmv')::numeric > 50000000),
        count(*),
        ('max lifetime_gmv=$' || round(max((d.properties ->> 'lifetime_gmv')::numeric), 0)::text)
    FROM cip_deals d
    WHERE d.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid
      AND d.properties ->> 'lifetime_gmv' ~ '^[0-9.]+$'

    UNION ALL

    SELECT
        'not_empty.attribution_china_lenses'::text,
        'not_empty'::text,
        'coverage'::text,
        'Core China attribution and coverage lenses each return at least one row'::text,
        ((CASE WHEN (SELECT count(*) FROM lens_eric_attributed_deals) = 0 THEN 1 ELSE 0 END)
       + (CASE WHEN (SELECT count(*) FROM lens_tim_attributed_deals) = 0 THEN 1 ELSE 0 END)
       + (CASE WHEN (SELECT count(*) FROM lens_adina_attributed_deals) = 0 THEN 1 ELSE 0 END)
       + (CASE WHEN (SELECT count(*) FROM lens_jeremy_attributed_deals) = 0 THEN 1 ELSE 0 END)
       + (CASE WHEN (SELECT count(*) FROM lens_openlight_attributed_deals) = 0 THEN 1 ELSE 0 END)
       + (CASE WHEN (SELECT count(*) FROM lens_wayward_attribution_summary) = 0 THEN 1 ELSE 0 END)
       + (CASE WHEN (SELECT count(*) FROM lens_china_clients) = 0 THEN 1 ELSE 0 END)
       + (CASE WHEN (SELECT count(*) FROM lens_china_companies) = 0 THEN 1 ELSE 0 END)
       + (CASE WHEN (SELECT count(*) FROM lens_china_contacts) = 0 THEN 1 ELSE 0 END))::bigint,
        9::bigint,
        'lens_eric_attributed_deals, lens_tim_attributed_deals, lens_adina_attributed_deals, lens_jeremy_attributed_deals, lens_openlight_attributed_deals, lens_wayward_attribution_summary, lens_china_clients, lens_china_companies, lens_china_contacts'::text

    UNION ALL

    SELECT
        'not_empty.china_verdict'::text,
        'not_empty'::text,
        'coverage'::text,
        'China verdict lens returns at least one row'::text,
        (CASE WHEN (SELECT count(*) FROM lens_ps_china_verdict) = 0 THEN 1 ELSE 0 END)::bigint,
        1::bigint,
        'lens_ps_china_verdict'::text

    UNION ALL

    SELECT
        'recon.partner_rate_5pct'::text,
        'reconciliation'::text,
        'money'::text,
        'Every active partner rate is 5 percent (cip_152 ratified rate)'::text,
        count(*) FILTER (WHERE pr.current_rate_pct <> 5),
        count(*),
        'lens_ps_partner_rate'::text
    FROM lens_ps_partner_rate pr

    UNION ALL

    SELECT
        'recon.china_claim_present'::text,
        'reconciliation'::text,
        'money'::text,
        'China verdict claim rows exist and no claim owed is negative'::text,
        (count(*) FILTER (WHERE cl.ps_claim_owed < 0)
         + CASE WHEN count(*) = 0 OR COALESCE(sum(cl.ps_claim_owed), 0) = 0 THEN 1 ELSE 0 END),
        count(*),
        'lens_ps_claim'::text
    FROM lens_ps_claim cl
    WHERE cl.verdict = 'china'

)
SELECT
    check_key,
    check_type,
    category,
    label,
    (total - violations)::bigint AS passed,
    total::bigint AS total,
    violations::bigint AS failed,
    CASE WHEN total = 0 THEN NULL ELSE round(100.0 * (total - violations)::numeric / total::numeric, 1) END AS pct,
    CASE WHEN violations = 0 THEN 'ok' ELSE 'fail' END AS status,
    detail
FROM checks
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"CREATE OR REPLACE VIEW {_VIEW} AS {_DEFINITION}")
    op.execute(f"GRANT SELECT ON {_VIEW} TO {_READER_ROLES}")
    print(
        f"cip_155: created {_VIEW} (DI-6a), 6 check arms (2 canary, 2 not_empty, 2 reconciliation). "
        "canary.gmv_total_sane and canary.gmv_deal_bound are expected to read status='fail' on live data."
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"DROP VIEW IF EXISTS {_VIEW}")
    print(f"cip_155 downgrade: dropped {_VIEW}.")
