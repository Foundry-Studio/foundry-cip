# foundry: kind=service domain=client-intelligence-platform touches=integration
"""ZendeskMapper — maps Zendesk v2 records to ``CIPRow``s.

Implements the full CIPMapper Protocol. Dispatches per-record on
``__cip_kind__`` (company / contact / ticket) → corresponding ``cip_*``
table. Zendesk organizations map to ``cip_companies``; Zendesk users to
``cip_contacts``.

Knowledge text:
- Ticket descriptions emit ``KnowledgeText`` for vector+BM25 ingestion.
- Other entities emit empty list.

Reference: ``cip/integration_mesh/connectors/fixture/mapper.py``.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from cip.integration_mesh.base import (
    CIPMapperBase,
    CIPRow,
    KnowledgeText,
    KnowledgeTextMetadata,
)
from cip.integration_mesh.exceptions import SchemaDriftError

_TARGET_TABLE_BY_TYPE: dict[str, str] = {
    "company": "cip_companies",
    "contact": "cip_contacts",
    "ticket": "cip_tickets",
    "ticket_comment": "cip_ticket_comments",
}

# Domain columns per cip_* table accepting Zendesk values directly.
_DOMAIN_FIELDS_BY_TYPE: dict[str, set[str]] = {
    "company": {"name", "domain"},  # cip_companies columns the mapper can fill
    "contact": {"first_name", "last_name", "email", "phone"},
    "ticket": {"subject", "description", "priority", "status"},
    "ticket_comment": {
        "ticket_source_id", "author_id", "author_email", "body", "html_body",
        "is_public", "via_channel", "attachments_count", "attachment_urls",
        "source_created_at",
    },
}

# Zendesk field name → cip_* SQL column name. Identity where omitted.
_RECORD_TO_SQL_COLUMN: dict[str, dict[str, str]] = {
    "company": {},
    "contact": {
        # Zendesk has a single "name" field; split into first/last by space.
        # Handled at map-time, not via static translation.
    },
    "ticket": {},
}

_RESERVED: set[str] = {
    "__cip_kind__",
    "__cip_backfill__",
    "__cip_valid_from__",
    "__cip_valid_to__",
    "id",
    "source_id",
    "updated_at",
    "record_type",
}

# Datetime fields per kind that need ISO-string → datetime conversion
# before they reach the persister (which asserts tz-aware datetimes).
_DATETIME_FIELDS: dict[str, set[str]] = {
    "ticket_comment": {"source_created_at"},
}


def _parse_zendesk_datetime(value: object) -> object:
    """Convert Zendesk ISO-8601 string (with Z suffix) to tz-aware datetime."""
    if not isinstance(value, str):
        return value
    from datetime import datetime as _dt
    if value.endswith("Z"):
        return _dt.fromisoformat(value.replace("Z", "+00:00"))
    return _dt.fromisoformat(value)


class ZendeskMapper(CIPMapperBase):
    """Zendesk v2 record → CIPRow mapper.

    Per-record dispatch on ``__cip_kind__``. Zendesk organizations →
    cip_companies; users → cip_contacts; tickets → cip_tickets.
    """

    object_type: str = "zendesk"
    target_table: str = "cip_tickets"

    def map(self, record: dict[str, object]) -> Iterable[CIPRow]:
        kind = record.get("__cip_kind__")
        if not isinstance(kind, str) or kind not in _TARGET_TABLE_BY_TYPE:
            raise SchemaDriftError(
                f"ZendeskMapper: unknown __cip_kind__={kind!r}; "
                f"known: {sorted(_TARGET_TABLE_BY_TYPE)}"
            )
        target = _TARGET_TABLE_BY_TYPE[kind]
        domain_keys = _DOMAIN_FIELDS_BY_TYPE[kind]

        fields: dict[str, object] = {}
        overflow: dict[str, object] = {}

        # Zendesk user "name" → split into first_name / last_name for cip_contacts
        if kind == "contact":
            name = record.get("name")
            if isinstance(name, str) and name.strip():
                parts = name.strip().split(" ", 1)
                fields["first_name"] = parts[0]
                fields["last_name"] = parts[1] if len(parts) > 1 else ""

        # Zendesk org "domain_names" is a list — emit first one to cip_companies.domain
        if kind == "company":
            domains = record.get("domain_names")
            if isinstance(domains, list) and domains:
                fields["domain"] = str(domains[0])

        dt_fields = _DATETIME_FIELDS.get(kind, set())
        for k, v in record.items():
            if k in _RESERVED:
                continue
            if k == "name" and kind == "contact":
                continue  # already handled above
            if k == "domain_names" and kind == "company":
                continue  # already handled above
            sql_col = _RECORD_TO_SQL_COLUMN.get(kind, {}).get(k, k)
            if sql_col in domain_keys:
                fields[sql_col] = (
                    _parse_zendesk_datetime(v) if sql_col in dt_fields else v
                )
            else:
                overflow[k] = v

        # Tickets need non-null subject
        if kind == "ticket" and "subject" not in fields:
            fields["subject"] = "(no subject)"

        # cip_companies requires non-null name
        if kind == "company" and "name" not in fields:
            fields["name"] = f"(zendesk org #{record.get('source_id', '?')})"

        # Comments: ticket_source_id is NOT NULL in the schema; fail loud
        # if the connector forgot to set it (would indicate a bug upstream).
        if kind == "ticket_comment" and not fields.get("ticket_source_id"):
            raise SchemaDriftError(
                "ZendeskMapper: ticket_comment record missing ticket_source_id"
            )

        yield CIPRow(
            target_table=target,
            source_id=str(record.get("source_id", "")),
            fields=fields,
            overflow=overflow,
            authority="ingested",
        )

    def overflow_fields(self) -> list[str]:
        return sorted({
            "details", "notes",  # company
            "role", "organization_id",  # contact
            "type", "requester_id", "assignee_id",  # ticket
            "tags",  # all kinds
        })

    def authority(self) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        if record.get("__cip_backfill__"):
            return []
        kind = record.get("__cip_kind__")
        if kind == "ticket":
            body = record.get("description") or record.get("content") or ""
            if not isinstance(body, str) or not body.strip():
                return []
            return [
                KnowledgeText(
                    text=body,
                    metadata=KnowledgeTextMetadata(
                        source_id=str(record.get("source_id", "")),
                    ),
                )
            ]
        if kind == "ticket_comment":
            body = record.get("body") or ""
            if not isinstance(body, str) or not body.strip():
                return []
            return [
                KnowledgeText(
                    text=body,
                    metadata=KnowledgeTextMetadata(
                        source_id=str(record.get("source_id", "")),
                    ),
                )
            ]
        return []
