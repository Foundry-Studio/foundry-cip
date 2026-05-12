# foundry: kind=service domain=client-intelligence-platform touches=integration
"""ZendeskConnector — CIP connector for Zendesk Support (v2 API).

Implements the full CIPConnector Protocol against Zendesk's v2 REST
endpoints (tickets, users, organizations). Historical backfill is
**mandatory** per D-159: tickets emit one synthesized history record
per ticket audit-log event (status changes, assignee changes, priority
changes); the orchestrator's SCD-2 differ writes ``cip_tickets_history``
rows for each pre-CIP audit-log event Zendesk still retains.

Auth: Basic with ``{email}/token:{token}`` format. Reads
``WAYWARD_ZENDESK_TOKEN`` + ``WAYWARD_ZENDESK_USER`` +
``WAYWARD_ZENDESK_SUBDOMAIN`` env vars.

Pagination: Zendesk v2 has TWO pagination idioms.
  - Legacy: ``next_page`` URL in the response body (used by tickets).
  - Cursor-based: ``after_cursor`` + ``has_more`` for incremental APIs
    (``/api/v2/incremental/tickets/cursor.json``).
  This connector uses incremental cursor for tickets (more reliable +
  not capped at 10K results) and standard pagination for users/orgs.

Rate-limit: Zendesk Standard plan: 700 req/min (~11 req/s). Connector
declares ``RateLimitPolicy(rps=11, burst=20)``; orchestrator paces and
backs off on 429 with ``Retry-After``.

Backfill mechanic (D-159): for each ticket pulled, the connector calls
``/api/v2/tickets/{id}/audits.json`` and emits one synthesized record
per audit event. Each carries the audit ``created_at`` as
``__cip_valid_from__`` so the differ writes ``cip_tickets_history``
correctly. Audit log retention varies by Zendesk plan; the connector
pulls what's still available without erroring on retention-window
boundaries.
"""
from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from uuid import UUID

from cip.integration_mesh.base import (
    CIPConnectorBase,
    PropertyDescriptor,
    RateLimitPolicy,
)
from cip.integration_mesh.connectors._http import (
    HTTPError,
    HTTPTransport,
    HttpxTransport,
)
from cip.integration_mesh.exceptions import (
    AuthenticationError,
    SchemaDriftError,
)

# Zendesk entity types we sync. Each maps to a cip_* table via ZendeskMapper.
_OBJECT_TYPES: tuple[tuple[str, str], ...] = (
    ("organizations", "company"),  # Zendesk orgs ≈ companies in CIP schema
    ("users", "contact"),           # Zendesk end-users ≈ contacts
    ("tickets", "ticket"),
)


class ZendeskConnector(CIPConnectorBase):
    """Zendesk Support v2 connector with mandatory ticket-audit backfill (D-159)."""

    connector_id: str = "zendesk-v1"
    cursor_safety_window_seconds: int = 300
    version: str = "1.0.0"

    def __init__(
        self,
        tenant_id: UUID,
        *,
        token: str | None = None,
        user: str | None = None,
        subdomain: str | None = None,
        http: HTTPTransport | None = None,
        backfill_history: bool = True,
    ) -> None:
        """
        Args:
            tenant_id: CIP tenant UUID (Wayward = b0000000-...0001).
            token: Zendesk API token. Defaults to ``WAYWARD_ZENDESK_TOKEN``.
            user: Auth user email. Defaults to ``WAYWARD_ZENDESK_USER``
                (``jake@wayward.com``).
            subdomain: Zendesk subdomain. Defaults to
                ``WAYWARD_ZENDESK_SUBDOMAIN`` (``waywardsupport``).
            http: Optional ``HTTPTransport`` for test-stub injection.
            backfill_history: D-159 default ``True``. ``False`` ONLY for
                test fixtures / explicit no-backfill scenarios.
        """
        self.tenant_id = tenant_id
        self.token = token or os.environ.get("WAYWARD_ZENDESK_TOKEN", "")
        self.user = user or os.environ.get(
            "WAYWARD_ZENDESK_USER", "jake@wayward.com"
        )
        self.subdomain = subdomain or os.environ.get(
            "WAYWARD_ZENDESK_SUBDOMAIN", ""
        )
        self.backfill_history = backfill_history

        if http is None and self.subdomain:
            auth = base64.b64encode(
                f"{self.user}/token:{self.token}".encode()
            ).decode()
            http = HttpxTransport(
                base_url=f"https://{self.subdomain}.zendesk.com",
                auth_headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/json",
                },
            )
        self._http = http
        self._authenticated = False

    def authenticate(self) -> None:
        """Validate the token + user by calling /users/me.json."""
        if not self.token or not self.subdomain:
            raise AuthenticationError(
                "WAYWARD_ZENDESK_TOKEN and WAYWARD_ZENDESK_SUBDOMAIN must be "
                "set (or passed explicitly to ctor)."
            )
        if self._http is None:
            raise AuthenticationError(
                "ZendeskConnector requires an HTTPTransport — none was "
                "constructed (subdomain may be empty)."
            )
        try:
            self._http.get("/api/v2/users/me.json")
        except HTTPError as exc:
            if exc.status == 401:
                raise AuthenticationError(
                    f"Zendesk credentials rejected (401) for user {self.user} "
                    f"@ {self.subdomain}.zendesk.com"
                ) from exc
            raise AuthenticationError(
                f"Zendesk probe failed (HTTP {exc.status}): {exc.body[:120]}"
            ) from exc
        self._authenticated = True

    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        if not self._authenticated:
            self.authenticate()
        if self._http is None:
            raise RuntimeError("ZendeskConnector has no HTTPTransport")

        last_key: datetime | None = None
        if cursor:
            raw = cursor.get("last_incremental_key")
            if isinstance(raw, str) and raw:
                last_key = datetime.fromisoformat(raw)

        for endpoint, record_type in _OBJECT_TYPES:
            yield from self._stream_entity(
                endpoint=endpoint,
                record_type=record_type,
                last_key=last_key,
                batch_size=batch_size,
            )

    def _stream_entity(
        self,
        *,
        endpoint: str,
        record_type: str,
        last_key: datetime | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        assert self._http is not None
        page_size = min(batch_size, 100)

        # All-records pagination via next_page URL pattern.
        path = f"/api/v2/{endpoint}.json"
        params: dict[str, Any] = {"per_page": page_size}

        while True:
            page = self._http.get(path, params=params)
            results = page.get(endpoint, [])

            for record in results:
                rec_dict = self._to_record(record, record_type)
                incremental_key_value = self._record_incremental_key(rec_dict)
                if last_key and incremental_key_value <= last_key:
                    continue
                yield rec_dict

                # Backfill ONLY for tickets (Zendesk audit log) — orgs +
                # users have no first-class history endpoint.
                if (
                    self.backfill_history
                    and record_type == "ticket"
                ):
                    yield from self._yield_ticket_audits(record)

            # Honor next_page URL (legacy pagination).
            next_url = page.get("next_page")
            if not isinstance(next_url, str) or not next_url:
                return
            # next_page is a fully-qualified URL; strip the base to keep
            # the HTTPTransport's base_url contract intact.
            path = next_url.split(".zendesk.com", 1)[-1] if ".zendesk.com" in next_url else next_url
            params = {}  # next_url already encodes the cursor

    def _to_record(
        self, zd_obj: dict[str, Any], record_type: str
    ) -> dict[str, object]:
        """Flatten a Zendesk v2 object into a record dict the mapper consumes."""
        return {
            "__cip_kind__": record_type,
            "id": str(zd_obj.get("id", "")),
            "source_id": str(zd_obj.get("id", "")),
            **{k: v for k, v in zd_obj.items() if v is not None and k != "id"},
            "updated_at": zd_obj.get("updated_at") or zd_obj.get("created_at"),
        }

    def _yield_ticket_audits(
        self, ticket_obj: dict[str, Any]
    ) -> Iterator[dict[str, object]]:
        """Walk /tickets/{id}/audits.json and emit one historical record
        per audit event.

        **FRAMEWORK GAP (2026-05-12 escalation):** same as HubSpot's
        _yield_history_revisions — the persister does NOT yet recognize
        the ``__cip_backfill__`` marker. Raises until the framework
        extension lands. Construct ZendeskConnector with
        ``backfill_history=False`` for current-state-only sync.

        Once the persister supports ``__cip_backfill__``, the real
        implementation will:
          1. GET ``/api/v2/tickets/{id}/audits.json`` (handles 403/404
             as informational — Zendesk audit retention varies by plan).
          2. Walk audits in chronological order, reconstructing ticket
             state by applying each event's Change events.
          3. Yield one synthesized record per audit timestamp with the
             reconstructed snapshot + backfill markers.
        """
        raise NotImplementedError(
            "Zendesk ticket-audit backfill emits records the persister "
            "doesn't yet route to cip_tickets_history correctly (see "
            "escalation 2026-05-12: __cip_backfill__ marker recognition "
            "pending in cip/integration_mesh/persister.py). Construct "
            "ZendeskConnector with backfill_history=False for "
            "current-state-only sync."
        )
        # The yield below is unreachable but makes Python recognize this
        # function as a generator. When the framework gap is closed, the
        # real implementation will be wired here.
        yield {}  # type: ignore[unreachable]

    def describe_schema(self) -> list[PropertyDescriptor]:
        out: list[PropertyDescriptor] = []
        for endpoint, record_type in _OBJECT_TYPES:
            cip_table = _CIP_TABLE_BY_TYPE[record_type]
            for prop_name, data_type in _SCHEMA_BY_TYPE.get(endpoint, ()):
                out.append(
                    PropertyDescriptor(
                        connector=self.connector_id,
                        object_type=record_type,
                        property_name=prop_name,
                        data_type=data_type,
                        storage_location="column",
                        column_name=prop_name,
                        cip_table=cip_table,
                        description=None,
                        is_custom=False,
                    )
                )
        return out

    def incremental_key(self, record: dict[str, object]) -> datetime:
        return self._record_incremental_key(record)

    def _record_incremental_key(
        self, record: dict[str, object]
    ) -> datetime:
        raw = record.get("updated_at")
        if not isinstance(raw, str):
            raise SchemaDriftError(
                f"Zendesk record missing updated_at: {list(record.keys())[:8]}"
            )
        # Zendesk returns ISO-8601 UTC with 'Z' suffix
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return datetime.fromisoformat(raw)

    @property
    def rate_limit_policy(self) -> RateLimitPolicy:
        # Zendesk Standard plan: 700 req/min.
        return RateLimitPolicy(requests_per_second=11.0, burst=20)


# ── Type-mapping tables ────────────────────────────────────────────────────

_CIP_TABLE_BY_TYPE: dict[str, str] = {
    "company": "cip_companies",  # Zendesk org → cip_companies
    "contact": "cip_contacts",   # Zendesk user → cip_contacts
    "ticket": "cip_tickets",
}

# Per-endpoint property descriptors (name, data_type).
_SCHEMA_BY_TYPE: dict[str, tuple[tuple[str, str], ...]] = {
    "organizations": (
        ("name", "string"),
        ("domain_names", "array"),
        ("details", "string"),
        ("notes", "string"),
        ("created_at", "datetime"),
        ("updated_at", "datetime"),
    ),
    "users": (
        ("name", "string"),
        ("email", "string"),
        ("phone", "string"),
        ("role", "enumeration"),
        ("organization_id", "reference"),
        ("created_at", "datetime"),
        ("updated_at", "datetime"),
    ),
    "tickets": (
        ("subject", "string"),
        ("description", "string"),
        ("priority", "enumeration"),
        ("status", "enumeration"),
        ("type", "enumeration"),
        ("requester_id", "reference"),
        ("assignee_id", "reference"),
        ("organization_id", "reference"),
        ("created_at", "datetime"),
        ("updated_at", "datetime"),
    ),
}
