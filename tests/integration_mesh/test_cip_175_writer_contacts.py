# foundry: kind=test domain=client-intelligence-platform
"""cip_175: ps_reporting_writer gains SELECT/INSERT/UPDATE on ps_partner_contacts
(for the partner.add_contact handler), and still cannot DELETE (least privilege)."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.requires_postgres
def test_writer_can_write_partner_contacts(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        for verb in ("SELECT", "INSERT", "UPDATE"):
            can = conn.execute(
                text(
                    "SELECT has_table_privilege("
                    "'ps_reporting_writer', 'ps_partner_contacts', :v)"
                ),
                {"v": verb},
            ).scalar()
            assert can is True, f"writer missing {verb} on ps_partner_contacts"
        assert conn.execute(
            text(
                "SELECT has_table_privilege("
                "'ps_reporting_writer', 'ps_partner_contacts', 'DELETE')"
            )
        ).scalar() is False
