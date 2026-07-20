# foundry: kind=test domain=client-intelligence-platform
"""cip_117 — lens_ps_china_contention: the china/not-china CONTENTION review queue.

Structural: the view exists, has the key columns, is grant-readable.
Behavioral: a brand with BOTH a china signal AND a human not_china override (+
collected revenue) surfaces as contention_type='not_china_overrides_china',
review_priority='high'; a brand with only-china evidence is absent (no contention).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
KEY_COLS = {
    "wayward_brand_id", "brand_name", "verdict", "china_evidence",
    "not_china_evidence", "manual_rationale", "usage_collected",
    "contention_type", "review_priority",
}


@pytest.mark.requires_postgres
def test_view_exists(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass('public.lens_ps_china_contention')")
        ).scalar() is not None, "lens_ps_china_contention missing"


@pytest.mark.requires_postgres
def test_view_has_key_columns(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'lens_ps_china_contention'"
            )).fetchall()
        }
    missing = KEY_COLS - cols
    assert not missing, f"lens_ps_china_contention missing columns: {missing}"


@pytest.mark.requires_postgres
def test_view_is_grant_readable(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        has_grant = conn.execute(text(
            "SELECT count(*) FROM information_schema.role_table_grants "
            "WHERE table_name = 'lens_ps_china_contention' AND grantee = 'cip_query_reader' "
            "AND privilege_type = 'SELECT'"
        )).scalar()
    assert has_grant, "lens_ps_china_contention not granted to cip_query_reader"


@pytest.mark.requires_postgres
def test_contending_revenue_brand_is_high_priority(seeded_engine: Engine) -> None:
    """china card signal + human not_china + $ collected -> high-priority contention,
    typed not_china_overrides_china (the 'are we right NOT to claim this?' case)."""
    b = "00000000-0000-0000-0000-0000000c1170"
    with seeded_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": TENANT})
            conn.execute(text(
                "INSERT INTO ps_products (tenant_id, product_id, name, fee_basis) "
                "VALUES (:t, 'connect', 'Connect', 'gmv_pct') ON CONFLICT DO NOTHING"
            ), {"t": TENANT})
            conn.execute(text(
                "INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name) "
                "VALUES (:b, :t, 'ContendBrand')"
            ), {"b": b, "t": TENANT})
            conn.execute(text(
                "INSERT INTO ps_nationality_signals "
                "(tenant_id, wayward_brand_id, signal, strength, points_to, evidence, "
                " source_system) VALUES "
                "(:t, :b, 'card_country_cn', 'strong', 'china', 'CN cards', "
                "  'stripe:card_country'), "
                "(:t, :b, 'manual_review', 'confirmed', 'not_china', 'ruled US', 'manual:test')"
            ), {"t": TENANT, "b": b})
            conn.execute(text(
                "INSERT INTO ps_stripe_invoice_lines "
                "(tenant_id, stripe_invoice_id, stripe_line_id, wayward_brand_id, product_id, "
                " is_ps_base, invoice_status, billing_month, amount) "
                "VALUES (:t, 'in_c117', 'il_c117', :b, 'connect', true, 'paid', '2026-01-01', 500)"
            ), {"t": TENANT, "b": b})
            row = conn.execute(text(
                "SELECT verdict, contention_type, review_priority "
                "FROM lens_ps_china_contention WHERE wayward_brand_id = :b"
            ), {"b": b}).fetchone()
            assert row is not None, "contending revenue brand missing from the queue"
            assert row[0] == "not_china", f"verdict should be not_china, got {row[0]}"
            assert row[1] == "not_china_overrides_china", f"unexpected type {row[1]}"
            assert row[2] == "high", f"revenue + overridden china signal must be high, got {row[2]}"
        finally:
            trans.rollback()


@pytest.mark.requires_postgres
def test_china_only_brand_absent_from_queue(seeded_engine: Engine) -> None:
    """A brand with ONLY china evidence has no contention -> not in the queue."""
    b = "00000000-0000-0000-0000-0000000c1171"
    with seeded_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": TENANT})
            conn.execute(text(
                "INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name) "
                "VALUES (:b, :t, 'ChinaOnly')"
            ), {"b": b, "t": TENANT})
            conn.execute(text(
                "INSERT INTO ps_nationality_signals "
                "(tenant_id, wayward_brand_id, signal, strength, points_to, evidence, "
                " source_system) "
                "VALUES (:t, :b, 'phone_+86', 'confirmed', 'china', '+8613800000000', 'test')"
            ), {"t": TENANT, "b": b})
            n = conn.execute(text(
                "SELECT count(*) FROM lens_ps_china_contention WHERE wayward_brand_id = :b"
            ), {"b": b}).scalar()
            assert n == 0, "a china-only brand must not appear in the contention queue"
        finally:
            trans.rollback()
