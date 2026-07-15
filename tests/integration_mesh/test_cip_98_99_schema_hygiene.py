# foundry: kind=test domain=client-intelligence-platform
"""cip_98/99 — dead tables stay dropped, supported-but-empty tables survive, source tables documented.

Guards the 2026-07-15 schema-hygiene pass (Tim). cip_98 dropped two genuinely-dead tables; the three
empty-but-SUPPORTED HubSpot connector tables were deliberately KEPT (they're in the connector
framework's contract). cip_99 documented the raw cip_* source layer.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.requires_postgres
def test_dead_tables_removed(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        for t in ("cip_test_trace", "ps_classification_rules"):
            got = conn.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar()
            assert got is None, f"{t} should be dropped (cip_98)"


@pytest.mark.requires_postgres
def test_supported_but_empty_tables_survive(seeded_engine: Engine) -> None:
    """The 3 HubSpot tables are SUPPORTED connector targets (base.py ALLOWED_CIP_TABLES), not dead."""
    with seeded_engine.connect() as conn:
        for t in ("cip_marketing_emails", "cip_contact_lists", "cip_contact_list_memberships"):
            got = conn.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar()
            assert got is not None, f"{t} is a supported connector target and must not be dropped"


@pytest.mark.requires_postgres
def test_source_tables_documented(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        for t in ("cip_companies", "cip_contacts", "cip_deals", "cip_tickets",
                  "cip_connector_property_registry"):
            desc = conn.execute(
                text("SELECT obj_description(CAST(:t AS regclass), 'pg_class')"), {"t": t}
            ).scalar()
            assert desc, f"{t} should carry a table comment (cip_99)"
