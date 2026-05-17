# foundry — Local Governance

This directory holds the venture's own governance objects: rules,
standards, decisions, principles that apply to foundry but
are not (yet) JOS-wide.

## ID Prefix

All venture-owned objects use the `CIP-` prefix. Examples:

- `CIP-R01-<slug>.md` — venture rule
- `CIP-S01-<slug>.md` — venture standard
- `CIP-D0001-<slug>.md` — venture decision

## What Belongs Here

- Rules unique to this venture's domain (e.g., client engagement
  conventions for a client-services venture)
- Local standards that override or extend JOS defaults
- Decisions specific to this venture

## What Does NOT Belong Here

- JOS-wide governance — that lives in the JOS repo; this venture
  adopts via `.jos/charter.yaml`
- Work product, deliverables, drafts — those go elsewhere in the repo
- Conventions that should be JOS-wide — propose those to JOS

## Registry

See `_registry.yaml`. Every governance object in this directory
MUST be registered (JOS-SO-005 / JOS-R02).
