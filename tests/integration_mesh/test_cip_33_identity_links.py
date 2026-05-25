# foundry: kind=test domain=client-intelligence-platform
"""Tests for cip_33 — cip_identity_links + resolver + lens_china_tickets.

Covers PM scope 08b4ce7d:
  1. Table RLS — PS GUC sees only PS links; no GUC → 0; cross-tenant isolation.
  2. Resolver tiers — email-exact (1.0), role inbox (0.9), 1:N ambiguous
     (0.5, all candidates written, none promoted), excluded domain skipped.
  3. Idempotence — re-run = no dupes, refreshed_at advances; manual row
     survives a deterministic re-run untouched.
  4. lens_china_tickets — returns tickets whose requester resolves (>=0.9)
     to a china-referred brand; excludes <0.9 links; GUC isolation.

Self-contained seeding into the testcontainer (seeded_engine runs
alembic upgrade head incl. cip_33). Cleanup via tenant-scoped DELETE.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.resolve_identity_links import resolve_tenant
from tests._helpers.rls import session_as_role_and_tenant

# Two synthetic tenants for isolation (not the real PS/EC, to avoid
# colliding with any other test's seeding).
TENANT_A = UUID("aaaaaaaa-0000-4000-8000-000000000001")
TENANT_B = UUID("bbbbbbbb-0000-4000-8000-000000000002")


def _insert_contact(conn: Any, *, tenant_id: UUID, connector: str,
                    source_id: str, email: str | None,
                    properties: dict | None = None) -> None:
    conn.execute(text(
        """
        INSERT INTO cip_contacts (
            id, tenant_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            email, properties, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), :t, :conn, :sid,
            NOW(), NOW(), gen_random_uuid(), 'validated',
            :em, CAST(:p AS jsonb), NOW(), NOW()
        )
        """
    ), {"t": str(tenant_id), "conn": connector, "sid": source_id,
        "em": email, "p": json.dumps(properties or {})})


def _insert_company(conn: Any, *, tenant_id: UUID, source_id: str, name: str) -> None:
    conn.execute(text(
        """
        INSERT INTO cip_companies (
            id, tenant_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            name, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), :t, 'hubspot-v1', :sid,
            NOW(), NOW(), gen_random_uuid(), 'validated', :n, NOW(), NOW()
        )
        """
    ), {"t": str(tenant_id), "sid": source_id, "n": name})


def _insert_deal(conn: Any, *, tenant_id: UUID, source_id: str,
                 hs_company_id: str, source_str: str) -> None:
    conn.execute(text(
        """
        INSERT INTO cip_deals (
            id, tenant_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            name, properties, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), :t, 'hubspot-v1', :sid,
            NOW(), NOW(), gen_random_uuid(), 'validated',
            'deal', CAST(:p AS jsonb), NOW(), NOW()
        )
        """
    ), {"t": str(tenant_id), "sid": source_id,
        "p": json.dumps({"source": source_str,
                         "hs_primary_associated_company": hs_company_id})})


def _insert_ticket(conn: Any, *, tenant_id: UUID, source_id: str,
                   requester_id: str, subject: str) -> None:
    conn.execute(text(
        """
        INSERT INTO cip_tickets (
            id, tenant_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            subject, status, priority, properties, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), :t, 'zendesk-v1', :sid,
            NOW(), NOW(), gen_random_uuid(), 'validated',
            :subj, 'open', 'normal', CAST(:p AS jsonb), NOW(), NOW()
        )
        """
    ), {"t": str(tenant_id), "sid": source_id, "subj": subject,
        "p": json.dumps({"requester_id": requester_id})})


def _cleanup(engine: Engine) -> None:
    with engine.begin() as conn:
        for t in (TENANT_A, TENANT_B):
            for tbl in ("cip_identity_links", "cip_tickets", "cip_deals",
                        "cip_companies", "cip_contacts"):
                conn.execute(text(f"DELETE FROM {tbl} WHERE tenant_id=:t"), {"t": str(t)})


@pytest.fixture
def il_seeded(seeded_engine: Engine) -> Engine:
    """Seed contacts for the resolver tiers + a full ticket→brand chain."""
    with seeded_engine.begin() as conn:
        # TENANT_A — resolver tier fixtures (zendesk + hubspot contact pairs)
        # exact 1:1
        _insert_contact(conn, tenant_id=TENANT_A, connector="zendesk-v1",
                        source_id="z-exact", email="alice@brand.cn")
        _insert_contact(conn, tenant_id=TENANT_A, connector="hubspot-v1",
                        source_id="h-exact", email="alice@brand.cn",
                        properties={"associatedcompanyid": "co-china"})
        # role inbox
        _insert_contact(conn, tenant_id=TENANT_A, connector="zendesk-v1",
                        source_id="z-role", email="support@brand.cn")
        _insert_contact(conn, tenant_id=TENANT_A, connector="hubspot-v1",
                        source_id="h-role", email="support@brand.cn",
                        properties={"associatedcompanyid": "co-china"})
        # ambiguous: one zendesk email → two hubspot contacts
        _insert_contact(conn, tenant_id=TENANT_A, connector="zendesk-v1",
                        source_id="z-amb", email="dup@brand.cn")
        _insert_contact(conn, tenant_id=TENANT_A, connector="hubspot-v1",
                        source_id="h-amb1", email="dup@brand.cn",
                        properties={"associatedcompanyid": "co-china"})
        _insert_contact(conn, tenant_id=TENANT_A, connector="hubspot-v1",
                        source_id="h-amb2", email="dup@brand.cn",
                        properties={"associatedcompanyid": "co-china"})
        # excluded internal/agent domain
        _insert_contact(conn, tenant_id=TENANT_A, connector="zendesk-v1",
                        source_id="z-internal", email="bot@reply.email.wayward.com")
        _insert_contact(conn, tenant_id=TENANT_A, connector="hubspot-v1",
                        source_id="h-internal", email="bot@reply.email.wayward.com")

        # The china brand + a china-referral deal pointing at it
        _insert_company(conn, tenant_id=TENANT_A, source_id="co-china", name="ChinaBrand")
        _insert_deal(conn, tenant_id=TENANT_A, source_id="deal-1",
                     hs_company_id="co-china", source_str="China Referral - Eric")
        # A non-china company + deal (negative control)
        _insert_company(conn, tenant_id=TENANT_A, source_id="co-other", name="OtherBrand")
        _insert_contact(conn, tenant_id=TENANT_A, connector="zendesk-v1",
                        source_id="z-other", email="bob@other.com")
        _insert_contact(conn, tenant_id=TENANT_A, connector="hubspot-v1",
                        source_id="h-other", email="bob@other.com",
                        properties={"associatedcompanyid": "co-other"})

        # Tickets: one from the exact-match requester (→ china brand),
        # one from the ambiguous requester (0.5 → excluded from lens),
        # one from the other-brand requester (not china).
        _insert_ticket(conn, tenant_id=TENANT_A, source_id="tk-china",
                       requester_id="z-exact", subject="China ticket")
        _insert_ticket(conn, tenant_id=TENANT_A, source_id="tk-amb",
                       requester_id="z-amb", subject="Ambiguous ticket")
        _insert_ticket(conn, tenant_id=TENANT_A, source_id="tk-other",
                       requester_id="z-other", subject="Other ticket")

        # TENANT_B — one exact pair, for isolation
        _insert_contact(conn, tenant_id=TENANT_B, connector="zendesk-v1",
                        source_id="zb", email="carol@b.cn")
        _insert_contact(conn, tenant_id=TENANT_B, connector="hubspot-v1",
                        source_id="hb", email="carol@b.cn")
    yield seeded_engine
    _cleanup(seeded_engine)


def _guc(conn: Any, t: UUID) -> None:
    conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": str(t)})


# ── 1. Resolver tiers ────────────────────────────────────────────────────

@pytest.mark.requires_postgres
def test_resolver_tiers(il_seeded: Engine) -> None:
    summary = resolve_tenant(il_seeded, TENANT_A)
    # exact (alice) = 1; role (support) = 1; ambiguous (dup→2 hubspot) = 2
    # candidates written; bob@other = 1 exact; internal excluded.
    assert summary.email_exact == 2, summary.to_dict()   # alice + bob
    assert summary.email_role_account == 1
    assert summary.email_ambiguous == 2                  # both candidates
    assert summary.excluded_domain == 1                  # the wayward reply bot

    with il_seeded.connect() as conn:
        _guc(conn, TENANT_A)
        rows = conn.execute(text(
            "SELECT left_source_id, right_source_id, link_type, confidence "
            "FROM cip_identity_links ORDER BY link_type, right_source_id"
        )).mappings().all()
    by_type: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r["link_type"], []).append(r)
    assert {float(r["confidence"]) for r in by_type["email-exact"]} == {1.0}
    assert {float(r["confidence"]) for r in by_type["email-role-account"]} == {0.9}
    assert {float(r["confidence"]) for r in by_type["email-ambiguous"]} == {0.5}
    # both ambiguous candidates present
    assert len(by_type["email-ambiguous"]) == 2
    # internal/agent domain never written
    assert all(r["right_source_id"] != "h-internal" for r in rows)


# ── 2. Idempotence + manual preservation ─────────────────────────────────

@pytest.mark.requires_postgres
def test_resolver_idempotent_and_preserves_manual(il_seeded: Engine) -> None:
    resolve_tenant(il_seeded, TENANT_A)
    with il_seeded.connect() as conn:
        _guc(conn, TENANT_A)
        n1 = conn.execute(text("SELECT COUNT(*) FROM cip_identity_links")).scalar()
        ts1 = conn.execute(text(
            "SELECT refreshed_at FROM cip_identity_links "
            "WHERE left_source_id='z-exact' AND method='deterministic-email-v1'"
        )).scalar()

    # Insert a manual override on the SAME edge (different method) — must survive.
    with il_seeded.begin() as conn:
        _guc(conn, TENANT_A)
        conn.execute(text(
            "INSERT INTO cip_identity_links (id, tenant_id, left_connector, "
            "left_source_id, right_connector, right_source_id, link_type, "
            "confidence, method, ingested_at) VALUES "
            "(gen_random_uuid(), :t, 'zendesk-v1', 'z-exact', 'hubspot-v1', "
            "'h-exact', 'manual', 1.0, 'operator:tim', NOW())"
        ), {"t": str(TENANT_A)})

    # Re-run deterministic pass.
    resolve_tenant(il_seeded, TENANT_A)
    with il_seeded.connect() as conn:
        _guc(conn, TENANT_A)
        n2 = conn.execute(text("SELECT COUNT(*) FROM cip_identity_links")).scalar()
        # +1 (the manual row) over n1; deterministic re-run adds no dupes
        assert n2 == n1 + 1, f"re-run created dupes: n1={n1} n2={n2}"
        # manual row untouched
        manual = conn.execute(text(
            "SELECT confidence, method FROM cip_identity_links "
            "WHERE left_source_id='z-exact' AND method='operator:tim'"
        )).mappings().first()
        assert manual is not None and float(manual["confidence"]) == 1.0
        # deterministic row's refreshed_at advanced
        ts2 = conn.execute(text(
            "SELECT refreshed_at FROM cip_identity_links "
            "WHERE left_source_id='z-exact' AND method='deterministic-email-v1'"
        )).scalar()
        assert ts2 >= ts1


# ── 3. Table RLS isolation ────────────────────────────────────────────────

@pytest.mark.requires_postgres
def test_identity_links_rls_isolation(il_seeded: Engine) -> None:
    """Table-level RLS via the non-superuser cip_rls_test_role (the
    testcontainer's default user is a BYPASSRLS superuser, so RLS only
    enforces under the restricted role — mirrors cip_30/cip_31 tests)."""
    resolve_tenant(il_seeded, TENANT_A)
    resolve_tenant(il_seeded, TENANT_B)
    distinct_sql = text("SELECT DISTINCT tenant_id FROM cip_identity_links")

    # GUC=A under the RLS-enforcing role → only A's links visible.
    with session_as_role_and_tenant(il_seeded, TENANT_A) as conn:
        a = conn.execute(text("SELECT COUNT(*) FROM cip_identity_links")).scalar()
        a_tenants = {str(r[0]) for r in conn.execute(distinct_sql).fetchall()}
    assert a_tenants == {str(TENANT_A)}, f"GUC=A leaked: {a_tenants}"
    assert a >= 4  # exact*2 + role*1 + ambiguous*2 for A

    # GUC=B → only B's links; A not leaked.
    with session_as_role_and_tenant(il_seeded, TENANT_B) as conn:
        b_tenants = {str(r[0]) for r in conn.execute(distinct_sql).fetchall()}
    assert b_tenants == {str(TENANT_B)}
    assert str(TENANT_A) not in b_tenants

    # No GUC under the restricted role → zero rows (fail-closed).
    with session_as_role_and_tenant(il_seeded, None) as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM cip_identity_links")).scalar()
    assert n == 0, f"expected 0 rows with no GUC under restricted role; got {n}"


# ── 4. lens_china_tickets ─────────────────────────────────────────────────

@pytest.mark.requires_postgres
def test_lens_china_tickets(il_seeded: Engine) -> None:
    resolve_tenant(il_seeded, TENANT_A)
    with il_seeded.connect() as conn:
        _guc(conn, TENANT_A)
        rows = conn.execute(text(
            "SELECT zendesk_ticket_id, brand_name, link_type, confidence "
            "FROM lens_china_tickets ORDER BY zendesk_ticket_id"
        )).mappings().all()
    # tk-china (z-exact → china brand, conf 1.0) IS included.
    # tk-amb (z-amb → 0.5 ambiguous) EXCLUDED (< 0.9).
    # tk-other (z-other → non-china brand) EXCLUDED (china predicate).
    ids = {r["zendesk_ticket_id"] for r in rows}
    assert ids == {"tk-china"}, f"unexpected lens rows: {ids}"
    assert rows[0]["brand_name"] == "ChinaBrand"
    assert float(rows[0]["confidence"]) == 1.0


@pytest.mark.requires_postgres
def test_lens_china_tickets_isolation(il_seeded: Engine) -> None:
    resolve_tenant(il_seeded, TENANT_A)
    with il_seeded.connect() as conn:
        # TENANT_B has no tickets/deals → lens empty under B GUC
        _guc(conn, TENANT_B)
        n = conn.execute(text("SELECT COUNT(*) FROM lens_china_tickets")).scalar()
        assert n == 0
        # no GUC → 0 (fail-closed predicate)
        conn.execute(text("RESET app.current_tenant"))
        n2 = conn.execute(text("SELECT COUNT(*) FROM lens_china_tickets")).scalar()
        assert n2 == 0
