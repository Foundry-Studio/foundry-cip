# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Canonical join helper for the CIP association contract (CIP-FW-004).

Per the Association Contract Atlas review (2026-05-22, CIP-FW-004):
CIP cross-entity associations join on `source_id` within
`(tenant_id, source_connector)`. The association key lives in the
source entity's `properties` JSONB column under the source-system's
native key (e.g., `hs_primary_associated_company` on HubSpot deals,
`associatedcompanyid` on HubSpot contacts).

This module is THE canonical place to compose those joins, so future
lens views + ad-hoc queries don't reinvent the JSONB-extraction pattern
(which is how cip_24's correlated-subquery perf bug crept in — the
correct uncorrelated pattern is harder to spot when each lens hand-rolls
its own join). Two surfaces:

  - `ASSOC_KEYS` — registry of known JSONB association keys per
    (source_connector, source_entity, target_entity)
  - `assoc_join_sql(...)` — returns a SQL fragment for the uncorrelated
    join, parameterized by tenant scoping

Lens authors call `assoc_join_sql(...)` in their `CREATE VIEW` bodies.

References:
  - docs/vision/ATLAS-REVIEW-ASSOCIATION-CONTRACT.md (CIP-FW-004)
  - docs/CONNECTOR-AUTHORING-GUIDE.md §Associations
  - cip/migrations/versions/cip_27_association_contract.py — schema
    deprecation + expression indexes that make these joins index-backed
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssocKey:
    """One association — the JSONB key on the source entity that
    references the target entity's `source_id`."""
    source_connector: str
    source_entity: str  # e.g., "deal", "contact", "ticket"
    target_entity: str  # e.g., "company", "contact"
    json_key: str       # the JSONB key in source.properties
    notes: str = ""


# Known association keys. Extend as new connectors land. The
# schema-drift test (`tests/integration_mesh/test_mapper_schema_drift.py`)
# asserts every entry here corresponds to a JSONB key actually emitted
# by the relevant connector.
ASSOC_KEYS: tuple[AssocKey, ...] = (
    # HubSpot — deal associations
    AssocKey(
        source_connector="hubspot-v1",
        source_entity="deal",
        target_entity="company",
        json_key="hs_primary_associated_company",
        notes="Primary associated company (1:1). HubSpot also supports "
              "M:N via associations API; only the primary is indexed here.",
    ),
    # HubSpot — contact associations
    AssocKey(
        source_connector="hubspot-v1",
        source_entity="contact",
        target_entity="company",
        json_key="associatedcompanyid",
        notes="HubSpot's primary-associated-company on contacts.",
    ),
    # Zendesk — ticket associations
    AssocKey(
        source_connector="zendesk-v1",
        source_entity="ticket",
        target_entity="zendesk_user",
        json_key="requester_id",
        notes="Zendesk user_id (numeric in source; stringified in JSONB). "
              "Cross-connector resolution to cip_contacts goes through "
              "cip_identity_links (separate Atlas-gated scope).",
    ),
)


def get_assoc_key(
    *,
    source_connector: str,
    source_entity: str,
    target_entity: str,
) -> AssocKey:
    """Look up the registered association key. Raises KeyError if not
    registered — agents should ADD to ASSOC_KEYS rather than inline a
    string literal in a lens view."""
    for k in ASSOC_KEYS:
        if (
            k.source_connector == source_connector
            and k.source_entity == source_entity
            and k.target_entity == target_entity
        ):
            return k
    raise KeyError(
        f"No registered association key for "
        f"{source_connector}.{source_entity} -> {target_entity}. "
        f"Add an entry to ASSOC_KEYS in lens_engine/joins.py rather "
        f"than inlining a JSONB key in your lens view."
    )


def assoc_join_sql(
    *,
    source_table: str,       # e.g., "cip_deals d"
    target_table: str,       # e.g., "cip_companies c"
    source_alias: str,       # e.g., "d"
    target_alias: str,       # e.g., "c"
    json_key: str,           # the JSONB key on source.properties
    tenant_guc: bool = True, # filter by app.current_tenant GUC
) -> str:
    """Return a SQL fragment expressing the canonical association join.

    The shape is INTENTIONALLY UNCORRELATED — the inner SELECT uses the
    GUC directly rather than referencing the outer row's tenant_id.
    This lets Postgres hash-join the inner set once instead of
    re-executing per outer row (cip_24's correlated-subquery rewrite
    benchmarked at 0.12s vs 60s+ for the correlated variant).

    Example::

        # In a lens view body:
        from cip.integration_mesh.lens_engine.joins import (
            get_assoc_key, assoc_join_sql,
        )

        ak = get_assoc_key(
            source_connector="hubspot-v1",
            source_entity="contact",
            target_entity="company",
        )
        body = f'''
            SELECT ct.*
            FROM cip_contacts ct
            WHERE {assoc_join_sql(
                source_table="cip_contacts ct",  # already in FROM
                target_table="cip_companies",
                source_alias="ct",
                target_alias="c",
                json_key=ak.json_key,
            )}
        '''

    For lens views, callers typically embed the IN-clause directly
    rather than calling this helper at runtime — but using this
    function in a Python lens-generator keeps the join shape uniform.
    """
    guc_clause = (
        "WHERE c.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid AND "
        if tenant_guc else "WHERE "
    )
    # The canonical uncorrelated shape: outer references source's
    # tenant_id (via GUC), inner subquery does the same independently.
    return (
        f"{source_alias}.source_id IN ("
        f"SELECT DISTINCT {target_alias}.properties->>'{json_key}' "
        f"FROM {source_table.split()[0]} {target_alias} "
        f"{guc_clause}"
        f"{target_alias}.properties->>'{json_key}' IS NOT NULL"
        f")"
    )


def assert_no_uuid_fk_join(sql: str) -> None:
    """Lint helper for lens authors: raise if the SQL appears to join on
    one of the deprecated CIP-UUID soft-FK columns
    (`cip_deals.company_id`, etc.).

    Not a perfect grep — won't catch SELECT t.company_id — but catches
    the common `JOIN ... ON ... .company_id = ... .id` pattern that
    lens authors might write out of habit.
    """
    import re as _re
    deprecated_patterns = [
        r"cip_deals\.company_id\s*=",
        r"cip_deals\.contact_id\s*=",
        r"cip_contacts\.company_id\s*=",
        r"cip_tickets\.requester_id\s*=",
        # Also catch the reverse direction
        r"=\s*cip_deals\.company_id\b",
        r"=\s*cip_deals\.contact_id\b",
        r"=\s*cip_contacts\.company_id\b",
        r"=\s*cip_tickets\.requester_id\b",
    ]
    for pat in deprecated_patterns:
        if _re.search(pat, sql, _re.IGNORECASE):
            raise ValueError(
                f"Lens SQL appears to join on a deprecated CIP-UUID soft-FK "
                f"({pat}). Per CIP-FW-004 (Association Contract, 2026-05-22), "
                f"join via source.properties->>'<source_key>' = "
                f"target.source_id instead. See "
                f"cip/integration_mesh/lens_engine/joins.py for the canonical "
                f"join shape."
            )
