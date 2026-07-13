# foundry: kind=migration domain=client-intelligence-platform
"""cip_51: ps_monthly_earnings — the money spine. Billed -> collected -> owed -> paid -> variance.

WHY
---
Every dashboard Tim wants (partner performance, client performance, what we're owed, the
historical month-by-month series) is a GROUP BY on ONE table. That table did not exist.

What DID exist was `ps_commission_ledger` — the right shape, zero rows, and a genuinely
dangerous name. In this domain "commission" means the CREATOR PASS-THROUGH: it runs ~4x
larger than the usage fee and is NOT our base. A column literally called `commission_base`
invites the exact error that 11-MONEY-FLOW-EXPLAINER.md exists to prevent (an agent made it
on 2026-07-06 and got the money 4x wrong). So this migration renames the table and the
field, and states the trap in the column comment.

    ps_commission_ledger  ->  ps_monthly_earnings
    commission_base       ->  usage_fee_base       ("commission" is the trap word)
    amount_accrued        ->  ps_gross_owed
    amount_received       ->  ps_actually_paid
    split_partner_amt     ->  partner_owed         (+ partner_id, which was missing entirely:
                                                    we stored an amount with no partner on it)

THE CHAIN, per brand x product x month — each step is a separate column, because collapsing
any two of them is how the truth gets lost:

    usage_billed        Stripe amount_due       (what Wayward invoiced the brand)
    usage_collected     Stripe amount_paid      <- we are paid on THIS (contract §4.1(b))
    usage_outstanding   billed - collected      (PIPELINE, not a claim)
      |
    ps_rate_pct         10 / 6 / 3              (the tier that applied THAT month, per product)
    ps_gross_owed       rate x collected
      |
    partner_id / partner_rate_pct / partner_owed
      |
    ps_net_owed         gross - partner
      |
    ps_actually_paid    what Jake actually paid us
    variance            net_owed - actually_paid   <- THE CLAIM
                                                     (GENERATED: it can never drift)

Also drops ps_monthly_snapshots — it was a 5-column stub holding (snapshot_month, rows).
A row counter, not a snapshot. Nothing wrote it and nothing read it.

Revision ID: cip_51_monthly_earnings
Revises: cip_50_productive_dates
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_51_monthly_earnings"
down_revision: str | Sequence[str] | None = "cip_50_productive_dates"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # The old ledger is empty (0 rows) — rename rather than migrate data.
    op.execute("DROP TABLE IF EXISTS ps_commission_ledger CASCADE")
    op.execute("DROP TABLE IF EXISTS ps_monthly_snapshots CASCADE")

    op.execute(
        """
        CREATE TABLE ps_monthly_earnings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,

            client_id UUID,
            wayward_brand_id UUID,
            brand_name TEXT,
            product_id TEXT NOT NULL,           -- connect | boosted
            period_month DATE NOT NULL,         -- always the 1st of the month

            -- 1. THE BASE (from Stripe — the source, not Jake's summary)
            usage_billed NUMERIC(14,2) NOT NULL DEFAULT 0,
            usage_collected NUMERIC(14,2) NOT NULL DEFAULT 0,
            usage_outstanding NUMERIC(14,2)
                GENERATED ALWAYS AS (usage_billed - usage_collected) STORED,

            -- 2. OUR RATE that month (per product — Connect and Boost run separate clocks)
            ps_rate_pct NUMERIC(5,2),
            months_since_productive INTEGER,

            -- 3. WHAT WE EARNED (on cash actually received)
            ps_gross_owed NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * COALESCE(ps_rate_pct, 0) / 100.0, 2)
                ) STORED,

            -- 4. THE PARTNER'S CUT (out of our 10, not on top of it)
            partner_id TEXT,
            partner_rate_pct NUMERIC(5,2),
            partner_owed NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * COALESCE(partner_rate_pct, 0) / 100.0, 2)
                ) STORED,

            -- 5. WHAT WE KEEP
            ps_net_owed NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * COALESCE(ps_rate_pct, 0) / 100.0, 2)
                    - ROUND(usage_collected * COALESCE(partner_rate_pct, 0) / 100.0, 2)
                ) STORED,

            -- 6. WHAT THEY ACTUALLY PAID US, and the gap
            ps_actually_paid NUMERIC(14,2) NOT NULL DEFAULT 0,
            variance NUMERIC(14,2)
                GENERATED ALWAYS AS (
                    ROUND(usage_collected * COALESCE(ps_rate_pct, 0) / 100.0, 2)
                    - ROUND(usage_collected * COALESCE(partner_rate_pct, 0) / 100.0, 2)
                    - ps_actually_paid
                ) STORED,

            -- context, so a row is readable on its own
            eligibility TEXT,                   -- eligible_rule_a | eligible_rule_b | excluded | ...
            excluded_bucket TEXT,
            is_chinese BOOLEAN,

            computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, wayward_brand_id, product_id, period_month)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_earn_month ON ps_monthly_earnings "
        "(tenant_id, period_month, product_id)"
    )
    op.execute(
        "CREATE INDEX idx_ps_earn_partner ON ps_monthly_earnings "
        "(tenant_id, partner_id, period_month)"
    )
    op.execute(
        "CREATE INDEX idx_ps_earn_variance ON ps_monthly_earnings "
        "(tenant_id, variance) WHERE variance <> 0"
    )

    op.execute(
        "COMMENT ON TABLE ps_monthly_earnings IS "
        "'THE MONEY SPINE. One row per brand x product x month, carrying the whole chain: "
        "billed -> collected -> our rate -> gross -> partner split -> net -> what they "
        "actually paid -> VARIANCE. Every dashboard (partner performance, client "
        "performance, what we are owed, the month-by-month history) is a GROUP BY on this "
        "table. "
        "Formerly ps_commission_ledger, which was empty and badly named: in this domain "
        "''commission'' means the CREATOR PASS-THROUGH, ~4x larger than the usage fee and "
        "NOT our base. Naming a column commission_base invited the exact 4x error that "
        "11-MONEY-FLOW-EXPLAINER.md exists to prevent.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.usage_billed IS "
        "'USAGE fees Wayward INVOICED the brand this month (Stripe amount_due). USAGE ONLY — "
        "creator COMMISSION fees are pass-through and are NOT our base. Confusing the two "
        "overstates what we are owed by roughly 4x.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.usage_collected IS "
        "'USAGE fees Wayward actually COLLECTED. THIS is what we are paid on — contract "
        "§4.1(b): ''Revenue Share payment obligation shall not commence until the underlying "
        "funds are actually received.'' Everything downstream is computed from this, never "
        "from usage_billed.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.usage_outstanding IS "
        "'Billed but NOT collected. This is PIPELINE, not a claim — we are owed nothing on it "
        "until the cash lands. Track it so we can see what is coming (and chase Wayward on "
        "collections), but NEVER add it to a claim.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.ps_rate_pct IS "
        "'The tier that applied THAT MONTH for THAT PRODUCT: 10 / 6 / 3, from the brand''s "
        "productive date on that product (§3.1). Connect and Boost step down independently — "
        "a brand can be at 6%% on Connect and 10%% on Boost.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.partner_owed IS "
        "'The partner''s cut, as a %% of the SAME usage-fee base we are paid on — it comes OUT "
        "of our 10, not on top of it. So ps_net_owed = gross - partner. Expires 12 months "
        "from the brand''s productive date, at which point our NET actually RISES (5%% -> 6%%), "
        "because the partner rolls off exactly when our own rate steps to 6%%.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.variance IS "
        "'THE CLAIM: what we should have been paid (ps_net_owed) minus what Wayward actually "
        "paid (ps_actually_paid). GENERATED, so it can never drift from its inputs. "
        "POSITIVE = they underpaid us. NEGATIVE = they overpaid. "
        "Remember §4.4: Wayward''s records are ''conclusive and controlling'' with a 30-DAY "
        "dispute window — a variance found late may be unrecoverable. Watch this column.'"
    )

    op.execute("ALTER TABLE ps_monthly_earnings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_monthly_earnings FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON ps_monthly_earnings "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_monthly_earnings TO {r}")

    # ── Dashboard 1: PARTNER performance, month by month ─────────────────────
    op.execute(
        """
        CREATE VIEW lens_ps_partner_performance AS
        SELECT
            e.tenant_id,
            e.partner_id,
            r.name                              AS partner_name,
            r.company_name,
            e.period_month,
            e.product_id,
            count(DISTINCT e.wayward_brand_id)  AS brands,
            sum(e.usage_billed)                 AS usage_billed,
            sum(e.usage_collected)              AS usage_collected,
            sum(e.usage_outstanding)            AS usage_outstanding,
            sum(e.ps_gross_owed)                AS ps_gross,
            sum(e.partner_owed)                 AS partner_earned,
            sum(e.ps_net_owed)                  AS ps_net,
            sum(e.variance)                     AS variance
        FROM ps_monthly_earnings e
        LEFT JOIN ps_partner_registry r
               ON r.tenant_id = e.tenant_id AND r.partner_id = e.partner_id
        WHERE e.partner_id IS NOT NULL AND e.partner_id <> 'unassigned'
        GROUP BY 1,2,3,4,5,6
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_partner_performance IS "
        "'PARTNER dashboard: per partner, per month, per product — brands, the usage fees "
        "they generated, what THEY earned, what WE netted. partner_earned comes out of our "
        "10%%, never on top of it.'"
    )

    # ── Dashboard 2: CLIENT (brand) performance, month by month ──────────────
    op.execute(
        """
        CREATE VIEW lens_ps_client_performance AS
        SELECT
            e.tenant_id,
            e.client_id,
            e.wayward_brand_id,
            e.brand_name,
            e.period_month,
            e.product_id,
            e.eligibility,
            e.excluded_bucket,
            e.is_chinese,
            e.usage_billed,
            e.usage_collected,
            e.usage_outstanding,
            e.ps_rate_pct,
            e.months_since_productive,
            e.ps_gross_owed,
            e.partner_id,
            e.partner_owed,
            e.ps_net_owed,
            e.ps_actually_paid,
            e.variance
        FROM ps_monthly_earnings e
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_client_performance IS "
        "'CLIENT dashboard: one row per brand x product x month — what they were billed, what "
        "they actually paid Wayward, what rate we were on, what we earned, and whether "
        "Wayward paid us correctly (variance). This is the per-brand history.'"
    )

    for v in ("lens_ps_partner_performance", "lens_ps_client_performance"):
        for r in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {v} TO {r}")
        d = (
            "Partner performance by month" if "partner" in v
            else "Client/brand performance by month"
        )
        op.execute(
            f"""
            INSERT INTO cip_views (
                id, tenant_id, client_id, source_connector, source_id,
                ingested_at, refreshed_at, ingestion_batch_id, authority,
                view_name, description, filter_config,
                owner_type, owner_id, is_default, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), '{PS_TENANT}', NULL, 'lens-mirror', '{v}',
                NOW(), NOW(), gen_random_uuid(), 'validated',
                '{v}', '{d}',
                '{{"slug": "{v}", "sql_view": "{v}", "filter_kind": "{v}", "phase": "3.2"}}'::jsonb,
                'system', 'cip', false, NOW(), NOW()
            )
            ON CONFLICT DO NOTHING
            """
        )

    # Dead column: confidence was never written — confidence lives on DECISIONS, not facts.
    op.execute("ALTER TABLE ps_brand_observations DROP COLUMN IF EXISTS confidence")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ps_brand_observations ADD COLUMN IF NOT EXISTS confidence NUMERIC(4,3)"
    )
    op.execute(
        "DELETE FROM cip_views WHERE view_name IN "
        "('lens_ps_partner_performance','lens_ps_client_performance')"
    )
    op.execute("DROP VIEW IF EXISTS lens_ps_client_performance")
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_performance")
    op.execute("DROP TABLE IF EXISTS ps_monthly_earnings CASCADE")
    op.execute(
        """
        CREATE TABLE ps_monthly_snapshots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            snapshot_month DATE,
            rows INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
