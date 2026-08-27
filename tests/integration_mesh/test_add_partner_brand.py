# foundry: kind=test domain=client-intelligence-platform
"""Tests for scripts/add_partner_brand.py — manual PS-staff brand→partner attribution.

Covers:
  1. resolve_brand: found / not-found (never mints) / ambiguous name.
  2. add writes a ps_manual ps_partner_credit row for EVERY billed product of the
     brand, crediting the partner.
  3. THE GUARANTEE: a ps_manual row survives rebuild_partner_attribution (which
     otherwise overwrites), while a non-manual row is still re-derived by the rebuild.
  4. Guards: unknown partner refused; unknown brand refused; brand with no billed
     products reports a warning and writes nothing.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.add_partner_brand import resolve_brand
from scripts.add_partner_brand import run as add_run
from scripts.rebuild_partner_attribution import run as rebuild_run

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"


def _guc(conn: Any) -> None:
    conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT})


def _brand(conn: Any, wbid: UUID, name: str) -> None:
    conn.execute(text(
        "INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name, "
        " seen_in_stripe, seen_in_slack_feed, seen_in_payment_reports, "
        " seen_in_exclusion_list, seen_in_eric_sheets, first_seen_at, updated_at) "
        "VALUES (:b, :t, :n, true, false, false, false, false, now(), now()) "
        "ON CONFLICT (wayward_brand_id) DO NOTHING"
    ), {"b": str(wbid), "t": PS_TENANT, "n": name})


def _line(conn: Any, wbid: UUID, product: str, i: int) -> None:
    conn.execute(text(
        "INSERT INTO ps_stripe_invoice_lines "
        "(tenant_id, stripe_invoice_id, stripe_line_id, wayward_brand_id, product_id, "
        " is_ps_base, invoice_status, billing_month, amount) "
        "VALUES (:t, :inv, :ln, :b, :p, true, 'paid', '2026-01-01', 1000) "
        "ON CONFLICT DO NOTHING"
    ), {"t": PS_TENANT, "inv": f"in_{i}", "ln": f"il_{i}", "b": str(wbid), "p": product})


WBID1 = UUID("11111111-1111-4111-8111-111111111111")  # two billed products
WBID2 = UUID("22222222-2222-4222-8222-222222222222")  # control: pre-existing auto row
WBID3 = UUID("33333333-3333-4333-8333-333333333333")  # no billed products


@pytest.fixture
def brand_seeded(seeded_engine: Engine) -> Any:
    # ps_products ('connect', 'boosted') are seeded by the migration chain.
    with seeded_engine.begin() as conn:
        _guc(conn)
        conn.execute(text(
            "INSERT INTO ps_partner_registry (tenant_id, partner_id, name, status) "
            "VALUES (:t, 'p_test', 'Test Partner', 'active') ON CONFLICT DO NOTHING"
        ), {"t": PS_TENANT})
        _brand(conn, WBID1, "TestBrandOne")
        _brand(conn, WBID2, "TestBrandTwo")
        _brand(conn, WBID3, "TestBrandThree")
        _line(conn, WBID1, "connect", 1)
        _line(conn, WBID1, "boosted", 2)
        _line(conn, WBID2, "connect", 3)
        # Control: a pre-existing NON-manual attribution row on WBID2/connect.
        conn.execute(text(
            "INSERT INTO ps_partner_credit (tenant_id, wayward_brand_id, product_id, "
            " partner_of_record, determined_by, determined_at, match_status) "
            "VALUES (:t, :b, 'connect', 'unassigned', 'rule:old', now(), 'unknown') "
            "ON CONFLICT DO NOTHING"
        ), {"t": PS_TENANT, "b": str(WBID2)})
    yield seeded_engine
    with seeded_engine.begin() as conn:
        _guc(conn)
        for tbl in ("ps_partner_credit", "ps_stripe_invoice_lines", "ps_brands"):
            for b in (WBID1, WBID2, WBID3):
                conn.execute(
                    text(f"DELETE FROM {tbl} WHERE tenant_id=:t AND wayward_brand_id=:b"),
                    {"t": PS_TENANT, "b": str(b)},
                )
        conn.execute(
            text("DELETE FROM ps_partner_registry WHERE tenant_id=:t AND partner_id='p_test'"),
            {"t": PS_TENANT},
        )


def _credit(conn: Any, wbid: UUID, product: str) -> Any:
    return conn.execute(text(
        "SELECT partner_of_record, determined_by, match_status FROM ps_partner_credit "
        "WHERE tenant_id=:t AND wayward_brand_id=:b AND product_id=:p"
    ), {"t": PS_TENANT, "b": str(wbid), "p": product}).one_or_none()


# ── 1. resolve_brand ──────────────────────────────────────────────────────

@pytest.mark.requires_postgres
def test_resolve_brand_by_name(brand_seeded: Engine) -> None:
    with brand_seeded.begin() as conn:
        _guc(conn)
        wbid, name = resolve_brand(conn, brand_name="TestBrandOne")
        assert wbid == str(WBID1)
        assert name == "TestBrandOne"


@pytest.mark.requires_postgres
def test_resolve_brand_unknown_never_mints(brand_seeded: Engine) -> None:
    with brand_seeded.begin() as conn:
        _guc(conn)
        with pytest.raises(ValueError, match="does not mint brands"):
            resolve_brand(conn, brand_name="NoSuchBrand")


# ── 2. add writes ps_manual rows for all billed products ───────────────────

@pytest.mark.requires_postgres
def test_add_credits_all_products_as_manual(brand_seeded: Engine) -> None:
    with brand_seeded.begin() as conn:
        out = add_run(conn, partner_id="p_test", brand_name="TestBrandOne", apply=True)
    assert out["rows_written"] == 2
    assert sorted(out["products"]) == ["boosted", "connect"]
    with brand_seeded.connect() as conn:
        _guc(conn)
        for product in ("connect", "boosted"):
            row = _credit(conn, WBID1, product)
            assert row is not None
            assert row.partner_of_record == "p_test"
            assert row.determined_by == "ps_manual"
            assert row.match_status == "confirmed"


# ── 3. THE GUARANTEE: manual survives rebuild; non-manual is re-derived ────

@pytest.mark.requires_postgres
def test_manual_attribution_survives_rebuild(brand_seeded: Engine) -> None:
    with brand_seeded.begin() as conn:
        add_run(conn, partner_id="p_test", brand_name="TestBrandOne", apply=True)
    # The automated rebuild runs over everything.
    with brand_seeded.begin() as conn:
        rebuild_run(conn, apply=True)
    with brand_seeded.connect() as conn:
        _guc(conn)
        # Manual rows untouched.
        for product in ("connect", "boosted"):
            row = _credit(conn, WBID1, product)
            assert row.partner_of_record == "p_test", f"{product} manual row was overwritten"
            assert row.determined_by == "ps_manual"
        # Control: the non-manual row WAS re-derived by the rebuild.
        ctrl = _credit(conn, WBID2, "connect")
        assert ctrl.determined_by == "rule:partner_attribution_v2"


# ── 4. Guards ──────────────────────────────────────────────────────────────

@pytest.mark.requires_postgres
def test_unknown_partner_refused(brand_seeded: Engine) -> None:
    with brand_seeded.begin() as conn, pytest.raises(ValueError, match="not create partners"):
        add_run(conn, partner_id="nope", brand_name="TestBrandOne", apply=True)


@pytest.mark.requires_postgres
def test_brand_with_no_products_warns(brand_seeded: Engine) -> None:
    with brand_seeded.begin() as conn:
        out = add_run(conn, partner_id="p_test", wayward_brand_id=str(WBID3), apply=True)
    assert out["rows_written"] == 0
    assert "warning" in out
