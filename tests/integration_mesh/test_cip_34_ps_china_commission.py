# foundry: kind=test domain=client-intelligence-platform
"""Tests for cip_34 — lens_ps_china_commission + PS-derived attribution backfill.

Covers PM cip_34 (china-commission-audit):
  1. Backfill attribution logic (pure _attribution_for): Tim→PS, partner→
     finders_fee unless Exhibit A, no-source→unclassified.
  2. Backfill run (DB): seeds the 3 derived keys per brand; idempotent
     (re-run = 0 updated); never touches ps_sales_lead/ps_cs_lead.
  3. lens_ps_china_commission: RETIRED by cip_154 (H4, wrong basis). Only
     attribution fields; GUC isolation.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.backfill_ps_china_attribution import _attribution_for, _norm, run_backfill

PS_TENANT = UUID("078a37d6-6ae2-4e22-869e-cc08f6cb2787")
EC_TENANT = UUID("dec814db-722a-4730-8e60-51afc4a5dad9")


def _insert_client(conn: Any, *, tenant_id: UUID, client_id: UUID,
                   source_id: str, name: str, companion: dict | None = None) -> None:
    conn.execute(text(
        """
        INSERT INTO cip_clients (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            name, slug, companion_data, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), :t, :cid, 'lens-mirror', :sid,
            NOW(), NOW(), gen_random_uuid(), 'validated',
            :n, :slug, CAST(:cd AS jsonb), NOW(), NOW()
        )
        """
    ), {"t": str(tenant_id), "cid": str(client_id), "sid": source_id,
        "n": name, "slug": f"test-{source_id}", "cd": json.dumps(companion or {})})


def _insert_deal(conn: Any, *, tenant_id: UUID, client_id: UUID, source_id: str,
                 amount: float, source_str: str,
                 billed: str | None = None, paid: str | None = None) -> None:
    props: dict[str, Any] = {"source": source_str}
    if billed is not None:
        props["total_fees_billed"] = billed
    if paid is not None:
        props["total_fees_paid"] = paid
    conn.execute(text(
        """
        INSERT INTO cip_deals (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            name, amount, properties, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), :t, :cid, 'lens-mirror-deals-v1', :sid,
            NOW(), NOW(), gen_random_uuid(), 'validated',
            'deal', :a, CAST(:p AS jsonb), NOW(), NOW()
        )
        """
    ), {"t": str(tenant_id), "cid": str(client_id), "sid": source_id,
        "a": amount, "p": json.dumps(props)})


_EXHIBIT_A = {_norm("Roborock"), _norm("Wolfbox")}  # small fixture set


def _guc(conn: Any, tenant: UUID) -> None:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"),
        {"t": str(tenant)},
    )


@pytest.fixture
def comm_seeded(seeded_engine: Engine) -> Engine:
    """PS brands across the attribution tiers + fee data."""
    tim = uuid4()      # Tim → PS
    eric = uuid4()     # Eric, not Exhibit A → finders_fee
    roboc = uuid4()    # Eric, Exhibit A (Roborock) → blank conditional
    nosrc = uuid4()    # no china-referral source → unclassified
    with seeded_engine.begin() as conn:
        _insert_client(conn, tenant_id=PS_TENANT, client_id=tim,
                       source_id="hs-tim", name="TimBrand")
        _insert_deal(conn, tenant_id=PS_TENANT, client_id=tim, source_id="d-tim1",
                     amount=10000, source_str="China Referral - Tim",
                     billed="10000", paid="8000")
        _insert_client(conn, tenant_id=PS_TENANT, client_id=eric,
                       source_id="hs-eric", name="EricBrand")
        _insert_deal(conn, tenant_id=PS_TENANT, client_id=eric, source_id="d-eric1",
                     amount=5000, source_str="China Referral - Eric",
                     billed="5000", paid="3000")
        _insert_client(conn, tenant_id=PS_TENANT, client_id=roboc,
                       source_id="hs-robo", name="Roborock")
        _insert_deal(conn, tenant_id=PS_TENANT, client_id=roboc, source_id="d-robo1",
                     amount=20000, source_str="China Referral - Eric",
                     billed="20000", paid="15000")
        _insert_client(conn, tenant_id=PS_TENANT, client_id=nosrc,
                       source_id="hs-no", name="NoSourceBrand")
        _insert_deal(conn, tenant_id=PS_TENANT, client_id=nosrc, source_id="d-no1",
                     amount=1000, source_str="Hyphen Social Migration",
                     billed="1000", paid="500")
        # EcomLever noise (isolation)
        _insert_client(conn, tenant_id=EC_TENANT, client_id=uuid4(),
                       source_id="hs-ec", name="ECBrand")
    yield seeded_engine
    with seeded_engine.begin() as conn:
        for t in (PS_TENANT, EC_TENANT):
            conn.execute(text("DELETE FROM cip_deals WHERE tenant_id=:t"), {"t": str(t)})
            conn.execute(text("DELETE FROM cip_clients WHERE tenant_id=:t"), {"t": str(t)})


# ── 1. Pure attribution logic ─────────────────────────────────────────────

def test_attribution_tim_is_ps() -> None:
    m = _attribution_for("Tim", "Whatever", _EXHIBIT_A)
    assert m == {"ps_attribution_owner": "PS", "ps_lead_source": "PS"}


def test_attribution_partner_off_exhibit_gets_finders_fee() -> None:
    m = _attribution_for("Eric", "SomeRandomBrand", _EXHIBIT_A)
    assert m["ps_attribution_owner"] == "Eric"
    assert m["ps_lead_source"] == "Eric"
    assert m["ps_conditional"] == "finders_fee"


def test_attribution_partner_on_exhibit_no_finders_fee() -> None:
    m = _attribution_for("Eric", "Roborock", _EXHIBIT_A)
    assert m["ps_attribution_owner"] == "Eric"
    assert "ps_conditional" not in m  # excluded → blank


def test_attribution_no_source_unclassified() -> None:
    m = _attribution_for(None, "X", _EXHIBIT_A)
    assert m == {"ps_attribution_owner": "unclassified"}


def test_attribution_unknown_sourcer_unclassified() -> None:
    m = _attribution_for("Mystery", "X", _EXHIBIT_A)
    assert m == {"ps_attribution_owner": "unclassified"}


# ── 2. Backfill run (DB) — idempotent, doesn't touch sales/cs ────────────

@pytest.mark.requires_postgres
def test_backfill_seeds_and_is_idempotent(comm_seeded: Engine) -> None:
    s1 = run_backfill(comm_seeded, _EXHIBIT_A)
    assert s1.brands_total == 4
    assert s1.set_ps == 1
    assert s1.set_partner_finders_fee == 1   # EricBrand
    assert s1.set_partner_excluded == 1      # Roborock (Eric + Exhibit A)
    assert s1.set_unclassified == 1
    assert s1.updated == 4

    # Re-run → no-op
    s2 = run_backfill(comm_seeded, _EXHIBIT_A)
    assert s2.updated == 0
    assert s2.unchanged == 4

    # Spot-check the rows; sales/cs lead never set by backfill
    with comm_seeded.connect() as conn:
        _guc(conn, PS_TENANT)
        eric = conn.execute(text(
            "SELECT companion_data FROM cip_clients WHERE name='EricBrand'"
        )).scalar()
        assert eric["ps_attribution_owner"] == "Eric"
        assert eric["ps_conditional"] == "finders_fee"
        assert "ps_sales_lead" not in eric
        assert "ps_cs_lead" not in eric
        robo = conn.execute(text(
            "SELECT companion_data FROM cip_clients WHERE name='Roborock'"
        )).scalar()
        assert robo["ps_attribution_owner"] == "Eric"
        assert "ps_conditional" not in robo


@pytest.mark.requires_postgres
def test_backfill_preserves_other_companion_keys(comm_seeded: Engine) -> None:
    """Backfill writes only the 3 attribution keys; a pre-existing
    companion key (e.g. ps_onboarded_status) survives."""
    with comm_seeded.begin() as conn:
        _guc(conn, PS_TENANT)
        conn.execute(text(
            "UPDATE cip_clients SET companion_data = companion_data || "
            "'{\"ps_onboarded_status\": \"onboarded\"}'::jsonb WHERE name='TimBrand'"
        ))
    run_backfill(comm_seeded, _EXHIBIT_A)
    with comm_seeded.connect() as conn:
        _guc(conn, PS_TENANT)
        cd = conn.execute(text(
            "SELECT companion_data FROM cip_clients WHERE name='TimBrand'"
        )).scalar()
    assert cd["ps_onboarded_status"] == "onboarded"  # preserved
    assert cd["ps_attribution_owner"] == "PS"        # added


# ── 3. lens_ps_china_commission — RETIRED 2026-09-04 ─────────────────────
#
# test_commission_lens_projection and test_commission_lens_isolation lived here
# and are REMOVED, not retargeted.
#
# cip_154 dropped lens_ps_china_commission as finding H4: "wrong basis (10% of
# stated total_fees_paid, no china filter), UNWIRED, no dependent view. RETIRE
# via DROP; a correct rebuild is deferred to DI-5e."
#
# That matters for what to do with the tests. They did not merely reference a
# view that moved. They asserted the SPECIFIC NUMBERS the retired lens produced,
# including the 10%-of-paid basis that was the defect. Retargeting them onto
# lens_ps_commission_ledger would carry a known-wrong calculation forward under
# a name that implies it was checked. Deleting them is the correct outcome.
#
# The replacement assertion below is deliberately narrow: it holds the retirement
# in place, so a downgrade or a careless rebuild that resurrects the wrong-basis
# view fails here. When DI-5e lands a correct commission lens, test IT, with
# numbers derived from the rebuilt definition rather than copied from these.


@pytest.mark.requires_postgres
def test_wrong_basis_commission_lens_stays_retired(comm_seeded: Engine) -> None:
    """cip_154 H4: the wrong-basis commission lens must not come back."""
    with comm_seeded.connect() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM pg_views "
            "WHERE schemaname = 'public' AND viewname = 'lens_ps_china_commission'"
        )).scalar()
    assert n == 0, (
        "lens_ps_china_commission is back. cip_154 retired it as H4 for using a "
        "wrong basis (10% of stated total_fees_paid, no china filter). If a "
        "correct rebuild has landed, give it a new name and its own tests."
    )
