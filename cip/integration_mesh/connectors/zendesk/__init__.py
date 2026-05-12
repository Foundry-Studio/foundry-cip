# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Zendesk Support v2 connector for CIP.

Per D-159: historical backfill is mandatory. On first sync, the
connector walks ``/api/v2/tickets/{id}/audits.json`` for every ticket
and emits one synthesized record per audit event. The SCD-2 differ
writes ``cip_tickets_history`` rows for each pre-CIP state change
Zendesk's audit log still retains.

Auth: Basic with ``{email}/token:{token}`` format. Reads
``WAYWARD_ZENDESK_TOKEN`` + ``WAYWARD_ZENDESK_USER`` +
``WAYWARD_ZENDESK_SUBDOMAIN`` env vars by default.

Entity mapping (Zendesk → CIP):
  - organizations → cip_companies
  - users → cip_contacts
  - tickets → cip_tickets (with audit-log backfill)

Usage::

    from cip.integration_mesh.connectors.zendesk import (
        ZendeskConnector, ZendeskMapper,
    )
    connector = ZendeskConnector(tenant_id=tid)  # reads env tokens
    mapper = ZendeskMapper()
    run_sync(connector, mapper, engine, tenant_id=tid, database_url=url)

See ``WORKBENCH/tim/wayward-tenant-coordinates.md`` for Wayward
deployment coordinates + ``docs/CONNECTOR-AUTHORING-GUIDE.md`` for the
authoring pattern.
"""
from __future__ import annotations

from .connector import ZendeskConnector
from .mapper import ZendeskMapper

__all__ = ["ZendeskConnector", "ZendeskMapper"]
