# foundry: kind=test domain=client-intelligence-platform
"""The knowledge hook must actually write, and must never drop quietly.

``ingest_texts_noop`` was an unconditional no-op from M2 until 2026-09-04: a
connector could emit valid KnowledgeText, the orchestrator would finalize and
validate it, and nothing wrote anything. These cover the sink that replaces
that silence, and the dispatch seam in the hook itself.

The failure-path tests matter more than the happy path here. Per D-067 the
orchestrator treats a non-validation exception from this hook as NON-FATAL: it
logs one warning and the run still reports success. Anything the sink drops
quietly is therefore dropped for good.
"""
from __future__ import annotations

import logging
from uuid import uuid4

import pytest

from cip.integration_mesh import knowledge_hook
from cip.integration_mesh.base import KnowledgeText
from cip.integration_mesh.knowledge.chunk_sink import KnowledgeChunkSink
from cip.integration_mesh.knowledge.tombstone import vector_id_for

TENANT = uuid4()
KIND = "cip_client_document"


class FakeEmbedding:
    model_id = "test-model/q8/2560"

    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.fail_on = fail_on or set()
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        if text in self.fail_on:
            raise RuntimeError("embedding backend down")
        return [0.1, 0.2, 0.3]


class FakePinecone:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.upserts: list[tuple[str, list]] = []

    def upsert(self, *, namespace: str, vectors: list) -> dict:
        if self.fail:
            raise RuntimeError("pinecone 503")
        self.upserts.append((namespace, vectors))
        return {"upserted": len(vectors)}


class FakeSession:
    def __init__(self) -> None:
        self.executed: list[dict] = []

    def execute(self, _stmt, params=None):  # noqa: ANN001, ANN202
        self.executed.append(params or {})
        return None


def _kt(i: int, total: int = 2, body: str = "content") -> KnowledgeText:
    return KnowledgeText(
        text=f"{body} {i}",
        metadata={"source_id": "r2/a.pdf", "chunk_index": i, "total_chunks": total},  # type: ignore[typeddict-unknown-key]
    )


def _sink(db, emb, pc=None) -> KnowledgeChunkSink:
    return KnowledgeChunkSink(
        db=db, tenant_id=TENANT, embedding_client=emb,  # type: ignore[arg-type]
        source_kind=KIND, pinecone=pc,  # type: ignore[arg-type]
    )


# ── The hook dispatch seam ────────────────────────────────────────────────


def test_default_hook_is_a_no_op_that_counts_what_it_discards() -> None:
    """A no-op is a real state, not a placeholder. A run producing thousands of
    texts and indexing none of them must be able to say so — the corpus this
    feeds sat frozen from 2026-05-22 with nobody noticing."""
    knowledge_hook.set_knowledge_sink(None)
    knowledge_hook.reset_discarded_count()
    knowledge_hook.ingest_texts_noop([_kt(0), _kt(1)])
    assert knowledge_hook.discarded_text_count == 2


def test_a_registered_sink_receives_the_texts() -> None:
    seen: list[list[KnowledgeText]] = []
    knowledge_hook.set_knowledge_sink(seen.append)
    try:
        knowledge_hook.ingest_texts_noop([_kt(0)])
    finally:
        knowledge_hook.set_knowledge_sink(None)
    assert len(seen) == 1 and len(seen[0]) == 1


def test_the_sink_can_be_restored_so_runs_do_not_leak_into_each_other() -> None:
    knowledge_hook.set_knowledge_sink(lambda _t: None)
    assert knowledge_hook.get_knowledge_sink() is not None
    knowledge_hook.set_knowledge_sink(None)
    assert knowledge_hook.get_knowledge_sink() is None


# ── Writing ───────────────────────────────────────────────────────────────


def test_every_text_is_embedded_and_written() -> None:
    db, emb = FakeSession(), FakeEmbedding()
    s = _sink(db, emb)
    s([_kt(0), _kt(1)])
    assert s.result.received == 2
    assert s.result.embedded == 2
    assert s.result.postgres_written == 2
    assert len(db.executed) == 2
    assert s.result.clean


def test_written_rows_carry_the_configured_source_kind() -> None:
    """The discriminator that protects the row-derived producer. If the sink
    wrote a different kind, a later scoped purge would miss these rows."""
    db = FakeSession()
    _sink(db, FakeEmbedding())([_kt(0)])
    assert db.executed[0]["source_kind"] == KIND


def test_embedding_dimension_is_recorded_from_the_vector() -> None:
    db = FakeSession()
    _sink(db, FakeEmbedding())([_kt(0)])
    assert db.executed[0]["embedding_dim"] == 3


def test_pinecone_ids_match_the_shared_convention() -> None:
    """Both write paths and the delete path must agree on the id, or deletion
    leaves orphaned vectors nothing can find."""
    pc = FakePinecone()
    _sink(FakeSession(), FakeEmbedding(), pc)([_kt(0), _kt(1)])
    (_ns, vectors), = pc.upserts
    assert [v.id for v in vectors] == [
        vector_id_for(KIND, "r2/a.pdf", 0),
        vector_id_for(KIND, "r2/a.pdf", 1),
    ]


# ── Failure paths, which is why this class exists ─────────────────────────


def test_an_embedding_failure_is_counted_and_logged_not_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = FakeSession()
    emb = FakeEmbedding(fail_on={"content 0"})
    s = _sink(db, emb)
    with caplog.at_level(logging.WARNING):
        s([_kt(0), _kt(1)])

    assert s.result.embed_failures == 1
    assert s.result.postgres_written == 1, "the healthy chunk must still land"
    assert not s.result.clean, "a run with a dropped chunk is not clean"
    assert s.result.errors, "the failure must be recorded on the result"
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_a_pinecone_failure_is_counted_and_says_the_stores_now_disagree(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Postgres already has the rows at this point. Reporting it plainly is the
    difference between drift that gets found and drift that does not."""
    db = FakeSession()
    s = _sink(db, FakeEmbedding(), FakePinecone(fail=True))
    with caplog.at_level(logging.WARNING):
        s([_kt(0), _kt(1)])

    assert s.result.postgres_written == 2
    assert s.result.pinecone_upserted == 0
    assert s.result.pinecone_failures == 2
    assert not s.result.clean
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "Postgres" in msg and "NOT searchable" in msg


def test_clean_is_false_when_anything_was_dropped() -> None:
    s = _sink(FakeSession(), FakeEmbedding(fail_on={"content 0"}))
    s([_kt(0)])
    assert not s.result.clean


def test_no_pinecone_client_means_no_upsert_and_no_false_success() -> None:
    s = _sink(FakeSession(), FakeEmbedding())
    s([_kt(0)])
    assert s.result.pinecone_upserted == 0
    assert s.result.pinecone_failures == 0


def test_empty_input_is_a_no_op() -> None:
    db = FakeSession()
    s = _sink(db, FakeEmbedding())
    s([])
    assert s.result.received == 0
    assert db.executed == []
