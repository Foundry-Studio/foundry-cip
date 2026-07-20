# foundry: kind=test domain=client-intelligence-platform
"""cip_119 — schema hardening + reporting labels. Guards the structural change
(RLS force) and the report-corrupting comment fixes against regression.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.requires_postgres
def test_rls_forced_on_the_three_tables(seeded_engine: Engine) -> None:
    """ps_added_facts / ps_nationality_signals / ps_stripe_customers were RLS-enabled
    but not FORCED; cip_119 forces them to match the 36 siblings."""
    with seeded_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT relname FROM pg_class WHERE relkind='r' "
            "AND relname IN ('ps_added_facts','ps_nationality_signals','ps_stripe_customers') "
            "AND relrowsecurity AND NOT relforcerowsecurity"
        )).fetchall()
    assert not rows, f"still enable-not-force: {[r[0] for r in rows]}"


@pytest.mark.requires_postgres
def test_no_ps_table_is_rls_enabled_but_unforced(seeded_engine: Engine) -> None:
    """Whole-schema invariant: every RLS-enabled ps_ table is also FORCED."""
    with seeded_engine.connect() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM pg_class WHERE relkind='r' AND relname LIKE 'ps_%' "
            "AND relrowsecurity AND NOT relforcerowsecurity"
        )).scalar()
    assert n == 0, f"{n} ps_ tables are RLS-enabled but not forced"


@pytest.mark.requires_postgres
def test_product_id_comments_say_boosted_not_boost(seeded_engine: Engine) -> None:
    """The product value is 'boosted'; no product_id comment may say 'boost' without
    'boosted' (a WHERE product_id='boost' filter returns zero rows -> empty report)."""
    with seeded_engine.connect() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM pg_description d "
            "JOIN pg_attribute a ON a.attrelid=d.objoid AND a.attnum=d.objsubid "
            "WHERE a.attname='product_id' AND d.description LIKE '%boost%' "
            "AND d.description NOT LIKE '%boosted%'"
        )).scalar()
    assert n == 0, f"{n} product_id comments still say 'boost' (not 'boosted')"


@pytest.mark.requires_postgres
def test_key_money_lens_columns_are_commented(seeded_engine: Engine) -> None:
    """The dashboard reads the lenses; the recovery column must carry a comment."""
    with seeded_engine.connect() as conn:
        desc = conn.execute(text(
            "SELECT col_description('lens_ps_claim'::regclass, a.attnum) "
            "FROM pg_attribute a WHERE a.attrelid='lens_ps_claim'::regclass "
            "AND a.attname='ps_claim_owed'"
        )).scalar()
    assert desc and "recovery" in desc.lower(), "lens_ps_claim.ps_claim_owed comment missing"
