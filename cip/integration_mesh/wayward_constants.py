# foundry: kind=module domain=client-intelligence-platform
"""Canonical UUIDs for Wayward tenant resolution.

Per VISION §4: tenants are operators/ventures (EcomLever);
clients are subjects of intelligence INSIDE a tenant (Wayward).

Wayward's data flows into CIP under:
  - tenant_id = EcomLever ('dec814db-...')
  - client_id = Wayward    ('661ecab4-...', deterministic UUIDv5
    derived from uuid5(EcomLever_tenant_id, 'wayward'))

The Wayward client row is seeded by migration
`cip_12_seed_wayward_client`.

History: 2026-05-12 a "locked coordinate" doc reserved
`b0000000-0000-0000-0000-000000000001` as Wayward's tenant_id. That
was a working stand-in, not VISION-aligned. Superseded 2026-05-16.

When adding new tenants/clients, NEVER use placeholder UUIDs —
look up the canonical IDs in the `tenants` and `cip_clients` tables.
See `docs/ONBOARDING-A-NEW-TENANT.md` Phase 0 (Stakeholder alignment)
for the canonical-UUID-resolution rule.
"""
from uuid import UUID

ECOMLEVER_TENANT_ID: UUID = UUID("dec814db-722a-4730-8e60-51afc4a5dad9")
WAYWARD_CLIENT_ID: UUID = UUID("661ecab4-dddb-5924-a34d-af1c5133132d")

# Legacy placeholder — for migration scripts that need to reference the
# pre-2026-05-16 tenant_id during data correction. DO NOT use for any
# new code path.
_LEGACY_WAYWARD_PLACEHOLDER: UUID = UUID("b0000000-0000-0000-0000-000000000001")


def set_wayward_client_id_on_null_rows(engine: object) -> dict[str, int]:
    """Tactical post-sync helper: backfill client_id on any rows the
    orchestrator wrote with NULL client_id.

    The orchestrator/persister don't yet propagate client_id from the
    sync caller down to INSERT/UPDATE statements (PM scope to be filed:
    "client_id propagation through orchestrator + persister"). Until
    that ships, syncs land new rows with NULL client_id. This helper
    fixes them up after each sync run for the Wayward client.

    Idempotent: re-running is safe (no rows match the WHERE once
    they've been set).

    Returns dict {table_name: rows_updated} for the operator's log.
    """
    from sqlalchemy import text
    tables = (
        "cip_companies", "cip_contacts", "cip_deals", "cip_tickets",
        "cip_ticket_comments", "cip_engagements", "cip_files",
        "cip_sync_runs", "cip_views",
    )
    updated: dict[str, int] = {}
    with engine.begin() as conn:  # type: ignore[attr-defined]
        for t in tables:
            r = conn.execute(
                text(
                    f"UPDATE {t} SET client_id = :c "
                    f"WHERE tenant_id = :tid AND client_id IS NULL"
                ),
                {
                    "c": str(WAYWARD_CLIENT_ID),
                    "tid": str(ECOMLEVER_TENANT_ID),
                },
            )
            updated[t] = r.rowcount or 0
    return updated
