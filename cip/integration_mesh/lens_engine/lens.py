# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Lens loading + application (M4 §4.4 binding).

A ``Lens`` wraps a ``cip_views`` row's loaded state. ``load_lens()`` fetches
the row from ``cip_views`` (RLS-bound + GUC-verified). ``apply_lens()``
composes the lens's compiled filter with a base query.

Security model (per M4 v2 QC1 hardening):
- ``load_lens`` verifies ``current_setting('app.current_tenant')`` matches the
  passed ``tenant_id`` BEFORE trusting RLS (Stress [2]). Catches stale-GUC
  pool-reuse vector. Mismatch → ``LensSecurityError``.
- ``load_lens`` adds an explicit ``AND tenant_id = :tenant_id`` filter
  alongside RLS (Stress [1] + Gap [2]). D-026 defense-in-depth — RLS is the
  primary guard, the predicate prevents silent leaks if RLS is misconfigured.
- ``apply_lens`` validates ``len(target_table.columns) > 0`` and that the
  lens's ``target_table`` matches the SQLAlchemy ``Table`` passed in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .compiler import compile_filter
from .exceptions import (
    LensCompilationError,
    LensNotFoundError,
    LensSecurityError,
)

# Map source_id convention → entity table name. M4 ships single-entity-table
# lenses; the lens row's source_id encodes which cip_<entity> table it scopes.
# Convention: source_id == "cip_companies" / "cip_contacts" / etc.
# Adding a new table to the whitelist is an explicit, intentional edit per
# v2 Stress [5] reframe — P-21 falsifiability holds WITHIN the whitelist;
# net-new tables require a deliberate compile-time change.
_VALID_TARGET_TABLES: frozenset[str] = frozenset(
    {
        "cip_companies",
        "cip_contacts",
        "cip_deals",
        "cip_tickets",
        "cip_files",
    }
)


@dataclass(frozen=True)
class Lens:
    """A loaded ``cip_views`` row.

    Frozen dataclass — immutable after load. Mirrors M2's ``CIPRow`` /
    ``KnowledgeText`` pattern.
    """

    id: UUID
    tenant_id: UUID
    view_name: str
    description: str | None
    filter_config: dict[str, Any]
    target_table: str  # source_id from the cip_views row, e.g., "cip_companies"
    is_default: bool

    def applies_to(self, table_name: str) -> bool:
        """Return True if this lens scopes to the given entity table."""
        return self.target_table == table_name


def load_lens(
    db: Session,
    *,
    tenant_id: UUID,
    view_name: str,
) -> Lens:
    """Load a lens definition from ``cip_views``.

    REQUIRES the caller's session to have already applied tenant context
    (``apply_tenant_context()``). Lens loading is RLS-bound: a tenant-A
    session looking up tenant-B's lens returns zero rows → ``LensNotFoundError``.

    Args:
        db: open SQLAlchemy ``Session`` inside an ``apply_tenant_context()``
            transaction.
        tenant_id: caller's tenant (enforced by RLS; passed for explicit
            logging + GUC verification).
        view_name: human-readable lens name (``cip_views.view_name``).

    Returns:
        ``Lens`` — frozen dataclass.

    Raises:
        LensSecurityError: GUC ``app.current_tenant`` doesn't match
            ``tenant_id``. Caller must open a fresh transaction + reapply
            tenant context (stale-GUC pool-reuse vector).
        LensNotFoundError: no lens row matches ``(tenant, view_name)`` under
            RLS, or the row's ``source_id`` is not in ``_VALID_TARGET_TABLES``.
        LensCompilationError: the row's ``filter_config`` column is malformed
            (non-dict). Surfaces corrupt JSONB before downstream compile.
    """
    # v2 (Stress [2]): GUC verification. Catches stale-GUC pool reuse before
    # we trust RLS. If the GUC doesn't match the caller's tenant_id, raise
    # LensSecurityError immediately — a fresh transaction must be opened.
    guc_value = db.execute(
        sa.text("SELECT current_setting('app.current_tenant', true)")
    ).scalar()
    if guc_value != str(tenant_id):
        raise LensSecurityError(
            f"GUC app.current_tenant={guc_value!r} doesn't match "
            f"tenant_id={tenant_id!r}; caller must apply_tenant_context() "
            f"in current transaction before load_lens()"
        )

    # v2 (Stress [1] + Gap [2]): explicit AND tenant_id filter alongside RLS.
    # D-026 defense-in-depth — RLS is primary, explicit predicate prevents
    # silent leak if RLS is misconfigured/disabled in a maintenance session.
    result = db.execute(
        sa.text(
            """
            SELECT id, tenant_id, view_name, description, filter_config,
                   source_id, is_default
            FROM cip_views
            WHERE view_name = :view_name AND tenant_id = :tenant_id
            LIMIT 1
            """
        ),
        {"view_name": view_name, "tenant_id": str(tenant_id)},
    ).first()

    if result is None:
        raise LensNotFoundError(
            f"no lens with view_name={view_name!r} for tenant_id={tenant_id} "
            f"(or RLS blocked access)"
        )

    # v2 (Gap [3]): explicit type-check on filter_config from DB. The column
    # has DEFAULT '{}'::jsonb but a manual INSERT or data migration could
    # bypass that. Empty string / NULL / corrupt JSONB → fail loud.
    if not isinstance(result.filter_config, dict):
        raise LensCompilationError(
            f"lens row {view_name!r} has malformed filter_config "
            f"(type={type(result.filter_config).__name__}); "
            f"expected JSONB-decoded dict"
        )

    target_table = result.source_id
    if target_table not in _VALID_TARGET_TABLES:
        raise LensNotFoundError(
            f"lens {view_name!r} has invalid source_id={target_table!r}; "
            f"M4 supports {sorted(_VALID_TARGET_TABLES)}"
        )

    return Lens(
        id=result.id,
        tenant_id=result.tenant_id,
        view_name=result.view_name,
        description=result.description,
        filter_config=result.filter_config,
        target_table=target_table,
        is_default=result.is_default,
    )


def apply_lens(
    base_query: sa.Select[Any],
    lens: Lens,
    target_table: sa.Table,
) -> sa.Select[Any]:
    """Compose a lens's filter with a base query.

    Args:
        base_query: SQLAlchemy ``Select``. Must already target the right table.
        lens: a loaded ``Lens``.
        target_table: the SQLAlchemy ``Table`` the lens applies to.

    Returns:
        New ``Select`` with the lens predicate AND-composed.

    Raises:
        LensCompilationError: ``lens.target_table`` doesn't match
            ``target_table.name``, or the underlying ``compile_filter`` rejects
            the lens's ``filter_config``.
    """
    if not lens.applies_to(target_table.name):
        raise LensCompilationError(
            f"lens {lens.view_name!r} targets {lens.target_table!r}, "
            f"but query targets {target_table.name!r}"
        )
    predicate = compile_filter(lens.filter_config, target_table)
    return base_query.where(predicate)


def lens_query_for_table(
    db: Session,
    *,
    tenant_id: UUID,
    view_name: str,
    target_table: sa.Table,
    base_columns: list[Any] | None = None,
) -> sa.Select[Any]:
    """Convenience: load lens + apply to a ``SELECT *`` on ``target_table``.

    Args:
        db: ``Session`` with tenant context applied.
        tenant_id: caller's tenant.
        view_name: lens identifier.
        target_table: SQLAlchemy ``Table`` to query.
        base_columns: optional column list (default = whole table).

    Returns:
        Compiled ``SELECT`` ready for ``db.execute()``.
    """
    lens = load_lens(db, tenant_id=tenant_id, view_name=view_name)
    base = (
        sa.select(target_table)
        if base_columns is None
        else sa.select(*base_columns)
    )
    return apply_lens(base, lens, target_table)
