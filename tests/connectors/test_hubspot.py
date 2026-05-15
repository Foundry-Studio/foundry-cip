# foundry: kind=test domain=client-intelligence-platform
"""HubSpotConnector + HubSpotMapper unit tests.

Uses StubTransport to avoid real HubSpot API calls. Tests:
- authenticate() validates with a successful probe
- authenticate() raises AuthenticationError on 401
- stream_records() paginates correctly via the 'after' cursor token
- stream_records() respects the incremental cursor (skips older records)
- backfill raises NotImplementedError per 2026-05-12 escalation
- describe_schema() returns PropertyDescriptors with valid data_type enum values
- HubSpotMapper.map() routes per __cip_kind__ + handles numeric coercion
- HubSpotMapper.ingest_as_knowledge() returns text for tickets, empty for others
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from cip.integration_mesh.connectors._http import HTTPError
from cip.integration_mesh.connectors.hubspot import (
    HubSpotConnector,
    HubSpotMapper,
)
from cip.integration_mesh.exceptions import (
    AuthenticationError,
    SchemaDriftError,
)
from tests.connectors.stub_transport import StubTransport

TENANT = UUID("b0000000-0000-0000-0000-000000000001")


def _make_connector(
    *, transport: StubTransport | None = None, discover: bool = False,
) -> tuple[HubSpotConnector, StubTransport]:
    """Build a connector wired to a stub transport (no real HTTP).

    Note (post-PM 218f67a4 redesign): backfill is now a separate method
    (``backfill_history``) on the connector, not a ctor flag. Tests for
    backfill behavior invoke ``conn.backfill_history(tenant_id)`` directly.

    Note (post-scope 9c3d1393, 2026-05-15): stream_records + backfill_history
    now call ``_discover_properties()`` lazily on first use. Tests that
    don't care about discovery semantics pre-populate the cache with a
    minimal property tuple to short-circuit the discovery HTTP call.
    Tests that DO care about discovery (e.g. testing 403 → fallback path)
    pass ``discover=True`` to leave the cache empty and queue discovery
    responses explicitly.
    """
    stub = transport or StubTransport()
    conn = HubSpotConnector(
        tenant_id=TENANT,
        token="pat-test-stub",
        http=stub,
    )
    if not discover:
        # Short-circuit lazy discovery — tests pre-populate to keep the
        # data-flow assertions clean.
        conn._discovered_properties = {
            "companies": ("name", "domain", "hs_lastmodifieddate", "createdate"),
            "contacts": ("firstname", "lastname", "email", "hs_lastmodifieddate"),
            "deals": ("dealname", "amount", "dealstage", "hs_lastmodifieddate"),
            "tickets": ("subject", "content", "hs_lastmodifieddate"),
        }
    return conn, stub


def test_authenticate_succeeds_on_200() -> None:
    conn, stub = _make_connector()
    stub.queue("GET", "/crm/v3/objects/companies", response={"results": []})
    conn.authenticate()
    assert conn._authenticated is True
    assert len(stub.calls) == 1


def test_authenticate_raises_on_401() -> None:
    conn, stub = _make_connector()
    stub.queue(
        "GET",
        "/crm/v3/objects/companies",
        error=HTTPError(status=401, body="invalid token"),
    )
    with pytest.raises(AuthenticationError, match="401"):
        conn.authenticate()


def test_authenticate_raises_on_unset_token() -> None:
    stub = StubTransport()
    conn = HubSpotConnector(tenant_id=TENANT, token="", http=stub)
    with pytest.raises(AuthenticationError, match="not set"):
        conn.authenticate()


def test_stream_records_paginates_via_after_cursor() -> None:
    """Per entity: GET list page → POST batch/read full props → emit records.

    Post-scope 9c3d1393 (2026-05-15): each page is a two-pass GET-then-POST.
    GET returns IDs + pagination cursor; POST returns the full property
    set for each ID. Tests mock both halves.
    """
    conn, stub = _make_connector()
    stub.queue("GET", "/crm/v3/objects/companies", response={"results": []})  # auth probe
    for hubspot_path in ("companies", "contacts", "deals", "tickets"):
        # GET: list IDs (one record, no further pagination)
        stub.queue(
            "GET",
            f"/crm/v3/objects/{hubspot_path}",
            response={"results": [{"id": "1"}]},
        )
        # POST: batch/read full properties
        stub.queue(
            "POST",
            f"/crm/v3/objects/{hubspot_path}/batch/read",
            response={
                "results": [
                    {
                        "id": "1",
                        "updatedAt": "2026-05-01T00:00:00Z",
                        "properties": {
                            "name": "Sample",
                            "hs_lastmodifieddate": "2026-05-01T00:00:00Z",
                        },
                    }
                ]
            },
        )
    records = list(conn.stream_records(cursor=None, batch_size=100))
    assert len(records) == 4  # one per entity type
    assert all(r.get("__cip_kind__") in {"company", "contact", "deal", "ticket"} for r in records)


def test_stream_records_pagination_continues_until_no_next() -> None:
    conn, stub = _make_connector()
    stub.queue("GET", "/crm/v3/objects/companies", response={"results": []})  # auth
    # Companies: GET page 1 (has cursor), POST batch/read for page 1 IDs,
    # GET page 2 (no cursor), POST batch/read for page 2 IDs.
    stub.queue(
        "GET",
        "/crm/v3/objects/companies",
        response={
            "results": [{"id": "1"}],
            "paging": {"next": {"after": "100"}},
        },
    )
    stub.queue(
        "POST",
        "/crm/v3/objects/companies/batch/read",
        response={
            "results": [{"id": "1", "properties": {"hs_lastmodifieddate": "2026-05-01T00:00:00Z"}}],
        },
    )
    stub.queue(
        "GET",
        "/crm/v3/objects/companies",
        response={"results": [{"id": "2"}]},
    )
    stub.queue(
        "POST",
        "/crm/v3/objects/companies/batch/read",
        response={
            "results": [{"id": "2", "properties": {"hs_lastmodifieddate": "2026-05-02T00:00:00Z"}}],
        },
    )
    # Other 3 entities: single empty page each — GET returns no results
    # so the POST batch/read is skipped (connector's empty-ids guard).
    for _ in range(3):
        stub.queue("GET", "/", response={"results": []})

    records = list(conn.stream_records(cursor=None, batch_size=100))
    # Should have 2 companies + 0 others
    companies = [r for r in records if r.get("__cip_kind__") == "company"]
    assert len(companies) == 2


def test_backfill_history_yields_historical_records() -> None:
    """Post-PM 218f67a4 design: backfill is a SEPARATE method
    (backfill_history) that yields HistoricalRecord instances directly,
    consumed by orchestrator.run_backfill() and routed by
    persister.persist_history_record() to cip_*_history.
    """
    from cip.integration_mesh.base import HistoricalRecord

    conn, stub = _make_connector()
    # auth probe
    stub.queue("GET", "/crm/v3/objects/companies", response={"results": []})
    # Iteration order: companies → contacts → deals → tickets.
    # Give companies ONE record with property history, others empty.
    stub.queue(
        "GET",
        "/crm/v3/objects/companies",
        response={
            "results": [
                {
                    "id": "42",
                    "properties": {"name": "Acme"},
                    "propertiesWithHistory": {
                        "name": [
                            {"timestamp": "2025-01-01T00:00:00Z", "value": "Acme Old"},
                            {"timestamp": "2025-06-01T00:00:00Z", "value": "Acme Mid"},
                            {"timestamp": "2025-12-01T00:00:00Z", "value": "Acme"},
                        ],
                    },
                }
            ],
        },
    )
    for _ in range(3):  # contacts, deals, tickets — empty
        stub.queue("GET", "/", response={"results": []})

    records = list(conn.backfill_history(TENANT))
    assert len(records) == 3, f"expected 3 historical snapshots, got {len(records)}"
    assert all(isinstance(r, HistoricalRecord) for r in records)
    assert all(r.target_table == "cip_companies" for r in records)
    assert all(r.source_id == "42" for r in records)
    # Oldest → newest ordering
    assert records[0].valid_from < records[1].valid_from < records[2].valid_from
    # valid_to chains: each row's valid_to == next row's valid_from
    assert records[0].valid_to == records[1].valid_from
    assert records[1].valid_to == records[2].valid_from
    # Last revision has valid_to=None (most-recent historical)
    assert records[2].valid_to is None
    # Domain field captured
    assert records[0].fields.get("name") == "Acme Old"
    assert records[2].fields.get("name") == "Acme"


def test_backfill_history_groups_mismatched_precision_timestamps() -> None:
    """Regression test for the 2026-05-15 valid_range bug.

    HubSpot's property-history stream can carry two timestamps that
    represent the same logical instant but serialize with different
    millisecond precision: e.g. "2025-07-15T18:03:26.491Z" and
    "2025-07-15T18:03:26Z". The pre-fix implementation sorted these as
    raw strings — ASCII ordering puts "." (0x2E) before "Z" (0x5A) — so
    the higher-precision string sorted BEFORE the bare-second one, then
    valid_from/valid_to were assigned from different parsed timestamps,
    yielding valid_from > valid_to and violating
    ck_cip_companies_history_valid_range, which poisoned the persister
    transaction and killed the rest of the batch. Fixed by parsing
    timestamps to datetime FIRST, then grouping snapshots by parsed
    datetime, then sorting by datetime — semantic equivalence.

    This test asserts the connector emits NO ``HistoricalRecord``
    where valid_from >= valid_to, even when the source returns
    mismatched-precision timestamps in the same property history.
    """
    conn, stub = _make_connector()
    stub.queue("GET", "/crm/v3/objects/companies", response={"results": []})  # auth
    # Companies: 3 history events. Two have the same logical instant
    # encoded with/without milliseconds; one is later. Pre-fix code
    # would order .491 BEFORE the bare second; post-fix groups them.
    stub.queue(
        "GET",
        "/crm/v3/objects/companies",
        response={
            "results": [
                {
                    "id": "42",
                    "properties": {"name": "Snappy Socks"},
                    "propertiesWithHistory": {
                        "name": [
                            {"timestamp": "2025-07-15T18:03:26Z", "value": "Old"},
                            {"timestamp": "2025-07-15T18:03:26.491Z", "value": "Snappy Socks"},
                            {"timestamp": "2025-08-01T00:00:00Z", "value": "Snappy Socks Renamed"},
                        ],
                    },
                }
            ],
        },
    )
    for _ in range(3):  # contacts, deals, tickets — empty
        stub.queue("GET", "/", response={"results": []})

    records = list(conn.backfill_history(TENANT))
    # Each emitted record must satisfy valid_from < valid_to (or valid_to is None).
    for rec in records:
        assert rec.valid_to is None or rec.valid_from < rec.valid_to, (
            f"valid_range violation: {rec.valid_from} >= {rec.valid_to}"
        )


def test_describe_schema_returns_valid_property_types() -> None:
    conn, _ = _make_connector()
    descriptors = conn.describe_schema()
    assert descriptors  # non-empty
    valid_types = {
        "string", "number", "datetime", "enumeration",
        "reference", "boolean", "array", "object",
    }
    valid_tables = {"cip_companies", "cip_contacts", "cip_deals", "cip_tickets"}
    for d in descriptors:
        assert d.data_type in valid_types, f"invalid data_type: {d.data_type}"
        assert d.cip_table in valid_tables, f"invalid cip_table: {d.cip_table}"
        assert d.storage_location == "column"
        assert d.is_custom is False


def test_rate_limit_policy_matches_hubspot_standard_plan() -> None:
    conn, _ = _make_connector()
    policy = conn.rate_limit_policy
    assert policy.requests_per_second == 10.0
    assert policy.burst == 10


# ── HubSpotMapper tests ────────────────────────────────────────────────────


def test_mapper_company_routes_to_cip_companies() -> None:
    mapper = HubSpotMapper()
    rows = list(mapper.map({
        "__cip_kind__": "company",
        "source_id": "42",
        "name": "Acme",
        "domain": "acme.com",
        "industry": "tech",
        "numberofemployees": "150",
    }))
    assert len(rows) == 1
    row = rows[0]
    assert row.target_table == "cip_companies"
    assert row.source_id == "42"
    assert row.fields["name"] == "Acme"
    assert row.fields["domain"] == "acme.com"
    # numberofemployees → employee_count, coerced to Decimal
    assert row.fields["employee_count"] == Decimal("150")


def test_mapper_ticket_with_subject_passes_through() -> None:
    mapper = HubSpotMapper()
    rows = list(mapper.map({
        "__cip_kind__": "ticket",
        "source_id": "99",
        "subject": "Login broken",
        "content": "Tim cannot log in",
        "hs_ticket_priority": "HIGH",
    }))
    assert len(rows) == 1
    row = rows[0]
    assert row.target_table == "cip_tickets"
    assert row.fields["subject"] == "Login broken"
    assert row.fields["description"] == "Tim cannot log in"  # content → description
    assert row.fields["priority"] == "HIGH"  # hs_ticket_priority → priority


def test_mapper_unknown_kind_raises_schema_drift() -> None:
    mapper = HubSpotMapper()
    with pytest.raises(SchemaDriftError, match="unknown __cip_kind__"):
        list(mapper.map({"__cip_kind__": "spaceship", "source_id": "1"}))


def test_mapper_ingest_as_knowledge_emits_for_tickets() -> None:
    mapper = HubSpotMapper()
    texts = mapper.ingest_as_knowledge({
        "__cip_kind__": "ticket",
        "source_id": "5",
        "content": "User reports login failure on iOS",
    })
    assert len(texts) == 1
    assert "login" in texts[0].text.lower()
    assert texts[0].metadata["source_id"] == "5"


def test_mapper_ingest_as_knowledge_empty_for_companies() -> None:
    mapper = HubSpotMapper()
    texts = mapper.ingest_as_knowledge({
        "__cip_kind__": "company",
        "source_id": "5",
        "name": "Acme",
    })
    assert texts == []


def test_mapper_ingest_as_knowledge_empty_for_backfill() -> None:
    """Backfill records should not re-emit knowledge text."""
    mapper = HubSpotMapper()
    texts = mapper.ingest_as_knowledge({
        "__cip_kind__": "ticket",
        "__cip_backfill__": True,
        "source_id": "5",
        "content": "Old ticket body",
    })
    assert texts == []
