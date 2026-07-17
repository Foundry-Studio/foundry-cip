# foundry: kind=test domain=client-intelligence-platform
"""cip_111 — the three Stripe live-sync tables exist, scoped + granted (AUTOMATIONS-PLAN §3).

Structural test in the test_cip_109/110 shape: each table exists post-chain, carries its key
columns, has FORCE RLS + the cip_tenant_scope policy, and is grant-readable by cip_query_reader.
The EVIDENCE-ONLY semantics of refunds/credit_notes are enforced by process (the sync never nets
them) + the table comments, not by schema, so there is nothing to assert there.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

# table -> the key columns downstream code / the sync rely on
EXPECTED = {
    "ps_stripe_events_processed": {
        "event_id", "tenant_id", "event_created", "event_type", "object_id", "applied_at",
    },
    "ps_stripe_refunds": {
        "stripe_refund_id", "tenant_id", "charge_id", "invoice_id", "amount",
        "currency", "status", "reason", "refund_created", "ingested_at",
    },
    "ps_stripe_credit_notes": {
        "stripe_credit_note_id", "tenant_id", "invoice_id", "total", "currency",
        "status", "reason", "credit_note_created", "ingested_at",
    },
}


@pytest.mark.requires_postgres
@pytest.mark.parametrize("table,cols", EXPECTED.items())
def test_table_exists_with_key_columns(seeded_engine: Engine, table: str, cols: set) -> None:
    with seeded_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
        ).scalar() is not None, f"{table} missing"
        actual = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
            ), {"t": table}).fetchall()
        }
        assert not (cols - actual), f"{table} missing columns: {cols - actual}"


@pytest.mark.requires_postgres
@pytest.mark.parametrize("table", list(EXPECTED))
def test_force_rls_and_tenant_policy(seeded_engine: Engine, table: str) -> None:
    """FORCE RLS + a cip_tenant_scope policy with both USING and WITH CHECK (cip_49 house style)."""
    with seeded_engine.connect() as conn:
        forced = conn.execute(
            text("SELECT relforcerowsecurity FROM pg_class WHERE relname = :t"), {"t": table}
        ).scalar()
        assert forced is True, f"{table} must FORCE row level security"
        pol = conn.execute(text(
            "SELECT qual IS NOT NULL, with_check IS NOT NULL FROM pg_policies "
            "WHERE tablename = :t AND policyname = 'cip_tenant_scope'"
        ), {"t": table}).fetchone()
        assert pol is not None, f"{table} missing cip_tenant_scope policy"
        assert pol[0] and pol[1], f"{table} policy needs both USING and WITH CHECK"


@pytest.mark.requires_postgres
@pytest.mark.parametrize("table", list(EXPECTED))
def test_grant_readable_by_read_roles(seeded_engine: Engine, table: str) -> None:
    with seeded_engine.connect() as conn:
        for role in ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk"):
            has_grant = conn.execute(text(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE table_name = :t AND grantee = :r AND privilege_type = 'SELECT'"
            ), {"t": table, "r": role}).scalar()
            assert has_grant, f"{table} not granted SELECT to {role}"
