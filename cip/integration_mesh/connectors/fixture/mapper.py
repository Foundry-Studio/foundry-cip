# foundry: kind=service domain=client-intelligence-platform touches=integration
"""FixtureMapper — canonical reference implementation of CIPMapper
(M3 §4.6 binding).

For each fixture record, emits exactly 1 ``CIPRow`` and (for body-bearing
record types) 1 ``KnowledgeText``.

Per v5.4 reconciliations:
- ``KnowledgeText.metadata`` is ``total=False`` TypedDict; mapper emits
  ``source_id`` only. Orchestrator finalizes operational keys
  (tenant_id, source_system, connector_version, extracted_at,
  ingestion_batch_id) before validation. Detect-then-assign on the two
  orchestrator-owned keys per Δ8.
- Δ4 (per-table EXTRAS_COLUMN_BY_TABLE): mapper does NOT need to know
  which column the overflow lands in. ``CIPRow.overflow`` is opaque to
  the mapper; persister consults ``EXTRAS_COLUMN_BY_TABLE`` at write time.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, cast

from cip.integration_mesh.base import (
    CIPMapperBase,
    CIPRow,
    KnowledgeText,
    KnowledgeTextMetadata,
)
from cip.integration_mesh.exceptions import SchemaDriftError

# Target table per record_type. Per v2 #2 (Senior #2): no notes mapping —
# FixtureConnector emits 0 notes; if Phase 2 lands a cip_notes migration,
# add ``"note": "cip_notes"`` here.
_TARGET_TABLE_BY_TYPE: dict[str, str] = {
    "company": "cip_companies",
    "contact": "cip_contacts",
    "deal": "cip_deals",
    "ticket": "cip_tickets",
    "document": "cip_files",
}

# Domain columns (storage_location='column' in describe_schema) per type.
# CONSISTENCY CONTRACT (v2 — Senior #1): this dict MUST match
# describe_schema()'s storage_location='column' descriptors per object_type.
# ``test_fixture_mapper.py::test_domain_fields_match_describe_schema_column_descriptors``
# enforces the consistency. Drift in either source-of-truth fails the test.
#
# Keys here are CIPRow.fields keys (record-side names). Persister maps these
# to deployed SQL columns; ``ticket.body`` → SQL column ``description`` per
# the deployed cip_08_tickets_and_registry migration; ``document.title`` →
# SQL column ``filename``; etc. The mapper doesn't track that translation —
# the persister + describe_schema do.
_DOMAIN_FIELDS_BY_TYPE: dict[str, set[str]] = {
    "company": {"name", "industry", "region", "domain"},
    "contact": {"first_name", "last_name", "email", "title", "phone"},
    "deal": {"name", "amount", "stage"},
    "ticket": {"subject", "body", "status", "priority", "assignee"},
    "document": {"title", "mime_type", "file_size_bytes"},
}

# Knowledge-emitting types — types whose records produce KnowledgeText for M5.
# Per v2 #2: notes excluded; tickets + documents are the body-bearing types.
_KNOWLEDGE_EMITTING_TYPES: frozenset[str] = frozenset({"ticket", "document"})

# Reserved record fields that flow neither to CIPRow.fields nor overflow
# (orchestrator-handled or shape metadata).
_RESERVED: frozenset[str] = frozenset({"record_type", "source_id", "id", "updated_at"})


class FixtureMapper(CIPMapperBase):
    """Reference CIPMapper. Inherits from CIPMapperBase for default behavior."""

    object_type: str = "fixture"  # superseded per-call by record's record_type
    target_table: str = "cip_contacts"  # default; per-call resolved via _TARGET_TABLE_BY_TYPE

    def map(self, record: dict[str, object]) -> Iterable[CIPRow]:
        """Emit exactly 1 CIPRow per record.

        Raises ``SchemaDriftError`` on unknown ``record_type``.
        """
        rec_type_obj = record.get("record_type")
        if not isinstance(rec_type_obj, str) or rec_type_obj not in _TARGET_TABLE_BY_TYPE:
            raise SchemaDriftError(
                f"FixtureMapper does not handle record_type={rec_type_obj!r}; "
                f"known types: {sorted(_TARGET_TABLE_BY_TYPE)}"
            )
        rec_type = rec_type_obj
        target = _TARGET_TABLE_BY_TYPE[rec_type]
        domain_keys = _DOMAIN_FIELDS_BY_TYPE[rec_type]

        fields: dict[str, object] = {
            k: v for k, v in record.items() if k in domain_keys
        }
        overflow: dict[str, object] = {
            k: v
            for k, v in record.items()
            if k not in domain_keys and k not in _RESERVED
        }

        yield CIPRow(
            target_table=target,
            source_id=str(record["source_id"]),
            fields=fields,
            overflow=overflow,
            authority="ingested",
        )

    def overflow_fields(self) -> list[str]:
        """Aggregate the overflow field names across all known types.

        Per CIPMapper Protocol the method takes no per-type argument. Returns
        the union of overflow keys across all 5 active object types so the
        orchestrator's registry-write side can plan for them.
        """
        return sorted(
            {
                "employee_count",
                "annual_revenue",
                "custom_field_1",
                "custom_field_2",
                "region",  # contact.region
                "expected_close_date",
                "owner",
                "body",  # document.body (storage_location='overflow' per descriptor)
                "company_source_id",
                "contact_source_id",
            }
        )

    def authority(
        self,
    ) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        """Emit a KnowledgeText for body-bearing types (ticket / document).

        Per v5.4 Δ8 + Round-6 Call A: mapper emits ``source_id`` only in
        metadata. Orchestrator finalizes the rest at boundary.
        """
        rec_type = record.get("record_type")
        if not isinstance(rec_type, str) or rec_type not in _KNOWLEDGE_EMITTING_TYPES:
            return []

        # tickets carry body; documents carry body. Both can be substantive;
        # gracefully no-op on whitespace-only or missing (Gap #10).
        body_obj = record.get("body") or ""
        body = str(body_obj).strip()
        if not body:
            return []

        md: dict[str, object] = {"source_id": str(record["source_id"])}
        return [
            KnowledgeText(
                text=body,
                metadata=cast(KnowledgeTextMetadata, md),
            )
        ]
