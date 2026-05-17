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

_HUBSPOT_BASE_URL = "https://api.hubapi.com"

# HubSpot v3 endpoints we ingest. Each maps to a cip_* entity table via
# HubSpotMapper. Order is deterministic for sync repeatability.
_OBJECT_TYPES: tuple[tuple[str, str], ...] = (
    ("companies", "company"),  # (HubSpot path, mapper record_type)
    ("contacts", "contact"),
    ("deals", "deal"),
    ("tickets", "ticket"),
)

# Engagement entity types (PM scope 9952dd26). Streamed via a separate
# method (_stream_engagements) on opt-in — keeps the existing CRM-object
# stream_records path unchanged. All engagement types land in a single
# cip_engagements table with engagement_type discriminator.
_ENGAGEMENT_TYPES: tuple[tuple[str, str], ...] = (
    ("notes", "engagement_note"),
    ("meetings", "engagement_meeting"),
    ("tasks", "engagement_task"),
    # calls + emails currently 0 records / 403 for Wayward; available
    # for future tenants without code changes — just add to this tuple
    # and the mapper will route to cip_engagements with the right type.
)

# Associations to fetch alongside each engagement so cross-entity queries
# work (e.g., "all notes on this deal"). HubSpot's batch read supports
# the `associations` parameter on the public CRM API.
_ENGAGEMENT_ASSOCIATIONS: tuple[str, ...] = (
    "contacts", "companies", "deals", "tickets",
)

# Explicit plural→singular for the association column-name suffix. Needed
# because "companies".rstrip("s") yields "companie" (rstrip removes
# trailing characters one at a time, not by English pluralization rules).
_ASSOC_SINGULAR: dict[str, str] = {
    "contacts": "contact",
    "companies": "company",
    "deals": "deal",
    "tickets": "ticket",
}

# Fallback property list used ONLY when discovery fails (network error,
# permission denied on /properties endpoint, etc.). In normal operation,
# the connector calls _discover_properties() on first use and fetches
# every property HubSpot exposes for the portal — ~300 per entity — so
# custom segmentation, ownership, partnership, Amazon, and platform-
# integration fields all land in cip_*.properties JSONB without having
# to be enumerated in code. Discovery output is cached per-connector-
# instance for the lifetime of the run (D-117 / scope 9c3d1393).
_FALLBACK_PROPERTIES: dict[str, tuple[str, ...]] = {
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
# Back-compat alias — some module-level imports reference the old name.
_DEFAULT_PROPERTIES = _FALLBACK_PROPERTIES


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
    ) -> None:
        """
        Args:
            tenant_id: CIP tenant UUID (Wayward = b0000000-...0001).
            token: HubSpot PAT. Defaults to ``WAYWARD_HUBSPOT_TOKEN`` env.
            portal_id: HubSpot portal/hub identifier. Defaults to
                ``WAYWARD_HUBSPOT_PORTAL_ID`` env.
            http: Optional ``HTTPTransport`` for test-stub injection.

        Note: ``stream_records()`` always emits current-state only.
        Historical backfill is a separate method (``backfill_history``)
        invoked by ``orchestrator.run_backfill()`` after ``run_sync`` —
        per D-159 + PM 218f67a4 implementation.
        """
        self.tenant_id = tenant_id
        self.token = token or os.environ.get("WAYWARD_HUBSPOT_TOKEN", "")
        self.portal_id = portal_id or int(
            os.environ.get("WAYWARD_HUBSPOT_PORTAL_ID", "0") or "0"
        )
        self._http = http or HttpxTransport(
            base_url=_HUBSPOT_BASE_URL,
            auth_headers={"Authorization": f"Bearer {self.token}"},
        )
        self._authenticated = False
        # Per-instance property catalog cache, populated lazily on first
        # call to _discover_properties(). Maps HubSpot path (e.g.,
        # "companies") to tuple of property names to fetch. Excludes
        # calculated and read-only-aggregate properties (HubSpot returns
        # those as derived values, not stored fields, and they don't
        # have history). See _discover_properties() for filter logic.
        self._discovered_properties: dict[str, tuple[str, ...]] = {}
        # Entities we've already determined we have no permission for
        # (403 on properties endpoint). Skipped silently on subsequent
        # access. Per-entity isolation per scope d3311846.
        self._unavailable_entities: set[str] = set()

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
            if hubspot_path in self._unavailable_entities:
                continue
            try:
                yield from self._stream_entity(
                    hubspot_path=hubspot_path,
                    record_type=record_type,
                    last_key=last_key,
                    batch_size=batch_size,
                )
            except HTTPError as exc:
                # Per-entity isolation (scope d3311846): if HubSpot says
                # this token can't access this entity, mark unavailable
                # and continue with the rest. Equivalent to the Wayward
                # tickets-403 case that cascade-killed the run on 2026-05-14.
                if exc.status in {401, 403}:
                    self._unavailable_entities.add(hubspot_path)
                    continue
                # Other HTTP errors are still entity-fatal but not
                # connector-fatal — let the orchestrator decide.
                raise

    def _discover_properties(self, hubspot_path: str) -> tuple[str, ...]:
        """Fetch the full property catalog for an entity type from HubSpot's
        Properties API and cache it per-instance.

        Calls ``/crm/v3/properties/{type}`` once. Returns every property
        name except those marked ``calculated`` (HubSpot derives those at
        read time; they don't represent stored fields and aren't meaningful
        to backfill). Filtering applies to both stream_records (current
        state) and backfill_history (so history reads are property-aligned).

        On 403/401: returns the fallback tuple, marks entity unavailable.
        On other error: returns the fallback tuple, doesn't mark unavailable
        (caller will hit the same error on the data endpoint and abort
        cleanly).

        Cached per-instance for the lifetime of the run — a connector that
        runs current-state then backfill in the same process gets one
        discovery call total per entity, not two.
        """
        cached = self._discovered_properties.get(hubspot_path)
        if cached is not None:
            return cached

        try:
            resp = self._http.get(f"/crm/v3/properties/{hubspot_path}")
        except HTTPError as exc:
            if exc.status in {401, 403}:
                self._unavailable_entities.add(hubspot_path)
            fallback = _FALLBACK_PROPERTIES.get(hubspot_path, ())
            self._discovered_properties[hubspot_path] = fallback
            return fallback

        props = resp.get("results", [])
        names: list[str] = []
        for p in props:
            if not isinstance(p, dict):
                continue
            if p.get("calculated"):
                continue
            name = p.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        if not names:
            names = list(_FALLBACK_PROPERTIES.get(hubspot_path, ()))
        result = tuple(sorted(set(names)))
        self._discovered_properties[hubspot_path] = result
        return result

    def _stream_entity(
        self,
        *,
        hubspot_path: str,
        record_type: str,
        last_key: datetime | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        """Paginate one entity type and emit current-state records with
        the FULL discovered property set per record.

        Two-pass flow (scope 9c3d1393):
          1. GET /crm/v3/objects/{type}?limit=100  — returns IDs + a
             minimal default property set per page, cursor-paginated.
          2. POST /crm/v3/objects/{type}/batch/read  — body carries up
             to 100 IDs + the FULL discovered property list, returns
             every property for every record. Avoids URL-length cap
             that GET hits at ~250 properties.

        Historical backfill is a separate method per D-159 redesign.
        """
        properties = self._discover_properties(hubspot_path)
        page_size = min(batch_size, 100)  # HubSpot caps at 100
        after: str | None = None

        while True:
            list_params: dict[str, str | int] = {"limit": page_size}
            if after:
                list_params["after"] = after
            page = self._http.get(
                f"/crm/v3/objects/{hubspot_path}", params=list_params
            )
            id_results = page.get("results", [])
            ids: list[str] = [
                str(r.get("id"))
                for r in id_results
                if isinstance(r, dict) and r.get("id") is not None
            ]
            if ids:
                # Batch-read full properties for this page of IDs.
                batch_resp = self._http.post(
                    f"/crm/v3/objects/{hubspot_path}/batch/read",
                    json_body={
                        "inputs": [{"id": i} for i in ids],
                        "properties": list(properties),
                    },
                )
                for record in batch_resp.get("results", []):
                    rec_dict = self._to_record(record, record_type)
                    incremental_key_value = self._record_incremental_key(rec_dict)
                    if last_key and incremental_key_value <= last_key:
                        continue
                    yield rec_dict

            paging = page.get("paging", {})
            after = (
                paging.get("next", {}).get("after")
                if isinstance(paging, dict) else None
            )
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

    def stream_engagements(
        self,
        kinds: tuple[tuple[str, str], ...] | None = None,
        batch_size: int = 100,
    ) -> Iterator[dict[str, object]]:
        """Stream HubSpot Engagement objects (PM scope 9952dd26).

        Iterates per (hubspot_path, mapper_record_type) — typically notes,
        meetings, tasks. Calls and emails currently disabled by default
        (0 records on Wayward / token scope restrictions) but routable
        if added to ``kinds`` here.

        Two-pass like _stream_entity (list IDs → batch read with full
        properties + associations). Yields one record dict per engagement
        with associations flattened into ``__cip_assoc_<type>__`` arrays
        that the mapper extracts into the cip_engagements association
        columns.
        """
        if not self._authenticated:
            self.authenticate()

        for hubspot_path, record_type in (kinds or _ENGAGEMENT_TYPES):
            if hubspot_path in self._unavailable_entities:
                continue
            try:
                yield from self._stream_engagement_entity(
                    hubspot_path=hubspot_path,
                    record_type=record_type,
                    batch_size=batch_size,
                )
            except HTTPError as exc:
                if exc.status in {401, 403}:
                    self._unavailable_entities.add(hubspot_path)
                    continue
                raise

    def _stream_engagement_entity(
        self,
        *,
        hubspot_path: str,
        record_type: str,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        """Two-pass stream for a single engagement entity type."""
        properties = self._discover_properties(hubspot_path)
        page_size = min(batch_size, 100)
        after: str | None = None
        assoc_param = ",".join(_ENGAGEMENT_ASSOCIATIONS)

        while True:
            list_params: dict[str, str | int] = {"limit": page_size}
            if after:
                list_params["after"] = after
            page = self._http.get(
                f"/crm/v3/objects/{hubspot_path}", params=list_params
            )
            id_results = page.get("results", [])
            ids: list[str] = [
                str(r.get("id"))
                for r in id_results
                if isinstance(r, dict) and r.get("id") is not None
            ]
            if ids:
                # Batch-read for properties. HubSpot's batch/read silently
                # IGNORES the `associations` parameter (verified 2026-05-17
                # against Wayward portal — returns 200 with empty associations
                # for every record). So we do a separate v4 batch-associations
                # call per (from_type, to_type) pair, then merge.
                batch_resp = self._http.post(
                    f"/crm/v3/objects/{hubspot_path}/batch/read",
                    json_body={
                        "inputs": [{"id": i} for i in ids],
                        "properties": list(properties),
                    },
                )
                # Fetch associations for this page (4 calls — one per target type)
                assoc_by_id = self._fetch_associations_batch(
                    hubspot_path, ids
                )
                for record in batch_resp.get("results", []):
                    rec_id = str(record.get("id", ""))
                    record["associations"] = assoc_by_id.get(rec_id, {})
                    yield self._engagement_to_record(record, record_type)

            paging = page.get("paging", {})
            after = (
                paging.get("next", {}).get("after")
                if isinstance(paging, dict) else None
            )
            if not after:
                return

    def _fetch_associations_batch(
        self, from_path: str, from_ids: list[str]
    ) -> dict[str, dict[str, dict]]:
        """Fetch associations for a batch of engagement IDs.

        Returns ``{from_id: {target_plural: {results: [{id: ...}, ...]}}}``,
        mirroring HubSpot's single-object response shape so
        ``_engagement_to_record`` can consume it uniformly.

        Uses v4 batch-associations endpoint (one HTTP call per target
        type, so 4 calls per page to fetch contacts + companies + deals
        + tickets). Calls and errors per target type are non-fatal —
        if one target type fails, the others still merge.
        """
        assert self._http is not None
        result: dict[str, dict[str, dict]] = {fid: {} for fid in from_ids}
        if not from_ids:
            return result
        body = {"inputs": [{"id": i} for i in from_ids]}
        for target in _ENGAGEMENT_ASSOCIATIONS:
            try:
                resp = self._http.post(
                    f"/crm/v4/associations/{from_path}/{target}/batch/read",
                    json_body=body,
                )
            except HTTPError:
                # Per-target isolation: missing scope on one target type
                # shouldn't kill the page. Silently skip — the column
                # remains an empty array on the resulting record.
                continue
            for row in resp.get("results", []):
                from_obj = row.get("from") or {}
                from_id = str(from_obj.get("id", ""))
                if not from_id or from_id not in result:
                    continue
                to_list = row.get("to") or []
                # v4 shape: to_list items have "toObjectId" + "associationTypes"
                # Normalize to v3-style {id: ...} for _engagement_to_record
                normalized = [
                    {"id": str(t.get("toObjectId"))}
                    for t in to_list
                    if isinstance(t, dict) and t.get("toObjectId") is not None
                ]
                result[from_id][target] = {"results": normalized}
        return result

    # ── Tier 2: HubSpot Files ─────────────────────────────────────────
    def stream_files(self, *, batch_size: int = 100) -> Iterator[dict[str, Any]]:
        """Stream HubSpot Files API records.

        Per PM scope ee5b7e72 (Tier 2). Returns metadata + URL; binary
        staging to R2 is the separate Layer 3 capability (scope
        134e6f28). Each record is a flat dict ready to map into cip_files
        (with r2_path=NULL for v1).
        """
        if not self._authenticated:
            self.authenticate()
        after: str | None = None
        page_size = min(batch_size, 100)
        while True:
            params: dict[str, str | int] = {"limit": page_size}
            if after:
                params["after"] = after
            try:
                page = self._http.get("/files/v3/files", params=params)
            except HTTPError as exc:
                # 401/403/404/405 → no access OR endpoint not exposed
                # for this portal. Graceful no-op so Tier 2 capability
                # is silent for tenants that can't reach the Files API.
                if exc.status in {401, 403, 404, 405}:
                    return
                raise
            for f in page.get("results", []):
                yield self._file_to_record(f)
            paging = page.get("paging", {})
            after = (
                paging.get("next", {}).get("after")
                if isinstance(paging, dict) else None
            )
            if not after:
                return

    def _file_to_record(self, f: dict[str, Any]) -> dict[str, object]:
        """Flatten a HubSpot file into cip_files-ready record dict."""
        return {
            "__cip_kind__": "file",
            "id": str(f.get("id", "")),
            "source_id": str(f.get("id", "")),
            "filename": f.get("name"),
            "mime_type": f.get("type"),
            "size_bytes": f.get("size"),
            "url": f.get("url"),
            "path": f.get("path"),
            "extension": f.get("extension"),
            "archived": f.get("archived"),
            "is_usable_in_content": f.get("isUsableInContent"),
            "created_at": f.get("createdAt"),
            "updated_at": f.get("updatedAt"),
        }

    # ── Tier 2: HubSpot Marketing Emails ──────────────────────────────
    def stream_marketing_emails(
        self, *, batch_size: int = 100
    ) -> Iterator[dict[str, Any]]:
        """Stream HubSpot Marketing Emails (campaign-level).

        Per PM scope 510fff61. Endpoint /marketing/v3/emails (CMS-side).
        Distinct from engagement_type='email' (1:1 transactional).
        """
        if not self._authenticated:
            self.authenticate()
        after: str | None = None
        page_size = min(batch_size, 100)
        while True:
            params: dict[str, str | int] = {"limit": page_size}
            if after:
                params["after"] = after
            try:
                page = self._http.get("/marketing/v3/emails", params=params)
            except HTTPError as exc:
                if exc.status in {401, 403}:
                    return
                raise
            for e in page.get("results", []):
                yield {
                    "__cip_kind__": "marketing_email",
                    "id": str(e.get("id", "")),
                    "source_id": str(e.get("id", "")),
                    "name": e.get("name"),
                    "subject": e.get("subject"),
                    "email_type": e.get("type"),
                    "state": e.get("state"),
                    "published_at": e.get("publishedAt"),
                    "from_name": e.get("from", {}).get("fromName") if isinstance(e.get("from"), dict) else None,
                    "from_email": e.get("from", {}).get("email") if isinstance(e.get("from"), dict) else None,
                    "stats": e.get("stats") or {},
                    "raw": e,  # vendor extras for properties JSONB
                }
            paging = page.get("paging", {})
            after = (
                paging.get("next", {}).get("after")
                if isinstance(paging, dict) else None
            )
            if not after:
                return

    # ── Tier 2: HubSpot Contact Lists ─────────────────────────────────
    def stream_contact_lists(self) -> Iterator[dict[str, Any]]:
        """Stream HubSpot Contact Lists (segmentation).

        Per PM scope 510fff61. Uses legacy /contacts/v1/lists endpoint
        (v3 lists API requires different scopes and shape).
        """
        if not self._authenticated:
            self.authenticate()
        offset = 0
        page_size = 250
        while True:
            try:
                page = self._http.get(
                    "/contacts/v1/lists",
                    params={"count": page_size, "offset": offset},
                )
            except HTTPError as exc:
                if exc.status in {401, 403}:
                    return
                raise
            for lst in page.get("lists", []):
                yield {
                    "__cip_kind__": "contact_list",
                    "id": str(lst.get("listId", "")),
                    "source_id": str(lst.get("listId", "")),
                    "name": lst.get("name"),
                    "list_type": "dynamic" if lst.get("dynamic") else "static",
                    "processing_type": lst.get("processingType"),
                    "member_count": lst.get("metaData", {}).get("size") if isinstance(lst.get("metaData"), dict) else None,
                    "filters": lst.get("filters") or {},
                    "raw": lst,
                }
            if not page.get("has-more"):
                return
            offset = page.get("offset", offset + page_size)

    def _engagement_to_record(
        self, hubspot_obj: dict[str, Any], record_type: str
    ) -> dict[str, object]:
        """Flatten engagement obj + associations into a mapper-consumable dict.

        Associations come back from HubSpot in a `associations.<type>.results`
        shape; flatten each to ``__cip_assoc_<singular_type>__`` arrays of
        source_ids that the mapper routes to the right cip_engagements
        association column.
        """
        props = hubspot_obj.get("properties", {}) or {}
        associations = hubspot_obj.get("associations", {}) or {}
        rec: dict[str, object] = {
            "__cip_kind__": record_type,
            "id": str(hubspot_obj.get("id", "")),
            "source_id": str(hubspot_obj.get("id", "")),
            **{k: v for k, v in props.items() if v is not None},
            "updated_at": (
                props.get("hs_lastmodifieddate")
                or props.get("hs_createdate")
                or hubspot_obj.get("updatedAt")
            ),
        }
        # Singularize and attach association source_ids. Use an explicit
        # mapping rather than rstrip("s") — "companies".rstrip("s") yields
        # "companie", not "company" (rstrip strips the trailing chars one
        # at a time but doesn't apply English singularization rules).
        for plural in _ENGAGEMENT_ASSOCIATIONS:
            block = associations.get(plural)
            if not isinstance(block, dict):
                continue
            results = block.get("results") or []
            ids = [
                str(r.get("id"))
                for r in results
                if isinstance(r, dict) and r.get("id") is not None
            ]
            singular = _ASSOC_SINGULAR.get(plural, plural.rstrip("s"))
            rec[f"__cip_assoc_{singular}__"] = ids
        return rec

    def backfill_history(
        self, tenant_id: UUID
    ) -> Iterator[HistoricalRecord]:
        """D-159 historical backfill via HubSpot Property History API.

        Re-paginates every entity type (companies/contacts/deals/tickets),
        requesting ``propertiesWithHistory=<csv-of-default-props>`` per
        page. For each record, flattens property revisions across all
        tracked properties, groups by timestamp into snapshots (HubSpot
        often writes multiple property changes within the same operator
        action sharing a timestamp), and yields one ``HistoricalRecord``
        per snapshot oldest → newest.

        Caller responsibility: run ``run_sync()`` first to materialize
        current state. The persister looks up the current row's ``id``
        for the history-table ``record_id`` FK; missing current rows
        are skipped (counted by the orchestrator, not fatal).
        """
        if not self._authenticated:
            self.authenticate()

        for hubspot_path, record_type in _OBJECT_TYPES:
            if hubspot_path in self._unavailable_entities:
                continue
            try:
                yield from self._backfill_entity(hubspot_path, record_type)
            except HTTPError as exc:
                # Per-entity isolation (scope d3311846): 403/401 on one
                # entity (e.g., Wayward token lacks tickets scope) marks
                # entity unavailable and continues; doesn't kill backfill.
                if exc.status in {401, 403}:
                    self._unavailable_entities.add(hubspot_path)
                    continue
                raise

    def _backfill_entity(
        self, hubspot_path: str, record_type: str
    ) -> Iterator[HistoricalRecord]:
        """Stream historical revisions for one entity type with the FULL
        discovered property set.

        Two-pass flow (post-2026-05-15 fix):
          1. GET /crm/v3/objects/{type}?limit=50 — returns 50 IDs +
             pagination cursor. NO ``properties`` or ``propertiesWithHistory``
             on this call; just the page of IDs.
          2. POST /crm/v3/objects/{type}/batch/read — body carries the 50
             IDs PLUS the full ``propertiesWithHistory`` array. Returns
             history for every property of every record.

        Why POST instead of GET: with ~300-450 properties per entity
        (Wayward portal — discovered 2026-05-15), the GET URL hit HTTP
        414 Request-URI Too Large on the contacts endpoint (~443 props
        × ~30 chars × 2 [properties + propertiesWithHistory] = ~26KB URL).
        POST puts the property list in the JSON body, no URL limit.

        50-record limit still applies (HubSpot's documented
        ``propertiesWithHistory`` cap), enforced via ``inputs`` size.
        """
        target_table = _CIP_TABLE_BY_TYPE[record_type]
        properties = self._discover_properties(hubspot_path)
        properties_list = list(properties)
        after: str | None = None
        while True:
            list_params: dict[str, str | int] = {"limit": 50}
            if after:
                list_params["after"] = after
            id_page = self._http.get(
                f"/crm/v3/objects/{hubspot_path}", params=list_params
            )
            id_results = id_page.get("results", [])
            ids: list[str] = [
                str(r.get("id"))
                for r in id_results
                if isinstance(r, dict) and r.get("id") is not None
            ]
            if ids:
                batch_resp = self._http.post(
                    f"/crm/v3/objects/{hubspot_path}/batch/read",
                    json_body={
                        "inputs": [{"id": i} for i in ids],
                        "properties": properties_list,
                        "propertiesWithHistory": properties_list,
                    },
                )
                for obj in batch_resp.get("results", []):
                    yield from self._historical_records_for_obj(
                        obj, record_type, target_table
                    )
            paging = id_page.get("paging", {})
            if isinstance(paging, dict):
                nxt = paging.get("next", {})
                after = nxt.get("after") if isinstance(nxt, dict) else None
            else:
                after = None
            if not after:
                break

    def _historical_records_for_obj(
        self, hubspot_obj: dict[str, Any], record_type: str, target_table: str
    ) -> Iterator[HistoricalRecord]:
        """For one HubSpot object, yield HistoricalRecord per snapshot
        across all tracked properties (oldest → newest).

        Bug history (2026-05-15): two adjacent HubSpot timestamps for the
        same instant can serialize with different millisecond precision
        ("2025-07-15T18:03:26.491Z" and "2025-07-15T18:03:26Z" both
        appearing in the same property-history stream for the same record).
        The previous implementation sorted these as RAW STRINGS — ASCII
        ordering puts "." (0x2E) before "Z" (0x5A), so the higher-precision
        string sorted BEFORE the lower-precision one even though they
        represent the same logical instant (or the .491 is later). After
        sort, valid_from = parsed(".491Z") and valid_to = parsed("Z")
        produced ``valid_from > valid_to`` → ``ck_*_history_valid_range``
        violation, which poisoned the persister transaction and killed
        the rest of the batch. Fixed by parsing all timestamps to
        ``datetime`` FIRST, then grouping snapshots by parsed datetime
        (semantic equivalence, not string), then sorting datetime objects,
        then defensively skipping any snapshot where ``valid_from >=
        valid_to`` (constraint requires strict greater-than).
        """
        history = hubspot_obj.get("propertiesWithHistory", {}) or {}
        if not isinstance(history, dict):
            return

        # Parse every (timestamp, property, value) tuple to typed
        # datetime FIRST. Skip un-parseable timestamps rather than crash.
        revisions: list[tuple[datetime, str, str, Any]] = []
        for prop_name, prop_history in history.items():
            if not isinstance(prop_history, list):
                continue
            for rev in prop_history:
                ts_raw = rev.get("timestamp")
                if not isinstance(ts_raw, str):
                    continue
                try:
                    ts_dt = _parse_hubspot_ts(ts_raw)
                except Exception:  # noqa: BLE001
                    continue
                revisions.append((ts_dt, ts_raw, prop_name, rev.get("value")))
        if not revisions:
            return

        # Group by PARSED datetime (semantic equivalence) — not raw
        # string. Multiple property changes at the same logical instant
        # collapse into a single snapshot regardless of string format.
        snapshots: dict[datetime, dict[str, Any]] = {}
        ts_string_for_dt: dict[datetime, str] = {}
        for ts_dt, ts_raw, prop, value in revisions:
            snapshots.setdefault(ts_dt, {})[prop] = value
            # Remember the original string for change_reason audit trail
            # (first one wins; deterministic given input order).
            ts_string_for_dt.setdefault(ts_dt, ts_raw)

        dts_sorted = sorted(snapshots.keys())
        source_id = str(hubspot_obj.get("id", ""))
        if not source_id:
            return

        domain_keys = _HUBSPOT_DOMAIN_FIELDS_FOR_HISTORY.get(record_type, set())
        translation = _HUBSPOT_RECORD_TO_SQL_FOR_HISTORY.get(record_type, {})

        for idx, valid_from in enumerate(dts_sorted):
            snap_props = snapshots[valid_from]
            valid_to = (
                dts_sorted[idx + 1] if idx + 1 < len(dts_sorted) else None
            )

            # Defensive: ck_*_history_valid_range requires
            # ``valid_to IS NULL OR valid_to > valid_from`` (strict >).
            # If parsing produced equal datetimes that somehow weren't
            # grouped, or if HubSpot ever returns out-of-order timestamps,
            # skip rather than violate the constraint and poison the txn.
            if valid_to is not None and valid_to <= valid_from:
                continue

            fields: dict[str, object] = {}
            overflow: dict[str, object] = {}
            for k, v in snap_props.items():
                if v is None:
                    continue
                sql_col = translation.get(k, k)
                if sql_col in domain_keys or k in domain_keys:
                    fields[sql_col] = v
                else:
                    overflow[k] = v

            # cip_companies / cip_tickets need non-null name/subject —
            # if the snapshot didn't include them, skip the snapshot
            # (mid-history with no name change → name unchanged but we
            # can't reconstruct without lookup; we just skip the
            # incomplete snapshot to avoid NULL violations).
            if record_type == "company" and "name" not in fields:
                continue
            if record_type == "ticket" and "subject" not in fields:
                continue

            yield HistoricalRecord(
                target_table=target_table,
                source_id=source_id,
                valid_from=valid_from,
                valid_to=valid_to,
                fields=fields,
                overflow=overflow,
                changed_by=self.connector_id,
                change_reason=(
                    f"hubspot-property-history-snapshot"
                    f"[{ts_string_for_dt[valid_from]}]"
                ),
            )

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




# ── Backfill helpers (D-159) ──────────────────────────────────────────────


def _parse_hubspot_ts(ts: str) -> datetime:
    """HubSpot property-history timestamps come as either ISO-8601 with
    'Z' suffix OR epoch-millis strings. Return tz-aware UTC datetime."""
    if ts.endswith("Z"):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if ts.isdigit():
        return datetime.fromtimestamp(int(ts) / 1000, UTC)
    return datetime.fromisoformat(ts)


# Backfill-side domain field + translation tables are SOURCED FROM the
# mapper. Duplicating them here caused a real bug (2026-05-14): the
# connector's table had stale ``job_title``/``jobtitle`` mappings even
# after the mapper was fixed for current-state. Mapping the connector
# table to point at the mapper's table eliminates the class of bug.
from .mapper import (  # noqa: E402
    _DOMAIN_FIELDS_BY_TYPE as _HUBSPOT_DOMAIN_FIELDS_FOR_HISTORY,
)
from .mapper import (  # noqa: E402
    _RECORD_TO_SQL_COLUMN as _HUBSPOT_RECORD_TO_SQL_FOR_HISTORY,
)
