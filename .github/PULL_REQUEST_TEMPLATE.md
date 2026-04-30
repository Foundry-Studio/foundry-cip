## What this PR does

<!-- One-paragraph summary. -->

## Why

<!-- The problem this solves or the capability it adds. Link issues if relevant. -->

## Type

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] New connector (implements `CIPConnector` Protocol)
- [ ] New migration (appends to Alembic chain)
- [ ] Breaking change (would cause existing functionality to not work as expected)
- [ ] Documentation update only

## Checklist

- [ ] `pytest` passes locally (against real Postgres via testcontainers)
- [ ] `mypy cip/` passes (strict mode)
- [ ] `ruff check cip/ tests/` passes
- [ ] If adding a migration: chain is linear, `alembic upgrade head` succeeds against fresh DB
- [ ] If adding a connector: passes the conformance harness in `tests/fixtures/connector_conformance/`
- [ ] CHANGELOG.md updated under `[Unreleased]`
- [ ] Documentation updated in `docs/` if behavior changed

## Tests

<!-- Describe what you tested and how. Include test commands if non-obvious. -->

## Decision authority

<!-- Does this PR require a new D-number in Foundry-Agent-System's DECISION-LOG?
     If yes, list the D-XXX you propose locking. -->
