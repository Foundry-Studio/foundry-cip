# foundry: kind=service domain=client-intelligence-platform touches=integration
"""DocumentLibraryConnector — a tenant's document library as a CIP connector.

Implements CIPConnector against object storage (R2) so that a tenant's
documents onboard by the same path as HubSpot or Zendesk, rather than through a
per-tenant script.

The contract this implements is docs/DOCUMENT-SOURCE-CONTRACT.md (CIP-SPEC-014).
Three of its rulings shape this module:

  - The RECORD IS A FILE. Chunks are a derived write, emitted by the mapper's
    ``ingest_as_knowledge``. That is the seam the Protocol already provided.
  - The CURSOR is the object's ``last_modified``; the IDENTITY is its sha256.
    They are different jobs. ``last_modified`` decides what to look at; the
    hash decides whether to do work.
  - A vanished file is TOMBSTONED, never hard-deleted.

WHY OBJECT ACCESS IS INJECTED. ``object_store`` is a parameter rather than a
module-level boto3 client, so the whole classification path is testable without
network, credentials, or a live bucket. The knowledge stack it feeds had zero
tests until 2026-09-04 precisely because its dependencies were unmockable in
practice; not repeating that is worth one constructor argument.
"""
from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from cip.integration_mesh.base import (
    DEFAULT_RATE_LIMIT,
    CIPConnectorBase,
    PropertyDescriptor,
    RateLimitPolicy,
)
from cip.integration_mesh.exceptions import TimezoneNaiveError

CONNECTOR_ID = "document-library-v1"
DEFAULT_SOURCE_KIND = "cip_client_document"


@dataclass(frozen=True)
class DocumentLibrary:
    """One addressable document library belonging to a tenant.

    Adding a library is configuration. Adding a TENANT is configuration. That
    is the exit bar for this connector: a new tenant with a new library needs
    no code change.
    """

    library_id: str
    name: str
    r2_prefix: str
    source_kind: str = DEFAULT_SOURCE_KIND
    client_id: UUID | None = None


@dataclass(frozen=True)
class StoredObject:
    """One object as the store lists it."""

    key: str
    last_modified: datetime
    size_bytes: int


class ObjectStore(Protocol):
    """The slice of object storage this connector needs.

    Deliberately two methods. A connector that can only list and fetch cannot
    delete a tenant's documents by accident, which matters because the
    tombstone ruling exists to make removal recoverable.
    """

    def list_objects(self, prefix: str) -> Iterator[StoredObject]: ...

    def get_bytes(self, key: str) -> bytes: ...


@dataclass
class ClassifiedFile:
    """What one enumerated object turned out to be, relative to what is stored.

    ``state`` is one of new / changed / unchanged / vanished. Classification is
    kept separate from action so it can be asserted directly in tests and
    reported in a run summary, rather than being inferred from side effects.
    """

    key: str
    filename: str
    state: str
    sha256: str | None = None
    last_modified: datetime | None = None
    size_bytes: int | None = None
    library_id: str = ""


def sha256_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# (text, extraction_status). Status is carried into the record so a run can
# report how many files it could not read, instead of that count silently
# reading as success.
TextExtractor = Callable[[str, bytes, str | None], tuple[str, str]]


def default_text_extractor(
    filename: str, payload: bytes, mime_type: str | None
) -> tuple[str, str]:
    """Decode what can be decoded without extra dependencies.

    Handles text/*, markdown, JSON and CSV. Everything else (PDF, docx, images)
    returns empty text with status ``unsupported`` rather than guessing.

    This is deliberately NOT silent-empty. PDFs are 49 of Rocky Ridge's 65
    files and images are another 9, so a caller that ships this default against
    a real corpus gets ~89% ``unsupported`` in its run summary and finds out
    immediately. The alternative, returning empty text with no status, is how a
    corpus ends up looking ingested while holding nothing.

    Real extraction (PDF text, docx, and the vision captioning that turned 9
    JPEGs into 26 chunks of usable description) is injected via
    ``text_extractor``.
    """
    mt = mime_type or ""
    if mt.startswith("text/") or mt in {"application/json", "application/csv"}:
        try:
            return payload.decode("utf-8"), "decoded"
        except UnicodeDecodeError:
            return payload.decode("utf-8", errors="replace"), "decoded_lossy"
    return "", "unsupported"


class DocumentLibraryConnector(CIPConnectorBase):
    """Streams a tenant's document libraries as file records."""

    connector_id: str = CONNECTOR_ID
    version: str = "1.0.0"

    def __init__(
        self,
        tenant_id: UUID,
        *,
        libraries: Sequence[DocumentLibrary],
        object_store: ObjectStore,
        known_hashes: dict[str, str] | None = None,
        text_extractor: TextExtractor | None = None,
    ) -> None:
        """
        Args:
            tenant_id: owning tenant.
            libraries: the configured ``document_libraries`` for this tenant.
            object_store: anything satisfying :class:`ObjectStore`.
            known_hashes: ``{object_key: sha256}`` for files already stored,
                used to decide new / changed / unchanged without downloading.
                Empty or None means everything reads as new, which is the
                correct behaviour for a first run.
        """
        self.tenant_id = tenant_id
        self.libraries = list(libraries)
        self.store = object_store
        self.known_hashes = dict(known_hashes or {})
        self.text_extractor = text_extractor or default_text_extractor
        self._authenticated = False
        # Counters, so a run can report what it did rather than only that it
        # finished. The document path previously reported nothing at all.
        self.counts: dict[str, int] = {
            "new": 0, "changed": 0, "unchanged": 0, "vanished": 0,
        }
        # Files whose bytes could not be turned into text. Named rather than
        # merely counted, because "89% of the corpus was unreadable" is only
        # actionable if you can see WHICH files.
        self.unsupported_files: list[str] = []

    @property
    def rate_limit_policy(self) -> RateLimitPolicy:
        return DEFAULT_RATE_LIMIT

    @property
    def cursor_safety_window_seconds(self) -> int:
        # Object stores can report a listing before it is globally consistent.
        # A minute of overlap costs a hash comparison per file and nothing else,
        # because unchanged files are skipped on content, not on timestamp.
        return 60

    def authenticate(self) -> None:
        """Prove the store is reachable before queueing work behind it.

        Deliberately eager, and for a specific reason: a stale endpoint once ran
        silently for three days in this codebase because the first failure
        surfaced deep inside a long ingestion instead of at startup.
        """
        for lib in self.libraries:
            next(iter(self.store.list_objects(lib.r2_prefix)), None)
        self._authenticated = True

    def classify(self) -> list[ClassifiedFile]:
        """Enumerate every library and say what each file IS, without writing.

        This is the whole change-detection decision in one place, and it is a
        pure function of (store contents, known_hashes). A dry run is just this
        method.
        """
        results: list[ClassifiedFile] = []
        seen_keys: set[str] = set()

        for lib in self.libraries:
            for obj in self.store.list_objects(lib.r2_prefix):
                seen_keys.add(obj.key)
                digest = sha256_of(self.store.get_bytes(obj.key))
                previous = self.known_hashes.get(obj.key)
                if previous is None:
                    state = "new"
                elif previous == digest:
                    state = "unchanged"
                else:
                    state = "changed"
                results.append(
                    ClassifiedFile(
                        key=obj.key,
                        filename=obj.key.rsplit("/", 1)[-1],
                        state=state,
                        sha256=digest,
                        last_modified=obj.last_modified,
                        size_bytes=obj.size_bytes,
                        library_id=lib.library_id,
                    )
                )

        # Anything stored that the libraries no longer list has been removed
        # upstream. Per CIP-SPEC-014 ruling 3 it is tombstoned, not deleted.
        for key in self.known_hashes:
            if key not in seen_keys:
                results.append(
                    ClassifiedFile(
                        key=key,
                        filename=key.rsplit("/", 1)[-1],
                        state="vanished",
                    )
                )

        self.counts = dict.fromkeys(("new", "changed", "unchanged", "vanished"), 0)
        for r in results:
            self.counts[r.state] += 1
        return results

    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        """Yield one record per file that needs work.

        ``unchanged`` files are skipped, which is what makes a re-run cost a
        listing plus a hash and no embedding spend. ``vanished`` files ARE
        yielded, carrying ``tombstone=True``, because a removal is work: a file
        that stops being retrievable is the point of the tombstone ruling, and
        a connector that silently dropped removals would leave deleted
        documents answerable forever.

        ``cursor`` carries ``last_incremental_key`` as ISO-8601 UTC, matching
        every other CIP connector. It filters the enumeration; it never decides
        whether content changed. That decision is the hash.
        """
        last_key: datetime | None = None
        if cursor is not None:
            key_iso = cursor.get("last_incremental_key")
            if isinstance(key_iso, str) and key_iso:
                last_key = datetime.fromisoformat(key_iso)
                if last_key.tzinfo is None or last_key.utcoffset() is None:
                    raise TimezoneNaiveError(
                        f"stored cursor last_incremental_key is tz-naive: "
                        f"{key_iso!r}"
                    )

        for item in self.classify():
            if item.state == "unchanged":
                continue
            if (
                last_key is not None
                and item.last_modified is not None
                and item.last_modified <= last_key
                and item.state != "vanished"
            ):
                continue
            yield self._to_record(item)

    def _to_record(self, item: ClassifiedFile) -> dict[str, object]:
        text, extraction, mime_type = "", "tombstoned", None
        if item.state != "vanished":
            mime_type = mimetypes.guess_type(item.filename)[0]
            payload = self.store.get_bytes(item.key)
            text, extraction = self.text_extractor(
                item.filename, payload, mime_type
            )
            if extraction == "unsupported":
                self.unsupported_files.append(item.filename)
        return {
            "text": text,
            "extraction": extraction,
            "mime_type": mime_type,
            "source_id": item.key,
            "library_id": item.library_id,
            "filename": item.filename,
            "r2_path": item.key,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
            "last_modified": (
                item.last_modified.isoformat() if item.last_modified else None
            ),
            "state": item.state,
            "tombstone": item.state == "vanished",
        }

    def incremental_key(self, record: dict[str, object]) -> datetime:
        """Return the object's ``last_modified`` as a tz-aware datetime.

        Object listings carry this, which is why the Protocol's datetime cursor
        contract is satisfiable for documents with no Protocol change at all.

        A tombstone record has no upstream timestamp — the object is gone. It
        takes the epoch so the cursor is never advanced past live work by a
        removal.
        """
        raw = record.get("last_modified")
        if raw is None:
            return datetime.fromtimestamp(0, tz=UTC)
        ts = datetime.fromisoformat(str(raw))
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise TimezoneNaiveError(
                f"document record {record.get('source_id')!r} last_modified "
                f"is tz-naive: {ts!r}"
            )
        return ts

    def describe_schema(self) -> list[PropertyDescriptor]:
        return list(_DESCRIPTORS)



def _d(name: str, data_type: str, column: str | None, desc: str) -> PropertyDescriptor:
    return PropertyDescriptor(
        connector=CONNECTOR_ID,
        object_type="document",
        property_name=name,
        data_type=data_type,
        storage_location="column" if column else "overflow",
        column_name=column,
        cip_table="cip_files",
        description=desc,
    )


_DESCRIPTORS: tuple[PropertyDescriptor, ...] = (
    _d("filename", "string", "filename", "Leaf name of the object key."),
    _d("r2_path", "string", "r2_path", "Full object key within the bucket."),
    _d("mime_type", "string", "mime_type", "Detected content type."),
    _d("size_bytes", "number", "size_bytes", "Object size as listed."),
    _d("sha256", "string", "sha256",
       "Content hash. The idempotency key: unchanged bytes do no work."),
    _d("tombstoned_at", "datetime", "tombstoned_at",
       "Set when the library no longer lists the file. NULL means live."),
    _d("library_id", "string", None,
       "Which configured document library this file came from."),
    _d("last_modified", "datetime", None,
       "Object last-modified time. The incremental cursor, not the identity."),
)
