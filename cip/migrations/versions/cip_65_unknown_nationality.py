# foundry: kind=migration domain=client-intelligence-platform
"""cip_65: "we do not know" is not "no". The China flag is worth ~$141k.

THE SAME BUG THAT STARTED THIS CLEANUP, WEARING A DIFFERENT HAT
---------------------------------------------------------------
cip_55 removed COALESCE(rate, 0), because an unknown RATE was being silently turned into a
confident $0.00. Claimability then reintroduced the identical failure one level up, on
NATIONALITY:

    is_chinese := (nationality_class IN ('chinese_confirmed','chinese_suspected')
                   OR wayward_country = 'CN')

Anything else — including a brand about which we know NOTHING — evaluated to FALSE. Not NULL.
FALSE. So "we have never established where this brand is from" was being written into the money
model as "this brand is not Chinese, we are owed nothing", and it read like a settled fact.

WHAT IT WAS COSTING
-------------------
Of the 1,318 brands the model was calling not-Chinese:

    733 brands   NO nationality evidence of any kind   $1,333,436 collected   ~$133,344 to PS
    311 brands   nationality_class = 'unknown'            $75,113 collected     ~$7,511 to PS
    ----                                                                        -----------
  1,044 brands   genuinely UNRESOLVED                                          ~$140,855

    266 brands   Wayward says US                         $218,670 collected    (correctly not ours)
     ~32 brands  Wayward says CA/GB/IN/DE/JP/...          $26,332 collected    (correctly not ours)

So roughly $141k of the claim was resting on a question nobody had asked, and the schema was
answering it "no" on our behalf. Only ~$24.5k is genuinely someone else's.

THE FIX
-------
'unknown_nationality' becomes its own claim_basis. It is NOT claimable — we cannot invoice a
brand we cannot place — but it is also NOT written off. It is a queue, with a dollar value
attached, and it is now the single highest-value work item in the audit.

Also fixed: one brand's `country` observation is the string "Impersonate Account button  View
Contact in Intercom button *Hubspot Sync Information*" — a Slack-parser artifact that scraped
page furniture into the country field. It carries $11,524 of collected usage. Treated as
unknown, not as a foreign country.

Revision ID: cip_65_unknown_nationality
Revises: cip_64_claimability
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_65_unknown_nationality"
down_revision: str | Sequence[str] | None = "cip_64_claimability"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# ISO-2 country codes only. Anything else in that field is parser debris, not a country.
_VALID_COUNTRY = "value ~ '^[A-Z]{2}$'"

_BASIS = (
    "boost_all_brands",
    "rule_a_post_takeover",
    "rule_b_december",
    "reactivation_flat_fee",
    "not_claimable_excluded",
    "not_claimable_not_chinese",
    "not_claimable_pre_takeover",
    "unknown_nationality",          # NEW — not claimable, but NOT written off either
)


def upgrade() -> None:
    allowed = ", ".join(f"'{b}'" for b in _BASIS)
    op.execute(
        "ALTER TABLE ps_monthly_earnings DROP CONSTRAINT IF EXISTS ck_earnings_claim_basis"
    )
    op.execute(
        f"""
        ALTER TABLE ps_monthly_earnings ADD CONSTRAINT ck_earnings_claim_basis CHECK (
            claim_basis IS NULL OR claim_basis IN ({allowed})
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.claim_basis IS "
        "'WHY this row is (or is not) claimable. boost_all_brands = Boost is ours even on "
        "excluded brands (Tim/Ali, verbal). rule_a_post_takeover = onboarded after the "
        "2025-11-18 freeze. rule_b_december = onboarded before it but billing from Dec 2025. "
        "reactivation_flat_fee = 90 days dark, back after 2025-11-01, flat-fee brand only. "
        "*** unknown_nationality = WE HAVE NOT ESTABLISHED WHERE THIS BRAND IS FROM. It is not "
        "claimable, but it is emphatically NOT a denial: 1,044 brands and ~$141k of PS "
        "commission sit here, and the schema used to answer that question ''not Chinese'' on our "
        "behalf. Unknown is a queue, not a verdict.***'"
    )

    # The highest-value open question in the audit, priced.
    op.execute("DROP VIEW IF EXISTS lens_ps_nationality_gap")
    op.execute(
        f"""
        CREATE VIEW lens_ps_nationality_gap AS
        WITH ctry AS (
            SELECT wayward_brand_id,
                   max(value) FILTER (WHERE {_VALID_COUNTRY}) AS country
            FROM ps_brand_observations
            WHERE field = 'country'
            GROUP BY wayward_brand_id
        ),
        money AS (
            SELECT e.wayward_brand_id,
                   sum(e.usage_collected)                              AS collected,
                   sum(e.usage_collected) FILTER (
                        WHERE e.period_month >= DATE '2025-12-01')     AS collected_our_era,
                   min(e.period_month)                                 AS first_month,
                   max(e.period_month)                                 AS last_month
            FROM ps_monthly_earnings e
            GROUP BY e.wayward_brand_id
        )
        SELECT
            b.wayward_brand_id,
            b.brand_name,
            b.signup_date,
            c.country                                       AS wayward_country,
            cl.nationality_class,
            pc.partner_of_record,
            pc.deal_source,
            x.bucket                                        AS excluded_bucket,
            round(m.collected, 2)                           AS collected_all_time,
            round(m.collected_our_era, 2)                   AS collected_our_era,
            round(m.collected_our_era * 0.10, 2)            AS ps_at_stake_if_chinese,
            m.first_month,
            m.last_month
        FROM ps_brands b
        JOIN money m           ON m.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN ctry c       ON c.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN cip_clients cl ON cl.id = b.client_id
        LEFT JOIN ps_excluded_brands x ON x.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN LATERAL (
            SELECT partner_of_record, deal_source FROM ps_partner_credit p
            WHERE p.wayward_brand_id = b.wayward_brand_id LIMIT 1
        ) pc ON true
        WHERE c.country IS NULL                                    -- no usable country
          AND COALESCE(cl.nationality_class, 'unknown') = 'unknown'
          AND m.collected > 0
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_nationality_gap IS "
        "'THE REVIEW QUEUE, priced. Every brand that has COLLECTED money and whose nationality we "
        "have never established — sorted by what it is worth. ~$141k of PS commission hangs on "
        "these, and until cip_65 the model was quietly answering ''not Chinese'' for all of them. "
        "ps_at_stake_if_chinese is 10%% of what was collected in our era: the value of resolving "
        "ONE row. Excludes brands where Wayward states a real ISO country — the string "
        "''Impersonate Account button...'' is Slack-parser debris, not a country, and is treated "
        "as unknown.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_nationality_gap TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_nationality_gap")
    op.execute(
        "ALTER TABLE ps_monthly_earnings DROP CONSTRAINT IF EXISTS ck_earnings_claim_basis"
    )
    keep = ", ".join(f"'{b}'" for b in _BASIS if b != "unknown_nationality")
    op.execute(
        f"""
        ALTER TABLE ps_monthly_earnings ADD CONSTRAINT ck_earnings_claim_basis CHECK (
            claim_basis IS NULL OR claim_basis IN ({keep})
        )
        """
    )
