# foundry: kind=test domain=client-intelligence-platform
"""DocumentLibraryConnector / DocumentLibraryMapper.

Covers the behaviours docs/DOCUMENT-SOURCE-CONTRACT.md rules on, and in
particular the two the one-off script got wrong: idempotency keyed on content
rather than chunk position, and removal handled at all.

Object storage is injected, so every one of these runs with no network, no
credentials and no bucket.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from cip.integration_mesh.connectors.document_library import (
    DocumentLibrary,
    DocumentLibraryConnector,
    DocumentLibraryMapper,
    StoredObject,
    sha256_of,
)
from cip.integration_mesh.exceptions import TimezoneNaiveError
from cip.integration_mesh.validation import validate_connector_shape

TENANT = uuid4()
PREFIX = "tenant-a/knowledge/"
T0 = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)


class FakeStore:
    """In-memory object store. Counts reads so cost can be asserted."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects: dict[str, bytes] = dict(objects or {})
        self.get_calls = 0

    def list_objects(self, prefix: str) -> Iterator[StoredObject]:
        for key in sorted(self.objects):
            if key.startswith(prefix):
                yield StoredObject(
                    key=key, last_modified=T0, size_bytes=len(self.objects[key])
                )

    def get_bytes(self, key: str) -> bytes:
        self.get_calls += 1
        return self.objects[key]


LIB = DocumentLibrary(
    library_id="lib-a", name="Library A", r2_prefix=PREFIX,
    source_kind="cip_client_document",
)


def _connector(store: FakeStore, known: dict[str, str] | None = None,
               libs: list[DocumentLibrary] | None = None) -> DocumentLibraryConnector:
    return DocumentLibraryConnector(
        TENANT, libraries=libs or [LIB], object_store=store, known_hashes=known,
    )


def _text_store(**files: str) -> FakeStore:
    return FakeStore({f"{PREFIX}{n}.txt": v.encode() for n, v in files.items()})


# ── Protocol ──────────────────────────────────────────────────────────────


def test_satisfies_the_protocol_shape() -> None:
    validate_connector_shape(_connector(FakeStore()), DocumentLibraryMapper())


def test_describe_schema_uses_only_deployed_property_types() -> None:
    allowed = {"string", "number", "datetime", "enumeration", "reference",
               "boolean", "array", "object"}
    for d in _connector(FakeStore()).describe_schema():
        assert d.data_type in allowed, f"{d.property_name}: {d.data_type}"
        assert d.cip_table == "cip_files"


# ── Classification ────────────────────────────────────────────────────────


def test_first_run_classifies_everything_as_new() -> None:
    c = _connector(_text_store(a="alpha", b="beta"))
    assert {f.state for f in c.classify()} == {"new"}
    assert c.counts["new"] == 2


def test_unchanged_bytes_classify_as_unchanged() -> None:
    store = _text_store(a="alpha")
    known = {f"{PREFIX}a.txt": sha256_of(b"alpha")}
    assert [f.state for f in _connector(store, known).classify()] == ["unchanged"]


def test_changed_bytes_classify_as_changed() -> None:
    store = _text_store(a="alpha revised")
    known = {f"{PREFIX}a.txt": sha256_of(b"alpha")}
    assert [f.state for f in _connector(store, known).classify()] == ["changed"]


def test_a_file_gone_from_the_store_classifies_as_vanished() -> None:
    known = {f"{PREFIX}gone.txt": "deadbeef"}
    out = _connector(_text_store(a="alpha"), known).classify()
    assert {f.state for f in out} == {"new", "vanished"}


# ── The script's actual bug ───────────────────────────────────────────────


def test_same_length_edit_is_detected_because_the_key_is_content() -> None:
    """THE REGRESSION TEST for the one-off script's defect.

    Its rerun guard keyed on which chunk_index values already existed, so a
    file whose bytes changed while producing the SAME number of chunks was
    skipped entirely, counted as processed, and its stale text stayed
    retrievable forever.

    Same byte length, same chunk count, different content. Keyed on position
    this is invisible; keyed on content it is a change.
    """
    old, new = b"canebrake burn every 2 years", b"canebrake burn every 5 years"
    assert len(old) == len(new)

    store = FakeStore({f"{PREFIX}a.txt": new})
    known = {f"{PREFIX}a.txt": sha256_of(old)}
    assert [f.state for f in _connector(store, known).classify()] == ["changed"]


def test_a_shrinking_file_is_a_change_not_a_partial_skip() -> None:
    store = FakeStore({f"{PREFIX}a.txt": b"short"})
    known = {f"{PREFIX}a.txt": sha256_of(b"a much longer original body")}
    assert [f.state for f in _connector(store, known).classify()] == ["changed"]


# ── Idempotence ───────────────────────────────────────────────────────────


def test_a_re_run_over_an_unchanged_corpus_yields_no_records() -> None:
    """The no-op proof. An unchanged library must cost a listing and a hash,
    and produce no work at all."""
    store = _text_store(a="alpha", b="beta")
    first = list(_connector(store).stream_records(None, 100))
    assert len(first) == 2

    known = {r["source_id"]: r["sha256"] for r in first}
    second = list(_connector(store, known).stream_records(None, 100))
    assert second == [], "an unchanged corpus must produce zero records"


def test_unchanged_files_are_not_re_extracted() -> None:
    """Cost proof: skipping must happen BEFORE the record is built, or the
    saving is only notional."""
    store = _text_store(a="alpha")
    known = {f"{PREFIX}a.txt": sha256_of(b"alpha")}
    c = _connector(store, known)
    list(c.stream_records(None, 100))
    # classify() hashes (1 read). Building a record would add another.
    assert store.get_calls == 1


# ── Tombstones ────────────────────────────────────────────────────────────


def test_a_vanished_file_is_yielded_as_work() -> None:
    """A removal is work. A connector that dropped vanished files would leave
    deleted documents answerable forever, which is what the ruling prevents."""
    known = {f"{PREFIX}gone.txt": "deadbeef"}
    recs = list(_connector(_text_store(), known).stream_records(None, 100))
    assert len(recs) == 1
    assert recs[0]["tombstone"] is True


def test_mapper_sets_tombstoned_at_for_a_vanished_file() -> None:
    m = DocumentLibraryMapper(libraries=[LIB])
    rec = {"source_id": "k", "library_id": "lib-a", "tombstone": True,
           "filename": "gone.txt"}
    row = next(iter(m.map(rec)))
    assert row.fields["tombstoned_at"] is not None
    assert row.target_table == "cip_files"


def test_mapper_emits_no_chunks_for_a_tombstoned_file() -> None:
    """The obligation that actually makes a tombstone mean something. Emitting
    chunks here would put a deleted document straight back into retrieval."""
    m = DocumentLibraryMapper(libraries=[LIB])
    rec = {"source_id": "k", "library_id": "lib-a", "tombstone": True,
           "text": "content that should no longer be retrievable"}
    assert m.ingest_as_knowledge(rec) == []


def test_a_live_file_is_not_tombstoned() -> None:
    m = DocumentLibraryMapper(libraries=[LIB])
    row = next(iter(m.map({"source_id": "k", "library_id": "lib-a",
                           "filename": "a.txt"})))
    assert row.fields["tombstoned_at"] is None


# ── source_kind scoping ───────────────────────────────────────────────────


def test_source_kind_comes_from_the_library_not_a_global_default() -> None:
    """cip_knowledge_chunks has a second producer. source_kind is the only
    discriminator, so it must be explicit per library."""
    contracts = DocumentLibrary(
        library_id="lib-contracts", name="Contracts",
        r2_prefix="tenant-a/contracts/", source_kind="cip_contract",
    )
    m = DocumentLibraryMapper(libraries=[LIB, contracts])
    assert m.source_kind_for({"library_id": "lib-contracts"}) == "cip_contract"
    assert m.source_kind_for({"library_id": "lib-a"}) == "cip_client_document"


def test_chunks_carry_their_source_kind() -> None:
    m = DocumentLibraryMapper(libraries=[LIB])
    texts = m.ingest_as_knowledge(
        {"source_id": "k", "library_id": "lib-a", "text": "a" * 5000}
    )
    assert texts
    assert all(t.metadata["source_kind"] == "cip_client_document" for t in texts)


def test_chunks_are_indexed_and_know_their_total() -> None:
    m = DocumentLibraryMapper(libraries=[LIB])
    texts = m.ingest_as_knowledge(
        {"source_id": "k", "library_id": "lib-a", "text": "b" * 9000}
    )
    assert len(texts) > 1
    assert [t.metadata["chunk_index"] for t in texts] == list(range(len(texts)))
    assert all(t.metadata["total_chunks"] == len(texts) for t in texts)


# ── Extraction is reported, never silently empty ──────────────────────────


def test_unsupported_files_are_named_not_silently_skipped() -> None:
    """A corpus that is 89% PDF must not read as a successful ingest of
    nothing. The status and the filenames are what make that visible."""
    store = FakeStore({f"{PREFIX}report.pdf": b"%PDF-1.7 binary"})
    c = _connector(store)
    recs = list(c.stream_records(None, 100))
    assert recs[0]["extraction"] == "unsupported"
    assert recs[0]["text"] == ""
    assert c.unsupported_files == ["report.pdf"]


def test_a_file_with_no_extractable_text_yields_no_chunks() -> None:
    m = DocumentLibraryMapper(libraries=[LIB])
    assert m.ingest_as_knowledge(
        {"source_id": "k", "library_id": "lib-a", "text": "",
         "extraction": "unsupported", "filename": "report.pdf"}
    ) == []


def test_an_injected_extractor_is_used() -> None:
    """Real PDF text and image captioning arrive this way."""
    def captioner(filename: str, payload: bytes, mime: str | None) -> tuple[str, str]:
        return f"[Image: {filename}] annotated aerial map", "captioned"

    store = FakeStore({f"{PREFIX}field.jpg": b"\xff\xd8\xff"})
    c = DocumentLibraryConnector(
        TENANT, libraries=[LIB], object_store=store, text_extractor=captioner,
    )
    rec = next(iter(c.stream_records(None, 100)))
    assert rec["extraction"] == "captioned"
    assert "annotated aerial map" in str(rec["text"])
    assert c.unsupported_files == []


def test_text_files_decode() -> None:
    store = _text_store(a="canebrake ecology notes")
    rec = next(iter(_connector(store).stream_records(None, 100)))
    assert rec["extraction"] == "decoded"
    assert "canebrake" in str(rec["text"])


# ── Cursor ────────────────────────────────────────────────────────────────


def test_incremental_key_returns_the_objects_last_modified() -> None:
    c = _connector(_text_store(a="alpha"))
    rec = next(iter(c.stream_records(None, 100)))
    assert c.incremental_key(rec) == T0


def test_incremental_key_rejects_a_tz_naive_timestamp() -> None:
    c = _connector(FakeStore())
    with pytest.raises(TimezoneNaiveError):
        c.incremental_key({"source_id": "k", "last_modified": "2026-05-22T12:00:00"})


def test_a_tz_naive_stored_cursor_raises_rather_than_being_guessed() -> None:
    c = _connector(_text_store(a="alpha"))
    with pytest.raises(TimezoneNaiveError):
        list(c.stream_records({"last_incremental_key": "2026-05-22T12:00:00"}, 100))


def test_a_tombstone_never_advances_the_cursor_past_live_work() -> None:
    """A vanished object has no upstream timestamp. Taking 'now' would push the
    cursor beyond files that still need syncing."""
    c = _connector(FakeStore(), {f"{PREFIX}gone.txt": "deadbeef"})
    rec = next(iter(c.stream_records(None, 100)))
    assert c.incremental_key(rec) == datetime.fromtimestamp(0, tz=UTC)


def test_the_cursor_does_not_suppress_a_removal() -> None:
    """Removals must survive an incremental run, or a deleted document is only
    ever noticed by a full resync."""
    c = _connector(FakeStore(), {f"{PREFIX}gone.txt": "deadbeef"})
    recs = list(c.stream_records({"last_incremental_key": T0.isoformat()}, 100))
    assert [r["tombstone"] for r in recs] == [True]


# ── Multiple libraries ────────────────────────────────────────────────────


def test_a_tenant_can_have_several_libraries_by_configuration_alone() -> None:
    """The exit bar for the whole workstream: a new library is config."""
    store = FakeStore({
        f"{PREFIX}a.txt": b"alpha",
        "tenant-a/contracts/msa.txt": b"master services agreement",
    })
    contracts = DocumentLibrary(
        library_id="lib-contracts", name="Contracts",
        r2_prefix="tenant-a/contracts/", source_kind="cip_contract",
    )
    c = _connector(store, libs=[LIB, contracts])
    recs = list(c.stream_records(None, 100))
    assert {r["library_id"] for r in recs} == {"lib-a", "lib-contracts"}
