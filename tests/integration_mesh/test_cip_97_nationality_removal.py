# foundry: kind=test domain=client-intelligence-platform
"""cip_97 — the superseded cip_clients nationality name-signal system stays gone.

Regression guard for the 2026-07-14 clean-state removal (Tim). The five
`cip_clients.nationality_*` columns, their 2 constraints + 2 indexes, and the four
now-dead views that read them (`lens_ps_eligibility` +
`lens_ps_china_commission_v2` / `_brand_opportunity` / `_nationality_gap`) must not
reappear. Nationality lives only in `ps_nationality_signals -> lens_ps_china_verdict`.

`seeded_engine` runs `alembic upgrade head` (incl. cip_97) against the testcontainer,
so these assert the post-removal schema.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

_DROPPED_COLUMNS = (
    "nationality_class", "nationality_review_status", "nationality_decided_at",
    "nationality_decided_by", "nationality_rationale",
)
_DROPPED_VIEWS = (
    "lens_ps_eligibility", "lens_ps_china_commission_v2",
    "lens_ps_brand_opportunity", "lens_ps_nationality_gap",
)


@pytest.mark.requires_postgres
def test_nationality_columns_removed(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'cip_clients'"
            )).fetchall()
        }
    leaked = [c for c in _DROPPED_COLUMNS if c in cols]
    assert not leaked, f"nationality columns still present on cip_clients: {leaked}"


@pytest.mark.requires_postgres
def test_dead_nationality_views_removed(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        views = {
            r[0] for r in conn.execute(text(
                "SELECT viewname FROM pg_views WHERE schemaname = 'public'"
            )).fetchall()
        }
    leaked = [v for v in _DROPPED_VIEWS if v in views]
    assert not leaked, f"dead nationality views still present: {leaked}"


@pytest.mark.requires_postgres
def test_nationality_constraints_and_indexes_removed(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        cons = {
            r[0] for r in conn.execute(text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'cip_clients'::regclass"
            )).fetchall()
        }
        idxs = {
            r[0] for r in conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'cip_clients'"
            )).fetchall()
        }
    assert "cip_clients_nationality_class_check" not in cons
    assert "cip_clients_nationality_review_status_check" not in cons
    assert "idx_cip_clients_nationality" not in idxs
    assert "idx_cip_clients_nationality_review" not in idxs


@pytest.mark.requires_postgres
def test_china_verdict_lens_survives(seeded_engine: Engine) -> None:
    """The nationality source of truth must remain — we removed the OLD system, not the new one."""
    with seeded_engine.connect() as conn:
        verdict = conn.execute(
            text("SELECT to_regclass('public.lens_ps_china_verdict')")
        ).scalar()
        companies = conn.execute(
            text("SELECT to_regclass('public.lens_ps_china_companies')")
        ).scalar()
    assert verdict is not None, "lens_ps_china_verdict (the nationality source of truth) is missing"
    assert companies is not None, "lens_ps_china_companies rollup is missing"


def test_eligibility_fanout_invariant_removed() -> None:
    """The lens_eligibility_fanout invariant guarded a now-dropped view, so it is gone. The
    same fan-out is still guarded on the surviving verdict view by lens_verdict_fanout — no DB."""
    from cip.integration_mesh.ps_invariants import INVARIANTS

    keys = {i.key for i in INVARIANTS}
    assert "lens_eligibility_fanout" not in keys, "orphaned eligibility invariant still present"
    assert "lens_verdict_fanout" in keys, "the surviving fan-out guard must remain"
