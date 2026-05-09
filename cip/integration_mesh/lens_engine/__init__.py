# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Lens Engine — P-21 Multi-Lens-by-Default enforcement for CIP data surfaces.

A lens is a row in ``cip_views`` with a ``filter_config`` JSONB. The engine
loads the row, compiles ``filter_config`` to a SQLAlchemy WHERE predicate,
and applies it to a base query targeting one of the ``cip_<entity>`` tables.

Lens application is RLS-native: queries run inside an
``apply_tenant_context()`` transaction. Lens filtering is AND-composed on
top of tenant scoping; never in place of it.

Usage::

    from cip.integration_mesh.lens_engine import (
        Lens, load_lens, apply_lens, lens_query_for_table,
    )

    with Session(engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        lens = load_lens(db, tenant_id=tenant_id, view_name="eu_west_companies")
        base = sa.select(cip_companies)
        filtered = apply_lens(base, lens, cip_companies)
        rows = db.execute(filtered).all()
"""
from .compiler import compile_filter
from .exceptions import (
    LensCompilationError,
    LensNotFoundError,
    LensSecurityError,
)
from .lens import Lens, apply_lens, lens_query_for_table, load_lens

__all__ = [
    "Lens",
    "LensCompilationError",
    "LensNotFoundError",
    "LensSecurityError",
    "apply_lens",
    "compile_filter",
    "lens_query_for_table",
    "load_lens",
]
