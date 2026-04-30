---
kind: contract
domain: client-intelligence-platform
---

# Foundry Client Intelligence Platform — foundry-cip

This is the standalone repo for **CIP**, Foundry's tenant-partitioned client intelligence platform. The framework code, schema migrations, and operating documentation all live here. Foundry-Agent-System (the monorepo) consumes foundry-cip via `pip install foundry-cip` and runs the migrations against its shared Postgres.

## What this repo is

- A Python library: `from cip.integration_mesh import CIPConnector, CIPMapper, run_sync`.
- A schema definition: 8 Alembic migrations creating the `cip_*` tables and SCD-type-2 history tables.
- A documentation set: vision, architecture, runbooks (TENANT-ONBOARDING-CHECKLIST, CONNECTOR-AUTHORING-GUIDE, etc.).

## What this repo is not

- Not a service. CIP runs in the caller's process via the orchestrator's `run_sync` function.
- Not a deployment. Foundry-Agent-System (or any consumer) handles deployment.
- Not the consumption surfaces. Metabase, REST API, MCP tools, chatbot — those live in Foundry-Agent-System.

## Orient

1. Read `README.md` (top-level).
2. Read `docs/vision/VISION.md` for the WHAT.
3. Read `docs/architecture/ARCHITECTURE.md` for the HOW.
4. Read `docs/vision/ROADMAP.md` for sequencing.
5. If onboarding a new venture: read `docs/DEPLOYING-FOUNDRY-CIP-FOR-A-NEW-VENTURE.md`.
6. If shipping a connector: read `docs/CONNECTOR-AUTHORING-GUIDE.md`.
7. If something is broken: read `docs/TROUBLESHOOTING-AND-INCIDENT-RESPONSE.md`.

## Rules (inherited from Foundry but stated here for clarity)

- All timestamps UTC. All UUIDs v4.
- Every database query MUST include tenant_id scoping (D-026).
- All LLM calls go through the LLM Roster (D-018/D-031/D-077). M2 ships no LLM calls; M5 wires the Roster.
- Master branch only. No branches, no PRs (Foundry convention).
- Tests run against `postgres:16-alpine` via `testcontainers-python`. RLS tests require real Postgres; SQLite is not supported.

## Decisions that govern this repo

D-118 (CIP framework lives in Integration Mesh), D-119 (CIP consumes Knowledge + Graph subsystems), D-120 (Three Data Layers), D-122 (CSS tag ownership), D-123 (Alembic schema authority), D-126 (non-SQL schema governance), D-133 (KnowledgeText return type), D-134 (Protocol-based connector framework), D-135 (app-layer SCD Type 2), D-146 (this repo exists; monorepo consumes via pip; separate alembic_version tables). Full text in the source-monorepo's `docs/DECISION-LOG.md`. As of extraction, foundry-cip does not maintain its own DECISION-LOG; governance authority remains in Foundry-Agent-System.

## Repo Layout

```
foundry-cip/
├── cip/                          # The Python package (importable as `cip`)
│   ├── __init__.py
│   ├── py.typed                  # PEP 561 marker
│   └── integration_mesh/         # M2 framework — Protocol + orchestrator + persister + ...
├── docs/
│   ├── vision/                   # VISION, ROADMAP, PHASE-1-PLAN, PHASE-1-PLAIN-SPEC, PHASE-2.5-PLAN
│   ├── architecture/             # ARCHITECTURE.md (Phase 0 data model, scaling, extraction story)
│   ├── notes/                    # Initial braindump, vision-discussion log
│   ├── research/                 # industry-landscape.md
│   ├── archive/                  # Superseded stage docs from monorepo era
│   ├── CONNECTOR-AUTHORING-GUIDE.md
│   ├── LENS-AUTHORING-GUIDE.md
│   ├── MIGRATION-RUNBOOK.md
│   ├── RLS-SET-LOCAL-OPERATOR-GUIDE.md
│   ├── SYNC-ORCHESTRATOR-GUIDE.md
│   ├── FOUR-ACCESS-PATHS.md
│   ├── FIXTURE-TENANT-HANDBOOK.md
│   ├── CSS-CLASSIFICATION-CONTRACT.md
│   ├── PHASE-1-TO-PHASE-2-HANDOFF.md
│   ├── TENANT-ONBOARDING-CHECKLIST.md
│   ├── _TEMPLATE.md
│   ├── DEPLOYING-FOUNDRY-CIP-FOR-A-NEW-VENTURE.md
│   ├── EXPORTING-VENTURE-CONNECTORS.md
│   ├── STANDALONE-INTEGRATION-GUIDE.md
│   └── TROUBLESHOOTING-AND-INCIDENT-RESPONSE.md
├── migrations/
│   └── versions/                 # 8 Alembic migrations: cip_01..cip_08 + _RESERVED.md
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── integration_mesh/         # Unit tests for framework (M2 fills)
│   ├── fixtures/                 # Conformance harness fixtures (M2 fills)
│   └── migrations/               # 9 RLS smoke tests + their conftest.py
├── alembic.ini
├── pyproject.toml
├── LICENSE                       # Apache 2.0
├── README.md
├── CONTRIBUTING.md
├── SECURITY.md
├── CHANGELOG.md
├── .gitignore
├── .gitattributes
└── CLAUDE.md                     # This file
```

## Commands

```bash
# Install (editable for dev):
pip install -e ".[dev]"

# Run migrations against a Postgres (USE ALEMBIC DIRECTLY):
DATABASE_URL=postgresql+psycopg://user:pw@host:5432/db alembic upgrade head
DATABASE_URL=postgresql+psycopg://user:pw@host:5432/db alembic downgrade -1
DATABASE_URL=postgresql+psycopg://user:pw@host:5432/db alembic current
DATABASE_URL=postgresql+psycopg://user:pw@host:5432/db alembic history

# Verify schema matches code (v5.2 — uses python -m cip.db check, the
# `python -m` pattern matches `python -m pip` / `python -m uv`. The previous
# v4 foundry-cip-migrate wrapper is retired):
DATABASE_URL=postgresql+psycopg://user:pw@host:5432/db python -m cip.db check

# Run tests:
pytest

# Type-check:
mypy cip/

# Lint:
ruff check cip/ tests/
```

**Why `alembic` directly for upgrade/downgrade and `python -m cip.db check`
for the schema-compat check?** Per Round-6 LLM panel guidance (5/6 expert
models): wrapping a stable upstream CLI without adding orchestration is a
leaky abstraction. The cross-pollution guard in `env.py` fires for both
`alembic` direct and any wrapper, so the wrapper added no behavior. The
schema-compat check DOES add novel behavior (runtime schema-vs-code revision
comparison) — but the right shape for it is `python -m cip.db check`, not a
console_scripts entry point. Matches `python -m pip`, `python -m uv` —
industry pattern, zero entry-point maintenance burden.

The previous `foundry-cip-migrate` console script (v4) is retired.
