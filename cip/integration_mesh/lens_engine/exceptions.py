# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Lens engine exception hierarchy (M4 §4.2 binding).

Three exception classes — all inherit from ``ConnectorError`` so callers
that catch broad CIP errors still capture lens-side failures, even though
lens-loading is a CIP-level concern (not strictly a connector boundary issue).
"""
from __future__ import annotations

from cip.integration_mesh.exceptions import ConnectorError


class LensNotFoundError(ConnectorError):
    """No lens row matches ``(tenant_id, view_name)`` under the active RLS context.

    Distinct from connector errors because lens loading is a CIP-level concern,
    not a connector boundary issue. Inherits from ``ConnectorError`` so callers
    that catch broad CIP errors still capture this.
    """


class LensCompilationError(ConnectorError):
    """``filter_config`` can't be compiled to a SQLAlchemy WHERE clause.

    Reasons: unknown field name, unsupported value type, malformed dict shape,
    reserved column name, forbidden operator token, filter size cap exceeded.
    The wrapped detail names the exact field + value for diagnosis.
    """


class LensSecurityError(ConnectorError):
    """Tenant context mismatch detected during lens loading.

    M4 v2 (QC1 Stress [2]): the GUC ``app.current_tenant`` value didn't match
    the ``tenant_id`` argument passed to ``load_lens()``. Indicates one of:
    - A pool checkout returned a connection with stale GUC from a prior tenant.
    - The caller forgot to call ``apply_tenant_context()`` before ``load_lens()``.
    - A concurrent transaction reset the GUC mid-operation.

    Always run-fatal. The caller MUST NOT retry without explicitly re-applying
    tenant context. Caller-side recovery: open a fresh transaction, call
    ``apply_tenant_context()``, then retry ``load_lens()``.
    """
