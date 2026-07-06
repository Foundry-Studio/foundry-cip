# foundry: kind=migration domain=client-intelligence-platform
"""cip_39: PS China Book v2 — new tables (S3) + classification rules (S5).

PS China Book Schema v2, Phase 1 (build spec 12-CC-SCHEMA-HANDOFF.md §S3+§S5).
Additive only — cip_34 objects untouched. Every table is PS-tenant-scoped
(tenant_id + cip_tenant_scope RLS USING+WITH CHECK per cip_30/cip_33) and
granted SELECT to the PS read roles. Money columns are NUMERIC(16,4).

Deviation note (reported to Tim): the reference tables (ps_products,
ps_partner_registry, ps_classification_rules) are tenant-scoped to PS for
Phase 1 rather than made globally-shared. doc 10 frames classification as
"CIP base, all tenants" — the base *column* (nationality_class) does live on
cip_clients for all tenants (cip_38); only the *rules* table is PS-scoped here.
The recurring all-tenant classification job is Phase 2 (S8 out-of-scope), so no
cross-tenant read is needed yet; the rules table can be broadened additively later.

The custom ps_slack_messages table (old S3 #10) is intentionally NOT created —
Slack lands in cip_engagements via a SlackConnector (spec 13, separate job).

ps_annotations is append-only, enforced at the DB (a trigger that raises on
UPDATE/DELETE — fires even for the table owner, unlike RLS), per S7
("enforce append-only at the grant level, not by convention").

Revision ID: cip_39_ps_china_book_tables
Revises: cip_38_ps_china_base_cols
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_39_ps_china_book_tables"
down_revision: str | Sequence[str] | None = "cip_38_ps_china_base_cols"
branch_labels = None
depends_on = None


PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# Order matters for FKs (parents first) and for drop (reverse).
_TABLES = (
    "ps_products",
    "ps_partner_registry",
    "ps_classification_rules",
    "ps_product_subscriptions",
    "ps_partner_credit",
    "ps_attribution",
    "ps_rate_cards",
    "ps_payment_events",
    "ps_commission_ledger",
    "ps_claims",
    "ps_claim_lines",
    "ps_annotations",
    "ps_ingestion_staging",
    "ps_monthly_snapshots",
)

# ── DDL — one CREATE per table. tenant_id first (D-026). ─────────────────────
_DDL = {
    "ps_products": """
        CREATE TABLE ps_products (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            product_id TEXT NOT NULL,
            name TEXT NOT NULL,
            fee_basis TEXT NOT NULL CHECK (fee_basis IN ('gmv_pct','ad_spend_pct')),
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, product_id)
        )""",
    "ps_partner_registry": """
        CREATE TABLE ps_partner_registry (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            partner_id TEXT NOT NULL,
            name TEXT NOT NULL,
            contact TEXT,
            channel TEXT,
            default_rate NUMERIC(6,4),
            payment_method TEXT,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','inactive','prospect')),
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, partner_id)
        )""",
    "ps_classification_rules": """
        CREATE TABLE ps_classification_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            signal TEXT NOT NULL,
            pattern TEXT NOT NULL,
            weight NUMERIC(6,3) NOT NULL,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, signal, pattern)
        )""",
    "ps_product_subscriptions": """
        CREATE TABLE ps_product_subscriptions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            client_id UUID NOT NULL,
            product_id TEXT NOT NULL,
            status TEXT
                CHECK (status IS NULL OR status IN
                    ('ACCOUNT_CREATED','ACTIVE','PRODUCTIVE_NOT_PAID','PRODUCTIVE_PAYABLE')),
            adopted_date DATE,
            churned_date DATE,
            adoption_driven_by TEXT
                CHECK (adoption_driven_by IS NULL OR adoption_driven_by IN
                    ('PS','partner','wayward_direct')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, client_id, product_id)
        )""",
    "ps_partner_credit": """
        CREATE TABLE ps_partner_credit (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            client_id UUID NOT NULL,
            product_id TEXT,
            referral_detail_raw TEXT,
            partner_of_record TEXT,
            credit_start DATE,
            credit_end DATE,
            partner_rate NUMERIC(6,4),
            determined_by TEXT,
            determined_at TIMESTAMPTZ,
            determination_note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, client_id, product_id)
        )""",
    "ps_attribution": """
        CREATE TABLE ps_attribution (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            client_id UUID NOT NULL,
            product_id TEXT NOT NULL,
            ps_attribution_owner TEXT,
            ps_lead_source TEXT,
            ps_conditional TEXT,
            ps_sales_lead TEXT,
            ps_cs_lead TEXT,
            effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
            effective_to TIMESTAMPTZ,
            changed_by TEXT,
            change_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
    "ps_rate_cards": """
        CREATE TABLE ps_rate_cards (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('brand_facing','ps_facing')),
            client_id UUID,
            product_id TEXT NOT NULL,
            fee_structure TEXT,
            rate NUMERIC(10,4),
            rate_base TEXT,
            currency TEXT DEFAULT 'USD',
            commission_pct NUMERIC(6,4),
            commission_base TEXT,
            tier_rule TEXT,
            effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
            effective_to TIMESTAMPTZ,
            source TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
    # rev_share_computed / _variance are GENERATED — the "variance 0" S6 target
    # is structurally enforced (stated must equal 0.10 x usage), not backfilled.
    "ps_payment_events": """
        CREATE TABLE ps_payment_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            client_id UUID,
            customer_id TEXT,
            wayward_brand_id UUID,
            brand_name TEXT,
            payment_date DATE NOT NULL,
            signup_date TIMESTAMPTZ,
            stripe_invoice_ids TEXT,
            stripe_invoice_links TEXT,
            commission_fees_paid NUMERIC(16,4) NOT NULL DEFAULT 0,
            usage_fees_paid NUMERIC(16,4) NOT NULL DEFAULT 0,
            saas_fees_paid NUMERIC(16,4) NOT NULL DEFAULT 0,
            cc_processing_fees_paid NUMERIC(16,4) NOT NULL DEFAULT 0,
            total_amount_paid NUMERIC(16,4) NOT NULL DEFAULT 0,
            rev_share_stated NUMERIC(16,4) NOT NULL DEFAULT 0,
            rev_share_computed NUMERIC(16,4)
                GENERATED ALWAYS AS (round(usage_fees_paid * 0.10, 4)) STORED,
            rev_share_variance NUMERIC(16,4)
                GENERATED ALWAYS AS (rev_share_stated - round(usage_fees_paid * 0.10, 4)) STORED,
            months_from_signup INTEGER,
            rev_share_start_date DATE,
            days_since_start INTEGER,
            source_ref TEXT NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, customer_id, payment_date, stripe_invoice_ids)
        )""",
    "ps_commission_ledger": """
        CREATE TABLE ps_commission_ledger (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            client_id UUID NOT NULL,
            product_id TEXT NOT NULL,
            period_month DATE NOT NULL,
            commission_base NUMERIC(16,4),
            rate_applied NUMERIC(6,4),
            tier_at_time TEXT,
            amount_accrued NUMERIC(16,4),
            amount_received NUMERIC(16,4),
            variance NUMERIC(16,4),
            status TEXT NOT NULL DEFAULT 'accrued'
                CHECK (status IN ('accrued','claimed','paid','partial','disputed','written_off')),
            split_partner_amt NUMERIC(16,4),
            split_sales_amt NUMERIC(16,4),
            split_cs_amt NUMERIC(16,4),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, client_id, product_id, period_month)
        )""",
    "ps_claims": """
        CREATE TABLE ps_claims (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            claim_number TEXT NOT NULL,
            claim_type TEXT
                CHECK (claim_type IS NULL OR claim_type IN
                    ('uncredited_chinese','mis_tag','start_date','rate_error')),
            submitted_to TEXT,
            submitted_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','sent','acknowledged','paid','partial','rejected','abandoned')),
            resolution_amount NUMERIC(16,4),
            resolution_notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, claim_number)
        )""",
    "ps_claim_lines": """
        CREATE TABLE ps_claim_lines (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            claim_id UUID NOT NULL REFERENCES ps_claims(id) ON DELETE CASCADE,
            client_id UUID,
            product_id TEXT,
            period_month DATE,
            amount NUMERIC(16,4),
            note TEXT,
            source_ref TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
    "ps_annotations": """
        CREATE TABLE ps_annotations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            note_type TEXT NOT NULL
                CHECK (note_type IN ('verification','provenance','correction','context')),
            body TEXT NOT NULL,
            author TEXT NOT NULL,
            source_ref TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, entity_type, entity_id, note_type, source_ref)
        )""",
    "ps_ingestion_staging": """
        CREATE TABLE ps_ingestion_staging (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            batch_id UUID NOT NULL,
            target_table TEXT NOT NULL,
            row_action TEXT NOT NULL CHECK (row_action IN ('insert','update','conflict')),
            payload JSONB NOT NULL,
            approved_by TEXT,
            approved_at TIMESTAMPTZ,
            applied_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
    "ps_monthly_snapshots": """
        CREATE TABLE ps_monthly_snapshots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            snapshot_month DATE NOT NULL,
            rows JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, snapshot_month)
        )""",
}

# Helpful non-unique indexes (tenant-first).
_INDEXES = (
    "CREATE INDEX idx_ps_sub_client ON ps_product_subscriptions (tenant_id, client_id)",
    "CREATE INDEX idx_ps_pay_brand ON ps_payment_events (tenant_id, wayward_brand_id)",
    "CREATE INDEX idx_ps_pay_client ON ps_payment_events (tenant_id, client_id)",
    "CREATE INDEX idx_ps_attr_client ON ps_attribution (tenant_id, client_id, product_id)",
    "CREATE INDEX idx_ps_credit_client ON ps_partner_credit (tenant_id, client_id)",
    "CREATE INDEX idx_ps_ledger_client ON ps_commission_ledger (tenant_id, client_id, period_month)",
    "CREATE INDEX idx_ps_annot_entity ON ps_annotations (tenant_id, entity_type, entity_id)",
    "CREATE INDEX idx_ps_claimline_claim ON ps_claim_lines (tenant_id, claim_id)",
)


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON {table} "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )


def upgrade() -> None:
    for t in _TABLES:
        op.execute(_DDL[t])
    for stmt in _INDEXES:
        op.execute(stmt)
    for t in _TABLES:
        _rls(t)
        for role in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {t} TO {role}")

    # ── Append-only enforcement on ps_annotations (S7) ──────────────────────
    # Fires for the owner too (RLS/grants don't restrain the superuser writer).
    op.execute(
        """
        CREATE FUNCTION ps_annotations_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'ps_annotations is append-only (no % allowed)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_ps_annotations_append_only "
        "BEFORE UPDATE OR DELETE ON ps_annotations "
        "FOR EACH ROW EXECUTE FUNCTION ps_annotations_append_only()"
    )

    _seed()


def _seed() -> None:
    """Deterministic reference seeds (idempotent). Report-derived data is the
    backfill script's job, not the migration's."""
    # Products
    op.execute(
        f"""
        INSERT INTO ps_products (tenant_id, product_id, name, fee_basis, notes) VALUES
          ('{PS_TENANT}','connect','Connect','gmv_pct','Wayward charges % of GMV from Wayward campaigns/traffic; PS earns 10% of usage fee'),
          ('{PS_TENANT}','boosted','Boosted','ad_spend_pct','Wayward charges 10% of ad spend; PS earns 10% of usage fee (~1% of ad spend)')
        ON CONFLICT (tenant_id, product_id) DO NOTHING
        """
    )
    # Partner registry seed (default_rate NULL until D6). Names visible in the
    # Brand List Referral Source column.
    op.execute(
        f"""
        INSERT INTO ps_partner_registry (tenant_id, partner_id, name, channel, status, notes) VALUES
          ('{PS_TENANT}','xq','xq',NULL,'active','Seed from Brand List referral(xq)'),
          ('{PS_TENANT}','adina','Adina',NULL,'active','Seed from Brand List referral(Adina)'),
          ('{PS_TENANT}','cassie','Cassie',NULL,'active','Seed from Brand List referral(Cassie)')
        ON CONFLICT (tenant_id, partner_id) DO NOTHING
        """
    )
    # Classification ruleset (01-METHOD §5). weight = evidence strength.
    rules = [
        ("cjk_chars", "principal/company name contains CJK characters", "0.9"),
        ("country_cn_hk", "country in (CN, HK)", "0.8"),
        ("city_shenzhen", "city = Shenzhen / Guangzhou / Hangzhou", "0.6"),
        ("domain_cn_hk", "email/website domain ends .cn or .hk", "0.8"),
        ("email_cn_provider", "email @qq/163/126/sina/sohu/foxmail/aliyun/139/263", "0.7"),
        ("phone_plus86", "phone begins +86", "0.8"),
        ("pinyin_surname", "principal surname is a common pinyin romanization", "0.4"),
        ("shenzhen_caps", "Shenzhen random-caps brand-name pattern", "0.4"),
        ("known_brand_list", "brand on the known-Chinese-brand list", "0.9"),
        ("web_verified", "web verification confirms Chinese ownership", "0.95"),
    ]
    values = ", ".join(
        f"('{PS_TENANT}','{s}','{p.replace(chr(39), chr(39)*2)}',{w})"
        for s, p, w in rules
    )
    op.execute(
        f"INSERT INTO ps_classification_rules (tenant_id, signal, pattern, weight) "
        f"VALUES {values} ON CONFLICT (tenant_id, signal, pattern) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_ps_annotations_append_only ON ps_annotations")
    op.execute("DROP FUNCTION IF EXISTS ps_annotations_append_only()")
    for t in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
