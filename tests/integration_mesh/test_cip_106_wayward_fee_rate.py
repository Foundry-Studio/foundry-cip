# foundry: kind=test domain=client-intelligence-platform
"""cip_106 — Wayward client fee rate surfaced per brand x product. Tim, 2026-07-16.

Structural: the override column + the lens fee-rate columns exist. Behavioral: with no deal the rate
falls to the standard default (0.05 Connect / 0.10 Boost); a manual override wins. (The feed path —
reading cip_deals.usage_fee via the deal bridge — is validated on prod: REDTIGER 3%/5%.)
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

TENANT = "00000000-0000-0000-0000-0000000000e6"


@pytest.mark.requires_postgres
def test_fee_rate_columns_exist(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        lens_cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'lens_ps_product_eligibility'"
            )).fetchall()
        }
        assert "wayward_client_fee_rate" in lens_cols
        assert "wayward_fee_rate_basis" in lens_cols
        tbl_cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'ps_product_eligibility'"
            )).fetchall()
        }
        assert "wayward_fee_rate_override" in tbl_cols


@pytest.mark.requires_postgres
def test_fee_rate_default_then_override(seeded_engine: Engine) -> None:
    bid = "00000000-0000-0000-0000-0000000000b1"
    with seeded_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_products (tenant_id, product_id, name, fee_basis) VALUES "
            "(:t,'connect','Connect','gmv_pct'), (:t,'boosted','Boost','ad_spend_pct')"
        ), {"t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name) "
            "VALUES (:b,:t,'FeeBrand')"
        ), {"b": bid, "t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_nationality_signals (tenant_id, wayward_brand_id, signal, strength, "
            " points_to, evidence, source_system) "
            "VALUES (:t,:b,'phone_+86','confirmed','china','+8613800000000','test')"
        ), {"t": TENANT, "b": bid})

        def rate(product: str) -> tuple:
            return conn.execute(text(
                "SELECT wayward_client_fee_rate, wayward_fee_rate_basis "
                "FROM lens_ps_product_eligibility WHERE wayward_brand_id=:b AND product_id=:p"
            ), {"b": bid, "p": product}).one()

        # no deal -> standard default (0.05 Connect / 0.10 Boost)
        c = rate("connect")
        assert float(c.wayward_client_fee_rate) == 0.05
        assert c.wayward_fee_rate_basis == "standard_default"
        b = rate("boosted")
        assert float(b.wayward_client_fee_rate) == 0.10
        assert b.wayward_fee_rate_basis == "standard_default"

        # a CRM override wins
        conn.execute(text(
            "INSERT INTO ps_product_eligibility (tenant_id, wayward_brand_id, product_id, "
            " ps_rev_share_eligible, wayward_fee_rate_override) VALUES (:t,:b,'connect',true,0.075)"
        ), {"t": TENANT, "b": bid})
        c2 = rate("connect")
        assert float(c2.wayward_client_fee_rate) == 0.075
        assert c2.wayward_fee_rate_basis == "override"
