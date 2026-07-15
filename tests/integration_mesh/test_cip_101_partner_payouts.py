# foundry: kind=test domain=client-intelligence-platform
"""cip_101 — ps_partner_payouts (the us->partner payout ledger). Tim, 2026-07-15."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.requires_postgres
def test_partner_payouts_table_exists_with_rls(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('public.ps_partner_payouts')")).scalar() is not None
        forced = conn.execute(
            text("SELECT relforcerowsecurity FROM pg_class WHERE relname='ps_partner_payouts'")
        ).scalar()
        assert forced is True, "tenant isolation must be FORCED on the payout ledger"


@pytest.mark.requires_postgres
def test_partner_payouts_has_waterfall_columns(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'ps_partner_payouts'"
            )).fetchall()
        }
    for needed in ("partner_id", "wayward_brand_id", "product_id", "period_month",
                   "amount_paid", "paid_at", "partner_rate_pct"):
        assert needed in cols, f"payout ledger missing {needed}"
