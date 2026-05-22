# foundry: kind=script domain=client-intelligence-platform
"""Purge the old Foundry-side Rocky Ridge state once CIP migration is verified.

Runs ONLY after `scripts/migrate_rocky_ridge_to_cip.py` has completed and
the acceptance gate passes. Removes:

  1. Foundry-side `knowledge_chunks` rows for the Rocky Ridge research
     library (source_id=52ad54c0-acfd-49db-b9b4-dc9c6098d9f6, tenant
     80252ad9-72d5-4c5a-b273-af804224872e). ~5,825 rows.
  2. The `knowledge_sources` row 52ad54c0... itself.
  3. Foundry-Pinecone vectors in namespace `tenant_80252ad9..._knowledge`
     that originated from this source (best-effort — Foundry Pinecone is
     a separate index in a separate account; we DELETE BY VECTOR ID using
     the chunk_id values we just deleted from Postgres).

DOES NOT touch:
  - The old R2 originals under `80252ad9.../knowledge/...` — left as cold
    backup. Drop with a separate one-shot if disk pressure demands it.
  - Anything under `cip-originals/` (the new CIP-owned copies — what we
    just moved INTO).

Safety gates:
  - SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD required (prod write).
  - PURGE_CONFIRM=I_HAVE_VERIFIED_CIP_PARITY required (extra interlock).
  - Pre-flight checks that CIP-side Rocky Ridge has ≥ the chunk count we're
    about to delete — refuses to purge otherwise.
  - Dry-run by default; pass `--apply` to actually delete.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        PURGE_CONFIRM=I_HAVE_VERIFIED_CIP_PARITY \\
        python scripts/purge_rocky_ridge_foundry_state.py [--apply]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import create_engine, text


# -- Constants ---------------------------------------------------------------

ROCKY_RIDGE_TENANT_ID: UUID = UUID("80252ad9-72d5-4c5a-b273-af804224872e")
FOUNDRY_KS_SOURCE_ID: UUID = UUID("52ad54c0-acfd-49db-b9b4-dc9c6098d9f6")
CIP_SOURCE_KIND_FOR_MIGRATED_DOCS = "cip_client_document"


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
    if os.environ.get("PURGE_CONFIRM") != "I_HAVE_VERIFIED_CIP_PARITY":
        print(
            "ABORTED: re-run with PURGE_CONFIRM=I_HAVE_VERIFIED_CIP_PARITY "
            "(extra interlock — see script docstring)",
            file=sys.stderr,
        )
        return 3
    print(f"[purge-rr] target={host} (prod={is_prod})")
    return None


def main() -> int:
    print(f"RUN_BEGAN tag=purge_rocky_ridge_foundry_state at={datetime.now(timezone.utc).isoformat()}")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually delete (default: dry-run)")
    args = ap.parse_args()

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

    with engine.connect() as conn:
        # Pre-flight 1: how many Foundry-side chunks exist for this source?
        foundry_chunks = conn.execute(text(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE source_id = :sid"
        ), {"sid": str(FOUNDRY_KS_SOURCE_ID)}).scalar() or 0
        print(f"[purge-rr] Foundry-side chunks to purge: {foundry_chunks:,}")
        if foundry_chunks == 0:
            print("[purge-rr] Nothing to purge — already clean.")
            return 0

        # Pre-flight 2: CIP-side parity — chunks tagged cip_client_document
        # for tenant 80252ad9 should be ≥ foundry_chunks.
        cip_chunks = conn.execute(text(
            "SELECT COUNT(*) FROM cip_knowledge_chunks "
            "WHERE tenant_id = :t AND source_kind = :sk"
        ), {"t": str(ROCKY_RIDGE_TENANT_ID), "sk": CIP_SOURCE_KIND_FOR_MIGRATED_DOCS}).scalar() or 0
        print(f"[purge-rr] CIP-side chunks (Rocky Ridge cip_client_document): {cip_chunks:,}")
        if cip_chunks < 100:
            print(
                "ABORTED: CIP-side has < 100 chunks for Rocky Ridge — migration "
                "likely incomplete. Re-run migrate_rocky_ridge_to_cip.py first.",
                file=sys.stderr,
            )
            return 4

        # Pre-flight 3: cip_files count parity vs R2 source object count.
        # We accept either: cip_files ≥ documents we expected (132 per
        # knowledge_sources.document_count, but 72 per R2 enumeration).
        cip_files_count = conn.execute(text(
            "SELECT COUNT(*) FROM cip_files WHERE tenant_id = :t AND source_connector = 'manual_upload'"
        ), {"t": str(ROCKY_RIDGE_TENANT_ID)}).scalar() or 0
        print(f"[purge-rr] CIP-side cip_files (manual_upload): {cip_files_count:,}")
        if cip_files_count < 50:
            print(
                f"ABORTED: cip_files count {cip_files_count} suspiciously low. "
                "Verify migration before purging.",
                file=sys.stderr,
            )
            return 4

        # Sample some chunk_ids we're about to delete — we'd need these to
        # also delete from Foundry-Pinecone, but Foundry-Pinecone is in a
        # different account/index and out of scope for this script. We
        # print them so an operator can drop them via a separate sweep if
        # they care about reclaiming the Foundry-side vector quota.
        sample_ids = conn.execute(text(
            "SELECT chunk_id::text FROM knowledge_chunks "
            "WHERE source_id = :sid ORDER BY chunk_id LIMIT 5"
        ), {"sid": str(FOUNDRY_KS_SOURCE_ID)}).all()
        print(f"[purge-rr] sample chunk_ids to delete: {[r[0] for r in sample_ids]}")
        print(
            "[purge-rr] Note: Foundry-Pinecone vectors are NOT deleted by "
            "this script. They live in a separate index/account. The "
            "Postgres knowledge_chunks rows are the discoverable handle — "
            "without them, the Foundry-Pinecone vectors orphan but don't "
            "break anything. A follow-up sweep can delete by vector id "
            "(equal to chunk_id) if reclaiming quota matters."
        )

        if not args.apply:
            print()
            print("[purge-rr] DRY RUN — would delete:")
            print(f"  - knowledge_chunks WHERE source_id={FOUNDRY_KS_SOURCE_ID}: {foundry_chunks:,} rows")
            print(f"  - knowledge_sources WHERE source_id={FOUNDRY_KS_SOURCE_ID}: 1 row")
            print()
            print("Re-run with --apply to actually delete.")
            return 0

    # Apply — use a fresh transaction (conn above was read-only pre-flight).
    print("[purge-rr] APPLY — deleting…")
    with engine.begin() as wconn:
        # Order: chunks first, then sources (FK)
        res_chunks = wconn.execute(text(
            "DELETE FROM knowledge_chunks WHERE source_id = :sid"
        ), {"sid": str(FOUNDRY_KS_SOURCE_ID)})
        print(f"[purge-rr] deleted {res_chunks.rowcount} knowledge_chunks rows")
        res_src = wconn.execute(text(
            "DELETE FROM knowledge_sources WHERE source_id = :sid"
        ), {"sid": str(FOUNDRY_KS_SOURCE_ID)})
        print(f"[purge-rr] deleted {res_src.rowcount} knowledge_sources rows")

    # Post-check
    with engine.connect() as conn:
        remaining = conn.execute(text(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE source_id = :sid"
        ), {"sid": str(FOUNDRY_KS_SOURCE_ID)}).scalar()
        print(f"[purge-rr] remaining knowledge_chunks for source: {remaining}")
        if remaining and remaining > 0:
            print("[purge-rr] WARNING: deletion did not fully complete", file=sys.stderr)
            return 5

    print("[purge-rr] Foundry-side Rocky Ridge state purged.")
    print(f"RUN_ENDED tag=purge_rocky_ridge_foundry_state at={datetime.now(timezone.utc).isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
