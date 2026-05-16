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
    HistoricalRecord,
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
    ("organizations", "company"),  # Zendesk orgs ~= companies in CIP schema
    ("users", "contact"),           # Zendesk end-users ~= contacts
    ("tickets", "ticket"),
)

# Per-entity incremental endpoint + pagination mode.
#
# Bug history (2026-05-13/14): legacy ``next_page`` URL pagination on
# /api/v2/organizations.json silently returned page 1 indefinitely
# (22-hour infinite loop on Wayward).
#
# Bug history (2026-05-15): the prior "all three use cursor" fix
# assumed parity with tickets/users. Reality: Zendesk has NEVER
# shipped a ``/api/v2/incremental/organizations/cursor.json`` endpoint
# (returns 404 "InvalidEndpoint"). Organizations only support
# ``/api/v2/incremental/organizations.json`` time-based incremental
# with ``next_page`` URL pagination and ``count < per_page`` /
# ``end_of_stream`` termination.
#
# So: tickets + users use cursor-incremental (documented stable).
# Organizations use time-based incremental (the only available
# incremental option). Both terminate cleanly without the legacy
# offset-pagination footgun.
_PAGINATION_CURSOR = "cursor"
_PAGINATION_TIME = "time"
_INCREMENTAL_PATH: dict[str, tuple[str, str]] = {
    "organizations": (
        "/api/v2/incremental/organizations.json",
        _PAGINATION_TIME,
    ),
    "users": ("/api/v2/incremental/users/cursor.json", _PAGINATION_CURSOR),
    "tickets": (
        "/api/v2/incremental/tickets/cursor.json",
        _PAGINATION_CURSOR,
    ),
}


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

        Note: ``stream_records()`` emits current-state only. Historical
        backfill is a separate method (``backfill_history``) invoked by
        ``orchestrator.run_backfill()`` after run_sync — per D-159.
        """
        self.tenant_id = tenant_id
        self.token = token or os.environ.get("WAYWARD_ZENDESK_TOKEN", "")
        self.user = user or os.environ.get(
            "WAYWARD_ZENDESK_USER", "jake@wayward.com"
        )
        self.subdomain = subdomain or os.environ.get(
            "WAYWARD_ZENDESK_SUBDOMAIN", ""
        )

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
        """Dispatch on per-endpoint pagination mode.

        Zendesk has two incremental APIs:
          - Cursor-based (``/api/v2/incremental/{type}/cursor.json``)
            for tickets + users — documented stable, no 10K cap.
          - Time-based (``/api/v2/incremental/organizations.json``)
            for organizations — the only incremental option Zendesk
            ships for orgs; cursor variant returns 404.

        Both use ``start_time`` seeding from ``last_key`` for incremental
        syncs (``start_time=0`` for full initial sync). Both terminate
        via explicit ``end_of_stream`` or absence of next-page marker.
        """
        assert self._http is not None
        path, mode = _INCREMENTAL_PATH[endpoint]
        if mode == _PAGINATION_CURSOR:
            yield from self._stream_cursor(
                path=path,
                endpoint=endpoint,
                record_type=record_type,
                last_key=last_key,
                batch_size=batch_size,
            )
        elif mode == _PAGINATION_TIME:
            yield from self._stream_time_incremental(
                path=path,
                endpoint=endpoint,
                record_type=record_type,
                last_key=last_key,
                batch_size=batch_size,
            )
        else:
            raise RuntimeError(
                f"Unknown pagination mode {mode!r} for endpoint {endpoint}"
            )

    def _stream_cursor(
        self,
        *,
        path: str,
        endpoint: str,
        record_type: str,
        last_key: datetime | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        """Cursor-incremental pagination (tickets, users)."""
        assert self._http is not None
        page_size = min(batch_size, 1000)
        params: dict[str, Any] = {"per_page": page_size}
        if last_key is not None:
            params["start_time"] = int(last_key.timestamp())
        else:
            params["start_time"] = 0

        while True:
            page = self._http.get(path, params=params)
            for record in page.get(endpoint, []):
                rec_dict = self._to_record(record, record_type)
                ikv = self._record_incremental_key(rec_dict)
                if last_key and ikv <= last_key:
                    continue
                yield rec_dict

            if page.get("end_of_stream") is True:
                return
            after_cursor = page.get("after_cursor")
            if not isinstance(after_cursor, str) or not after_cursor:
                return
            params = {"per_page": page_size, "cursor": after_cursor}

    def _stream_time_incremental(
        self,
        *,
        path: str,
        endpoint: str,
        record_type: str,
        last_key: datetime | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        """Time-based incremental pagination (organizations).

        Zendesk's time-based incremental returns up to 1000 records per
        call, sorted by ``updated_at`` ascending. Termination is via:
          - ``count < per_page`` (canonical), OR
          - missing ``next_page`` URL, OR
          - ``end_of_stream`` true (newer responses include this too).

        We advance ``start_time`` from the response's ``end_time`` rather
        than following ``next_page`` URLs, because the latter caused the
        2026-05-13 infinite loop when Zendesk returned page 1 forever for
        a non-cursor-aware endpoint.
        """
        assert self._http is not None
        page_size = min(batch_size, 1000)
        start_time = (
            int(last_key.timestamp()) if last_key is not None else 0
        )

        while True:
            params: dict[str, Any] = {
                "per_page": page_size,
                "start_time": start_time,
            }
            page = self._http.get(path, params=params)
            records = page.get(endpoint, [])
            for record in records:
                rec_dict = self._to_record(record, record_type)
                ikv = self._record_incremental_key(rec_dict)
                if last_key and ikv <= last_key:
                    continue
                yield rec_dict

            count = page.get("count")
            if isinstance(count, int) and count < page_size:
                return
            if page.get("end_of_stream") is True:
                return
            end_time = page.get("end_time")
            if not isinstance(end_time, int) or end_time <= start_time:
                # No forward progress; defensive exit to avoid infinite loop.
                return
            start_time = end_time

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

    def backfill_history(
        self, tenant_id: UUID
    ) -> Iterator[HistoricalRecord]:
        """D-159 historical backfill via Zendesk Ticket Audits API.

        Iterates all tickets (organizations + users have no first-class
        history endpoint in Zendesk v2), and for each ticket fetches
        ``/api/v2/tickets/{id}/audits.json``. Walks audits in chronological
        order, reconstructing ticket state at each event by replaying
        ``Change`` events forward. Yields one ``HistoricalRecord`` per
        audit timestamp with the snapshot at that moment.

        Caller responsibility: run ``run_sync()`` first to materialize
        ``cip_tickets`` current state.

        Bug history (2026-05-15): the previous implementation iterated
        tickets via /api/v2/tickets.json with next_page URL pagination.
        That endpoint silently returns page 1 forever on Wayward's
        cursor-migrated portal (same root cause as the 2026-05-13 orgs
        infinite-loop bug). Net effect: 6h 45min of backfill processed
        only 100 unique tickets repeatedly, generating 112,400 duplicate
        cip_tickets_history rows (avg 1,128/ticket; real tickets have
        ~10-30 audit events). Fixed by iterating tickets via the same
        cursor-incremental endpoint used in stream_records
        (/api/v2/incremental/tickets/cursor.json with after_cursor +
        end_of_stream termination + defensive return) — the
        Zendesk-documented stable pagination, not the legacy URL.
        """
        if not self._authenticated:
            self.authenticate()
        if self._http is None:
            return

        # Cursor-incremental tickets endpoint (same as stream_records
        # uses). per_page max 1000. start_time=0 = "from the beginning."
        path = _INCREMENTAL_PATH["tickets"][0]  # cursor-mode path
        page_size = 100
        params: dict[str, Any] = {
            "per_page": page_size,
            "start_time": 0,
        }

        while True:
            page = self._http.get(path, params=params)
            tickets = page.get("tickets", [])
            for ticket in tickets:
                yield from self._historical_records_for_ticket(ticket)

            if page.get("end_of_stream") is True:
                return
            after_cursor = page.get("after_cursor")
            if not isinstance(after_cursor, str) or not after_cursor:
                # No further cursor + not end_of_stream: defensively
                # return (avoid infinite loop on missing terminator).
                return
            params = {"per_page": page_size, "cursor": after_cursor}

    def _historical_records_for_ticket(
        self, ticket_obj: dict[str, Any]
    ) -> Iterator[HistoricalRecord]:
        """Walk one ticket's audit log; yield HistoricalRecord per snapshot."""
        assert self._http is not None
        ticket_id = ticket_obj.get("id")
        if not ticket_id:
            return
        try:
            audits_page = self._http.get(
                f"/api/v2/tickets/{ticket_id}/audits.json"
            )
        except HTTPError as exc:
            if exc.status in (403, 404):
                return
            return

        audits = audits_page.get("audits", [])
        audits.sort(key=lambda a: a.get("created_at", ""))

        # Reconstruct ticket state by applying Change events forward.
        # Start from initial state seen in the audit's first Create event
        # (or fall back to current state from the ticket object).
        snapshot: dict[str, Any] = {
            "subject": ticket_obj.get("subject"),
            "description": ticket_obj.get("description"),
            "priority": ticket_obj.get("priority"),
            "status": ticket_obj.get("status"),
        }
        source_id = str(ticket_id)

        for idx, audit in enumerate(audits):
            ts_raw = audit.get("created_at")
            if not isinstance(ts_raw, str):
                continue
            # Apply Change events to snapshot.
            for event in audit.get("events", []):
                if event.get("type") == "Change":
                    field = event.get("field_name")
                    new_val = event.get("value")
                    if field in snapshot:
                        snapshot[field] = new_val

            valid_from = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            next_ts = (
                audits[idx + 1].get("created_at")
                if idx + 1 < len(audits) else None
            )
            valid_to = (
                datetime.fromisoformat(next_ts.replace("Z", "+00:00"))
                if isinstance(next_ts, str) and next_ts else None
            )

            fields = {k: v for k, v in snapshot.items() if v is not None}
            if "subject" not in fields:
                fields["subject"] = "(no subject)"

            yield HistoricalRecord(
                target_table="cip_tickets",
                source_id=source_id,
                valid_from=valid_from,
                valid_to=valid_to,
                fields=fields,
                overflow={},
                changed_by=self.connector_id,
                change_reason=f"zendesk-audit-event[{ts_raw}]",
            )

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
