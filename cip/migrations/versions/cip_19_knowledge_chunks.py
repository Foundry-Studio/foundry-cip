# foundry: kind=migration domain=client-intelligence-platform
"""CIP M2 step — cip_knowledge_chunks for Layer 2 semantic search.

Per PM scope 2d6390fa (Layer 2 wiring v1) + 47fd2b2e/d46f4b37
(Wayward instance).

v1 STORAGE DECISION (2026-05-17): Postgres-native double precision[]
column for the embedding vector — NOT pgvector (not available in
Railway), NOT Pinecone (API key not in local env). Rationale:

  - 24K vectors × 2,560 dims × 8 bytes = ~470 MB. Fits easily.
  - Same DB as cip_engagements / cip_ticket_comments → one backup
    story, one query language, one RLS pattern.
  - Cosine similarity is computed at query-time in Python (post-
    fetch) OR via a Postgres function — fine at 24K-row scale.
  - When pgvector becomes available in Railway or volume grows,
    upgrade path is single ALTER TABLE statement.

Schema:
  cip_knowledge_chunks — one row per (tenant, client, source_kind,
    source_id, chunk_index) tuple. Embedded with the configured
    embedding model. Tenant-scoped via RLS.

source_kind values (open enum, free text):
  - 'cip_ticket_comment' — body of a cip_ticket_comments row
  - 'cip_engagement_note' / 'cip_engagement_meeting' / 'cip_engagement_task' — body of cip_engagements
  - 'cip_ticket' — description of cip_tickets
  - (future) 'cip_deal_description', 'cip_company_about', etc.

Revision ID: cip_19_knowledge_chunks
Revises: cip_18_wayward_attr_lenses
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cip_19_knowledge_chunks"
down_revision: str | Sequence[str] | None = "cip_18_wayward_attr_lenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cip_knowledge_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Source identity — what record + which chunk
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        # Embedding
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("content_chars", sa.Integer(), nullable=False),
        sa.Column(
            "embedding",
            postgresql.ARRAY(sa.dialects.postgresql.DOUBLE_PRECISION),
            nullable=False,
        ),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        # Metadata for retrieval-side filtering + provenance
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "source_kind", "source_id", "chunk_index",
            name="uq_cip_knowledge_chunks_source",
        ),
    )
    op.create_index(
        "idx_cip_knowledge_chunks_tenant_client",
        "cip_knowledge_chunks",
        ["tenant_id", "client_id"],
    )
    op.create_index(
        "idx_cip_knowledge_chunks_source",
        "cip_knowledge_chunks",
        ["tenant_id", "source_kind", "source_id"],
    )
    op.create_index(
        "idx_cip_knowledge_chunks_kind",
        "cip_knowledge_chunks",
        ["tenant_id", "source_kind"],
    )
    op.create_index(
        "idx_cip_knowledge_chunks_content_hash",
        "cip_knowledge_chunks",
        ["tenant_id", "content_hash"],
    )

    # RLS
    op.execute("ALTER TABLE cip_knowledge_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_knowledge_chunks FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON cip_knowledge_chunks "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )

    # Cosine similarity SQL function (works on double precision[] vectors).
    # When pgvector is available, switch to its native <=> operator and
    # drop this function. For now, this is the bridge.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cip_cosine_similarity(
            a double precision[], b double precision[]
        ) RETURNS double precision AS $$
        DECLARE
            i int;
            dot double precision := 0;
            norm_a double precision := 0;
            norm_b double precision := 0;
            len int := least(array_length(a, 1), array_length(b, 1));
        BEGIN
            IF len IS NULL OR len = 0 THEN
                RETURN NULL;
            END IF;
            FOR i IN 1..len LOOP
                dot := dot + a[i] * b[i];
                norm_a := norm_a + a[i] * a[i];
                norm_b := norm_b + b[i] * b[i];
            END LOOP;
            IF norm_a = 0 OR norm_b = 0 THEN
                RETURN NULL;
            END IF;
            RETURN dot / (sqrt(norm_a) * sqrt(norm_b));
        END;
        $$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS cip_cosine_similarity(double precision[], double precision[])")
    op.execute("DROP POLICY IF EXISTS cip_tenant_scope ON cip_knowledge_chunks")
    op.execute("ALTER TABLE cip_knowledge_chunks NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cip_knowledge_chunks DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_cip_knowledge_chunks_content_hash", table_name="cip_knowledge_chunks")
    op.drop_index("idx_cip_knowledge_chunks_kind", table_name="cip_knowledge_chunks")
    op.drop_index("idx_cip_knowledge_chunks_source", table_name="cip_knowledge_chunks")
    op.drop_index("idx_cip_knowledge_chunks_tenant_client", table_name="cip_knowledge_chunks")
    op.drop_table("cip_knowledge_chunks")
