# foundry: kind=service domain=client-intelligence-platform touches=knowledge
"""Knowledge-ingest hook (M2 §4.9 call site; M5 body).

Locked-shape signature: ``ingest_texts_noop(texts: list[KnowledgeText]) -> None``.

M2 / M5 boundary (per §4.8 restate sign-off, 2026-04-29), unchanged:
  - M2 OWNS: validator (``validate_knowledge_text_metadata``), call site
    (orchestrator's per-record finalize → validate → hook), the fail-loud
    contract (``KnowledgeMetadataValidationError`` + ``TimezoneNaiveError``
    are run-fatal), the non-validation-error → log+continue split per D-067.
  - M5 OWNS: only the implementation BODY of ``ingest_texts_noop``.

WHAT CHANGED 2026-09-04. The body is no longer unconditionally a no-op. It
dispatches to a registered sink, and the signature, the call site and the
validation contract are all untouched — which is what keeps this inside M5's
half of the line.

WHY A REGISTERED SINK rather than the body constructing its own writer. The
locked signature takes only ``texts``: no session, no tenant, no clients. A
body that reached for its own database connection and Pinecone client would be
building hidden global state on every call, and would be untestable without
both. Registration keeps the dependency explicit and lets a caller install a
sink for exactly as long as a sync runs.

THE DEFAULT IS STILL A NO-OP, and that is a real state, not a placeholder: with
no sink registered nothing is indexed. It now COUNTS what it discards. That
distinction matters here more than most places, because the corpus this feeds
sat frozen from 2026-05-22 with nobody noticing. A run that produces four
thousand knowledge texts and indexes none of them should be able to say so.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from .base import KnowledgeText

logger = logging.getLogger(__name__)

KnowledgeSink = Callable[[list[KnowledgeText]], None]

_sink: KnowledgeSink | None = None

#: Texts the default no-op has discarded since the last reset. Read by callers
#: that want to report "produced N, indexed 0" rather than reporting success.
discarded_text_count = 0


def set_knowledge_sink(sink: KnowledgeSink | None) -> None:
    """Install the sink ``ingest_texts_noop`` dispatches to.

    Pass ``None`` to restore the counting no-op. Callers that install a sink
    for the duration of a run should restore it afterwards, so one connector's
    sink cannot silently receive another's texts.
    """
    global _sink
    _sink = sink


def get_knowledge_sink() -> KnowledgeSink | None:
    return _sink


def reset_discarded_count() -> None:
    global discarded_text_count
    discarded_text_count = 0


def ingest_texts_noop(texts: list[KnowledgeText]) -> None:
    """Dispatch ``texts`` to the registered sink, or count them as discarded.

    Args:
        texts: metadata already finalized and validated by the orchestrator
            (see §4.8). Implementations can trust that all 5 required core
            keys are present and ``extracted_at`` is tz-aware, and MUST NOT
            re-validate — that would move M2's contract into M5's body.

    Raises:
        Nothing itself. A sink MAY raise non-validation ``Exception``
        subclasses (network errors, Pinecone 503, database unavailable); the
        orchestrator catches those at the call site and treats them as
        non-fatal per D-067.

        That non-fatal treatment is precisely why a sink must count and log its
        own partial failures. Anything it drops quietly is dropped for good:
        the orchestrator will log one warning and the run will still report
        success.
    """
    global discarded_text_count
    if _sink is None:
        discarded_text_count += len(texts)
        return
    _sink(texts)
