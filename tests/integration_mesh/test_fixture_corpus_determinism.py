# foundry: kind=test domain=client-intelligence-platform
"""M3 corpus determinism tests.

Per M3 §2.2 + §9 acceptance criterion #6: same seed + same Python version +
same Faker pin (``faker==40.15.0``) + ``PYTHONHASHSEED=0`` ⇒ byte-identical
corpus. Runs ONLY on Python 3.12 (the CI matrix's primary version) per the
constraint scope; other Python versions skip with reason.

Bumping Faker's version requires updating the snapshot below intentionally —
the snapshot is the M3 regression guard against silent corpus drift.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

from cip.integration_mesh.connectors.fixture.corpus import (
    CorpusSize,
    generate_corpus,
)


def _canonical_sha256(corpus: dict[str, list[dict[str, object]]]) -> str:
    """Hash the corpus via canonical JSON (sorted keys, no whitespace)."""
    return hashlib.sha256(
        json.dumps(corpus, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


_PRIMARY_PY = sys.version_info[:2] == (3, 12)
_PYTHONHASHSEED_OK = os.environ.get("PYTHONHASHSEED") in ("0", None)


class TestCorpusDeterminism:
    def test_same_seed_byte_identical(self) -> None:
        a = generate_corpus(seed=42, size=CorpusSize.STANDARD)
        b = generate_corpus(seed=42, size=CorpusSize.STANDARD)
        assert _canonical_sha256(a) == _canonical_sha256(b)

    def test_different_seeds_different_corpus(self) -> None:
        a = generate_corpus(seed=42, size=CorpusSize.COMPACT)
        b = generate_corpus(seed=43, size=CorpusSize.COMPACT)
        assert _canonical_sha256(a) != _canonical_sha256(b)

    def test_size_preset_counts(self) -> None:
        c_std = generate_corpus(seed=42, size=CorpusSize.STANDARD)
        c_cmp = generate_corpus(seed=42, size=CorpusSize.COMPACT)
        c_smk = generate_corpus(seed=42, size=CorpusSize.SMOKE)
        # STANDARD: 50/200/300/500/100/0 = 1150 (M3 §0 / Senior #11).
        assert sum(len(v) for v in c_std.values()) == 1150
        assert len(c_std["companies"]) == 50
        assert len(c_std["contacts"]) == 200
        assert len(c_std["deals"]) == 300
        assert len(c_std["tickets"]) == 500
        assert len(c_std["documents"]) == 100
        assert len(c_std["notes"]) == 0  # v2 #2: notes dropped
        # COMPACT: 5/20/30/50/10/0 = 115.
        assert sum(len(v) for v in c_cmp.values()) == 115
        # SMOKE: 0/10/0/0/0/0 = 10 (MockConnector-equivalent).
        assert sum(len(v) for v in c_smk.values()) == 10
        assert len(c_smk["contacts"]) == 10


@pytest.mark.skipif(
    not _PRIMARY_PY or not _PYTHONHASHSEED_OK,
    reason=(
        "Determinism snapshot scoped to Python 3.12 + PYTHONHASHSEED=0; "
        "cross-Python-version reproducibility not promised per M3 §2.2 + Stress #4"
    ),
)
class TestCorpusSnapshot:
    """Snapshot test — the regression guard against silent Faker drift.

    If this fails, EITHER (a) Faker pin was bumped without updating the
    snapshot, OR (b) corpus.py was changed in a way that shifts output. In
    case (a), update the snapshot HERE intentionally and document the bump
    in the commit message. In case (b), the change author owns determining
    whether the drift is intentional + updating the snapshot.

    Snapshot generated 2026-05-07 against faker==40.15.0 + Python 3.12.10
    + PYTHONHASHSEED=0. Captured via ``_canonical_sha256(generate_corpus(
    seed=42, size=CorpusSize.STANDARD))``.
    """

    # Snapshot SHA-256 of the canonical-JSON corpus.
    # Recorded 2026-05-07 on Python 3.12.10 + faker==40.15.0 + PYTHONHASHSEED=0.
    # Bumping Faker requires intentional update of this constant + a
    # commit-message note explaining the bump.
    _STANDARD_SEED42_SHA256 = (
        "9f06b2f77ef054bea435ab597571c4bb8f87a4b81d6d9b160862fb363f03b533"
    )

    def test_record_snapshot_matches(self) -> None:
        sha = _canonical_sha256(
            generate_corpus(seed=42, size=CorpusSize.STANDARD)
        )
        assert sha == self._STANDARD_SEED42_SHA256, (
            f"Corpus drift: got {sha}; expected {self._STANDARD_SEED42_SHA256}. "
            "Either Faker was bumped (update snapshot intentionally) or corpus.py "
            "changed (verify intent + update snapshot)."
        )
