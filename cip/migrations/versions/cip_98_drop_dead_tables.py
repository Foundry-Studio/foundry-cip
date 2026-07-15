# foundry: kind=migration domain=client-intelligence-platform
"""cip_98: drop two genuinely-dead tables (Tim, 2026-07-15, after blast-radius verification).

Both verified 2026-07-15: no inbound FK, no dependent view, no trigger, no live code reference
(grep over cip/ + scripts/ + tests/, excluding migrations), not in the connector framework's
ALLOWED_CIP_TABLES / persister map.

1. `cip_test_trace` — a 1-column debug artifact from M1 env.py troubleshooting. MIGRATION-RUNBOOK
   already documents it as "historical artifact, not a supported table… no migration backing it,
   artifact only" (dropped once 2026-04-20, reappeared). No migration creates it; nothing reads it.

2. `ps_classification_rules` — 10 rows of the OLD weighted name-signal classifier (cjk_chars=0.9,
   country_cn_hk=0.8, city_shenzhen=0.6, …), created cip_39. That whole approach was replaced by
   evidence rows in `ps_nationality_signals` → `lens_ps_china_verdict`; nothing reads this table
   anymore (grep: migrations only). Same class as the cip_97 removals.

NOT dropped (held, they have negative blast radius): `cip_marketing_emails`, `cip_contact_lists`,
`cip_contact_list_memberships` are EMPTY but are SUPPORTED connector targets — registered in
`cip/integration_mesh/base.py` (ALLOWED_CIP_TABLES) + `persister.py`, and read by test_base.py
(pins len==15) and test_cip_31. Empty by sync scope, not dead. Removing them is a connector-
framework change, not a zero-risk drop — flagged to Tim, not done here.

Reversible: downgrade recreates both tables (empty — the data was dead). ps_classification_rules is
restored with its constraints, RLS, and read grants.

Revision ID: cip_98_drop_dead_tables
Revises: cip_97_remove_nationality_system
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_98_drop_dead_tables"
down_revision: str | Sequence[str] | None = "cip_97_remove_nationality_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cip_test_trace")
    op.execute("DROP TABLE IF EXISTS ps_classification_rules")


def downgrade() -> None:
    # 1. the trivial debug artifact
    op.execute("CREATE TABLE IF NOT EXISTS cip_test_trace (id integer)")

    # 2. the old classifier rules table — structure + constraints + RLS + grants (data not restored)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ps_classification_rules (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL,
            signal text NOT NULL,
            pattern text NOT NULL,
            weight numeric NOT NULL,
            notes text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ps_classification_rules_tenant_id_signal_pattern_key
                UNIQUE (tenant_id, signal, pattern)
        )
        """
    )
    op.execute("ALTER TABLE ps_classification_rules ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON ps_classification_rules "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )
    # Guard every grant on role-existence: cip_rls_test_role is provisioned by the pytest harness
    # and is absent from the plain Tier-C container, so an unguarded GRANT breaks env-agnostic replay.
    op.execute(
        """
        DO $$
        DECLARE r text;
        BEGIN
            FOREACH r IN ARRAY ARRAY['cip_query_reader','cip_metabase_project_silk','cip_twenty_project_silk'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('GRANT SELECT ON ps_classification_rules TO %I', r);
                END IF;
            END LOOP;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cip_rls_test_role') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON ps_classification_rules TO cip_rls_test_role;
            END IF;
        END $$;
        """
    )
