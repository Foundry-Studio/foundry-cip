# foundry: kind=migration domain=client-intelligence-platform
"""cip_177 — tombstone state for cip_files (CIP-SPEC-014 ruling 3).

WHY. Structured connectors upsert and never delete, which is right for rows
that a source system keeps forever. Documents are different: a file removed
from a tenant's library must stop being retrievable, or the platform answers
questions from material the tenant deleted. That is a correctness defect, not
a staleness one.

Tim ruled TOMBSTONE over hard delete on 2026-09-04 (PM decision
505da403-6a0a-437a-ac90-e369e684ee5c), recorded in docs/DOCUMENT-SOURCE-CONTRACT.md.
Hard delete is a one-way door with no recovery, for a problem that is
reversible. A tombstone keeps the audit trail, and filtering it out of
retrieval is cheap.

SHAPE. One nullable timestamptz. NULL means live; non-NULL is the moment the
connector observed the file gone from its source library.

  - Additive and nullable, so every existing row stays valid and reads
    unchanged. No backfill, no data rewrite.
  - Fully reversible: the downgrade drops the column. Nothing else depends on
    it at this revision.
  - A partial index on the live rows, because every retrieval path filters
    ``tombstoned_at IS NULL`` and that predicate should not cost a seq scan
    once a library has a long tail of removed files.

WHAT THIS MIGRATION DELIBERATELY DOES NOT DO. It does not filter anything.
Adding the column cannot by itself stop a tombstoned document surfacing —
every retrieval path has to honour it, and a vector left in a Pinecone
namespace is still returned by a vector search regardless of what Postgres
says. Those are code obligations, enforced by tests, not schema obligations.
A tombstone that retrieval ignores is exactly as wrong as no tombstone.

Revision ID: cip_177_file_tombstone
Revises: cip_176_rls_tenant_gaps
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cip_177_file_tombstone"
down_revision: str | Sequence[str] | None = "cip_176_rls_tenant_gaps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_cip_files_live"


def upgrade() -> None:
    op.add_column(
        "cip_files",
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "COMMENT ON COLUMN cip_files.tombstoned_at IS "
        "'When the source library was observed no longer to contain this file. "
        "NULL means live. Retrieval MUST filter non-NULL rows; see "
        "docs/DOCUMENT-SOURCE-CONTRACT.md ruling 3.'"
    )
    # Partial index on live rows only: the tombstoned tail grows without bound
    # and is never the thing being searched.
    op.create_index(
        _INDEX,
        "cip_files",
        ["tenant_id", "source_connector"],
        unique=False,
        postgresql_where=sa.text("tombstoned_at IS NULL"),
    )
    print(
        "cip_177: cip_files.tombstoned_at added (nullable, NULL = live) + "
        "partial index on live rows. Retrieval-side filtering is a CODE "
        "obligation, not enforced here."
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="cip_files")
    op.drop_column("cip_files", "tombstoned_at")
