# foundry: kind=service domain=client-intelligence-platform touches=integration
"""LensMirror mappers — per-entity translation from source lens rows to CIPRows.

Each mapper consumes one row from the corresponding source lens view
(e.g., `lens_china_clients` for deals, `lens_china_companies` for
companies, `lens_china_contacts` for contacts) and produces a single
`CIPRow` targeting the destination tenant's `cip_*` table.

Atlas-locked design notes:

- **Mapper output NEVER includes `companion_data`** (Atlas Q1 enforcement
  on the writer side — paired with cip_25's role-grant on the reader
  side). Because companion_data is not in `mapper.fields` and not the
  configured extras column, the persister never writes it. PS's
  pre-existing companion edits survive every re-mirror automatically.

- **Mapper output NEVER includes `initial_intake_route`** (Atlas C-2 —
  the persister overwrites all domain_cols on UPDATE, which would fight
  the insert-only semantics. The orchestrator backfills NULL values
  post-sync instead).

- **`source_connector` is rewritten to `'lens-mirror'`** so the
  destination tenant's provenance is explicit (PS knows its data came
  from a lens-mirror, not from a direct HubSpot connect).

- **`client_id` is resolved via a Pass-1 lookup table** (Atlas C-1
  two-pass orchestration). The lookup maps HubSpot upstream company_id
  → PS client_id. Mappers are constructed with the lookup pre-built;
  rows whose lookup key resolves to None are SKIPPED (yield nothing) —
  the orchestrator counts these and logs.

- **Identity-shape transformation otherwise** — lens views project
  `SELECT t.*` from their underlying `cip_*` table, so column names
  already match the destination schema. No HubSpot-property-name
  translation needed.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Literal
from uuid import UUID

from cip.integration_mesh.base import CIPMapperBase, CIPRow, KnowledgeText

# Columns we strip from every source row before producing the
# destination row. These are either orchestrator-finalized (tenant_id,
# ingestion_batch_id, *_at), persister-owned (id, previous_version_id),
# destination-private (companion_data, initial_intake_route — Atlas),
# or formally DEPRECATED per CIP-FW-004 (the soft-FK UUID columns).
_STRIP_COLS = frozenset({
    "id",  # destination persister assigns
    "tenant_id",  # orchestrator finalizes
    "client_id",  # mapper resolves via Pass-1 lookup
    "source_connector",  # mapper rewrites to 'lens-mirror'
    "ingested_at",
    "refreshed_at",
    "previous_version_id",
    "ingestion_batch_id",
    "created_at",
    "updated_at",
    "authority",  # mapper sets explicitly
    "companion_data",  # PS-owned — mirror cannot write (Atlas Q1)
    "initial_intake_route",  # post-sync backfill only (Atlas C-2)
    # Deprecated soft-FK columns per CIP-FW-004 — never propagate
    # through the mirror. Associations live in `properties` JSONB.
    "company_id",
    "contact_id",
    "requester_id",
    # debug-only fields injected by LensMirrorConnector.stream_records
    "_source_tenant_id",
    "_source_lens",
})

# Per-entity domain columns. These mirror the cip_* table's typed
# columns (the lens view's `SELECT t.*` exposes all of them). Anything
# not in this set + not in _STRIP_COLS routes to overflow.
# Per CIP-FW-004 (Association Contract, 2026-05-22): the deprecated
# soft-FK UUID columns (cip_deals.company_id, cip_deals.contact_id,
# cip_contacts.company_id) are NOT in any mapper's domain set. They're
# vestigial schema (kept for backward-compat; COMMENT-deprecated in
# cip_27). Cross-entity association data lives in `properties` JSONB —
# the mapper preserves it there via the overflow-merge logic below.
_DOMAIN_FIELDS_BY_ENTITY: dict[str, set[str]] = {
    "company": {
        "name", "domain", "industry", "city", "country",
        "employee_count", "annual_revenue", "region",
    },
    "contact": {
        "first_name", "last_name", "email", "phone",
        "title", "country", "city", "lifecycle_stage",
        "company_name",
    },
    "deal": {
        "name", "amount", "stage", "pipeline", "close_date",
        "currency", "probability",
    },
}

# Overflow column on each destination table (matches
# persister.EXTRAS_COLUMN_BY_TABLE).
_OVERFLOW_COL_BY_TARGET = {
    "cip_companies": "properties",
    "cip_contacts": "properties",
    "cip_deals": "properties",
    "cip_clients": "metadata",  # cip_clients uses 'metadata' not 'properties'
}


class _LensMirrorMapperBase(CIPMapperBase):
    """Shared logic: strip orchestrator-owned cols, split domain vs
    overflow, attach resolved client_id, rewrite source_connector."""

    # Subclasses set these:
    object_type: str = ""
    target_table: str = ""
    entity_kind: str = ""  # one of "company", "contact", "deal"

    def __init__(
        self,
        *,
        client_id_lookup: dict[str, UUID],
        lookup_key_extractor: Callable[[dict[str, object]], str | None] | None = None,
    ) -> None:
        """
        Args:
            client_id_lookup: maps upstream company_id (HubSpot id, as
                string) → PS client_id (UUID). Built by Pass 1 of the
                orchestrator.
            lookup_key_extractor: callable(record) → str | None that
                returns the HubSpot company_id for this record. If None,
                the per-entity default is used.
        """
        self._lookup = client_id_lookup
        self._lookup_key = lookup_key_extractor or self._default_lookup_key

    def _default_lookup_key(self, record: dict[str, object]) -> str | None:
        """Subclasses override. The default returns None which means
        the row is unattributable → skip."""
        return None

    def map(self, record: dict[str, object]) -> Iterable[CIPRow]:
        # Resolve destination client_id via Pass-1 lookup.
        lookup_key = self._lookup_key(record)
        if not lookup_key:
            return  # unresolvable → skip
        client_uuid = self._lookup.get(str(lookup_key))
        if client_uuid is None:
            return  # not a china-subset record → skip

        source_id = record.get("source_id")
        if not source_id:
            return
        source_id_str = str(source_id)

        domain = _DOMAIN_FIELDS_BY_ENTITY.get(self.entity_kind, set())
        fields: dict[str, object] = {}
        # Start overflow from the source's existing properties/metadata
        # JSONB payload (so HubSpot's full property set carries over).
        # Lens views project the underlying table's columns directly,
        # so the original JSONB column name (`properties` for
        # company/contact/deal, `metadata` for client) is present.
        src_overflow_col = (
            "metadata" if self.target_table == "cip_clients" else "properties"
        )
        existing_overflow = record.get(src_overflow_col) or {}
        overflow: dict[str, object] = (
            dict(existing_overflow) if isinstance(existing_overflow, dict) else {}
        )
        for col, val in record.items():
            if col in _STRIP_COLS:
                continue
            if col == src_overflow_col:
                continue  # already absorbed above
            if col == "source_id":
                continue  # CIPRow.source_id is set separately
            if col in domain:
                fields[col] = val
            else:
                # Non-domain typed column on the source → goes to overflow
                # under its column name as a key. Drops nothing.
                if val is not None:
                    overflow[col] = val

        yield CIPRow(
            target_table=self.target_table,
            source_id=source_id_str,
            fields=fields,
            overflow=overflow,
            client_id=client_uuid,
            authority="ingested",
        )

    def overflow_fields(self) -> list[str]:
        # All non-domain non-stripped fields go to the configured overflow
        # column. We can't enumerate them at class-definition time
        # because lens view columns are dynamic — declare the policy
        # rather than a fixed list.
        return []

    def authority(self) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"

    def ingest_as_knowledge(self, record: dict[str, object]) -> list[KnowledgeText]:
        return []  # mirror does NOT re-ingest content into the knowledge layer
        # (Atlas C-4: PS knowledge-layer mirror is out of 2.6 scope)


class LensMirrorDealMapper(_LensMirrorMapperBase):
    """Maps `lens_china_clients` rows (which is the deal lens) → `cip_deals`.

    Lookup key for client_id resolution: the deal's
    `properties->>'hs_primary_associated_company'`. The Pass 1 lookup
    was built by scanning the same field across China-Referral deals.
    """

    object_type: str = "lens-mirror-deal"
    target_table: str = "cip_deals"
    entity_kind: str = "deal"

    def _default_lookup_key(self, record: dict[str, object]) -> str | None:
        props = record.get("properties") or {}
        if isinstance(props, dict):
            v = props.get("hs_primary_associated_company")
            return str(v) if v else None
        return None


class LensMirrorCompanyMapper(_LensMirrorMapperBase):
    """Maps `lens_china_companies` rows → `cip_companies`.

    Lookup key: the company's own `source_id` (HubSpot company id).
    """

    object_type: str = "lens-mirror-company"
    target_table: str = "cip_companies"
    entity_kind: str = "company"

    def _default_lookup_key(self, record: dict[str, object]) -> str | None:
        v = record.get("source_id")
        return str(v) if v else None


class LensMirrorContactMapper(_LensMirrorMapperBase):
    """Maps `lens_china_contacts` rows → `cip_contacts`.

    Lookup key: the contact's `properties->>'associatedcompanyid'`.
    Verified prod join 2026-05-22.
    """

    object_type: str = "lens-mirror-contact"
    target_table: str = "cip_contacts"
    entity_kind: str = "contact"

    def _default_lookup_key(self, record: dict[str, object]) -> str | None:
        props = record.get("properties") or {}
        if isinstance(props, dict):
            v = props.get("associatedcompanyid")
            return str(v) if v else None
        return None
