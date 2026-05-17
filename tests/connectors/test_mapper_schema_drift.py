# foundry: kind=test domain=client-intelligence-platform
"""Mapper schema-drift guard tests.

Bug history (2026-05-13/14): HubSpotMapper had ``jobtitle -> job_title``
in its translation table, but ``cip_contacts.job_title`` does not exist
(the column is named ``title``). The mapper's ``_DOMAIN_FIELDS_BY_TYPE``
referenced the non-existent column too. Result: real Wayward sync hit
``NotNullViolation: column "job_title" of relation "cip_contacts" does
not exist`` mid-batch, 3 consecutive failures killed the run after only
66,500 of the entity types persisted.

These tests assert every column referenced in a connector's
``_DOMAIN_FIELDS_BY_TYPE`` AND every TARGET in ``_RECORD_TO_SQL_COLUMN``
exists as an actual column on the target ``cip_*`` table. Catches drift
without needing a real DB — uses a small inlined source-of-truth dict
of deployed columns (sync'd from ``information_schema.columns`` against
Railway prod 2026-05-14; alembic migrations are the canonical truth).
"""
from __future__ import annotations

from cip.integration_mesh.connectors.hubspot.mapper import (
    _DOMAIN_FIELDS_BY_TYPE as HUBSPOT_DOMAIN,
)
from cip.integration_mesh.connectors.hubspot.mapper import (
    _RECORD_TO_SQL_COLUMN as HUBSPOT_TRANSLATION,
)
from cip.integration_mesh.connectors.zendesk.mapper import (
    _DOMAIN_FIELDS_BY_TYPE as ZENDESK_DOMAIN,
)
from cip.integration_mesh.connectors.zendesk.mapper import (
    _RECORD_TO_SQL_COLUMN as ZENDESK_TRANSLATION,
)

# Source of truth: column lists as deployed on Railway prod 2026-05-14
# (queried via information_schema.columns; alembic migrations cip_01-cip_10
# are authoritative). Provenance/SCD/extras columns excluded from the
# mapper-domain check because mappers shouldn't reference them.
_DEPLOYED_DOMAIN_COLUMNS: dict[str, set[str]] = {
    "cip_companies": {
        "name", "domain", "industry", "region", "language",
        "country", "city", "employee_count", "annual_revenue",
    },
    "cip_contacts": {
        "email", "phone", "first_name", "last_name", "company_name",
        "company_id", "title", "country", "city", "lifecycle_stage",
    },
    "cip_deals": {
        "name", "stage", "amount", "currency", "close_date",
        "company_id", "contact_id", "pipeline", "probability",
    },
    "cip_tickets": {
        "subject", "description", "status", "priority", "ticket_type",
        "requester_id", "requester_email", "assignee_name",
        "group_name", "channel", "satisfaction_rating",
        "first_response_at", "resolved_at",
        "source_created_at", "source_updated_at",
    },
    # cip_15 (PM scope 28739b6e) — Zendesk ticket comments.
    "cip_ticket_comments": {
        "ticket_source_id", "author_id", "author_email", "body",
        "html_body", "is_public", "via_channel", "attachments_count",
        "attachment_urls", "source_created_at",
    },
    # cip_16 (PM scope 9952dd26) — HubSpot engagements (unified table).
    "cip_engagements": {
        "engagement_type", "title", "body", "owner_source_id",
        "engagement_at", "source_created_at", "source_updated_at",
        "status", "priority", "task_type", "completion_date",
        "start_time", "end_time", "location", "outcome", "external_url",
        "duration_seconds", "recording_url", "has_transcript", "transcript",
        "contact_source_ids", "deal_source_ids", "company_source_ids",
        "ticket_source_ids",
    },
}

# kind name -> target cip_* table (per connector mapping).
_HUBSPOT_KIND_TO_TABLE: dict[str, str] = {
    "company": "cip_companies",
    "contact": "cip_contacts",
    "deal": "cip_deals",
    "ticket": "cip_tickets",
    # cip_16 / PM scope 9952dd26 — all engagement kinds route to cip_engagements
    "engagement_note": "cip_engagements",
    "engagement_meeting": "cip_engagements",
    "engagement_task": "cip_engagements",
    "engagement_call": "cip_engagements",
    "engagement_email": "cip_engagements",
}

_ZENDESK_KIND_TO_TABLE: dict[str, str] = {
    "company": "cip_companies",
    "contact": "cip_contacts",
    "ticket": "cip_tickets",
    # cip_15 / PM scope 28739b6e
    "ticket_comment": "cip_ticket_comments",
}


def test_hubspot_domain_fields_exist_in_deployed_schema() -> None:
    """Every column in HubSpotMapper's _DOMAIN_FIELDS_BY_TYPE must exist
    on the target cip_* table per the deployed schema."""
    errors: list[str] = []
    for kind, fields in HUBSPOT_DOMAIN.items():
        target = _HUBSPOT_KIND_TO_TABLE[kind]
        deployed = _DEPLOYED_DOMAIN_COLUMNS[target]
        for f in fields:
            if f not in deployed:
                errors.append(
                    f"HubSpotMapper._DOMAIN_FIELDS_BY_TYPE[{kind!r}] references "
                    f"{f!r} but {target} has no such column"
                )
    assert not errors, "Schema drift found:\n  " + "\n  ".join(errors)


def test_hubspot_translation_targets_exist_in_deployed_schema() -> None:
    """Every TARGET in HubSpotMapper._RECORD_TO_SQL_COLUMN must exist on
    the target cip_* table — this is the exact class of bug that killed
    Wayward sync on 2026-05-13 (``jobtitle -> job_title`` where actual
    column is ``title``)."""
    errors: list[str] = []
    for kind, translation in HUBSPOT_TRANSLATION.items():
        target = _HUBSPOT_KIND_TO_TABLE[kind]
        deployed = _DEPLOYED_DOMAIN_COLUMNS[target]
        for source, sql_col in translation.items():
            if sql_col not in deployed:
                errors.append(
                    f"HubSpotMapper._RECORD_TO_SQL_COLUMN[{kind!r}][{source!r}] "
                    f"-> {sql_col!r}, but {target} has no such column"
                )
    assert not errors, "Schema drift found:\n  " + "\n  ".join(errors)


def test_zendesk_domain_fields_exist_in_deployed_schema() -> None:
    errors: list[str] = []
    for kind, fields in ZENDESK_DOMAIN.items():
        target = _ZENDESK_KIND_TO_TABLE[kind]
        deployed = _DEPLOYED_DOMAIN_COLUMNS[target]
        for f in fields:
            if f not in deployed:
                errors.append(
                    f"ZendeskMapper._DOMAIN_FIELDS_BY_TYPE[{kind!r}] references "
                    f"{f!r} but {target} has no such column"
                )
    assert not errors, "Schema drift found:\n  " + "\n  ".join(errors)


def test_zendesk_translation_targets_exist_in_deployed_schema() -> None:
    errors: list[str] = []
    for kind, translation in ZENDESK_TRANSLATION.items():
        target = _ZENDESK_KIND_TO_TABLE[kind]
        deployed = _DEPLOYED_DOMAIN_COLUMNS[target]
        for source, sql_col in translation.items():
            if sql_col not in deployed:
                errors.append(
                    f"ZendeskMapper._RECORD_TO_SQL_COLUMN[{kind!r}][{source!r}] "
                    f"-> {sql_col!r}, but {target} has no such column"
                )
    assert not errors, "Schema drift found:\n  " + "\n  ".join(errors)


def test_hubspot_translation_targets_in_domain_set() -> None:
    """Belt-and-suspenders: every TARGET in _RECORD_TO_SQL_COLUMN must
    also appear in _DOMAIN_FIELDS_BY_TYPE for the same kind, otherwise
    the translated column would silently route to overflow."""
    errors: list[str] = []
    for kind, translation in HUBSPOT_TRANSLATION.items():
        domain_keys = HUBSPOT_DOMAIN[kind]
        for source, sql_col in translation.items():
            if sql_col not in domain_keys:
                errors.append(
                    f"HubSpotMapper translation[{kind!r}][{source!r}] -> "
                    f"{sql_col!r} not in domain_keys (would route to overflow)"
                )
    assert not errors, "Translation-target / domain-keys mismatch:\n  " + "\n  ".join(errors)


def test_zendesk_translation_targets_in_domain_set() -> None:
    errors: list[str] = []
    for kind, translation in ZENDESK_TRANSLATION.items():
        domain_keys = ZENDESK_DOMAIN[kind]
        for source, sql_col in translation.items():
            if sql_col not in domain_keys:
                errors.append(
                    f"ZendeskMapper translation[{kind!r}][{source!r}] -> "
                    f"{sql_col!r} not in domain_keys (would route to overflow)"
                )
    assert not errors, "Translation-target / domain-keys mismatch:\n  " + "\n  ".join(errors)
