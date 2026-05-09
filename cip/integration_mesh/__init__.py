# foundry: kind=service domain=client-intelligence-platform touches=integration
"""CIP Integration Mesh public API (M2 §4.10 binding).

Per plan §7 step 6: re-export the Protocols + dataclasses + ``run_sync`` +
exceptions + validation entry point so consumers can ``from cip.integration_mesh
import ...`` instead of reaching into submodules.

The conformance harness (§5) imports from this module; submodule imports are a
private-API path used internally by tests that need direct module references
(e.g., monkeypatch.setattr(orch_module, ...)).
"""
from __future__ import annotations

from .base import (
    ALLOWED_CIP_TABLES,
    DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS,
    DEFAULT_RATE_LIMIT,
    HISTORY_TABLE_BY_CURRENT,
    KNOWLEDGE_TEXT_REQUIRED_KEYS,
    MAX_BATCH_RATE_LIMIT_RETRIES,
    MAX_CONSECUTIVE_BATCH_FAILURES,
    MAX_RATE_LIMIT_SLEEP_SECONDS,
    CIPConnector,
    CIPConnectorBase,
    CIPMapper,
    CIPMapperBase,
    CIPRow,
    KnowledgeText,
    KnowledgeTextMetadata,
    PropertyDescriptor,
    RateLimitPolicy,
    SyncRunState,
    validate_knowledge_text_metadata,
)
from .connectors.fixture import CorpusSize, FixtureConnector, FixtureMapper
from .exceptions import (
    AuthenticationError,
    ConnectorError,
    KnowledgeMetadataValidationError,
    PersistenceError,
    RateLimitExceeded,
    SchemaDriftError,
    SyncAlreadyRunningError,
    SyncLockUnavailableError,
    TimezoneNaiveError,
)
from .lens_engine import (
    Lens,
    LensCompilationError,
    LensNotFoundError,
    LensSecurityError,
    apply_lens,
    compile_filter,
    lens_query_for_table,
    load_lens,
)
from .orchestrator import run_sync
from .validation import ProtocolShapeError, validate_connector_shape

__all__ = [
    "ALLOWED_CIP_TABLES",
    "DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS",
    "DEFAULT_RATE_LIMIT",
    "HISTORY_TABLE_BY_CURRENT",
    "KNOWLEDGE_TEXT_REQUIRED_KEYS",
    "MAX_BATCH_RATE_LIMIT_RETRIES",
    "MAX_CONSECUTIVE_BATCH_FAILURES",
    "MAX_RATE_LIMIT_SLEEP_SECONDS",
    # Protocols + ABC helpers
    "CIPConnector",
    "CIPConnectorBase",
    "CIPMapper",
    "CIPMapperBase",
    # Value objects
    "CIPRow",
    "KnowledgeText",
    "KnowledgeTextMetadata",
    "PropertyDescriptor",
    "RateLimitPolicy",
    "SyncRunState",
    # Validators (boundary)
    "validate_knowledge_text_metadata",
    "validate_connector_shape",
    "ProtocolShapeError",
    # Exception hierarchy
    "AuthenticationError",
    "ConnectorError",
    "KnowledgeMetadataValidationError",
    "PersistenceError",
    "RateLimitExceeded",
    "SchemaDriftError",
    "TimezoneNaiveError",
    # M3 §4.7 — advisory-lock dual-run prevention
    "SyncAlreadyRunningError",
    "SyncLockUnavailableError",
    # M3 §4.1-§4.6 — canonical reference connector
    "FixtureConnector",
    "FixtureMapper",
    "CorpusSize",
    # M4 §4.1-§4.5 — Lens Engine (P-21 Multi-Lens by Default)
    "Lens",
    "LensCompilationError",
    "LensNotFoundError",
    "LensSecurityError",
    "apply_lens",
    "compile_filter",
    "lens_query_for_table",
    "load_lens",
    # Orchestrator entry point
    "run_sync",
]
