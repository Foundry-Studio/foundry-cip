# foundry: kind=test domain=client-intelligence-platform
"""ZendeskConnector + ZendeskMapper unit tests.

Mirror shape of test_hubspot.py — StubTransport-based.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from cip.integration_mesh.connectors._http import HTTPError
from cip.integration_mesh.connectors.zendesk import (
    ZendeskConnector,
    ZendeskMapper,
)
from cip.integration_mesh.exceptions import (
    AuthenticationError,
    SchemaDriftError,
)
from tests.connectors.stub_transport import StubTransport

TENANT = UUID("b0000000-0000-0000-0000-000000000001")


def _make_connector(
    *, backfill: bool = False, transport: StubTransport | None = None
) -> tuple[ZendeskConnector, StubTransport]:
    stub = transport or StubTransport()
    conn = ZendeskConnector(
        tenant_id=TENANT,
        token="ZENDESK_TEST_TOKEN",
        user="test@example.com",
        subdomain="teststub",
        http=stub,
        backfill_history=backfill,
    )
    return conn, stub


def test_authenticate_succeeds_on_200() -> None:
    conn, stub = _make_connector()
    stub.queue("GET", "/api/v2/users/me.json", response={"user": {"id": 1}})
    conn.authenticate()
    assert conn._authenticated is True


def test_authenticate_raises_on_401() -> None:
    conn, stub = _make_connector()
    stub.queue(
        "GET",
        "/api/v2/users/me.json",
        error=HTTPError(status=401, body="bad creds"),
    )
    with pytest.raises(AuthenticationError, match="401"):
        conn.authenticate()


def test_authenticate_raises_on_unset_credentials() -> None:
    stub = StubTransport()
    conn = ZendeskConnector(
        tenant_id=TENANT, token="", user="x", subdomain="", http=stub
    )
    with pytest.raises(AuthenticationError, match="must be"):
        conn.authenticate()


def test_stream_records_yields_one_per_entity_type() -> None:
    conn, stub = _make_connector()
    stub.queue("GET", "/api/v2/users/me.json", response={"user": {"id": 1}})  # auth
    # 3 entity types: organizations, users, tickets — one page each.
    org = {"id": 10, "name": "Acme", "updated_at": "2026-05-01T00:00:00Z"}
    user = {
        "id": 20, "name": "Jane Doe", "email": "j@d.co",
        "updated_at": "2026-05-01T00:00:00Z",
    }
    ticket = {"id": 30, "subject": "Login broke", "updated_at": "2026-05-01T00:00:00Z"}
    for entity, sample in (
        ("organizations", org),
        ("users", user),
        ("tickets", ticket),
    ):
        stub.queue(
            "GET",
            f"/api/v2/{entity}.json",
            response={entity: [sample], "next_page": None},
        )

    records = list(conn.stream_records(cursor=None, batch_size=100))
    assert len(records) == 3
    kinds = sorted(str(r["__cip_kind__"]) for r in records)
    assert kinds == ["company", "contact", "ticket"]


def test_stream_records_handles_pagination_via_next_page() -> None:
    conn, stub = _make_connector()
    stub.queue("GET", "/api/v2/users/me.json", response={"user": {"id": 1}})  # auth
    # organizations: 2 pages
    stub.queue(
        "GET",
        "/api/v2/organizations.json",
        response={
            "organizations": [{"id": 1, "name": "A", "updated_at": "2026-05-01T00:00:00Z"}],
            "next_page": "https://teststub.zendesk.com/api/v2/organizations.json?page=2",
        },
    )
    stub.queue(
        "GET",
        "/api/v2/organizations.json?page=2",
        response={
            "organizations": [{"id": 2, "name": "B", "updated_at": "2026-05-02T00:00:00Z"}],
            "next_page": None,
        },
    )
    # users + tickets: empty
    stub.queue("GET", "/api/v2/users.json", response={"users": [], "next_page": None})
    stub.queue("GET", "/api/v2/tickets.json", response={"tickets": [], "next_page": None})

    records = list(conn.stream_records(cursor=None, batch_size=100))
    orgs = [r for r in records if r["__cip_kind__"] == "company"]
    assert len(orgs) == 2


def test_backfill_raises_when_enabled_and_ticket_seen() -> None:
    conn, stub = _make_connector(backfill=True)
    stub.queue("GET", "/api/v2/users/me.json", response={"user": {"id": 1}})  # auth
    stub.queue(
        "GET", "/api/v2/organizations.json",
        response={"organizations": [], "next_page": None},
    )
    stub.queue("GET", "/api/v2/users.json", response={"users": [], "next_page": None})
    stub.queue(
        "GET",
        "/api/v2/tickets.json",
        response={
            "tickets": [{"id": 99, "subject": "Test", "updated_at": "2026-05-01T00:00:00Z"}],
            "next_page": None,
        },
    )
    with pytest.raises(NotImplementedError, match="backfill"):
        list(conn.stream_records(cursor=None, batch_size=100))


def test_describe_schema_returns_valid_property_types() -> None:
    conn, _ = _make_connector()
    descriptors = conn.describe_schema()
    assert descriptors
    valid_types = {
        "string", "number", "datetime", "enumeration",
        "reference", "boolean", "array", "object",
    }
    for d in descriptors:
        assert d.data_type in valid_types
        assert d.cip_table in {"cip_companies", "cip_contacts", "cip_tickets"}


def test_rate_limit_policy_matches_zendesk_standard_plan() -> None:
    conn, _ = _make_connector()
    policy = conn.rate_limit_policy
    assert policy.requests_per_second == 11.0
    assert policy.burst == 20


# ── ZendeskMapper tests ────────────────────────────────────────────────────


def test_mapper_org_routes_to_cip_companies() -> None:
    mapper = ZendeskMapper()
    rows = list(mapper.map({
        "__cip_kind__": "company",
        "source_id": "10",
        "name": "Acme",
        "domain_names": ["acme.com", "acme.co"],
    }))
    row = rows[0]
    assert row.target_table == "cip_companies"
    assert row.fields["name"] == "Acme"
    assert row.fields["domain"] == "acme.com"  # first domain_name


def test_mapper_user_splits_name() -> None:
    mapper = ZendeskMapper()
    rows = list(mapper.map({
        "__cip_kind__": "contact",
        "source_id": "20",
        "name": "Jane Smith",
        "email": "j@example.com",
    }))
    row = rows[0]
    assert row.target_table == "cip_contacts"
    assert row.fields["first_name"] == "Jane"
    assert row.fields["last_name"] == "Smith"
    assert row.fields["email"] == "j@example.com"


def test_mapper_ticket_routes_to_cip_tickets() -> None:
    mapper = ZendeskMapper()
    rows = list(mapper.map({
        "__cip_kind__": "ticket",
        "source_id": "30",
        "subject": "Login broke",
        "description": "User reports 500",
        "priority": "high",
        "status": "open",
    }))
    row = rows[0]
    assert row.target_table == "cip_tickets"
    assert row.fields["subject"] == "Login broke"
    assert row.fields["description"] == "User reports 500"
    assert row.fields["priority"] == "high"
    assert row.fields["status"] == "open"


def test_mapper_unknown_kind_raises_schema_drift() -> None:
    mapper = ZendeskMapper()
    with pytest.raises(SchemaDriftError, match="unknown __cip_kind__"):
        list(mapper.map({"__cip_kind__": "alien", "source_id": "1"}))


def test_mapper_ingest_as_knowledge_emits_for_tickets() -> None:
    mapper = ZendeskMapper()
    texts = mapper.ingest_as_knowledge({
        "__cip_kind__": "ticket",
        "source_id": "5",
        "description": "Account locked after 3 failed logins",
    })
    assert len(texts) == 1
    assert texts[0].metadata["source_id"] == "5"
