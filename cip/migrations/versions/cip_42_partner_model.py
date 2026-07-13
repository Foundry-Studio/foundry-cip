# foundry: kind=migration domain=client-intelligence-platform
"""cip_42: partner model — contacts, per-product terms, and the `unassigned` state.

Locks the commission model Tim resolved 2026-07-09 (canonical semantics:
china-commission-audit/11-MONEY-FLOW-EXPLAINER.md §"Partner splits + the two aligned
clocks"):

  BASE = the usage fee Wayward charges the brand.
         Connect: fee% x GMV   |   Boost: 10% x ad spend
  PS's rate from Wayward steps down from the brand's kickoff (contract §3.1):
         M1-12: 10%   M13-18: 6%   M19+: 3%     -- all of BASE
  The partner's cut is X% of the SAME BASE (NOT a % of PS's commission), set
  manually per partner x product, and it EXPIRES at month 12 — the same anchor as
  the step-down. So during M1-12, PS nets (10 - X)% of base; from M13 the partner is
  gone and PS keeps its full stepped-down rate. The two clocks are aligned by design,
  which is why PS's net can never go negative.

Three changes:

(a) ps_partner_registry — add company_name + country. Also seed the special
    'unassigned' partner (rate 0). Making `unassigned` a REAL registry row is what
    lets ps_partner_credit.partner_of_record reference it like any other partner,
    while keeping NULL meaning something different:
        'unassigned' = a DECISION: no partner is credited; PS keeps the full 10%.
        NULL         = NOT YET DETERMINED.
    These are different facts and must never collapse into each other (same
    principle as the china / not-china / unknown decision column).
    Boost defaults to 'unassigned' — nobody earns on Boost unless we say so.

(b) ps_partner_contacts — a child table, NOT "up to 4 contact columns". Hardcode a
    limit and you hit limit+1. Unlimited contacts per partner.

(c) ps_partner_terms — the manually-entered contract rate, per partner x product,
    effective-dated. commission_pct is a % OF THE USAGE-FEE BASE, constrained to
    0..10 (a partner rate above PS's own 10% during M1-12 is a data error, not a
    generous contract). commission_basis is stored explicitly so the number can
    never be misread as "% of PS's commission" again.

Also seeds PS's own step-down tiers into ps_rate_cards (ps_facing), which closes the
old G2 "tier trigger" open question — the contract answers it.

Revision ID: cip_42_partner_model
Revises: cip_41_brand_observations
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_42_partner_model"
down_revision: str | Sequence[str] | None = "cip_41_brand_observations"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
_NEW = ("ps_partner_contacts", "ps_partner_terms")


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON {table} "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON {table} TO {role}")


def upgrade() -> None:
    # ── (a) registry: company + country ──────────────────────────────────────
    op.execute(
        """
        ALTER TABLE ps_partner_registry
            ADD COLUMN IF NOT EXISTS company_name TEXT,
            ADD COLUMN IF NOT EXISTS country TEXT
        """
    )

    # ── (b) contacts — unlimited per partner ─────────────────────────────────
    op.execute(
        """
        CREATE TABLE ps_partner_contacts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            partner_id TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT,
            email TEXT,
            phone TEXT,
            wechat TEXT,
            is_primary BOOLEAN NOT NULL DEFAULT false,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','inactive')),
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_partner_contacts_partner "
        "ON ps_partner_contacts (tenant_id, partner_id)"
    )

    # ── (c) terms — manual, per partner x product, effective-dated ───────────
    op.execute(
        """
        CREATE TABLE ps_partner_terms (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            partner_id TEXT NOT NULL,
            product_id TEXT NOT NULL,

            -- X% of the USAGE-FEE BASE (the same base as PS's own 10%).
            -- NOT a percentage of PS's commission. 0..10 — above 10 would mean
            -- paying out more than Wayward pays us during M1-12.
            commission_pct NUMERIC(5,2) NOT NULL
                CHECK (commission_pct >= 0 AND commission_pct <= 10),
            commission_basis TEXT NOT NULL DEFAULT 'pct_of_usage_fee'
                CHECK (commission_basis IN ('pct_of_usage_fee')),

            -- The partner's cut expires 12 months after the brand's kickoff — the
            -- SAME anchor as the contract §3.1 step-down. Held here for reference;
            -- the per-brand window lives on ps_partner_credit.credit_start/_end.
            credit_window_months INTEGER NOT NULL DEFAULT 12,

            effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
            effective_to TIMESTAMPTZ,
            contract_ref TEXT,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, partner_id, product_id, effective_from)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_partner_terms_lookup "
        "ON ps_partner_terms (tenant_id, partner_id, product_id)"
    )

    for t in _NEW:
        _rls(t)

    # ── Seeds ───────────────────────────────────────────────────────────────
    # 'unassigned' is a REAL partner row so partner_of_record can point at it.
    # NULL still means "not yet determined" — a different fact.
    op.execute(
        f"""
        INSERT INTO ps_partner_registry
            (tenant_id, partner_id, name, company_name, default_rate, status, notes)
        VALUES (
            '{PS_TENANT}', 'unassigned', '(unassigned - no partner credit)', NULL, 0,
            'active',
            'Explicit DECISION that no partner earns on this brand x product; PS keeps the full 10%. Distinct from NULL, which means not yet determined. Boost defaults here.'
        )
        ON CONFLICT (tenant_id, partner_id) DO NOTHING
        """
    )
    # Boost earns nobody anything unless we say so.
    op.execute(
        f"""
        INSERT INTO ps_partner_terms
            (tenant_id, partner_id, product_id, commission_pct, notes)
        VALUES
            ('{PS_TENANT}', 'unassigned', 'connect', 0, 'No partner credit -> PS keeps the full 10%.'),
            ('{PS_TENANT}', 'unassigned', 'boosted', 0, 'Boost is wide open by default: no partner earns unless explicitly assigned.')
        ON CONFLICT DO NOTHING
        """
    )
    # PS's own step-down from Wayward (contract §3.1) — closes the old G2 question.
    # Anchored per-brand on the kickoff / Rev-Share-Start (Productive) date.
    op.execute(
        f"""
        INSERT INTO ps_rate_cards
            (tenant_id, kind, product_id, commission_pct, commission_base, tier_rule, source, effective_from)
        VALUES
            ('{PS_TENANT}','ps_facing','connect',10,'usage_fee','M1-12 from kickoff','contract 3.1', now()),
            ('{PS_TENANT}','ps_facing','connect', 6,'usage_fee','M13-18 from kickoff','contract 3.1', now()),
            ('{PS_TENANT}','ps_facing','connect', 3,'usage_fee','M19+ from kickoff','contract 3.1', now()),
            ('{PS_TENANT}','ps_facing','boosted',10,'usage_fee','M1-12 from kickoff','contract 3.1', now()),
            ('{PS_TENANT}','ps_facing','boosted', 6,'usage_fee','M13-18 from kickoff','contract 3.1', now()),
            ('{PS_TENANT}','ps_facing','boosted', 3,'usage_fee','M19+ from kickoff','contract 3.1', now())
        ON CONFLICT DO NOTHING
        """
    )

    # Self-documenting the one distinction most likely to be lost.
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.partner_of_record IS "
        "'FK-by-value into ps_partner_registry.partner_id. "
        "''unassigned'' = a DECISION (no partner earns; PS keeps the full 10%). "
        "NULL = NOT YET DETERMINED. These are different facts — never collapse them.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_partner_terms.commission_pct IS "
        "'X%% of the USAGE-FEE BASE (same base as PS''s 10%%), NOT a %% of PS''s "
        "commission. PS nets (10 - X)%% during M1-12; the partner expires at M12.'"
    )


def downgrade() -> None:
    op.execute("COMMENT ON COLUMN ps_partner_credit.partner_of_record IS NULL")
    op.execute(
        "DELETE FROM ps_rate_cards WHERE kind='ps_facing' AND source='contract 3.1'"
    )
    op.execute("DELETE FROM ps_partner_terms WHERE partner_id='unassigned'")
    op.execute("DELETE FROM ps_partner_registry WHERE partner_id='unassigned'")
    for t in reversed(_NEW):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute(
        """
        ALTER TABLE ps_partner_registry
            DROP COLUMN IF EXISTS country,
            DROP COLUMN IF EXISTS company_name
        """
    )
