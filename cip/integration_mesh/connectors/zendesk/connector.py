# foundry: kind=service domain=client-intelligence-platform touches=integration
"""ZendeskConnector — SCAFFOLD ONLY.

Stub class extending ``CIPConnectorBase``. Every Protocol method raises
``NotImplementedError`` until the Phase 2 Wayward deep plan locks the
real implementation strategy.

Phase 2 implementation will need:

- ``authenticate()`` — read ``WAYWARD_ZENDESK_TOKEN`` + ``WAYWARD_ZENDESK_USER``
  from env; validate against Zendesk's ``/api/v2/users/me.json`` endpoint;
  raise ``AuthenticationError`` on 401.
- ``stream_records(cursor, batch_size)`` — paginate the Tickets API +
  Users API + Organizations API; yield records one at a time; respect
  ``batch_size`` as page-target; cap each Zendesk page at the source-system
  100/page maximum per CONNECTOR-AUTHORING-GUIDE.md §4.
- ``describe_schema()`` — return ``PropertyDescriptor`` list for the
  Zendesk ticket / user / org fields the mapper consumes. Map to
  ``cip_tickets`` / ``cip_contacts`` / ``cip_companies`` per the deployed
  CHECK constraint enum on ``cip_connector_property_registry.property_type``.
- ``incremental_key(record)`` — return ``datetime.fromisoformat(record['updated_at'])``;
  ensure tz-aware (Zendesk returns UTC; safe).
- ``rate_limit_policy`` — Zendesk allows 700 req/min on standard plans;
  recommended ``RateLimitPolicy(requests_per_second=11.0, burst=20)`` per
  CONNECTOR-AUTHORING-GUIDE.md §10.

Reference: ``cip/integration_mesh/connectors/fixture/connector.py``.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

from cip.integration_mesh.base import (
    DEFAULT_RATE_LIMIT,
    CIPConnectorBase,
    PropertyDescriptor,
    RateLimitPolicy,
)


class ZendeskConnector(CIPConnectorBase):
    """Zendesk CRM/support connector. SCAFFOLD — Phase 2 implementation."""

    connector_id: str = "zendesk-v1"
    cursor_safety_window_seconds: int = 300  # absorb up to 5 min of replica lag
    version: str = "0.0.0"  # bump when first real implementation lands

    def __init__(self, tenant_id: UUID, *, subdomain: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.subdomain = subdomain
        # Auth state, rate-limit bucket, page-token cursor live here in Phase 2.
        raise NotImplementedError(
            "ZendeskConnector scaffold — Phase 2 implementation pending. "
            "See WORKBENCH/tim/wayward-tenant-coordinates.md + "
            "docs/CONNECTOR-AUTHORING-GUIDE.md."
        )

    def authenticate(self) -> None:
        raise NotImplementedError(
            "ZendeskConnector.authenticate — Phase 2. Reads WAYWARD_ZENDESK_TOKEN "
            "+ WAYWARD_ZENDESK_USER env vars; validates against /users/me.json."
        )

    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        raise NotImplementedError(
            "ZendeskConnector.stream_records — Phase 2. Paginates Tickets + "
            "Users + Organizations; yields records one at a time."
        )

    def describe_schema(self) -> list[PropertyDescriptor]:
        raise NotImplementedError(
            "ZendeskConnector.describe_schema — Phase 2. Returns "
            "PropertyDescriptor list for Zendesk ticket/user/org fields."
        )

    def incremental_key(self, record: dict[str, object]) -> datetime:
        raise NotImplementedError(
            "ZendeskConnector.incremental_key — Phase 2. Returns "
            "datetime.fromisoformat(record['updated_at']) (tz-aware UTC)."
        )

    @property
    def rate_limit_policy(self) -> RateLimitPolicy:
        # Phase 2 will tune; default for now.
        return DEFAULT_RATE_LIMIT
