# foundry: kind=test domain=client-intelligence-platform
"""Tests for cip_29 — lens_deals_history + Metabase grants.

Modeled on test_cip_10_history_lens_view.py. Verifies the view exists,
both Metabase roles can SELECT it, P-21 enforcement holds (raw history
table denied), and cross-tenant isolation via GUC works.

Per PM scope a0aebe06 ASK 1.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_METABASE_ROLE = "cip_metabase_role"
_METABASE_PS_ROLE = "cip_metabase_project_silk"
_TEST_PASSWORD_FALLBACK = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105


def _role_engine(seeded_engine: Engine, role: str, pw_env: str) -> Engine:
    """Engine bound to a Metabase role. Caller MUST dispose()."""
    url = seeded_engine.url.set(
        username=role,
        password=os.environ.get(pw_env, _TEST_PASSWORD_FALLBACK),
    )
    return create_engine(url, pool_pre_ping=True)


# ── 1. View exists in pg_views ────────────────────────────────────────────

@pytest.mark.requires_postgres
def test_lens_deals_history_view_exists(seeded_engine: Engine) -> None:
    """cip_29 migration creates lens_deals_history in public schema."""
    with seeded_engine.connect() as conn:
        row = conn.execute(text(
            "SELECT viewname FROM pg_views "
            "WHERE schemaname = 'public' AND viewname = 'lens_deals_history'"
        )).first()
    assert row is not None, (
        "lens_deals_history view not found in pg_views — cip_29 may not have run"
    )


# ── 2. Both Metabase roles can SELECT the view (under a GUC tenant) ──────

@pytest.mark.requires_postgres
def test_metabase_role_can_select_lens_deals_history(
    seeded_engine: Engine,
) -> None:
    """cip_metabase_role MUST have SELECT on lens_deals_history.
    Empty result is fine — this test only proves access, not data."""
    tenant_id = uuid.uuid4()
    role_eng = _role_engine(seeded_engine, _METABASE_ROLE, "METABASE_DB_PASSWORD")
    try:
        with role_eng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(tenant_id)},
            )
            n = conn.execute(text("SELECT COUNT(*) FROM lens_deals_history")).scalar()
            assert isinstance(n, int) and n >= 0
    finally:
        role_eng.dispose()


@pytest.mark.requires_postgres
def test_metabase_ps_role_can_select_lens_deals_history(
    seeded_engine: Engine,
) -> None:
    """cip_metabase_project_silk MUST have SELECT on lens_deals_history
    (this is the load-bearing grant for ASK 1 — the PS Metabase tenant
    is the actual consumer)."""
    tenant_id = uuid.uuid4()
    role_eng = _role_engine(
        seeded_engine, _METABASE_PS_ROLE, "PROJECT_SILK_METABASE_DB_PASSWORD"
    )
    try:
        with role_eng.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, false)"),
                {"t": str(tenant_id)},
            )
            n = conn.execute(text("SELECT COUNT(*) FROM lens_deals_history")).scalar()
            assert isinstance(n, int) and n >= 0
    finally:
        role_eng.dispose()


# ── 3. P-21 enforcement — raw history table is NOT readable ──────────────

@pytest.mark.requires_postgres
def test_metabase_role_cannot_select_raw_cip_deals_history(
    seeded_engine: Engine,
) -> None:
    """The whole point of the lens layer: cip_metabase_role MUST NOT have
    SELECT on the raw cip_deals_history table. Only the lens_* surface
    is reachable. Mirrors cip_10's M5 falsifiability test."""
    role_eng = _role_engine(seeded_engine, _METABASE_ROLE, "METABASE_DB_PASSWORD")
    try:
        with role_eng.connect() as conn:
            with pytest.raises(Exception) as exc_info:
                conn.execute(text("SELECT 1 FROM cip_deals_history LIMIT 1"))
            assert isinstance(
                exc_info.value.orig,  # type: ignore[attr-defined]
                psycopg.errors.InsufficientPrivilege,
            ), (
                "expected permission denied on cip_deals_history; "
                f"got {type(exc_info.value.orig).__name__}"  # type: ignore[attr-defined]
            )
    finally:
        role_eng.dispose()


@pytest.mark.requires_postgres
def test_metabase_ps_role_cannot_select_raw_cip_deals_history(
    seeded_engine: Engine,
) -> None:
    """Same P-21 check for the PS Metabase role."""
    role_eng = _role_engine(
        seeded_engine, _METABASE_PS_ROLE, "PROJECT_SILK_METABASE_DB_PASSWORD"
    )
    try:
        with role_eng.connect() as conn:
            with pytest.raises(Exception) as exc_info:
                conn.execute(text("SELECT 1 FROM cip_deals_history LIMIT 1"))
            assert isinstance(
                exc_info.value.orig,  # type: ignore[attr-defined]
                psycopg.errors.InsufficientPrivilege,
            )
    finally:
        role_eng.dispose()


# ── 4. GUC isolation — no GUC = zero rows visible ────────────────────────

@pytest.mark.requires_postgres
def test_lens_returns_zero_rows_without_guc(seeded_engine: Engine) -> None:
    """The view body filters on the GUC. Without SET LOCAL the predicate
    NULLIF(...)::uuid evaluates to NULL and excludes every row — fail-closed."""
    role_eng = _role_engine(seeded_engine, _METABASE_ROLE, "METABASE_DB_PASSWORD")
    try:
        with role_eng.connect() as conn:
            # No app.current_tenant set
            n = conn.execute(text("SELECT COUNT(*) FROM lens_deals_history")).scalar()
            assert n == 0, f"expected 0 rows without GUC; got {n}"
    finally:
        role_eng.dispose()


# ── 5. View body exposes the SCD-2 history columns ────────────────────────

@pytest.mark.requires_postgres
def test_lens_exposes_history_specific_columns(seeded_engine: Engine) -> None:
    """The lens is SELECT * from cip_deals_history, so it must surface
    valid_from / valid_to / changed_by / change_reason / amount — the
    SCD-2 columns Metabase needs for period-over-period revenue deltas
    (ASK 1's load-bearing point).
    """
    with seeded_engine.connect() as conn:
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'lens_deals_history'"
            )).fetchall()
        }
    required = {
        "tenant_id", "valid_from", "valid_to", "changed_by", "change_reason",
        "source_connector", "source_id",
        "name", "stage", "amount", "currency", "close_date",
        "properties",
    }
    missing = required - cols
    assert not missing, f"lens_deals_history missing expected columns: {missing}"
