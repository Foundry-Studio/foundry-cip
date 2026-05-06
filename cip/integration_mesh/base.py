# foundry: kind=service domain=client-intelligence-platform touches=integration
"""CIP Integration Mesh base Protocols + value objects (M2 binding).

The normative contract. Every CIP connector + mapper conforms to the Protocols
defined here.

Decisions:
- D-118: CIP framework lives inside Integration Mesh.
- D-122: Domain ownership determined by CSS tag, not folder location.
- D-133 (amended 2026-04-29 Round-6 Call A): ``CIPMapper.ingest_as_knowledge``
  returns ``list[KnowledgeText]``; ``KnowledgeText.metadata`` is a
  ``KnowledgeTextMetadata`` ``TypedDict`` with ``total=False`` (boundary
  validator enforces required-core contract — no "lying mock").
- D-134: Protocol-based connector framework (``@runtime_checkable``).
- D-135: SCD Type 2 diffing applied at the application layer.

Round-7 Verifier discipline:
- ``KnowledgeMetadataValidationError`` + ``TimezoneNaiveError`` are defined
  ONLY in ``exceptions.py``; this module imports them lazily at use-site.
- ``__init__.py`` exposes ``validate_knowledge_text_metadata``,
  ``KNOWLEDGE_TEXT_REQUIRED_KEYS``, and ``KnowledgeMetadataValidationError``.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, TypedDict, runtime_checkable
from uuid import UUID

# ── tz-aware datetime guard (v5 PATCH-NR-7) ─────────────────────────────


def _assert_tz_aware(value: object, field_name: str) -> None:
    """Raise ``TimezoneNaiveError`` if ``value`` is a tz-naive datetime.

    Called everywhere a datetime crosses the framework boundary into
    ``KnowledgeTextMetadata`` or ``CIPRow.fields``. Silent tz-naive datetimes
    are a correctness landmine in cross-DB / cross-timezone deployments —
    fail fast.

    Accepts ``object`` rather than ``datetime`` because callers iterate over
    ``dict[str, object]`` field maps and need a no-op on non-datetime values
    (CIPRow.fields can carry strings, ints, etc.).
    """
    # Lazy-import to avoid a circular dependency. ``exceptions.py`` does
    # not import ``base.py`` (it has no cip-internal deps), so importing
    # at use-site is safe and keeps module-load cheap.
    from .exceptions import TimezoneNaiveError

    if not isinstance(value, datetime):
        return
    if value.tzinfo is None or value.utcoffset() is None:
        raise TimezoneNaiveError(
            f"{field_name} must be tz-aware UTC datetime; got naive: {value!r}"
        )


# ── Value objects (frozen dataclasses) ──────────────────────────────────


@dataclass(frozen=True)
class PropertyDescriptor:
    """One property a connector exposes, registered in
    ``cip_connector_property_registry``. Emitted by
    ``CIPConnector.describe_schema()``.
    """

    connector: str
    object_type: str
    property_name: str
    # Python attribute name preserved as public API. SQL column name is
    # ``property_type`` (Δ11) — orchestrator's
    # ``_register_properties_best_effort`` maps ``p.data_type`` → ``:property_type``
    # at bind time. Deployed CHECK enum:
    # {string, number, datetime, enumeration, reference, boolean, array, object} (Δ12).
    data_type: str
    storage_location: Literal["column", "overflow"]
    column_name: str | None
    cip_table: str
    description: str | None = None
    is_custom: bool = False


@dataclass(frozen=True)
class CIPRow:
    """One row the mapper emits.

    Orchestrator persists to ``target_table`` and (on change) to
    ``{target_table}_history``.
    """

    target_table: str
    source_id: str
    fields: dict[str, object]
    overflow: dict[str, object] = field(default_factory=dict)
    client_id: UUID | None = None
    authority: Literal["agent_discovered", "ingested", "validated"] = "ingested"


@dataclass(frozen=True)
class RateLimitPolicy:
    """In-process rate-limiting policy for ``stream_records`` calls."""

    requests_per_second: float
    burst: int = 1

    def __post_init__(self) -> None:
        if self.requests_per_second <= 0:
            raise ValueError("requests_per_second must be > 0")
        if self.burst < 1:
            raise ValueError("burst must be >= 1")


# v3 R2-C6: single canonical name. CIPConnectorBase's default references this.
DEFAULT_RATE_LIMIT = RateLimitPolicy(requests_per_second=10.0, burst=5)


# ── Module-level TSP constants (v3 R2-C2) ───────────────────────────────

DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS: int = 300
"""H-13. Orchestrator rewinds the stored cursor by this many seconds before
passing it to ``connector.stream_records()``. Absorbs clock skew + replica
lag at the source. Per-connector override via the
``cursor_safety_window_seconds`` property on ``CIPConnector``."""

MAX_RATE_LIMIT_SLEEP_SECONDS: int = 300
"""M-21. Cap on ``RateLimitExceeded.retry_after_seconds``. Prevents a buggy
or malicious connector from parking the sync for an hour."""

MAX_BATCH_RATE_LIMIT_RETRIES: int = 3
"""H-6. Per-batch budget for rate-limit retries. After this many retries on
the same batch, the batch is counted as one ``consecutive_batch_failures``
increment and the orchestrator moves on."""

MAX_CONSECUTIVE_BATCH_FAILURES: int = 3
"""H-8. Cross-batch budget. After this many consecutive batch failures the
orchestrator aborts the run with ``status='partial'``."""


# ── KnowledgeText (D-133 amended 2026-04-29 — Round-6 Call A) ───────────


class KnowledgeTextMetadata(TypedDict, total=False):
    """Framework-owned metadata keys for ``KnowledgeText``.

    All keys are NotRequired at the type level (``total=False``);
    ``validate_knowledge_text_metadata()`` enforces the required-core
    contract at the boundary CROSSING moment (when text leaves the
    connector → mapper layer and is handed to the Knowledge+Graph layer).
    This separates SHAPE (TypedDict, mypy-strict checks key names) from
    REQUIRED-AT-EMISSION (orchestrator-validated, fail-loud).

    With ``total=False``, mappers emit only the keys they genuinely know;
    the orchestrator finalizes operational metadata at boundary; mock
    mappers no longer have to lie. Eliminates the "lying mock"
    anti-pattern flagged by Kimi-k2.5 in Round-6.

    Connectors that need source-specific fields subclass this TypedDict in
    their own module::

        from typing import NotRequired
        class HubSpotKnowledgeMetadata(KnowledgeTextMetadata):
            hs_object_id: NotRequired[str]
            hs_pipeline_stage: NotRequired[str]

    Framework-owned core keys (orchestrator-populated, validated at boundary):
      - ``source_id``         REQUIRED at boundary
      - ``source_system``     REQUIRED at boundary
      - ``extracted_at``      REQUIRED at boundary; tz-aware UTC
      - ``tenant_id``         REQUIRED at boundary
      - ``connector_version`` REQUIRED at boundary; connector's own semver

    Framework-owned optional extensions:
      - ``authority``           ``"agent_discovered" | "ingested" | "validated"``
      - ``record_updated_at``   tz-aware UTC datetime
      - ``ingestion_batch_id``  UUID
    """

    source_id: str
    source_system: str
    extracted_at: datetime
    tenant_id: UUID
    connector_version: str
    authority: Literal["agent_discovered", "ingested", "validated"]
    record_updated_at: datetime
    ingestion_batch_id: UUID


# v5.2 (Round-6 Call A — Verifier HIGH-B): orchestrator-boundary required-set.
KNOWLEDGE_TEXT_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "source_id",
        "source_system",
        "extracted_at",
        "tenant_id",
        "connector_version",
    }
)


def validate_knowledge_text_metadata(
    metadata: KnowledgeTextMetadata,
    *,
    where: str = "KnowledgeText emission",
) -> None:
    """Boundary-crossing validation of KnowledgeText metadata.

    Called by the orchestrator AFTER mapper output + orchestrator
    finalization, BEFORE handing the list to the Knowledge+Graph layer
    (M2 stub: ``ingest_texts_noop``; M5: real Pinecone+FalkorDB write).

    Raises:
        KnowledgeMetadataValidationError: any of the 5 required core keys
            missing.
        TimezoneNaiveError: ``extracted_at`` or ``record_updated_at`` is
            present but tz-naive.

    Args:
        metadata: dict-shaped KnowledgeTextMetadata (still a dict at runtime).
        where: human-readable string for the error message — e.g.
            ``"ingest_as_knowledge for record c001"`` or
            ``"M5 Knowledge layer entry"``.
    """
    # Lazy-imports to avoid a circular import. ``exceptions.py`` has no
    # cip-internal deps; importing here is cheap and safe. (v5.2 Verifier
    # HIGH fix: canonical home for both classes is ``exceptions.py``.)
    from .exceptions import KnowledgeMetadataValidationError, TimezoneNaiveError

    missing = KNOWLEDGE_TEXT_REQUIRED_KEYS - metadata.keys()
    if missing:
        raise KnowledgeMetadataValidationError(
            f"KnowledgeText metadata missing required keys at {where}: "
            f"{sorted(missing)}. Mapper output (or orchestrator finalization) "
            "must populate all 5 core keys."
        )
    # tz-aware enforcement (PATCH-NR-7).
    for k in ("extracted_at", "record_updated_at"):
        v = metadata.get(k)
        if (
            isinstance(v, datetime)
            and (v.tzinfo is None or v.utcoffset() is None)
        ):
            raise TimezoneNaiveError(
                f"KnowledgeText.metadata[{k!r}] must be tz-aware UTC at "
                f"{where}; got naive: {v!r}"
            )


@dataclass(frozen=True)
class KnowledgeText:
    """A text chunk the mapper emits for downstream Knowledge ingestion.

    Outer shape: frozen dataclass (D-133 outer-shape lock — connector
    cannot mutate mid-pipeline).
    Inner ``metadata`` shape: ``KnowledgeTextMetadata`` ``TypedDict`` with
    ``total=False`` (refined by Round-6 panel synthesis 2026-04-29).

    Required-at-boundary contract enforced by
    ``validate_knowledge_text_metadata()``, NOT by the type. Mock mappers
    can emit ``metadata={}``; orchestrator fills operational metadata;
    validator runs at boundary.
    """

    text: str
    metadata: KnowledgeTextMetadata


# ── Allowed CIP tables (v2 allowlist; closed enum) ──────────────────────

ALLOWED_CIP_TABLES: frozenset[str] = frozenset(
    {
        "cip_clients",
        "cip_companies",
        "cip_contacts",
        "cip_deals",
        "cip_files",
        "cip_tickets",
        "cip_views",
        "cip_connector_property_registry",
    }
)

# Tables that have sibling _history tables for SCD Type 2.
# cip_connector_property_registry intentionally absent — no history.
# cip_sync_runs intentionally absent — audit log, not domain table.
HISTORY_TABLE_BY_CURRENT: dict[str, str] = {
    "cip_clients": "cip_clients_history",
    "cip_companies": "cip_companies_history",
    "cip_contacts": "cip_contacts_history",
    "cip_deals": "cip_deals_history",
    "cip_files": "cip_files_history",
    "cip_tickets": "cip_tickets_history",
    "cip_views": "cip_views_history",
}


@dataclass(frozen=True)
class SyncRunState:
    """Snapshot of what the orchestrator returns to callers.

    Counter semantics per QC M-24 split (v3 R2-C9):
      - ``rows_received``         raw count yielded by ``stream_records``
      - ``rows_created``          new rows INSERTed into ``cip_{entity}``
      - ``rows_updated``          existing rows UPDATEd with new values
      - ``rows_skipped_unchanged`` diffed identical → only ``refreshed_at`` bumped
      - ``rows_skipped_drift``    mapper.map raised ``SchemaDriftError``
      - ``rows_skipped_duplicate`` intra-batch dedupe dropped this row
      - ``rows_history``          SCD history rows written
    """

    run_id: UUID
    batch_id: UUID
    status: Literal["success", "partial", "failed"]
    rows_received: int
    rows_created: int
    rows_updated: int
    rows_skipped_unchanged: int
    rows_skipped_drift: int
    rows_skipped_duplicate: int
    rows_history: int
    started_at: datetime
    ended_at: datetime
    error_detail: dict[str, object] | None = None
    cursor_state: dict[str, object] | None = None

    @property
    def rows_processed(self) -> int:
        """Rows that were acted on (created + updated + skipped_unchanged)."""
        return (
            self.rows_created + self.rows_updated + self.rows_skipped_unchanged
        )


# ── Protocols (the normative contract) ──────────────────────────────────


@runtime_checkable
class CIPConnector(Protocol):
    connector_id: str
    tenant_id: UUID

    def authenticate(self) -> None: ...
    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]: ...
    def describe_schema(self) -> list[PropertyDescriptor]: ...
    def incremental_key(self, record: dict[str, object]) -> datetime: ...

    @property
    def rate_limit_policy(self) -> RateLimitPolicy: ...

    @property
    def cursor_safety_window_seconds(self) -> int: ...


@runtime_checkable
class CIPMapper(Protocol):
    object_type: str
    target_table: str

    def map(self, record: dict[str, object]) -> Iterable[CIPRow]: ...
    def overflow_fields(self) -> list[str]: ...
    def authority(
        self,
    ) -> Literal["agent_discovered", "ingested", "validated"]: ...
    # D-133: locked return type. M5 wires real ingestion against the same shape.
    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]: ...


# ── Optional ABCs (runtime safety net, not required) ────────────────────


class CIPConnectorBase:
    """Optional base class. Connectors can inherit for default
    ``rate_limit_policy`` + ``cursor_safety_window_seconds`` and helpful
    ``NotImplementedError`` messages. Not required — structural compatibility
    via the Protocol above is sufficient.
    """

    connector_id: str = ""
    tenant_id: UUID  # subclasses set in __init__

    @property
    def rate_limit_policy(self) -> RateLimitPolicy:
        return DEFAULT_RATE_LIMIT

    @property
    def cursor_safety_window_seconds(self) -> int:
        return DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS

    def authenticate(self) -> None:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement authenticate()"
        )

    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement stream_records()"
        )

    def describe_schema(self) -> list[PropertyDescriptor]:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement describe_schema()"
        )

    def incremental_key(self, record: dict[str, object]) -> datetime:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement incremental_key()"
        )


class CIPMapperBase:
    """Optional mapper base class with sensible defaults."""

    object_type: str = ""
    target_table: str = ""

    def overflow_fields(self) -> list[str]:
        return []

    def authority(
        self,
    ) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"

    def ingest_as_knowledge(
        self, record: dict[str, object]
    ) -> list[KnowledgeText]:
        return []

    def map(self, record: dict[str, object]) -> Iterable[CIPRow]:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement map()"
        )
