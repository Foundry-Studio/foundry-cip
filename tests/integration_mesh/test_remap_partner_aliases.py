# foundry: kind=test domain=client-intelligence-platform
"""remap_partner_aliases: xq->kerry, sj->sarah on stale ps_partner_credit rows;
Eric's unknown codes reported but never remapped; dry-run changes nothing."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.remap_partner_aliases import run as remap_run

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
WB = {
    "xq1": UUID("b1111111-1111-4111-8111-111111111111"),
    "xq2": UUID("b2222222-2222-4222-8222-222222222222"),
    "sj1": UUID("b3333333-3333-4333-8333-333333333333"),
    "we1": UUID("b4444444-4444-4444-8444-444444444444"),
}


def _guc(conn: Any) -> None:
    conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT})


def _seed_credit(conn: Any, wbid: UUID, partner: str) -> None:
    conn.execute(text(
        "INSERT INTO ps_brands (wayward_brand_id, tenant_id, brand_name, seen_in_stripe, "
        "seen_in_slack_feed, seen_in_payment_reports, seen_in_exclusion_list, seen_in_eric_sheets, "
        "first_seen_at, updated_at) VALUES (:b,:t,:n,false,false,false,false,false,now(),now()) "
        "ON CONFLICT (wayward_brand_id) DO NOTHING"
    ), {"b": str(wbid), "t": PS_TENANT, "n": f"brand-{partner}"})
    conn.execute(text(
        "INSERT INTO ps_partner_credit "
        "(tenant_id, wayward_brand_id, product_id, partner_of_record, "
        "determined_by, determined_at, match_status) "
        "VALUES (:t, :b, 'connect', :p, 'test', now(), 'confirmed')"
    ), {"t": PS_TENANT, "b": str(wbid), "p": partner})


@pytest.fixture
def stale_seeded(seeded_engine: Engine) -> Any:
    with seeded_engine.begin() as conn:
        _guc(conn)
        _seed_credit(conn, WB["xq1"], "xq")
        _seed_credit(conn, WB["xq2"], "xq")
        _seed_credit(conn, WB["sj1"], "sj")
        _seed_credit(conn, WB["we1"], "we")
    yield seeded_engine
    with seeded_engine.begin() as conn:
        _guc(conn)
        for w in WB.values():
            conn.execute(text(
                "DELETE FROM ps_partner_credit "
                "WHERE tenant_id=:t AND wayward_brand_id=:b"
            ), {"t": PS_TENANT, "b": str(w)})
            conn.execute(text("DELETE FROM ps_brands WHERE tenant_id=:t AND wayward_brand_id=:b"),
                         {"t": PS_TENANT, "b": str(w)})


def _por(conn: Any, wbid: UUID) -> str | None:
    return conn.execute(
        text(
            "SELECT partner_of_record FROM ps_partner_credit "
            "WHERE tenant_id=:t AND wayward_brand_id=:b"
        ),
        {"t": PS_TENANT, "b": str(wbid)},
    ).scalar()


@pytest.mark.requires_postgres
def test_remap_merges_known_aliases_and_flags_unknown(stale_seeded: Engine) -> None:
    with stale_seeded.begin() as conn:
        out = remap_run(conn, apply=True)
    assert out["known_merges_credit_rows"]["xq->kerry"] == 2
    assert out["known_merges_credit_rows"]["sj->sarah"] == 1
    assert out["unknown_eric_codes_left"].get("we") == 1
    with stale_seeded.connect() as conn:
        _guc(conn)
        assert _por(conn, WB["xq1"]) == "kerry"
        assert _por(conn, WB["xq2"]) == "kerry"
        assert _por(conn, WB["sj1"]) == "sarah"
        assert _por(conn, WB["we1"]) == "we"  # unknown Eric code left untouched


@pytest.mark.requires_postgres
def test_remap_dry_run_changes_nothing(stale_seeded: Engine) -> None:
    with stale_seeded.connect() as conn:
        out = remap_run(conn, apply=False)
    assert out["applied"] is False
    with stale_seeded.connect() as conn:
        _guc(conn)
        assert _por(conn, WB["xq1"]) == "xq"  # unchanged
