# foundry: kind=script domain=client-intelligence-platform
"""Seed Wayward Tier 2 content from HubSpot + Zendesk.

Per PM scopes:
  - ee5b7e72  HubSpot Files + Zendesk Satisfaction Ratings
  - 510fff61  HubSpot Marketing Emails + Lists

Five passes (all gracefully skip on 403 -- Wayward PAT scope limits):
  1. HubSpot Files       -> cip_files (r2_path NULL; Layer 3 stages later)
  2. HubSpot Marketing Emails -> cip_marketing_emails
  3. HubSpot Contact Lists    -> cip_contact_lists
  4. Zendesk Satisfaction Ratings -> updates cip_tickets.satisfaction_rating
     for matched tickets
  5. Reports row counts post-seed

Idempotent: UNIQUE constraints + ON CONFLICT for upsert.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        WAYWARD_HUBSPOT_TOKEN=... \\
        WAYWARD_ZENDESK_TOKEN=... \\
        WAYWARD_ZENDESK_USER=jake@wayward.com \\
        WAYWARD_ZENDESK_SUBDOMAIN=waywardsupport \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python scripts/seed_wayward_tier2_capabilities.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from uuid import uuid4

from sqlalchemy import create_engine, text

from cip.integration_mesh.connectors.hubspot import HubSpotConnector
from cip.integration_mesh.connectors.zendesk import ZendeskConnector
from cip.integration_mesh.wayward_constants import (
    ECOMLEVER_TENANT_ID,
    WAYWARD_CLIENT_ID,
)

T = str(ECOMLEVER_TENANT_ID)
C = str(WAYWARD_CLIENT_ID)


def _safety_gate(url: str) -> int | None:
    m = re.search(r"@([^/:?]+)", url)
    host = m.group(1) if m else "<unknown>"
    is_prod = bool(re.search(r"\.rlwy\.net|\.railway\.app", host))
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if not is_local:
        expected = "YES_I_KNOW_THIS_IS_PROD" if is_prod else "YES_I_KNOW_THIS_IS_REMOTE"
        if os.environ.get("SEED_CONFIRM") != expected:
            print(f"ABORTED: re-run with SEED_CONFIRM={expected}", file=sys.stderr)
            return 3
    print(f"[seed-tier2] target={host} (prod={is_prod})")
    return None


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    err = _safety_gate(url)
    if err is not None:
        return err

    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)
    batch_id = str(uuid4())

    # ── Pass 1: HubSpot Files -> cip_files ─────────────────────────────
    print("\n[seed-tier2] PASS 1: HubSpot Files -> cip_files")
    n_files = _seed_hubspot_files(engine, batch_id)
    print(f"  UPSERTed {n_files} cip_files rows (r2_path NULL until Layer 3)")

    # ── Pass 2: HubSpot Marketing Emails -> cip_marketing_emails ───────
    print("\n[seed-tier2] PASS 2: HubSpot Marketing Emails -> cip_marketing_emails")
    n_emails = _seed_hubspot_marketing_emails(engine, batch_id)
    print(f"  UPSERTed {n_emails} cip_marketing_emails rows")

    # ── Pass 3: HubSpot Contact Lists -> cip_contact_lists ─────────────
    print("\n[seed-tier2] PASS 3: HubSpot Contact Lists -> cip_contact_lists")
    n_lists = _seed_hubspot_contact_lists(engine, batch_id)
    print(f"  UPSERTed {n_lists} cip_contact_lists rows")

    # ── Pass 4: Zendesk Satisfaction Ratings -> cip_tickets update ─────
    print("\n[seed-tier2] PASS 4: Zendesk Satisfaction Ratings -> cip_tickets.satisfaction_rating")
    n_ratings, n_matched = _seed_zendesk_satisfaction(engine)
    print(f"  Fetched {n_ratings} ratings; updated {n_matched} cip_tickets rows")

    # ── Final verification ────────────────────────────────────────────
    print("\n[seed-tier2] Final state:")
    with engine.connect() as conn:
        conn.execute(text(f"SELECT set_config('app.current_tenant','{T}',true)"))
        for tbl, label in [
            ("cip_files", "HubSpot files"),
            ("cip_marketing_emails", "Marketing emails"),
            ("cip_contact_lists", "Contact lists"),
            ("cip_contact_list_memberships", "List memberships"),
        ]:
            n = conn.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = :t"),
                {"t": T},
            ).scalar()
            print(f"  {tbl:35s}: {n:>6,}  ({label})")
        n_rated = conn.execute(
            text(
                "SELECT COUNT(*) FROM cip_tickets WHERE tenant_id = :t "
                "AND satisfaction_rating IS NOT NULL"
            ),
            {"t": T},
        ).scalar()
        print(f"  {'cip_tickets w/ satisfaction':35s}: {n_rated:>6,}")
    return 0


def _seed_hubspot_files(engine, batch_id: str) -> int:
    conn = HubSpotConnector(tenant_id=ECOMLEVER_TENANT_ID)
    conn.authenticate()
    count = 0
    with engine.begin() as db:
        db.execute(text(f"SELECT set_config('app.current_tenant','{T}',true)"))
        for rec in conn.stream_files(batch_size=100):
            db.execute(
                text("""
                    INSERT INTO cip_files (
                        tenant_id, client_id, source_connector, source_id,
                        ingestion_batch_id, filename, mime_type, size_bytes,
                        properties
                    ) VALUES (
                        :tenant_id, :client_id, 'hubspot-v1', :source_id,
                        :batch_id, :filename, :mime_type, :size_bytes,
                        CAST(:properties AS jsonb)
                    )
                    ON CONFLICT (tenant_id, client_id, source_connector, source_id)
                    DO UPDATE SET
                        filename = EXCLUDED.filename,
                        mime_type = EXCLUDED.mime_type,
                        size_bytes = EXCLUDED.size_bytes,
                        properties = EXCLUDED.properties,
                        refreshed_at = now(),
                        updated_at = now()
                """),
                {
                    "tenant_id": T,
                    "client_id": C,
                    "source_id": rec["source_id"],
                    "batch_id": batch_id,
                    "filename": rec.get("filename"),
                    "mime_type": rec.get("mime_type"),
                    "size_bytes": rec.get("size_bytes"),
                    "properties": json.dumps({
                        k: v for k, v in rec.items()
                        if k not in ("__cip_kind__", "id", "source_id", "filename", "mime_type", "size_bytes")
                    }),
                },
            )
            count += 1
    return count


def _seed_hubspot_marketing_emails(engine, batch_id: str) -> int:
    conn = HubSpotConnector(tenant_id=ECOMLEVER_TENANT_ID)
    conn.authenticate()
    count = 0
    try:
        with engine.begin() as db:
            db.execute(text(f"SELECT set_config('app.current_tenant','{T}',true)"))
            for rec in conn.stream_marketing_emails(batch_size=100):
                db.execute(
                    text("""
                        INSERT INTO cip_marketing_emails (
                            tenant_id, client_id, source_connector, source_id,
                            ingestion_batch_id, name, subject, email_type, state,
                            published_at, from_name, from_email, stats, properties
                        ) VALUES (
                            :tenant_id, :client_id, 'hubspot-v1', :source_id,
                            :batch_id, :name, :subject, :email_type, :state,
                            :published_at, :from_name, :from_email,
                            CAST(:stats AS jsonb), CAST(:properties AS jsonb)
                        )
                        ON CONFLICT (tenant_id, client_id, source_connector, source_id)
                        DO UPDATE SET
                            name = EXCLUDED.name, subject = EXCLUDED.subject,
                            email_type = EXCLUDED.email_type, state = EXCLUDED.state,
                            published_at = EXCLUDED.published_at,
                            from_name = EXCLUDED.from_name, from_email = EXCLUDED.from_email,
                            stats = EXCLUDED.stats, properties = EXCLUDED.properties,
                            refreshed_at = now(), updated_at = now()
                    """),
                    {
                        "tenant_id": T, "client_id": C, "source_id": rec["source_id"],
                        "batch_id": batch_id, "name": rec.get("name"),
                        "subject": rec.get("subject"), "email_type": rec.get("email_type"),
                        "state": rec.get("state"), "published_at": rec.get("published_at"),
                        "from_name": rec.get("from_name"), "from_email": rec.get("from_email"),
                        "stats": json.dumps(rec.get("stats") or {}),
                        "properties": json.dumps(rec.get("raw") or {}),
                    },
                )
                count += 1
    except Exception as e:  # noqa: BLE001
        print(f"  WARN: marketing emails fetch errored: {type(e).__name__}: {str(e)[:200]}")
    return count


def _seed_hubspot_contact_lists(engine, batch_id: str) -> int:
    conn = HubSpotConnector(tenant_id=ECOMLEVER_TENANT_ID)
    conn.authenticate()
    count = 0
    try:
        with engine.begin() as db:
            db.execute(text(f"SELECT set_config('app.current_tenant','{T}',true)"))
            for rec in conn.stream_contact_lists():
                db.execute(
                    text("""
                        INSERT INTO cip_contact_lists (
                            tenant_id, client_id, source_connector, source_id,
                            ingestion_batch_id, name, list_type, processing_type,
                            member_count, filters, properties
                        ) VALUES (
                            :tenant_id, :client_id, 'hubspot-v1', :source_id,
                            :batch_id, :name, :list_type, :processing_type,
                            :member_count, CAST(:filters AS jsonb),
                            CAST(:properties AS jsonb)
                        )
                        ON CONFLICT (tenant_id, client_id, source_connector, source_id)
                        DO UPDATE SET
                            name = EXCLUDED.name, list_type = EXCLUDED.list_type,
                            processing_type = EXCLUDED.processing_type,
                            member_count = EXCLUDED.member_count,
                            filters = EXCLUDED.filters, properties = EXCLUDED.properties,
                            refreshed_at = now(), updated_at = now()
                    """),
                    {
                        "tenant_id": T, "client_id": C, "source_id": rec["source_id"],
                        "batch_id": batch_id, "name": rec.get("name"),
                        "list_type": rec.get("list_type"),
                        "processing_type": rec.get("processing_type"),
                        "member_count": rec.get("member_count"),
                        "filters": json.dumps(rec.get("filters") or {}),
                        "properties": json.dumps(rec.get("raw") or {}),
                    },
                )
                count += 1
    except Exception as e:  # noqa: BLE001
        print(f"  WARN: contact lists fetch errored: {type(e).__name__}: {str(e)[:200]}")
    return count


def _seed_zendesk_satisfaction(engine) -> tuple[int, int]:
    conn = ZendeskConnector(tenant_id=ECOMLEVER_TENANT_ID)
    try:
        conn.authenticate()
    except Exception as e:  # noqa: BLE001
        print(f"  WARN: Zendesk auth failed: {type(e).__name__}: {str(e)[:120]}")
        return 0, 0

    n_ratings = 0
    n_matched = 0
    with engine.begin() as db:
        db.execute(text(f"SELECT set_config('app.current_tenant','{T}',true)"))
        for rec in conn.stream_satisfaction_ratings(page_size=100):
            n_ratings += 1
            score = rec.get("score")
            ticket_sid = rec.get("ticket_source_id")
            if not score or not ticket_sid:
                continue
            r = db.execute(
                text(
                    "UPDATE cip_tickets "
                    "SET satisfaction_rating = :score, "
                    "    properties = properties || jsonb_build_object("
                    "      'satisfaction_rating_id', :rid, "
                    "      'satisfaction_comment', :comment, "
                    "      'satisfaction_reason', :reason, "
                    "      'satisfaction_created_at', :created_at"
                    "    ), "
                    "    updated_at = now() "
                    "WHERE tenant_id = :t AND source_connector = 'zendesk-v1' "
                    "  AND source_id = :sid"
                ),
                {
                    "score": score, "rid": rec.get("source_id"),
                    "comment": rec.get("comment"), "reason": rec.get("reason"),
                    "created_at": rec.get("created_at"),
                    "t": T, "sid": ticket_sid,
                },
            )
            n_matched += r.rowcount or 0
    return n_ratings, n_matched


if __name__ == "__main__":
    sys.exit(main())
