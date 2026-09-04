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
def test_every_tenant_scoped_table_is_enabled_forced_and_policied(
    seeded_engine: Engine,
) -> None:
    """ENUMERATIVE invariant: every table carrying tenant_id is fenced.

    The sibling test above is CONDITIONAL by construction: it only sees a table
    that is RLS-enabled, so a table shipped with NO row security at all passes
    it silently. That is exactly how ps_nationality_request_log (cip_164) and
    ps_readout_editions (cip_149) reached production unprotected, alongside
    ps_nationality_review_state (cip_150) which was enabled but never forced.
    All three were found by querying production on 2026-09-04, not by this
    suite, and repaired in cip_176.

    This test is driven off the CATALOG rather than a hardcoded list, so a NEW
    table that carries tenant_id and forgets its policy fails here on the
    migration that adds it, instead of being discovered months later.
    """
    with seeded_engine.connect() as conn:
        rows = conn.execute(text(
            """
            SELECT c.relname,
                   c.relrowsecurity   AS enabled,
                   c.relforcerowsecurity AS forced,
                   (SELECT count(*) FROM pg_policies p
                     WHERE p.schemaname = 'public' AND p.tablename = c.relname) AS policies
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND EXISTS (
                    SELECT 1 FROM information_schema.columns col
                     WHERE col.table_schema = 'public'
                       AND col.table_name = c.relname
                       AND col.column_name = 'tenant_id')
            ORDER BY c.relname
            """
        )).fetchall()

    assert rows, "catalog query returned nothing; the invariant would pass vacuously"

    unfenced = [
        f"{r.relname}(enabled={r.enabled}, forced={r.forced}, policies={r.policies})"
        for r in rows
        if not r.enabled or not r.forced or r.policies == 0
    ]
    assert not unfenced, (
        f"{len(unfenced)} of {len(rows)} tenant-scoped tables are not "
        f"ENABLE + FORCE + policied: {unfenced}"
    )


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
