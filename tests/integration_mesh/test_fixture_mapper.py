# foundry: kind=test domain=client-intelligence-platform
"""M3 unit tests for FixtureMapper (M3 §6).

Per-type CIPRow shape, SchemaDriftError on unknown record_type, KnowledgeText
emission per knowledge-bearing type, honest-mock metadata (mapper emits
source_id only). Includes the consistency contract test (Senior #1) that
``_DOMAIN_FIELDS_BY_TYPE`` matches ``describe_schema()`` column descriptors.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from cip.integration_mesh import CIPRow, KnowledgeText
from cip.integration_mesh.connectors.fixture import (
    CorpusSize,
    FixtureConnector,
    FixtureMapper,
)
from cip.integration_mesh.connectors.fixture.mapper import (
    _DOMAIN_FIELDS_BY_TYPE,
    _KNOWLEDGE_EMITTING_TYPES,
    _RESERVED,
    _TARGET_TABLE_BY_TYPE,
)
from cip.integration_mesh.exceptions import SchemaDriftError


@pytest.fixture
def mapper() -> FixtureMapper:
    return FixtureMapper()


@pytest.fixture
def connector() -> FixtureConnector:
    return FixtureConnector(tenant_id=uuid4(), seed=42, size=CorpusSize.COMPACT)


# ── Per-type CIPRow shape ────────────────────────────────────────────────


class TestPerTypeMap:
    def test_company_maps_to_cip_companies(
        self, mapper: FixtureMapper, connector: FixtureConnector
    ) -> None:
        rec = connector.corpus["companies"][0]
        rows = list(mapper.map(rec))
        assert len(rows) == 1
        r = rows[0]
        assert isinstance(r, CIPRow)
        assert r.target_table == "cip_companies"
        assert r.source_id == rec["source_id"]
        # Domain fields ⊆ _DOMAIN_FIELDS_BY_TYPE['company']
        assert set(r.fields.keys()) <= _DOMAIN_FIELDS_BY_TYPE["company"]
        # Reserved keys never in fields or overflow.
        assert _RESERVED.isdisjoint(r.fields.keys())
        assert _RESERVED.isdisjoint(r.overflow.keys())

    def test_contact_maps_to_cip_contacts(
        self, mapper: FixtureMapper, connector: FixtureConnector
    ) -> None:
        rec = connector.corpus["contacts"][0]
        rows = list(mapper.map(rec))
        assert rows[0].target_table == "cip_contacts"
        assert "first_name" in rows[0].fields
        assert "email" in rows[0].fields

    def test_deal_maps_to_cip_deals(
        self, mapper: FixtureMapper, connector: FixtureConnector
    ) -> None:
        rec = connector.corpus["deals"][0]
        rows = list(mapper.map(rec))
        assert rows[0].target_table == "cip_deals"
        assert {"name", "amount", "stage"} <= set(rows[0].fields.keys())

    def test_ticket_maps_to_cip_tickets(
        self, mapper: FixtureMapper, connector: FixtureConnector
    ) -> None:
        rec = connector.corpus["tickets"][0]
        rows = list(mapper.map(rec))
        assert rows[0].target_table == "cip_tickets"
        assert "subject" in rows[0].fields
        # Δ5: record-side ``body`` → SQL column ``description`` (cip_08
        # migration uses ``description`` for ticket body); ``assignee`` →
        # ``assignee_name``. The translation lives in mapper._RECORD_TO_SQL_COLUMN.
        assert "description" in rows[0].fields
        assert "body" not in rows[0].fields
        assert "assignee_name" in rows[0].fields

    def test_document_maps_to_cip_files(
        self, mapper: FixtureMapper, connector: FixtureConnector
    ) -> None:
        rec = connector.corpus["documents"][0]
        rows = list(mapper.map(rec))
        assert rows[0].target_table == "cip_files"
        # Δ5: ``title`` → SQL column ``filename`` (cip_04_files migration);
        # ``file_size_bytes`` → ``size_bytes``.
        assert "filename" in rows[0].fields
        assert "title" not in rows[0].fields
        assert "size_bytes" in rows[0].fields

    def test_authority_is_ingested(
        self, mapper: FixtureMapper, connector: FixtureConnector
    ) -> None:
        rec = connector.corpus["companies"][0]
        rows = list(mapper.map(rec))
        assert rows[0].authority == "ingested"


# ── SchemaDriftError on unknown record_type ──────────────────────────────


class TestSchemaDrift:
    def test_unknown_type_raises(self, mapper: FixtureMapper) -> None:
        bad: dict[str, object] = {
            "record_type": "alien",
            "source_id": "x",
            "id": "x",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        with pytest.raises(SchemaDriftError, match="alien"):
            list(mapper.map(bad))

    def test_missing_record_type_raises(self, mapper: FixtureMapper) -> None:
        bad: dict[str, object] = {
            "source_id": "x",
            "id": "x",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        with pytest.raises(SchemaDriftError):
            list(mapper.map(bad))


# ── KnowledgeText emission ───────────────────────────────────────────────


class TestKnowledgeText:
    def test_ticket_emits_knowledge_text(
        self, mapper: FixtureMapper, connector: FixtureConnector
    ) -> None:
        rec = connector.corpus["tickets"][0]
        kts = mapper.ingest_as_knowledge(rec)
        assert len(kts) == 1
        kt = kts[0]
        assert isinstance(kt, KnowledgeText)
        assert kt.text == rec["body"]
        # Honest mock: only source_id in metadata.
        assert dict(kt.metadata) == {"source_id": rec["source_id"]}

    def test_document_emits_knowledge_text(
        self, mapper: FixtureMapper, connector: FixtureConnector
    ) -> None:
        rec = connector.corpus["documents"][0]
        kts = mapper.ingest_as_knowledge(rec)
        assert len(kts) == 1
        assert kts[0].text == rec["body"]

    def test_company_emits_no_knowledge_text(
        self, mapper: FixtureMapper, connector: FixtureConnector
    ) -> None:
        rec = connector.corpus["companies"][0]
        assert mapper.ingest_as_knowledge(rec) == []

    def test_contact_emits_no_knowledge_text(
        self, mapper: FixtureMapper, connector: FixtureConnector
    ) -> None:
        rec = connector.corpus["contacts"][0]
        assert mapper.ingest_as_knowledge(rec) == []

    def test_empty_body_emits_no_knowledge_text(self, mapper: FixtureMapper) -> None:
        # Gap #10: whitespace-only body skipped.
        rec: dict[str, object] = {
            "record_type": "ticket",
            "source_id": "t1",
            "id": "t1",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "body": "   ",
            "subject": "x",
            "status": "open",
            "priority": "low",
        }
        assert mapper.ingest_as_knowledge(rec) == []

    def test_mapper_does_not_emit_orchestrator_owned_keys(
        self, mapper: FixtureMapper, connector: FixtureConnector
    ) -> None:
        # Per Δ8: mapper does NOT emit tenant_id, ingestion_batch_id,
        # source_system, connector_version, extracted_at.
        for rec_type in ("tickets", "documents"):
            for rec in connector.corpus[rec_type]:
                for kt in mapper.ingest_as_knowledge(rec):
                    md_keys = set(kt.metadata.keys())
                    forbidden = {
                        "tenant_id", "ingestion_batch_id", "source_system",
                        "connector_version", "extracted_at",
                    }
                    assert md_keys & forbidden == set(), (
                        f"mapper emitted orchestrator-owned key(s): "
                        f"{md_keys & forbidden}"
                    )


# ── Senior #1 consistency contract ───────────────────────────────────────


class TestDomainFieldsConsistency:
    """``_DOMAIN_FIELDS_BY_TYPE`` MUST match describe_schema() column
    descriptors per object_type. Drift in either source-of-truth fails."""

    def test_domain_fields_match_describe_schema_column_descriptors(
        self, connector: FixtureConnector
    ) -> None:
        for object_type, expected_fields in _DOMAIN_FIELDS_BY_TYPE.items():
            schema_columns = {
                d.property_name
                for d in connector.describe_schema()
                if d.object_type == object_type and d.storage_location == "column"
            }
            assert schema_columns == expected_fields, (
                f"Drift for object_type={object_type!r}: "
                f"_DOMAIN_FIELDS_BY_TYPE has {expected_fields}, "
                f"describe_schema() column-stored has {schema_columns}"
            )


# ── overflow_fields ──────────────────────────────────────────────────────


class TestOverflowFields:
    def test_returns_sorted_list(self, mapper: FixtureMapper) -> None:
        fields = mapper.overflow_fields()
        assert fields == sorted(fields)
        assert isinstance(fields, list)
        assert len(fields) > 0


# ── Constants ────────────────────────────────────────────────────────────


class TestConstants:
    def test_target_table_by_type_covers_active_types(self) -> None:
        # Per v2 #2: 5 active types (notes dropped).
        assert set(_TARGET_TABLE_BY_TYPE) == {
            "company", "contact", "deal", "ticket", "document",
        }

    def test_knowledge_emitting_types(self) -> None:
        # Tickets + documents only.
        assert frozenset({"ticket", "document"}) == _KNOWLEDGE_EMITTING_TYPES
