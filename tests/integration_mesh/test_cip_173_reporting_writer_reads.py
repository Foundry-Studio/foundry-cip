# foundry: kind=test domain=client-intelligence-platform
"""cip_173: ps_reporting_writer can SELECT the brand + billing source tables its
add-brand handler reads, and still cannot write them (least privilege)."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

_READ_TABLES = ("ps_brands", "ps_stripe_invoice_lines", "cip_clients")


@pytest.mark.requires_postgres
def test_reporting_writer_can_read_brand_and_billing_tables(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        for tbl in _READ_TABLES:
            can = conn.execute(
                text("SELECT has_table_privilege('ps_reporting_writer', :t, 'SELECT')"),
                {"t": tbl},
            ).scalar()
            assert can is True, f"ps_reporting_writer missing SELECT on {tbl}"


@pytest.mark.requires_postgres
def test_reporting_writer_stays_read_only_on_source_tables(seeded_engine: Engine) -> None:
    # The grant is SELECT only — the writer must not gain write on the source tables.
    with seeded_engine.connect() as conn:
        for tbl in _READ_TABLES:
            can_write = conn.execute(
                text("SELECT has_table_privilege('ps_reporting_writer', :t, 'INSERT')"),
                {"t": tbl},
            ).scalar()
            assert can_write is False, f"ps_reporting_writer should not have INSERT on {tbl}"
