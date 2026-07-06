---
doc_type: reference
owner: tim
status: active
created: 2026-07-06
last_modified: 2026-07-06
last_reviewed: 2026-07-06
review_cadence: 90
---
# Cross-Connector Identity Links

How CIP resolves that a **Zendesk** person and a **HubSpot** person are the same human,
so a support ticket can be attributed to the HubSpot company/brand it belongs to. This is the
missing edge that makes `lens_china_tickets` (Metabase ASK 2) possible.

Introduced in migration `cip_33_identity_links` (PM 08b4ce7d). Atlas-locked policy
(CIP-FW-004 §5 + `identity-resolution-policy-design.md`, Tim sign-off 2026-05-24).

## The problem

A Zendesk ticket carries a `requester_id` (a Zendesk user id) — it has **no HubSpot key**. To reach
the HubSpot company that owns the brand, the chain is:

```
cip_tickets (zendesk-v1) → properties->>'requester_id'         (Zendesk user id)
  → cip_contacts WHERE source_connector='zendesk-v1' AND source_id=requester_id
  → cip_identity_links (zendesk contact ↔ hubspot contact)      ← the resolved edge
  → cip_contacts (hubspot-v1) → properties->>'associatedcompanyid'
  → cip_companies.source_id → China-referral filter (the cip_24 predicate)
```

`cip_identity_links` is the cached, curatable representation of that middle edge.

## The table: `cip_identity_links`

A generic left↔right edge (not Zendesk-specific by shape), tenant-scoped (RLS FORCE + `WITH CHECK`,
per cip_30). Columns of note:

- `left_connector` / `left_source_id`, `right_connector` / `right_source_id` — the two endpoints
  (e.g. `zendesk-v1`/`<zendesk user id>` ↔ `hubspot-v1`/`<hubspot contact id>`).
- `link_type` — e.g. `deterministic-email` or `manual`.
- `confidence` — numeric; the ticket lens consumes only links `>= 0.9` (plus any `manual` /
  `operator:` link regardless of confidence).
- `method` — **part of the unique key** (`uq_cip_identity_links_edge_method`). This lets a
  `manual` / `operator:<who>` row coexist with a `deterministic-email-v1` row on the same edge, so
  **the deterministic pass never clobbers a human override** — consumption prefers the manual link.

## The resolver: `scripts/resolve_identity_links.py`

Populates the table. Deterministic **email-exact** match — NOT a fuzzy/ML matcher (that would be a v3,
out of scope). Run per-tenant, GUC-scoped, idempotent upsert (re-running produces no duplicate edges
thanks to the unique key). Grounded on prod evidence (EcomLever, 2026-05-24): of 20,152 distinct
Zendesk contact emails, 19,783 (98.2%) exact-match a HubSpot contact email, with 0 ambiguity.

Because the deterministic pass is upsert-idempotent and never overwrites a `manual`/`operator:` row,
it is safe to re-run on every sync cycle as new Zendesk/HubSpot contacts land.

## The consumer: `lens_china_tickets`

Defined in the same migration. Walks the chain above, joining `cip_identity_links` with
`il.confidence >= 0.9 OR il.method LIKE 'operator:%' OR il.link_type = 'manual'`, then applies the
`cip_24` China-referral predicate (deal `properties->>'source' LIKE 'China Referral%'`). GUC-scoped
like the other `lens_china_*` views. Granted to `cip_query_reader` + `cip_metabase_project_silk`.
See [LENS-INVENTORY.md](LENS-INVENTORY.md) for its row in the full lens table.

## Extending this to other connectors

The table shape is connector-agnostic. A new source (say a billing system) resolves into the same
graph by writing `<billing>`↔`hubspot-v1` edges with an appropriate `method`/`confidence`; any lens
that needs the join consumes edges the same way (confidence threshold + manual-override precedence).
Keep deterministic writers idempotent and never let them overwrite a `manual` edge.
