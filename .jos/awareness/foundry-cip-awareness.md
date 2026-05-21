# foundry-cip — Cross-Venture Awareness Manifest

> Per JOS-SPEC-018 v1.1. Surfaces what CIP offers to other ventures and what CIP needs from them.
> Aggregator: `jordan-operating-system/scripts/jos_tools/awareness_aggregator.py`

```yaml
schema_version: "1.0"
manifest_type: venture_awareness
venture: foundry-cip
owner: tim
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence_days: 90

# What CIP provides to other ventures + agents working in them
offers:
  - id: cip-python-library
    title: foundry-cip Python Library
    description: >
      Multi-tenant client-data platform shipped as a pip-installable Python library.
      Provides CIPConnector + CIPMapper Protocols + sync orchestrator + persister
      + SCD-2 differ + tenant context + lens engine. Consumed by Foundry-Agent-System
      (and any future product) via `pip install foundry-cip`.
    consumption_surface: library
    access: public-in-portfolio
    status: stable
    contact: tim
    external_link: https://github.com/Foundry-Studio/foundry-cip

  - id: cip-schema-and-migrations
    title: CIP Schema + Alembic Migrations
    description: >
      11 Alembic migrations creating cip_* tables (companies/contacts/deals/tickets/
      files-metadata + bitemporal SCD-2 history + RLS policies). Migration chain uses
      version_table = alembic_version_cip per D-146. Apply via `alembic upgrade head`
      against any consumer's Postgres.
    consumption_surface: data-feed
    access: tenant-scoped
    status: stable
    related: [cip-python-library]
    contact: tim

  - id: cip-connector-framework
    title: Connector Framework + Conformance Harness
    description: >
      Protocol-based framework letting any external source plug in. 8-test conformance
      harness gates new connectors before their migration lands. FixtureConnector +
      HubSpot + Zendesk shipped; Plaid + Chatwoot planned.
    consumption_surface: library
    access: public-in-portfolio
    status: stable
    related: [cip-python-library]

  - id: cip-lens-engine
    title: Multi-Lens Filtered Views (P-21)
    description: >
      Query-time predicate compilation from cip_views.filter_config JSONB AND-composed
      with tenant RLS. Adding a new lens = INSERT-only into cip_views, no schema or
      code change. Golden-file snapshot harness locks determinism.
    consumption_surface: library
    access: tenant-scoped
    status: stable
    related: [cip-python-library, cip-schema-and-migrations]

  - id: cip-metabase-grant-matrix
    title: cip_metabase_role + lens_* Postgres Views
    description: >
      Postgres role + view grant matrix structurally enforcing P-21 — REVOKE on cip_*
      tables; GRANT on lens_* views only. M5 shipped lens_all_companies +
      lens_eu_west_companies; M8 fixture-tenant gate PASSED 2026-05-12. Pattern scales
      to additional lenses by INSERT-only.
    consumption_surface: data-feed
    access: tenant-scoped
    status: stable
    related: [cip-lens-engine, cip-schema-and-migrations]

  - id: cip-tenant-isolation-pattern
    title: RLS + SET LOCAL Tenant Isolation Pattern
    description: >
      Defense-in-depth tenant isolation — PostgreSQL Row-Level Security on every cip_*
      table keyed on app.current_tenant GUC + explicit tenant_id predicates in lens
      views. 9 RLS smoke tests at tests/migrations/. Documented in
      docs/RLS-SET-LOCAL-OPERATOR-GUIDE.md.
    consumption_surface: library
    access: public-in-portfolio
    status: stable
    related: [cip-python-library]

  - id: cip-doc-suite
    title: CIP Phase-1 Documentation Suite
    description: >
      10 runbook artifacts shipped with Phase 1: TENANT-ONBOARDING-CHECKLIST,
      CONNECTOR-AUTHORING-GUIDE, LENS-AUTHORING-GUIDE, MIGRATION-RUNBOOK,
      RLS-SET-LOCAL-OPERATOR-GUIDE, SYNC-ORCHESTRATOR-GUIDE, FOUR-ACCESS-PATHS,
      FIXTURE-TENANT-HANDBOOK, CSS-CLASSIFICATION-CONTRACT, PHASE-1-TO-PHASE-2-HANDOFF.
    consumption_surface: docs
    access: public-in-portfolio
    status: stable

  - id: cip-fixture-corpus
    title: Deterministic Synthetic Corpus (FixtureConnector)
    description: >
      1150-row deterministic synthetic dataset reproducible byte-for-byte under
      Python 3.12 + Faker pin + PYTHONHASHSEED=0. Useful for any product wanting
      synthetic-data tests against the CIP schema.
    consumption_surface: dataset
    access: public-in-portfolio
    status: stable
    related: [cip-connector-framework]

# What CIP wishes existed (or wishes was better) from other ventures
needs:
  - id: fas-knowledge-subsystem-stable
    title: FAS Knowledge subsystem stable + tenant-isolated
    description: >
      CIP-CAP-003 (Derived Knowledge) needs FAS's Knowledge subsystem to provide
      stable KnowledgeText ingestion + retrieval with cross-tenant isolation. Today
      the hook is wired (in-progress); first end-to-end use in Phase 2 will exercise
      it. Tenant-isolation in the vector store is the load-bearing solve-for.
    related_offers: [foundry-agent-system:foundry-mcp-tools, foundry-agent-system:knowledge-retrieval]
    priority: would-use-today

  - id: fas-graph-subsystem-graphrag
    title: FAS Graph subsystem GraphRAG retrieval
    description: >
      CIP-CAP-003 also consumes the Graph subsystem for entity + relationship
      retrieval. GraphRAG paths from CIP entities (companies/contacts/deals/tickets)
      to the rest of the platform's knowledge graph. Phase 2-3 will exercise this.
    related_offers: [foundry-agent-system:knowledge-retrieval]
    priority: nice-to-have

  - id: fas-mcp-cip-tools
    title: foundry_mcp_cip_query / _search / _files MCP tools
    description: >
      Phase 4 deliverable but FAS-side. CIP's MCP tool surface (CIP-CAP-005)
      requires FAS to expose the foundry_mcp_cip_* tools that wrap CIP's
      Python API. Today: agents must call CIP through the library; not yet
      through MCP.
    priority: nice-to-have

  - id: fas-railway-deploy-orchestration
    title: Railway deploy orchestration for cip_* migrations
    description: >
      CIP migrations need to land on Railway prod when CIP is bumped on FAS side.
      Today: manual coordination. Future: alembic upgrade head automated as part
      of FAS's deploy flow with cip-specific change detection.
    related_offers: [foundry-agent-system:fas-railway-deployment]
    priority: nice-to-have

# v1.1 pointers to CIP's enumeration files — consumed by JOS-DIR-FLEET-FEATURES
features_manifest:
  path: "features.yaml"

capabilities_manifest:
  path: "capabilities.yaml"
```

## Notes

- **Cadence:** reviewed every 90 days or whenever a new pillar lights up.
- **What's intentionally NOT here:** every individual feature. Coarse-grain only. For granular discovery, agents follow `features_manifest.path` (v1.1 pointer) into the per-thing `features.yaml`.
- **Aggregator handling:** the JOS-side aggregator may copy this file into `jordan-operating-system/distribution/awareness/foundry-cip.yaml` for the fleet projection. The file at this path is the canonical source.
- **Phase-2 update trigger:** when Wayward goes live as first real tenant, update `offers:` to add a `wayward-tenant-coordinates` entry and update `needs:` priority on `fas-knowledge-subsystem-stable`.
