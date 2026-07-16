# foundry: kind=test domain=client-intelligence-platform
"""cip_105 — per-product PS eligibility model. Tim, 2026-07-16.

`seeded_engine` runs `alembic upgrade head` (incl. cip_105). Structural tests assert the table +
lens exist; the behavioral test proves the per-product rule (a rev-share brand is NOT PS-eligible on
Connect but IS on Boost) and that a manual override wins.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

TENANT = "00000000-0000-0000-0000-0000000000e5"


@pytest.mark.requires_postgres
def test_eligibility_table_and_lens_exist(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass('public.ps_product_eligibility')")
        ).scalar() is not None
        assert conn.execute(
            text("SELECT to_regclass('public.lens_ps_product_eligibility')")
        ).scalar() is not None
        forced = conn.execute(
            text("SELECT relforcerowsecurity FROM pg_class WHERE relname='ps_product_eligibility'")
        ).scalar()
        assert forced is True, "the override table must FORCE tenant isolation"


@pytest.mark.requires_postgres
def test_lens_has_eligibility_columns(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'lens_ps_product_eligibility'"
            )).fetchall()
        }
    for needed in ("wayward_brand_id", "product_id", "ps_rev_share_eligible", "basis",
                   "ps_partner_rev_share_eligible", "partner_name", "partner_rate_pct"):
        assert needed in cols, f"eligibility lens missing {needed}"


@pytest.mark.requires_postgres
def test_per_product_rule_and_override(seeded_engine: Engine) -> None:
    """rev-share brand: NOT eligible on Connect, eligible on Boost; never-listed: eligible both;
    a manual override wins."""
    rev = "00000000-0000-0000-0000-0000000000a1"  # china, on the rev-share exclusion list
    nl = "00000000-0000-0000-0000-0000000000a2"   # china, never listed
    with seeded_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_products (tenant_id, product_id, name, fee_basis) VALUES "
            "(:t,'connect','Connect','gmv_pct'), (:t,'boosted','Boost','ad_spend_pct')"
        ), {"t": TENANT})
        for bid, nm in ((rev, "RevShareBrand"), (nl, "NeverListedBrand")):
            conn.execute(text(
                "INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name) VALUES (:b,:t,:n)"
            ), {"b": bid, "t": TENANT, "n": nm})
            conn.execute(text(
                "INSERT INTO ps_nationality_signals (tenant_id, wayward_brand_id, signal, "
                " strength, points_to, evidence, source_system) "
                "VALUES (:t,:b,'phone_+86','confirmed','china','+8613800000000','test')"
            ), {"t": TENANT, "b": bid})
        # rev brand sits on the rev-share exclusion list (disposition='excluded')
        conn.execute(text(
            "INSERT INTO ps_excluded_brands (tenant_id, wayward_brand_id, brand_name, bucket, "
            " disposition) VALUES (:t,:b,'RevShareBrand','Eric Rev Share Brands','excluded')"
        ), {"t": TENANT, "b": rev})

        def elig(bid: str, product: str) -> tuple:
            return conn.execute(text(
                "SELECT ps_rev_share_eligible, basis FROM lens_ps_product_eligibility "
                "WHERE wayward_brand_id=:b AND product_id=:p"
            ), {"b": bid, "p": product}).one()

        # rev-share brand: Connect blocked, Boost open
        c = elig(rev, "connect")
        assert c.ps_rev_share_eligible is False and c.basis == "rev_share_excl_connect"
        b = elig(rev, "boosted")
        assert b.ps_rev_share_eligible is True and b.basis == "rev_share_boost_open"
        # never-listed brand: eligible on both
        assert elig(nl, "connect").ps_rev_share_eligible is True
        assert elig(nl, "boosted").ps_rev_share_eligible is True

        # a manual override wins — mark the rev brand's Connect as won-back
        conn.execute(text(
            "INSERT INTO ps_product_eligibility (tenant_id, wayward_brand_id, product_id, "
            " ps_rev_share_eligible, basis) VALUES (:t,:b,'connect',true,'won back')"
        ), {"t": TENANT, "b": rev})
        c2 = elig(rev, "connect")
        assert c2.ps_rev_share_eligible is True and c2.basis == "manual_override"
