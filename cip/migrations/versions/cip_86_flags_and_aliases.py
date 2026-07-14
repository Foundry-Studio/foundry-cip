# foundry: kind=migration domain=client-intelligence-platform
"""cip_86: the seen_in_* flags are a cache nothing maintains, and they are lying about the contract.

An adversarial schema audit found 26 brands that ARE on the frozen exclusion list while
`ps_brands.seen_in_exclusion_list = false`. Nineteen of them carry money — $41,743.82 collected.

    CrownShade   $14,804.37   bucket 'Shallow'                <- ANOTHER PARTNER IS STILL EARNING
    OBSBOT       $10,865.22   bucket 'Heavy Producer Brands'
    Veise         $4,044.08   bucket 'Jeremy  Caspar'

`WHERE NOT seen_in_exclusion_list` is the obvious way to ask "which brands does nobody else have a
claim on?" — and it hands you twenty-six brands somebody else is being paid on. That is a claim
integrity bug, not a cosmetic one.

WHY IT DRIFTED
--------------
cip_55 backfilled all five `seen_in_*` flags ONCE with EXISTS subqueries. Only `seen_in_stripe` has
had a maintainer since. The others are a denormalised cache with no writer — so they can only ever
go stale in ONE direction: the row exists, the flag says false. `flag = true` is trustworthy;
`flag = false` is not, and nothing said so.

`harvest_nationality_signals.py` reads `seen_in_eric_sheets` to emit a DEFINITIONAL-strength China
signal. It is in sync today. It is maintained by nothing. That is a loaded gun pointed at the
nationality verdict.

THE DOUBLE SPACE
----------------
`ps_excluded_brands.bucket = 'Jeremy  Caspar'` — two spaces. `WHERE bucket = 'Jeremy Caspar'`
returns zero rows and silently drops 34 brands. The column decides winnability and has no CHECK.

THE ALIASES
-----------
`canonical_brand_id` is populated on 852 rows and collapses 5,352 rows to 4,500 real brands. Exactly
ONE view consumes it — `lens_ps_claim_reconciliation` — and that view is PARKED. Every live lens
keys on `wayward_brand_id`, so the chase list sends the team to ring 70 brands twice under two
names. This migration collapses the CHASE LIST, which is the one people act on. The rest of the
lenses still over-count and that is filed, not fixed — collapsing money lenses is a bigger change
than this migration should carry.

Revision ID: cip_86_flags_and_aliases
Revises: cip_85_reality_money_wins
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_86_flags_and_aliases"
down_revision: str | Sequence[str] | None = "cip_85_reality_money_wins"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # ── 1. the double space, before anything keys on the bucket ──────────────
    op.execute(
        "UPDATE ps_excluded_brands "
        "SET bucket = btrim(regexp_replace(bucket, '\\s+', ' ', 'g')) "
        "WHERE bucket <> btrim(regexp_replace(bucket, '\\s+', ' ', 'g'))"
    )

    # ── 2. resync every unmaintained flag from its source of truth ───────────
    op.execute(
        """
        UPDATE ps_brands b SET
            seen_in_exclusion_list = EXISTS (
                SELECT 1 FROM ps_excluded_brands x WHERE x.wayward_brand_id = b.wayward_brand_id),
            seen_in_eric_sheets = EXISTS (
                SELECT 1 FROM ps_brand_observations o WHERE o.wayward_brand_id = b.wayward_brand_id
                  AND o.source_system = 'gsheet:eric-all-agreements'),
            seen_in_slack_feed = EXISTS (
                SELECT 1 FROM ps_brand_observations o WHERE o.wayward_brand_id = b.wayward_brand_id
                  AND o.source_system LIKE 'slack:%'),
            seen_in_payment_reports = EXISTS (
                SELECT 1 FROM ps_payment_events p WHERE p.wayward_brand_id = b.wayward_brand_id),
            seen_in_stripe = EXISTS (
                SELECT 1 FROM ps_stripe_customers s WHERE s.wayward_brand_id = b.wayward_brand_id)
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_brands.seen_in_exclusion_list IS "
        "'*** A DENORMALISED CACHE. THE SOURCE OF TRUTH IS ps_excluded_brands. *** cip_55 backfilled "
        "this once and nothing maintained it, so by 2026-07-14 it was FALSE on 26 brands that were "
        "on the frozen list — $41,743.82 of collected revenue, including CrownShade (bucket "
        "''Shallow'', where another partner is still earning) and OBSBOT (Heavy Producer). "
        "`WHERE NOT seen_in_exclusion_list` is the natural way to ask ''who does nobody else have a "
        "claim on?'' and it handed back brands somebody else is being paid on. "
        "It drifts in ONE direction only: the row exists, the flag says false. So TRUE is "
        "trustworthy and FALSE is not. If it matters, JOIN ps_excluded_brands — do not trust this. "
        "Guarded by the `stale_seen_in_flags` invariant.'"
    )

    # ── 3. the chase list is the thing people ACT on. Collapse the aliases. ──
    op.execute("DROP VIEW IF EXISTS lens_ps_china_chase_list CASCADE")
    op.execute(
        """
        CREATE VIEW lens_ps_china_chase_list AS
        WITH collapsed AS (
            SELECT DISTINCT ON (COALESCE(b.canonical_brand_id, b.wayward_brand_id))
                COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS brand_id,
                b.wayward_brand_id,
                b.brand_name,
                b.signup_date
            FROM ps_brands b
            JOIN lens_ps_brand_reality r ON r.wayward_brand_id = b.wayward_brand_id
            JOIN lens_ps_china_verdict v ON v.wayward_brand_id = b.wayward_brand_id
            WHERE r.reality = 'REAL' AND v.verdict = 'china' AND NOT r.ever_billed
            -- prefer the row that actually carries a contact; a phone beats no phone
            ORDER BY COALESCE(b.canonical_brand_id, b.wayward_brand_id),
                     (EXISTS (SELECT 1 FROM ps_brand_contacts c
                               WHERE c.wayward_brand_id = b.wayward_brand_id
                                 AND c.phone IS NOT NULL)) DESC,
                     (EXISTS (SELECT 1 FROM ps_brand_contacts c
                               WHERE c.wayward_brand_id = b.wayward_brand_id)) DESC,
                     b.wayward_brand_id
        )
        SELECT
            cp.brand_id                        AS wayward_brand_id,
            cp.brand_name,
            v.verdict,
            v.china_evidence,
            r.wayward_onboarded_them,
            r.on_a_frozen_list,
            r.on_eric_sheet,
            ct.name    AS contact_name,
            ct.email   AS contact_email,
            ct.phone   AS contact_phone,
            ct.country AS contact_country,
            cp.signup_date
        FROM collapsed cp
        JOIN lens_ps_china_verdict  v ON v.wayward_brand_id = cp.wayward_brand_id
        JOIN lens_ps_brand_reality  r ON r.wayward_brand_id = cp.wayward_brand_id
        LEFT JOIN LATERAL (
            SELECT name, email, phone, country FROM ps_brand_contacts c
            WHERE c.wayward_brand_id = cp.wayward_brand_id
            ORDER BY (c.phone IS NOT NULL) DESC, (c.email IS NOT NULL) DESC LIMIT 1
        ) ct ON true
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_china_chase_list IS "
        "'CONFIRMED CHINESE, REAL, AND HAS NEVER SOLD A THING — the CRM chase list. "
        "*** ONE ROW PER REAL COMPANY. *** Collapsed on canonical_brand_id: ps_brands holds 852 "
        "ALIAS rows (5,352 rows = 4,500 companies) and the uncollapsed version of this list sent the "
        "team to ring 70 brands twice under two names. Where a company has several rows, this picks "
        "the one that actually carries a contact — a phone beats an email beats nothing. "
        "NOTE: canonical_brand_id is consumed by almost nothing else. The other lenses still "
        "over-count. This one is collapsed because it is the one people ACT on.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_chase_list TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_chase_list CASCADE")
    op.execute(
        """
        CREATE VIEW lens_ps_china_chase_list AS
        SELECT r.wayward_brand_id, r.brand_name, v.verdict, v.china_evidence,
               r.wayward_onboarded_them, r.on_a_frozen_list, r.on_eric_sheet,
               ct.name AS contact_name, ct.email AS contact_email,
               ct.phone AS contact_phone, ct.country AS contact_country, b.signup_date
        FROM lens_ps_brand_reality r
        JOIN lens_ps_china_verdict v ON v.wayward_brand_id = r.wayward_brand_id
        JOIN ps_brands b             ON b.wayward_brand_id = r.wayward_brand_id
        LEFT JOIN LATERAL (
            SELECT name, email, phone, country FROM ps_brand_contacts c
            WHERE c.wayward_brand_id = r.wayward_brand_id
            ORDER BY (c.email IS NOT NULL) DESC, (c.phone IS NOT NULL) DESC LIMIT 1
        ) ct ON true
        WHERE r.reality = 'REAL' AND v.verdict = 'china' AND NOT r.ever_billed
        """
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_chase_list TO {r}")
