# foundry: kind=migration domain=client-intelligence-platform
"""cip_63: Rule B tests whether a brand IS billing, not when it FIRST billed.

MY BUG, CAUGHT IN cip_62 AND FIXED HERE
---------------------------------------
Tim's Rule B:

  "There are brands that they onboarded before the takeover, but starting with DECEMBER
   BILLINGS, we STILL GET CREDIT if they are in China, as we are handling the CS and everything."

cip_62 implemented that as `first_billed_month >= 2025-12-01`. That is the wrong test. It asks
"did this brand's billing history BEGIN in December?" when the rule asks "is this brand billing
in December or later?"

The difference is not academic. A brand that first billed in June 2025 and is STILL billing today
fails `first_billed_month >= 2025-12-01` — and it is exactly the kind of brand the rule was
written for: onboarded before the takeover, still running, and we are the ones handling its CS.

    585 brands were tagged 'pre_takeover_no_dec_billing' while actively billing since December.
    $545,080.78 collected from them since 2025-12-01.

Only 203 brands genuinely stopped billing before December, and those remain correctly ineligible.

So Rule B becomes an EXISTS over billing months, not a comparison against the first one. And
credit_starts stays 2025-12-01 for these brands — we are owed on their December-onward billings,
not on their history.

Revision ID: cip_63_rule_b_fix
Revises: cip_62_signup_date
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_63_rule_b_fix"
down_revision: str | Sequence[str] | None = "cip_62_signup_date"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

FREEZE = "2025-11-18"
RULE_B = "2025-12-01"


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_eligibility CASCADE")
    op.execute(
        f"""
        CREATE VIEW lens_ps_eligibility AS
        WITH billed AS (
            SELECT wayward_brand_id,
                   min(billing_month)                         AS first_billed_month,
                   max(billing_month)                         AS last_billed_month,
                   -- THE FIX: is this brand billing in the December-onward window AT ALL?
                   bool_or(billing_month >= DATE '{RULE_B}')  AS bills_in_our_era,
                   max(client_id::text)::uuid                 AS client_id
            FROM ps_stripe_invoice_lines
            WHERE is_ps_base AND amount > 0
              AND billing_month IS NOT NULL AND wayward_brand_id IS NOT NULL
            GROUP BY wayward_brand_id
        ),
        obs AS (
            SELECT wayward_brand_id,
                   max(client_id::text)::uuid                      AS client_id,
                   max(value) FILTER (WHERE field = 'brand_name')  AS brand_name,
                   max(value) FILTER (WHERE field = 'country')     AS wayward_country,
                   max(value) FILTER (WHERE field = 'deal_source') AS deal_source
            FROM ps_brand_observations
            GROUP BY wayward_brand_id
        )
        SELECT
            br.wayward_brand_id,
            COALESCE(b.client_id, obs.client_id)                   AS client_id,
            COALESCE(obs.brand_name, br.brand_name)                AS brand_name,
            b.first_billed_month,
            b.last_billed_month,
            b.bills_in_our_era,
            br.signup_date                                         AS onboarded,
            br.signup_date_source                                  AS onboarded_source,
            obs.deal_source,
            obs.wayward_country,
            c.nationality_class,
            x.bucket                                               AS excluded_bucket,
            x.winback_path,
            (x.wayward_brand_id IS NOT NULL)                       AS is_excluded,
            (c.nationality_class IN ('chinese_confirmed','chinese_suspected')
             OR obs.wayward_country = 'CN')                        AS is_chinese,
            (br.signup_date > DATE '{FREEZE}')                     AS post_takeover,
            CASE
                WHEN x.wayward_brand_id IS NOT NULL        THEN 'excluded'
                WHEN NOT (c.nationality_class IN ('chinese_confirmed','chinese_suspected')
                          OR obs.wayward_country = 'CN')   THEN 'not_chinese'
                -- Rule A: onboarded after the freeze. Ours outright, any referral source.
                WHEN br.signup_date > DATE '{FREEZE}'      THEN 'eligible_rule_a'
                -- Rule B: onboarded before it, but BILLING in our era. We run the CS.
                WHEN b.bills_in_our_era                    THEN 'eligible_rule_b'
                WHEN b.first_billed_month IS NULL          THEN 'never_billed'
                ELSE 'stopped_billing_pre_december'
            END                                                    AS eligibility,
            CASE
                WHEN x.wayward_brand_id IS NOT NULL        THEN NULL
                WHEN br.signup_date > DATE '{FREEZE}'      THEN b.first_billed_month
                WHEN b.bills_in_our_era                    THEN DATE '{RULE_B}'
                ELSE NULL
            END                                                    AS credit_starts
        FROM ps_brands br
        LEFT JOIN billed b             ON b.wayward_brand_id   = br.wayward_brand_id
        LEFT JOIN obs                  ON obs.wayward_brand_id = br.wayward_brand_id
        LEFT JOIN ps_excluded_brands x ON x.wayward_brand_id   = br.wayward_brand_id
        LEFT JOIN cip_clients c        ON c.id = COALESCE(b.client_id, obs.client_id)
        """
    )
    op.execute(
        f"COMMENT ON VIEW lens_ps_eligibility IS "
        f"'Is this brand ours to claim? Rule A: ONBOARDED after {FREEZE} (the day Jake sent the "
        f"frozen exclusion list) — ours outright, whatever the referral source, if Chinese. "
        f"Rule B: onboarded on/before the freeze, not excluded, but BILLING from {RULE_B} onward "
        f"— ours from {RULE_B}, because we run the CS. Rule B asks whether the brand IS billing "
        f"in our era (bool_or over its billing months), NOT when it FIRST billed: a brand that "
        f"first billed in June 2025 and is still billing today is precisely what the rule is "
        f"for, and testing first_billed_month excluded 585 such brands holding $545k of "
        f"collected usage. Proof the {FREEZE} boundary is real: of the brands onboarded after "
        f"it, ZERO are on the exclusion list.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_eligibility.bills_in_our_era IS "
        "'Does this brand have ANY usage-fee billing from 2025-12-01 onward? This is the Rule-B "
        "test. It deliberately does NOT ask when the brand first billed — a brand billing since "
        "2024 and still billing today is exactly the population Rule B covers.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_eligibility.credit_starts IS "
        "'The month from which we are owed on this brand. Rule A brands: their whole billing "
        "history. Rule B brands: only from 2025-12-01 — we do not claim their pre-takeover "
        "months, only the ones we have been servicing.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_eligibility TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_eligibility CASCADE")
