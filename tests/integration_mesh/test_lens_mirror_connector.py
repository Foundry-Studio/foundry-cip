# foundry: kind=test domain=client-intelligence-platform
"""Unit tests for the LensMirrorConnector + mappers (Phase 2.6 PM scope 280a2f20).

These tests cover Protocol conformance + mapper output shape + the
defining invariants of the Atlas-locked design (companion_data not
written; initial_intake_route not in mapper output; client_id resolved
via lookup; unattributable rows skipped).

DB-touching behavior is covered separately by manual prod smoke
(scripts/orchestrate_ps_lens_mirror.py first run). Unit tests use
unittest.mock for the source engine so they run offline + fast.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import create_engine

from cip.integration_mesh.base import CIPConnector, CIPMapper
from cip.integration_mesh.connectors.lens_mirror import (
    LensMirrorCompanyMapper,
    LensMirrorConnector,
    LensMirrorContactMapper,
    LensMirrorDealMapper,
)

PS_TENANT = UUID("078a37d6-6ae2-4e22-869e-cc08f6cb2787")
ECOMLEVER_TENANT = UUID("dec814db-722a-4730-8e60-51afc4a5dad9")


# ── Protocol conformance ─────────────────────────────────────────────────


def test_connector_conforms_to_cipconnector_protocol() -> None:
    """LensMirrorConnector must satisfy the runtime-checkable CIPConnector
    Protocol shape (D-134 / M2 binding)."""
    # Use sqlite::memory: to avoid network — only the Engine handle matters
    # for the Protocol check, not actual queries.
    src_engine = create_engine("sqlite:///:memory:")
    connector = LensMirrorConnector(
        tenant_id=PS_TENANT,
        source_tenant_id=ECOMLEVER_TENANT,
        source_lens="lens_china_clients",
        source_engine=src_engine,
        connector_id="lens-mirror-deals-v1",
    )
    assert isinstance(connector, CIPConnector)
    assert connector.tenant_id == PS_TENANT
    assert connector.connector_id == "lens-mirror-deals-v1"
    # cursor_safety_window_seconds should be 0 (full-mirror, no replica lag concern)
    assert connector.cursor_safety_window_seconds == 0


def test_mappers_conform_to_cipmapper_protocol() -> None:
    lookup: dict[str, UUID] = {}
    for cls in (LensMirrorDealMapper, LensMirrorCompanyMapper, LensMirrorContactMapper):
        mapper = cls(client_id_lookup=lookup)
        assert isinstance(mapper, CIPMapper), f"{cls.__name__} does not conform"
        assert mapper.object_type.startswith("lens-mirror-")
        assert mapper.target_table.startswith("cip_")


# ── Mapper output invariants (Atlas-locked design) ────────────────────────


def _ps_client_id_for(hubspot_id: str) -> UUID:
    """Deterministic mapping mirroring orchestrate_ps_lens_mirror.py Pass 1."""
    from uuid import uuid5
    return uuid5(PS_TENANT, f"wayward-china:{hubspot_id}")


def test_company_mapper_routes_via_source_id() -> None:
    """LensMirrorCompanyMapper looks up client_id via source.source_id
    (the HubSpot company id)."""
    hubspot_id = "92826776258"
    ps_client = _ps_client_id_for(hubspot_id)
    lookup = {hubspot_id: ps_client}
    mapper = LensMirrorCompanyMapper(client_id_lookup=lookup)

    source_row = {
        "id": uuid4(),
        "tenant_id": ECOMLEVER_TENANT,
        "client_id": UUID("661ecab4-dddb-5924-a34d-af1c5133132d"),
        "source_connector": "hubspot-v1",
        "source_id": hubspot_id,
        "name": "Test China Brand Co.",
        "domain": "testbrand.cn",
        "industry": "ecommerce",
        "properties": {"hs_lead_status": "OPEN"},
        "companion_data": {"twenty_note": "should not leak into mapper output"},
        "initial_intake_route": "should_not_be_in_mapper_output",
        "_source_lens": "lens_china_companies",
    }
    rows = list(mapper.map(source_row))
    assert len(rows) == 1
    row = rows[0]
    assert row.target_table == "cip_companies"
    assert row.source_id == hubspot_id
    assert row.client_id == ps_client
    assert row.authority == "ingested"
    # Domain fields populated
    assert row.fields["name"] == "Test China Brand Co."
    assert row.fields["domain"] == "testbrand.cn"
    # Companion data NOT in fields (Atlas Q1)
    assert "companion_data" not in row.fields
    assert "companion_data" not in row.overflow
    # initial_intake_route NOT in fields (Atlas C-2)
    assert "initial_intake_route" not in row.fields
    assert "initial_intake_route" not in row.overflow
    # Original properties merged into overflow
    assert row.overflow.get("hs_lead_status") == "OPEN"
    # source-side tenant_id / source_connector stripped
    assert "tenant_id" not in row.fields
    assert "source_connector" not in row.fields


def test_contact_mapper_routes_via_associatedcompanyid() -> None:
    hubspot_company_id = "92826776258"
    ps_client = _ps_client_id_for(hubspot_company_id)
    lookup = {hubspot_company_id: ps_client}
    mapper = LensMirrorContactMapper(client_id_lookup=lookup)

    source_row = {
        "id": uuid4(),
        "tenant_id": ECOMLEVER_TENANT,
        "source_connector": "hubspot-v1",
        "source_id": "contact-1",
        "first_name": "Wang",
        "last_name": "Mei",
        "email": "wang@testbrand.cn",
        "properties": {"associatedcompanyid": hubspot_company_id, "hs_seniority": "exec"},
    }
    rows = list(mapper.map(source_row))
    assert len(rows) == 1
    assert rows[0].client_id == ps_client
    assert rows[0].target_table == "cip_contacts"
    assert rows[0].fields["email"] == "wang@testbrand.cn"


def test_deal_mapper_routes_via_hs_primary_associated_company() -> None:
    hubspot_company_id = "92826776258"
    ps_client = _ps_client_id_for(hubspot_company_id)
    lookup = {hubspot_company_id: ps_client}
    mapper = LensMirrorDealMapper(client_id_lookup=lookup)

    source_row = {
        "id": uuid4(),
        "tenant_id": ECOMLEVER_TENANT,
        "source_connector": "hubspot-v1",
        "source_id": "deal-51222531798",
        "name": "Cane Brand Onboarding",
        "amount": 12500.0,
        "stage": "appointment-scheduled",
        "properties": {
            "hs_primary_associated_company": hubspot_company_id,
            "source": "China Referral - Eric",
        },
    }
    rows = list(mapper.map(source_row))
    assert len(rows) == 1
    assert rows[0].client_id == ps_client
    assert rows[0].fields["amount"] == 12500.0
    # The 'source' attribution stays in overflow
    assert rows[0].overflow.get("source") == "China Referral - Eric"


def test_unattributable_row_is_skipped() -> None:
    """Rows whose lookup key resolves to None are SKIPPED (yield empty),
    not raised — Atlas C-1 contract."""
    mapper = LensMirrorCompanyMapper(client_id_lookup={})
    rows = list(mapper.map({
        "source_id": "unknown-hubspot-id",
        "tenant_id": ECOMLEVER_TENANT,
        "name": "Should not appear",
    }))
    assert rows == []


def test_mapper_does_not_emit_companion_data_even_when_present_in_source() -> None:
    """Defensive: even if the source row carries companion_data (e.g.,
    a future flow leaks it through the lens view), the mapper must not
    emit it. Atlas Q1 — companion is destination-private."""
    hubspot_id = "92826776258"
    lookup = {hubspot_id: _ps_client_id_for(hubspot_id)}
    mapper = LensMirrorCompanyMapper(client_id_lookup=lookup)
    rows = list(mapper.map({
        "source_id": hubspot_id,
        "tenant_id": ECOMLEVER_TENANT,
        "name": "X",
        "companion_data": {"leaked": True},
    }))
    assert rows
    # Walk every place fields/overflow could leak companion_data
    for r in rows:
        assert "companion_data" not in r.fields
        assert "companion_data" not in r.overflow


def test_mapper_strips_orchestrator_owned_fields() -> None:
    """tenant_id / id / ingestion_batch_id etc. must never appear in
    CIPRow.fields or CIPRow.overflow — orchestrator owns those."""
    hubspot_id = "92826776258"
    lookup = {hubspot_id: _ps_client_id_for(hubspot_id)}
    mapper = LensMirrorCompanyMapper(client_id_lookup=lookup)
    rows = list(mapper.map({
        "id": uuid4(),
        "tenant_id": ECOMLEVER_TENANT,
        "client_id": UUID("661ecab4-dddb-5924-a34d-af1c5133132d"),
        "source_connector": "hubspot-v1",  # should be rewritten by orchestrator/persister
        "source_id": hubspot_id,
        "ingested_at": "2026-05-22T00:00:00+00:00",
        "refreshed_at": "2026-05-22T00:00:00+00:00",
        "ingestion_batch_id": uuid4(),
        "previous_version_id": None,
        "name": "X",
    }))
    assert rows
    fields = rows[0].fields
    overflow = rows[0].overflow
    for forbidden in (
        "id", "tenant_id", "client_id", "source_connector", "source_id",
        "ingested_at", "refreshed_at", "ingestion_batch_id", "previous_version_id",
    ):
        assert forbidden not in fields, f"{forbidden} leaked into fields"
        assert forbidden not in overflow, f"{forbidden} leaked into overflow"
