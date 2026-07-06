# foundry: kind=migration domain=client-intelligence-platform
"""cip_38: PS China Book v2 — CIP base columns on cip_clients (S2).

PS China Book Schema v2, Phase 1 (build spec: china-commission-audit/12-CC-SCHEMA-HANDOFF.md
§S2; semantics: 11-MONEY-FLOW-EXPLAINER.md; mapping: 10-CIP-DATA-MODEL-PROPOSAL.md).

Adds six CIP-*base* columns to cip_clients (all tenants, per Tim 2026-07-06 —
classification lives on the base, the PS lens consumes `chinese_confirmed`).
These are CIP-computed / report-derived, NOT connector domain fields — the
HubSpot mapper never emits them, so the persister's targeted-column UPDATE
(persister.py `_update_current`) leaves them untouched on every re-sync (verified:
the differ treats columns absent from `row.fields` as "no change"). They are
therefore clobber-safe as real columns without needing the companion_data escape
hatch. Their audit trail is `ps_annotations` (cip_39), not SCD-2 history, so they
are intentionally NOT mirrored onto cip_clients_history (the differ skips
target columns the history table lacks — no error).

TEXT + CHECK (repo convention — no Postgres ENUM types, cf. cip_23).

Revision ID: cip_38_ps_china_base_cols
Revises: cip_37_grant_repair
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_38_ps_china_base_cols"
down_revision: str | Sequence[str] | None = "cip_37_grant_repair"
branch_labels = None
depends_on = None


# D5-locked classification enum (doc 10 §B2 / doc 12 §S2).
_NATIONALITY_CLASSES = (
    "chinese_confirmed",
    "chinese_suspected",
    "non_chinese",
    "unknown",
)
# Computed later from the fee ledger (job is Phase 2); column now.
_PERFORMANCE_TIERS = ("heavy", "standard", "dormant")
# Wayward lifecycle enum, adopted verbatim from the Brand List report.
_LIFECYCLE_STATUSES = (
    "ACCOUNT_CREATED",
    "ACTIVE",
    "PRODUCTIVE_NOT_PAID",
    "PRODUCTIVE_PAYABLE",
)


def _csv(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE cip_clients
            ADD COLUMN IF NOT EXISTS nationality_class TEXT NOT NULL DEFAULT 'unknown'
                CHECK (nationality_class IN ({_csv(_NATIONALITY_CLASSES)})),
            ADD COLUMN IF NOT EXISTS wayward_brand_id UUID NULL,
            ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NULL
                CHECK (lifecycle_status IS NULL
                       OR lifecycle_status IN ({_csv(_LIFECYCLE_STATUSES)})),
            ADD COLUMN IF NOT EXISTS performance_tier TEXT NULL
                CHECK (performance_tier IS NULL
                       OR performance_tier IN ({_csv(_PERFORMANCE_TIERS)})),
            ADD COLUMN IF NOT EXISTS exhibit_a BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS exhibit_a_matched_name TEXT NULL
        """
    )
    # wayward_brand_id is the join key for Jake's reports + Exhibit A — index it
    # (partial: only the rows that carry one).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cip_clients_wayward_brand_id "
        "ON cip_clients (tenant_id, wayward_brand_id) "
        "WHERE wayward_brand_id IS NOT NULL"
    )
    # Classification chase queue + PS-lens filter both scan nationality_class.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cip_clients_nationality "
        "ON cip_clients (tenant_id, nationality_class)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_cip_clients_nationality")
    op.execute("DROP INDEX IF EXISTS idx_cip_clients_wayward_brand_id")
    op.execute(
        """
        ALTER TABLE cip_clients
            DROP COLUMN IF EXISTS exhibit_a_matched_name,
            DROP COLUMN IF EXISTS exhibit_a,
            DROP COLUMN IF EXISTS performance_tier,
            DROP COLUMN IF EXISTS lifecycle_status,
            DROP COLUMN IF EXISTS wayward_brand_id,
            DROP COLUMN IF EXISTS nationality_class
        """
    )
