# foundry: kind=service domain=client-intelligence-platform touches=integration
"""HubSpot connector — SCAFFOLD ONLY.

Phase 2 Wayward Onboarding deliverable. Folder structure + class
skeletons in place to give the Phase 2 M1 build a deliberate starting
point. None of the methods are implemented yet; each raises
``NotImplementedError`` with a pointer to the spec.

Real implementation requires:
- Wayward HubSpot/Zendesk Phase 2 deep plan (Atlas / Tim joint decision
  on OAuth refresh strategy, pagination quirks, history-clock semantics)
- ``WAYWARD_HUBSPOT_TOKEN`` env var provisioned per
  ``WORKBENCH/tim/wayward-tenant-coordinates.md``
- Decision on the **HubSpot "backup tape"** question: HubSpot retains
  up to 20 revisions per property; the connector either backfills that
  pre-CIP history into cip_*_history (preserves history before first
  sync) or accepts from-sync-onward history (loses pre-CIP changes).
  See PHASE-1-PLAN.md R5 + the historical-data answer in the
  Wayward Phase 2 deep plan.
- An existing pull-hubspot.py reference at
  ``WORKBENCH/tim/ventures/ecomlever/clients/wayward/pull-hubspot.py``
  in the monorepo — useful but pre-CIP-framework; the connector here is
  a clean rewrite against ``CIPConnectorBase``.

Use the FixtureConnector at ``cip/integration_mesh/connectors/fixture/``
as the canonical reference implementation; mirror its layout
(connector.py, mapper.py).
"""
from __future__ import annotations

from .connector import HubSpotConnector
from .mapper import HubSpotMapper

__all__ = ["HubSpotConnector", "HubSpotMapper"]
