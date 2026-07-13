# foundry: kind=migration domain=client-intelligence-platform
"""cip_41: ps_brand_observations (evidence store) + classification decision metadata.

Locks the facts-vs-conclusions separation Tim specified 2026-07-09:

  "if someone in slack says it's chinese, but the client is NOT listed chinese in
   hubspot, those are two pieces of separate info — don't let things supersede
   until the final decision column, which is china or not"

So:

(a) ``ps_brand_observations`` — an APPEND-ONLY evidence store. One immutable row per
    (subject, field, source). Every fact carries WHERE IT CAME FROM (source_system +
    source_ref, e.g. a Slack permalink) and WHEN IT WAS OBSERVED. Sources are allowed
    to disagree: Slack's brand-connection feed saying Country=CN and HubSpot saying
    country=US are two separate true statements about what a *source* said. Both are
    stored. Neither wins. Ingestion writes ONLY here — it must never touch a decision.

(b) Decision metadata on cip_clients alongside the existing ``nationality_class``
    (cip_38). ``nationality_class`` remains THE single determination
    (chinese_confirmed / chinese_suspected / non_chinese / unknown); these columns
    record who decided, when, and why, so a conclusion is auditable and clearly
    distinct from the evidence that informed it. Only the decision layer (rules +
    human review) writes these — never a connector.

Append-only is enforced at the DB (a BEFORE UPDATE/DELETE trigger that raises —
fires for the table owner too, unlike RLS), mirroring ps_annotations (cip_39).
Re-ingest is idempotent via the natural key + ON CONFLICT DO NOTHING: a re-run
adds nothing and rewrites nothing.

Revision ID: cip_41_brand_observations
Revises: cip_40_ps_china_lens_v2
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_41_brand_observations"
down_revision: str | Sequence[str] | None = "cip_40_ps_china_lens_v2"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# The determination is a separate act from the evidence.
_REVIEW_STATUSES = ("pending", "confirmed", "escalated")


def upgrade() -> None:
    # ── (a) Evidence store — append-only, provenance-carrying ────────────────
    op.execute(
        """
        CREATE TABLE ps_brand_observations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,

            -- Subject: the brand. wayward_brand_id is the exact join key the
            -- Slack brand-connection feed emits; client_id is the resolved
            -- cip_clients row when we can match it (nullable — an observation
            -- is still a fact even if the brand isn't in CIP yet).
            subject_type TEXT NOT NULL DEFAULT 'brand'
                CHECK (subject_type IN ('brand')),
            wayward_brand_id UUID,
            client_id UUID,

            -- The fact itself.
            field TEXT NOT NULL,              -- country, referral_source, deal_source,
                                              -- usage_fee_pct, email, hubspot_company_id, ...
            value TEXT,                       -- verbatim, as the source stated it
            value_normalized TEXT,            -- lowercased/trimmed for matching

            -- WHERE IT CAME FROM (the whole point).
            source_system TEXT NOT NULL,      -- 'slack:amazon-brand-connections',
                                              -- 'hubspot', 'jake_report',
                                              -- 'human:tim', 'rule:<id>'
            source_ref TEXT NOT NULL,         -- Slack permalink / message ts /
                                              -- report filename / deal id
            observed_at TIMESTAMPTZ,          -- when the source says it was true
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            confidence NUMERIC(4,3),          -- optional, per-source

            -- Idempotency: same fact from the same source ref lands once.
            UNIQUE (tenant_id, subject_type, wayward_brand_id, field,
                    source_system, source_ref)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_obs_brand ON ps_brand_observations "
        "(tenant_id, wayward_brand_id, field)"
    )
    op.execute(
        "CREATE INDEX idx_ps_obs_client ON ps_brand_observations (tenant_id, client_id)"
    )
    op.execute(
        "CREATE INDEX idx_ps_obs_field_value ON ps_brand_observations "
        "(tenant_id, field, value_normalized)"
    )
    op.execute(
        "CREATE INDEX idx_ps_obs_source ON ps_brand_observations "
        "(tenant_id, source_system)"
    )

    op.execute("ALTER TABLE ps_brand_observations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_brand_observations FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON ps_brand_observations "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_brand_observations TO {role}")

    # Facts are immutable. Enforced at the DB, not by convention.
    op.execute(
        """
        CREATE FUNCTION ps_brand_observations_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'ps_brand_observations is append-only (no % allowed) — '
                'observations are immutable facts; add a new one instead', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_ps_brand_observations_append_only "
        "BEFORE UPDATE OR DELETE ON ps_brand_observations "
        "FOR EACH ROW EXECUTE FUNCTION ps_brand_observations_append_only()"
    )

    # ── (b) Decision metadata — the conclusion, kept distinct from evidence ──
    # nationality_class itself already exists (cip_38) and remains THE decision.
    op.execute(
        f"""
        ALTER TABLE cip_clients
            ADD COLUMN IF NOT EXISTS nationality_decided_by TEXT,
            ADD COLUMN IF NOT EXISTS nationality_decided_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS nationality_rationale TEXT,
            ADD COLUMN IF NOT EXISTS nationality_review_status TEXT
                CHECK (nationality_review_status IS NULL
                       OR nationality_review_status IN
                          ({", ".join(f"'{s}'" for s in _REVIEW_STATUSES)}))
        """
    )
    # The chase/review queue scans this.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cip_clients_nationality_review "
        "ON cip_clients (tenant_id, nationality_review_status) "
        "WHERE nationality_review_status IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_cip_clients_nationality_review")
    op.execute(
        """
        ALTER TABLE cip_clients
            DROP COLUMN IF EXISTS nationality_review_status,
            DROP COLUMN IF EXISTS nationality_rationale,
            DROP COLUMN IF EXISTS nationality_decided_at,
            DROP COLUMN IF EXISTS nationality_decided_by
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_ps_brand_observations_append_only "
        "ON ps_brand_observations"
    )
    op.execute("DROP FUNCTION IF EXISTS ps_brand_observations_append_only()")
    op.execute("DROP TABLE IF EXISTS ps_brand_observations CASCADE")
