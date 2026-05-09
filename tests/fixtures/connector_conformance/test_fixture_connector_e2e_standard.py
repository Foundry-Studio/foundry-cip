# foundry: kind=test domain=client-intelligence-platform
"""M3 e2e STANDARD — FixtureConnector + FixtureMapper round-trip on the
~1150-row STANDARD corpus through the full sync path against real Postgres.

Capstone validation per M3 §7 dispatch — covers acceptance criteria
#12–#17 at realistic volume:

  #12: STANDARD persists exactly 1150 rows across 5 cip_* tables.
  #13: Second run is a no-op (rows_skipped_unchanged=1150; created/updated/history=0).
  #14: Property registry has ≥22 descriptors covering 5 object types.
  #15: ``is_custom=True`` survives across upsert (M-16 OR-semantics carryover).
  #16: Knowledge hook fires exactly 500 ticket + 100 document KnowledgeTexts.
  #17: Validation contract — mapper-emitted ``tenant_id`` / ``ingestion_batch_id``
       mismatch raises ``KnowledgeMetadataValidationError``.

Risk surface this exercises end-to-end for the first time:
- Δ4 per-table EXTRAS_COLUMN_BY_TABLE on cip_companies/deals/tickets/files
  (M2 only exercised cip_contacts).
- psycopg3 JSONB roundtrip volume (~1150 rows × overflow JSONB).
- Δ8 detect-then-assign machinery × 600 invocations.
- _register_properties_best_effort writing 30 descriptors per run.

M3 Δ4 placement reconciliation (see test_fixture_connector_e2e_smoke
header) — co-located with conformance fixtures rather than under
tests/integration_mesh/ as plan §7 specifies.
"""
from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from cip.integration_mesh import (
    CorpusSize,
    FixtureConnector,
    FixtureMapper,
    KnowledgeText,
    run_sync,
)
from cip.integration_mesh.base import KnowledgeTextMetadata
from cip.integration_mesh.exceptions import (
    KnowledgeMetadataValidationError,
)


def _count(engine: Engine, tenant_id: UUID, table: str) -> int:
    with engine.connect() as conn:
        n = conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        ).scalar()
    return int(n or 0)


def _registry_rows(
    engine: Engine, tenant_id: UUID
) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": str(tenant_id)},
        )
        rows = conn.execute(
            text(
                "SELECT property_name, property_type, storage_location, "
                "column_name, is_custom, cip_table, object_type "
                "FROM cip_connector_property_registry "
                "WHERE connector = 'fixture-connector-v1' "
                "ORDER BY object_type, property_name"
            ),
        ).mappings().all()
    return [dict(r) for r in rows]


# ── Sub-test 1: 1150-row first run + registry coverage ──────────────────


def test_standard_first_run_persists_1150_rows(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """Acceptance #12 + #14 at full STANDARD volume.

    Verifies the 50/200/300/500/100 row distribution lands in the
    expected cip_* tables and the property registry covers all 6
    declared object types (5 active + 1 forward-compat ``note``).
    """
    tenant_id = uuid4()
    state = run_sync(
        FixtureConnector(
            tenant_id=tenant_id, seed=42, size=CorpusSize.STANDARD
        ),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    assert state.status == "success", (
        f"got {state.status}: {state.error_detail}"
    )
    assert state.rows_received == 1150
    assert state.rows_created == 1150
    assert state.rows_updated == 0
    assert state.rows_skipped_unchanged == 0
    assert state.rows_history == 0

    # Acceptance #12: per-table row counts match the corpus shape.
    assert _count(seeded_engine, tenant_id, "cip_companies") == 50
    assert _count(seeded_engine, tenant_id, "cip_contacts") == 200
    assert _count(seeded_engine, tenant_id, "cip_deals") == 300
    assert _count(seeded_engine, tenant_id, "cip_tickets") == 500
    assert _count(seeded_engine, tenant_id, "cip_files") == 100
    total = sum(
        _count(seeded_engine, tenant_id, t)
        for t in (
            "cip_companies",
            "cip_contacts",
            "cip_deals",
            "cip_tickets",
            "cip_files",
        )
    )
    assert total == 1150

    # Acceptance #14: property registry coverage. FixtureConnector ships 30
    # descriptors across 6 object types (5 active + note forward-compat).
    rows = _registry_rows(seeded_engine, tenant_id)
    assert len(rows) >= 22, f"expected ≥22 descriptors, got {len(rows)}"
    object_types = {r["object_type"] for r in rows}
    required = {"company", "contact", "deal", "ticket", "document"}
    assert required.issubset(object_types), (
        f"missing object_types: {required - object_types}"
    )


# ── Sub-test 2: second-run idempotency + is_custom preservation ─────────


def test_standard_second_run_is_no_op_and_is_custom_preserved(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """Acceptance #13 + #15 at STANDARD volume.

    A clean second run with identical fixture data must:
    - Receive 1150 rows but create/update 0 (rows_skipped_unchanged=1150).
    - Write zero history rows (no SCD-2 archive on unchanged rows).
    - Preserve ``is_custom=True`` on company.custom_field_1/2 across the
      registry upsert (M-16 once-true-stays-true OR-semantics).
    """
    tenant_id = uuid4()
    run_sync(
        FixtureConnector(
            tenant_id=tenant_id, seed=42, size=CorpusSize.STANDARD
        ),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    state2 = run_sync(
        FixtureConnector(
            tenant_id=tenant_id, seed=42, size=CorpusSize.STANDARD
        ),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    assert state2.status == "success"
    assert state2.rows_received == 1150
    assert state2.rows_created == 0
    assert state2.rows_updated == 0
    assert state2.rows_skipped_unchanged == 1150
    assert state2.rows_history == 0

    # Final row counts unchanged.
    assert _count(seeded_engine, tenant_id, "cip_contacts") == 200
    assert _count(seeded_engine, tenant_id, "cip_companies") == 50

    # Acceptance #15: custom_field_1 + custom_field_2 still is_custom=True.
    rows = _registry_rows(seeded_engine, tenant_id)
    custom_rows = {
        r["property_name"]: r["is_custom"]
        for r in rows
        if r["property_name"] in {"custom_field_1", "custom_field_2"}
    }
    assert custom_rows.get("custom_field_1") is True, (
        f"custom_field_1.is_custom should be True after re-upsert; "
        f"got {custom_rows}"
    )
    assert custom_rows.get("custom_field_2") is True


# ── Sub-test 3: knowledge hook fires 500 tickets + 100 documents ────────


def test_standard_knowledge_emits_500_tickets_100_docs(
    seeded_engine: Engine,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance #16. Mock ``ingest_texts_noop`` and partition the
    captured calls by source_id prefix:
      - tickets: source_id starts with ``t`` followed by 4 digits (t0001..t0500)
      - documents: source_id starts with ``doc`` (doc0001..doc0100)
    Prefixes are disjoint so simple ``startswith`` partitioning is unambiguous.
    """
    captured_texts: list[KnowledgeText] = []

    def _spy(texts: list[KnowledgeText]) -> None:
        captured_texts.extend(texts)

    monkeypatch.setattr(
        "cip.integration_mesh.orchestrator.ingest_texts_noop", _spy
    )

    tenant_id = uuid4()
    state = run_sync(
        FixtureConnector(
            tenant_id=tenant_id, seed=42, size=CorpusSize.STANDARD
        ),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    assert state.status == "success"

    ticket_count = sum(
        1
        for kt in captured_texts
        if str(kt.metadata["source_id"]).startswith("t")
        and not str(kt.metadata["source_id"]).startswith("doc")
    )
    doc_count = sum(
        1
        for kt in captured_texts
        if str(kt.metadata["source_id"]).startswith("doc")
    )
    assert ticket_count == 500, (
        f"expected 500 ticket KnowledgeTexts, got {ticket_count}"
    )
    assert doc_count == 100, (
        f"expected 100 document KnowledgeTexts, got {doc_count}"
    )
    assert ticket_count + doc_count == len(captured_texts), (
        f"unexpected non-ticket/doc KnowledgeText emissions: "
        f"total={len(captured_texts)}, ticket+doc={ticket_count + doc_count}"
    )

    # Tenant_id finalized by orchestrator on every text.
    assert all(
        kt.metadata.get("tenant_id") == tenant_id for kt in captured_texts
    )


# ── Sub-tests 4 + 5: validation contract (acceptance #17) ───────────────


class _BadTenantMapper(FixtureMapper):
    """Mapper that emits a foreign tenant_id in KnowledgeText metadata.
    Orchestrator's Δ8 detect-then-assign must catch this and raise
    ``KnowledgeMetadataValidationError`` (orchestrator-owned key cannot
    be overridden by the mapper)."""

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        rec_type = record.get("record_type")
        if not isinstance(rec_type, str) or rec_type not in {
            "ticket",
            "document",
        }:
            return []
        body = str(record.get("body") or "").strip()
        if not body:
            return []
        bogus_tenant = uuid4()
        md: dict[str, object] = {
            "source_id": str(record["source_id"]),
            "tenant_id": bogus_tenant,
        }
        return [
            KnowledgeText(
                text=body, metadata=cast(KnowledgeTextMetadata, md)
            )
        ]


class _BadBatchIdMapper(FixtureMapper):
    """Mapper that emits a foreign ingestion_batch_id. Same Δ8
    detect-then-assign guardrail applies."""

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        rec_type = record.get("record_type")
        if not isinstance(rec_type, str) or rec_type not in {
            "ticket",
            "document",
        }:
            return []
        body = str(record.get("body") or "").strip()
        if not body:
            return []
        bogus_batch = uuid4()
        md: dict[str, object] = {
            "source_id": str(record["source_id"]),
            "ingestion_batch_id": bogus_batch,
        }
        return [
            KnowledgeText(
                text=body, metadata=cast(KnowledgeTextMetadata, md)
            )
        ]


def test_standard_validation_contract_tenant_id_mismatch(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """Acceptance #17 (tenant_id half). Mapper emits a foreign tenant_id
    in metadata → orchestrator raises run-fatal validation error.

    Uses COMPACT corpus (115 rows, 50 tickets) so the validation fires
    on the first ticket without paying full STANDARD-volume cost — the
    mismatch path doesn't depend on volume.
    """
    tenant_id = uuid4()
    with pytest.raises(
        KnowledgeMetadataValidationError, match="tenant_id"
    ):
        run_sync(
            FixtureConnector(
                tenant_id=tenant_id, seed=42, size=CorpusSize.COMPACT
            ),
            _BadTenantMapper(),
            seeded_engine,
            tenant_id=tenant_id,
            database_url=database_url,
        )


def test_standard_validation_contract_ingestion_batch_id_mismatch(
    seeded_engine: Engine,
    database_url: str,
) -> None:
    """Acceptance #17 (ingestion_batch_id half). Same guardrail as
    tenant_id; orchestrator owns batch_id and rejects mapper override.
    """
    tenant_id = uuid4()
    with pytest.raises(
        KnowledgeMetadataValidationError, match="ingestion_batch_id"
    ):
        run_sync(
            FixtureConnector(
                tenant_id=tenant_id, seed=42, size=CorpusSize.COMPACT
            ),
            _BadBatchIdMapper(),
            seeded_engine,
            tenant_id=tenant_id,
            database_url=database_url,
        )
