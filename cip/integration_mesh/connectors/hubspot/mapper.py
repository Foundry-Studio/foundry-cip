# foundry: kind=service domain=client-intelligence-platform touches=integration
"""HubSpotMapper — maps HubSpot v3 records to ``CIPRow``s.

Implements the full CIPMapper Protocol. Dispatches per-record on the
``__cip_kind__`` marker the connector injects (company / contact / deal
/ ticket) → corresponding ``cip_*`` table.

Key behaviors:
- HubSpot property names → SQL column names per ``_RECORD_TO_SQL_COLUMN``
  (e.g. ``hs_lastmodifieddate`` → ``updated_at`` is NOT done; we keep
  HubSpot names where the cip schema accepts them and route the rest to
  the per-table JSONB ``properties`` overflow column).
- HubSpot returns property values as strings (even for numbers); the
  mapper coerces numerics where the target cip_* column is NUMERIC /
  INTEGER per M3 Δ7 (Decimal round-trip discipline).
- Backfill records (``__cip_backfill__: True``) emit a single CIPRow
  the same way as current-state — the orchestrator's SCD-2 differ
  recognizes the historical valid_from/valid_to via the
  ``__cip_valid_from__`` / ``__cip_valid_to__`` markers and writes the
  history row directly without bumping the current-state row.

Knowledge text:
- Ticket bodies (``content``) and deal notes (where available) emit
  ``KnowledgeText`` for the platform's vector+BM25 ingestion.
- Pure-structured records (companies, contacts) emit empty list.

Reference: ``cip/integration_mesh/connectors/fixture/mapper.py``.
"""
from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Literal

from cip.integration_mesh.base import (
    CIPMapperBase,
    CIPRow,
    KnowledgeText,
    KnowledgeTextMetadata,
)
from cip.integration_mesh.exceptions import SchemaDriftError

# Record-side kind → cip_* table mapping.
_TARGET_TABLE_BY_TYPE: dict[str, str] = {
    "company": "cip_companies",
    "contact": "cip_contacts",
    "deal": "cip_deals",
    "ticket": "cip_tickets",
}

# Domain columns per object_type on the target cip_* table. HubSpot
# property keys that match column names go in CIPRow.fields; the rest
# go to CIPRow.overflow (JSONB ``properties`` column on each table).
#
# The deployed cip_* schemas (per cip_05/06/07/08 migrations) accept a
# specific column set; everything else routes to overflow. The list
# below mirrors HubSpot's default property names where the column name
# matches; explicit translation lives in _RECORD_TO_SQL_COLUMN.
# Per-record-type domain field sets. SQL column names ONLY (no HubSpot
# raw names) — translation happens via _RECORD_TO_SQL_COLUMN below.
# Schema-drift guard: tests/integration_mesh/test_mapper_schema_drift.py
# asserts every value here exists as a column on the corresponding cip_*
# table.
_DOMAIN_FIELDS_BY_TYPE: dict[str, set[str]] = {
    "company": {
        "name", "domain", "industry", "city", "country",
        "employee_count", "annual_revenue",
    },
    "contact": {
        "first_name", "last_name", "email", "phone",
        "title", "country", "city", "lifecycle_stage",
        "company_name",
    },
    "deal": {
        "name", "amount", "stage", "pipeline", "close_date",
        "currency", "probability",
    },
    "ticket": {
        "subject", "description", "priority", "status",
        "ticket_type",
    },
}

# HubSpot property name → cip_* column name. Identity where omitted.
# Every TARGET value here must appear in _DOMAIN_FIELDS_BY_TYPE for the
# same record type. Schema-drift test catches mismatches.
_RECORD_TO_SQL_COLUMN: dict[str, dict[str, str]] = {
    "company": {
        "numberofemployees": "employee_count",
        "annualrevenue": "annual_revenue",
    },
    "contact": {
        "firstname": "first_name",
        "lastname": "last_name",
        # cip_contacts.title (NOT job_title — column doesn't exist).
        # Surfaced 2026-05-13 during Wayward initial sync as a
        # NotNullViolation; locked here.
        "jobtitle": "title",
        # HubSpot writes "lifecyclestage" (no underscore); cip_contacts
        # has "lifecycle_stage". Translate so the column is populated
        # rather than dumped to overflow.
        "lifecyclestage": "lifecycle_stage",
        "company": "company_name",
    },
    "deal": {
        "dealname": "name",
        "dealstage": "stage",
        "closedate": "close_date",
    },
    "ticket": {
        "content": "description",
        "hs_ticket_priority": "priority",
        "hs_pipeline_stage": "status",
    },
}

# Numeric-coerced fields (HubSpot returns strings; cip_* columns are
# NUMERIC / INTEGER). Coerce via Decimal(str(v)) for SCD-differ stability.
_NUMERIC_FIELDS: set[str] = {
    "employee_count",
    "annual_revenue",
    "amount",
}

# Reserved record-side keys that don't go to fields OR overflow (used by
# connector/mapper internally for routing + backfill semantics).
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


class HubSpotMapper(CIPMapperBase):
    """HubSpot v3 record → CIPRow mapper.

    Dispatches per-record on ``__cip_kind__`` (company / contact / deal
    / ticket). Honors backfill markers for historical-row routing.
    """

    object_type: str = "hubspot"  # superseded per-call
    target_table: str = "cip_companies"  # default; per-call resolved

    def map(self, record: dict[str, object]) -> Iterable[CIPRow]:
        kind = record.get("__cip_kind__")
        if not isinstance(kind, str) or kind not in _TARGET_TABLE_BY_TYPE:
            raise SchemaDriftError(
                f"HubSpotMapper: unknown __cip_kind__={kind!r}; "
                f"known: {sorted(_TARGET_TABLE_BY_TYPE)}"
            )
        target = _TARGET_TABLE_BY_TYPE[kind]
        domain_keys = _DOMAIN_FIELDS_BY_TYPE[kind]
        translation = _RECORD_TO_SQL_COLUMN.get(kind, {})

        # Build fields (translated record-side keys → SQL column names)
        fields: dict[str, object] = {}
        overflow: dict[str, object] = {}

        for k, v in record.items():
            if k in _RESERVED:
                continue
            sql_col = translation.get(k, k)
            if sql_col in domain_keys or k in domain_keys:
                # Numeric coercion for cip-side NUMERIC columns
                if sql_col in _NUMERIC_FIELDS and v is not None:
                    try:
                        fields[sql_col] = Decimal(str(v))
                    except (ValueError, ArithmeticError):
                        # Source returned non-numeric; treat as overflow
                        overflow[k] = v
                else:
                    fields[sql_col] = v
            else:
                overflow[k] = v

        # Tickets need a non-null subject; HubSpot returns the field as
        # "subject" already. If absent, fall back to a derived placeholder
        # so SCD-2 inserts succeed.
        if kind == "ticket" and "subject" not in fields:
            fields["subject"] = "(no subject)"

        # cip_companies requires non-null name — surfaced 2026-05-13 during
        # Wayward initial sync, HubSpot had a company record without a name
        # property set (HubSpot allows this; CIP doesn't). Apply same
        # fallback pattern as ticket subject + Zendesk org name.
        if kind == "company" and "name" not in fields:
            fields["name"] = (
                f"(unnamed hubspot company #{record.get('source_id', '?')})"
            )

        # cip_contacts has FK / unique constraints that allow null names
        # but downstream BI consumers want consistent fields; leave as-is.

        yield CIPRow(
            target_table=target,
            source_id=str(record.get("source_id", "")),
            fields=fields,
            overflow=overflow,
            authority="ingested",
        )

    def overflow_fields(self) -> list[str]:
        """HubSpot's custom properties are tenant-portal-specific —
        discovered at runtime via describe_schema. The static overflow
        list returned here is the aggregate of well-known HubSpot
        property names we route to overflow by default.
        """
        return sorted({
            # Companies — non-domain HubSpot properties commonly seen
            "lifecyclestage",
            # Contacts
            # phone routes to overflow; cip_contacts.phone is nullable per cip_05
            "phone", "company",
            # Deals
            "hubspot_owner_id", "pipeline",
            # Tickets
            "hs_pipeline",
        })

    def authority(self) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        """Emit KnowledgeText for ticket bodies; empty for other kinds.

        Per CONNECTOR-AUTHORING-GUIDE.md §9 "honest mock" pattern: the
        mapper emits ONLY ``source_id`` in metadata; orchestrator fills
        the rest at the boundary.
        """
        if record.get("__cip_kind__") != "ticket":
            return []
        if record.get("__cip_backfill__"):
            # Historical ticket revisions don't re-emit knowledge text
            # (orchestrator de-dupes by source_id + content hash later).
            return []
        body = record.get("content") or record.get("description") or ""
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
