# foundry: kind=migration domain=client-intelligence-platform
"""cip_50: the PRODUCTIVE DATE, per brand x PRODUCT — the clock everything else hangs on.

WHAT WAS BROKEN
---------------
Until now CIP had NOTHING to run the 10/6/3 step-down from. Every rate we computed was
unanchored. Contract §1.5 is explicit, and it is NOT the onboarding date:

    "'Productive' means the date of the FIRST TRACKED SALE of a Revenue Share Eligible
     Brand's product through Qualifying Links on the Wayward Platform that is INCLUDED IN
     A PAYABLE INVOICE by Wayward, in accordance with Wayward's records."

And §3.1(a): our 10% is "measured FROM THE PRODUCTIVE DATE through the end of the 365th day
thereafter." So a brand that onboarded in June but first sold in December starts its 12
months in DECEMBER.

PER PRODUCT (Tim, 2026-07-13)
-----------------------------
Connect and Boost carry SEPARATE clocks. Boost launched later, so a brand is routinely
partway through its Connect window while its Boost window has not started at all. A single
brand-level productive date would silently misprice one of the two. ps_product_subscriptions
is already keyed (client_id, product_id), so the clock lives there — one row, one product,
one clock.

HOW WE DETERMINE IT (three sources, ranked — they WILL disagree, so we keep all three)
  1. stripe               - the earliest invoice carrying a USAGE-FEE line for that brand x
                            product. This IS the contract's definition ("first tracked sale
                            included in a payable invoice"), so Stripe is not a proxy — it is
                            the source.
  2. wayward_stated       - Wayward's own "Rev Share Start Date" from the monthly report.
                            Their claim. §4.4 makes their records "conclusive", so a
                            disagreement with Stripe is worth knowing about.
  3. fallback_month_start - if we can only see the billing MONTH, use the 1st of that month
                            (Tim's rule). A brand first billed in December => 2025-12-01.

EXPIRIES are GENERATED from the productive date — pure date arithmetic, which IS immutable
(unlike the dormancy flag, which depends on now() and therefore must be computed at read
time; see cip_43). Storing them makes "how much revenue rolls off in March?" a plain indexed
query instead of a recomputation.

Revision ID: cip_50_productive_dates
Revises: cip_49_stripe_invoices
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_50_productive_dates"
down_revision: str | Sequence[str] | None = "cip_49_stripe_invoices"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

SOURCES = ("stripe", "wayward_stated", "fallback_month_start", "human")
CONFIDENCE = ("confirmed", "probable", "unknown")


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE ps_product_subscriptions
            ADD COLUMN IF NOT EXISTS productive_date DATE,
            ADD COLUMN IF NOT EXISTS productive_date_source TEXT
                CHECK (productive_date_source IS NULL OR productive_date_source IN
                       ({", ".join(f"'{s}'" for s in SOURCES)})),
            ADD COLUMN IF NOT EXISTS productive_date_confidence TEXT
                CHECK (productive_date_confidence IS NULL OR productive_date_confidence IN
                       ({", ".join(f"'{c}'" for c in CONFIDENCE)})),
            ADD COLUMN IF NOT EXISTS productive_date_note TEXT,
            ADD COLUMN IF NOT EXISTS productive_date_wayward DATE,
            ADD COLUMN IF NOT EXISTS first_billed_month DATE
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.productive_date IS "
        "'THE CLOCK. Contract §1.5: the date of the FIRST TRACKED SALE included in a PAYABLE "
        "INVOICE — NOT the onboarding date. §3.1(a) measures our 10%% from here through the "
        "365th day. PER PRODUCT: Connect and Boost run SEPARATE clocks (Boost launched later, "
        "so a brand is routinely partway through Connect while Boost has not started). "
        "A single brand-level date would misprice one of them.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.productive_date_source IS "
        "'''stripe'' = earliest invoice with a usage-fee line for this brand x product. This "
        "IS the contract''s definition, so Stripe is the SOURCE, not a proxy. "
        "''wayward_stated'' = Wayward''s own Rev Share Start Date (their claim — §4.4 makes "
        "their records ''conclusive'', so a disagreement with Stripe matters). "
        "''fallback_month_start'' = we could only see the billing MONTH, so we used the 1st "
        "of it (Tim''s rule: first billed in December => 2025-12-01). "
        "productive_date_wayward keeps THEIR value alongside ours — we never overwrite a "
        "source with a derivation.'"
    )

    # Expiries: pure date+integer / date+interval arithmetic is IMMUTABLE, so these can be
    # GENERATED and indexed. (Contrast cip_43's dormancy flag, which depends on now() and
    # therefore MUST be computed at read time — Postgres rejected it, correctly.)
    op.execute(
        """
        ALTER TABLE ps_product_subscriptions
            ADD COLUMN IF NOT EXISTS rate_10_expires DATE
                GENERATED ALWAYS AS (productive_date + 365) STORED,
            ADD COLUMN IF NOT EXISTS partner_credit_expires DATE
                GENERATED ALWAYS AS (productive_date + 365) STORED,
            ADD COLUMN IF NOT EXISTS rate_6_expires DATE
                GENERATED ALWAYS AS (productive_date + 365 + 183) STORED
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.rate_10_expires IS "
        "'productive_date + 365 days. On this date we drop 10%% -> 6%% ON THIS PRODUCT "
        "(§3.1(a)-(b)).'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.rate_6_expires IS "
        "'End of the 6%% band -> we drop to 3%% (§3.1(c)). Approximated as +183 days after "
        "the 365-day window; the contract says ''exactly six (6) months'', which is a "
        "CALENDAR interval, but a calendar cast is not immutable and so cannot be GENERATED. "
        "For anything billable, recompute the exact calendar month boundary — this column is "
        "for filtering and roll-off forecasting, not for invoicing.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.partner_credit_expires IS "
        "'The partner''s 5%% ends 12 months from the SAME anchor. Note the pleasant "
        "consequence: our NET goes UP at this date (5%% -> 6%%), because the partner rolls "
        "off at exactly the moment our own rate steps down to 6%%. Aligned by design — it is "
        "why our net can never go negative.'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ps_subs_rollover ON ps_product_subscriptions "
        "(tenant_id, product_id, rate_10_expires)"
    )

    # ── The rate lens: what rate are we on TODAY, per brand x product ───────
    op.execute(
        """
        CREATE VIEW lens_ps_rate_clock AS
        SELECT
            s.tenant_id,
            s.client_id,
            s.product_id,
            s.productive_date,
            s.productive_date_source,
            s.productive_date_confidence,
            s.rate_10_expires,
            s.rate_6_expires,
            s.partner_credit_expires,

            -- Which tier are we in RIGHT NOW? Time-dependent => read-time, never stored.
            CASE
                WHEN s.productive_date IS NULL          THEN NULL
                WHEN CURRENT_DATE <= s.rate_10_expires  THEN 10
                WHEN CURRENT_DATE <= s.rate_6_expires   THEN 6
                ELSE 3
            END                                                  AS current_rate_pct,

            (s.productive_date IS NOT NULL
             AND CURRENT_DATE <= s.partner_credit_expires)       AS partner_still_earning,

            CASE
                WHEN s.productive_date IS NULL THEN NULL
                ELSE (s.rate_10_expires - CURRENT_DATE)
            END                                                  AS days_until_10_drops
        FROM ps_product_subscriptions s
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_rate_clock IS "
        "'What rate are we on TODAY, per brand x PRODUCT (10 / 6 / 3), and when does it drop. "
        "current_rate_pct is computed at READ time because it depends on today''s date — a "
        "stored tier would be wrong the morning after it changed. "
        "Feed days_until_10_drops into a roll-off report to answer ''how much revenue steps "
        "down in March?''. Connect and Boost have SEPARATE clocks, so a brand can be at 6%% on "
        "Connect and 10%% on Boost.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_rate_clock TO {r}")

    _d = (
        "The rate clock per brand x product: productive date, current 10/6/3 tier, and when "
        "it steps down. Drives roll-off forecasting."
    ).replace("'", "''")
    op.execute(
        f"""
        INSERT INTO cip_views (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            view_name, description, filter_config,
            owner_type, owner_id, is_default, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), '{PS_TENANT}', NULL, 'lens-mirror', 'ps_rate_clock',
            NOW(), NOW(), gen_random_uuid(), 'validated',
            'lens_ps_rate_clock', '{_d}',
            '{{"slug": "ps_rate_clock", "sql_view": "lens_ps_rate_clock", "filter_kind": "ps_rate_clock", "phase": "3.1"}}'::jsonb,
            'system', 'cip', false, NOW(), NOW()
        )
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM cip_views WHERE view_name='lens_ps_rate_clock'")
    op.execute("DROP VIEW IF EXISTS lens_ps_rate_clock")
    op.execute("DROP INDEX IF EXISTS idx_ps_subs_rollover")
    op.execute(
        """
        ALTER TABLE ps_product_subscriptions
            DROP COLUMN IF EXISTS rate_6_expires,
            DROP COLUMN IF EXISTS partner_credit_expires,
            DROP COLUMN IF EXISTS rate_10_expires,
            DROP COLUMN IF EXISTS first_billed_month,
            DROP COLUMN IF EXISTS productive_date_wayward,
            DROP COLUMN IF EXISTS productive_date_note,
            DROP COLUMN IF EXISTS productive_date_confidence,
            DROP COLUMN IF EXISTS productive_date_source,
            DROP COLUMN IF EXISTS productive_date
        """
    )
