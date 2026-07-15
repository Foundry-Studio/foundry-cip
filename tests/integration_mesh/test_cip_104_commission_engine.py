# foundry: kind=test domain=client-intelligence-platform
"""cip_104 — the commission recovery engine (lens-first). Tim, 2026-07-15.

`seeded_engine` runs `alembic upgrade head` (incl. cip_104) against the testcontainer. The
structural tests assert the view stack + the pinned-statement table exist; the behavioral test
seeds a china brand with collected usage and proves the gates (nationality + ownership + rate) and
the per-brand claim floor.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

TENANT = "00000000-0000-0000-0000-0000000000ce"


@pytest.mark.requires_postgres
def test_engine_views_exist(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        for v in ("lens_ps_rate_schedule", "lens_ps_commission_ledger", "lens_ps_claim"):
            assert conn.execute(
                text("SELECT to_regclass(:v)"), {"v": f"public.{v}"}
            ).scalar() is not None, f"{v} missing"


@pytest.mark.requires_postgres
def test_claim_statements_table_is_rls_forced(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass('public.ps_claim_statements')")
        ).scalar() is not None
        forced = conn.execute(
            text("SELECT relforcerowsecurity FROM pg_class WHERE relname='ps_claim_statements'")
        ).scalar()
        assert forced is True, "the pinned-statement ledger must FORCE tenant isolation"


@pytest.mark.requires_postgres
def test_ledger_has_waterfall_columns(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'lens_ps_commission_ledger'"
            )).fetchall()
        }
    for needed in ("wayward_brand_id", "product_id", "period_month", "usage_collected",
                   "mgmt_rate", "mgmt_fee_owed", "claimable", "claim_status",
                   "partner_fee_owed", "ownership"):
        assert needed in cols, f"ledger missing {needed}"


def test_engine_invariants_registered() -> None:
    """The four gate-guards ship with the engine — a claim can't silently break its own rules."""
    from cip.integration_mesh.ps_invariants import INVARIANTS

    keys = {i.key for i in INVARIANTS}
    for k in ("ledger_grain_unique", "claim_requires_china", "fee_only_when_claimable",
              "mgmt_rate_is_ladder"):
        assert k in keys, f"engine invariant {k} not registered"


@pytest.mark.requires_postgres
def test_gates_and_claim_floor(seeded_engine: Engine) -> None:
    """china + owned + in-window -> 10% owed; unknown -> $0; overpaid -> claim floors to 0."""
    cb = "00000000-0000-0000-0000-00000000c001"  # china brand
    nb = "00000000-0000-0000-0000-00000000c002"  # no-signal (unknown) brand
    with seeded_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": TENANT})
        conn.execute(text(
            "INSERT INTO ps_products (tenant_id, product_id, name, fee_basis) "
            "VALUES (:t, 'connect', 'Connect', 'gmv_pct')"
        ), {"t": TENANT})
        for bid, nm in ((cb, "TestChinaBrand"), (nb, "TestUnknownBrand")):
            conn.execute(text(
                "INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name) "
                "VALUES (:b, :t, :n)"
            ), {"b": bid, "t": TENANT, "n": nm})
        # make cb china via a confirming +86 signal
        conn.execute(text(
            "INSERT INTO ps_nationality_signals "
            "(tenant_id, wayward_brand_id, signal, strength, points_to, evidence, source_system) "
            "VALUES (:t, :b, 'phone_+86', 'confirmed', 'china', '+8613800000000', 'test')"
        ), {"t": TENANT, "b": cb})
        # $1,000 collected usage each, Dec-2025 (>= the 2025-10-01 never-listed anchor)
        for i, bid in enumerate((cb, nb)):
            conn.execute(text(
                "INSERT INTO ps_stripe_invoice_lines "
                "(tenant_id, stripe_invoice_id, stripe_line_id, wayward_brand_id, product_id, "
                " is_ps_base, invoice_status, billing_month, amount) "
                "VALUES (:t, :inv, :ln, :b, 'connect', true, 'paid', '2025-12-01', 1000)"
            ), {"t": TENANT, "inv": f"in_{i}", "ln": f"il_{i}", "b": bid})

        led = conn.execute(text(
            "SELECT mgmt_rate, mgmt_fee_owed, claimable FROM lens_ps_commission_ledger "
            "WHERE wayward_brand_id = :b"
        ), {"b": cb}).one()
        assert float(led.mgmt_rate) == 0.10, "recent brand should sit at the 10% tier"
        assert float(led.mgmt_fee_owed) == 100.0, "10% of $1,000 collected"
        assert led.claimable is True

        nbled = conn.execute(text(
            "SELECT mgmt_fee_owed, claimable FROM lens_ps_commission_ledger "
            "WHERE wayward_brand_id = :b"
        ), {"b": nb}).one()
        assert float(nbled.mgmt_fee_owed) == 0.0, "no china verdict -> nothing owed"
        assert nbled.claimable is False, "nationality gate must block a non-china brand"

        # claim with no payment = full owed
        claim = conn.execute(text(
            "SELECT ps_claim_owed FROM lens_ps_claim WHERE wayward_brand_id = :b"
        ), {"b": cb}).scalar()
        assert float(claim) == 100.0

        # overpay it -> claim floors at 0 (never negative, never offsets another brand)
        conn.execute(text(
            "INSERT INTO ps_payment_events (tenant_id, wayward_brand_id, payment_date, source_ref, "
            " rev_share_stated) VALUES (:t, :b, '2025-12-15', 'test', 150)"
        ), {"t": TENANT, "b": cb})
        floored = conn.execute(text(
            "SELECT ps_claim_owed FROM lens_ps_claim WHERE wayward_brand_id = :b"
        ), {"b": cb}).scalar()
        assert float(floored) == 0.0, "overpaid brand claims $0, never a negative offset"
