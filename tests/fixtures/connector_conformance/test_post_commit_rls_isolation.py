# foundry: kind=test domain=client-intelligence-platform
"""Conformance test §5.8 — post-commit RLS isolation (v4 Round-3 CRIT-1).

Catches the failure mode that 6/7 expert-panel models flagged as severity-5:
forgetting to call ``apply_tenant_context()`` on any auxiliary connection
path (recorder, knowledge hook, property-registry write, future M5/M6 paths).
``set_config(..., true)`` is transaction-scoped — if it ever survives a
commit, this test catches it.

Test invariant: after every batch commit, the ``app.current_tenant`` GUC
is empty on every freshly-checked-out pool connection. The PATCH-NR-1
checkout listener guarantees this; the test verifies the guarantee holds.
"""
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from cip.integration_mesh import run_sync
from tests.fixtures.connector_conformance.conftest import (
    MockConnector,
    MockMapper,
)
from tests.fixtures.connector_conformance.fixtures.records import (
    CANONICAL_CONTACTS,
    CANONICAL_SCHEMA,
)


def _read_current_tenant_setting(engine: Engine) -> str:
    """Open a fresh pool checkout and read the GUC. PATCH-NR-1 listener
    should have RESET it to empty on checkout.
    """
    with engine.connect() as conn:
        # Don't open a transaction; we want the bare connection state.
        return str(
            conn.execute(
                text(
                    "SELECT current_setting('app.current_tenant', true)"
                )
            ).scalar()
            or ""
        )


@pytest.mark.usefixtures("cleanup_tenant")
def test_guc_empty_after_full_sync_returns(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    """After ``run_sync`` returns normally, fresh checkouts get a cleared GUC."""
    state = run_sync(
        MockConnector(
            tenant_id=tenant_id,
            records=CANONICAL_CONTACTS[:5],
            schema=CANONICAL_SCHEMA,
        ),
        mock_mapper,
        seeded_engine,
        tenant_id=tenant_id,
    )
    assert state.status == "success"
    setting = _read_current_tenant_setting(seeded_engine)
    assert setting == "", (
        f"Stale tenant context leaked: app.current_tenant={setting!r}; "
        f"PATCH-NR-1 checkout listener should have cleared it."
    )


@pytest.mark.usefixtures("cleanup_tenants")
def test_back_to_back_tenant_a_then_b_no_leakage(
    seeded_engine: Engine,
    cleanup_tenants: list[UUID],
    mock_mapper: MockMapper,
) -> None:
    """Run A, then B back-to-back on the same engine; verify B's run sees
    only B's rows (and inherits no stale context from A)."""
    from uuid import uuid4

    tid_a = uuid4()
    tid_b = uuid4()
    cleanup_tenants.extend([tid_a, tid_b])

    state_a = run_sync(
        MockConnector(
            tenant_id=tid_a,
            records=CANONICAL_CONTACTS[:5],
            schema=CANONICAL_SCHEMA,
        ),
        mock_mapper,
        seeded_engine,
        tenant_id=tid_a,
    )
    assert state_a.status == "success"
    # GUC clear between runs.
    assert _read_current_tenant_setting(seeded_engine) == ""

    state_b = run_sync(
        MockConnector(
            tenant_id=tid_b,
            records=CANONICAL_CONTACTS[5:8],  # 3 records
            schema=CANONICAL_SCHEMA,
        ),
        mock_mapper,
        seeded_engine,
        tenant_id=tid_b,
    )
    assert state_b.status == "success"
    assert state_b.rows_received == 3
    assert state_b.rows_created == 3
    # GUC clear after B too.
    assert _read_current_tenant_setting(seeded_engine) == ""


@pytest.mark.usefixtures("cleanup_tenant")
def test_guc_empty_after_run_sync_failed_via_validation_error(
    seeded_engine: Engine,
    tenant_id: UUID,
    mock_mapper: MockMapper,
) -> None:
    """Even when ``run_sync`` raises (e.g., KnowledgeMetadataValidationError
    from a buggy mapper), the GUC must be cleared on subsequent checkouts —
    the per-batch txn rolled back via ``db.begin()`` exception path."""
    from typing import Any, cast

    from cip.integration_mesh import (
        CIPMapperBase,
        CIPRow,
        KnowledgeMetadataValidationError,
        KnowledgeText,
    )

    class TenantOverrideMapper(CIPMapperBase):
        object_type = "contact"
        target_table = "cip_contacts"

        def map(self, record: dict[str, object]) -> Any:
            yield CIPRow(
                target_table="cip_contacts",
                source_id=str(record["id"]),
                fields={"email": str(record.get("email", ""))},
            )

        def overflow_fields(self) -> list[str]:
            return []

        def authority(self) -> Any:
            return "ingested"

        def ingest_as_knowledge(
            self, record: dict[str, object]
        ) -> list[KnowledgeText]:
            from uuid import uuid4

            # Override-detection trip: emit a tenant_id different from binding.
            return [
                KnowledgeText(
                    text="x",
                    metadata=cast(
                        Any,
                        {
                            "source_id": str(record["id"]),
                            "tenant_id": uuid4(),  # WRONG tenant
                        },
                    ),
                )
            ]

    with pytest.raises(KnowledgeMetadataValidationError):
        run_sync(
            MockConnector(
                tenant_id=tenant_id,
                records=CANONICAL_CONTACTS[:1],
                schema=CANONICAL_SCHEMA,
            ),
            TenantOverrideMapper(),
            seeded_engine,
            tenant_id=tenant_id,
        )
    # Even after the run-fatal exception escaped, the GUC is empty on
    # subsequent checkouts.
    assert _read_current_tenant_setting(seeded_engine) == ""
