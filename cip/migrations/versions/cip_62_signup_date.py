# foundry: kind=migration domain=client-intelligence-platform
"""cip_62: signup_date, and eligibility that actually tests what Tim said.

THE RULES, AS TIM STATED THEM
-----------------------------
  "Set a date of Nov 18th, AND brand onboarded AFTER that, we get full credit AUTOMATICALLY,
   no matter the referral source, as long as they are in China."

  "ALSO, there are brands that they onboarded before the takeover, but starting with DECEMBER
   BILLINGS, we STILL GET CREDIT if they are in China, as we are handling the CS and everything."

Two rules, and they test DIFFERENT THINGS:

    Rule A  ONBOARDING  > 2025-11-18                      -> ours, whatever the referral source
    Rule B  onboarded on/before the freeze, not excluded,
            but BILLED from December 2025 onward          -> ours (we run the CS)

lens_ps_eligibility was testing `first_billed_month >= 2025-11-01` for BOTH. Wrong field for
Rule A (billing is not onboarding — a brand can onboard in December and not bill until March),
and the wrong date besides (Nov 1, not Nov 18). It even parsed the onboarding date into a column
called `onboarded`, exposed it, and then never referenced it in the CASE.

THE DATA VALIDATES THE FREEZE DATE INDEPENDENTLY
------------------------------------------------
    onboarded AFTER  2025-11-18:  677 brands, of which  0  are on the exclusion list
    onboarded ON/BEFORE it:       671 brands, of which 343 are

Zero overlap on one side, heavy overlap on the other. That is exactly what a list frozen on
2025-11-18 must look like: nothing onboarded after the freeze can possibly be on it. The
boundary is real, and it is 2025-11-18 — not 2025-11-01, and not the contract's later signing
date.

signup_date
-----------
ps_brands had no date at all except first_seen_at, which records when WE learned of a brand —
useless for a rule about when WAYWARD onboarded it. Sources, strongest first:

    slack_feed      connection_event_at from the onboarding feed. The actual onboarding EVENT.
                    1,347 brands.
    stripe_customer the Stripe customer's created date. 5,351 brands — far broader, but it is
                    when BILLING was set up, which is a proxy for onboarding and not the thing
                    itself. Recorded as such so nobody mistakes reach for accuracy.
    payment_report  Jake's stated signup_date. 590 brands.

Recorded with its source, because a Rule-A decision worth ~$X per brand should never rest on a
date whose provenance nobody can see.

Revision ID: cip_62_signup_date
Revises: cip_61_partner_credit_key
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_62_signup_date"
down_revision: str | Sequence[str] | None = "cip_61_partner_credit_key"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

FREEZE = "2025-11-18"   # the day Jake sent Tim the frozen exclusion list
RULE_B = "2025-12-01"   # December billings onward, we run the CS


def upgrade() -> None:
    op.execute("ALTER TABLE ps_brands ADD COLUMN IF NOT EXISTS signup_date DATE")
    op.execute("ALTER TABLE ps_brands ADD COLUMN IF NOT EXISTS signup_date_source TEXT")
    op.execute(
        """
        ALTER TABLE ps_brands DROP CONSTRAINT IF EXISTS ck_ps_brands_signup_source;
        ALTER TABLE ps_brands ADD CONSTRAINT ck_ps_brands_signup_source CHECK (
            (signup_date IS NULL AND signup_date_source IS NULL)
         OR (signup_date IS NOT NULL AND signup_date_source IN
                ('slack_feed', 'payment_report', 'stripe_customer'))
        )
        """
    )
    op.execute(
        f"COMMENT ON COLUMN ps_brands.signup_date IS "
        f"'When WAYWARD onboarded this brand. Load-bearing: a brand onboarded AFTER "
        f"{FREEZE} is ours automatically, whatever the referral source, if it is Chinese "
        f"(Tim, 2026-07-13). Distinct from first_seen_at, which is when WE first learned the "
        f"brand exists and is useless for this rule. Always read signup_date_source with it.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_brands.signup_date_source IS "
        "'slack_feed = the onboarding EVENT from #amazon-brand-connections — the real thing, "
        "1,347 brands. stripe_customer = when the Stripe customer was created — 5,351 brands, "
        "far broader, but it is when BILLING was set up, a PROXY for onboarding and not the "
        "event itself. payment_report = Jake''s stated signup date. Reach is not accuracy: a "
        "Rule-A decision must never rest on a date whose provenance nobody can see.'"
    )

    # ── backfill, strongest source first ────────────────────────────────────
    # 1. the onboarding event itself: "November 18, 2025 at 9:44 PM"
    op.execute(
        """
        UPDATE ps_brands b
           SET signup_date = to_date(split_part(o.value, ' at ', 1), 'FMMonth DD, YYYY'),
               signup_date_source = 'slack_feed',
               updated_at = now()
          FROM (SELECT wayward_brand_id, max(value) AS value
                  FROM ps_brand_observations
                 WHERE field = 'connection_event_at' AND value IS NOT NULL
                 GROUP BY wayward_brand_id) o
         WHERE o.wayward_brand_id = b.wayward_brand_id
           AND b.signup_date IS NULL
        """
    )
    # 2. Jake's stated signup date
    op.execute(
        """
        UPDATE ps_brands b
           SET signup_date = p.signup_date::date,
               signup_date_source = 'payment_report',
               updated_at = now()
          FROM (SELECT wayward_brand_id, min(signup_date) AS signup_date
                  FROM ps_payment_events
                 WHERE signup_date IS NOT NULL AND wayward_brand_id IS NOT NULL
                 GROUP BY wayward_brand_id) p
         WHERE p.wayward_brand_id = b.wayward_brand_id
           AND b.signup_date IS NULL
        """
    )
    # 3. Stripe customer creation — broad reach, weaker meaning. Explicitly last.
    op.execute(
        """
        UPDATE ps_brands b
           SET signup_date = s.created::date,
               signup_date_source = 'stripe_customer',
               updated_at = now()
          FROM (SELECT wayward_brand_id, min(created_at_stripe) AS created
                  FROM ps_stripe_customers
                 WHERE created_at_stripe IS NOT NULL AND wayward_brand_id IS NOT NULL
                 GROUP BY wayward_brand_id) s
         WHERE s.wayward_brand_id = b.wayward_brand_id
           AND b.signup_date IS NULL
        """
    )

    # ── eligibility, rebuilt on the rules as stated ─────────────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_eligibility CASCADE")
    op.execute(
        f"""
        CREATE VIEW lens_ps_eligibility AS
        WITH billed AS (
            SELECT wayward_brand_id,
                   min(billing_month)                    AS first_billed_month,
                   max(client_id::text)::uuid            AS client_id
            FROM ps_stripe_invoice_lines
            WHERE is_ps_base AND amount > 0
              AND billing_month IS NOT NULL AND wayward_brand_id IS NOT NULL
            GROUP BY wayward_brand_id
        ),
        obs AS (
            SELECT wayward_brand_id,
                   max(client_id::text)::uuid                                 AS client_id,
                   max(value) FILTER (WHERE field = 'brand_name')             AS brand_name,
                   max(value) FILTER (WHERE field = 'country')                AS wayward_country,
                   max(value) FILTER (WHERE field = 'deal_source')            AS deal_source
            FROM ps_brand_observations
            GROUP BY wayward_brand_id
        )
        SELECT
            br.wayward_brand_id,
            COALESCE(b.client_id, obs.client_id)                              AS client_id,
            COALESCE(obs.brand_name, br.brand_name)                           AS brand_name,
            b.first_billed_month,
            br.signup_date                                                    AS onboarded,
            br.signup_date_source                                             AS onboarded_source,
            obs.deal_source,
            obs.wayward_country,
            c.nationality_class,
            x.bucket                                                          AS excluded_bucket,
            x.winback_path,
            (x.wayward_brand_id IS NOT NULL)                                  AS is_excluded,
            (c.nationality_class IN ('chinese_confirmed','chinese_suspected')
             OR obs.wayward_country = 'CN')                                   AS is_chinese,
            (br.signup_date > DATE '{FREEZE}')                                AS post_takeover,
            CASE
                WHEN x.wayward_brand_id IS NOT NULL                THEN 'excluded'
                WHEN NOT (c.nationality_class IN ('chinese_confirmed','chinese_suspected')
                          OR obs.wayward_country = 'CN')           THEN 'not_chinese'
                -- Rule A: onboarded after the freeze. Ours, whatever the referral source.
                WHEN br.signup_date > DATE '{FREEZE}'              THEN 'eligible_rule_a'
                -- Rule B: onboarded before it, but billing from December — we run the CS.
                WHEN b.first_billed_month >= DATE '{RULE_B}'       THEN 'eligible_rule_b'
                WHEN b.first_billed_month IS NULL                  THEN 'never_billed'
                ELSE 'pre_takeover_no_dec_billing'
            END                                                               AS eligibility,
            CASE
                WHEN x.wayward_brand_id IS NOT NULL                THEN NULL
                WHEN br.signup_date > DATE '{FREEZE}'              THEN b.first_billed_month
                WHEN b.first_billed_month >= DATE '{RULE_B}'       THEN DATE '{RULE_B}'
                ELSE NULL
            END                                                               AS credit_starts
        FROM ps_brands br
        LEFT JOIN billed b       ON b.wayward_brand_id   = br.wayward_brand_id
        LEFT JOIN obs            ON obs.wayward_brand_id = br.wayward_brand_id
        LEFT JOIN ps_excluded_brands x ON x.wayward_brand_id = br.wayward_brand_id
        LEFT JOIN cip_clients c  ON c.id = COALESCE(b.client_id, obs.client_id)
        """
    )
    op.execute(
        f"COMMENT ON VIEW lens_ps_eligibility IS "
        f"'Is this brand ours to claim? Rule A: ONBOARDED after {FREEZE} (the day Jake sent the "
        f"frozen exclusion list) — ours automatically, whatever the referral source, if Chinese. "
        f"Rule B: onboarded on/before the freeze and not excluded, but billing from {RULE_B} "
        f"onward — ours, because we run the CS. These test DIFFERENT FIELDS: Rule A tests "
        f"onboarding, Rule B tests billing. The previous version tested billing for BOTH, against "
        f"2025-11-01 rather than the {FREEZE} freeze, and silently ignored the onboarding date it "
        f"had already parsed. Proof the boundary is real: of 677 brands onboarded after the "
        f"freeze, ZERO are on the exclusion list.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_eligibility TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_eligibility CASCADE")
    op.execute("ALTER TABLE ps_brands DROP CONSTRAINT IF EXISTS ck_ps_brands_signup_source")
    op.execute("ALTER TABLE ps_brands DROP COLUMN IF EXISTS signup_date_source")
    op.execute("ALTER TABLE ps_brands DROP COLUMN IF EXISTS signup_date")
