# foundry: kind=test domain=client-intelligence-platform
"""cip_108 — Wayward reconciliation lens. Tim, 2026-07-16.

Structural: the lens + its axis columns exist. Behavioral: a china brand we claim, that Wayward does
not attribute and has not paid, reads delta_status='unacknowledged_unpaid'. (The Tim-acknowledged
path — reading cip_deals attribution via the bridge — is validated on prod: 75 acknowledged_unpaid.)
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

TENANT = "00000000-0000-0000-0000-0000000000e8"


@pytest.mark.requires_postgres
def test_reconciliation_lens_columns(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass('public.lens_ps_wayward_reconciliation')")
        ).scalar() is not None
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'lens_ps_wayward_reconciliation'"
            )).fetchall()
        }
    for needed in ("wayward_brand_id", "ps_claim_owed", "wayward_paid", "wayward_credits_ps",
                   "wayward_attribution_source", "wayward_ack_commission", "delta_status"):
        assert needed in cols, f"reconciliation lens missing {needed}"


@pytest.mark.requires_postgres
def test_unacknowledged_unpaid(seeded_engine: Engine) -> None:
    """china + owed + no Wayward attribution + $0 paid -> unacknowledged_unpaid."""
    bid = "00000000-0000-0000-0000-0000000000d8"
    with seeded_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_products (tenant_id, product_id, name, fee_basis) "
            "VALUES (:t,'connect','Connect','gmv_pct')"
        ), {"t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name) "
            "VALUES (:b,:t,'ReconBrand')"
        ), {"b": bid, "t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_nationality_signals (tenant_id, wayward_brand_id, signal, strength, "
            " points_to, evidence, source_system) "
            "VALUES (:t,:b,'phone_+86','confirmed','china','+8613800000000','test')"
        ), {"t": TENANT, "b": bid})
        # collected usage -> a claim; no payment, no cip_deals attribution
        conn.execute(text(
            "INSERT INTO ps_stripe_invoice_lines "
            "(tenant_id, stripe_invoice_id, stripe_line_id, wayward_brand_id, product_id, "
            " is_ps_base, invoice_status, billing_month, amount) "
            "VALUES (:t,'in_r','il_r',:b,'connect', true,'paid','2025-12-01',1000)"
        ), {"t": TENANT, "b": bid})

        r = conn.execute(text(
            "SELECT delta_status, ps_claim_owed, wayward_credits_ps, wayward_paid "
            "FROM lens_ps_wayward_reconciliation WHERE wayward_brand_id=:b"
        ), {"b": bid}).one()
        assert float(r.ps_claim_owed) == 100.0  # 10% of $1,000
        assert float(r.wayward_paid) == 0.0
        assert r.wayward_credits_ps is False
        assert r.delta_status == "unacknowledged_unpaid"
