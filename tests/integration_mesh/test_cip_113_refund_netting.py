# foundry: kind=test domain=client-intelligence-platform
"""cip_113 — usage_collected is net of succeeded refunds. Tim, 2026-07-18.

Structural: lens_ps_refund_allocation exists + grants; the two dead legacy recomputers are gone.
Behavioral: a succeeded refund on a paid is_ps_base invoice nets its usage SHARE out of the ledger's
usage_collected; a failed refund nets nothing; the netted figure never exceeds the cell's gross.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

PS = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

_BRAND = ("INSERT INTO ps_brands (tenant_id, wayward_brand_id, brand_name) "
          "VALUES (:t,:b,:n) ON CONFLICT DO NOTHING")
_LINE = ("INSERT INTO ps_stripe_invoice_lines (tenant_id, stripe_line_id, stripe_invoice_id, "
         "wayward_brand_id, product_id, billing_month, amount, invoice_status, is_ps_base, "
         "channel, fee_type, brand_id_source) "
         "VALUES (:t,:l,:i,:b,'connect','2026-01-01',:a,'paid',:base,:ch,:ft,'stripe_metadata') "
         "ON CONFLICT DO NOTHING")
_REFUND = ("INSERT INTO ps_stripe_refunds (tenant_id, stripe_refund_id, charge_id, invoice_id, "
           "amount, currency, status, refund_created) VALUES (:t,:r,:c,:i,:a,'usd',:st, now())")
_NETTED = ("SELECT usage_refund_netted FROM lens_ps_refund_allocation "
           "WHERE wayward_brand_id=:b AND product_id='connect' AND period_month='2026-01-01'")
_COLLECTED = ("SELECT usage_collected FROM lens_ps_commission_ledger "
              "WHERE wayward_brand_id=:b AND product_id='connect' AND period_month='2026-01-01'")
_OVER_CAP = (
    "SELECT count(*) FROM lens_ps_refund_allocation ra JOIN ("
    "  SELECT wayward_brand_id, product_id, billing_month::date pm, "
    "         sum(amount) FILTER (WHERE invoice_status='paid') gross "
    "  FROM ps_stripe_invoice_lines WHERE is_ps_base GROUP BY 1,2,3) g "
    " ON g.wayward_brand_id=ra.wayward_brand_id AND g.product_id=ra.product_id "
    "AND g.pm=ra.period_month "
    "WHERE ra.usage_refund_netted > g.gross + 0.01")


@pytest.mark.requires_postgres
def test_refund_lens_exists_with_columns_and_grants(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass('public.lens_ps_refund_allocation')")
        ).scalar() is not None
        cols = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='lens_ps_refund_allocation'")).fetchall()}
        assert {"wayward_brand_id", "product_id", "period_month",
                "usage_refund_raw", "usage_refund_netted"} <= cols
        assert conn.execute(text(
            "SELECT count(*) FROM information_schema.role_table_grants "
            "WHERE table_name='lens_ps_refund_allocation' AND grantee='cip_query_reader' "
            "AND privilege_type='SELECT'")).scalar()


@pytest.mark.requires_postgres
def test_dead_legacy_recomputers_are_gone(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        for v in ("lens_ps_billed_vs_collected", "lens_ps_partner_performance"):
            assert conn.execute(
                text("SELECT to_regclass(:v)"), {"v": f"public.{v}"}
            ).scalar() is None, f"{v} should be retired by cip_113"


@pytest.mark.requires_postgres
def test_refund_nets_the_usage_share_only(seeded_engine: Engine) -> None:
    """A $400 refund on a $400 invoice whose usage is $100 nets only the $100 usage share →
    net collected for that cell = 0, and the netted figure never exceeds gross."""
    bid = uuid.UUID("a7000000-0000-4000-8000-000000000b13")
    inv = "in_test_cip113_a7"
    with seeded_engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": PS})
            conn.execute(text(_BRAND), {"t": PS, "b": bid, "n": "CIP113 Test Brand"})
            conn.execute(text(_LINE), {"t": PS, "l": "il_a7_usage", "i": inv, "b": bid, "a": 100,
                                       "base": True, "ch": "amazon_connect", "ft": "usage"})
            conn.execute(text(_LINE), {"t": PS, "l": "il_a7_comm", "i": inv, "b": bid, "a": 300,
                                       "base": False, "ch": "amazon_connect", "ft": "commission"})
            conn.execute(text(_REFUND), {"t": PS, "r": "re_a7", "c": "ch_a7", "i": inv, "a": 400,
                                         "st": "succeeded"})

            netted = conn.execute(text(_NETTED), {"b": bid}).scalar()
            assert netted is not None, "no allocation row"
            assert abs(float(netted) - 100.0) < 0.01, f"want 100 got {netted}"
            collected = conn.execute(text(_COLLECTED), {"b": bid}).scalar()
            assert abs(float(collected)) < 0.01, f"want net collected ~0 got {collected}"
            assert conn.execute(text(_OVER_CAP)).scalar() == 0
        finally:
            tx.rollback()


@pytest.mark.requires_postgres
def test_failed_refund_nets_nothing(seeded_engine: Engine) -> None:
    bid = uuid.UUID("a7000000-0000-4000-8000-000000000b14")
    inv = "in_test_cip113_failed"
    with seeded_engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": PS})
            conn.execute(text(_BRAND), {"t": PS, "b": bid, "n": "CIP113 Failed"})
            conn.execute(text(_LINE), {"t": PS, "l": "il_fail", "i": inv, "b": bid, "a": 100,
                                       "base": True, "ch": "amazon_connect", "ft": "usage"})
            conn.execute(text(_REFUND), {"t": PS, "r": "re_fail", "c": "ch_fail", "i": inv,
                                         "a": 100, "st": "failed"})
            n = conn.execute(text("SELECT count(*) FROM lens_ps_refund_allocation "
                                  "WHERE wayward_brand_id=:b"), {"b": bid}).scalar()
            assert n == 0, "a failed refund must net nothing"
        finally:
            tx.rollback()
