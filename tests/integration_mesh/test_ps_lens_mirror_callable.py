# foundry: kind=test domain=client-intelligence-platform
"""Tests for cip.integration_mesh.sync.ps_lens_mirror.run_ps_china_mirror.

PM scope 8d47e809. The PS LensMirror orchestration was lifted from
scripts/orchestrate_ps_lens_mirror.py into a callable so the FAS
subsystem_scheduler can drive it. These tests verify the callable's
contract:

  1. Returns the documented dict shape (JSON-safe, no exotic types).
  2. dry_run=True does Pass-1 lookup-derivation but no writes.
  3. No prints to stdout — uses stdlib logger only (so the FAS executor
     doesn't see noisy stdout from a scheduled task).
  4. **Does NOT verify the FAS-owned `tenants` table.** That precondition
     is caller-side (script + FAS wrapper); CIP must not depend on FAS
     schema.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from cip.integration_mesh.sync.ps_lens_mirror import run_ps_china_mirror

PS_TENANT = UUID("078a37d6-6ae2-4e22-869e-cc08f6cb2787")


# ── 1. dry_run=True does derivation but no writes ────────────────────────────


@pytest.mark.requires_postgres
def test_dry_run_returns_documented_shape(seeded_engine: Engine) -> None:
    """dry_run=True returns the documented summary dict but writes nothing
    to PS cip_clients. Empty Pass 1 (no fixture china companies) is fine —
    we just need the shape to be right."""
    pre_ps_clients = _count_ps_clients(seeded_engine)
    summary = run_ps_china_mirror(
        engine=seeded_engine,
        ps_tenant_id=PS_TENANT,
        dry_run=True,
    )
    post_ps_clients = _count_ps_clients(seeded_engine)

    # Shape contract
    assert set(summary.keys()) >= {
        "ps_tenant", "dry_run", "pass_1", "pass_2"
    }
    assert summary["ps_tenant"] == str(PS_TENANT)
    assert summary["dry_run"] is True
    assert set(summary["pass_1"].keys()) == {
        "source_china_companies", "inserted", "updated", "intake_route_backfilled"
    }
    # No writes — dry-run honored.
    assert post_ps_clients == pre_ps_clients

    # JSON-safe — the FAS scheduler stores this in tasks.result (JSONB).
    json.dumps(summary)  # must not raise


# ── 2. Quiet stdout — production schedulers don't want noise ─────────────────


@pytest.mark.requires_postgres
def test_no_print_to_stdout(seeded_engine: Engine) -> None:
    """run_ps_china_mirror logs via stdlib logger only — no `print()`.

    Reasoning: the FAS executor captures stdout into tasks output; noisy
    stdout from scheduled tasks bloats the tasks table. We use logger for
    a clean separation between operator-facing diagnostics (script's
    print) and structured run records (return value).
    """
    buf = io.StringIO()
    with redirect_stdout(buf):
        run_ps_china_mirror(
            engine=seeded_engine,
            ps_tenant_id=PS_TENANT,
            dry_run=True,
        )
    # No prints — quiet by design.
    assert buf.getvalue() == "", (
        f"run_ps_china_mirror printed to stdout: {buf.getvalue()!r}"
    )


# ── 3. JSON-safe return value (Decimal / UUID / datetime would fail JSONB) ──


@pytest.mark.requires_postgres
def test_json_safe_summary(seeded_engine: Engine) -> None:
    """Round-trip the summary through json.dumps/loads — no exotic types."""
    summary = run_ps_china_mirror(
        engine=seeded_engine,
        ps_tenant_id=PS_TENANT,
        dry_run=True,
    )
    serialized = json.dumps(summary, sort_keys=True)
    deserialized = json.loads(serialized)
    assert deserialized["ps_tenant"] == str(PS_TENANT)
    assert deserialized["dry_run"] is True
    # Pass 1 + Pass 2 are dicts with int counters / per-entity entries.
    assert isinstance(deserialized["pass_1"], dict)
    assert isinstance(deserialized["pass_2"], dict)


# ── 4. No dependency on the FAS-owned `tenants` table ───────────────────────


@pytest.mark.requires_postgres
def test_no_tenants_table_dependency(seeded_engine: Engine) -> None:
    """The CIP testcontainer has no `tenants` table (that's a FAS-owned
    table). run_ps_china_mirror must NOT depend on it — see DESIGN NOTE
    in cip/integration_mesh/sync/ps_lens_mirror.py.

    This test asserts that explicitly: if `tenants` doesn't exist and
    the call still works, we know the callable hasn't reacquired the
    coupling that was removed during the PM scope 8d47e809 refactor."""
    with seeded_engine.connect() as c:
        tenants_exists = c.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'tenants' AND table_schema = 'public'"
            )
        ).first()
    # If this assertion ever fails (e.g. someone added the `tenants` table
    # to a CIP migration), drop the assertion — the test is fine.
    assert tenants_exists is None, (
        "Unexpected `tenants` table in CIP testcontainer; this test "
        "assumes CIP doesn't own that schema."
    )
    # The real test: this call must succeed without `tenants` existing.
    summary = run_ps_china_mirror(
        engine=seeded_engine,
        ps_tenant_id=PS_TENANT,
        dry_run=True,
    )
    assert summary["ps_tenant"] == str(PS_TENANT)


# ── helpers ────────────────────────────────────────────────────────────────


def _count_ps_clients(engine: Engine) -> int:
    with engine.connect() as c:
        return c.execute(
            text("SELECT COUNT(*) FROM cip_clients WHERE tenant_id=:t"),
            {"t": str(PS_TENANT)},
        ).scalar()
