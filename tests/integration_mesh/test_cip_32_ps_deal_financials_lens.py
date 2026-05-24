# foundry: kind=test domain=client-intelligence-platform
"""Tests for cip_32 — PS deal-financials read-surface lens (Metabase ASK 5).

Covers PM scope e5bfb702:
  1. lens_ps_china_deal_financials exists + returns deal-grain financials
     under GUC=PS, with the JSONB fields cast to numeric.
  2. Cross-tenant isolation — non-PS GUC (and no-GUC) → 0 rows from the
     new lens (tenant-pin + GUC double-scope, mirrors cip_26).
  3. cip_metabase_project_silk can SELECT the new lens but still cannot
     SELECT raw cip_deals (P-21 lens boundary preserved).
  4. lens_ps_china_brands_financial_summary now carries the per-brand
     financial rollups alongside its existing columns (unchanged).

Self-contained seeding into the testcontainer (seeded_engine runs
alembic upgrade head incl. cip_32). Cleanup via tenant-scoped DELETE.
"""
from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

PS_TENANT = UUID("078a37d6-6ae2-4e22-869e-cc08f6cb2787")
EC_TENANT = UUID("dec814db-722a-4730-8e60-51afc4a5dad9")
_METABASE_PS_ROLE = "cip_metabase_project_silk"
_TEST_PASSWORD_FALLBACK = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105


def _insert_client(conn: Any, *, tenant_id: UUID, client_id: UUID,
                   source_id: str, name: str) -> None:
    conn.execute(text(
        """
        INSERT INTO cip_clients (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            name, slug, companion_data, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), :t, :cid, 'lens-mirror', :sid,
            NOW(), NOW(), gen_random_uuid(), 'validated',
            :n, :slug, '{}'::jsonb, NOW(), NOW()
        )
        """
    ), {"t": str(tenant_id), "cid": str(client_id), "sid": source_id,
        "n": name, "slug": f"test-{source_id}"})


def _insert_deal(conn: Any, *, tenant_id: UUID, client_id: UUID,
                 source_id: str, name: str, amount: float | None,
                 properties: dict[str, Any]) -> None:
    conn.execute(text(
        """
        INSERT INTO cip_deals (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            name, amount, close_date, properties, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), :t, :cid, 'lens-mirror-deals-v1', :sid,
            NOW(), NOW(), gen_random_uuid(), 'validated',
            :n, :a, '2026-01-15', CAST(:p AS jsonb), NOW(), NOW()
        )
        """
    ), {"t": str(tenant_id), "cid": str(client_id), "sid": source_id,
        "n": name, "a": amount, "p": json.dumps(properties)})


@pytest.fixture
def fin_seeded(seeded_engine: Engine) -> Engine:
    """Seed PS + EcomLever brands with financial-bearing deals.

    PS BrandA: 2 deals carrying total_fees_paid (1000 + 500), lifetime_gmv,
               invoices, account_creation_date.
    PS BrandB: 1 deal, total_fees_paid empty-string (cast-guard test).
    EC noise:  1 brand + deal under EcomLever (isolation test target).
    """
    ps_a, ps_b, ec = uuid4(), uuid4(), uuid4()
    with seeded_engine.begin() as conn:
        _insert_client(conn, tenant_id=PS_TENANT, client_id=ps_a,
                       source_id="hs-A", name="BrandA")
        _insert_deal(conn, tenant_id=PS_TENANT, client_id=ps_a,
                     source_id="d-A1", name="A deal 1", amount=10000.0,
                     properties={
                         "total_fees_paid": "1000.50",
                         "lifetime_gmv": "50000",
                         "invoices_paid": "5",
                         "overdue_invoices": "1",
                         "account_creation_date": "2025-03-01",
                     })
        _insert_deal(conn, tenant_id=PS_TENANT, client_id=ps_a,
                     source_id="d-A2", name="A deal 2", amount=5000.0,
                     properties={
                         "total_fees_paid": "500.25",
                         "lifetime_gmv": "20000",
                         "invoices_paid": "2",
                         "overdue_invoices": "0",
                         "account_creation_date": "2025-06-01",
                     })
        _insert_client(conn, tenant_id=PS_TENANT, client_id=ps_b,
                       source_id="hs-B", name="BrandB")
        # Empty-string financial value — must NOT break the numeric cast.
        _insert_deal(conn, tenant_id=PS_TENANT, client_id=ps_b,
                     source_id="d-B1", name="B deal 1", amount=2000.0,
                     properties={"total_fees_paid": "", "lifetime_gmv": ""})
        # EcomLever noise — for the isolation test.
        _insert_client(conn, tenant_id=EC_TENANT, client_id=ec,
                       source_id="hs-EC", name="EC Brand")
        _insert_deal(conn, tenant_id=EC_TENANT, client_id=ec,
                     source_id="d-EC1", name="EC deal", amount=9999.0,
                     properties={"total_fees_paid": "8888.88"})
    yield seeded_engine
    with seeded_engine.begin() as conn:
        for t in (PS_TENANT, EC_TENANT):
            conn.execute(text("DELETE FROM cip_deals WHERE tenant_id=:t"), {"t": str(t)})
            conn.execute(text("DELETE FROM cip_clients WHERE tenant_id=:t"), {"t": str(t)})


def _ps_guc(conn: Any) -> None:
    conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"),
                 {"t": str(PS_TENANT)})


# ── 1. New lens returns deal-grain financials under PS GUC ───────────────

@pytest.mark.requires_postgres
def test_deal_financials_lens_returns_rows(fin_seeded: Engine) -> None:
    with fin_seeded.connect() as conn:
        _ps_guc(conn)
        rows = conn.execute(text(
            "SELECT brand_name, total_fees_paid, lifetime_gmv, invoices_paid, "
            "overdue_invoices, account_creation_date "
            "FROM lens_ps_china_deal_financials ORDER BY total_fees_paid DESC NULLS LAST"
        )).mappings().all()
    # 3 PS deals total (2 BrandA + 1 BrandB)
    assert len(rows) == 3
    # BrandA's top deal: fees cast to numeric
    top = rows[0]
    assert top["brand_name"] == "BrandA"
    assert float(top["total_fees_paid"]) == 1000.50
    assert float(top["lifetime_gmv"]) == 50000
    # BrandB's empty-string fee → NULL (not a cast error)
    b_rows = [r for r in rows if r["brand_name"] == "BrandB"]
    assert len(b_rows) == 1
    assert b_rows[0]["total_fees_paid"] is None


@pytest.mark.requires_postgres
def test_deal_financials_sum_matches(fin_seeded: Engine) -> None:
    """SUM(total_fees_paid) over PS = 1000.50 + 500.25 (BrandB empty → NULL)."""
    with fin_seeded.connect() as conn:
        _ps_guc(conn)
        total = conn.execute(text(
            "SELECT SUM(total_fees_paid) FROM lens_ps_china_deal_financials"
        )).scalar()
    assert float(total) == 1500.75


# ── 2. Cross-tenant isolation ─────────────────────────────────────────────

@pytest.mark.requires_postgres
def test_deal_financials_isolation(fin_seeded: Engine) -> None:
    """PS GUC → PS rows; EcomLever GUC → 0; no GUC → 0. The EcomLever
    deal (with its own total_fees_paid) must never leak into the PS lens."""
    with fin_seeded.connect() as conn:
        _ps_guc(conn)
        ps_n = conn.execute(text("SELECT COUNT(*) FROM lens_ps_china_deal_financials")).scalar()
        assert ps_n == 3

        conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"),
                     {"t": str(EC_TENANT)})
        ec_n = conn.execute(text("SELECT COUNT(*) FROM lens_ps_china_deal_financials")).scalar()
        assert ec_n == 0, f"PS-pinned lens leaked under EcomLever GUC: {ec_n}"

        conn.execute(text("RESET app.current_tenant"))
        no_n = conn.execute(text("SELECT COUNT(*) FROM lens_ps_china_deal_financials")).scalar()
        assert no_n == 0, f"PS lens returned rows without GUC: {no_n}"


# ── 3. Role boundary — lens granted, raw table denied ────────────────────

@pytest.mark.requires_postgres
def test_metabase_role_can_read_lens_not_raw_deals(fin_seeded: Engine) -> None:
    url = fin_seeded.url.set(
        username=_METABASE_PS_ROLE,
        password=os.environ.get("PROJECT_SILK_METABASE_DB_PASSWORD", _TEST_PASSWORD_FALLBACK),
    )
    reng = create_engine(url, pool_pre_ping=True)
    try:
        with reng.connect() as conn:
            _ps_guc(conn)
            # lens: allowed
            n = conn.execute(text("SELECT COUNT(*) FROM lens_ps_china_deal_financials")).scalar()
            assert isinstance(n, int) and n >= 0
            # raw cip_deals: denied
            with pytest.raises(Exception) as exc_info:
                conn.execute(text("SELECT 1 FROM cip_deals LIMIT 1"))
            assert isinstance(
                exc_info.value.orig,  # type: ignore[attr-defined]
                psycopg.errors.InsufficientPrivilege,
            )
    finally:
        reng.dispose()


# ── 4. Summary lens extended with rollups (existing columns intact) ──────

@pytest.mark.requires_postgres
def test_summary_lens_has_rollups_and_existing_columns(fin_seeded: Engine) -> None:
    with fin_seeded.connect() as conn:
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'lens_ps_china_brands_financial_summary'"
            )).fetchall()
        }
    # Existing columns preserved
    for existing in ("client_id", "client_name", "deal_count", "total_amount",
                     "earliest_close", "latest_close", "ps_onboarded_status"):
        assert existing in cols, f"existing column dropped: {existing}"
    # New rollups added
    for added in ("total_fees_paid", "lifetime_gmv", "invoices_paid",
                  "overdue_invoices", "brand_onboarded_date"):
        assert added in cols, f"rollup column missing: {added}"


@pytest.mark.requires_postgres
def test_summary_rollups_aggregate_per_brand(fin_seeded: Engine) -> None:
    """BrandA: total_fees_paid = 1000.50 + 500.25 = 1500.75; deal_count=2;
    brand_onboarded_date = MIN(2025-03-01, 2025-06-01) = 2025-03-01."""
    with fin_seeded.connect() as conn:
        _ps_guc(conn)
        row = conn.execute(text(
            "SELECT deal_count, total_amount, total_fees_paid, lifetime_gmv, "
            "brand_onboarded_date "
            "FROM lens_ps_china_brands_financial_summary WHERE client_name = 'BrandA'"
        )).mappings().first()
    assert row is not None
    assert row["deal_count"] == 2
    assert float(row["total_amount"]) == 15000.0
    assert float(row["total_fees_paid"]) == 1500.75
    assert float(row["lifetime_gmv"]) == 70000
    assert str(row["brand_onboarded_date"]) == "2025-03-01"
