# foundry: kind=test domain=client-intelligence-platform
"""cip_110 — the frozen ps_monthly_earnings snapshot is fully retired. Tim, 2026-07-16.

The decisive property of this migration: NOTHING in the schema still reads the frozen table. We
assert the table and the five superseded reporting lenses are gone, the three repointed lenses
survive with their key columns, and no surviving view references ps_monthly_earnings. Money-engine
behaviour (recovery, headcount) is validated on prod and is unchanged by construction (the ledger
reads only v.verdict from lens_ps_china_verdict, which is derived from ps_nationality_signals).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

GONE = (
    "ps_monthly_earnings",
    "lens_ps_claim_reconciliation",
    "lens_ps_client_statement",
    "lens_ps_partner_statement",
    "lens_ps_partner_summary",
    "lens_ps_unclaimed",
)

REPOINTED = {
    "lens_ps_brand_reality": {"ever_billed", "reality"},
    "lens_ps_china_verdict": {"verdict", "usage_collected", "ever_billed"},
    "lens_ps_china_companies": {"verdict", "usage_collected"},
}


@pytest.mark.requires_postgres
@pytest.mark.parametrize("obj", GONE)
def test_frozen_snapshot_and_superseded_lenses_are_gone(seeded_engine: Engine, obj: str) -> None:
    with seeded_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass(:o)"), {"o": f"public.{obj}"}
        ).scalar() is None, f"{obj} should be dropped by cip_110 but still exists"


@pytest.mark.requires_postgres
@pytest.mark.parametrize("view,cols", REPOINTED.items())
def test_repointed_lenses_survive_with_columns(seeded_engine: Engine, view: str, cols: set) -> None:
    with seeded_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass(:v)"), {"v": f"public.{view}"}
        ).scalar() is not None, f"{view} missing"
        actual = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = :v"
            ), {"v": view}).fetchall()
        }
        assert not (cols - actual), f"{view} missing columns: {cols - actual}"


@pytest.mark.requires_postgres
def test_no_view_references_the_frozen_table(seeded_engine: Engine) -> None:
    """The whole point of cip_110: zero surviving views read ps_monthly_earnings."""
    with seeded_engine.connect() as conn:
        offenders = [
            r[0] for r in conn.execute(text(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind IN ('v','m') "
                "AND n.nspname NOT IN ('pg_catalog','information_schema') "
                "AND pg_get_viewdef(c.oid) ILIKE '%ps_monthly_earnings%'"
            )).fetchall()
        ]
        assert offenders == [], f"views still reference the frozen table: {offenders}"
