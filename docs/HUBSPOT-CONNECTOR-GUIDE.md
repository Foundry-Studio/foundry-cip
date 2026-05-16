# foundry: kind=doc domain=client-intelligence-platform
---
kind: doc
domain: client-intelligence-platform
status: active
last_updated: 2026-05-16
authors: [tim, cc-session-2026-05-15]
audience: [connector maintainers, new-tenant operators, agents querying CIP HubSpot data]
---

# HubSpot Connector — Operator Guide

> **Tenant-agnostic.** This guide captures everything an operator or contributor needs to know about CIP's HubSpot connector behavior, gotchas, rate limits, and decisions. Wayward-specific knowledge lives in `docs/tenants/<wayward-uuid>/`. This guide applies to ANY tenant whose HubSpot portal is connected to CIP.
>
> Companion: [`CONNECTOR-AUTHORING-GUIDE.md`](CONNECTOR-AUTHORING-GUIDE.md) covers the generic `CIPConnector` Protocol; this guide covers HubSpot-specific concerns layered on top.

## 1. What the HubSpot connector does

Implements the full `CIPConnector` + `CIPMapper` Protocol against HubSpot's v3 CRM API. Four object types in `_OBJECT_TYPES`:

| HubSpot path | CIP table | Notes |
|---|---|---|
| `companies` | `cip_companies` | ~292 properties per portal (varies by plan + customs) |
| `contacts` | `cip_contacts` | ~443 properties (most engagement-rich) |
| `deals` | `cip_deals` | ~435 properties (custom rev-share / partnership fields land here) |
| `tickets` | `cip_tickets` | Requires `tickets-read` scope; many tenants 403 on this |

Connector ID: `hubspot-v1`. Rate limit policy: 10 req/sec (HubSpot Standard plan).

## 2. Authentication

HubSpot Private App Tokens (PATs). Token format: `pat-<region>-<uuid>` (e.g., `pat-na2-...`). Region prefix matters — `na1` portals can use `pat-na1-*`; `eu1`/`na2` are separate regions.

Environment variables read by the connector:
- `WAYWARD_HUBSPOT_TOKEN` — currently hardcoded to Wayward; **TODO** (PM scope): generic per-tenant env-var naming
- `WAYWARD_HUBSPOT_PORTAL_ID` — informational; not strictly required for auth

Probe: connector calls `GET /crm/v3/objects/companies?limit=1` to validate auth on every `authenticate()`. A 401 raises `AuthenticationError`; other HTTP errors during probe are also run-fatal.

## 3. Permission scopes — audit BEFORE first sync

HubSpot scopes are per-object-type. A token may have:
- `crm.objects.companies.read` ✓
- `crm.objects.contacts.read` ✓
- `crm.objects.deals.read` ✓
- `crm.objects.tickets.read` ✗ (common — many tenants use Zendesk for tickets)

**Behavior on 403/401 per entity (post-scope `d3311846`):** the connector marks the entity unavailable in `self._unavailable_entities` and continues with other entities. The whole run doesn't fail. The unavailable entity list is surfaced in script output and (eventually) in `cip_sync_runs.error_detail` (pending structured-error-detail scope).

**Operator action at onboarding:** in Phase 1 of `ONBOARDING-A-NEW-TENANT.md`, probe each entity once. Document expected-unavailable entities in the tenant profile so future operators don't waste time re-discovering.

## 4. Property discovery — full catalog by default

**Critical lesson (2026-05-15):** never use a hardcoded property list. The HubSpot connector calls `/crm/v3/properties/{type}` at first use (per-instance cached in `_discovered_properties`) and pulls the ENTIRE property catalog the portal exposes. This is the only correct behavior for a multi-tenant connector — different tenants have wildly different custom-property landscapes.

| Tenant scale (typical) | Hub-default properties | Custom properties | Total |
|---|---|---|---|
| Companies | ~257 | ~35 | ~292 |
| Contacts | ~387 | ~56 | ~443 |
| Deals | ~373 | ~62 | ~435 |
| Tickets | varies | varies | (auth-gated) |

Calculated properties (where HubSpot derives the value at read time, e.g. `hs_time_in_lead`) are filtered out of the discovered list because they have no stored history and adding them to backfill requests slows pages without benefit.

**Drift handling:** if a tenant's HubSpot admin adds new custom properties later, the connector picks them up on the next sync (discovery re-runs each connector instantiation). However, NO ALERT FIRES on new properties — a separate "schema drift detector" scope (`6e7f08bb`) handles that.

## 5. Current-state ingestion — POST batch/read flow

Because the discovered property list often exceeds ~250 properties per entity, **the connector uses POST `/crm/v3/objects/{type}/batch/read`**, NOT GET with `?properties=` in the URL. GET with a CSV property list hit HTTP 414 (Request-URI Too Large) on Wayward's contacts endpoint — ~443 properties × ~30 chars = 13KB URL, exceeding HubSpot's URL cap.

Two-pass flow per entity:
1. `GET /crm/v3/objects/{type}?limit=100` — returns 100 IDs + `paging.next.after` cursor token
2. `POST /crm/v3/objects/{type}/batch/read` with body `{"inputs": [{"id": ...}, ...], "properties": [...]}` — returns each record with the full property set

Pagination terminates when `paging.next.after` is missing.

## 6. Historical backfill — same flow + 50-record cap

HubSpot's `propertiesWithHistory` parameter has a documented cap of **50 records per request** ("You can only request at most 50 objects in one request for properties with history"). The connector enforces this in `_backfill_entity` by setting `limit=50` on the GET-IDs call.

Backfill uses the same two-pass shape as current-state:
1. `GET /crm/v3/objects/{type}?limit=50` — 50 IDs
2. `POST /crm/v3/objects/{type}/batch/read` with body containing BOTH `properties` AND `propertiesWithHistory` arrays (full discovered list)

The connector emits one `HistoricalRecord` per property-revision-snapshot per record, ordered oldest → newest.

## 7. Timestamp handling — semantic, not string

**Critical lesson (2026-05-15):** HubSpot property-history timestamps can serialize with mixed millisecond precision in the same property's history (e.g., `"2025-07-15T18:03:26.491Z"` and `"2025-07-15T18:03:26Z"` for the same logical instant). Sorting these as ASCII strings produces the wrong order (`.` < `Z` in ASCII).

The connector's `_historical_records_for_obj` parses every timestamp to a `datetime` object FIRST, then groups snapshots by parsed datetime (semantic equivalence), then sorts datetime objects. Defensive `if valid_to <= valid_from: continue` skips any snapshot whose constraint would be violated (`ck_cip_*_history_valid_range` requires strict `>`).

**Lesson for any future timestamp-handling code:** parse to typed values before any comparison, sort, or grouping.

## 8. SCD-2 history table FK chain

For each `HistoricalRecord` emitted, the persister:
1. Looks up `cip_<table>.id` by `(tenant_id, source_connector, source_id)`
2. If found: INSERT into `cip_<table>_history` with `record_id = <looked-up id>`
3. If not found: increment `skipped_missing_current` counter (current-state sync must run FIRST before backfill)

This means: **always run current-state sync to completion before historical backfill.** If current-state is still running when backfill fires, the still-pending records will produce `skipped_missing_current` instead of history rows.

The orchestrator wraps each persist in a SAVEPOINT (`db.begin_nested()`), so a single record's failure does NOT poison the whole batch. Cascade failures from earlier in CIP's history are no longer possible.

## 9. Rate limiting

HubSpot's standard rate limit: **10 req/sec, 100,000 req/day** (Standard plan). Higher tiers have higher caps. The connector declares `RateLimitPolicy(requests_per_second=10.0, burst=10)`.

HTTP 429 with `Retry-After` is honored by the transport layer (`_http.py`). Backoff caps at 300s. After 5 retries the batch is marked failed (per-batch retry budget); after 3 consecutive batch failures the run aborts (per-run safety net).

**For very large tenants** (>500K records across entities), the 10 req/sec cap is the binding constraint. Backfill of ~100K records ≈ 6-10 hours. There's no way around the rate limit without a paid HubSpot uplift OR splitting load across multiple PATs (not currently supported by the connector).

## 10. Common HubSpot quirks

| Quirk | Impact | What we do |
|---|---|---|
| `numberofemployees` and `annualrevenue` returned as strings | Type drift if not coerced | Mapper coerces to `Decimal` via `_NUMERIC_FIELDS` |
| `hubspot_owner_id` is an integer ID, not a name/email | Queries need a join to resolve | Tier 2 scope `cb6750f0` adds `cip_owners` table; until then, owner name lives in `properties->>'ownername'` if present |
| `dealstage` returns a stage ID (like `"1304289985"`), not a label | Stage names invisible without pipelines API | Same Tier 2 scope adds `cip_pipelines` resolver |
| Engagements (notes, calls, emails, meetings) are SEPARATE object types | Not synced today | Tier 1 scope `9952dd26` adds engagements connector — most-valuable next addition |
| `hs_lastmodifieddate` differs from `lastmodifieddate` (contacts) | Inconsistent incremental key | Connector treats `hs_lastmodifieddate` as authoritative; falls back to `lastmodifieddate` for contacts only |
| Some companies have NO `name` property set | NULL violates `cip_companies.name NOT NULL` | Mapper applies fallback `"(unnamed hubspot company #<source_id>)"` |
| Calculated properties return current values but have no history | Backfill skips them quietly | Discovery filter on `calculated=true` |
| Properties with no revisions still appear in `propertiesWithHistory` response with `[]` | Wastes parse time but harmless | No mitigation needed |

## 11. Known gaps (filed as PM scopes)

| Gap | PM scope | Tier |
|---|---|---|
| Engagements (notes, calls, emails, meetings, tasks) — Firefly transcripts, etc. | `9952dd26` | Tier 1 |
| Owners + Pipelines + Stage labels resolver | `cb6750f0` | Tier 2 |
| Files (proposals, contracts, mocks attached to deals/contacts) | `ee5b7e72` | Tier 2 (bundled) |
| Marketing emails + Lists / memberships | `510fff61` | Tier 2 |
| Schema drift detector (alert on new fields) | `6e7f08bb` | Tier 2 |
| Quotes / Line items / Products / Feedback submissions | (unfiled, future) | Tier 3 |

## 12. Operating the connector — common commands

**Current-state sync only (one tenant):**
```bash
DATABASE_URL=$DATABASE_PUBLIC_URL \
  WAYWARD_HUBSPOT_TOKEN=pat-... \
  WAYWARD_HUBSPOT_PORTAL_ID=... \
  SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \
  python -u scripts/run_wayward_hubspot_only.py
```

**Historical backfill (after current-state succeeds):**
```bash
# Same env, different script:
python -u scripts/run_wayward_hubspot_backfill_no_tickets.py
```

**Note on script naming:** the `_no_tickets` suffix is historical; today's connector handles per-entity isolation natively, so the subclass-override that originally motivated the script name no longer exists. The script uses the plain `HubSpotConnector` and the `tickets` entity gets gracefully skipped on 403. Rename pending (PM scope: minor cleanup).

## 13. Validation checklist before declaring HubSpot sync "good"

- [ ] `cip_sync_runs` shows `status='success'` for the most-recent current-state run
- [ ] `cip_sync_runs` shows `status='success'` for the most-recent backfill run (or `partial` with documented `error_detail`)
- [ ] Row counts in `cip_companies` / `cip_contacts` / `cip_deals` filtered by `source_connector='hubspot-v1'` match what the HubSpot UI reports (allow ~1% drift for transient deletions)
- [ ] `cip_companies.properties::jsonb ? '<custom-property-name>'` returns true for known custom properties (e.g. `customer_target_segment` on Wayward's portal)
- [ ] `cip_companies_history` has rows for at least 80% of `cip_companies` source_ids (lower coverage is expected — many companies have only create-event history)
- [ ] Manifest view `lens_tenant_manifest` (post scope `bfc3d5d0`) shows HubSpot connector active + property catalog populated

## 14. Bug history (reference)

| Date | Bug | Root cause | Fix |
|---|---|---|---|
| 2026-05-13 | Wayward Tier 3 import: 185 companies had no name | HubSpot allows NULL company names; CIP requires NOT NULL | Mapper applies `"(unnamed hubspot company #<source_id>)"` fallback |
| 2026-05-13/14 | `jobtitle` → `job_title` mapped to non-existent column | Mapper translation table referenced wrong column name | Corrected to `jobtitle` → `title`; added schema-drift test |
| 2026-05-14 | HubSpot tickets 403 killed whole HubSpot run | No per-entity isolation | Added per-entity try/except in stream_records + backfill_history |
| 2026-05-14 | Slim 4-property default missed all custom fields | Hardcoded property list | Discovery via `/crm/v3/properties/{type}`, full catalog cached per-instance |
| 2026-05-15 | `propertiesWithHistory` 400 on limit=100 | HubSpot caps at 50 records/request | Set `limit=50` in backfill |
| 2026-05-15 | `cip_sync_runs.sync_mode` CheckViolation on 'backfill' | Constraint only allowed full/incremental | Migration `cip_11_sync_mode_backfill` widens constraint |
| 2026-05-15 | SCD-2 `valid_range` violation on same-instant snapshots | ASCII string sort + mixed-precision timestamps | Parse to datetime first, group by semantic value, defensive `<=` guard |
| 2026-05-15 | 414 URL too long on contacts backfill (~443 props) | GET with property list in URL | POST `batch/read` with property list in body |
| 2026-05-15 | One bad record poisoned the whole batch (200 spurious failures) | `db.begin()` per batch, no savepoints | Per-record SAVEPOINT (`db.begin_nested()`) |

## Cross-references

- [`CONNECTOR-AUTHORING-GUIDE.md`](CONNECTOR-AUTHORING-GUIDE.md) — generic Protocol contract for writing new connectors
- [`ZENDESK-CONNECTOR-GUIDE.md`](ZENDESK-CONNECTOR-GUIDE.md) — sibling guide, same shape
- [`ONBOARDING-A-NEW-TENANT.md`](ONBOARDING-A-NEW-TENANT.md) — per-tenant discovery + onboarding procedure
- [`SYNC-ORCHESTRATOR-GUIDE.md`](SYNC-ORCHESTRATOR-GUIDE.md) — orchestrator run-loop, advisory locks, retry policy
- [`MIGRATION-RUNBOOK.md`](MIGRATION-RUNBOOK.md) — applying `cip_*` migrations
- HubSpot API docs: https://developers.hubspot.com/docs/api/overview
