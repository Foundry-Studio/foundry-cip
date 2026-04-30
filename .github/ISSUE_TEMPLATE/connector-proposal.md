---
name: New connector proposal
about: Propose a new CIPConnector for a source system (HubSpot, Zendesk, Stripe, etc.)
title: "[CONNECTOR] "
labels: connector, enhancement
assignees: timjordan-foundry-studio
---

## Source system

<!-- Name + link to API docs. -->

## Why this connector

<!-- Which venture(s) need it? What use case does it unlock? -->

## Connector shape (sketch)

```python
class MyConnector(CIPConnectorBase):
    connector_id = "..."
    # ... method sketches per CONNECTOR-AUTHORING-GUIDE.md
```

## Mapper shape (sketch)

```python
class MyMapper(CIPMapperBase):
    object_type = "..."
    target_table = "cip_..."
    # ... method sketches
```

## Open questions

<!-- Schema mapping questions, auth model, rate-limit policy, history-capture requirements, etc. -->

## Reference

- [CONNECTOR-AUTHORING-GUIDE.md](../../docs/CONNECTOR-AUTHORING-GUIDE.md)
- [SYNC-ORCHESTRATOR-GUIDE.md](../../docs/SYNC-ORCHESTRATOR-GUIDE.md)
- [Conformance harness](../../tests/fixtures/connector_conformance/) (M2 ships this)
