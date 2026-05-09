# foundry: kind=test domain=client-intelligence-platform
"""M4 lens-loading integration tests (M4 §5.2 binding).

Real Postgres testcontainer. Exercises:
- Public-API import surface (acceptance #12).
- ``load_lens`` happy path with all 7 dataclass fields populated (acceptance #5).
- RLS-bound cross-tenant blocking (acceptance #16) — tenant-A's lens hidden
  from tenant-B context, surfaces as ``LensNotFoundError``.
- Invalid ``source_id`` (not in ``_VALID_TARGET_TABLES``) → ``LensNotFoundError``.
- GUC mismatch → ``LensSecurityError`` (acceptance #24, M4 v2 Stress [2]).
- Exception inheritance from ``ConnectorError`` (Gap [6]).
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cip.integration_mesh import (
    ConnectorError,
    Lens,
    LensNotFoundError,
    LensSecurityError,
    apply_lens,
    compile_filter,
    lens_query_for_table,
    load_lens,
)
from cip.integration_mesh.tenant_context import apply_tenant_context
from tests.integration_mesh.conftest import (
    LENS_A_FILTER_CONFIG,
    LENS_B_FILTER_CONFIG,
    seed_lens,
)

# ── §5.2.1 — public-API surface ────────────────────────────────────────────


def test_public_api() -> None:
    """All 8 lens-engine names are importable from ``cip.integration_mesh``."""
    # Imports above already prove this; assert truthiness as a smoke check.
    assert Lens is not None
    assert load_lens is not None
    assert apply_lens is not None
    assert lens_query_for_table is not None
    assert compile_filter is not None
    assert LensNotFoundError is not None
    assert LensSecurityError is not None
    # The compiler-side ``LensCompilationError`` is exported alongside.
    from cip.integration_mesh import LensCompilationError  # noqa: PLC0415
    assert LensCompilationError is not None


# ── §5.2.2 — load_lens happy path ─────────────────────────────────────────


@pytest.mark.usefixtures("clean_lens_tables")
def test_load_lens_happy_path(seeded_engine: Engine) -> None:
    """Seed a lens, load it, all 7 dataclass fields populated correctly."""
    tenant_id = uuid4()
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        seeded_id = seed_lens(
            db,
            tenant_id=tenant_id,
            view_name="all_companies",
            filter_config=LENS_A_FILTER_CONFIG,
            target_table="cip_companies",
            description="Lens-A: all rows.",
            is_default=False,
        )

    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        lens = load_lens(
            db, tenant_id=tenant_id, view_name="all_companies"
        )

    assert isinstance(lens, Lens)
    assert lens.id == seeded_id
    assert lens.tenant_id == tenant_id
    assert lens.view_name == "all_companies"
    assert lens.description == "Lens-A: all rows."
    assert lens.filter_config == LENS_A_FILTER_CONFIG
    assert lens.target_table == "cip_companies"
    assert lens.is_default is False


# ── §5.2.3 — missing view_name ─────────────────────────────────────────────


@pytest.mark.usefixtures("clean_lens_tables")
def test_load_lens_missing_view_name_raises_lens_not_found_error(
    seeded_engine: Engine,
) -> None:
    tenant_id = uuid4()
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        with pytest.raises(
            LensNotFoundError, match="no lens with view_name"
        ):
            load_lens(db, tenant_id=tenant_id, view_name="nonexistent_lens")


# ── §5.2.4 — RLS-bound cross-tenant blocking (acceptance #16) ──────────────


@pytest.mark.usefixtures("clean_lens_tables")
def test_load_lens_cross_tenant_blocked_by_rls(
    seeded_engine: Engine,
) -> None:
    """Seed a lens for tenant A. Query with tenant B context → RLS hides
    the row → ``LensNotFoundError``. Acceptance #16."""
    tenant_a = uuid4()
    tenant_b = uuid4()

    # Seed under tenant A
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_a)
        seed_lens(
            db,
            tenant_id=tenant_a,
            view_name="tenant_a_lens",
            filter_config=LENS_B_FILTER_CONFIG,
        )

    # Query under tenant B — RLS hides tenant-A row.
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_b)
        with pytest.raises(
            LensNotFoundError, match="RLS blocked access|no lens"
        ):
            load_lens(db, tenant_id=tenant_b, view_name="tenant_a_lens")


# ── §5.2.5 — invalid source_id (not in whitelist) ─────────────────────────


@pytest.mark.usefixtures("clean_lens_tables")
def test_load_lens_invalid_source_id_raises(seeded_engine: Engine) -> None:
    """A lens row with ``source_id`` not in ``_VALID_TARGET_TABLES`` →
    ``LensNotFoundError``. Defends against rogue lens definitions."""
    tenant_id = uuid4()
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        seed_lens(
            db,
            tenant_id=tenant_id,
            view_name="bad_lens",
            filter_config={},
            target_table="not_a_real_table",
        )

    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        with pytest.raises(
            LensNotFoundError, match="invalid source_id"
        ):
            load_lens(db, tenant_id=tenant_id, view_name="bad_lens")


# ── §5.2.6 — GUC mismatch → LensSecurityError (acceptance #24) ────────────


@pytest.mark.usefixtures("clean_lens_tables")
def test_load_lens_raises_lens_security_error_on_guc_mismatch(
    seeded_engine: Engine,
) -> None:
    """Caller forgot to call ``apply_tenant_context()`` first. The GUC is
    empty (or stale from another tenant). ``load_lens`` detects the
    mismatch and raises ``LensSecurityError``. Acceptance #24."""
    tenant_id = uuid4()
    # No apply_tenant_context! GUC stays at the empty-string default the
    # checkout listener resets to.
    with Session(seeded_engine, autoflush=False) as db, db.begin(), pytest.raises(
        LensSecurityError, match="doesn't match tenant_id"
    ):
        load_lens(
            db, tenant_id=tenant_id, view_name="any_view"
        )


@pytest.mark.usefixtures("clean_lens_tables")
def test_load_lens_raises_lens_security_error_on_stale_guc(
    seeded_engine: Engine,
) -> None:
    """Pool-reuse vector: GUC carries tenant-A's value but caller passes
    tenant-B. Mismatch → LensSecurityError before RLS is trusted."""
    tenant_a = uuid4()
    tenant_b = uuid4()
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_a)
        # Caller passes tenant_b but GUC is set to tenant_a → mismatch.
        with pytest.raises(
            LensSecurityError, match="doesn't match tenant_id"
        ):
            load_lens(db, tenant_id=tenant_b, view_name="any_view")


# ── Exception inheritance (Gap [6]) ────────────────────────────────────────


def test_lens_not_found_error_inherits_connector_error() -> None:
    assert issubclass(LensNotFoundError, ConnectorError)


def test_lens_security_error_inherits_connector_error() -> None:
    assert issubclass(LensSecurityError, ConnectorError)


# ── Sanity: UUID typing on returned dataclass ──────────────────────────────


@pytest.mark.usefixtures("clean_lens_tables")
def test_load_lens_returns_uuid_typed_ids(seeded_engine: Engine) -> None:
    """``Lens.id`` and ``Lens.tenant_id`` come back as ``UUID`` instances
    (not strings) — psycopg3 + SQLAlchemy 2.0 native UUID type."""
    tenant_id = uuid4()
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        seed_lens(
            db,
            tenant_id=tenant_id,
            view_name="typed_lens",
            filter_config={},
        )

    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        lens = load_lens(
            db, tenant_id=tenant_id, view_name="typed_lens"
        )

    assert isinstance(lens.id, UUID)
    assert isinstance(lens.tenant_id, UUID)


# Silence unused-import warning from the conftest helper visible at module scope
_ = sa
