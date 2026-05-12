# foundry: kind=service domain=client-intelligence-platform touches=integration
"""HubSpotConnector — SCAFFOLD ONLY.

Stub class extending ``CIPConnectorBase``. Every Protocol method raises
``NotImplementedError`` until the Phase 2 Wayward deep plan locks the
real implementation strategy.

Phase 2 implementation will need:

- ``authenticate()`` — read ``WAYWARD_HUBSPOT_TOKEN`` from env; validate
  against HubSpot's ``/oauth/v1/access-tokens/<token>`` endpoint; raise
  ``AuthenticationError`` on 401.
- ``stream_records(cursor, batch_size)`` — paginate the Companies / Contacts
  / Deals / Tickets v3 endpoints using HubSpot's ``after`` cursor token;
  cap per-page at HubSpot's 100/page maximum; yield records one at a time.
- ``describe_schema()`` — return ``PropertyDescriptor`` list for the
  HubSpot company / contact / deal / ticket fields the mapper consumes,
  including any tenant-defined custom fields discovered at runtime via
  the Properties API (``is_custom=True``).
- ``incremental_key(record)`` — return
  ``datetime.fromtimestamp(int(record['updatedAt']) / 1000, UTC)``;
  HubSpot timestamps are epoch-millis, tz-naive in JSON.
- ``rate_limit_policy`` — HubSpot allows 100 requests / 10 seconds
  burst on standard plans; recommended
  ``RateLimitPolicy(requests_per_second=10.0, burst=10)`` per
  CONNECTOR-AUTHORING-GUIDE.md §10.

**Historical-data note (Tim's question 2026-05-12):** HubSpot retains
up to 20 revisions per property via the Property History API. The
default ``stream_records`` returns only current state. To preserve
HubSpot's pre-CIP history during initial sync (the "backup tape"
question — PHASE-1-PLAN.md R5), the connector needs an additional
path that calls ``/crm/v3/objects/<type>/<id>?propertiesWithHistory=...``
for each record and synthesizes ``cip_*_history`` rows for each
revision. That's a Phase 2 deep-plan decision; the scaffold leaves
the hook open but doesn't commit to either choice.

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


class HubSpotConnector(CIPConnectorBase):
    """HubSpot CRM connector. SCAFFOLD — Phase 2 implementation."""

    connector_id: str = "hubspot-v1"
    cursor_safety_window_seconds: int = 300  # absorb up to 5 min of replica lag
    version: str = "0.0.0"  # bump when first real implementation lands

    def __init__(
        self,
        tenant_id: UUID,
        *,
        portal_id: int | None = None,
        backfill_property_history: bool = False,
    ) -> None:
        """
        Args:
            tenant_id: CIP tenant UUID (Wayward = b0000000-...0001).
            portal_id: HubSpot portal/hub identifier. Optional in token-auth
                mode; required if cross-portal disambiguation is needed.
            backfill_property_history: when True, the initial sync also
                pulls each record's property-history (up to 20 revisions
                per property) and writes synthetic ``cip_*_history`` rows
                so reports can span pre-CIP time windows. Phase 2 deep
                plan decision — see module docstring "backup tape" note.
        """
        self.tenant_id = tenant_id
        self.portal_id = portal_id
        self.backfill_property_history = backfill_property_history
        raise NotImplementedError(
            "HubSpotConnector scaffold — Phase 2 implementation pending. "
            "See WORKBENCH/tim/wayward-tenant-coordinates.md + "
            "docs/CONNECTOR-AUTHORING-GUIDE.md."
        )

    def authenticate(self) -> None:
        raise NotImplementedError(
            "HubSpotConnector.authenticate — Phase 2. Reads WAYWARD_HUBSPOT_TOKEN "
            "env var; validates against /oauth/v1/access-tokens/<token>."
        )

    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        raise NotImplementedError(
            "HubSpotConnector.stream_records — Phase 2. Paginates Companies / "
            "Contacts / Deals / Tickets v3 endpoints with the 'after' cursor; "
            "when backfill_property_history=True, also yields synthesized "
            "history records constructed from /crm/v3/objects/<type>/<id>"
            "?propertiesWithHistory=<all> calls."
        )

    def describe_schema(self) -> list[PropertyDescriptor]:
        raise NotImplementedError(
            "HubSpotConnector.describe_schema — Phase 2. Returns "
            "PropertyDescriptor list for HubSpot company/contact/deal/ticket "
            "fields, including tenant-defined custom fields (is_custom=True)."
        )

    def incremental_key(self, record: dict[str, object]) -> datetime:
        raise NotImplementedError(
            "HubSpotConnector.incremental_key — Phase 2. HubSpot returns "
            "updatedAt as epoch-millis; convert to UTC-aware datetime."
        )

    @property
    def rate_limit_policy(self) -> RateLimitPolicy:
        # Phase 2 will tune; default for now.
        return DEFAULT_RATE_LIMIT
