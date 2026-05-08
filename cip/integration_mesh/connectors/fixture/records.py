# foundry: kind=service domain=client-intelligence-platform touches=integration
"""TypedDict shapes for FixtureConnector records (M3 §4.3 binding).

Each record dict has a ``record_type`` discriminator + a stable ``source_id``
+ a tz-aware ISO-8601 UTC ``updated_at`` + the type-specific fields. The
mapper's ``map()`` inspects ``record_type`` to dispatch to the right
``CIPRow.target_table``.

Plan-vs-reality reconciliation (M3 Δ1, 2026-05-07):
Plan §4.3 names the discriminator ``__type``. Python's name-mangling rule
mangles ``__type`` (double-leading-underscore, no double-trailing) inside a
class body to ``_ClassName__type`` — including TypedDict subclasses, whose
``__annotations__`` then store the mangled name and TypedDict typechecks
fail to match a dict literal carrying key ``"__type"``. Reconciliation:
rename to ``record_type`` (no mangling, no semantic loss). Mapper +
corpus generators dispatch on ``record_type`` accordingly.
Atlas v5.5 / M3-hygiene TODO: update plan §4.3 / §4.4 / §4.6 to use
``record_type``.
"""
from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


# ``record_type`` is declared on each subclass with its specific ``Literal``;
# leaving it off ``_BaseRecord`` avoids mypy --strict "Overwriting TypedDict
# field while extending" errors that arise when a subclass narrows a parent
# field's type. Each subclass below independently declares ``record_type``.
class _BaseRecord(TypedDict):
    source_id: str
    updated_at: str  # tz-aware ISO-8601 UTC
    id: str  # alias of source_id (legacy field connectors often emit)


class CompanyRecord(_BaseRecord):
    record_type: Literal["company"]
    name: str
    industry: NotRequired[str]
    region: NotRequired[str]
    employee_count: NotRequired[int]
    annual_revenue: NotRequired[float]
    domain: NotRequired[str]
    custom_field_1: NotRequired[str]
    custom_field_2: NotRequired[str]


class ContactRecord(_BaseRecord):
    record_type: Literal["contact"]
    first_name: str
    last_name: str
    email: str
    company_source_id: NotRequired[str]
    title: NotRequired[str]
    phone: NotRequired[str]
    region: NotRequired[str]


class DealRecord(_BaseRecord):
    record_type: Literal["deal"]
    name: str
    amount: float
    stage: str  # "qualifying" | "negotiating" | "closed_won" | "closed_lost"
    company_source_id: NotRequired[str]
    expected_close_date: NotRequired[str]
    owner: NotRequired[str]


class TicketRecord(_BaseRecord):
    record_type: Literal["ticket"]
    subject: str
    body: str  # ingested as KnowledgeText
    status: str  # "open" | "pending" | "resolved" | "closed"
    priority: str  # "low" | "normal" | "high" | "urgent"
    contact_source_id: NotRequired[str]
    assignee: NotRequired[str]


class DocumentRecord(_BaseRecord):
    record_type: Literal["document"]
    title: str
    body: str  # ingested as KnowledgeText
    company_source_id: NotRequired[str]
    file_size_bytes: NotRequired[int]
    mime_type: NotRequired[str]


# NoteRecord retained as TypedDict definition for forward-compatibility,
# but per v2 #2 (Senior #2) the STANDARD corpus drops note generation
# (notes_count = 0). Phase 2 may add a cip_notes migration if Wayward's
# note-distinct-from-ticket semantics require it.
class NoteRecord(_BaseRecord):
    record_type: Literal["note"]
    body: str
    contact_source_id: NotRequired[str]
    author: NotRequired[str]
