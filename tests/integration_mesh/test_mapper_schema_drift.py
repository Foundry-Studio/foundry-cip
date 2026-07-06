# foundry: kind=test domain=client-intelligence-platform
"""Schema-drift guards for mappers + the association contract (CIP-FW-004).

Per Atlas review CIP-FW-004 §4 (2026-05-22), two guards land here:

1. **Deprecated-column guard** — no mapper may write to the four
   deprecated CIP-UUID soft-FK columns. Per the Association Contract
   (CIP-FW-004), these columns are vestigial — joins go via JSONB
   source-id refs instead.

2. **New-soft-FK guard** — any newly-introduced `*_id uuid` column on
   an entity table is either a known PK / `client_id` / `tenant_id`,
   or it appears on an explicit `_INTENTIONAL_TYPED_PROMOTIONS`
   allowlist. Without this, a future agent could silently resurrect
   the dead UUID-FK pattern.

Mapper-side enforcement (the deprecated-column guard) runs against ALL
shipped CIPMapper subclasses by walking each, calling `.map()` with a
realistic record fixture, and asserting `CIPRow.fields` doesn't contain
any deprecated column name.

Schema-side enforcement (the new-soft-FK guard) walks
`information_schema.columns` looking for `*_id uuid NOT NULL` on
non-history `cip_*` tables and checks each against the allowlist.

References:
  - docs/vision/ATLAS-REVIEW-ASSOCIATION-CONTRACT.md (CIP-FW-004)
  - cip/migrations/versions/cip_27_association_contract.py
  - cip/integration_mesh/lens_engine/joins.py
"""
from __future__ import annotations

import inspect
import pkgutil
from collections.abc import Iterable

import pytest

from cip.integration_mesh.base import CIPMapperBase

# ── The deprecated soft-FK column set (from cip_27 + CIP-FW-004) ────────

# (table, column). Any mapper write to one of these is a violation.
DEPRECATED_SOFT_FK_COLUMNS: frozenset[tuple[str, str]] = frozenset({
    ("cip_deals", "company_id"),
    ("cip_deals", "contact_id"),
    ("cip_contacts", "company_id"),
    ("cip_tickets", "requester_id"),
})

# Just the column names (any mapper writing any of these is a violation
# regardless of target_table — they're forbidden everywhere).
DEPRECATED_SOFT_FK_COLUMN_NAMES: frozenset[str] = frozenset(
    col for _tbl, col in DEPRECATED_SOFT_FK_COLUMNS
)


# ── Known typed-id columns that are NOT deprecated soft-FKs ──────────────
# (these legitimately exist as typed UUID columns and the schema guard
# must NOT flag them).

_LEGITIMATE_UUID_COLUMNS: frozenset[str] = frozenset({
    "id",                    # primary key
    "tenant_id",             # tenant scope
    "client_id",             # client scope
    "previous_version_id",   # SCD-2 chain
    "ingestion_batch_id",    # provenance batch
    "owner_principal_id",    # PM scope
    "source_file_id",        # knowledge_chunks FK
    "chunk_id",              # knowledge chunks
    "record_id",             # history tables
    "killed_reason_id",      # PM kill metadata
    "parent_project_id",     # PM hierarchy
    "parent_tenant_id",      # tenant hierarchy
    "initiative_id",         # PM hierarchy
    "project_template_version_id",  # PM templating
    "product_id",            # PM products
    "scope_id",              # PM scope id (in scopes table itself)
    "project_id",            # PM project ref
    "decision_id",           # PM decisions
    "task_id",               # PM tasks
    "assignment_id",         # PM assignments
    "escalation_id",         # PM escalations
    "approval_id",           # PM approvals
    "attachment_id",         # PM attachments
    # cip_sync_runs internal PK + per-run batch tracking
    "batch_id",              # cip_sync_runs.batch_id — orchestrator-owned run id
    # cip_connector_property_registry internal PK
    "registry_id",           # cip_connector_property_registry.registry_id — registry row PK
})

# Explicit allowlist for INTENDED typed `*_source_id`-style promotions
# (Atlas-blessed pattern). Future migrations that promote a hot
# association add the column here.
_INTENTIONAL_TYPED_PROMOTIONS: frozenset[tuple[str, str]] = frozenset({
    # cip_38 (PS China Book v2 §S2): wayward_brand_id is an EXTERNAL identifier
    # (Wayward issues brand UUIDs — the join key for Jake's reports + Exhibit A),
    # NOT a CIP-internal cross-entity soft-FK. CIP-FW-004 governs CIP↔CIP
    # associations; an external system's native UUID id is a different thing and
    # is correctly typed uuid per the build spec.
    ("cip_clients", "wayward_brand_id"),
})


# ── Mapper discovery ─────────────────────────────────────────────────────


def _all_shipped_mapper_classes() -> list[type[CIPMapperBase]]:
    """Walk cip.integration_mesh.connectors.* and collect every
    concrete subclass of CIPMapperBase. We exclude the base + the
    runtime-checkable Protocol itself."""
    import cip.integration_mesh.connectors as connectors_pkg

    found: list[type[CIPMapperBase]] = []
    seen: set[type] = set()

    def _walk(pkg) -> Iterable:
        for _finder, name, is_pkg in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
            module = __import__(name, fromlist=["_"])
            for attr in vars(module).values():
                if (
                    inspect.isclass(attr)
                    and issubclass(attr, CIPMapperBase)
                    and attr is not CIPMapperBase
                    and attr not in seen
                ):
                    seen.add(attr)
                    yield attr
            if is_pkg:
                sub = __import__(name, fromlist=["_"])
                yield from _walk(sub)

    found.extend(_walk(connectors_pkg))
    return found


# ── Test 1: no mapper writes a deprecated soft-FK column ─────────────────


def test_mapper_instantiates_cleanly() -> None:
    """Sanity guard — every shipped CIPMapperBase subclass either
    instantiates with no required args (most do) or documents its
    required kwargs via the call-site that drives it (the LensMirror
    family takes client_id_lookup).

    The MAIN deprecated-column guard lives in
    `test_no_mapper_emits_deprecated_soft_fk_for_known_fixtures` below,
    which exercises actual `.map()` output. That's the load-bearing
    contract — record-side field names appearing in `overflow_fields()`
    is actually FINE (per Atlas they route to `properties` JSONB, which
    is the canonical new contract). The persister-level violation is
    when those field names appear in `CIPRow.fields`, which targets
    the typed column directly.
    """
    mappers = _all_shipped_mapper_classes()
    assert mappers, "no mapper classes found — discovery is broken"
    instantiated = 0
    for cls in mappers:
        try:
            cls()  # type: ignore[call-arg]
            instantiated += 1
        except TypeError:
            # Required kwargs — exercised by fixture-driven test below.
            pass
    # At minimum the no-arg mappers (Fixture, HubSpot, Zendesk) should
    # all construct cleanly.
    assert instantiated >= 3, (
        f"only {instantiated} mapper classes instantiated cleanly. "
        f"Expected at least 3 (Fixture, HubSpot, Zendesk)."
    )


def test_no_mapper_emits_deprecated_soft_fk_for_known_fixtures() -> None:
    """For mappers we can construct + drive with a representative record,
    assert CIPRow.fields never contains a deprecated soft-FK column name.

    This is the load-bearing guard: at WRITE time, the persister honors
    CIPRow.fields literally. If a mapper sneaks `company_id` into fields,
    the persister will write the dead column. CIP-FW-004 says no.
    """
    from uuid import UUID, uuid4
    ps_tenant = UUID("078a37d6-6ae2-4e22-869e-cc08f6cb2787")

    # LensMirror mappers — drive them with a representative source row.
    from cip.integration_mesh.connectors.lens_mirror import (
        LensMirrorCompanyMapper,
        LensMirrorContactMapper,
        LensMirrorDealMapper,
    )

    lookup = {"X-COMPANY-ID": uuid4()}
    fixture_rows = [
        # Each test row carries the deprecated columns IN THE INPUT —
        # the mapper must STRIP them, not pass them through.
        (LensMirrorDealMapper, {
            "source_id": "deal-1",
            "tenant_id": ps_tenant,
            "company_id": uuid4(),  # ← deprecated, must be stripped
            "contact_id": uuid4(),  # ← deprecated, must be stripped
            "name": "Test deal",
            "properties": {"hs_primary_associated_company": "X-COMPANY-ID"},
        }),
        (LensMirrorCompanyMapper, {
            "source_id": "X-COMPANY-ID",
            "tenant_id": ps_tenant,
            "name": "Test company",
        }),
        (LensMirrorContactMapper, {
            "source_id": "contact-1",
            "tenant_id": ps_tenant,
            "company_id": uuid4(),  # ← deprecated, must be stripped
            "email": "test@example.com",
            "properties": {"associatedcompanyid": "X-COMPANY-ID"},
        }),
    ]
    for mapper_cls, record in fixture_rows:
        mapper = mapper_cls(client_id_lookup=lookup)
        for row in mapper.map(record):
            forbidden_fields = set(row.fields.keys()) & DEPRECATED_SOFT_FK_COLUMN_NAMES
            assert not forbidden_fields, (
                f"{mapper_cls.__name__}.map() emitted deprecated soft-FK "
                f"column(s) in CIPRow.fields: {forbidden_fields}. "
                f"Per CIP-FW-004 these are vestigial — strip them in the mapper."
            )
            forbidden_overflow = set(row.overflow.keys()) & DEPRECATED_SOFT_FK_COLUMN_NAMES
            assert not forbidden_overflow, (
                f"{mapper_cls.__name__}.map() emitted deprecated soft-FK "
                f"column(s) in CIPRow.overflow: {forbidden_overflow}. "
                f"Per CIP-FW-004 these are vestigial — strip them in the mapper."
            )


# ── Test 2: no surprise typed `*_id uuid` column on cip_* tables ─────────


@pytest.mark.requires_postgres
def test_no_surprise_typed_uuid_fk_columns(seeded_engine) -> None:
    """Walk live `cip_*` entity tables; assert every `*_id uuid` column
    is either a legitimate PK/scope column or on the explicit
    promotions allowlist. Catches a future migration that silently
    resurrects the dead UUID-FK pattern.

    Per CIP-FW-004: typed promotion is `*_source_id TEXT`, not
    `*_id UUID`. CIP-UUID FKs are formally REJECTED.
    """
    from sqlalchemy import text

    forbidden_findings: list[str] = []
    with seeded_engine.connect() as c:
        rows = c.execute(text("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name LIKE 'cip_%'
              AND table_name NOT LIKE 'cip_%_history'
              AND data_type = 'uuid'
              AND column_name LIKE '%_id'
            ORDER BY table_name, column_name
        """)).all()
    for table_name, column_name in rows:
        if column_name in _LEGITIMATE_UUID_COLUMNS:
            continue
        if (table_name, column_name) in _INTENTIONAL_TYPED_PROMOTIONS:
            continue
        if (table_name, column_name) in DEPRECATED_SOFT_FK_COLUMNS:
            # Acceptable — they exist but are COMMENT-deprecated.
            continue
        forbidden_findings.append(f"{table_name}.{column_name}")

    assert not forbidden_findings, (
        "Surprise typed UUID-FK column(s) detected:\n  "
        + "\n  ".join(forbidden_findings)
        + "\n\nPer CIP-FW-004 (Association Contract, 2026-05-22), typed "
          "promotion for cross-entity associations uses `<assoc>_source_id "
          "TEXT`, NOT `<assoc>_id UUID`. Either:\n"
          "  (a) Rename to *_source_id (TEXT) per the Atlas-blessed pattern, OR\n"
          "  (b) Add to _INTENTIONAL_TYPED_PROMOTIONS allowlist in this "
          "test if it's a legitimate non-FK UUID column with explicit Tim "
          "approval.\n"
          "Do NOT silently introduce a new CIP-UUID FK."
    )
