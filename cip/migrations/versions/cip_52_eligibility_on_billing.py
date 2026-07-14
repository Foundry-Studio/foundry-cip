# foundry: kind=migration domain=client-intelligence-platform
"""cip_52: eligibility keys off BILLING, not onboarding. Fixes a real misclassification.

THE BUG
-------
lens_ps_eligibility (cip_48) keyed Rule A off `connection_event_at` — the ONBOARDING date
from the Slack brand feed. But Tim's rule keys off BILLING:

    "We key off billing, not onboarding — because we often don't know the true onboarding or
     first-transaction date, but we can ALWAYS see when a brand was first BILLED."

    RULE A (net new): first billed NOVEMBER 2025 or later => ours, full credit, regardless of
                      who referred it. A DECEMBER bill for NOVEMBER SALES is ours. We do not
                      give away the month we cannot see.
    RULE B (legacy) : first billed earlier, not on the frozen list => ours on revenue from
                      2025-12-01 onward, because PS took over CS and account management.

These are different dates and they classify brands differently. Onboarding is when a brand
signed up; billing is when it started producing. A brand can onboard in June and not bill
until March — under the old lens that brand was judged on June.

It also fixes a coverage hole: `connection_event_at` only exists for brands that appear in
the Slack brand-connection feed. Brands billing in Stripe but absent from that feed had NO
onboarding date at all and fell into 'unknown_onboard_date'. Stripe covers every brand
Wayward has ever invoiced, so keying off billing sees brands the feed never mentioned.

WHAT STAYS THE SAME: a brand is ours only if it is CHINESE and NOT on the frozen exclusion
list. The frozen list is still the only carve-out.

Revision ID: cip_52_elig_on_billing
Revises: cip_51_monthly_earnings
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_52_elig_on_billing"
down_revision: str | Sequence[str] | None = "cip_51_monthly_earnings"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

TAKEOVER = "2025-11-01"     # Rule A: first billed in NOVEMBER 2025 or later
CREDIT_START = "2025-12-01"  # Rule B: legacy brands earn from the December billings


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_eligibility")
    op.execute(
        f"""
        CREATE VIEW lens_ps_eligibility AS
        WITH billed AS (
            -- FIRST BILLED MONTH, from Stripe. This is the anchor now — not onboarding.
            -- Stripe covers every brand Wayward ever invoiced, so this sees brands the
            -- Slack brand feed never mentioned.
            SELECT wayward_brand_id,
                   min(billing_month) AS first_billed_month,
                   max(client_id::text)::uuid AS client_id
            FROM ps_stripe_invoice_lines
            WHERE is_ps_base AND amount > 0
              AND billing_month IS NOT NULL AND wayward_brand_id IS NOT NULL
            GROUP BY 1
        ),
        obs AS (
            SELECT o.wayward_brand_id,
                   max(o.client_id::text)::uuid                              AS client_id,
                   max(o.value) FILTER (WHERE o.field='brand_name')          AS brand_name,
                   max(o.value) FILTER (WHERE o.field='country')             AS wayward_country,
                   max(o.value) FILTER (WHERE o.field='deal_source')         AS deal_source,
                   max(o.value) FILTER (WHERE o.field='connection_event_at') AS onboarded_raw
            FROM ps_brand_observations o
            GROUP BY o.wayward_brand_id
        ),
        base AS (
            SELECT
                COALESCE(b.wayward_brand_id, obs.wayward_brand_id)  AS wayward_brand_id,
                COALESCE(b.client_id, obs.client_id)                AS client_id,
                obs.brand_name,
                obs.wayward_country,
                obs.deal_source,
                b.first_billed_month,
                CASE WHEN obs.onboarded_raw IS NULL THEN NULL
                     ELSE to_date(split_part(obs.onboarded_raw,' at ',1),'FMMonth DD, YYYY')
                END                                                 AS onboarded,
                x.bucket                                            AS excluded_bucket,
                x.winback_path,
                c.nationality_class
            FROM billed b
            FULL OUTER JOIN obs ON obs.wayward_brand_id = b.wayward_brand_id
            LEFT JOIN ps_excluded_brands x
                   ON x.wayward_brand_id = COALESCE(b.wayward_brand_id, obs.wayward_brand_id)
            LEFT JOIN cip_clients c
                   ON c.id = COALESCE(b.client_id, obs.client_id)
        )
        SELECT
            b.wayward_brand_id,
            b.client_id,
            b.brand_name,
            b.first_billed_month,          -- THE ANCHOR
            b.onboarded,                   -- kept for reference; NOT the gate
            b.deal_source,                 -- PROVENANCE ONLY. Never a gate on eligibility.
            b.wayward_country,
            b.nationality_class,
            b.excluded_bucket,
            b.winback_path,

            (b.excluded_bucket IS NOT NULL)                          AS is_excluded,

            -- China wins: our own determination OR Wayward's country field saying CN.
            (b.nationality_class IN ('chinese_confirmed','chinese_suspected')
             OR b.wayward_country = 'CN')                            AS is_chinese,

            (b.first_billed_month >= DATE '{TAKEOVER}')              AS post_takeover,

            CASE
                WHEN b.excluded_bucket IS NOT NULL          THEN 'excluded'
                WHEN NOT (b.nationality_class IN ('chinese_confirmed','chinese_suspected')
                          OR b.wayward_country = 'CN')     THEN 'not_chinese'
                WHEN b.first_billed_month IS NULL           THEN 'never_billed'
                WHEN b.first_billed_month >= DATE '{TAKEOVER}' THEN 'eligible_rule_a'
                ELSE 'eligible_rule_b'
            END                                                      AS eligibility,

            -- When our credit starts. Rule A: from its first bill. Rule B: Dec 2025.
            CASE
                WHEN b.excluded_bucket IS NOT NULL              THEN NULL
                WHEN b.first_billed_month IS NULL               THEN NULL
                WHEN b.first_billed_month >= DATE '{TAKEOVER}'  THEN b.first_billed_month
                ELSE DATE '{CREDIT_START}'
            END                                                      AS credit_starts
        FROM base b
        WHERE b.wayward_brand_id IS NOT NULL
        """
    )
    op.execute(
        f"COMMENT ON VIEW lens_ps_eligibility IS "
        f"'THE money model. A brand is ours if it is CHINESE and NOT on the frozen exclusion "
        f"list. Keyed off BILLING, not onboarding (Tim, 2026-07-13): we often cannot see the "
        f"true onboarding or first-transaction date, but we can ALWAYS see when a brand was "
        f"first BILLED. "
        f"RULE A - first billed {TAKEOVER} or later: FULL credit, REGARDLESS of referral "
        f"source. A DECEMBER bill for NOVEMBER sales is ours — we do not give away the month "
        f"we cannot see. "
        f"RULE B - first billed earlier, not excluded: ours on revenue from {CREDIT_START} "
        f"onward, because PS took over CS. We do NOT claim their pre-freeze revenue. "
        f"deal_source is PROVENANCE (so we pay partners correctly), NEVER a gate on what is "
        f"ours. ''never_billed'' means the brand has produced nothing — not that it is not ours.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_eligibility.first_billed_month IS "
        "'THE ANCHOR for eligibility — the earliest Stripe month carrying a positive "
        "usage-fee line. Replaces connection_event_at (onboarding), which was both the wrong "
        "rule AND had a coverage hole: it only exists for brands in the Slack brand feed, so "
        "brands billing in Stripe but absent from that feed had no date at all.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_eligibility TO {r}")


def downgrade() -> None:
    # cip_48's onboarding-keyed version is the prior state; recreate it from that migration
    # if ever needed. Dropping here keeps the chain reversible without duplicating 60 lines.
    op.execute("DROP VIEW IF EXISTS lens_ps_eligibility")
