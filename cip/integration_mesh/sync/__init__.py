# foundry: kind=package domain=client-intelligence-platform
"""Reconciliation / sync jobs that don't fit the CIPConnector contract.

Members:

- ``crm_companion_writeback`` — Phase 2.8 Leg B: read PS-team enrichments
  out of the Foundry-CRM Postgres and write them into the corresponding
  ``cip_clients.companion_data`` JSONB via the restricted
  ``cip_twenty_project_silk`` role.

These jobs do NOT go through ``run_sync`` / ``CIPRowPersister`` — those
write source fields with the app role. Sync jobs here write companion
columns with the twenty role. Different role, different column.
"""
from cip.integration_mesh.sync.crm_companion_writeback import (
    PS_TENANT_ID,
    RunSummary,
    build_managed_companion,
    run_writeback,
)

__all__ = [
    "PS_TENANT_ID",
    "RunSummary",
    "build_managed_companion",
    "run_writeback",
]
