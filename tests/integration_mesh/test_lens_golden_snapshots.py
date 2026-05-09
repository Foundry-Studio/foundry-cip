# foundry: kind=test domain=client-intelligence-platform
"""M4 lens-engine golden-file snapshot tests (M4 §5.4 binding).

Pattern matches M3's
``tests/integration_mesh/test_fixture_corpus_determinism.py::TestCorpusSnapshot``.
Each lens's canonical-JSON output (rows sorted by ``source_id``, non-deterministic
columns stripped) is hashed via SHA-256; the digest is locked as a constant.

Drift triggers (cause of snapshot mismatch):
- FixtureConnector's region distribution changes (Faker version bump).
- Lens engine compiler changes its predicate output.
- New columns added to ``cip_companies`` that change the SELECT shape.

When any of these fire, the test fails loudly. Update the snapshot only when
the drift is intentional + explained in commit message.

Per acceptance #22 + Gap [13]: snapshot tests pinned to Python 3.12 +
``PYTHONHASHSEED=0`` (corpus determinism contract per M3 §2.2).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cip.integration_mesh import (
    CorpusSize,
    FixtureConnector,
    FixtureMapper,
    lens_query_for_table,
    run_sync,
)
from cip.integration_mesh.tenant_context import apply_tenant_context
from tests.integration_mesh.conftest import (
    LENS_A_FILTER_CONFIG,
    LENS_B_FILTER_CONFIG,
    seed_lens,
    session_as_role_and_tenant,
)

# ── Snapshot scoping ──────────────────────────────────────────────────────


_PRIMARY_PY = sys.version_info[:2] == (3, 12)
_PYTHONHASHSEED_OK = os.environ.get("PYTHONHASHSEED") in ("0", None)


# ── Canonicalization helpers ───────────────────────────────────────────────


# Columns that vary per test-run and must be stripped before hashing.
# (UUIDs from server defaults, per-run timestamps, per-run batch ids.)
_NON_DETERMINISTIC_COLS: frozenset[str] = frozenset(
    {
        "id",
        "tenant_id",
        "ingestion_batch_id",
        "ingested_at",
        "refreshed_at",
        "created_at",
        "updated_at",
        "previous_version_id",
    }
)


def _canonicalize_lens_output(rows: Sequence[Any]) -> str:
    """Sort rows by ``source_id``, strip non-deterministic columns, return
    canonical JSON. Same shape as M3's ``_canonical_sha256``."""
    items: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row._mapping)  # noqa: SLF001  # SQLAlchemy Row → dict
        for k in _NON_DETERMINISTIC_COLS:
            d.pop(k, None)
        items.append(d)
    items.sort(key=lambda r: str(r["source_id"]))
    return json.dumps(items, sort_keys=True, default=str)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _reflect_companies(engine: Engine) -> sa.Table:
    md = sa.MetaData()
    md.reflect(bind=engine, only=["cip_companies"])
    return md.tables["cip_companies"]


# ── Snapshot harness — fresh tenant per test, deterministic via seed=42 ────


def _run_lens_against_standard(
    seeded_engine: Engine,
    database_url: str,
    *,
    view_name: str,
    filter_config: dict[str, Any],
) -> str:
    """Provision a fresh tenant + STANDARD corpus, seed the named lens,
    apply it under role-enforced tenant context, return the canonical SHA."""
    tenant_id = uuid4()
    run_sync(
        FixtureConnector(
            tenant_id=tenant_id, seed=42, size=CorpusSize.STANDARD
        ),
        FixtureMapper(),
        seeded_engine,
        tenant_id=tenant_id,
        database_url=database_url,
    )
    with Session(seeded_engine, autoflush=False) as db, db.begin():
        apply_tenant_context(db, tenant_id)
        seed_lens(
            db,
            tenant_id=tenant_id,
            view_name=view_name,
            filter_config=filter_config,
            target_table="cip_companies",
        )

    companies = _reflect_companies(seeded_engine)
    with session_as_role_and_tenant(seeded_engine, tenant_id) as conn:
        query = lens_query_for_table(
            conn,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            view_name=view_name,
            target_table=companies,
        )
        rows = conn.execute(query).all()
    return _sha256(_canonicalize_lens_output(rows))


# ── Locked snapshot SHAs (re-record only when drift is intentional) ────────


# Snapshot SHA-256 of Lens-A (filter_config={}) over FixtureConnector
# STANDARD corpus seed=42, captured 2026-05-09 against:
#   - Python 3.12.10
#   - faker==40.15.0
#   - PYTHONHASHSEED=0
#   - foundry-cip HEAD post-M4-Δ2/Δ3
#
# Bumping requires intent. If this fails: EITHER the corpus regenerated
# (Faker bump? — see M3 corpus-determinism tracker), OR the lens engine
# changed its column selection / predicate output, OR a new column landed
# on cip_companies via a future migration.
_LENS_A_STANDARD_SEED42_SHA256: str = (
    "8c384082678d261d97ee30ca22ba49fc14e0713a625270074f8ae1f2a14e5e93"
)

_LENS_B_STANDARD_SEED42_SHA256: str = (
    "a11b830c57dd5adf3d309aa1b9aa35a3296d3cc8e8a7461b4cd6889cfe165c55"
)


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not _PRIMARY_PY or not _PYTHONHASHSEED_OK,
    reason=(
        "Lens-engine snapshot scoped to Python 3.12 + PYTHONHASHSEED=0; "
        "cross-Python-version corpus reproducibility not promised "
        "(M3 §2.2 + M4 acceptance #22)"
    ),
)
class TestLensSnapshot:
    """Snapshot regression tests — canonical-JSON SHA-256 of lens output.

    Failure modes documented at module top.
    """

    def test_lens_a_canonical_output_matches_snapshot(
        self, seeded_engine: Engine, database_url: str
    ) -> None:
        sha = _run_lens_against_standard(
            seeded_engine,
            database_url,
            view_name="snapshot_lens_a",
            filter_config=LENS_A_FILTER_CONFIG,
        )
        assert sha == _LENS_A_STANDARD_SEED42_SHA256, (
            f"Lens-A snapshot drift: got {sha}; "
            f"expected {_LENS_A_STANDARD_SEED42_SHA256}. "
            "Either the corpus regenerated (Faker bump / corpus.py edit) "
            "or the lens engine changed output shape. Verify intent + "
            "update the constant."
        )

    def test_lens_b_canonical_output_matches_snapshot(
        self, seeded_engine: Engine, database_url: str
    ) -> None:
        sha = _run_lens_against_standard(
            seeded_engine,
            database_url,
            view_name="snapshot_lens_b",
            filter_config=LENS_B_FILTER_CONFIG,
        )
        assert sha == _LENS_B_STANDARD_SEED42_SHA256, (
            f"Lens-B snapshot drift: got {sha}; "
            f"expected {_LENS_B_STANDARD_SEED42_SHA256}. "
            "Either the corpus regenerated or the eu-west subset shifted. "
            "Verify intent + update the constant."
        )
