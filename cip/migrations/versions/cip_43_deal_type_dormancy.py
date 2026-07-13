# foundry: kind=migration domain=client-intelligence-platform
"""cip_43: deal_type (flat-fee vs rev-share), per-product dormancy, reactivation rights.

Locks the rules Tim set 2026-07-13. The whole point of this migration is that the
MEANING travels with the data: every semantic column below carries a COMMENT, so an
agent (or a human) reading the schema cold cannot misinterpret what a flag means.

THE RULES
---------
1. Eric's ~845 "flat fee" brands are CONNECT, attributed to Eric, under a FLAT-FEE
   deal. He was paid once. He earns NO ongoing revenue on them. We still track their
   performance — attribution is a fact about who brought the brand, NOT a claim on
   future money. That is exactly why deal_type is a separate column from
   partner_of_record: WHO gets credit and WHETHER money flows are different questions.

2. A Connect flat-fee attribution DOES NOT lock Boost. Boost stays wide open
   ('unassigned' — cip_42) unless a partner is *specifically* attributed on Boost.
   So PS sales staff can target every one of these brands for Boost and PS keeps the
   full 10%. Attribution is per (brand x PRODUCT) — that grain is what makes this
   expressible at all.

3. DORMANT = no activity for 90 days, evaluated PER PRODUCT. A dormant brand becomes
   fair game for reactivation — by PS or by a partner. Dormancy is a DERIVED
   observation about activity; reactivation eligibility is a DECISION. They are
   deliberately separate columns (facts vs conclusions, same as nationality_class).

4. Partners will claim they referred brands to Eric under the old flat-fee deal and
   are therefore owed a reactivation. Those claims are EVIDENCE
   (ps_brand_observations, source_system='partner_claim:<partner>') and will conflict
   with Eric's own tracking. The conflict is a finding, not a bug.

Revision ID: cip_43_deal_type_dormancy
Revises: cip_42_partner_model
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_43_deal_type_dormancy"
down_revision: str | Sequence[str] | None = "cip_42_partner_model"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

DORMANCY_DAYS = 90


def upgrade() -> None:
    # ── 1. deal_type — WHO gets credit vs WHETHER money flows are different ──
    # deal_type belongs on ps_partner_credit, NOT ps_attribution: partner_of_record and
    # partner_rate live there, and deal_type answers "does money still flow to that
    # partner?" — a partner-economics question. ps_attribution is about PS's own
    # ownership of the brand (ps_sales_lead / ps_cs_lead), which is a different axis.
    op.execute(
        """
        ALTER TABLE ps_partner_credit
            ADD COLUMN IF NOT EXISTS deal_type TEXT
                CHECK (deal_type IS NULL OR deal_type IN
                       ('rev_share','flat_fee','none')),
            ADD COLUMN IF NOT EXISTS deal_type_source TEXT,
            ADD COLUMN IF NOT EXISTS flat_fee_paid_at TIMESTAMPTZ
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.deal_type IS "
        "'The COMMERCIAL nature of the partner''s credit — deliberately SEPARATE from "
        "partner_of_record, because WHO brought the brand and WHETHER money still "
        "flows to them are different questions. "
        "''flat_fee'' = the partner was paid ONCE and earns NO ongoing revenue. This "
        "is Eric''s pre-contract Connect book (~845 brands). We KEEP the attribution "
        "so performance stays trackable and we know whose relationship it is — it is "
        "NOT a claim on future money, and partner_rate must be ignored when "
        "deal_type=''flat_fee''. "
        "''rev_share'' = the partner earns an ongoing %% of the usage fee per "
        "ps_partner_terms, expiring 12 months from kickoff. "
        "''none'' = no partner economics at all. "
        "NULL = NOT YET DETERMINED (not the same as ''none'').'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.deal_type_source IS "
        "'Where the deal_type determination came from (e.g. "
        "''gsheet:eric-all-agreements'', ''contract:exhibit-a'', ''human:tim''). "
        "Sources DISAGREE: Eric''s sheet marks 548 brands flat-fee that the "
        "contract''s Exhibit-A does NOT exclude. Keep the provenance — the "
        "disagreement is a finding, not a bug.'"
    )

    # ── 2. Dormancy — per brand x PRODUCT. A fact about activity. ────────────
    # NOTE: is_dormant is deliberately NOT a stored column.
    # (a) Postgres rejects a GENERATED column over now() — it is not immutable.
    # (b) More importantly, a STORED dormancy flag goes stale the moment the clock
    #     moves: a brand would sit marked "active" for days after it actually went
    #     quiet, and sales would skip a brand that is in fact fair game. Dormancy is
    #     a function of TIME, so it must be evaluated at READ time.
    # We store the FACT (last_activity_at) and derive the FLAG in the lens below.
    op.execute(
        """
        ALTER TABLE ps_product_subscriptions
            ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS activity_source TEXT,
            ADD COLUMN IF NOT EXISTS dormant_since TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS dormancy_evaluated_at TIMESTAMPTZ
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.last_activity_at IS "
        "'The most recent evidence of activity on this product — the FACT from which "
        "dormancy is derived. activity_source records WHAT was measured (e.g. "
        "''ps_payment_events.usage_fees_paid>0''), because ''activity'' is a "
        "definition and the definition must travel with the number. "
        "Dormancy itself (no activity for 90 days) is computed at READ time in "
        "lens_ps_brand_opportunity — never stored, because a stored time-based flag "
        "is stale the moment the clock moves. NULL => never active => NOT dormant "
        "(you cannot go quiet if you never spoke).'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ps_subs_activity "
        "ON ps_product_subscriptions (tenant_id, product_id, last_activity_at)"
    )

    # ── 3. Reactivation — a DECISION layered on top of the dormancy fact ─────
    op.execute(
        """
        CREATE TABLE ps_reactivation_rights (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            client_id UUID,
            wayward_brand_id UUID,
            product_id TEXT NOT NULL,

            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','claimed','won','lost','blocked')),
            claimed_by TEXT,
            claimed_at TIMESTAMPTZ,
            won_at TIMESTAMPTZ,

            -- A reactivation re-starts the clocks. See the column comment.
            new_kickoff_at TIMESTAMPTZ,

            blocked_reason TEXT,
            rationale TEXT,
            decided_by TEXT,
            decided_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, wayward_brand_id, product_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ps_reactivation_rights IS "
        "'Who may go after a dormant brand, per PRODUCT. The rule (Tim, 2026-07-13): "
        "a partner (or PS) may activate a DORMANT brand on Connect, or ANY brand on "
        "Boost — UNLESS a partner is specifically attributed on Boost for that brand. "
        "An Eric flat-fee Connect attribution does NOT block Boost. "
        "UNIQUE(brand, product) is the double-claim guard: two partners cannot both "
        "hold the same brand x product.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_reactivation_rights.claimed_by IS "
        "'ps_partner_registry.partner_id, or ''unassigned'' when PS sales is working "
        "it directly (PS then keeps the full 10%%). Partners WILL claim they referred "
        "a brand to Eric under the old flat-fee deal; such claims arrive as evidence "
        "(ps_brand_observations, source_system=''partner_claim:<partner>'') and may "
        "contradict Eric''s tracking. Record both; decide here.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_reactivation_rights.new_kickoff_at IS "
        "'OPEN QUESTION (raised 2026-07-13, not yet answered): does a reactivation "
        "restart the contract 3.1 step-down (10/6/3) and the 12-month partner window "
        "from a NEW kickoff date? Contract 3.2 mentions earn-backs on reactivations "
        "(Lysoatur/OpenLight), so the concept exists — the exact clock rule does not "
        "yet. Left NULL until Tim/the contract answers. DO NOT infer it.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_reactivation_rights TO {r}")
    op.execute("ALTER TABLE ps_reactivation_rights ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_reactivation_rights FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON ps_reactivation_rights "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )

    # ── 4. The lens PS sales actually filters on ─────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_brand_opportunity AS
        SELECT
            c.id                AS client_id,
            c.tenant_id,
            c.name              AS brand_name,
            c.wayward_brand_id,
            c.nationality_class,
            c.exhibit_a,

            con.partner_of_record   AS connect_partner,
            con.deal_type           AS connect_deal_type,
            bst.partner_of_record   AS boost_partner,
            bst.deal_type           AS boost_deal_type,
            att.ps_sales_lead       AS connect_sales_lead,

            cs.last_activity_at     AS connect_last_activity,
            bs.last_activity_at     AS boost_last_activity,

            -- Dormancy derived HERE, at read time, so it can never be stale.
            (cs.last_activity_at IS NOT NULL
             AND cs.last_activity_at < now() - INTERVAL '90 days') AS connect_dormant,
            (bs.last_activity_at IS NOT NULL
             AND bs.last_activity_at < now() - INTERVAL '90 days') AS boost_dormant,

            -- Boost is open unless a partner is SPECIFICALLY attributed on Boost.
            -- 'unassigned' is a decision meaning nobody is credited, so it stays open.
            -- Eric's flat-fee CONNECT attribution does NOT close Boost.
            (bst.partner_of_record IS NULL
             OR bst.partner_of_record = 'unassigned')          AS boost_open_to_ps,

            -- Connect can be reactivated only once the brand has gone dormant.
            COALESCE(
                cs.last_activity_at < now() - INTERVAL '90 days', false
            )                                                  AS connect_reactivatable
        FROM cip_clients c
        -- partner economics (who is credited, and does money still flow to them)
        LEFT JOIN ps_partner_credit con
               ON con.client_id = c.id AND con.product_id = 'connect'
              AND (con.credit_end IS NULL OR con.credit_end > now())
        LEFT JOIN ps_partner_credit bst
               ON bst.client_id = c.id AND bst.product_id = 'boosted'
              AND (bst.credit_end IS NULL OR bst.credit_end > now())
        -- PS's own ownership of the brand (a different axis from partner credit)
        LEFT JOIN ps_attribution att
               ON att.client_id = c.id AND att.product_id = 'connect'
              AND att.effective_to IS NULL
        LEFT JOIN ps_product_subscriptions cs
               ON cs.client_id = c.id AND cs.product_id = 'connect'
        LEFT JOIN ps_product_subscriptions bs
               ON bs.client_id = c.id AND bs.product_id = 'boosted'
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_brand_opportunity IS "
        "'The sales-targeting lens. boost_open_to_ps = every brand PS may pursue on "
        "Boost keeping the full 10%% (i.e. no partner specifically attributed on "
        "Boost) — including all of Eric''s flat-fee Connect brands. "
        "connect_reactivatable = dormant on Connect, therefore fair game. "
        "Read 11-MONEY-FLOW-EXPLAINER.md before interpreting any of this.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_brand_opportunity TO {r}")
    # Lens registration per D-121 (same shape as cip_40).
    _desc = (
        "Sales targeting: which brands PS may pursue on Boost keeping the full 10% "
        "(no partner specifically attributed on Boost - includes all of Eric's "
        "flat-fee Connect book), and which Connect brands are dormant and therefore "
        "reactivatable."
    ).replace("'", "''")  # SQL-escape: "Eric's" would otherwise close the literal
    op.execute(
        f"""
        INSERT INTO cip_views (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            view_name, description, filter_config,
            owner_type, owner_id, is_default, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), '{PS_TENANT}', NULL, 'lens-mirror',
            'ps_brand_opportunity',
            NOW(), NOW(), gen_random_uuid(), 'validated',
            'lens_ps_brand_opportunity', '{_desc}',
            '{{"slug": "ps_brand_opportunity", "sql_view": "lens_ps_brand_opportunity", "filter_kind": "ps_brand_opportunity", "phase": "2.9"}}'::jsonb,
            'system', 'cip', false, NOW(), NOW()
        )
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM cip_views WHERE view_name='lens_ps_brand_opportunity'")
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_opportunity")
    op.execute("DROP TABLE IF EXISTS ps_reactivation_rights CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_ps_subs_activity")
    op.execute(
        """
        ALTER TABLE ps_product_subscriptions
            DROP COLUMN IF EXISTS dormancy_evaluated_at,
            DROP COLUMN IF EXISTS dormant_since,
            DROP COLUMN IF EXISTS activity_source,
            DROP COLUMN IF EXISTS last_activity_at
        """
    )
    op.execute(
        """
        ALTER TABLE ps_partner_credit
            DROP COLUMN IF EXISTS flat_fee_paid_at,
            DROP COLUMN IF EXISTS deal_type_source,
            DROP COLUMN IF EXISTS deal_type
        """
    )
