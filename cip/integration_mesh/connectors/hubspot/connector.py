# foundry: kind=service domain=client-intelligence-platform touches=integration
"""HubSpotConnector — CIP connector for HubSpot CRM (v3 API).

Implements the full CIPConnector Protocol against HubSpot's v3 CRM
endpoints (companies, contacts, deals, tickets). Historical backfill is
**mandatory** per D-159: on first sync for any new tenant, the connector
pulls each record's full property-history (up to HubSpot's 20-revision
retention window per property) and yields synthesized records to the
orchestrator so the SCD-2 differ writes ``cip_*_history`` rows for every
pre-CIP revision.

Auth: Private App Tokens (PATs, ``pat-*`` prefix). Read from
``WAYWARD_HUBSPOT_TOKEN`` env var. Bearer-auth header.

Pagination: HubSpot v3 uses the ``after`` cursor token; pages of up to
100. The connector caps per-request size at 100 (HubSpot maximum) and
yields records one-at-a-time so the orchestrator chunks at the caller's
``batch_size``.

Rate-limit: HubSpot Standard plan allows 100 requests / 10 second burst
(=10 req/s sustained). The connector declares ``RateLimitPolicy(rps=10,
burst=10)``; the orchestrator's TokenBucket paces ``stream_records`` and
backoff/retries on 429 responses with the ``Retry-After`` header.

Backfill mechanic (D-159): when the connector pulls a record's
current-state via the standard endpoint, it ALSO calls
``/crm/v3/objects/{type}/{id}?propertiesWithHistory=<csv-of-tracked-props>``
to retrieve each property's revision history. For every prior revision
the connector synthesizes a record dict with the historical property
values + the historical timestamp + a ``__cip_backfill__: True`` marker
the mapper inspects to set ``valid_from`` / ``valid_to`` correctly. The
synthesized records are yielded ascending by `valid_from` so the SCD-2
differ writes history rows in chronological order.

Reference: ``cip/integration_mesh/connectors/fixture/connector.py`` for
the canonical Protocol shape; ``WORKBENCH/tim/ventures/ecomlever/clients/
wayward/pull-hubspot.py`` (monorepo) for HubSpot API examples (pre-CIP-
framework — this connector replaces it cleanly).
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
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

_HUBSPOT_BASE_URL = "https://api.hubapi.com"

# HubSpot v3 endpoints we ingest. Each maps to a cip_* entity table via
# HubSpotMapper. Order is deterministic for sync repeatability.
_OBJECT_TYPES: tuple[tuple[str, str], ...] = (
    ("companies", "company"),  # (HubSpot path, mapper record_type)
    ("contacts", "contact"),
    ("deals", "deal"),
    ("tickets", "ticket"),
)

# Properties we request on every entity. HubSpot returns a stable subset
# by default; explicit list documents the columns we map. Custom-portal
# properties are discovered at runtime via the Properties API in
# describe_schema().
_DEFAULT_PROPERTIES: dict[str, tuple[str, ...]] = {
    "companies": (
        "name", "domain", "industry", "city", "country", "numberofemployees",
        "annualrevenue", "createdate", "hs_lastmodifieddate", "lifecyclestage",
    ),
    "contacts": (
        "firstname", "lastname", "email", "phone", "company", "jobtitle",
        "createdate", "lastmodifieddate", "lifecyclestage",
    ),
    "deals": (
        "dealname", "amount", "dealstage", "pipeline", "closedate",
        "createdate", "hs_lastmodifieddate", "hubspot_owner_id",
    ),
    "tickets": (
        "subject", "content", "hs_pipeline", "hs_pipeline_stage",
        "hs_ticket_priority", "createdate", "hs_lastmodifieddate",
    ),
}


class HubSpotConnector(CIPConnectorBase):
    """HubSpot v3 CRM connector with mandatory historical backfill (D-159)."""

    connector_id: str = "hubspot-v1"
    cursor_safety_window_seconds: int = 300  # 5 min replica-lag absorption
    version: str = "1.0.0"

    def __init__(
        self,
        tenant_id: UUID,
        *,
        token: str | None = None,
        portal_id: int | None = None,
        http: HTTPTransport | None = None,
        backfill_history: bool = True,
    ) -> None:
        """
        Args:
            tenant_id: CIP tenant UUID (Wayward = b0000000-...0001).
            token: HubSpot PAT. Defaults to ``WAYWARD_HUBSPOT_TOKEN`` env.
            portal_id: HubSpot portal/hub identifier. Defaults to
                ``WAYWARD_HUBSPOT_PORTAL_ID`` env.
            http: Optional ``HTTPTransport`` for test-stub injection.
                When None, the default httpx-backed transport is used.
            backfill_history: D-159 default ``True``. Set ``False`` ONLY
                for explicit no-backfill scenarios (test fixtures, retry-
                of-current-state-only mid-incident). Production code
                should never override.
        """
        self.tenant_id = tenant_id
        self.token = token or os.environ.get("WAYWARD_HUBSPOT_TOKEN", "")
        self.portal_id = portal_id or int(
            os.environ.get("WAYWARD_HUBSPOT_PORTAL_ID", "0") or "0"
        )
        self.backfill_history = backfill_history
        self._http = http or HttpxTransport(
            base_url=_HUBSPOT_BASE_URL,
            auth_headers={"Authorization": f"Bearer {self.token}"},
        )
        self._authenticated = False

    def authenticate(self) -> None:
        """Validate the PAT by making a minimal read call. HubSpot PATs
        don't have a dedicated validate-token endpoint; the canonical
        check is a small CRM call that returns 401 on bad creds."""
        if not self.token:
            raise AuthenticationError(
                "WAYWARD_HUBSPOT_TOKEN not set; pass token=<...> or set env"
            )
        try:
            self._http.get(
                "/crm/v3/objects/companies", params={"limit": 1}
            )
        except HTTPError as exc:
            if exc.status == 401:
                raise AuthenticationError(
                    f"HubSpot token rejected (401). Token starts: "
                    f"{self.token[:8]}..."
                ) from exc
            # Other HTTP errors during authenticate are also run-fatal
            raise AuthenticationError(
                f"HubSpot probe failed (HTTP {exc.status}): {exc.body[:120]}"
            ) from exc
        self._authenticated = True

    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        """Yield records from all 4 entity types in order, optionally
        backfilling property-history for each."""
        if not self._authenticated:
            self.authenticate()

        last_key: datetime | None = None
        if cursor:
            raw = cursor.get("last_incremental_key")
            if isinstance(raw, str) and raw:
                last_key = datetime.fromisoformat(raw)

        for hubspot_path, record_type in _OBJECT_TYPES:
            yield from self._stream_entity(
                hubspot_path=hubspot_path,
                record_type=record_type,
                last_key=last_key,
                batch_size=batch_size,
            )

    def _stream_entity(
        self,
        *,
        hubspot_path: str,
        record_type: str,
        last_key: datetime | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        """Paginate one entity type. For each record:
          1. Emit the current-state record (record_type=<singular>).
          2. If backfill_history is True, emit one record per historical
             property revision (record_type=<singular>, with
             __cip_backfill__=True + __cip_valid_from__ set).
        """
        page_size = min(batch_size, 100)  # HubSpot caps at 100
        properties = _DEFAULT_PROPERTIES.get(hubspot_path, ())
        properties_with_history = ",".join(properties) if self.backfill_history else ""
        after: str | None = None

        while True:
            params: dict[str, str | int] = {
                "limit": page_size,
                "properties": ",".join(properties),
            }
            if properties_with_history:
                params["propertiesWithHistory"] = properties_with_history
            if after:
                params["after"] = after

            page = self._http.get(f"/crm/v3/objects/{hubspot_path}", params=params)
            results = page.get("results", [])

            for record in results:
                rec_dict = self._to_record(record, record_type)
                # Filter incremental on current-state.
                incremental_key_value = self._record_incremental_key(rec_dict)
                if last_key and incremental_key_value <= last_key:
                    continue
                yield rec_dict

                if self.backfill_history:
                    yield from self._yield_history_revisions(
                        record, record_type
                    )

            paging = page.get("paging", {})
            after = paging.get("next", {}).get("after") if isinstance(paging, dict) else None
            if not after:
                return

    def _to_record(
        self, hubspot_obj: dict[str, Any], record_type: str
    ) -> dict[str, object]:
        """Flatten a HubSpot v3 object into a record dict the mapper consumes."""
        props = hubspot_obj.get("properties", {}) or {}
        return {
            "__cip_kind__": record_type,
            "id": str(hubspot_obj.get("id", "")),
            "source_id": str(hubspot_obj.get("id", "")),
            **{k: v for k, v in props.items() if v is not None},
            "updated_at": (
                props.get("hs_lastmodifieddate")
                or props.get("lastmodifieddate")
                or props.get("createdate")
                or hubspot_obj.get("updatedAt")
            ),
        }

    def _yield_history_revisions(
        self, hubspot_obj: dict[str, Any], record_type: str
    ) -> Iterator[dict[str, object]]:
        """For each property with history, emit one record per prior
        revision (oldest first).

        **FRAMEWORK GAP (2026-05-12 escalation):** the persister does NOT
        yet recognize the ``__cip_backfill__`` marker; if these records
        flowed through as-is, the SCD-2 differ would treat each as a
        current-state update and stamp ``valid_from = NOW()`` instead of
        the actual historical timestamp — destroying the time-series the
        contract exists to preserve. Pending persister extension; until
        then this method raises NotImplementedError so backfill-enabled
        syncs fail loud instead of producing misleading history rows.

        To run a current-state-only sync against real source systems
        while the framework extension is pending, construct with
        ``backfill_history=False``.

        Once the persister supports ``__cip_backfill__``, the real
        implementation will:
          1. Read ``hubspot_obj['propertiesWithHistory']`` (dict of
             prop_name → list of {timestamp, value, sourceType, ...}).
          2. Flatten + group revisions by timestamp; build per-snapshot
             dicts of property values.
          3. Sort oldest → newest and yield each as a synthesized record
             with ``__cip_backfill__: True`` + ``__cip_valid_from__`` +
             ``__cip_valid_to__`` markers.
        """
        raise NotImplementedError(
            "HubSpot property-history backfill emits records the persister "
            "doesn't yet route to cip_*_history correctly (see escalation "
            "2026-05-12: __cip_backfill__ marker recognition pending in "
            "cip/integration_mesh/persister.py). Construct HubSpotConnector "
            "with backfill_history=False for current-state-only sync."
        )
        # The yield below is unreachable but makes Python recognize this
        # function as a generator (for the Iterator return type). When the
        # framework gap is closed, the real implementation will be wired here.
        yield {}  # type: ignore[unreachable]

    def describe_schema(self) -> list[PropertyDescriptor]:
        """Return PropertyDescriptors for the default properties on each
        entity. Custom-portal properties not yet enumerated — future
        enhancement queries ``/crm/v3/properties/{type}`` per entity to
        discover ``is_custom=True`` properties dynamically.
        """
        out: list[PropertyDescriptor] = []
        for hubspot_path, record_type in _OBJECT_TYPES:
            cip_table = _CIP_TABLE_BY_TYPE[record_type]
            for prop_name in _DEFAULT_PROPERTIES.get(hubspot_path, ()):
                data_type = _DATA_TYPE_BY_PROP.get(prop_name, "string")
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
        """Return tz-aware datetime from the record's updated_at field."""
        return self._record_incremental_key(record)

    def _record_incremental_key(
        self, record: dict[str, object]
    ) -> datetime:
        raw = record.get("updated_at")
        if not isinstance(raw, str):
            raise SchemaDriftError(
                f"HubSpot record missing updated_at: {list(record.keys())[:8]}"
            )
        # HubSpot returns either ISO-8601 with 'Z' suffix OR epoch-millis
        # string depending on the API endpoint version.
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw) / 1000, UTC)
        return datetime.fromisoformat(raw)

    @property
    def rate_limit_policy(self) -> RateLimitPolicy:
        # HubSpot Standard plan: 100 req / 10 sec burst.
        return RateLimitPolicy(requests_per_second=10.0, burst=10)


# ── Type-mapping tables ────────────────────────────────────────────────────

_CIP_TABLE_BY_TYPE: dict[str, str] = {
    "company": "cip_companies",
    "contact": "cip_contacts",
    "deal": "cip_deals",
    "ticket": "cip_tickets",
}

_DATA_TYPE_BY_PROP: dict[str, str] = {
    # numeric
    "numberofemployees": "number",
    "annualrevenue": "number",
    "amount": "number",
    # datetime
    "createdate": "datetime",
    "hs_lastmodifieddate": "datetime",
    "lastmodifieddate": "datetime",
    "closedate": "datetime",
    # enum
    "lifecyclestage": "enumeration",
    "dealstage": "enumeration",
    "hs_pipeline": "enumeration",
    "hs_pipeline_stage": "enumeration",
    "hs_ticket_priority": "enumeration",
    "pipeline": "enumeration",
    # reference
    "hubspot_owner_id": "reference",
}


