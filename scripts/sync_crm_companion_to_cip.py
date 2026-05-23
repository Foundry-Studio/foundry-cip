"""Phase 2.8 Leg B — orchestration entry for CRM → CIP companion writeback.

Reads PS-team enrichments from the Foundry-CRM Postgres and writes them
into ``cip_clients.companion_data`` on the matching PS-tenant rows via
the ``cip_twenty_project_silk`` role.

ENV (live run):
    CRM_DATABASE_URL              read-only credential to CRM Postgres
    CIP_DATABASE_URL              CIP Postgres host (NO embedded creds —
                                  the script builds the URL with the
                                  twenty role + password below)
    TWENTY_PROJECT_SILK_DB_PASSWORD   the cip_twenty_project_silk password
                                  (Railway secret; refuse to start if
                                  unset or equal to the test sentinel)

Usage::

    CRM_DATABASE_URL=postgresql://reader:pw@crm-host/db \\
    CIP_DATABASE_URL=postgresql://cip-host:5432/railway \\
    TWENTY_PROJECT_SILK_DB_PASSWORD=… \\
    python scripts/sync_crm_companion_to_cip.py

Cadence: scheduled poll (15–30 min recommended for v1). Idempotent —
running more often only burns CRM reads.

Tier B: no CIP migration; the companion_data column + role already
exist (cip_23 + cip_25). The script is a thin wrapper around
``cip.integration_mesh.sync.crm_companion_writeback.run_writeback``.
"""
from __future__ import annotations

import json
import logging
import os
import sys

from sqlalchemy import create_engine

from cip.integration_mesh.sync.crm_companion_writeback import run_writeback

# Match cip_25's test sentinel — refuse to use this in prod.
_TEST_PASSWORD_SENTINEL = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105
_TWENTY_ROLE = "cip_twenty_project_silk"

# ``RUN_MODE=test`` lets the runner pass the sentinel locally without the
# loud-fail guard tripping (used by tests + dev orchestration). Production
# orchestration MUST NOT set this.
_RUN_MODE_TEST_SENTINEL = "test"


def _scrub_url(url: str) -> str:
    """Best-effort scrub the password component for logging."""
    try:
        from sqlalchemy.engine.url import make_url
        u = make_url(url)
        if u.password:
            u = u.set(password="***")
        return str(u)
    except Exception:
        return "<unparseable url>"


def _build_cip_url(base_url: str, password: str) -> str:
    """Replace the username + password in ``base_url`` with the twenty
    role credentials. ``base_url`` MUST NOT carry embedded creds in prod
    usage — we deliberately rebuild the URL ourselves so callers can
    point at the bare host + db and never leak a superuser DSN.
    """
    from sqlalchemy.engine.url import make_url
    u = make_url(base_url)
    # Force psycopg v3 dialect — the repo standardized away from psycopg2.
    drivername = u.drivername
    if drivername == "postgresql":
        drivername = "postgresql+psycopg"
    elif drivername.startswith("postgresql+psycopg2"):
        drivername = drivername.replace("psycopg2", "psycopg")
    u = u.set(
        drivername=drivername,
        username=_TWENTY_ROLE,
        password=password,
    )
    return str(u)


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("scripts.sync_crm_companion_to_cip")

    crm_url = os.environ.get("CRM_DATABASE_URL")
    cip_url = os.environ.get("CIP_DATABASE_URL")
    pw = os.environ.get("TWENTY_PROJECT_SILK_DB_PASSWORD", "")
    run_mode = os.environ.get("RUN_MODE", "").lower()

    if not crm_url:
        log.error("CRM_DATABASE_URL is required")
        return 2
    if not cip_url:
        log.error("CIP_DATABASE_URL is required")
        return 2
    if not pw:
        log.error(
            "TWENTY_PROJECT_SILK_DB_PASSWORD is required — refusing to "
            "connect. Set it in Railway + ALTER ROLE cip_twenty_project_silk "
            "PASSWORD <secret> before running."
        )
        return 2
    if pw == _TEST_PASSWORD_SENTINEL and run_mode != _RUN_MODE_TEST_SENTINEL:
        log.error(
            "refusing to run with the test password sentinel "
            "(TWENTY_PROJECT_SILK_DB_PASSWORD = sentinel) outside RUN_MODE=test."
        )
        return 2

    crm_url_built = crm_url
    if crm_url_built.startswith("postgresql://"):
        crm_url_built = crm_url_built.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )

    try:
        cip_url_built = _build_cip_url(cip_url, pw)
    except Exception as exc:  # noqa: BLE001
        # Never echo password or full DSN — log only the safe parts.
        log.error("failed to build CIP URL: %s", type(exc).__name__)
        return 3

    log.info("CRM URL: %s", _scrub_url(crm_url_built))
    log.info("CIP URL: %s (role=%s)", _scrub_url(cip_url_built), _TWENTY_ROLE)

    # Pool size = 1 — Leg B is a single-threaded scheduled job.
    crm_engine = create_engine(crm_url_built, pool_size=1, max_overflow=0)
    cip_engine = create_engine(cip_url_built, pool_size=1, max_overflow=0)

    try:
        summary = run_writeback(crm_engine=crm_engine, cip_engine=cip_engine)
    except Exception:
        log.exception("Leg B writeback failed")
        return 1
    finally:
        cip_engine.dispose()
        crm_engine.dispose()

    # One structured line for ingestion by log scrapers.
    print(
        "LEG_B_RUN_SUMMARY " + json.dumps(summary.to_dict(), sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
