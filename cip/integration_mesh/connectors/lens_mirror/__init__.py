# foundry: kind=service domain=client-intelligence-platform touches=integration
"""LensMirrorConnector + per-entity mappers (Phase 2.6, PM scope 280a2f20).

Per Atlas-locked design (docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md):
the lens-mirror connector reads from a SOURCE tenant's lens_* view + writes
to a DESTINATION tenant's `cip_*` table — the cross-tenant pattern Project
Silk uses to own + enrich a subset of EcomLever's Wayward data.

Wired into the existing orchestrator (`run_sync`) without modifications to
persister.py or orchestrator.py beyond a one-token Literal extension to
accept the new `'lens-mirror'` sync_mode value (cip_23 CHECK).

The two-pass orchestration (Pass 1 cip_clients dedup-and-upsert; Pass 2
entity mirror with resolved client_id FKs) lives in
`scripts/orchestrate_ps_lens_mirror.py`, not the connector itself.
"""
from cip.integration_mesh.connectors.lens_mirror.connector import (
    LensMirrorConnector,
)
from cip.integration_mesh.connectors.lens_mirror.mapper import (
    LensMirrorCompanyMapper,
    LensMirrorContactMapper,
    LensMirrorDealMapper,
)

__all__ = [
    "LensMirrorConnector",
    "LensMirrorCompanyMapper",
    "LensMirrorContactMapper",
    "LensMirrorDealMapper",
]
