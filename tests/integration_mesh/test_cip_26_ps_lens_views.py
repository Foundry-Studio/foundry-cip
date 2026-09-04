# foundry: kind=test domain=client-intelligence-platform
"""Tests for cip_26 — Project Silk destination-side lens views (Phase 2.7).

Originally five tests over the locked design from CIP-SPEC-012 + PM scope 250.
cip_156 (2026-08-04) retired four of the five lens_ps_china_brands_* views as
unwired legacy, so this file now covers what remains:

  1. Retirement completeness: the four retired views are gone and the
     surviving _financial_summary lens is present.
  2. Cross-tenant isolation: non-PS GUC returns zero rows (double-scoped:
     hardcoded PS_TENANT clause + GUC equality). Retargeted onto the
     surviving lens after its original subject was retired.
  3 + 4. Removed. Their subject views no longer exist; see the note below.
  5. Financial summary aggregation: sums + counts + close-date min/max
     compute correctly per client, including LEFT JOIN behavior for
     clients with zero deals.

Each test seeds a tiny synthetic PS-tenant dataset directly via SQL
inside the testcontainer (the seeded_engine fixture runs alembic upgrade
head, including cip_26). The PS_TENANT row exists in a fresh container
because cip's tenant-bootstrap fixtures create it — if not, the tests
insert it themselves to avoid an FK violation.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

PS_TENANT = UUID("078a37d6-6ae2-4e22-869e-cc08f6cb2787")


def _insert_client(
    conn: Any,
    *,
    tenant_id: UUID,
    client_id: UUID,
    source_id: str,
    name: str,
    companion: dict[str, str] | None = None,
) -> None:
    import json
    conn.execute(
        text(
            """
            INSERT INTO cip_clients (
                id, tenant_id, client_id, source_connector, source_id,
                ingested_at, refreshed_at, ingestion_batch_id, authority,
                name, slug, companion_data, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), :t, :cid, 'lens-mirror', :sid,
                NOW(), NOW(), gen_random_uuid(), 'validated',
                :n, :slug, CAST(:cd AS jsonb), NOW(), NOW()
            )
            """
        ),
        {
            "t": str(tenant_id),
            "cid": str(client_id),
            "sid": source_id,
            "n": name,
            "slug": f"test-{source_id}",
            "cd": json.dumps(companion or {}),
        },
    )


def _insert_company(
    conn: Any,
    *,
    tenant_id: UUID,
    client_id: UUID,
    source_id: str,
    name: str,
    domain: str | None = None,
    country: str | None = None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO cip_companies (
                id, tenant_id, client_id, source_connector, source_id,
                ingested_at, refreshed_at, ingestion_batch_id, authority,
                name, domain, country, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), :t, :cid, 'lens-mirror-companies-v1', :sid,
                NOW(), NOW(), gen_random_uuid(), 'validated',
                :n, :d, :c, NOW(), NOW()
            )
            """
        ),
        {
            "t": str(tenant_id),
            "cid": str(client_id),
            "sid": source_id,
            "n": name,
            "d": domain,
            "c": country,
        },
    )


def _insert_deal(
    conn: Any,
    *,
    tenant_id: UUID,
    client_id: UUID,
    source_id: str,
    name: str,
    amount: float | None,
    close_date: str | None,
    attribution_source: str | None,
) -> None:
    import json
    props = {"source": attribution_source} if attribution_source is not None else {}
    conn.execute(
        text(
            """
            INSERT INTO cip_deals (
                id, tenant_id, client_id, source_connector, source_id,
                ingested_at, refreshed_at, ingestion_batch_id, authority,
                name, amount, close_date, properties, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), :t, :cid, 'lens-mirror-deals-v1', :sid,
                NOW(), NOW(), gen_random_uuid(), 'validated',
                :n, :a, :cd, CAST(:p AS jsonb), NOW(), NOW()
            )
            """
        ),
        {
            "t": str(tenant_id),
            "cid": str(client_id),
            "sid": source_id,
            "n": name,
            "a": amount,
            "cd": close_date,
            "p": json.dumps(props),
        },
    )


@pytest.fixture
def ps_seeded(seeded_engine: Engine) -> Engine:
    """Populate the testcontainer with a small synthetic PS dataset.

    Three brands, varied companion_data states + a per-brand mix of deal
    attributions and amounts. Cleanup happens after the test via DELETE
    scoped to PS_TENANT — safe since each test owns the whole PS slice
    in the testcontainer.
    """
    with seeded_engine.begin() as conn:
        brand_a = uuid4()
        brand_b = uuid4()
        brand_c = uuid4()

        # Brand A: onboarded + producing, one big deal attributed to Eric
        _insert_client(
            conn, tenant_id=PS_TENANT, client_id=brand_a,
            source_id="hs-100", name="BrandA",
            companion={
                "ps_segment": "china_referral",
                "ps_onboarded_status": "onboarded",
                "ps_engagement_health": "producing",
            },
        )
        _insert_company(
            conn, tenant_id=PS_TENANT, client_id=brand_a,
            source_id="hs-100", name="BrandA Inc.",
            domain="branda.cn", country="CN",
        )
        _insert_deal(
            conn, tenant_id=PS_TENANT, client_id=brand_a,
            source_id="d-100", name="BrandA Q1 order",
            amount=10000.0, close_date="2026-01-15",
            attribution_source="China Referral - Eric",
        )
        _insert_deal(
            conn, tenant_id=PS_TENANT, client_id=brand_a,
            source_id="d-101", name="BrandA Q2 order",
            amount=5000.0, close_date="2026-04-10",
            attribution_source="China Referral - Eric",
        )

        # Brand B: onboarded, green (NOT producing), one deal attributed to Tim
        _insert_client(
            conn, tenant_id=PS_TENANT, client_id=brand_b,
            source_id="hs-200", name="BrandB",
            companion={
                "ps_segment": "china_referral",
                "ps_onboarded_status": "onboarded",
                "ps_engagement_health": "green",
            },
        )
        _insert_company(
            conn, tenant_id=PS_TENANT, client_id=brand_b,
            source_id="hs-200", name="BrandB Co.",
            domain="brandb.cn", country="CN",
        )
        _insert_deal(
            conn, tenant_id=PS_TENANT, client_id=brand_b,
            source_id="d-200", name="BrandB onboarding",
            amount=2000.0, close_date="2026-02-20",
            attribution_source="China Referral - Tim",
        )

        # Brand C: prospect, no deals, no companion_data filter hits, no company mirror
        _insert_client(
            conn, tenant_id=PS_TENANT, client_id=brand_c,
            source_id="hs-300", name="BrandC",
            companion={
                "ps_segment": "china_referral",
                "ps_onboarded_status": "prospect",
                "ps_engagement_health": "unknown",
            },
        )

        # Other-tenant noise: insert one EcomLever client + deal so cross-
        # tenant isolation test has something to MISS.
        _insert_client(
            conn,
            tenant_id=UUID("dec814db-722a-4730-8e60-51afc4a5dad9"),
            client_id=uuid4(), source_id="hs-999", name="EC noise",
            companion={"ps_onboarded_status": "onboarded"},
        )

    yield seeded_engine

    with seeded_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM cip_deals WHERE tenant_id IN (:t1, :t2)"),
            {"t1": str(PS_TENANT), "t2": "dec814db-722a-4730-8e60-51afc4a5dad9"},
        )
        conn.execute(
            text("DELETE FROM cip_companies WHERE tenant_id IN (:t1, :t2)"),
            {"t1": str(PS_TENANT), "t2": "dec814db-722a-4730-8e60-51afc4a5dad9"},
        )
        conn.execute(
            text("DELETE FROM cip_clients WHERE tenant_id IN (:t1, :t2)"),
            {"t1": str(PS_TENANT), "t2": "dec814db-722a-4730-8e60-51afc4a5dad9"},
        )


# ── 1. View existence ─────────────────────────────────────────────────────

# cip_26 shipped FIVE lens_ps_china_brands_* views. cip_156 (2026-08-04)
# deliberately retired four of them as "unwired legacy china_brands_* lenses",
# leaving only _financial_summary. This test asserted all five and went red the
# moment they were dropped; because CI had been red since 2026-05-11 nobody saw
# it, and it stayed broken for a month.
#
# It is rewritten rather than deleted. Asserting that a retirement ACTUALLY
# HAPPENED is worth more than asserting nothing: a migration that silently fails
# to drop a view, or a later change that resurrects one, now fails here.
_RETIRED_BY_CIP_156 = {
    "lens_ps_china_brands_all",
    "lens_ps_china_brands_onboarded",
    "lens_ps_china_brands_producing",
    "lens_ps_china_brands_by_original_attribution",
}
_SURVIVING = {"lens_ps_china_brands_financial_summary"}


@pytest.mark.requires_postgres
def test_cip_156_lens_retirement_is_complete_and_survivor_remains(
    seeded_engine: Engine,
) -> None:
    """Exactly the surviving cip_26 lens exists; the four retired ones do not."""
    with seeded_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT viewname FROM pg_views "
                "WHERE schemaname = 'public' AND viewname LIKE 'lens_ps_china_brands_%'"
            )
        ).all()
    actual = {r.viewname for r in rows}

    still_present = _RETIRED_BY_CIP_156 & actual
    assert not still_present, (
        f"cip_156 was supposed to retire these, but they exist: {sorted(still_present)}"
    )
    missing = _SURVIVING - actual
    assert not missing, f"surviving cip_26 lens went missing: {sorted(missing)}"


# ── 2. Cross-tenant isolation ─────────────────────────────────────────────

@pytest.mark.requires_postgres
def test_master_lens_isolates_to_ps_tenant(ps_seeded: Engine) -> None:
    """GUC=PS returns rows; GUC=other returns zero; GUC unset returns zero.
    The hardcoded PS_TENANT clause is what defeats a superuser peek at non-PS
    rows.

    RETARGETED 2026-09-04. This originally probed lens_ps_china_brands_all,
    retired by cip_156. The three-way GUC property is the point of the test and
    is still worth asserting, so it now runs against the surviving cip_26 lens
    rather than being deleted alongside its former subject. Counts are asserted
    as "some" / "none" instead of an exact 3, because _financial_summary
    aggregates per client and coupling this test to the aggregation shape would
    make it fail for reasons that have nothing to do with isolation.
    """
    view = "lens_ps_china_brands_financial_summary"
    with ps_seeded.connect() as conn:
        # PS GUC
        conn.execute(text("SET app.current_tenant = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'"))
        ps_count = conn.execute(text(f"SELECT COUNT(*) FROM {view}")).scalar()
        assert ps_count and ps_count > 0, f"expected PS rows from {view}, got {ps_count}"

        # Other tenant (EcomLever, which has 1 cip_clients row)
        conn.execute(text("SET app.current_tenant = 'dec814db-722a-4730-8e60-51afc4a5dad9'"))
        ec_count = conn.execute(text(f"SELECT COUNT(*) FROM {view}")).scalar()
        assert ec_count == 0, f"PS view leaked to EcomLever GUC: {ec_count} rows"

        # No GUC
        conn.execute(text("RESET app.current_tenant"))
        no_count = conn.execute(text(f"SELECT COUNT(*) FROM {view}")).scalar()
        assert no_count == 0, f"PS view returned rows without GUC: {no_count}"


# ── 3 + 4. RETIRED 2026-09-04 ───────────────────────────────────────
#
# Two tests lived here and were removed, not disabled:
#
#   test_companion_data_filters_select_correct_subsets
#       asserted lens_ps_china_brands_onboarded / _producing
#   test_attribution_sourcer_extracted_correctly
#       asserted lens_ps_china_brands_by_original_attribution
#
# cip_156 (2026-08-04) dropped all three of those views as "unwired legacy
# china_brands_* lenses". The behaviour these tests covered no longer exists,
# so there is nothing left to assert about it. Keeping them as xfail would
# imply the feature is coming back; it is not.
#
# What replaces them: the retirement itself is now asserted in
# test_cip_156_lens_retirement_is_complete_and_survivor_remains above, so a
# migration that fails to drop these, or a change that resurrects one, fails
# loudly. Cross-tenant isolation, the one property here worth keeping, was
# retargeted onto the surviving lens rather than deleted.
#
# These went red on 2026-08-04 and nobody noticed for a month because CI had
# been red since 2026-05-11. A red suite hides its own new failures.


# ── 5. Financial summary aggregation ───────────────────────────────────────

@pytest.mark.requires_postgres
def test_financial_summary_aggregates_correctly(ps_seeded: Engine) -> None:
    """BrandA: 2 deals, sum=15000, earliest=2026-01-15, latest=2026-04-10.
    BrandB: 1 deal, sum=2000.
    BrandC: 0 deals (LEFT JOIN keeps the row); deal_count=0, total_amount=0."""
    with ps_seeded.connect() as conn:
        conn.execute(text("SET app.current_tenant = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'"))
        rows = conn.execute(
            text(
                "SELECT client_name, deal_count, total_amount, "
                "earliest_close, latest_close "
                "FROM lens_ps_china_brands_financial_summary "
                "ORDER BY client_name"
            )
        ).all()
    by_name = {r.client_name: r for r in rows}

    a = by_name["BrandA"]
    assert a.deal_count == 2
    assert float(a.total_amount) == 15000.0
    assert str(a.earliest_close) == "2026-01-15"
    assert str(a.latest_close) == "2026-04-10"

    b = by_name["BrandB"]
    assert b.deal_count == 1
    assert float(b.total_amount) == 2000.0

    c = by_name["BrandC"]
    assert c.deal_count == 0
    assert float(c.total_amount) == 0.0
    assert c.earliest_close is None
    assert c.latest_close is None
