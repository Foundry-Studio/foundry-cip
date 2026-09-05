# foundry: kind=test domain=client-intelligence-platform
"""Tombstoning a file must remove its derived chunks from BOTH stores.

CIP-SPEC-014 ruling 3 as amended (PM decision 7d1c0148, option (a)). The
original ruling required every retrieval path to filter tombstoned chunks,
which was unimplementable: the retriever queries cip_knowledge_chunks directly
and never joins cip_files, where tombstoned_at lives. Deleting the derived rows
makes the property structural instead.

The two properties worth testing are the ones that look fine on a happy path:
the delete is SCOPED (or it destroys the row-derived producer's chunks), and it
is ORDERED Pinecone-first (or a Pinecone failure leaves Postgres claiming the
chunks are gone while a vector search still returns them).
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cip.integration_mesh.clients.pinecone import namespace_for
from cip.integration_mesh.knowledge.tombstone import (
    count_disagreements,
    purge_file_chunks,
    vector_id_for,
)
from cip.integration_mesh.tenant_context import apply_tenant_context

DOC_KIND = "cip_client_document"
ROW_KIND = "cip_ticket_comment"


class FakePinecone:
    """Records deletes. Can be told to fail, which is the interesting case."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[tuple[str, list[str]]] = []
        self.stats: dict = {"namespaces": {}}

    def delete(self, *, namespace: str, ids: list[str]) -> dict:
        if self.fail:
            raise RuntimeError("pinecone 503")
        self.deleted.append((namespace, list(ids)))
        return {"deleted": len(ids)}

    def describe_index_stats(self) -> dict:
        return self.stats


def _insert_chunk(
    db: Session, *, tenant_id, source_kind: str, source_id: str, idx: int
) -> None:
    db.execute(
        text(
            "INSERT INTO cip_knowledge_chunks ("
            "  id, tenant_id, source_kind, source_id, chunk_index, total_chunks,"
            "  content, content_hash, content_chars, embedding, embedding_dim,"
            "  embedding_model, metadata, embedded_at, created_at, updated_at"
            ") VALUES ("
            "  gen_random_uuid(), :t, :sk, :si, :i, 3,"
            "  :c, :h, :n, :emb, 3,"
            "  'test-model', '{}'::jsonb, now(), now(), now()"
            ")"
        ),
        {
            "t": str(tenant_id), "sk": source_kind, "si": source_id, "i": idx,
            "c": f"chunk {idx} of {source_id}", "h": f"hash-{source_id}-{idx}",
            "n": 20, "emb": [0.1, 0.2, 0.3],
        },
    )


# ── Unit: ordering and scoping, no database needed ────────────────────────


def test_vector_id_matches_the_upsert_convention() -> None:
    """Deletion reconstructs what upsert produced. A drift here leaves
    orphaned vectors that no delete ever finds."""
    assert vector_id_for(DOC_KIND, "abc", 0) == f"cip-{DOC_KIND}-abc-0"


# ── Postgres-backed ───────────────────────────────────────────────────────


@pytest.mark.requires_postgres
def test_purge_deletes_the_files_chunks(seeded_engine: Engine) -> None:
    tenant, src = uuid4(), "r2/key/a.pdf"
    with Session(seeded_engine) as db:
        apply_tenant_context(db, tenant)
        for i in range(3):
            _insert_chunk(db, tenant_id=tenant, source_kind=DOC_KIND,
                          source_id=src, idx=i)
        db.commit()

        apply_tenant_context(db, tenant)
        pc = FakePinecone()
        res = purge_file_chunks(db, tenant_id=tenant, source_kind=DOC_KIND,
                                source_id=src, pinecone=pc)
        db.commit()

        assert res.chunks_found == 3
        assert res.postgres_deleted == 3
        assert res.pinecone_deleted == 3

        apply_tenant_context(db, tenant)
        left = db.execute(
            text("SELECT count(*) FROM cip_knowledge_chunks "
                 "WHERE tenant_id=:t AND source_id=:si"),
            {"t": str(tenant), "si": src},
        ).scalar()
        assert left == 0


@pytest.mark.requires_postgres
def test_purge_does_not_touch_the_row_derived_producer(
    seeded_engine: Engine,
) -> None:
    """THE SCOPING INVARIANT. cip_knowledge_chunks holds chunks from a second
    producer. An unscoped delete would destroy them, and nothing downstream
    would report it."""
    tenant, src = uuid4(), "shared-source-id"
    with Session(seeded_engine) as db:
        apply_tenant_context(db, tenant)
        # Same source_id, different source_kind — the adversarial case.
        _insert_chunk(db, tenant_id=tenant, source_kind=DOC_KIND,
                      source_id=src, idx=0)
        _insert_chunk(db, tenant_id=tenant, source_kind=ROW_KIND,
                      source_id=src, idx=0)
        db.commit()

        apply_tenant_context(db, tenant)
        purge_file_chunks(db, tenant_id=tenant, source_kind=DOC_KIND,
                          source_id=src, pinecone=FakePinecone())
        db.commit()

        apply_tenant_context(db, tenant)
        survivors = db.execute(
            text("SELECT source_kind FROM cip_knowledge_chunks "
                 "WHERE tenant_id=:t AND source_id=:si"),
            {"t": str(tenant), "si": src},
        ).scalars().all()
        assert survivors == [ROW_KIND], (
            "the row-derived producer's chunk was destroyed by a document purge"
        )


@pytest.mark.requires_postgres
def test_a_pinecone_failure_leaves_postgres_intact(seeded_engine: Engine) -> None:
    """THE ORDERING INVARIANT.

    Deleting Postgres first would, on a Pinecone failure, leave the database
    saying the chunks are gone while a vector search still returned them:
    retrievable content nothing knows about. Pinecone-first fails safe — both
    stores keep the rows and the retry is well-defined.
    """
    tenant, src = uuid4(), "r2/key/b.pdf"
    with Session(seeded_engine) as db:
        apply_tenant_context(db, tenant)
        for i in range(2):
            _insert_chunk(db, tenant_id=tenant, source_kind=DOC_KIND,
                          source_id=src, idx=i)
        db.commit()

        apply_tenant_context(db, tenant)
        with pytest.raises(RuntimeError, match="pinecone 503"):
            purge_file_chunks(db, tenant_id=tenant, source_kind=DOC_KIND,
                              source_id=src, pinecone=FakePinecone(fail=True))
        db.rollback()

        apply_tenant_context(db, tenant)
        left = db.execute(
            text("SELECT count(*) FROM cip_knowledge_chunks "
                 "WHERE tenant_id=:t AND source_id=:si"),
            {"t": str(tenant), "si": src},
        ).scalar()
        assert left == 2, (
            "Postgres rows were deleted despite the Pinecone delete failing"
        )


@pytest.mark.requires_postgres
def test_purge_targets_the_right_namespace_and_ids(seeded_engine: Engine) -> None:
    tenant, src = uuid4(), "r2/key/c.pdf"
    with Session(seeded_engine) as db:
        apply_tenant_context(db, tenant)
        for i in range(2):
            _insert_chunk(db, tenant_id=tenant, source_kind=DOC_KIND,
                          source_id=src, idx=i)
        db.commit()

        apply_tenant_context(db, tenant)
        pc = FakePinecone()
        purge_file_chunks(db, tenant_id=tenant, source_kind=DOC_KIND,
                          source_id=src, pinecone=pc)
        db.commit()

    (ns, ids), = pc.deleted
    assert ns == namespace_for(tenant, None)
    assert ids == [vector_id_for(DOC_KIND, src, 0), vector_id_for(DOC_KIND, src, 1)]


@pytest.mark.requires_postgres
def test_purging_a_file_with_no_chunks_is_a_no_op(seeded_engine: Engine) -> None:
    tenant = uuid4()
    with Session(seeded_engine) as db:
        apply_tenant_context(db, tenant)
        pc = FakePinecone()
        res = purge_file_chunks(db, tenant_id=tenant, source_kind=DOC_KIND,
                                source_id="never-existed", pinecone=pc)
    assert res.chunks_found == 0
    assert pc.deleted == [], "must not issue an empty Pinecone delete"


@pytest.mark.requires_postgres
def test_purge_without_a_pinecone_client_warns_rather_than_pretending(
    seeded_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    """A Postgres-only purge leaves the vectors retrievable. That is sometimes
    acceptable, but it must never read as a completed removal."""
    import logging

    tenant, src = uuid4(), "r2/key/d.pdf"
    with Session(seeded_engine) as db:
        apply_tenant_context(db, tenant)
        _insert_chunk(db, tenant_id=tenant, source_kind=DOC_KIND,
                      source_id=src, idx=0)
        db.commit()

        apply_tenant_context(db, tenant)
        with caplog.at_level(logging.WARNING):
            res = purge_file_chunks(db, tenant_id=tenant, source_kind=DOC_KIND,
                                    source_id=src, pinecone=None)
        db.commit()

    assert res.pinecone_deleted == 0
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


@pytest.mark.requires_postgres
def test_count_disagreement_is_reported_with_its_size(
    seeded_engine: Engine,
) -> None:
    """The size of the drift distinguishes one failed write from a run that
    half-landed, so a boolean would throw away the useful part."""
    tenant = uuid4()
    with Session(seeded_engine) as db:
        apply_tenant_context(db, tenant)
        for i in range(3):
            _insert_chunk(db, tenant_id=tenant, source_kind=DOC_KIND,
                          source_id="x", idx=i)
        db.commit()

        pc = FakePinecone()
        pc.stats = {"namespaces": {namespace_for(tenant, None): {"vectorCount": 1}}}
        apply_tenant_context(db, tenant)
        out = count_disagreements(db, tenant_id=tenant, pinecone=pc)

    assert out["postgres_chunks"] == 3
    assert out["pinecone_vectors"] == 1
    assert out["difference"] == 2
