"""One-shot — files the CIP-FW-004 Atlas decision in PM + 2 follow-up scopes.

Atlas-locked decision (2026-05-22): Association contract = JSONB source-id
natural-key joins; CIP-UUID soft-FKs deprecated; typed promotion is
*_source_id (TEXT) only. CIP-UUID FKs formally rejected.

Two follow-up scopes filed per Atlas §5 + §8:
1. cip_identity_links — cross-connector identity resolution (Zendesk
   requester ↔ HubSpot contact by email). Atlas-gated.
2. Legacy soft-FK column DROP — Tim-gated after a consumer audit.

PM is direct-SQL since foundry-tools MCP is still down. Kept in repo for
audit trail (mirror of _apply_atlas_decisions_to_pm_2026_05_22.py from
the prior Phase 2.6 build).
"""
from __future__ import annotations

import os
import sys
import json
from uuid import uuid4
from sqlalchemy import create_engine, text

PROJECT = "596825db-61bc-4899-bc6c-e207489ca35d"
TENANT = "4ebafb2d-01ba-434a-ac73-ea9603e7d0bb"
ACTOR = "claude-direct-sql-mcp-down"


def main() -> int:
    url = os.environ["DATABASE_URL"]
    sa = url.replace("postgresql://", "postgresql+psycopg://").replace(
        "postgres://", "postgresql+psycopg://"
    )
    e = create_engine(sa)
    with e.begin() as c:
        # ── 1. PM decision row ───────────────────────────────────────
        dec_id = uuid4()
        # decision_type CHECK accepts: scope_change, priority_change,
        # gate_pass, gate_kill, escalation_response, dependency_waived,
        # status_override, configuration, lessons_learned, other.
        # 'configuration' fits — Atlas locked a system-wide CONFIGURATION
        # of how associations are represented across all connectors.
        c.execute(text("""
            INSERT INTO project_decisions (
                decision_id, tenant_id, project_id, decision_type,
                summary, context, actor_type, actor_id, created_at
            ) VALUES (
                :did, :t, :p, 'configuration',
                :summary, :context, 'ai_assistant', :actor, NOW()
            )
        """), {
            "did": str(dec_id), "t": TENANT, "p": PROJECT,
            "summary": (
                "Association contract = JSONB source-id natural-key joins; "
                "CIP-UUID soft-FKs deprecated; typed promotion is *_source_id "
                "(TEXT) only. CIP-UUID FKs formally rejected."
            ),
            "context": json.dumps({
                "atlas_review_doc": "docs/vision/ATLAS-REVIEW-ASSOCIATION-CONTRACT.md (CIP-FW-004)",
                "migration": "cip_27_association_contract",
                "deprecated_columns": [
                    "cip_deals.company_id",
                    "cip_deals.contact_id",
                    "cip_contacts.company_id",
                    "cip_tickets.requester_id",
                ],
                "promotion_pattern": "<assoc>_source_id TEXT (e.g., cip_deals.company_source_id)",
                "rejected_pattern": "CIP-UUID FK columns referencing cip_*.id",
                "follow_ups": [
                    "cip_identity_links (cross-connector identity resolution; Atlas-gated)",
                    "Legacy soft-FK column DROP (Tim-gated after consumer audit)",
                ],
                "implemented_in": "foundry-cip cip_27 + lens_engine/joins.py + test_mapper_schema_drift.py",
            }),
            "actor": ACTOR,
        })
        print(f"FILED decision {dec_id}")

        # ── 2. Follow-up scope: cip_identity_links ────────────────────
        title1 = "[Phase 3 prep] cip_identity_links — cross-connector identity resolution (Atlas-gated)"
        existing = c.execute(text("""
            SELECT scope_id FROM scopes WHERE project_id=:p AND title=:t
        """), {"p": PROJECT, "t": title1}).first()
        if not existing:
            c.execute(text("""
                INSERT INTO scopes (
                    scope_id, tenant_id, project_id, title, description,
                    sort_order, status, last_status_change_at,
                    last_status_change_by, created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), :t, :p, :title, :desc,
                    400.0, 'backlog', NOW(), :actor, NOW(), NOW()
                )
            """), {
                "t": TENANT, "p": PROJECT, "title": title1,
                "actor": ACTOR,
                "desc": """Cross-connector identity resolution table — unblocks tickets-in-mirror (Phase 2.6 §Q5 deferred) and any future cross-connector association.

Atlas-locked design (CIP-FW-004 §5, 2026-05-22):

  cip_identity_links (
      id UUID PK,
      tenant_id UUID NOT NULL,
      left_connector TEXT NOT NULL,
      left_source_id TEXT NOT NULL,
      right_connector TEXT NOT NULL,
      right_source_id TEXT NOT NULL,
      link_type TEXT NOT NULL,  -- 'email-match', 'manual', 'fuzzy', etc.
      confidence NUMERIC,        -- 0.0 - 1.0
      method TEXT,               -- algorithm or operator identifier
      ingested_at, refreshed_at, ...
  )

THE HARD PART (Atlas's note): the resolution POLICY (exact / fuzzy / manual + confidence thresholds) is the actual review-worthy design call — needs its own Atlas-gated review BEFORE this table ships.

DEPENDS ON: Atlas review #N (Identity Resolution Policy) — file separately.
UNBLOCKS: tickets-in-mirror lens (LensMirrorTicketMapper); also future Plaid <-> HubSpot account linking, etc.

REF: docs/vision/ATLAS-REVIEW-ASSOCIATION-CONTRACT.md §5""",
            })
            print(f"FILED scope: {title1[:70]}...")
        else:
            print(f"SKIP (exists): {title1[:70]}...")

        # ── 3. Follow-up scope: legacy soft-FK column DROP ──────────────
        title2 = "[Cleanup] Drop the 4 deprecated soft-FK columns (cip_27 follow-up, Tim-gated after audit)"
        existing = c.execute(text("""
            SELECT scope_id FROM scopes WHERE project_id=:p AND title=:t
        """), {"p": PROJECT, "t": title2}).first()
        if not existing:
            c.execute(text("""
                INSERT INTO scopes (
                    scope_id, tenant_id, project_id, title, description,
                    sort_order, status, last_status_change_at,
                    last_status_change_by, created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), :t, :p, :title, :desc,
                    410.0, 'backlog', NOW(), :actor, NOW(), NOW()
                )
            """), {
                "t": TENANT, "p": PROJECT, "title": title2,
                "actor": ACTOR,
                "desc": """The 4 deprecated soft-FK columns (cip_deals.company_id, cip_deals.contact_id, cip_contacts.company_id, cip_tickets.requester_id) are currently COMMENT-deprecated (cip_27, 2026-05-22). Atlas deferred the actual DROP until a consumer audit confirms nothing reads them.

WHY THIS IS DEFERRED:
- Metabase questions / saved SQL across multiple tenants may reference these column names verbatim. Dropping them silently breaks those.
- External REST consumers (Phase 4+) may have hardcoded the column names.
- The COMMENT-deprecation today gives operators visibility without breaking consumers.

PRE-DROP AUDIT CHECKLIST (Atlas §7):
- grep across foundry-metabase, all venture repos, and any external integration code for the column names
- query Metabase's saved-card metadata for any SELECT referencing them
- file a one-month migration window with explicit consumer notification
- run the DROP migration ONLY after the audit passes

WHEN TIM-GATED: do not ship the DROP without explicit Tim approval (this is destructive + irreversible).

REF: docs/vision/ATLAS-REVIEW-ASSOCIATION-CONTRACT.md §7 + §8 + cip_27 migration.""",
            })
            print(f"FILED scope: {title2[:70]}...")
        else:
            print(f"SKIP (exists): {title2[:70]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
