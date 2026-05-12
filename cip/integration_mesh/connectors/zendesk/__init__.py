# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Zendesk connector — SCAFFOLD ONLY.

Phase 2 Wayward Onboarding deliverable. Folder structure + class
skeletons in place to give the Phase 2 M1 build a deliberate starting
point. None of the methods are implemented yet; each raises
``NotImplementedError`` with a pointer to the spec.

Real implementation requires:
- Wayward HubSpot/Zendesk Phase 2 deep plan (Atlas / Tim joint decision
  on OAuth refresh strategy, pagination quirks, history-clock semantics)
- ``WAYWARD_ZENDESK_TOKEN`` + ``WAYWARD_ZENDESK_USER`` (default
  ``jake@wayward.com``) env vars provisioned per
  ``WORKBENCH/tim/wayward-tenant-coordinates.md``
- An existing pull-zendesk.py reference at
  ``WORKBENCH/tim/ventures/ecomlever/clients/wayward/pull-zendesk.py``
  in the monorepo — useful but pre-CIP-framework; the connector here is
  a clean rewrite against ``CIPConnectorBase``.

Use the FixtureConnector at ``cip/integration_mesh/connectors/fixture/``
as the canonical reference implementation; mirror its layout
(connector.py, mapper.py, optional records.py for fixtures).
"""
from __future__ import annotations

from .connector import ZendeskConnector
from .mapper import ZendeskMapper

__all__ = ["ZendeskConnector", "ZendeskMapper"]
