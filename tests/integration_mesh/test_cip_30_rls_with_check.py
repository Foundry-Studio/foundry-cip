# foundry: kind=test domain=client-intelligence-platform
"""Tests for cip_30 — WITH CHECK hardening on cip_tenant_scope (PM a1055c41).

The new guarantee: an INSERT or UPDATE that would land a row whose
tenant_id ≠ the session GUC is now REJECTED by the policy's WITH CHECK
clause (previously it would silently succeed on INSERT and silently
rewrite tenant on UPDATE — the USING-only fence had no post-write
validation).

The fixture-side seed_engine runs alembic upgrade head, which now
includes cip_30 — so every cip_* table with cip_tenant_scope has
WITH CHECK in the testcontainer.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests._helpers.rls import session_as_role_and_tenant

# ── 1. Every cip_tenant_scope policy now carries WITH CHECK ──────────────


@pytest.mark.requires_postgres
def test_every_cip_tenant_scope_policy_has_with_check(seeded_engine: Engine) -> None:
    """Defense-in-depth shape check: after cip_30, no cip_tenant_scope
    policy should be missing WITH CHECK."""
    with seeded_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT tablename, with_check FROM pg_policies "
            "WHERE schemaname='public' AND policyname='cip_tenant_scope' "
            "ORDER BY tablename"
        )).fetchall()
    assert rows, "no cip_tenant_scope policies found — migration chain broken"
    missing = [r[0] for r in rows if r[1] is None]
    assert not missing, (
        f"cip_30 hardening incomplete — tables still missing WITH CHECK: {missing}"
    )


@pytest.mark.requires_postgres
def test_with_check_matches_using_expression(seeded_engine: Engine) -> None:
    """Belt-and-suspenders: WITH CHECK and USING must reference the
    same predicate. Any drift means the fence is asymmetric (could
    allow writes the read fence wouldn't see)."""
    with seeded_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT tablename, qual, with_check FROM pg_policies "
            "WHERE schemaname='public' AND policyname='cip_tenant_scope'"
        )).fetchall()
    drift = [r.tablename for r in rows if r.qual != r.with_check]
    assert not drift, (
        f"WITH CHECK ≠ USING on: {drift} — predicates must match"
    )


# ── 2. THE NEW GUARANTEE: cross-tenant INSERT is rejected ────────────────


@pytest.mark.requires_postgres
def test_cross_tenant_insert_rejected_by_with_check(
    seeded_engine: Engine,
) -> None:
    """GUC=tenant_A, INSERT row with tenant_id=tenant_B → must raise
    InsufficientPrivilege / new-row-violates-row-level-security.
    Before cip_30 this would silently succeed."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    with session_as_role_and_tenant(seeded_engine, tenant_a) as session:
        with pytest.raises(Exception) as exc_info:
            session.execute(text(
                "INSERT INTO cip_clients ("
                "  id, tenant_id, source_connector, source_id,"
                "  ingestion_batch_id, authority, name, slug"
                ") VALUES ("
                "  gen_random_uuid(), :b, 'test', 'rls-attack-1',"
                "  gen_random_uuid(), 'validated', 'pwn', 'pwn'"
                ")"
            ), {"b": str(tenant_b)})
            session.execute(text("SELECT 1"))  # force statement send
        # Postgres maps this to InsufficientPrivilege (SQLSTATE 42501)
        # with message containing "new row violates row-level security policy".
        underlying = getattr(exc_info.value, "orig", exc_info.value)
        msg = str(underlying).lower()
        assert (
            "row-level security" in msg
            or isinstance(underlying, psycopg.errors.InsufficientPrivilege)
        ), (
            "expected RLS rejection on cross-tenant INSERT; "
            f"got {type(underlying).__name__}: {underlying}"
        )


# ── 3. Within-tenant INSERT still succeeds ────────────────────────────────


@pytest.mark.requires_postgres
def test_within_tenant_insert_still_succeeds(seeded_engine: Engine) -> None:
    """The hardening must not break the happy path. GUC=tenant_A, INSERT
    row with tenant_id=tenant_A → row written cleanly."""
    tenant_a = uuid.uuid4()
    with session_as_role_and_tenant(seeded_engine, tenant_a) as session:
        new_id = session.execute(text(
            "INSERT INTO cip_clients ("
            "  id, tenant_id, source_connector, source_id,"
            "  ingestion_batch_id, authority, name, slug"
            ") VALUES ("
            "  gen_random_uuid(), :a, 'test', 'rls-happy-1',"
            "  gen_random_uuid(), 'validated', 'good', 'good'"
            ") RETURNING id"
        ), {"a": str(tenant_a)}).scalar()
        assert new_id is not None
        # And we can read it back under the same GUC
        seen = session.execute(text(
            "SELECT name FROM cip_clients WHERE id = :i"
        ), {"i": str(new_id)}).scalar()
        assert seen == "good"


# ── 4. UPDATE that rewrites tenant_id is rejected ─────────────────────────


@pytest.mark.requires_postgres
def test_update_rewriting_tenant_id_rejected(seeded_engine: Engine) -> None:
    """An UPDATE that tries to move a row to a different tenant via
    SET tenant_id=<other> must be rejected by WITH CHECK. The USING
    fence already prevents targeting rows from other tenants; this
    test pins the post-write check that rejects moving your OWN row
    to another tenant.

    INSERT + UPDATE happen in the same RLS context — session_as_role_and_tenant
    ROLLBACKs at exit, so cross-context state doesn't persist.
    """
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    with session_as_role_and_tenant(seeded_engine, tenant_a) as session:
        # Seed a legitimate row under tenant_a inside the same RLS context.
        row_id = session.execute(text(
            "INSERT INTO cip_clients ("
            "  id, tenant_id, source_connector, source_id,"
            "  ingestion_batch_id, authority, name, slug"
            ") VALUES ("
            "  gen_random_uuid(), :a, 'test', 'rls-rewrite-1',"
            "  gen_random_uuid(), 'validated', 'orig', 'orig'"
            ") RETURNING id"
        ), {"a": str(tenant_a)}).scalar()
        assert row_id is not None

        # Now try to rewrite its tenant_id to tenant_b. The USING fence
        # lets us SEE the row (it's our own); WITH CHECK rejects the
        # post-write state.
        with pytest.raises(Exception) as exc_info:
            session.execute(text(
                "UPDATE cip_clients SET tenant_id = :b WHERE id = :i"
            ), {"b": str(tenant_b), "i": str(row_id)})
            session.execute(text("SELECT 1"))
        underlying = getattr(exc_info.value, "orig", exc_info.value)
        msg = str(underlying).lower()
        assert (
            "row-level security" in msg
            or isinstance(underlying, psycopg.errors.InsufficientPrivilege)
        ), (
            "expected RLS rejection on UPDATE rewriting tenant_id; "
            f"got {type(underlying).__name__}: {underlying}"
        )
