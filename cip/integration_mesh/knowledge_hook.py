# foundry: kind=service domain=client-intelligence-platform touches=knowledge
"""Knowledge-ingest hook (M2 §4.9 stub).

Locked-shape signature: ``ingest_texts_noop(texts: list[KnowledgeText]) -> None``.
M2 ships the no-op; M5 replaces the BODY with real Pinecone + FalkorDB
ingestion. Per D-133, the input shape is locked NOW so M5 does not
churn the Protocol contract.

M2 / M5 boundary (per §4.8 restate sign-off, 2026-04-29):
  - M2 OWNS: validator (``validate_knowledge_text_metadata``), call site
    (orchestrator's per-record finalize → validate → hook), the fail-loud
    contract (``KnowledgeMetadataValidationError`` + ``TimezoneNaiveError``
    are run-fatal), the non-validation-error → log+continue split per D-067.
  - M5 OWNS: only the implementation BODY of ``ingest_texts_noop``,
    which becomes real Knowledge+Graph ingestion.

Hook implementations (M5+) MUST NOT raise validation-class errors of
their own — those come from the validator BEFORE the hook is called.
Implementations MAY raise other ``Exception`` subclasses; the orchestrator
catches them at the call site and treats them as non-fatal (D-067).
"""
from __future__ import annotations

from .base import KnowledgeText


def ingest_texts_noop(texts: list[KnowledgeText]) -> None:
    """M2 stub. M5 replaces with actual Knowledge+Graph ingestion.

    Args:
        texts: List of ``KnowledgeText``. Metadata is already finalized
            and validated by the orchestrator (see §4.8 metadata-finalize
            block). Implementations can trust that all 5 required core
            keys (``source_id``, ``source_system``, ``extracted_at``,
            ``tenant_id``, ``connector_version``) are present and
            ``extracted_at`` is tz-aware.

    Raises:
        Nothing in M2. M5 implementations may raise non-validation
        ``Exception`` subclasses (network errors, Pinecone 503, FalkorDB
        unavailable, etc.); the orchestrator treats those as non-fatal
        per D-067 (knowledge extraction failures don't kill the run).
    """
    # Intentionally a no-op in M2.
    _ = texts  # silence unused-arg complaint
    return None
