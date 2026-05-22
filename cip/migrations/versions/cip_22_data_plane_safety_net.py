# foundry: kind=migration domain=client-intelligence-platform
"""cip_22: data-plane safety net — cip_files dedupe UNIQUE + cip_knowledge_chunks source_kind CHECK.

Per PM scope `ed653420` (Hardening — CIP data-plane safety net, filed
2026-05-22 from Hard-Split sniff test). Closes two integrity gaps that
the Rocky Ridge migration surfaced:

1. **cip_files has no natural dedupe constraint.** Today's RR migration
   script does SELECT-then-INSERT against `(tenant_id, client_id,
   sha256)`. Two ingestion paths racing on the same file would produce
   duplicate rows. Partial unique index closes the gap cheaply (only
   covers rows where sha256 is set, so legacy/in-flight rows without a
   hash don't block).

2. **cip_knowledge_chunks.source_kind is unconstrained.** Any string can
   be written. We just closed the equivalent gate on Foundry-Knowledge
   via cip02_revert_source_types (2026-05-22). Mirror that defense here.

The CHECK lists the 10 source_kinds currently planned per CIP-SPEC-010
(Hard Split) + observed in prod (`cip_engagement_meeting`,
`cip_engagement_note`, `cip_ticket_comment`, `cip_client_document` are
live as of 2026-05-22). Additional source_kinds get added via future
migrations as new connectors land.

Revision ID: cip_22_data_plane_safety_net
Revises: cip_21_project_silk_grant_role
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "cip_22_data_plane_safety_net"
down_revision: str | Sequence[str] | None = "cip_21_project_silk_grant_role"
branch_labels = None
depends_on = None


# Allowed source_kind values for cip_knowledge_chunks. Additive — extend
# with future migrations as new content kinds land. Keep alphabetized.
_ALLOWED_SOURCE_KINDS = (
    "cip_call_transcript",
    "cip_client_document",   # uploaded docs (RR research library)
    "cip_contract",
    "cip_email_thread",
    "cip_engagement_meeting",
    "cip_engagement_note",
    "cip_ticket_body",
    "cip_ticket_comment",
    "cip_sop",
    "cip_training",
)


def upgrade() -> None:
    # 1. cip_files partial UNIQUE (tenant_id, client_id, sha256)
    # Partial — only rows with sha256 set are constrained. Older rows
    # (pre-cip_22) or in-flight rows where sha256 hasn't been computed
    # yet are exempt. This matches how the RR migration writes: sha256
    # is populated on every new row, but the schema doesn't FORCE it
    # NOT NULL on legacy data.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cip_files_tenant_client_sha256 "
        "ON cip_files (tenant_id, client_id, sha256) "
        "WHERE sha256 IS NOT NULL"
    )

    # 2. cip_knowledge_chunks.source_kind CHECK
    # Drop any existing CHECK first to be safe on idempotent re-runs.
    # Use raw SQL because the constraint may not exist on first run; the
    # IF EXISTS clause handles that.
    op.execute(
        "ALTER TABLE cip_knowledge_chunks "
        "DROP CONSTRAINT IF EXISTS ck_cip_knowledge_chunks_source_kind"
    )
    allowed_csv = ", ".join(f"'{k}'" for k in _ALLOWED_SOURCE_KINDS)
    op.execute(
        f"ALTER TABLE cip_knowledge_chunks "
        f"ADD CONSTRAINT ck_cip_knowledge_chunks_source_kind "
        f"CHECK (source_kind IN ({allowed_csv}))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE cip_knowledge_chunks "
        "DROP CONSTRAINT IF EXISTS ck_cip_knowledge_chunks_source_kind"
    )
    op.execute("DROP INDEX IF EXISTS uq_cip_files_tenant_client_sha256")
