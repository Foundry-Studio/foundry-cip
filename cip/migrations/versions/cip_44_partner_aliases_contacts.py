# foundry: kind=migration domain=client-intelligence-platform
"""cip_44: partner alias map, brand contacts (incl. WeChat), and the rules Tim resolved.

Tim answered the five open questions on 2026-07-13. This migration writes those answers
into the schema — including CORRECTING two comments that previously said "open question".

THE ANSWERS
-----------
1. REACTIVATION RESTARTS THE CLOCKS — for THAT PRODUCT only. A reactivated brand gets a
   NEW kickoff on that product: PS goes back to 10% (contract 3.1 step-down restarts)
   and a fresh 12-month partner window opens. Connect and Boost restart independently.

2. THE 548/845 FLAT-FEE BRANDS: **NOBODY earns the 10% on them today** — not Eric (paid
   once), and NOT PS. They are dead revenue on Connect *until* they go inactive for 90
   days, at which point they become ELIGIBLE for reactivation and PS can earn again.
   (This CORRECTS my earlier speculation that PS might already be entitled to them. It
   is not a claim item. It is an OPPORTUNITY item.)
   BUT: **all of them are open on BOOST right now**, unless already on Boost.

3. ACTIVITY = sales through the platform in that month. Our only true signal is
   ps_payment_events.usage_fees_paid > 0 — the usage fee IS levied on sales (fee% x GMV),
   so a nonzero usage fee in a month PROVES sales happened that month. HubSpot cannot
   answer this: cip_deals.amount is CRM pipeline value and cip_companies.annual_revenue
   is a firmographic — neither is monthly platform sales.
   COVERAGE GAP: we hold payment history for only 420 of the 845 flat-fee brands. For
   the other ~425 we have NO activity signal and therefore CANNOT determine dormancy.
   That is an ask for Jake, recorded in activity_source.

4. PARTNER RATE: when a partner refers on a product, 5% is AUTOMATIC (PS nets the other
   5% of the 10% pool) — manually adjustable per contract. No partner => PS keeps the
   full 10%. Seeded as the default below.

5. PARTNER ALIASES: raw referrer values are messy (XQ/xq, Adina/adina, Eric/'Eric -
   Organic') and UTM codes (xq, wd, we, wj, wx, wz, sj) are a SECOND naming system for
   the same people. Without a map the same partner is counted twice. ps_partner_aliases
   maps every raw value -> one canonical partner_id. Observations keep the raw value
   verbatim (never destroy the source); the alias table does the normalizing.

Revision ID: cip_44_partner_aliases
Revises: cip_43_deal_type_dormancy
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_44_partner_aliases"
down_revision: str | Sequence[str] | None = "cip_43_deal_type_dormancy"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

DEFAULT_PARTNER_PCT = 5  # of the usage-fee base; PS nets the other 5 of its 10.


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON {table} "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON {table} TO {r}")


def upgrade() -> None:
    # ── 1. Partner alias map — the anti-double-count table ───────────────────
    op.execute(
        """
        CREATE TABLE ps_partner_aliases (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            partner_id TEXT NOT NULL,     -- canonical, -> ps_partner_registry.partner_id
            alias_value TEXT NOT NULL,    -- the raw string as a source actually wrote it
            alias_kind TEXT NOT NULL
                CHECK (alias_kind IN (
                    'display_name',   -- 'XQ', 'xq', 'Adina', 'Eric - Organic'
                    'utm_campaign',   -- 'xq', 'wd', 'we', 'wj', 'wx', 'wz', 'sj'
                    'referral_tag',   -- 'referral(xq)', 'referral(Cassie)'
                    'email',
                    'wechat'
                )),
            source TEXT,                  -- where we learned this alias
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            -- One raw value maps to exactly ONE partner. This UNIQUE is the guard:
            -- it makes double-counting a constraint violation, not a silent bug.
            UNIQUE (tenant_id, alias_kind, alias_value)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_partner_aliases_partner "
        "ON ps_partner_aliases (tenant_id, partner_id)"
    )
    op.execute(
        "COMMENT ON TABLE ps_partner_aliases IS "
        "'Maps every raw partner string a source ever wrote onto ONE canonical "
        "partner_id. The same human appears as ''XQ'', ''xq'', ''referral(xq)'' and as "
        "UTM code ''xq'' — four spellings, one person. Without this map they get paid "
        "or credited more than once. "
        "Observations (ps_brand_observations) keep the raw value VERBATIM — we never "
        "destroy what a source said. This table is where normalization happens, so the "
        "raw truth and the resolved identity both survive. "
        "UNIQUE(alias_kind, alias_value) makes an ambiguous alias a constraint "
        "violation rather than a silent mis-credit.'"
    )
    _rls("ps_partner_aliases")

    # ── 2. Brand contacts — unlimited, and WeChat is first-class ─────────────
    op.execute(
        """
        CREATE TABLE ps_brand_contacts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            client_id UUID,
            wayward_brand_id UUID,
            name TEXT,
            role TEXT,
            email TEXT,
            phone TEXT,
            wechat TEXT,
            is_primary BOOLEAN NOT NULL DEFAULT false,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','inactive')),
            source TEXT,          -- 'slack:amazon-brand-connections', 'hubspot', ...
            source_ref TEXT,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_brand_contacts_brand "
        "ON ps_brand_contacts (tenant_id, wayward_brand_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_ps_brand_contacts_ident ON ps_brand_contacts "
        "(tenant_id, wayward_brand_id, coalesce(lower(email),''), coalesce(name,''))"
    )
    op.execute(
        "COMMENT ON TABLE ps_brand_contacts IS "
        "'Contacts AT THE BRAND (distinct from ps_partner_contacts, which is contacts "
        "at a referral partner). Unlimited per brand — never a fixed number of columns. "
        "WeChat is first-class: it is the primary channel for Chinese sellers and is "
        "often the ONLY way to reach them. "
        "Today we can seed name+email from the Slack brand-connection feed; WeChat is "
        "NULL because Wayward does not capture it at onboarding. ASK FOR JAKE (open, "
        "2026-07-13): capture WeChat ID alongside the contact name during onboarding.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_brand_contacts.wechat IS "
        "'WeChat ID. Currently NULL for nearly every brand — Wayward does not ask for "
        "it at onboarding. Requesting that they add it (Tim, 2026-07-13). For a Chinese "
        "seller this is frequently the only reliable contact channel.'"
    )
    _rls("ps_brand_contacts")

    # ── 3. Correct the comments that said "open question" — Tim answered ─────
    op.execute(
        "COMMENT ON COLUMN ps_reactivation_rights.new_kickoff_at IS "
        "'RESOLVED (Tim, 2026-07-13): a reactivation DOES restart the clocks — for "
        "THAT PRODUCT ONLY. On reactivation the brand gets a NEW kickoff on that "
        "product: the contract 3.1 step-down restarts at 10%% (M1-12), and a fresh "
        "12-month partner window opens. Connect and Boost restart INDEPENDENTLY — "
        "reactivating Connect does not touch the Boost clock. Set this when status "
        "becomes ''won''; every downstream rate calculation for that product dates "
        "from here, not from the original signup.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.deal_type IS "
        "'The COMMERCIAL nature of the partner''s credit — SEPARATE from "
        "partner_of_record, because WHO brought the brand and WHETHER money still "
        "flows are different questions. "
        "''flat_fee'' = paid ONCE; NO ongoing revenue. Eric''s pre-contract Connect "
        "book (~845 brands). partner_rate MUST be ignored. CRITICAL (Tim, 2026-07-13): "
        "on these brands NOBODY earns the 10%% on Connect — not Eric, and NOT PS. They "
        "are not a claim item; they are an OPPORTUNITY item. PS can only earn on them "
        "by (a) reactivating them on Connect once they have been inactive 90 days, or "
        "(b) selling them BOOST, which is open on every one of them right now unless a "
        "partner is specifically attributed on Boost. Attribution is kept so we still "
        "track their performance and know whose relationship it is. "
        "''rev_share'' = ongoing %% of the usage fee per ps_partner_terms, expiring at "
        "M12 from kickoff. ''none'' = no partner economics. "
        "NULL = NOT YET DETERMINED (a different fact from ''none'').'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.activity_source IS "
        "'WHAT was measured to produce last_activity_at. Canonical definition (Tim, "
        "2026-07-13): ACTIVITY = sales through the platform in that month. Our only "
        "true signal is ''ps_payment_events.usage_fees_paid>0'' — the usage fee is "
        "levied ON sales (fee%% x GMV), so a nonzero usage fee PROVES sales occurred. "
        "HubSpot cannot answer this (cip_deals.amount is CRM pipeline value; "
        "cip_companies.annual_revenue is a firmographic). "
        "KNOWN GAP: we hold payment history for only ~420 of the 845 flat-fee brands, "
        "so for the rest dormancy is UNKNOWABLE until Wayward gives us per-brand "
        "monthly sales. Record ''none:no_activity_signal'' rather than guessing — a "
        "brand wrongly assumed active is an opportunity silently thrown away.'"
    )

    # ── 4. The default partner rate: 5% (PS nets the other 5 of its 10) ──────
    op.execute(
        f"""
        INSERT INTO ps_partner_terms
            (tenant_id, partner_id, product_id, commission_pct, notes)
        VALUES
            ('{PS_TENANT}', '_default', 'connect', {DEFAULT_PARTNER_PCT},
             'DEFAULT (Tim, 2026-07-13): a partner who refers on a product gets 5% of the usage-fee base automatically; PS nets the other 5% of its 10% pool. Manually adjustable per contract via a partner-specific row.'),
            ('{PS_TENANT}', '_default', 'boosted', {DEFAULT_PARTNER_PCT},
             'DEFAULT (Tim, 2026-07-13): 5% automatic on referral. No partner => PS keeps the full 10%.')
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        f"""
        INSERT INTO ps_partner_registry
            (tenant_id, partner_id, name, default_rate, status, notes)
        VALUES ('{PS_TENANT}', '_default', '(default terms - not a real partner)',
                {DEFAULT_PARTNER_PCT}, 'active',
                'Carrier row for the default 5% partner rate. Never assign as partner_of_record.')
        ON CONFLICT (tenant_id, partner_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM ps_partner_terms WHERE partner_id='_default'")
    op.execute("DELETE FROM ps_partner_registry WHERE partner_id='_default'")
    op.execute("DROP TABLE IF EXISTS ps_brand_contacts CASCADE")
    op.execute("DROP TABLE IF EXISTS ps_partner_aliases CASCADE")
