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
    # PM scope 9952dd26 — engagements unified table with discriminator
    "engagement_note": "cip_engagements",
    "engagement_meeting": "cip_engagements",
    "engagement_task": "cip_engagements",
    "engagement_call": "cip_engagements",
    "engagement_email": "cip_engagements",
}

# Engagement kinds → cip_engagements.engagement_type discriminator value
_ENGAGEMENT_TYPE_BY_KIND: dict[str, str] = {
    "engagement_note": "note",
    "engagement_meeting": "meeting",
    "engagement_task": "task",
    "engagement_call": "call",
    "engagement_email": "email",
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
    # Engagements: all five engagement kinds route to cip_engagements.
    # Common columns plus per-type optional columns. The mapper sets
    # engagement_type discriminator from the kind.
    "engagement_note": {
        "engagement_type", "title", "body", "owner_source_id",
        "engagement_at", "source_created_at", "source_updated_at",
        "contact_source_ids", "deal_source_ids", "company_source_ids",
        "ticket_source_ids",
    },
    "engagement_meeting": {
        "engagement_type", "title", "body", "owner_source_id",
        "engagement_at", "source_created_at", "source_updated_at",
        "start_time", "end_time", "location", "outcome", "external_url",
        "duration_seconds",
        "contact_source_ids", "deal_source_ids", "company_source_ids",
        "ticket_source_ids",
    },
    "engagement_task": {
        "engagement_type", "title", "body", "owner_source_id",
        "engagement_at", "source_created_at", "source_updated_at",
        "status", "priority", "task_type", "completion_date",
        "contact_source_ids", "deal_source_ids", "company_source_ids",
        "ticket_source_ids",
    },
    "engagement_call": {
        "engagement_type", "title", "body", "owner_source_id",
        "engagement_at", "source_created_at", "source_updated_at",
        "duration_seconds", "outcome", "recording_url",
        "has_transcript", "transcript",
        "contact_source_ids", "deal_source_ids", "company_source_ids",
        "ticket_source_ids",
    },
    "engagement_email": {
        "engagement_type", "title", "body", "owner_source_id",
        "engagement_at", "source_created_at", "source_updated_at",
        "contact_source_ids", "deal_source_ids", "company_source_ids",
        "ticket_source_ids",
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
    # Engagement property → cip_engagements column translations.
    # See cip_16_engagements migration for the target schema.
    "engagement_note": {
        "hs_note_body": "body",
        "hs_timestamp": "engagement_at",
        "hs_createdate": "source_created_at",
        "hs_lastmodifieddate": "source_updated_at",
        "hubspot_owner_id": "owner_source_id",
    },
    "engagement_meeting": {
        "hs_meeting_title": "title",
        "hs_meeting_body": "body",
        "hs_meeting_start_time": "start_time",
        "hs_meeting_end_time": "end_time",
        "hs_meeting_location": "location",
        "hs_meeting_outcome": "outcome",
        "hs_meeting_external_url": "external_url",
        "hs_timestamp": "engagement_at",
        "hs_createdate": "source_created_at",
        "hs_lastmodifieddate": "source_updated_at",
        "hubspot_owner_id": "owner_source_id",
    },
    "engagement_task": {
        "hs_task_subject": "title",
        "hs_task_body": "body",
        "hs_task_status": "status",
        "hs_task_priority": "priority",
        "hs_task_type": "task_type",
        "hs_task_completion_date": "completion_date",
        "hs_timestamp": "engagement_at",
        "hs_createdate": "source_created_at",
        "hs_lastmodifieddate": "source_updated_at",
        "hubspot_owner_id": "owner_source_id",
    },
    "engagement_call": {
        "hs_call_title": "title",
        "hs_call_body": "body",
        "hs_call_duration": "duration_seconds",
        "hs_call_disposition": "outcome",
        "hs_call_recording_url": "recording_url",
        "hs_call_has_transcript": "has_transcript",
        "hs_timestamp": "engagement_at",
        "hs_createdate": "source_created_at",
        "hs_lastmodifieddate": "source_updated_at",
        "hubspot_owner_id": "owner_source_id",
    },
    "engagement_email": {
        "hs_email_subject": "title",
        "hs_email_text": "body",
        "hs_timestamp": "engagement_at",
        "hs_createdate": "source_created_at",
        "hs_lastmodifieddate": "source_updated_at",
        "hubspot_owner_id": "owner_source_id",
    },
}

# Numeric-coerced fields (HubSpot returns strings; cip_* columns are
# NUMERIC / INTEGER). Coerce via Decimal(str(v)) for SCD-differ stability.
_NUMERIC_FIELDS: set[str] = {
    "employee_count",
    "annual_revenue",
    "amount",
    "duration_seconds",
}

# HubSpot datetime properties that need ISO-string → tz-aware datetime
# conversion before the persister sees them. The persister asserts every
# datetime field is tz-aware.
_DATETIME_COLUMNS: set[str] = {
    "engagement_at", "source_created_at", "source_updated_at",
    "start_time", "end_time", "completion_date",
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


def _parse_hubspot_datetime(value: object) -> object:
    """Convert HubSpot ISO-8601 string to tz-aware datetime.

    HubSpot timestamps come in two flavors:
      - ISO-8601 string with Z suffix: "2025-03-11T17:04:09.035Z"
      - Unix milliseconds (older properties): integer or string of digits

    Returns the original value unchanged if conversion fails.
    """
    if value is None:
        return value
    from datetime import datetime as _dt, timezone as _tz
    if isinstance(value, _dt):
        return value
    if isinstance(value, (int, float)):
        # Unix millis
        try:
            return _dt.fromtimestamp(int(value) / 1000.0, tz=_tz.utc)
        except (ValueError, OSError, OverflowError):
            return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.isdigit():
            try:
                return _dt.fromtimestamp(int(s) / 1000.0, tz=_tz.utc)
            except (ValueError, OSError, OverflowError):
                return value
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        try:
            return _dt.fromisoformat(s)
        except ValueError:
            return value
    return value


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
        is_engagement = kind in _ENGAGEMENT_TYPE_BY_KIND

        # Build fields (translated record-side keys → SQL column names)
        fields: dict[str, object] = {}
        overflow: dict[str, object] = {}

        for k, v in record.items():
            if k in _RESERVED:
                continue
            # Engagement association markers (__cip_assoc_<singular>__)
            # → cip_engagements.<singular>_source_ids array columns.
            if is_engagement and isinstance(k, str) and k.startswith("__cip_assoc_") and k.endswith("__"):
                singular = k[len("__cip_assoc_"):-2]
                col = f"{singular}_source_ids"
                if col in domain_keys and isinstance(v, list):
                    fields[col] = list(v)
                continue
            sql_col = translation.get(k, k)
            if sql_col in domain_keys or k in domain_keys:
                # Numeric coercion for cip-side NUMERIC columns
                if sql_col in _NUMERIC_FIELDS and v is not None:
                    try:
                        # Engagement duration_seconds is INTEGER not NUMERIC;
                        # round to int
                        if sql_col == "duration_seconds":
                            fields[sql_col] = int(Decimal(str(v)))
                        else:
                            fields[sql_col] = Decimal(str(v))
                    except (ValueError, ArithmeticError):
                        # Source returned non-numeric; treat as overflow
                        overflow[k] = v
                elif sql_col in _DATETIME_COLUMNS and v is not None:
                    parsed = _parse_hubspot_datetime(v)
                    fields[sql_col] = parsed
                elif sql_col == "has_transcript":
                    # HubSpot booleans return as strings "true"/"false"
                    if isinstance(v, str):
                        fields[sql_col] = v.lower() == "true"
                    else:
                        fields[sql_col] = bool(v)
                else:
                    fields[sql_col] = v
            else:
                overflow[k] = v

        # Engagements: set the discriminator + ensure default assoc arrays.
        if is_engagement:
            fields["engagement_type"] = _ENGAGEMENT_TYPE_BY_KIND[kind]
            for assoc_col in (
                "contact_source_ids", "deal_source_ids",
                "company_source_ids", "ticket_source_ids",
            ):
                fields.setdefault(assoc_col, [])

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
        kind = record.get("__cip_kind__")
        if record.get("__cip_backfill__"):
            # Historical ticket revisions don't re-emit knowledge text
            # (orchestrator de-dupes by source_id + content hash later).
            return []
        # Engagements: emit body text (HTML body acceptable — orchestrator
        # can strip tags downstream if needed).
        if isinstance(kind, str) and kind in _ENGAGEMENT_TYPE_BY_KIND:
            engagement_body_keys = (
                "hs_note_body", "hs_meeting_body", "hs_task_body",
                "hs_call_body", "hs_email_text",
            )
            for k in engagement_body_keys:
                body = record.get(k)
                if isinstance(body, str) and body.strip():
                    return [
                        KnowledgeText(
                            text=body,
                            metadata=KnowledgeTextMetadata(
                                source_id=str(record.get("source_id", "")),
                            ),
                        )
                    ]
            return []
        if kind != "ticket":
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
