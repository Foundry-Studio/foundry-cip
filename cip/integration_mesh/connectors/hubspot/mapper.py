# foundry: kind=service domain=client-intelligence-platform touches=integration
"""HubSpotMapper — SCAFFOLD ONLY.

Maps HubSpot records (companies, contacts, deals, tickets) to ``CIPRow``s
targeting ``cip_companies`` / ``cip_contacts`` / ``cip_deals`` / ``cip_tickets``.

Phase 2 implementation will need:

- ``map(record)`` — dispatch on record-side type indicator (HubSpot
  records carry ``properties`` dict + ``id`` + ``objectType`` from v3
  API). Mirror FixtureMapper's record-type → target-table routing.
- ``overflow_fields()`` — HubSpot custom properties (per portal) route
  to the per-table JSONB extras column (``properties`` for cip_companies/
  cip_contacts/cip_deals/cip_tickets per CONNECTOR-AUTHORING-GUIDE.md §7).
- ``authority()`` — return ``"ingested"`` for Phase 2 (default).
- ``ingest_as_knowledge(record)`` — emit ``KnowledgeText`` for ticket
  bodies, deal notes, contact engagement summaries; empty list for
  pure-structured records (companies, deals without notes).

Reference: ``cip/integration_mesh/connectors/fixture/mapper.py``.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from cip.integration_mesh.base import (
    CIPMapperBase,
    CIPRow,
    KnowledgeText,
)


class HubSpotMapper(CIPMapperBase):
    """HubSpot record → CIPRow mapper. SCAFFOLD — Phase 2 implementation."""

    object_type: str = "hubspot"  # superseded per-call by record-side kind
    target_table: str = "cip_companies"  # default; per-call resolved

    def map(self, record: dict[str, object]) -> Iterable[CIPRow]:
        raise NotImplementedError(
            "HubSpotMapper.map — Phase 2 implementation pending. See "
            "FixtureMapper at cip/integration_mesh/connectors/fixture/mapper.py "
            "for the canonical pattern (record-type dispatch + "
            "_RECORD_TO_SQL_COLUMN translation + overflow routing)."
        )

    def overflow_fields(self) -> list[str]:
        raise NotImplementedError(
            "HubSpotMapper.overflow_fields — Phase 2. Return list of "
            "HubSpot custom-property keys that route to the target "
            "table's JSONB extras column."
        )

    def authority(self) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"  # Phase 2 default per CONNECTOR-AUTHORING-GUIDE.md §8

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        raise NotImplementedError(
            "HubSpotMapper.ingest_as_knowledge — Phase 2. Emit "
            "KnowledgeText for ticket bodies, deal notes, contact "
            "engagement summaries; empty list for pure-structured records."
        )
