# foundry: kind=service domain=client-intelligence-platform touches=integration
"""HubSpot v3 CRM connector for CIP.

Per D-159: historical backfill is mandatory. On first sync for a new
tenant, ``HubSpotConnector`` pulls each record's full property-history
(up to HubSpot's 20-revision-per-property retention window) and emits
synthesized backfill records to the orchestrator. The SCD-2 differ
writes ``cip_*_history`` rows for every pre-CIP revision.

Auth: HubSpot Private App Token (PAT, ``pat-*`` prefix). Read from
``WAYWARD_HUBSPOT_TOKEN`` env var by default; pass ``token=...`` to
override.

Usage::

    from cip.integration_mesh.connectors.hubspot import (
        HubSpotConnector, HubSpotMapper,
    )
    connector = HubSpotConnector(tenant_id=tid)  # reads env tokens
    mapper = HubSpotMapper()
    run_sync(connector, mapper, engine, tenant_id=tid, database_url=url)

See ``WORKBENCH/tim/wayward-tenant-coordinates.md`` for the Wayward
deployment coordinates + ``docs/CONNECTOR-AUTHORING-GUIDE.md`` for the
authoring pattern.
"""
from __future__ import annotations

from .connector import HubSpotConnector
from .mapper import HubSpotMapper

__all__ = ["HubSpotConnector", "HubSpotMapper"]
