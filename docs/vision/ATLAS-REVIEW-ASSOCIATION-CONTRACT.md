---
id: CIP-FW-004
uuid: 7f3b8c9d-2e4a-4f6b-a8c1-3d5e9b2c7a4f
title: Atlas Review Request — Association Contract (typed-FK vs JSONB-source-id normalization)
type: framework
owner: tim
solve_for: Self-contained prompt for Atlas's review of how CIP should
  formally treat entity associations going forward. Surfaced as a latent
  gap during Phase 2.6 build (2026-05-22).
stage_label: trial
domain: meta
version: '1.0'
created: '2026-05-22'
last_modified: '2026-05-22'
last_reviewed: '2026-05-22'
review_cadence: 30
---

# Atlas Review — Association Contract (typed-FK vs JSONB-source-id)

> **For Tim to copy-paste:** everything below the `=====` line is the prompt to send Atlas. The intro is just orientation for the operator.

This is the latent gap Atlas explicitly punted to a separate review during Phase 2.6 (see [CIP-FW-003](ATLAS-REVIEW-PHASE-2.6-RESPONSE.md) §Q1 sharpening 2 + Atlas's 2026-05-22 follow-up ruling on data-shape). The build verified the gap empirically: CIP's typed FK columns (`cip_deals.company_id`, `cip_contacts.company_id`, `cip_tickets.requester_id`) are vestigial — no connector writes them, by design. All real associations live in JSONB properties (`hs_primary_associated_company`, `associatedcompanyid`, etc).

Phase 2.6 worked around this by joining via JSONB source-id refs. That was the right tactical call for shipping 2.6. The strategic question — should CIP normalize to typed FKs across all connectors + all tenants, or formally adopt JSONB-source-id as the canonical contract — is now ripe.

---

=====================================================================
COPY EVERYTHING BELOW THIS LINE TO ATLAS
=====================================================================

# Atlas Architecture Review — Association Contract for CIP

You are Atlas. You have full architectural authority over foundry-cip. Tim is filing this review request to resolve a latent gap that Phase 2.6 surfaced. The gap touches every connector + every tenant — it's a foundational decision, not a per-feature one.

## The gap (empirically verified)

CIP's `cip_*` tables define **typed FK columns** for cross-entity associations:

- `cip_deals.company_id uuid` — intended to point at `cip_companies.id`
- `cip_deals.contact_id uuid` — intended to point at `cip_contacts.id`
- `cip_contacts.company_id uuid` — intended to point at `cip_companies.id`
- `cip_tickets.requester_id uuid` — intended to point at `cip_contacts.id`

**None of these columns are populated by any deployed connector**, by design. Reading the HubSpot mapper (`connectors/hubspot/mapper.py`) and Zendesk mapper (`connectors/zendesk/mapper.py`):

- HubSpot's deal mapper's `_DOMAIN_FIELDS_BY_TYPE["deal"]` has no FK fields. The HubSpot association `hs_primary_associated_company` is dumped to `properties` JSONB via `overflow_fields()`.
- HubSpot's contact mapper writes `company_name` (a string) but never `company_id`. The HubSpot `associatedcompanyid` lands in `properties` JSONB.
- Zendesk's ticket mapper lists `requester_id` in `overflow_fields()`, so it's pushed to JSONB.

Verified against prod (EcomLever / Wayward tenant, 2026-05-22):
- `cip_deals.company_id` populated rows: **0 / 3,057**
- `cip_contacts.company_id` populated rows: **0 / 68,084**
- `cip_tickets.requester_id` populated rows: **0 / 3,390**
- `cip_deals.properties->>'hs_primary_associated_company'` populated: **~98% of deals**
- `cip_contacts.properties->>'associatedcompanyid'` populated: **most contacts**

The JSONB-source-id pattern is the LIVE contract. The typed FK columns are dead schema.

## Why this matters

Phase 2.6 needed cross-entity joins (build PS-side mirrored entities that share `client_id` via upstream company associations). I (Atlas) initially designed lens views assuming FK columns were populated. The build agent ran the views; they returned 0 rows. They had to be rewritten to do `cip_companies.source_id IN (SELECT properties->>'hs_primary_associated_company' FROM cip_deals WHERE ...)`. It works, but:

1. It's not discoverable — a junior dev reading the cip_* schema sees `company_id uuid` and naturally writes `JOIN ... ON company_id = ...`. The query silently returns nothing. No CHECK, no constraint, no docstring on the column saying "vestigial — use JSONB."
2. It's inconsistent — the columns exist but are dead. Future agents will keep authoring code against them.
3. JSONB extraction has different query-planner characteristics — Phase 2.6's first cip_24 draft used a correlated subquery and timed out at >60s. The rewrite to uncorrelated form ran in <0.5s. Typed-FK + index would have been ~0ms regardless of join shape.
4. Cross-connector identity resolution (Zendesk ticket → HubSpot contact by email, etc.) is hard to do via JSONB — but trivial via typed FK with a backfill resolver.
5. Phase 2.6 deferred `lens_china_tickets` out of scope specifically because the Zendesk → HubSpot identity resolution requires cross-connector email matching. A typed-FK contract would have made this a normal lens.

## The decision

CIP has three possible contract shapes. Pick one with reasoning.

### Option A — Typed-FK contract (normalize)

CIP formally requires all connectors to populate the typed FK columns. The JSONB source-id keys remain as connector-native provenance but are no longer the joining contract.

What this entails:
- Migration `cip_26_backfill_associations` (or similar): for every existing row, resolve JSONB source-ids to internal UUIDs via a SQL join (`UPDATE cip_deals SET company_id = (SELECT c.id FROM cip_companies c WHERE c.source_id = cip_deals.properties->>'hs_primary_associated_company' AND c.tenant_id = cip_deals.tenant_id)`). Repeat for contacts, tickets.
- Connector changes: HubSpot's deal mapper must look up the cip_companies UUID at mapping time and write it to `CIPRow.fields["company_id"]`. Same for contacts and Zendesk tickets. Either the mapper does the lookup directly (requires a session-scoped cache of source_id → uuid) or the persister does it post-mapping in a resolver step.
- Constraint hardening: add FK CHECK or actual FK constraint on the typed columns once backfilled.
- Schema-drift test: add a test that fails if any new typed-FK column is added without a corresponding mapper-side population.
- **Affects every existing tenant** — Wayward (119k companies, 68k contacts, 3k deals, 3.4k tickets), Rocky Ridge (no structured data — unaffected), future tenants.

### Option B — JSONB-source-id contract (lock the live behavior)

CIP formally documents that JSONB source-id refs ARE the association contract. The typed FK columns are deprecated.

What this entails:
- Migration to either drop the typed FK columns (destructive — breaks any external query that expects them) OR leave them in place with a DB-level COMMENT marking them deprecated.
- Update `docs/CONNECTOR-AUTHORING-GUIDE.md` to document the JSONB pattern as canonical: "connectors emit associations as `properties[json_key]` where `json_key` is the source-system's native association key (`hs_primary_associated_company`, `associatedcompanyid`, etc.). Joins use `target.source_id = source.properties->>'key'`."
- Build a query-helper function (or SQLAlchemy expression helper) so the JSONB-extraction join shape is canonical and reusable rather than reinvented per lens.
- Add a JSONB GIN index on `(tenant_id, properties)` for the common extraction keys to bring query planner performance closer to typed-FK speed.
- Schema-drift test: fail if any new typed-FK column is added (since JSONB is now the contract).
- **Cross-connector identity resolution** still needs solving separately (the deferred tickets-in-2.6 case) — likely via a `cip_identity_resolutions` table that bridges Zendesk emails ↔ HubSpot contact source_ids.

### Option C — Hybrid (split by stability)

Some associations get typed FKs (stable, source-system-native); others stay JSONB (volatile, cross-connector, or rarely-queried).

What this entails:
- A decision rule per association type. Candidates for typed:
  - `cip_deals.company_id` — high-traffic join, source-system-stable (HubSpot's company_id is durable)
  - `cip_contacts.company_id` — same
  - `cip_tickets.requester_id` — depends on identity-resolution strategy
- Candidates for JSONB:
  - Many-to-many: a deal associated with multiple companies (HubSpot supports this; JSONB array is simpler)
  - Cross-connector: a Zendesk ticket linked to HubSpot deals (no clean FK target without identity resolution)
- Migrate the FK-bound ones; keep the JSONB ones; document both.

## Tim's input (do NOT relitigate)

These are locked already by virtue of the 2.6 build shipping:

1. **Phase 2.6 mirror ships AS-IS using JSONB joins.** PS already has 5,229 mirrored rows in prod via the JSONB pattern. This review doesn't undo 2.6; it sets direction going forward.
2. **Mirror + grant patterns coexist.** Already established by CIP-SPEC-011. The association contract decision affects BOTH — mirror needs cross-entity joins on the destination side; grant needs them on the source side.
3. **PS's dest-side lens recut (Phase 2.7) is starting.** Whatever association contract Atlas locks here, the cip_26 PS lens migration will follow it. Don't pretend cip_26 won't be authored — it will be authored shortly. The contract you lock determines whether cip_26's lenses join via JSONB or typed FKs.

## Open questions for Atlas

### Q1 (BLOCKER): Which option — A, B, or C?

Pick one. Defend the call against the alternatives. Specifically address:
- Performance: typed-FK lookups vs JSONB GIN extraction at our current scale (~120k cip_companies, ~70k contacts, ~3k deals per Wayward-shape tenant)
- Operational complexity: backfill migration touching 200k+ rows per existing tenant vs ongoing JSONB query discipline
- Discoverability: a junior dev reading `cip_deals.company_id uuid` and the actual joining contract — how do they not get fooled?
- Future-proofing: cross-connector identity resolution (Zendesk-ticket → HubSpot-contact-by-email) for the deferred tickets-in-2.6 case

### Q2: What's the migration sequence?

If Option A or C: a single big-bang backfill migration, or a per-tenant rolling backfill, or a connector-by-connector cutover with old-and-new coexisting?

If Option B: do we DROP the typed FK columns, COMMENT them deprecated, or repurpose them (e.g., `company_id` stays but is renamed `_legacy_company_id` to make the deprecation visible)?

### Q3: Connector contract update

Whichever direction we pick, `CONNECTOR-AUTHORING-GUIDE.md` needs an updated normative section on associations. Sketch the new contract language — what does a connector author do? What's enforced by tests, what's documented as best practice?

### Q4: Schema-drift discipline

Today there's no test guarding "every new typed-FK column has a corresponding mapper-side write." If Option A or C, this discipline becomes load-bearing. Propose the test shape and where it lives (`tests/integration_mesh/test_mapper_schema_drift.py` already exists per `connectors/hubspot/mapper.py` line 76 reference).

### Q5: Cross-connector identity resolution

The Phase 2.6 deferred ticket lens needs Zendesk-requester-email → HubSpot-contact resolution before tickets can be mirrored. Is this:
- Part of the association-contract decision (e.g., Option A requires solving this to populate `cip_tickets.requester_id`)?
- A separate scope that the contract decision unblocks?
- Outside CIP's responsibility entirely (the connector authoring the data is expected to resolve at ingest time)?

Whichever — call out the dependency explicitly so the next agent picking up tickets-mirror knows what's blocking.

## Constraints

- Hard Split (CIP-SPEC-010) is binding — Foundry-Knowledge / Memory Service are off this conversation entirely.
- Phase 1 (Plain Jane) is closed — don't propose changes there.
- Mirror pattern (CIP-SPEC-011) is binding — the contract you pick must support the cross-tenant mirror cleanly.
- **Whatever you pick, it MUST work with the lens-mirror two-pass orchestration** (Pass 1 dedupes upstream company source_ids → destination client UUIDs; Pass 2 mirrors entities). If Option A, the orchestrator additionally populates the typed FKs after Pass 1 builds the lookup. If Option B, the orchestrator stays as-is.

## Expected output format

A v5.x-style deep plan. Sections:

1. **Decision** — option locked + one-paragraph defense
2. **Migration plan** — files, ordering, idempotency, rollback story, per-tenant blast radius estimate
3. **Connector contract update** — what `CONNECTOR-AUTHORING-GUIDE.md` §X says after this
4. **Test-side discipline** — what `test_mapper_schema_drift.py` (or equivalent) asserts going forward
5. **Cross-connector identity resolution** — answer to Q5
6. **Implementation pointers** — file paths in foundry-cip where the changes go, migration numbers (cip_26 is taken by Phase 2.7's PS lens recut — propose the next free number)
7. **Concerns / counter-cases** — anything the prompt missed that should be raised
8. **Blocking decisions for Tim** — tagged `[BLOCKING: Tim decision required]` if any

When you're done, output as a single markdown response. Tim will paste it back.
