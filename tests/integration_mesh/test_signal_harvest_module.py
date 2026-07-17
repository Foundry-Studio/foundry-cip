# foundry: kind=test domain=client-intelligence-platform
"""Behavioural tests for cip.integration_mesh.sync.signal_harvest.run_signal_harvest.

Review M9 lifted the PS nationality-signal harvester from scripts/ into the package so the FAS
scheduler can import it. These tests pin the three properties that lift has to preserve or add:

  (a) IDEMPOTENT — a second run inserts zero new signals (ON CONFLICT DO NOTHING).
  (b) seen_in_* MAINTENANCE (review C2) — a stale cache flag is corrected and counted, and it runs
      BEFORE the harvest that depends on it (the eric_sheet signal is emitted on the first run only
      because the pre-step flipped seen_in_eric_sheets to its truth first).
  (c) HEARTBEAT (review M9) — each run records a cip_sync_runs row with connector_id
      'ps-signal-harvest-v1' so a scheduled harvest is observable.

seeded_engine runs `alembic upgrade head` against a testcontainer; its default user is a BYPASSRLS
superuser, so every query here is scoped by the harvester's own explicit `tenant_id = :t` predicates
(not RLS) — which is exactly why the harvest filters that way.
"""
from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from cip.integration_mesh.sync.signal_harvest import CONNECTOR_ID, run_signal_harvest

# A dedicated synthetic tenant so seeded rows never collide with other suites.
# NB: ps_brands.wayward_brand_id is GLOBALLY unique (the signals FK references it), so the brand
# ids must be unique across the whole session too — an 'a7'-prefixed namespace avoids the plain
# ...b1/...b2 ids that neighbouring suites (e.g. test_cip_106) already squat on.
TENANT = "00000000-0000-0000-0000-0000000000a7"
BRAND_EXCLUDED = "a7b10000-0000-4000-8000-000000000001"  # on the exclusion list
BRAND_ERIC = "a7b20000-0000-4000-8000-000000000002"      # in Eric's sheet


def _seed(engine: Engine) -> None:
    """Two brands: one on the frozen exclusion list, one in Eric's sheet.

    The source rows (brands, excluded, observation) are seeded IDEMPOTENTLY and never deleted:
    ps_brand_observations is append-only (a trigger blocks DELETE/UPDATE) AND it has an FK onto
    ps_brands, which transitively pins its brand. So per-test isolation resets the DENORMALISED
    seen_in_* flags to their STALE default (false) here instead — that is the drift the maintenance
    step exists to repair, and it is what makes rows_corrected deterministic each run."""
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": TENANT})
        for bid, nm in ((BRAND_EXCLUDED, "ExcludedBrand"), (BRAND_ERIC, "EricSheetBrand")):
            conn.execute(
                text(
                    "INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name) "
                    "VALUES (:b, :t, :n) ON CONFLICT DO NOTHING"
                ),
                {"b": bid, "t": TENANT, "n": nm},
            )
        # reset both flags to their stale default so every test starts from drift.
        conn.execute(
            text(
                "UPDATE ps_brands SET seen_in_exclusion_list = false, seen_in_eric_sheets = false "
                "WHERE tenant_id = :t AND wayward_brand_id IN (:b1, :b2)"
            ),
            {"t": TENANT, "b1": BRAND_EXCLUDED, "b2": BRAND_ERIC},
        )
        # source of truth for seen_in_exclusion_list + the on_exclusion_list signal
        conn.execute(
            text(
                "INSERT INTO ps_excluded_brands (tenant_id, wayward_brand_id, bucket) "
                "VALUES (:t, :b, 'Heavy Producer Brands') ON CONFLICT DO NOTHING"
            ),
            {"t": TENANT, "b": BRAND_EXCLUDED},
        )
        # source of truth for seen_in_eric_sheets (the eric_sheet harvest reads the FLAG, not this).
        conn.execute(
            text(
                "INSERT INTO ps_brand_observations "
                "(tenant_id, wayward_brand_id, field, value, source_system, source_ref) "
                "VALUES (:t, :b, 'referral_source', 'eric', "
                "'gsheet:eric-all-agreements', 'test-eric-sheet-ref') "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": TENANT, "b": BRAND_ERIC},
        )


def _cleanup(engine: Engine) -> None:
    # Only the PER-RUN accumulating rows are cleared. The source rows (brands/excluded/observation)
    # persist — the append-only observation and its FK onto ps_brands make them undeletable, and
    # _seed resets their derived flags anyway.
    with engine.begin() as conn:
        for tbl in ("ps_nationality_signals", "cip_sync_runs"):
            conn.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :t"), {"t": TENANT})


@pytest.fixture
def seeded(seeded_engine: Engine) -> Generator[Engine, None, None]:
    _cleanup(seeded_engine)  # defensive: clear any residue from a prior failed run
    _seed(seeded_engine)
    try:
        yield seeded_engine
    finally:
        _cleanup(seeded_engine)


def _seen_flag(engine: Engine, brand_id: str, column: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT {column} FROM ps_brands WHERE wayward_brand_id = :b"),
            {"b": brand_id},
        ).scalar()


# ── (a) idempotency ─────────────────────────────────────────────────────────


@pytest.mark.requires_postgres
def test_second_run_inserts_zero_new_signals(seeded: Engine) -> None:
    """First run inserts on_exclusion_list + eric_sheet; the second inserts nothing."""
    run1 = run_signal_harvest(seeded, tenant_id=TENANT, apply=True)
    assert run1["harvested"]["on_exclusion_list"] == 1
    assert run1["harvested"]["eric_sheet"] == 1, (
        "eric_sheet must fire on run 1 — proving the seen_in maintenance pre-step ran BEFORE the "
        "harvest that reads seen_in_eric_sheets"
    )
    assert run1["signals_inserted"] == 2

    run2 = run_signal_harvest(seeded, tenant_id=TENANT, apply=True)
    assert run2["signals_inserted"] == 0
    assert run2["harvested"]["on_exclusion_list"] == 0
    assert run2["harvested"]["eric_sheet"] == 0
    # nothing stale left to fix on the second pass, either
    assert run2["seen_in_maintenance"]["rows_corrected"] == 0

    # exactly two signal rows persisted for this tenant — no duplication.
    with seeded.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM ps_nationality_signals WHERE tenant_id = :t"),
            {"t": TENANT},
        ).scalar()
    assert n == 2


@pytest.mark.requires_postgres
def test_dry_run_persists_nothing(seeded: Engine) -> None:
    """apply=False rolls the harvest + maintenance back: no signals, flags untouched."""
    out = run_signal_harvest(seeded, tenant_id=TENANT, apply=False)
    assert out["applied"] is False
    with seeded.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM ps_nationality_signals WHERE tenant_id = :t"),
            {"t": TENANT},
        ).scalar()
    assert n == 0, "dry run must not persist signals"
    # the flag the maintenance step *would* have flipped is still at its stale default
    assert _seen_flag(seeded, BRAND_EXCLUDED, "seen_in_exclusion_list") is False


# ── (b) seen_in maintenance corrects + counts a stale flag ──────────────────


@pytest.mark.requires_postgres
def test_stale_seen_in_flag_is_corrected_and_counted(seeded: Engine) -> None:
    """First run brings both flags to truth; corrupt one; the next run re-corrects and counts it."""
    run1 = run_signal_harvest(seeded, tenant_id=TENANT, apply=True)
    # run 1 corrected both stale defaults: exclusion (b1) + eric (b2) = two distinct rows.
    assert run1["seen_in_maintenance"]["rows_corrected"] == 2
    assert run1["seen_in_maintenance"]["seen_in_exclusion_list_corrected"] == 1
    assert run1["seen_in_maintenance"]["seen_in_eric_sheets_corrected"] == 1
    assert _seen_flag(seeded, BRAND_EXCLUDED, "seen_in_exclusion_list") is True

    # Corrupt the cache the way it drifts in the wild: row exists, flag says false.
    with seeded.begin() as conn:
        conn.execute(
            text(
                "UPDATE ps_brands SET seen_in_exclusion_list = false "
                "WHERE wayward_brand_id = :b"
            ),
            {"b": BRAND_EXCLUDED},
        )

    run2 = run_signal_harvest(seeded, tenant_id=TENANT, apply=True)
    assert run2["seen_in_maintenance"]["rows_corrected"] == 1
    assert run2["seen_in_maintenance"]["seen_in_exclusion_list_corrected"] == 1
    assert run2["seen_in_maintenance"]["seen_in_eric_sheets_corrected"] == 0
    # the flag is back to its truth.
    assert _seen_flag(seeded, BRAND_EXCLUDED, "seen_in_exclusion_list") is True


# ── (c) heartbeat row ───────────────────────────────────────────────────────


@pytest.mark.requires_postgres
def test_heartbeat_row_recorded(seeded: Engine) -> None:
    """Each run records a cip_sync_runs row with connector_id 'ps-signal-harvest-v1'."""
    run = run_signal_harvest(seeded, tenant_id=TENANT, apply=True)
    assert run["sync_run_status"] == "success"

    with seeded.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, status, sync_mode, rows_created, rows_updated, rows_ingested "
                "FROM cip_sync_runs "
                "WHERE tenant_id = :t AND connector_id = :c"
            ),
            {"t": TENANT, "c": CONNECTOR_ID},
        ).mappings().all()

    assert len(row) == 1, "exactly one heartbeat for one run"
    hb = row[0]
    assert str(hb["id"]) == run["sync_run_id"]
    assert hb["status"] == "success"
    assert hb["sync_mode"] == "incremental"
    # counters map: 2 signals created + 2 flags corrected = 4 rows ingested.
    assert hb["rows_created"] == 2
    assert hb["rows_updated"] == 2
    assert hb["rows_ingested"] == 4
