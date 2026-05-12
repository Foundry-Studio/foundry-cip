# foundry: kind=service domain=client-intelligence-platform touches=integration
"""ZendeskMapper — SCAFFOLD ONLY.

Maps Zendesk records (tickets, users, organizations) to ``CIPRow``s
targeting ``cip_tickets`` / ``cip_contacts`` / ``cip_companies``.

Phase 2 implementation will need:

- ``map(record)`` — dispatch on a record-side type indicator (Zendesk's
  ``type`` field on tickets is "incident/problem/question"; for entity
  routing use ``__cip_kind__`` injected by the connector — same pattern
  as FixtureMapper's ``record_type``).
- ``overflow_fields()`` — Zendesk-specific custom fields that don't
  match a column on the target ``cip_*`` table; these route to the
  per-table JSONB extras column (``properties`` for most tables; per
  CONNECTOR-AUTHORING-GUIDE.md §7).
- ``authority()`` — return ``"ingested"`` for Phase 2 (default).
- ``ingest_as_knowledge(record)`` — emit ``KnowledgeText`` for ticket
  bodies and comment threads (the high-signal text in Zendesk data);
  empty list for users/orgs which are pure structured records.

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


class ZendeskMapper(CIPMapperBase):
    """Zendesk record → CIPRow mapper. SCAFFOLD — Phase 2 implementation."""

    object_type: str = "zendesk"  # superseded per-call by record-side kind
    target_table: str = "cip_tickets"  # default; per-call resolved

    def map(self, record: dict[str, object]) -> Iterable[CIPRow]:
        raise NotImplementedError(
            "ZendeskMapper.map — Phase 2 implementation pending. See "
            "FixtureMapper at cip/integration_mesh/connectors/fixture/mapper.py "
            "for the canonical pattern (record-type dispatch + "
            "_RECORD_TO_SQL_COLUMN translation + overflow routing)."
        )

    def overflow_fields(self) -> list[str]:
        raise NotImplementedError(
            "ZendeskMapper.overflow_fields — Phase 2. Return list of "
            "Zendesk custom-field keys that route to the target table's "
            "JSONB extras column."
        )

    def authority(self) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"  # Phase 2 default per CONNECTOR-AUTHORING-GUIDE.md §8

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        raise NotImplementedError(
            "ZendeskMapper.ingest_as_knowledge — Phase 2. Emit "
            "KnowledgeText for ticket bodies + comment threads; empty "
            "list for users/orgs (pure structured)."
        )
