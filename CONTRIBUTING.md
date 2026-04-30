# Contributing to foundry-cip

This repo is part of [Foundry Studio](https://github.com/Foundry-Studio). It governs the Client Intelligence Platform — a generic connector framework + tenant-partitioned data layer.

## How to contribute

### Bug reports + feature requests

Open an issue using one of the templates. Include:
- What you tried
- What you expected
- What actually happened
- The version of foundry-cip + Python + Postgres
- A minimal reproduction if possible

### Pull requests

Foundry's working convention is master-branch development inside controlled environments. Pull requests from external contributors are accepted but reviewed against the same governance bar applied internally:

1. Run the test suite locally — `pytest` against a real Postgres (testcontainers handles this).
2. Confirm `mypy cip/` passes (strict mode).
3. Confirm `ruff check cip/ tests/` passes.
4. New migrations need a corresponding revision in the Alembic chain — see `docs/MIGRATION-RUNBOOK.md`.
5. Connector contributions follow `docs/CONNECTOR-AUTHORING-GUIDE.md` — every connector implements the `CIPConnector` Protocol + ships a conformance-harness pass.
6. Reserved migration slots: `cip_09` and `cip_10` are reserved for Phase 3 cross-tenant grants. Use `cip_13_<descriptive>.py` or higher for new Phase 1/M2 migrations. See `migrations/versions/_RESERVED.md`.

### Decision authority

Architectural decisions affecting this repo land in the source-monorepo's `docs/DECISION-LOG.md` (D-numbers). foundry-cip implements; it does not author governance. If your contribution would require a new D-number, open an issue first and we'll route to the source-monorepo for decision authoring.

## Code of conduct

Be useful, be specific, be kind. Disagreement is welcome; condescension is not.

## Security

Vulnerabilities (RLS bypass, tenant leakage, etc.) — see `SECURITY.md` for private reporting.

## Ownership

Maintainer: Tim Jordan ([Foundry Studio](https://github.com/Foundry-Studio)).
Contact: tim@foundry-studio.com.
