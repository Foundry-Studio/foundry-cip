# foundry: kind=migration domain=client-intelligence-platform
"""cip_101: ps_partner_payouts — the missing "what we PAID partners" ledger (Tim, 2026-07-15).

The money waterfall tracked partner OWED (ps_monthly_earnings.partner_owed, ps_partner_credit) but
had nowhere for partner PAID. This is that ledger — us -> partner — mirroring ps_payment_events
(Wayward -> us). Reconciling amount_paid against ps_monthly_earnings.partner_owed (per brand x
product x month) gives the partner shortfall, exactly like owed-vs-paid from Wayward.

SCOPE (Tim's rule): this holds ONLY the partners WE pay — brands referred in OUR timeframe
(post-cutover). Partners on the 10% exclusion list are paid by WAYWARD directly and are NOT recorded
here. And not every deal has a partner — direct deals simply have no rows.

Isolated addition: nothing references this table yet (no view, no code). The owed-vs-paid math that
consumes it is P2 (the frozen partner_owed snapshot is rebuilt there).

Revision ID: cip_101_partner_payouts
Revises: cip_100_wechat_id_and_phone
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_101_partner_payouts"
down_revision: str | Sequence[str] | None = "cip_100_wechat_id_and_phone"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ps_partner_payouts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL,
            partner_id text NOT NULL,
            wayward_brand_id uuid,
            client_id uuid,
            product_id text,
            period_month date,
            partner_rate_pct numeric,
            amount_paid numeric NOT NULL,
            paid_at date,
            source_ref text,
            notes text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # product_id -> ps_products (the cip_93 pattern; MATCH SIMPLE lets NULL product_id through)
    op.execute(
        "ALTER TABLE ps_partner_payouts ADD CONSTRAINT ps_partner_payouts_product_fk "
        "FOREIGN KEY (tenant_id, product_id) REFERENCES ps_products (tenant_id, product_id) "
        "ON DELETE RESTRICT"
    )
    # tenant isolation, mirroring the other ps_ tables (FORCE so even the table owner is scoped)
    op.execute("ALTER TABLE ps_partner_payouts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_partner_payouts FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON ps_partner_payouts "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )
    op.execute(
        "COMMENT ON TABLE ps_partner_payouts IS "
        "'Ledger of commission WE PAY OUT to partners (us -> partner) — mirrors ps_payment_events "
        "(Wayward -> us). SCOPE: only partners WE pay (brands referred in OUR timeframe, post-cutover). "
        "Partners on the 10%% exclusion list are paid by WAYWARD directly and are NOT recorded here. "
        "Direct (no-partner) deals have no rows. Reconcile amount_paid vs "
        "ps_monthly_earnings.partner_owed (brand x product x month) for the partner shortfall. The "
        "owed-vs-paid math that consumes this is P2.'"
    )
    op.execute("COMMENT ON COLUMN ps_partner_payouts.partner_id IS "
               "'The partner we paid (text, matches ps_partner_credit.partner_of_record / "
               "ps_partner_registry.partner_id). No FK — partner identity is alias-heavy.'")
    op.execute("COMMENT ON COLUMN ps_partner_payouts.amount_paid IS "
               "'What we actually paid the partner for this brand x product x month. DOLLARS.'")
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_partner_payouts TO {r}")
    # cip_rls_test_role is provisioned only by the pytest harness — guard for the raw Tier-C container
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cip_rls_test_role') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON ps_partner_payouts TO cip_rls_test_role;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ps_partner_payouts")
