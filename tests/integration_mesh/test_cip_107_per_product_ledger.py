# foundry: kind=test domain=client-intelligence-platform
"""cip_107 — the commission ledger gates on PER-PRODUCT eligibility. Tim, 2026-07-16.

A china rev-share-excluded brand: its Connect stays blocked (a partner earns the rev-share), but its
Boost is now claimable (open). Proves the ledger consumes lens_ps_product_eligibility.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

TENANT = "00000000-0000-0000-0000-0000000000e7"


@pytest.mark.requires_postgres
def test_rev_share_brand_boost_claimable_connect_not(seeded_engine: Engine) -> None:
    bid = "00000000-0000-0000-0000-0000000000d7"
    with seeded_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_products (tenant_id, product_id, name, fee_basis) VALUES "
            "(:t,'connect','Connect','gmv_pct'), (:t,'boosted','Boost','ad_spend_pct')"
        ), {"t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name) "
            "VALUES (:b,:t,'RevBrand')"
        ), {"b": bid, "t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_nationality_signals (tenant_id, wayward_brand_id, signal, strength, "
            " points_to, evidence, source_system) "
            "VALUES (:t,:b,'phone_+86','confirmed','china','+8613800000000','test')"
        ), {"t": TENANT, "b": bid})
        # on the rev-share exclusion list
        conn.execute(text(
            "INSERT INTO ps_excluded_brands (tenant_id, wayward_brand_id, brand_name, bucket, "
            " disposition) VALUES (:t,:b,'RevBrand','Eric Rev Share Brands','excluded')"
        ), {"t": TENANT, "b": bid})
        # $1000 Connect + $500 Boost collected usage, Dec-2025 (>= the 2025-10-01 anchor)
        for i, (prod, amt) in enumerate((("connect", 1000), ("boosted", 500))):
            conn.execute(text(
                "INSERT INTO ps_stripe_invoice_lines "
                "(tenant_id, stripe_invoice_id, stripe_line_id, wayward_brand_id, product_id, "
                " is_ps_base, invoice_status, billing_month, amount) "
                "VALUES (:t,:inv,:ln,:b,:p, true,'paid','2025-12-01',:a)"
            ), {"t": TENANT, "inv": f"in_{i}", "ln": f"il_{i}", "b": bid, "p": prod, "a": amt})

        def row(product: str) -> tuple:
            return conn.execute(text(
                "SELECT claimable, mgmt_fee_owed FROM lens_ps_commission_ledger "
                "WHERE wayward_brand_id=:b AND product_id=:p"
            ), {"b": bid, "p": product}).one()

        # Connect: rev-share partner earns it -> blocked
        conn_row = row("connect")
        assert conn_row.claimable is False
        assert float(conn_row.mgmt_fee_owed) == 0.0
        # Boost: open -> ours, 10% of $500 = $50
        boost_row = row("boosted")
        assert boost_row.claimable is True
        assert float(boost_row.mgmt_fee_owed) == 50.0
