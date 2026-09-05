# foundry: kind=service domain=client-intelligence-platform touches=integration
"""DocumentLibraryMapper — a file record becomes a cip_files row plus chunks.

This is the seam the Protocol already provided and the one-off script ignored.
``CIPMapper.ingest_as_knowledge`` has existed since M2 with its return shape
locked by D-133 explicitly so that real ingestion could be wired against it
later. Chunking a document belongs there, not in a script.

Two obligations from docs/DOCUMENT-SOURCE-CONTRACT.md are enforced here rather
than left to the caller:

  - source_kind SCOPING. ``cip_knowledge_chunks`` has a second producer
    (row-derived chunks under cip_ticket_comment / cip_engagement_* /
    cip_ticket). Every chunk this mapper emits carries its library's
    source_kind so a document-side rewrite can be scoped and cannot destroy
    the other producer's rows.
  - TOMBSTONES ARE WORK. A vanished file yields a row that sets
    ``tombstoned_at`` and emits ZERO knowledge texts. Emitting chunks for a
    document the tenant deleted is the failure this ruling exists to prevent.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Literal

from cip.integration_mesh.base import CIPRow, KnowledgeText
from cip.integration_mesh.knowledge.chunker import ChunkSpec, chunk_text

from .connector import DEFAULT_SOURCE_KIND, DocumentLibrary


class DocumentLibraryMapper:
    """Maps document-library file records onto ``cip_files`` and knowledge."""

    object_type: str = "document"
    target_table: str = "cip_files"

    def __init__(
        self,
        *,
        libraries: list[DocumentLibrary] | None = None,
        chunk_spec: ChunkSpec | None = None,
    ) -> None:
        self._by_library = {lib.library_id: lib for lib in (libraries or [])}
        self.chunk_spec = chunk_spec or ChunkSpec()

    def source_kind_for(self, record: dict[str, object]) -> str:
        """Which source_kind this record's chunks belong under.

        Per-library rather than global, so a tenant can separate contracts from
        training material without a code change, and so the discriminator that
        protects the row-derived producer is always explicit.
        """
        lib = self._by_library.get(str(record.get("library_id", "")))
        return lib.source_kind if lib else DEFAULT_SOURCE_KIND

    def map(self, record: dict[str, object]) -> Iterator[CIPRow]:
        """Emit the ``cip_files`` row for this file.

        MUST be a generator: ``validate_connector_shape`` unwraps decorators and
        rejects a mapper whose ``map`` is a plain function.
        """
        lib = self._by_library.get(str(record.get("library_id", "")))
        fields: dict[str, object] = {
            "r2_path": record.get("r2_path"),
            "filename": record.get("filename"),
            "sha256": record.get("sha256"),
            "size_bytes": record.get("size_bytes"),
            "mime_type": record.get("mime_type"),
            "source_connector": "document-library-v1",
        }
        if record.get("tombstone"):
            # The removal IS the update. Everything else about the row stays as
            # it was, so the audit trail survives the file not doing so.
            fields["tombstoned_at"] = datetime.now(tz=UTC)
        else:
            fields["tombstoned_at"] = None

        yield CIPRow(
            target_table=self.target_table,
            source_id=str(record["source_id"]),
            fields=fields,
            overflow={
                k: record[k]
                for k in ("library_id", "last_modified", "state")
                if k in record
            },
            client_id=lib.client_id if lib else None,
            authority="ingested",
        )

    def overflow_fields(self) -> list[str]:
        return ["library_id", "last_modified", "state"]

    def authority(self) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"

    def ingest_as_knowledge(self, record: dict[str, object]) -> list[KnowledgeText]:
        """Chunk this file's extracted text into ``KnowledgeText``.

        Returns EMPTY for a tombstoned file. That is the whole point of the
        ruling: a document the tenant removed must stop being retrievable, and
        re-emitting its chunks here would put it straight back.

        Returns empty for a file with no extractable text too, rather than
        emitting a chunk of the filename and calling it content. The record
        carries ``extraction`` so the run can report how many files that was,
        instead of the count quietly reading as success.

        Metadata deliberately carries only what this mapper genuinely knows.
        The orchestrator finalizes the five required core keys (source_id,
        source_system, extracted_at, tenant_id, connector_version) and the
        validator runs at the boundary, so inventing them here would be the
        lying-mock anti-pattern the TypedDict's total=False exists to avoid.
        """
        if record.get("tombstone"):
            return []

        text = str(record.get("text") or "")
        if not text.strip():
            return []

        chunks = chunk_text(text, self.chunk_spec)
        source_kind = self.source_kind_for(record)
        total = len(chunks)
        return [
            KnowledgeText(
                text=chunk,
                metadata={  # type: ignore[typeddict-unknown-key]
                    "source_kind": source_kind,
                    "chunk_index": i,
                    "total_chunks": total,
                    "filename": record.get("filename"),
                    "r2_path": record.get("r2_path"),
                    "library_id": record.get("library_id"),
                    "extraction": record.get("extraction"),
                },
            )
            for i, chunk in enumerate(chunks)
        ]
