# foundry: kind=script domain=client-intelligence-platform

"""Resolve cross-connector identity links (deterministic email match, v1).

PM scope 08b4ce7d. Populates cip_identity_links by exact-matching
Zendesk contacts to HubSpot contacts on lower(trim(email)) within a
tenant. v1 is DETERMINISTIC ONLY — no fuzzy/ML (v3), no manual UI (v2).

Tiers (identity-resolution-policy-design.md §4.1):
  - exact 1:1, local-part NOT a role inbox  → email-exact         conf 1.0
  - exact 1:1, local-part ∈ role set        → email-role-account  conf 0.9
  - email → >1 hubspot contact (ambiguous)  → email-ambiguous     conf 0.5
                                              (all candidates written; NOT auto-consumed)

Excludes internal/agent email domains (Wayward's own reply system, etc.)
so staff identities aren't treated as customer identities.

Idempotent: upsert keyed on
(tenant_id, left_connector, left_source_id, right_connector,
 right_source_id, method). Re-run refreshes confidence/refreshed_at,
never duplicates. NEVER touches rows whose method is 'manual' or starts
'operator:' — the deterministic pass leaves human overrides alone.

Usage:
    CIP_DATABASE_URL=postgresql://… TENANT_ID=<uuid> \
        python scripts/resolve_identity_links.py [--dry-run]

Idempotent: yes
Category: sync
Owner: tim
Lifecycle: active
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

log = logging.getLogger("cip.resolve_identity_links")

_LEFT_CONNECTOR = "zendesk-v1"
_RIGHT_CONNECTOR = "hubspot-v1"
_METHOD = "deterministic-email-v1"

# Local-part role/shared-inbox set (policy §4.1). Matched case-insensitively
# against the part before '@'.
_ROLE_LOCALPARTS = frozenset({
    "support", "info", "sales", "hello", "admin", "billing",
    "no-reply", "noreply", "contact", "help", "team", "orders",
    "service", "returns", "wholesale", "care",
})

# Internal/agent email domains to exclude from customer-identity linking.
# Grounded on prod 2026-05-24: Wayward's outbound-reply system domain.
_EXCLUDED_DOMAINS = frozenset({
    "reply.email.wayward.com",
})


@dataclass
class ResolveSummary:
    tenant_id: str
    candidate_emails: int = 0
    email_exact: int = 0
    email_role_account: int = 0
    email_ambiguous: int = 0
    excluded_domain: int = 0
    upserted: int = 0
    manual_preserved: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# Resolve every zendesk-contact ↔ hubspot-contact email match in one query.
# Returns one row per (zendesk_source_id, hubspot_source_id) candidate edge,
# plus the per-email hubspot match count (for ambiguity tiering) and the
# zendesk local-part/domain (for role + exclusion tiering).
_RESOLVE_SQL = text(
    """
    WITH z AS (
        SELECT source_id AS zendesk_source_id,
               lower(trim(email)) AS em,
               split_part(lower(trim(email)), '@', 1) AS localpart,
               split_part(lower(trim(email)), '@', 2) AS domain
        FROM cip_contacts
        WHERE tenant_id = :tid
          AND source_connector = 'zendesk-v1'
          AND NULLIF(trim(email), '') IS NOT NULL
    ),
    h AS (
        SELECT source_id AS hubspot_source_id,
               lower(trim(email)) AS em
        FROM cip_contacts
        WHERE tenant_id = :tid
          AND source_connector = 'hubspot-v1'
          AND NULLIF(trim(email), '') IS NOT NULL
    ),
    matched AS (
        SELECT z.zendesk_source_id, z.em, z.localpart, z.domain,
               h.hubspot_source_id,
               COUNT(*) OVER (PARTITION BY z.zendesk_source_id) AS hubspot_match_count
        FROM z JOIN h ON h.em = z.em
    )
    SELECT zendesk_source_id, em, localpart, domain,
           hubspot_source_id, hubspot_match_count
    FROM matched
    """
)

_UPSERT_SQL = text(
    """
    INSERT INTO cip_identity_links (
        id, tenant_id, left_connector, left_source_id,
        right_connector, right_source_id, link_type, confidence, method,
        ingested_at, refreshed_at
    ) VALUES (
        gen_random_uuid(), :tid, :lc, :lsid, :rc, :rsid,
        :link_type, :confidence, :method, NOW(), NOW()
    )
    ON CONFLICT (tenant_id, left_connector, left_source_id,
                 right_connector, right_source_id, method)
    DO UPDATE SET
        link_type = EXCLUDED.link_type,
        confidence = EXCLUDED.confidence,
        refreshed_at = NOW()
    """
)


def _tier(localpart: str, domain: str, match_count: int) -> tuple[str, float] | None:
    """Return (link_type, confidence) for an edge, or None to skip."""
    if domain in _EXCLUDED_DOMAINS:
        return None
    if match_count > 1:
        return ("email-ambiguous", 0.5)
    if localpart in _ROLE_LOCALPARTS:
        return ("email-role-account", 0.9)
    return ("email-exact", 1.0)


def resolve_tenant(engine: Engine, tenant_id: UUID, *, dry_run: bool = False) -> ResolveSummary:
    """Resolve identity links for one tenant. GUC-scoped + idempotent."""
    summary = ResolveSummary(tenant_id=str(tenant_id))
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        rows = conn.execute(_RESOLVE_SQL, {"tid": str(tenant_id)}).mappings().all()

        seen_zendesk: set[str] = set()
        for r in rows:
            seen_zendesk.add(r["zendesk_source_id"])
            tier = _tier(r["localpart"], r["domain"], r["hubspot_match_count"])
            if tier is None:
                summary.excluded_domain += 1
                continue
            link_type, confidence = tier
            if link_type == "email-exact":
                summary.email_exact += 1
            elif link_type == "email-role-account":
                summary.email_role_account += 1
            elif link_type == "email-ambiguous":
                summary.email_ambiguous += 1

            if dry_run:
                continue

            # Never clobber a manual/operator override: the unique key
            # includes `method`, so this deterministic upsert is a
            # separate row from any 'manual'/'operator:' row. The
            # consumption rule (lens) prefers manual. We additionally
            # skip writing the deterministic row only if a manual row
            # for the SAME edge exists AND we'd contradict it — but per
            # policy we just coexist; nothing to skip here.
            conn.execute(_UPSERT_SQL, {
                "tid": str(tenant_id),
                "lc": _LEFT_CONNECTOR, "lsid": r["zendesk_source_id"],
                "rc": _RIGHT_CONNECTOR, "rsid": r["hubspot_source_id"],
                "link_type": link_type, "confidence": confidence,
                "method": _METHOD,
            })
            summary.upserted += 1

        summary.candidate_emails = len(seen_zendesk)

        # Count manual rows preserved (informational).
        summary.manual_preserved = conn.execute(text(
            "SELECT COUNT(*) FROM cip_identity_links "
            "WHERE tenant_id = :tid AND (method LIKE 'operator:%' OR link_type = 'manual')"
        ), {"tid": str(tenant_id)}).scalar() or 0

    return summary


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Resolve cip_identity_links (deterministic email match)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute tiers, write nothing")
    args = parser.parse_args()

    url = (
        os.environ.get("CIP_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("DATABASE_PUBLIC_URL")
    )
    if not url:
        log.error("CIP_DATABASE_URL / DATABASE_URL not set")
        return 2
    tenant_raw = os.environ.get("TENANT_ID", "").strip()
    if not tenant_raw:
        log.error("TENANT_ID env var required (the tenant to resolve)")
        return 2
    try:
        tenant_id = UUID(tenant_raw)
    except ValueError:
        log.error("TENANT_ID=%r is not a valid uuid", tenant_raw)
        return 2

    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = create_engine(url, pool_pre_ping=True)
    try:
        summary = resolve_tenant(engine, tenant_id, dry_run=args.dry_run)
    finally:
        engine.dispose()

    import json
    print("RESOLVE_IDENTITY_LINKS_SUMMARY " + json.dumps(summary.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
