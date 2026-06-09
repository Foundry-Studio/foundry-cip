# foundry: kind=package domain=client-intelligence-platform
"""Reconciliation / sync jobs that don't fit the CIPConnector contract.

Members:

- ``crm_companion_writeback`` — Phase 2.8 Leg B: read PS-team enrichments
  out of the Foundry-CRM Postgres and write them into the corresponding
  ``cip_clients.companion_data`` JSONB via the restricted
  ``cip_twenty_project_silk`` role.

- ``ps_lens_mirror`` — PM scope 8d47e809: EcomLever → Project Silk
  china-subset mirror. Pass-1 derives PS cip_clients deterministically;
  Pass-2 drives ``run_sync(..., sync_mode='lens-mirror')`` per entity.
  Lifted from ``scripts/orchestrate_ps_lens_mirror.py`` so it's callable
  from the FAS subsystem_scheduler (see
  ``Foundry-Agent-System/src/work_execution/producers/scheduled_tasks/cip_sync.py``).

These jobs do NOT go through ``run_sync`` / ``CIPRowPersister`` for the
companion-writeback case — that writes companion columns with a different
role. ``ps_lens_mirror`` DOES go through ``run_sync`` (it's a tenant-to-
tenant mirror of source fields, not a companion writeback).
"""
from cip.integration_mesh.sync.crm_companion_writeback import (
    PS_TENANT_ID,
    RunSummary,
    build_managed_companion,
    run_writeback,
)
from cip.integration_mesh.sync.ps_lens_mirror import run_ps_china_mirror

__all__ = [
    "PS_TENANT_ID",
    "RunSummary",
    "build_managed_companion",
    "run_ps_china_mirror",
    "run_writeback",
]
