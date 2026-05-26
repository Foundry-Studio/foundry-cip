# foundry: kind=test domain=client-intelligence-platform
"""Tests for cip_36 — lens_china_deals_history + backfill_ps_deal_history.

Covers PM scope a0aebe06 ASK 6:
  1. Lens shape — lens_china_deals_history exists, exposes SCD-2 columns,
     filters via the JSONB china predicate on cip_deals (current).
  2. GUC isolation — PS GUC → only PS china rows; EC GUC → only EC china
     rows; no GUC → 0.
  3. Grant surface — cip_query_reader + cip_metabase_project_silk can
     SELECT; cip_metabase_role (Foundry-internal Metabase) is NOT granted.
  4. Backfill — EC china history → PS history with rewritten record_id,
     tenant_id, source_connector; preserved valid_from/valid_to/properties;
     idempotent (re-run = 0 inserts).
  5. record_id-miss skip — EC history rows whose source_id has no PS
     cip_deals match are counted in skipped_no_record, not inserted.
  6. Audit — cip_sync_runs gets one PS-tenant row per backfill run.
  7. **Forward-path simulation (CRITICAL gate)** — the dispatch's load-
     bearing concern: PS history is empty today because the mirror has
     only INSERTed. Verify that when PS cip_deals UPDATEs go through
     persister.persist(), `_archive_to_history` writes a new row into
     cip_deals_history — so the backfilled rows + forward-path rows
     compose into a coherent SCD-2 chain.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cip.integration_mesh.base import CIPRow
from cip.integration_mesh.persister import CIPRowPersister
from cip.integration_mesh.scd_differ import SCDDiffer
from scripts.backfill_ps_deal_history import run_backfill

PS_TENANT = UUID("078a37d6-6ae2-4e22-869e-cc08f6cb2787")
EC_TENANT = UUID("dec814db-722a-4730-8e60-51afc4a5dad9")
PS_TENANT_S = str(PS_TENANT)
EC_TENANT_S = str(EC_TENANT)

_METABASE_PS_ROLE = "cip_metabase_project_silk"
_QUERY_READER_ROLE = "cip_query_reader"
_METABASE_ROLE = "cip_metabase_role"
_TEST_PASSWORD_FALLBACK = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105


# ── helpers ──────────────────────────────────────────────────────────────


def _role_engine(seeded_engine: Engine, role: str, pw_env: str) -> Engine:
    """Engine bound to a grantee role. Caller MUST dispose()."""
    url = seeded_engine.url.set(
        username=role,
        password=os.environ.get(pw_env, _TEST_PASSWORD_FALLBACK),
    )
    return create_engine(url, pool_pre_ping=True)


def _set_guc(conn: Any, tenant: UUID) -> None:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"),
        {"t": str(tenant)},
    )


def _insert_deal(
    conn: Any,
    *,
    tenant_id: UUID,
    source_id: str,
    name: str,
    source_str: str,
    amount: float = 1000.0,
    source_connector: str = "hubspot-v1",
) -> UUID:
    """Insert a cip_deals row and return its id."""
    deal_id = uuid4()
    conn.execute(
        text(
            """
            INSERT INTO cip_deals (
                id, tenant_id, client_id, source_connector, source_id,
                ingested_at, refreshed_at, ingestion_batch_id, authority,
                name, amount, properties, created_at, updated_at
            ) VALUES (
                :id, :t, NULL, :sc, :sid,
                NOW(), NOW(), gen_random_uuid(), 'validated',
                :n, :a, CAST(:p AS jsonb), NOW(), NOW()
            )
            """
        ),
        {
            "id": str(deal_id),
            "t": str(tenant_id),
            "sc": source_connector,
            "sid": source_id,
            "n": name,
            "a": amount,
            "p": json.dumps({"source": source_str}),
        },
    )
    return deal_id


def _insert_history(
    conn: Any,
    *,
    tenant_id: UUID,
    record_id: UUID,
    source_id: str,
    valid_from: datetime,
    valid_to: datetime | None,
    name: str,
    amount: float,
    source_connector: str = "hubspot-v1",
    changed_by: str = "test-fixture",
) -> UUID:
    """Insert a cip_deals_history row and return its history_id."""
    hid = uuid4()
    conn.execute(
        text(
            """
            INSERT INTO cip_deals_history (
                history_id, record_id, tenant_id, valid_from, valid_to,
                changed_by, change_reason, source_connector, source_id,
                ingested_at, refreshed_at, previous_version_id,
                ingestion_batch_id, authority, name, amount, properties
            ) VALUES (
                :hid, :rid, :t, :vf, :vt,
                :cb, 'fixture', :sc, :sid,
                :vf, :vf, NULL,
                gen_random_uuid(), 'validated', :n, :a,
                CAST(:p AS jsonb)
            )
            """
        ),
        {
            "hid": str(hid),
            "rid": str(record_id),
            "t": str(tenant_id),
            "vf": valid_from,
            "vt": valid_to,
            "cb": changed_by,
            "sc": source_connector,
            "sid": source_id,
            "n": name,
            "a": amount,
            "p": json.dumps({"source": "China Referral - Tim"}),
        },
    )
    return hid


@pytest.fixture
def hist_seeded(seeded_engine: Engine) -> Engine:
    """Seed:
      EC: 2 china deals (h-CN-1, h-CN-2) + 1 non-china deal (h-NOCHN).
          3 history rows on h-CN-1 (versions a/b/c), 1 on h-CN-2,
          1 on h-NOCHN (must be filtered out by the china predicate).
      PS: 1 mirrored china deal (h-CN-1) → 1 match (1 EC source_id will
          be unmatched: h-CN-2). Models the ~1.5% record_id-miss universe.
    """
    with seeded_engine.begin() as conn:
        # EC current deals
        ec_d1 = _insert_deal(
            conn, tenant_id=EC_TENANT, source_id="h-CN-1",
            name="EC CN One", source_str="China Referral - Tim",
        )
        ec_d2 = _insert_deal(
            conn, tenant_id=EC_TENANT, source_id="h-CN-2",
            name="EC CN Two", source_str="China Referral - Eric",
        )
        ec_dn = _insert_deal(
            conn, tenant_id=EC_TENANT, source_id="h-NOCHN",
            name="EC NonChina", source_str="Hyphen Social",
        )
        # PS current deal (mirror) — only h-CN-1 matches
        _insert_deal(
            conn, tenant_id=PS_TENANT, source_id="h-CN-1",
            name="PS CN One", source_str="China Referral - Tim",
            source_connector="lens-mirror-deals-v1",
        )

        # EC history rows
        base = datetime(2025, 1, 1, tzinfo=UTC)
        _insert_history(
            conn, tenant_id=EC_TENANT, record_id=ec_d1,
            source_id="h-CN-1", valid_from=base,
            valid_to=datetime(2025, 6, 1, tzinfo=UTC),
            name="EC CN One v1", amount=100.0,
        )
        _insert_history(
            conn, tenant_id=EC_TENANT, record_id=ec_d1,
            source_id="h-CN-1", valid_from=datetime(2025, 6, 1, tzinfo=UTC),
            valid_to=datetime(2025, 12, 1, tzinfo=UTC),
            name="EC CN One v2", amount=200.0,
        )
        _insert_history(
            conn, tenant_id=EC_TENANT, record_id=ec_d1,
            source_id="h-CN-1", valid_from=datetime(2025, 12, 1, tzinfo=UTC),
            valid_to=None,
            name="EC CN One v3", amount=300.0,
        )
        _insert_history(
            conn, tenant_id=EC_TENANT, record_id=ec_d2,
            source_id="h-CN-2", valid_from=base,
            valid_to=None,
            name="EC CN Two v1", amount=500.0,
        )
        # Non-china history row — china predicate must filter it out
        _insert_history(
            conn, tenant_id=EC_TENANT, record_id=ec_dn,
            source_id="h-NOCHN", valid_from=base, valid_to=None,
            name="EC NonChina v1", amount=999.0,
        )
    yield seeded_engine
    with seeded_engine.begin() as conn:
        for t in (PS_TENANT, EC_TENANT):
            conn.execute(text("DELETE FROM cip_deals_history WHERE tenant_id=:t"), {"t": str(t)})
            conn.execute(text("DELETE FROM cip_deals WHERE tenant_id=:t"), {"t": str(t)})
            conn.execute(text("DELETE FROM cip_sync_runs WHERE tenant_id=:t"), {"t": str(t)})


# ── 1. Lens shape & exposure ─────────────────────────────────────────────


@pytest.mark.requires_postgres
def test_lens_china_deals_history_view_exists(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        row = conn.execute(text(
            "SELECT viewname FROM pg_views WHERE schemaname='public' "
            "AND viewname='lens_china_deals_history'"
        )).first()
    assert row is not None, "lens_china_deals_history not in pg_views — cip_36 may not have run"


@pytest.mark.requires_postgres
def test_lens_exposes_scd2_columns(seeded_engine: Engine) -> None:
    """The lens must surface valid_from / valid_to / changed_by /
    change_reason + the deal-domain snapshot columns Metabase needs."""
    with seeded_engine.connect() as conn:
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='lens_china_deals_history'"
            )).fetchall()
        }
    required = {
        "history_id", "record_id", "tenant_id",
        "valid_from", "valid_to", "changed_by", "change_reason",
        "source_connector", "source_id",
        "ingested_at", "refreshed_at", "previous_version_id",
        "ingestion_batch_id", "authority",
        "name", "stage", "amount", "currency", "close_date",
        "pipeline", "probability", "tags", "properties",
    }
    missing = required - cols
    assert not missing, f"lens missing columns: {missing}"


# ── 2. Lens body: china predicate + GUC isolation ────────────────────────


@pytest.mark.requires_postgres
def test_lens_under_ec_guc_returns_china_rows_only(hist_seeded: Engine) -> None:
    """Under EC GUC: 3 (h-CN-1 versions) + 1 (h-CN-2) = 4 china history
    rows; h-NOCHN must be excluded by the china predicate."""
    with hist_seeded.connect() as conn:
        _set_guc(conn, EC_TENANT)
        rows = conn.execute(text(
            "SELECT source_id, name FROM lens_china_deals_history "
            "ORDER BY source_id, valid_from"
        )).mappings().all()
    sids = [r["source_id"] for r in rows]
    assert len(rows) == 4, f"expected 4 china history rows, got {len(rows)}: {sids}"
    assert "h-NOCHN" not in sids, "non-china history row leaked into lens"
    assert sids.count("h-CN-1") == 3
    assert sids.count("h-CN-2") == 1


@pytest.mark.requires_postgres
def test_lens_no_guc_returns_zero(hist_seeded: Engine) -> None:
    """The lens fails closed when no GUC is set."""
    with hist_seeded.connect() as conn:
        conn.execute(text("RESET app.current_tenant"))
        n = conn.execute(text("SELECT COUNT(*) FROM lens_china_deals_history")).scalar()
    assert n == 0


@pytest.mark.requires_postgres
def test_lens_isolation_ps_vs_ec(hist_seeded: Engine) -> None:
    """PS GUC sees only PS-tenant history; EC GUC sees only EC-tenant."""
    with hist_seeded.connect() as conn:
        _set_guc(conn, PS_TENANT)
        ps_n = conn.execute(text("SELECT COUNT(*) FROM lens_china_deals_history")).scalar()
        _set_guc(conn, EC_TENANT)
        ec_n = conn.execute(text("SELECT COUNT(*) FROM lens_china_deals_history")).scalar()
    # PS has 0 history rows seeded (the gap the backfill closes)
    assert ps_n == 0, f"PS lens should see 0 history rows before backfill; got {ps_n}"
    assert ec_n == 4


# ── 3. Grant surface ─────────────────────────────────────────────────────


@pytest.mark.requires_postgres
def test_query_reader_can_select_lens(seeded_engine: Engine) -> None:
    role_eng = _role_engine(seeded_engine, _QUERY_READER_ROLE, "CIP_QUERY_READER_DB_PASSWORD")
    try:
        with role_eng.connect() as conn:
            _set_guc(conn, PS_TENANT)
            n = conn.execute(text("SELECT COUNT(*) FROM lens_china_deals_history")).scalar()
            assert isinstance(n, int) and n >= 0
    finally:
        role_eng.dispose()


@pytest.mark.requires_postgres
def test_metabase_ps_role_can_select_lens(seeded_engine: Engine) -> None:
    role_eng = _role_engine(
        seeded_engine, _METABASE_PS_ROLE, "PROJECT_SILK_METABASE_DB_PASSWORD"
    )
    try:
        with role_eng.connect() as conn:
            _set_guc(conn, PS_TENANT)
            n = conn.execute(text("SELECT COUNT(*) FROM lens_china_deals_history")).scalar()
            assert isinstance(n, int) and n >= 0
    finally:
        role_eng.dispose()


@pytest.mark.requires_postgres
def test_metabase_internal_role_cannot_select_lens(seeded_engine: Engine) -> None:
    """cip_metabase_role (Foundry-internal) is NOT granted china lenses —
    mirrors cip_24's policy. China = PS / EcomLever business."""
    role_eng = _role_engine(seeded_engine, _METABASE_ROLE, "METABASE_DB_PASSWORD")
    try:
        with role_eng.connect() as conn:
            with pytest.raises(Exception) as exc_info:
                conn.execute(text("SELECT 1 FROM lens_china_deals_history LIMIT 1"))
            assert isinstance(
                exc_info.value.orig,  # type: ignore[attr-defined]
                psycopg.errors.InsufficientPrivilege,
            )
    finally:
        role_eng.dispose()


# ── 4. Backfill — copies EC → PS with rewritten metadata ─────────────────


@pytest.mark.requires_postgres
def test_backfill_copies_ec_china_history_to_ps(hist_seeded: Engine) -> None:
    s = run_backfill(hist_seeded)
    assert s.ec_history_rows == 4, f"expected 4 EC china history rows; got {s.ec_history_rows}"
    assert s.distinct_source_ids == 2  # h-CN-1 + h-CN-2
    assert s.ps_deals_matched == 1     # only h-CN-1 has a PS mirror deal
    assert s.ps_deals_unmatched == 1   # h-CN-2
    # 3 versions of h-CN-1 inserted; 1 row of h-CN-2 skipped (no PS deal)
    assert s.rows_inserted == 3
    assert s.rows_skipped_no_record == 1
    assert s.rows_skipped_existing == 0

    # Verify PS history rows have the expected shape.
    with hist_seeded.connect() as conn:
        _set_guc(conn, PS_TENANT)
        rows = conn.execute(text(
            "SELECT source_id, name, amount, source_connector, changed_by, "
            "change_reason, ingestion_batch_id, valid_from, valid_to, properties "
            "FROM cip_deals_history WHERE tenant_id=:t ORDER BY valid_from"
        ), {"t": PS_TENANT_S}).mappings().all()
        # PS cip_deals.id for h-CN-1 — record_id should resolve to this.
        ps_deal_id = conn.execute(text(
            "SELECT id FROM cip_deals WHERE tenant_id=:t AND source_id='h-CN-1'"
        ), {"t": PS_TENANT_S}).scalar()
        ps_record_ids = {
            r[0] for r in conn.execute(text(
                "SELECT DISTINCT record_id FROM cip_deals_history WHERE tenant_id=:t"
            ), {"t": PS_TENANT_S}).fetchall()
        }

    assert len(rows) == 3
    for r in rows:
        assert r["source_id"] == "h-CN-1"
        assert r["source_connector"] == "lens-mirror-deals-v1"  # rewritten
        assert r["changed_by"] == "atlas-ask6-backfill"
        assert r["change_reason"] == "ASK6 historical backfill from ecomlever"
        assert str(r["ingestion_batch_id"]) == s.batch_id
        # properties preserved verbatim (china source string)
        assert "China Referral" in r["properties"]["source"]

    # Domain values preserved (amount, name)
    amounts = [float(r["amount"]) for r in rows]
    assert sorted(amounts) == [100.0, 200.0, 300.0]
    names = [r["name"] for r in rows]
    assert sorted(names) == ["EC CN One v1", "EC CN One v2", "EC CN One v3"]

    # record_id resolved to the PS cip_deal, not the EC one
    assert ps_record_ids == {ps_deal_id}


@pytest.mark.requires_postgres
def test_backfill_is_idempotent(hist_seeded: Engine) -> None:
    """Re-run = 0 new inserts, same skip counts. Idempotency via the
    NOT EXISTS clause on (tenant_id, source_id, valid_from)."""
    s1 = run_backfill(hist_seeded)
    assert s1.rows_inserted == 3

    s2 = run_backfill(hist_seeded)
    assert s2.rows_inserted == 0
    assert s2.rows_skipped_existing == 3
    assert s2.rows_skipped_no_record == 1  # still skips h-CN-2

    # PS history still has exactly 3 rows.
    with hist_seeded.connect() as conn:
        n = conn.execute(text(
            "SELECT COUNT(*) FROM cip_deals_history WHERE tenant_id=:t"
        ), {"t": PS_TENANT_S}).scalar()
    assert n == 3, f"expected exactly 3 PS history rows after re-run; got {n}"


@pytest.mark.requires_postgres
def test_backfill_writes_audit_row(hist_seeded: Engine) -> None:
    """cip_sync_runs gets a PS-tenant row with sync_mode=full and the
    same batch_id as the inserted history rows."""
    s = run_backfill(hist_seeded)
    with hist_seeded.connect() as conn:
        row = conn.execute(text(
            "SELECT connector_id, sync_mode, status, rows_history, "
            "rows_skipped, batch_id, tenant_id "
            "FROM cip_sync_runs WHERE batch_id = :b"
        ), {"b": s.batch_id}).mappings().first()
    assert row is not None
    assert row["connector_id"] == "lens-mirror-deals-v1-backfill"
    assert row["sync_mode"] == "full"
    assert row["status"] == "success"
    assert row["rows_history"] == 3
    assert row["rows_skipped"] == 1  # 1 record_id miss + 0 existing
    assert str(row["tenant_id"]) == PS_TENANT_S


@pytest.mark.requires_postgres
def test_backfill_dry_run_writes_nothing(hist_seeded: Engine) -> None:
    """--dry-run reports the would-be result without touching the DB."""
    s = run_backfill(hist_seeded, dry_run=True)
    # No inserts performed; skipped_no_record IS counted (we know it from
    # the lookup pass alone).
    assert s.rows_inserted == 0
    assert s.rows_skipped_no_record == 1
    assert s.ps_deals_matched == 1
    with hist_seeded.connect() as conn:
        n = conn.execute(text(
            "SELECT COUNT(*) FROM cip_deals_history WHERE tenant_id=:t"
        ), {"t": PS_TENANT_S}).scalar()
    assert n == 0, "dry-run wrote rows; should have been a no-op"


# ── 5. Forward-path simulation (load-bearing) ────────────────────────────


@pytest.mark.requires_postgres
def test_forward_path_persister_archives_ps_deal_update(hist_seeded: Engine) -> None:
    """The dispatch's load-bearing concern: PS cip_deals_history is empty
    today only because the mirror has only INSERTed so far. When a real
    UPDATE flows through `persister.persist()`, `_archive_to_history`
    fires and writes a new cip_deals_history row.

    Wire it up end-to-end: PS deal currently 'PS CN One' / amount 1000 —
    push a CIPRow with a changed amount/name and assert a new history
    row materializes under PS GUC.
    """
    # Backfill the historical rows first, so we're verifying the COMPOSITION
    # (backfill + forward-path) — not just an isolated archive.
    run_backfill(hist_seeded)
    with hist_seeded.connect() as conn:
        _set_guc(conn, PS_TENANT)
        before = conn.execute(text(
            "SELECT COUNT(*) FROM cip_deals_history WHERE tenant_id=:t"
        ), {"t": PS_TENANT_S}).scalar()
    assert before == 3  # the backfilled rows

    # Forward-path: persister.persist() against the existing PS deal.
    # CIPRowPersister expects a Session (has get_bind() for lazy reflection),
    # so we open one off the engine — same shape as orchestrator.run_sync().
    differ = SCDDiffer()
    with Session(hist_seeded, autoflush=False, expire_on_commit=False) as db, db.begin():
        _set_guc(db, PS_TENANT)
        persister = CIPRowPersister(db, differ)
        row = CIPRow(
            target_table="cip_deals",
            source_id="h-CN-1",
            fields={
                "name": "PS CN One — updated",
                "amount": 2500.0,
            },
        )
        result = persister.persist(
            row,
            tenant_id=PS_TENANT,
            connector_id="lens-mirror-deals-v1",
            batch_id=uuid4(),
        )
    assert result.updated == 1, "persister should report 1 update on a changed deal"
    assert result.history == 1, "persister should archive 1 row into cip_deals_history"

    with hist_seeded.connect() as conn:
        _set_guc(conn, PS_TENANT)
        after = conn.execute(text(
            "SELECT COUNT(*) FROM cip_deals_history WHERE tenant_id=:t"
        ), {"t": PS_TENANT_S}).scalar()
        # The archive row captures the PRIOR state — name='PS CN One',
        # changed_by='lens-mirror-deals-v1', NOT 'atlas-ask6-backfill'.
        archived = conn.execute(text(
            "SELECT name, amount, changed_by FROM cip_deals_history "
            "WHERE tenant_id=:t AND changed_by='lens-mirror-deals-v1' "
            "ORDER BY valid_from DESC LIMIT 1"
        ), {"t": PS_TENANT_S}).mappings().first()
    assert after == 4, f"expected 1 new history row from forward path (3→4); got {after}"
    assert archived is not None, "forward-path archive row missing"
    assert archived["name"] == "PS CN One"
    assert float(archived["amount"]) == 1000.0
    assert archived["changed_by"] == "lens-mirror-deals-v1"
