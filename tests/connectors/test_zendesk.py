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
    *, transport: StubTransport | None = None
) -> tuple[ZendeskConnector, StubTransport]:
    stub = transport or StubTransport()
    conn = ZendeskConnector(
        tenant_id=TENANT,
        token="ZENDESK_TEST_TOKEN",
        user="test@example.com",
        subdomain="teststub",
        http=stub,
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


def test_stream_records_yields_one_per_entity_type_via_incremental_apis() -> None:
    """Per-entity incremental API contract.

    Post-2026-05-15 fix: organizations uses time-based incremental at
    /api/v2/incremental/organizations.json (cursor variant returns 404
    on Wayward — Zendesk has never shipped one for orgs). Users +
    tickets use cursor-incremental.
    """
    conn, stub = _make_connector()
    stub.queue("GET", "/api/v2/users/me.json", response={"user": {"id": 1}})  # auth
    stub.queue(
        "GET",
        "/api/v2/incremental/organizations.json",
        response={
            "organizations": [
                {"id": 10, "name": "Acme", "updated_at": "2026-05-01T00:00:00Z"},
            ],
            "count": 1,
            "end_time": 1714521600,
        },
    )
    stub.queue(
        "GET",
        "/api/v2/incremental/users/cursor.json",
        response={
            "users": [
                {
                    "id": 20, "name": "Jane Doe", "email": "j@d.co",
                    "updated_at": "2026-05-01T00:00:00Z",
                },
            ],
            "end_of_stream": True,
        },
    )
    stub.queue(
        "GET",
        "/api/v2/incremental/tickets/cursor.json",
        response={
            "tickets": [
                {"id": 30, "subject": "Login broke", "updated_at": "2026-05-01T00:00:00Z"},
            ],
            "end_of_stream": True,
        },
    )

    records = list(conn.stream_records(cursor=None, batch_size=100))
    assert len(records) == 3
    kinds = sorted(str(r["__cip_kind__"]) for r in records)
    assert kinds == ["company", "contact", "ticket"]


def test_cursor_pagination_chains_users_until_end_of_stream() -> None:
    """Regression test for 2026-05-13/14 Wayward stuck-loop bug. The
    legacy `next_page` pagination would silently loop on the same page
    because the endpoint silently ignored the legacy `?page=N` param.
    Cursor-incremental code (users + tickets) MUST:
      - Send `start_time=0` (or last_key timestamp) on first page
      - Send `cursor=<after_cursor>` on subsequent pages
      - Terminate when `end_of_stream=true`
      - Defensive return if cursor + end_of_stream are both falsy
    """
    conn, stub = _make_connector()
    stub.queue("GET", "/api/v2/users/me.json", response={"user": {"id": 1}})  # auth
    stub.queue(
        "GET",
        "/api/v2/incremental/organizations.json",
        response={"organizations": [], "count": 0, "end_time": 0},
    )
    stub.queue(
        "GET",
        "/api/v2/incremental/users/cursor.json",
        response={
            "users": [
                {"id": 1, "name": "A", "email": "a@x.io",
                 "updated_at": "2026-05-01T00:00:00Z"},
            ],
            "after_cursor": "cursor-page-2-token",
            "end_of_stream": False,
        },
    )
    stub.queue(
        "GET",
        "/api/v2/incremental/users/cursor.json",
        response={
            "users": [
                {"id": 2, "name": "B", "email": "b@x.io",
                 "updated_at": "2026-05-02T00:00:00Z"},
            ],
            "end_of_stream": True,
        },
    )
    stub.queue(
        "GET",
        "/api/v2/incremental/tickets/cursor.json",
        response={"tickets": [], "end_of_stream": True},
    )

    records = list(conn.stream_records(cursor=None, batch_size=100))
    contacts = [r for r in records if r["__cip_kind__"] == "contact"]
    assert len(contacts) == 2, f"expected 2 contacts across cursor pages, got {len(contacts)}"


def test_cursor_pagination_defensively_returns_when_cursor_missing() -> None:
    """If end_of_stream is False AND after_cursor is absent/empty, the
    cursor pager must STILL terminate to avoid the kind of infinite-loop
    bug the legacy pagination had. Defense-in-depth termination."""
    conn, stub = _make_connector()
    stub.queue("GET", "/api/v2/users/me.json", response={"user": {"id": 1}})  # auth
    stub.queue(
        "GET",
        "/api/v2/incremental/organizations.json",
        response={"organizations": [], "count": 0, "end_time": 0},
    )
    stub.queue(
        "GET",
        "/api/v2/incremental/users/cursor.json",
        response={
            "users": [
                {"id": 1, "name": "A", "email": "a@x.io",
                 "updated_at": "2026-05-01T00:00:00Z"},
            ],
            # Neither end_of_stream nor after_cursor
        },
    )
    stub.queue(
        "GET",
        "/api/v2/incremental/tickets/cursor.json",
        response={"tickets": [], "end_of_stream": True},
    )

    records = list(conn.stream_records(cursor=None, batch_size=100))
    contacts = [r for r in records if r["__cip_kind__"] == "contact"]
    assert len(contacts) == 1, f"expected 1 contact (defensive terminate), got {len(contacts)}"


def test_time_incremental_pagination_advances_start_time() -> None:
    """Time-based incremental (organizations) must:
      - Chain pages by setting start_time = previous response's end_time
      - Terminate when count < per_page (or end_of_stream true)
      - Defensive exit when end_time fails to advance (no forward progress)
    Regression test for the 2026-05-15 fix that moved organizations from
    a non-existent cursor.json endpoint to time-based incremental.
    """
    conn, stub = _make_connector()
    stub.queue("GET", "/api/v2/users/me.json", response={"user": {"id": 1}})  # auth
    # Page 1: full page (count == per_page)  →  chain via end_time
    stub.queue(
        "GET",
        "/api/v2/incremental/organizations.json",
        response={
            "organizations": [
                {"id": i, "name": f"Org{i}",
                 "updated_at": f"2026-05-01T00:00:0{i}Z"}
                for i in range(100)
            ],
            "count": 100,
            "end_time": 1714525200,
        },
    )
    # Page 2: short page (count < per_page)  →  terminates
    stub.queue(
        "GET",
        "/api/v2/incremental/organizations.json",
        response={
            "organizations": [
                {"id": 101, "name": "Org101",
                 "updated_at": "2026-05-02T00:00:00Z"},
            ],
            "count": 1,
            "end_time": 1714611600,
        },
    )
    stub.queue(
        "GET",
        "/api/v2/incremental/users/cursor.json",
        response={"users": [], "end_of_stream": True},
    )
    stub.queue(
        "GET",
        "/api/v2/incremental/tickets/cursor.json",
        response={"tickets": [], "end_of_stream": True},
    )

    records = list(conn.stream_records(cursor=None, batch_size=100))
    orgs = [r for r in records if r["__cip_kind__"] == "company"]
    assert len(orgs) == 101, f"expected 101 orgs (100 + 1), got {len(orgs)}"


def test_backfill_history_yields_historical_records_for_tickets() -> None:
    """Post-PM 218f67a4 design: Zendesk backfill walks ticket audits +
    yields one HistoricalRecord per audit event.

    Post-2026-05-15 fix: backfill iterates tickets via the
    cursor-incremental endpoint (/api/v2/incremental/tickets/cursor.json),
    NOT the legacy /api/v2/tickets.json which silently page-1-loops on
    cursor-migrated portals.
    """
    from cip.integration_mesh.base import HistoricalRecord

    conn, stub = _make_connector()
    stub.queue(
        "GET", "/api/v2/users/me.json", response={"user": {"id": 1}}
    )  # auth probe
    # Tickets endpoint (CURSOR-INCREMENTAL, not legacy)
    stub.queue(
        "GET",
        "/api/v2/incremental/tickets/cursor.json",
        response={
            "tickets": [
                {
                    "id": 99,
                    "subject": "Login broken",
                    "priority": "high",
                    "status": "open",
                    "updated_at": "2026-05-01T00:00:00Z",
                }
            ],
            "end_of_stream": True,
        },
    )
    # Audits for that ticket: 2 events (Create + status Change)
    stub.queue(
        "GET",
        "/api/v2/tickets/99/audits.json",
        response={
            "audits": [
                {
                    "created_at": "2025-12-01T08:00:00Z",
                    "events": [
                        {"type": "Create", "field_name": "subject",
                         "value": "Login broken"},
                    ],
                },
                {
                    "created_at": "2025-12-02T08:00:00Z",
                    "events": [
                        {"type": "Change", "field_name": "status",
                         "value": "open"},
                    ],
                },
            ],
        },
    )

    records = list(conn.backfill_history(TENANT))
    assert all(isinstance(r, HistoricalRecord) for r in records)
    assert all(r.target_table == "cip_tickets" for r in records)
    assert all(r.source_id == "99" for r in records)
    assert len(records) == 2
    # Oldest first
    assert records[0].valid_from < records[1].valid_from
    # First audit's valid_to == second audit's valid_from
    assert records[0].valid_to == records[1].valid_from
    assert records[1].valid_to is None  # most-recent historical


def test_backfill_history_paginates_via_cursor_until_end_of_stream() -> None:
    """Regression test for the 2026-05-15 backfill infinite-loop bug.

    Pre-fix: backfill iterated /api/v2/tickets.json with next_page URL
    pagination. Zendesk's tickets endpoint silently returned page 1
    forever for the Wayward portal (same root cause as the 2026-05-13
    organizations infinite-loop), generating 1,128 duplicate history
    rows per ticket on 100 tickets repeatedly until the operator killed
    the script. Fixed by switching to cursor-incremental pagination
    with after_cursor + end_of_stream termination.

    This test asserts the cursor chains correctly across 2 pages with
    distinct tickets, and terminates cleanly on end_of_stream.
    """
    conn, stub = _make_connector()
    stub.queue("GET", "/api/v2/users/me.json", response={"user": {"id": 1}})  # auth
    # Page 1: ticket 100, with after_cursor pointing to page 2
    stub.queue(
        "GET",
        "/api/v2/incremental/tickets/cursor.json",
        response={
            "tickets": [
                {"id": 100, "subject": "T1", "status": "open",
                 "updated_at": "2026-05-01T00:00:00Z"},
            ],
            "after_cursor": "cursor-page-2",
            "end_of_stream": False,
        },
    )
    # Audits for ticket 100
    stub.queue(
        "GET",
        "/api/v2/tickets/100/audits.json",
        response={
            "audits": [
                {"created_at": "2025-12-01T08:00:00Z",
                 "events": [{"type": "Create", "field_name": "subject", "value": "T1"}]},
            ],
        },
    )
    # Page 2: ticket 101, with end_of_stream=True terminating cleanly
    stub.queue(
        "GET",
        "/api/v2/incremental/tickets/cursor.json",
        response={
            "tickets": [
                {"id": 101, "subject": "T2", "status": "closed",
                 "updated_at": "2026-05-02T00:00:00Z"},
            ],
            "end_of_stream": True,
        },
    )
    stub.queue(
        "GET",
        "/api/v2/tickets/101/audits.json",
        response={
            "audits": [
                {"created_at": "2025-12-02T08:00:00Z",
                 "events": [{"type": "Create", "field_name": "subject", "value": "T2"}]},
            ],
        },
    )

    records = list(conn.backfill_history(TENANT))
    source_ids = {r.source_id for r in records}
    # Must cover BOTH distinct tickets exactly once each — proves cursor
    # advances and doesn't loop back to page 1.
    assert source_ids == {"100", "101"}, (
        f"expected {{100, 101}} unique tickets across cursor pages, got {source_ids}"
    )


def test_backfill_history_defensively_returns_when_cursor_missing() -> None:
    """If a response carries neither end_of_stream nor after_cursor, the
    backfill loop must STILL terminate to avoid the page-1-loop pattern.
    Defense-in-depth termination (same shape as the stream_records
    defensive exit added 2026-05-14 for organizations)."""
    conn, stub = _make_connector()
    stub.queue("GET", "/api/v2/users/me.json", response={"user": {"id": 1}})  # auth
    # Page 1: malformed — no end_of_stream + no after_cursor
    stub.queue(
        "GET",
        "/api/v2/incremental/tickets/cursor.json",
        response={
            "tickets": [
                {"id": 200, "subject": "T", "status": "open",
                 "updated_at": "2026-05-01T00:00:00Z"},
            ],
            # Neither end_of_stream nor after_cursor → must defensively return.
        },
    )
    stub.queue(
        "GET",
        "/api/v2/tickets/200/audits.json",
        response={"audits": []},
    )

    records = list(conn.backfill_history(TENANT))
    # Should have processed exactly one ticket then terminated.
    assert all(r.source_id == "200" for r in records)


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
