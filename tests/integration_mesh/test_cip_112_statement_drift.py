# foundry: kind=test domain=client-intelligence-platform
"""cip_112 — the statement-drift guard (AUTOMATIONS-PLAN §5). Tim, 2026-07-17.

`seeded_engine` runs `alembic upgrade head` (incl. cip_112) against the testcontainer.
Structural tests: the view exists post-chain with its key columns and is grant-readable
(cip_109 style). Behavioral: pin a statement + set a differing live claim -> drift_amount and
drift_direction are correct, and the LATEST pinned statement wins; with nothing pinned the view
is empty (the expected state today — none pinned yet).

The behavioral test seeds inside a rolled-back transaction (the view reads its own uncommitted
rows), so it leaves the shared session container clean for the rest of the suite.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

TENANT = "00000000-0000-0000-0000-0000000000d1"  # distinct from cip_104's ...00ce

KEY_COLS = {
    "wayward_brand_id", "brand_name", "statement_label", "statement_generated_at",
    "stated_claim_owed", "live_claim_owed", "drift_amount", "drift_direction",
}


@pytest.mark.requires_postgres
def test_view_exists(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass('public.lens_ps_statement_drift')")
        ).scalar() is not None, "lens_ps_statement_drift missing"


@pytest.mark.requires_postgres
def test_view_has_key_columns(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'lens_ps_statement_drift'"
            )).fetchall()
        }
    missing = KEY_COLS - cols
    assert not missing, f"lens_ps_statement_drift missing columns: {missing}"


@pytest.mark.requires_postgres
def test_view_is_grant_readable(seeded_engine: Engine) -> None:
    """cip_query_reader can SELECT the drift lens (grants applied, cip_109 style)."""
    with seeded_engine.connect() as conn:
        has_grant = conn.execute(text(
            "SELECT count(*) FROM information_schema.role_table_grants "
            "WHERE table_name = 'lens_ps_statement_drift' AND grantee = 'cip_query_reader' "
            "AND privilege_type = 'SELECT'"
        )).scalar()
    assert has_grant, "lens_ps_statement_drift not granted to cip_query_reader"


@pytest.mark.requires_postgres
def test_empty_statements_yields_empty_view(seeded_engine: Engine) -> None:
    """No pinned statements -> the view is empty (the expected state today)."""
    with seeded_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("TRUNCATE ps_claim_statements"))
            n = conn.execute(text("SELECT count(*) FROM lens_ps_statement_drift")).scalar()
            assert n == 0, "empty ps_claim_statements must yield an empty drift view"
        finally:
            trans.rollback()


@pytest.mark.requires_postgres
def test_drift_amount_and_direction(seeded_engine: Engine) -> None:
    """Live 100 vs pinned 60 -> +40 'up'; a NEWER pin at 100 -> 'none' (latest wins); an
    older-dated later insert must NOT win; the newest pin at 130 -> -30 'down'."""
    cb = "00000000-0000-0000-0000-0000000d0001"  # china brand for this test
    with seeded_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"), {"t": TENANT}
            )
            conn.execute(text(
                "INSERT INTO ps_products (tenant_id, product_id, name, fee_basis) "
                "VALUES (:t, 'connect', 'Connect', 'gmv_pct')"
            ), {"t": TENANT})
            conn.execute(text(
                "INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name) "
                "VALUES (:b, :t, 'DriftBrand')"
            ), {"b": cb, "t": TENANT})
            conn.execute(text(
                "INSERT INTO ps_nationality_signals "
                "(tenant_id, wayward_brand_id, signal, strength, points_to, evidence, "
                " source_system) "
                "VALUES (:t, :b, 'phone_+86', 'confirmed', 'china', '+8613800000000', 'test')"
            ), {"t": TENANT, "b": cb})
            # $1,000 collected Dec-2025 -> 10% -> mgmt_fee_owed 100, no payment -> live claim 100
            conn.execute(text(
                "INSERT INTO ps_stripe_invoice_lines "
                "(tenant_id, stripe_invoice_id, stripe_line_id, wayward_brand_id, product_id, "
                " is_ps_base, invoice_status, billing_month, amount) "
                "VALUES (:t, 'in_d1', 'il_d1', :b, 'connect', true, 'paid', '2025-12-01', 1000)"
            ), {"t": TENANT, "b": cb})

            live = conn.execute(text(
                "SELECT ps_claim_owed FROM lens_ps_claim WHERE wayward_brand_id = :b"
            ), {"b": cb}).scalar()
            assert float(live) == 100.0, "sanity: live claim should be $100 before any pin"

            def pin(label: str, generated_at: str, owed: int) -> None:
                conn.execute(text(
                    "INSERT INTO ps_claim_statements "
                    "(tenant_id, statement_label, generated_at, wayward_brand_id, brand_name, "
                    " verdict, ownership, mgmt_fee_owed, wayward_paid, ps_claim_owed) "
                    "VALUES (:t, :l, :g, :b, 'DriftBrand', 'china', 'never_listed', 100, 0, :o)"
                ), {"t": TENANT, "l": label, "g": generated_at, "b": cb, "o": owed})

            def drift():
                return conn.execute(text(
                    "SELECT stated_claim_owed, live_claim_owed, drift_amount, drift_direction "
                    "FROM lens_ps_statement_drift WHERE wayward_brand_id = :b"
                ), {"b": cb}).one()

            # before any pin -> brand absent from the drift view
            assert conn.execute(text(
                "SELECT count(*) FROM lens_ps_statement_drift WHERE wayward_brand_id = :b"
            ), {"b": cb}).scalar() == 0, "no pin yet -> brand absent"

            # pin 60 (older) vs live 100 -> drift +40 up
            pin("STMT-A", "2026-01-01T00:00:00+00:00", 60)
            r = drift()
            assert float(r.stated_claim_owed) == 60.0
            assert float(r.live_claim_owed) == 100.0
            assert float(r.drift_amount) == 40.0
            assert r.drift_direction == "up"

            # pin 100 NEWER -> latest wins -> drift 0 none
            pin("STMT-B", "2026-03-01T00:00:00+00:00", 100)
            r = drift()
            assert float(r.stated_claim_owed) == 100.0
            assert float(r.drift_amount) == 0.0
            assert r.drift_direction == "none"

            # pin 130 at an OLDER date than B -> must NOT win (B stays latest)
            pin("STMT-C", "2026-02-01T00:00:00+00:00", 130)
            r = drift()
            assert float(r.stated_claim_owed) == 100.0, "an older-dated later insert must not win"
            assert r.drift_direction == "none"

            # pin 130 NEWEST -> live 100 -> drift -30 down
            pin("STMT-D", "2026-04-01T00:00:00+00:00", 130)
            r = drift()
            assert float(r.stated_claim_owed) == 130.0
            assert float(r.drift_amount) == -30.0
            assert r.drift_direction == "down"
        finally:
            trans.rollback()
