# foundry: kind=test domain=client-intelligence-platform
"""cip_174: partner detail -- entity_type + lens_ps_partner_detail.

Covers: the entity_type CHECK ('individual'|'agent'|NULL); lens_ps_partner_detail
projects registry facts + entity_type + primary contact + full contact list; the
reporting reader can SELECT the lens.
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
PID = "p_detail_test"
PARTY = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


def _guc(conn: Any) -> None:
    conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT})


def _contact(conn: Any, *, name: str, primary: bool, role: str = "", email: str = "") -> None:
    conn.execute(text(
        "INSERT INTO ps_partner_contacts "
        "(tenant_id, partner_id, name, role, email, is_primary, status, created_at, updated_at) "
        "VALUES (:t, :p, :n, :r, :e, :pr, 'active', now(), now())"
    ), {"t": PS_TENANT, "p": PID, "n": name, "r": role, "e": email, "pr": primary})


@pytest.fixture
def partner_seeded(seeded_engine: Engine) -> Any:
    with seeded_engine.begin() as conn:
        _guc(conn)
        conn.execute(text(
            "INSERT INTO ps_partner_registry "
            "(tenant_id, partner_id, name, status, entity_type, company_name, country, created_at) "
            "VALUES (:t, :p, 'Detail Test', 'active', 'agent', 'Acme Agency', 'CN', now()) "
            "ON CONFLICT (tenant_id, partner_id) DO NOTHING"
        ), {"t": PS_TENANT, "p": PID})
        # party + handle alias so the lens can bridge partner_id (slug) -> party_id (UUID).
        conn.execute(text(
            "INSERT INTO ps_party (party_id, tenant_id, display_name, status, created_at, updated_at) "
            "VALUES (:pty, :t, 'Detail Test', 'active', now(), now()) ON CONFLICT DO NOTHING"
        ), {"pty": PARTY, "t": PS_TENANT})
        conn.execute(text(
            "INSERT INTO ps_party_alias (tenant_id, party_id, alias_value, alias_kind, created_at) "
            "VALUES (:t, :pty, :p, 'handle', now()) ON CONFLICT DO NOTHING"
        ), {"t": PS_TENANT, "pty": PARTY, "p": PID})
        _contact(conn, name="Alice", primary=True, role="Owner", email="alice@acme.cn")
        _contact(conn, name="Bob", primary=False, role="Assistant")
    yield seeded_engine
    with seeded_engine.begin() as conn:
        _guc(conn)
        conn.execute(text("DELETE FROM ps_partner_contacts WHERE tenant_id=:t AND partner_id=:p"),
                     {"t": PS_TENANT, "p": PID})
        conn.execute(text("DELETE FROM ps_party_alias WHERE tenant_id=:t AND alias_value=:p AND alias_kind='handle'"),
                     {"t": PS_TENANT, "p": PID})
        conn.execute(text("DELETE FROM ps_party WHERE tenant_id=:t AND party_id=:pty"),
                     {"t": PS_TENANT, "pty": PARTY})
        conn.execute(text("DELETE FROM ps_partner_registry WHERE tenant_id=:t AND partner_id=:p"),
                     {"t": PS_TENANT, "p": PID})


@pytest.mark.requires_postgres
def test_lens_projects_detail_and_primary_contact(partner_seeded: Engine) -> None:
    with partner_seeded.connect() as conn:
        _guc(conn)
        row = conn.execute(text(
            "SELECT party_id, entity_type, company_name, country, primary_contact_name, "
            "primary_contact_email, contact_count, contacts "
            "FROM lens_ps_partner_detail WHERE partner_id = :p"
        ), {"p": PID}).one()
    assert str(row.party_id) == PARTY                    # bridged slug -> party_id for the reports drill
    assert row.entity_type == "agent"
    assert row.company_name == "Acme Agency" and row.country == "CN"
    assert row.primary_contact_name == "Alice"          # is_primary wins
    assert row.primary_contact_email == "alice@acme.cn"
    assert row.contact_count == 2
    names = {c["name"] for c in row.contacts}
    assert names == {"Alice", "Bob"}
    assert row.contacts[0]["is_primary"] is True         # primary first


@pytest.mark.requires_postgres
def test_entity_type_check_rejects_bad_value(partner_seeded: Engine) -> None:
    with partner_seeded.begin() as conn:  # noqa: SIM117
        _guc(conn)
        with pytest.raises(IntegrityError):
            conn.execute(text(
                "INSERT INTO ps_partner_registry "
                "(tenant_id, partner_id, name, status, entity_type, created_at) "
                "VALUES (:t, 'p_bad_type', 'Bad', 'active', 'company', now())"
            ), {"t": PS_TENANT})


@pytest.mark.requires_postgres
def test_reporting_reader_can_read_lens(partner_seeded: Engine) -> None:
    with partner_seeded.connect() as conn:
        can = conn.execute(text(
            "SELECT has_table_privilege('ps_reporting_reader', 'lens_ps_partner_detail', 'SELECT')"
        )).scalar()
    assert can is True
