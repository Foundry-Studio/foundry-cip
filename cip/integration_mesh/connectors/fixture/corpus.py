# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Deterministic synthetic corpus generation for FixtureConnector (M3 §4.4 binding).

Uses ``Faker.seed_instance(int)`` for shape generation + a SEPARATE stdlib
``random.Random(seed)`` for SELECTION (FK picks, weighted-choice draws). Two
RNGs is intentional — adding a Faker call upstream doesn't shift downstream
selection state, which is critical for the byte-identical determinism contract.

Determinism contract (per v2 §2.2 + Stress #4):
  same Python version + same Faker pin + ``PYTHONHASHSEED=0`` ⇒ byte-identical
  corpus across two same-seed instances. Cross-Python-version reproducibility
  is NOT promised. Faker version is pinned exact (``faker==X.Y.Z``) in
  pyproject.toml's ``[fixture]`` extra.

Per-type buckets (v2 #2: notes count = 0; the bucket exists for forward
compat but is empty in STANDARD):
  ``companies``, ``contacts``, ``deals``, ``tickets``, ``documents``, ``notes``.

STANDARD corpus shape (post-v2 reconciliation):
  50 companies + 200 contacts + 300 deals + 500 tickets + 100 documents +
  0 notes = exactly **1150 rows**.

The discriminator key on each record is ``record_type`` (not ``__type``;
see records.py header for M3 Δ1 reconciliation).
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from faker import Faker

# Per v2 #2 (Senior #2): notes intentionally generated at count 0 in STANDARD;
# bucket retained for forward-compatibility with a future cip_notes migration.


class CorpusSize(Enum):
    """Preset corpus sizes for FixtureConnector."""

    STANDARD = "standard"  # 50/200/300/500/100/0 = 1150 rows (Phase 1 ROADMAP)
    COMPACT = "compact"  # 5/20/30/50/10/0 = 115 rows (10× smaller, fast unit tests)
    SMOKE = "smoke"  # 0/10/0/0/0/0 = 10 rows (MockConnector-equivalent)


_COUNTS_BY_SIZE: dict[CorpusSize, dict[str, int]] = {
    CorpusSize.STANDARD: {
        "companies": 50,
        "contacts": 200,
        "deals": 300,
        "tickets": 500,
        "documents": 100,
        "notes": 0,
    },
    CorpusSize.COMPACT: {
        "companies": 5,
        "contacts": 20,
        "deals": 30,
        "tickets": 50,
        "documents": 10,
        "notes": 0,
    },
    CorpusSize.SMOKE: {
        # MockConnector-equivalent for fast smoke tests + e2e_smoke.
        # 10 contacts only; mirrors M2's CANONICAL_CONTACTS shape.
        "companies": 0,
        "contacts": 10,
        "deals": 0,
        "tickets": 0,
        "documents": 0,
        "notes": 0,
    },
}


# Deterministic timestamp base. All updated_at values are derived as
# _T0 + offset_hours so the clock is reproducible and ordered by type.
_T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

# Per-type hour offset. Companies start at hour 0; contacts at hour 1000;
# deals at 2000; tickets at 3000; documents at 4000; notes at 5000. The
# ranges don't overlap so cursor-driven incremental sync ordering is stable.
_HOUR_OFFSET_BY_TYPE: dict[str, int] = {
    "companies": 0,
    "contacts": 1000,
    "deals": 2000,
    "tickets": 3000,
    "documents": 4000,
    "notes": 5000,
}


def _ts(hours_offset: int) -> str:
    """Deterministic timestamp: T0 + hours_offset hours, ISO-8601 UTC tz-aware."""
    return (_T0 + timedelta(hours=hours_offset)).isoformat()


# Weighted enums for selection determinism. ``random.Random(seed).choices(...)``
# is deterministic for the same seed.
_DEAL_STAGES = ["qualifying", "negotiating", "closed_won", "closed_lost"]
_DEAL_STAGE_WEIGHTS = [40, 30, 20, 10]
_TICKET_STATUSES = ["open", "pending", "resolved", "closed"]
_TICKET_STATUS_WEIGHTS = [25, 25, 25, 25]
_TICKET_PRIORITIES = ["low", "normal", "high", "urgent"]
_TICKET_PRIORITY_WEIGHTS = [40, 35, 20, 5]
_INDUSTRIES = ["software", "finance", "retail", "healthcare", "manufacturing"]
_REGIONS = ["us-east", "us-west", "eu-west", "apac", "latam"]
_MIME_TYPES = ["application/pdf", "text/plain"]


def generate_corpus(
    seed: int, size: CorpusSize = CorpusSize.STANDARD
) -> dict[str, list[dict[str, Any]]]:
    """Generate the deterministic corpus.

    Args:
        seed: integer seed. Same seed + same env (Python version, Faker pin,
            ``PYTHONHASHSEED=0``) yields byte-identical output.
        size: corpus preset (STANDARD / COMPACT / SMOKE).

    Returns:
        Dict keyed by object_type with sorted-by-source_id lists of record dicts.
    """
    faker = Faker(locale="en_US")
    faker.seed_instance(seed)
    rng = random.Random(seed)

    counts = _COUNTS_BY_SIZE[size]
    corpus: dict[str, list[dict[str, Any]]] = {
        "companies": [],
        "contacts": [],
        "deals": [],
        "tickets": [],
        "documents": [],
        "notes": [],
    }

    _generate_companies(faker, rng, corpus, counts["companies"])
    _generate_contacts(faker, rng, corpus, counts["contacts"], size)
    _generate_deals(faker, rng, corpus, counts["deals"])
    _generate_tickets(faker, rng, corpus, counts["tickets"])
    _generate_documents(faker, rng, corpus, counts["documents"])
    _generate_notes(faker, rng, corpus, counts["notes"])

    return corpus


# ── Per-type generators ────────────────────────────────────────────────────


def _generate_companies(
    faker: Faker, rng: random.Random, corpus: dict[str, list[dict[str, Any]]], n: int
) -> None:
    base = _HOUR_OFFSET_BY_TYPE["companies"]
    for i in range(n):
        sid = f"co{i + 1:04d}"
        rec: dict[str, Any] = {
            "record_type": "company",
            "source_id": sid,
            "id": sid,
            "updated_at": _ts(base + i),
            "name": faker.company(),
            "industry": rng.choice(_INDUSTRIES),
            "region": rng.choice(_REGIONS),
            "employee_count": rng.randint(10, 5000),
            "annual_revenue": round(rng.uniform(100_000, 500_000_000), 2),
            "domain": faker.domain_name(),
            "custom_field_1": faker.word(),
            "custom_field_2": faker.word(),
        }
        corpus["companies"].append(rec)


def _generate_contacts(
    faker: Faker,
    rng: random.Random,
    corpus: dict[str, list[dict[str, Any]]],
    n: int,
    size: CorpusSize,
) -> None:
    base = _HOUR_OFFSET_BY_TYPE["contacts"]
    companies = corpus["companies"]
    for i in range(n):
        sid = f"c{i + 1:04d}"
        # SMOKE size mirrors M2 CANONICAL_CONTACTS naming for parity.
        if size == CorpusSize.SMOKE:
            sid = f"c{i + 1:03d}"
        rec: dict[str, Any] = {
            "record_type": "contact",
            "source_id": sid,
            "id": sid,
            "updated_at": _ts(base + i),
            "first_name": faker.first_name(),
            "last_name": faker.last_name(),
            "email": faker.email(),
        }
        if companies:
            rec["company_source_id"] = rng.choice(companies)["source_id"]
            rec["title"] = faker.job()
            rec["phone"] = faker.phone_number()
            rec["region"] = rng.choice(_REGIONS)
        corpus["contacts"].append(rec)


def _generate_deals(
    faker: Faker, rng: random.Random, corpus: dict[str, list[dict[str, Any]]], n: int
) -> None:
    base = _HOUR_OFFSET_BY_TYPE["deals"]
    companies = corpus["companies"]
    for i in range(n):
        sid = f"d{i + 1:04d}"
        rec: dict[str, Any] = {
            "record_type": "deal",
            "source_id": sid,
            "id": sid,
            "updated_at": _ts(base + i),
            "name": f"{faker.bs().title()} deal",
            "amount": round(rng.uniform(1_000, 500_000), 2),
            "stage": rng.choices(_DEAL_STAGES, weights=_DEAL_STAGE_WEIGHTS, k=1)[0],
        }
        if companies:
            rec["company_source_id"] = rng.choice(companies)["source_id"]
            # Reference base ``_T0`` (not ``datetime.now()``) so the corpus
            # is byte-identical across days. Wall-clock time would shift
            # ``expected_close_date`` daily, breaking the snapshot guard.
            close_offset = rng.randint(7, 365)
            rec["expected_close_date"] = (
                (_T0 + timedelta(days=close_offset)).date().isoformat()
            )
            rec["owner"] = faker.name()
        corpus["deals"].append(rec)


def _generate_tickets(
    faker: Faker, rng: random.Random, corpus: dict[str, list[dict[str, Any]]], n: int
) -> None:
    base = _HOUR_OFFSET_BY_TYPE["tickets"]
    contacts = corpus["contacts"]
    for i in range(n):
        sid = f"t{i + 1:04d}"
        body_paragraphs = faker.paragraphs(nb=rng.randint(1, 3))
        body = " ".join(body_paragraphs)
        rec: dict[str, Any] = {
            "record_type": "ticket",
            "source_id": sid,
            "id": sid,
            "updated_at": _ts(base + i),
            "subject": faker.sentence(nb_words=6),
            "body": body,
            "status": rng.choices(
                _TICKET_STATUSES, weights=_TICKET_STATUS_WEIGHTS, k=1
            )[0],
            "priority": rng.choices(
                _TICKET_PRIORITIES, weights=_TICKET_PRIORITY_WEIGHTS, k=1
            )[0],
        }
        if contacts:
            rec["contact_source_id"] = rng.choice(contacts)["source_id"]
            rec["assignee"] = faker.name()
        corpus["tickets"].append(rec)


def _generate_documents(
    faker: Faker, rng: random.Random, corpus: dict[str, list[dict[str, Any]]], n: int
) -> None:
    base = _HOUR_OFFSET_BY_TYPE["documents"]
    companies = corpus["companies"]
    for i in range(n):
        sid = f"doc{i + 1:04d}"
        body_paragraphs = faker.paragraphs(nb=rng.randint(2, 5))
        body = " ".join(body_paragraphs)
        rec: dict[str, Any] = {
            "record_type": "document",
            "source_id": sid,
            "id": sid,
            "updated_at": _ts(base + i),
            "title": faker.sentence(nb_words=5),
            "body": body,
            "mime_type": rng.choice(_MIME_TYPES),
            "file_size_bytes": rng.randint(1024, 10_485_760),
        }
        if companies:
            rec["company_source_id"] = rng.choice(companies)["source_id"]
        corpus["documents"].append(rec)


def _generate_notes(
    faker: Faker, rng: random.Random, corpus: dict[str, list[dict[str, Any]]], n: int
) -> None:
    """Per v2 #2: STANDARD ships 0 notes. Generator retained for forward-compat."""
    base = _HOUR_OFFSET_BY_TYPE["notes"]
    contacts = corpus["contacts"]
    for i in range(n):
        sid = f"n{i + 1:04d}"
        rec: dict[str, Any] = {
            "record_type": "note",
            "source_id": sid,
            "id": sid,
            "updated_at": _ts(base + i),
            "body": faker.paragraph(nb_sentences=rng.randint(2, 5)),
            "author": faker.name(),
        }
        if contacts:
            rec["contact_source_id"] = rng.choice(contacts)["source_id"]
        corpus["notes"].append(rec)
