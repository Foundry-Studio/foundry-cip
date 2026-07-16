# foundry: kind=test domain=client-intelligence-platform
"""cip_109 — reporting lenses exist with their key columns. Tim, 2026-07-16.

These are thin read-surfaces over the money engine (cip_104-108), which is behaviorally tested
elsewhere; here we assert the five views exist, carry the columns Metabase/downloads rely on,
and are grant-readable. Behavioral output is validated on prod.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

EXPECTED = {
    "lens_ps_ar_aging": {"wayward_brand_id", "ps_claim_owed", "months_outstanding", "aging_bucket"},
    "lens_ps_partner_payout_summary": {"partner", "partner_owed", "partner_paid",
                                       "partner_still_owed", "brands"},
    "lens_ps_monthly_summary": {"period_month", "product_id", "mgmt_fee_owed", "partner_fee_owed",
                                "net_owed"},
    "lens_ps_excluded_partner_performance": {"bucket", "referrer", "product_id", "brands",
                                             "collected_revenue"},
    "lens_ps_wayward_stated": {"wayward_brand_id", "wayward_stated_fees_paid",
                               "wayward_lifetime_commission", "our_recorded_paid"},
}


@pytest.mark.requires_postgres
@pytest.mark.parametrize("view,cols", EXPECTED.items())
def test_reporting_lens_exists_with_columns(seeded_engine: Engine, view: str, cols: set) -> None:
    with seeded_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass(:v)"), {"v": f"public.{view}"}
        ).scalar() is not None, f"{view} missing"
        actual = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = :v"
            ), {"v": view}).fetchall()
        }
        missing = cols - actual
        assert not missing, f"{view} missing columns: {missing}"


@pytest.mark.requires_postgres
def test_reporting_lenses_are_grant_readable(seeded_engine: Engine) -> None:
    """cip_query_reader can SELECT each reporting lens (grants applied)."""
    with seeded_engine.connect() as conn:
        for view in EXPECTED:
            has_grant = conn.execute(text(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE table_name = :v AND grantee = 'cip_query_reader' "
                "AND privilege_type = 'SELECT'"
            ), {"v": view}).scalar()
            assert has_grant, f"{view} not granted to cip_query_reader"
