# foundry: kind=service domain=client-intelligence-platform touches=integration,security
"""SET LOCAL app.current_tenant helper for RLS scoping (M2 §4.4 / §4.5 binding).

D-026 + D-127 require every cip_* read/write to flow through the
``cip_tenant_scope`` RLS policy. The persister + recorder + orchestrator
all call ``apply_tenant_context()`` at the top of every transaction.

v3 (R2-C4): widened the input type to a ``Session | Connection`` union so
both the orchestrator's per-batch Session and the recorder's short-lived
``engine.begin()`` Connection are accepted without per-call-site casts.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

# Module-local alias: NOT a public contract — keep out of __init__ exports.
SessionOrConnection = Session | Connection


def apply_tenant_context(db: SessionOrConnection, tenant_id: UUID) -> None:
    """Set the per-transaction tenant context (``app.current_tenant`` GUC).

    MUST be called inside an open transaction (``SET LOCAL`` scope = txn).
    MUST be called before any ``cip_*`` read or write.

    Per D-026 + D-127, every query inside this txn is automatically filtered
    to ``tenant_id`` by the RLS policy ``cip_tenant_scope`` (cmd=ALL) on
    every ``cip_*`` table.

    v4 (Round-3 panel CRIT-1) — pooler safety:
        ``SET LOCAL`` is bound to the current transaction. As soon as the
        transaction commits or rolls back, the GUC is cleared. This is
        intentional and is what makes ``SET LOCAL`` safe under PgBouncer
        TRANSACTION pooling — the connection is returned to the pool with
        no residual tenant state.

        This is NOT safe under SESSION pooling. M2's deployment target
        (Railway, plain QueuePool, no PgBouncer) is fine. Phase 2 ventures
        deploying behind PgBouncer MUST run in transaction-pooling mode.

    v4 (Round-3 panel) — belt-and-suspenders pattern for venture-side
    deployments wanting auto-applied tenant context::

        # In your engine setup module (NOT M2 framework code):
        from sqlalchemy import event
        from cip.integration_mesh import apply_tenant_context

        @event.listens_for(engine, "begin")
        def _set_tenant(conn):
            tenant_id = your_tenant_resolver()  # request scope, etc.
            if tenant_id is not None:
                apply_tenant_context(conn, tenant_id)

    M2 itself does NOT use this pattern — orchestrator / recorder /
    persister all call ``apply_tenant_context()`` explicitly. The pattern
    exists for Phase 2+ ventures that want it as a backstop. Conformance
    Test 7 (post-commit RLS isolation) catches missed call sites either way.
    """
    # v5.3 PLAN-VS-REALITY RECONCILIATION (Delta 14, 2026-05-05)
    # Plan §4.4: ``text("SET LOCAL app.current_tenant = :tid")`` with bind param.
    # Deployed reality: Postgres ``SET LOCAL`` does NOT support parameterized
    # values — ``SET LOCAL`` accepts only literal values. With a bind, psycopg
    # sends ``SET LOCAL app.current_tenant = $1`` and Postgres rejects:
    # ``syntax error at or near "$1"``.
    # Reconciliation: ``SELECT set_config('app.current_tenant', :tid, true)`` —
    # the Postgres-documented equivalent that DOES accept bind parameters.
    # The third arg ``true`` makes it transaction-local (matches SET LOCAL
    # scope semantics — auto-clears at txn boundary, RLS-safe).
    # Rationale: P-22 / D-123 — Postgres SQL grammar is the authority.
    # Atlas v5.4 TODO: plan §4.4 SQL should use ``set_config(...)``.
    db.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": str(tenant_id)},
    )
