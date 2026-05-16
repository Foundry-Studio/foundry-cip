# foundry: kind=doc domain=client-intelligence-platform
---
kind: doc
domain: client-intelligence-platform
status: active
last_updated: 2026-05-16
authors: [tim, cc-session-2026-05-15]
audience: [connector maintainers, new-tenant operators, agents querying CIP Zendesk data]
---

# Zendesk Connector — Operator Guide

> **Tenant-agnostic.** This guide captures everything an operator or contributor needs to know about CIP's Zendesk connector. Tenant-specific knowledge lives in `docs/tenants/<tenant-uuid>/`. This guide applies to ANY tenant whose Zendesk instance is connected to CIP.
>
> Companion: [`CONNECTOR-AUTHORING-GUIDE.md`](CONNECTOR-AUTHORING-GUIDE.md) covers the generic `CIPConnector` Protocol; this guide covers Zendesk-specific concerns layered on top.

## 1. What the Zendesk connector does

Implements `CIPConnector` + `CIPMapper` against Zendesk's v2 REST API. Three object types:

| Zendesk endpoint | CIP table | Notes |
|---|---|---|
| `organizations` | `cip_companies` (alongside HubSpot companies) | Zendesk orgs map to CIP company shape |
| `users` | `cip_contacts` (alongside HubSpot contacts) | Zendesk end-users map to CIP contact shape |
| `tickets` | `cip_tickets` | Ticket audit log → `cip_tickets_history` |

Connector ID: `zendesk-v1`. Rate limit policy: 11 req/sec (Zendesk Standard plan).

## 2. Authentication

API token + email basic auth. Authorization header format: `Basic base64({email}/token:{api_token})`. Note the `/token` suffix in the username — easy to omit.

Environment variables:
- `WAYWARD_ZENDESK_TOKEN` — currently tenant-prefixed; **TODO** (PM scope): generic per-tenant env-var naming
- `WAYWARD_ZENDESK_USER` — email of the API user (e.g., `admin@yourorg.com`)
- `WAYWARD_ZENDESK_SUBDOMAIN` — the `<subdomain>.zendesk.com` portion

Probe: `GET /api/v2/users/me.json`. A 401 raises `AuthenticationError`. Other failures surface as `AuthenticationError` with the status code attached.

## 3. The cursor-vs-time-based incremental dichotomy (READ THIS BEFORE CHANGING ANY PAGINATION CODE)

Zendesk has **three** pagination idioms. Picking the wrong one for a given endpoint causes silent infinite loops (which we've hit twice — 2026-05-13 on organizations, 2026-05-15 on tickets backfill). The matrix:

| Endpoint | Pagination | Path |
|---|---|---|
| Organizations | **Time-based incremental** (cursor variant doesn't exist) | `/api/v2/incremental/organizations.json` with `start_time`, response carries `end_time` + `next_page` |
| Users | **Cursor-based incremental** | `/api/v2/incremental/users/cursor.json` with `start_time`, response carries `after_cursor` + `end_of_stream` |
| Tickets | **Cursor-based incremental** | `/api/v2/incremental/tickets/cursor.json` with `start_time`, response carries `after_cursor` + `end_of_stream` |

**Why both: organizations never got a cursor-incremental endpoint. Calling `/api/v2/incremental/organizations/cursor.json` returns 404.**

**Bug pattern (twice burned, finally documented):** the legacy `/api/v2/<type>.json` endpoints (without `/incremental/`) use `next_page` URL pagination — but on cursor-migrated portals those endpoints silently return page 1 forever. Symptom: `COUNT(DISTINCT source_id)` plateaus; total row count keeps growing; per-source-id row count balloons (1000+/record).

**Rule of thumb:** if Zendesk offers both legacy and cursor for an endpoint, ALWAYS use cursor. Stubs don't reproduce the page-1-loop, so unit tests alone are insufficient — verify against a real tenant during onboarding.

The connector's `_INCREMENTAL_PATH` dict makes the choice explicit per entity:

```python
_INCREMENTAL_PATH: dict[str, tuple[str, str]] = {
    "organizations": ("/api/v2/incremental/organizations.json", _PAGINATION_TIME),
    "users": ("/api/v2/incremental/users/cursor.json", _PAGINATION_CURSOR),
    "tickets": ("/api/v2/incremental/tickets/cursor.json", _PAGINATION_CURSOR),
}
```

`_stream_entity` dispatches on mode. `backfill_history` ALSO uses cursor-incremental for tickets (fixed 2026-05-15 — see §14).

## 4. Defensive pagination termination

Both pagination paths (cursor + time-based) have defense-in-depth termination:

**Cursor:** terminates when `end_of_stream=true` OR `after_cursor` is missing/empty (avoids infinite loop on malformed server responses).

**Time-based:** terminates when:
- `count < per_page` (canonical Zendesk indicator), OR
- `end_of_stream=true` (newer responses include this), OR
- `end_time <= start_time` (no forward progress — defensive exit; should never trigger but does if a buggy server is encountered)

The defensive exits exist because we've been bitten by the page-1-loop pattern twice. Don't remove them.

## 5. Backfill — ticket audit log

Zendesk historical data comes from **ticket audit events**. Organizations + users have NO first-class audit endpoint — they're current-state-only on the history side.

For each ticket, the connector:
1. Pulls `/api/v2/tickets/{id}/audits.json`
2. Sorts audits by `created_at`
3. Reconstructs ticket state by replaying `Change` events forward
4. Emits one `HistoricalRecord` per audit timestamp (with `valid_from` = audit timestamp, `valid_to` = next audit timestamp)

**Important:** audit log retention depends on Zendesk plan. Free/Suite Team plans retain audits indefinitely on active tickets; archived tickets may have shorter retention. There's no API to query retention policy programmatically — confirm with Zendesk admin during onboarding.

## 6. Timestamp resolution (seconds, not milliseconds)

**Critical lesson (2026-05-16):** Zendesk's audit `created_at` field is **second-resolution**, not millisecond. Two audit events on the same ticket within the same second produce `valid_from == valid_to` for the earlier one, violating `ck_cip_tickets_history_valid_range` (requires strict `>`).

The connector's `_historical_records_for_ticket` defensively skips snapshots where `valid_to <= valid_from`. Loss: typically 0-0.1% of audit events (only when a ticket has two events within the same wall-clock second). Acceptable.

If full audit fidelity matters later, the fix is to detect same-second collisions and merge their events into a single snapshot (the HubSpot connector does this via `snapshots.setdefault(ts_dt, {})`). Not implemented for Zendesk because the loss rate is so low.

## 7. Rate limiting

Zendesk Standard plan: **11 req/sec (= 700/min)**. Suite Professional+: higher caps. The connector declares `RateLimitPolicy(requests_per_second=11.0, burst=20)`.

The 11/sec is enforced by Zendesk via `Retry-After` headers on 429 responses. The transport layer honors these; backoff caps at 300s.

**Backfill efficiency:** the ticket audit endpoint is per-ticket (one HTTP call per ticket), so backfill of N tickets requires roughly N+pagination HTTP calls. At 11 req/sec: 3,000 tickets ≈ 5 minutes; 30,000 tickets ≈ 50 minutes. Plus pagination + persister overhead.

## 8. Common Zendesk quirks

| Quirk | Impact | What we do |
|---|---|---|
| `requester_id` and `assignee_id` are integer IDs into `users` | Joins required to get name/email | Future scope: resolve to `cip_owners` equivalent |
| `via.channel` field has 30+ possible values | Type drift if not normalized | Stored as-is in `channel` column; lens views can normalize |
| Private vs public comments distinction | Privacy matters for chatbot context | Pending scope `28739b6e` (Comments connector) adds the `public` flag |
| Tickets can be merged (one becomes the canonical, others redirect) | Source IDs change | Connector treats merged tickets as soft-deletes (relies on Zendesk's `status='deleted'`); no special merge handling yet |
| Side conversations are a separate API | Not synced today | Future scope (unfiled) |
| Macros / triggers / SLA policies are admin config, not transactional data | Not on the sync path | Could be a Tier 3 scope if anomaly detection needs it |
| Talk / Chat / Sell / Guide are separate Zendesk products | Need dedicated connectors | Out of scope for this connector |
| `next_page` URL responses include absolute URLs starting with `https://<subdomain>.zendesk.com/...` | Parsing required to strip host | `_stream_time_incremental` strips the host (legacy `next_page` only; cursor-incremental doesn't need this) |

## 9. Known gaps (filed as PM scopes)

| Gap | PM scope | Tier |
|---|---|---|
| Ticket comments + attachments (full conversation content) | `28739b6e` | Tier 1 — highest CS value |
| Satisfaction ratings (CSAT) | `ee5b7e72` (bundled) | Tier 2 |
| Schema drift detector | `6e7f08bb` | Tier 2 |
| Macros, triggers, SLA policies (admin config) | (unfiled) | Tier 3 |
| Side conversations | (unfiled) | Tier 3 |
| Talk / Chat / Sell / Guide connectors | (unfiled) | Tier 3 |

## 10. Operating the connector — common commands

**Current-state sync only:**
```bash
DATABASE_URL=$DATABASE_PUBLIC_URL \
  WAYWARD_ZENDESK_TOKEN=... \
  WAYWARD_ZENDESK_USER=admin@example.com \
  WAYWARD_ZENDESK_SUBDOMAIN=examplesupport \
  SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \
  python -u scripts/run_wayward_zendesk_only.py
```

**Historical backfill (after current-state succeeds):**
```bash
# Same env, different script:
python -u scripts/run_wayward_zendesk_backfill.py
```

Backfill prereq: `cip_tickets` must have anchor rows for the history-table FK lookup. Always run current-state first.

## 11. Monitoring discipline (lessons learned)

**For long-running backfills**, watch the per-source-id history-row distribution. Healthy ranges:
- Zendesk ticket audit history: 1-100 rows per ticket (most have 5-30; outliers up to 100 for very-active tickets)
- HubSpot company history: 1-5 rows per company
- HubSpot contact history: 5-100 rows per contact (engagement-heavy)

**Red flag patterns:**
- `COUNT(DISTINCT source_id)` plateaus while total row count grows → pagination loop
- Per-source-id row count > 200 → re-iteration or buggy duplicate emission
- Per-source-id row count exactly 1 across ALL records → maybe `valid_to == valid_from` defensive guard is dropping mid-history snapshots

Query for the health check:

```sql
SELECT source_id, COUNT(*) AS history_rows
FROM cip_tickets_history
WHERE tenant_id = '<tenant-uuid>'
GROUP BY source_id
ORDER BY history_rows DESC
LIMIT 10;
```

If the top 10 are reasonable (< 200 per ticket), the backfill is healthy.

## 12. Validation checklist before declaring Zendesk sync "good"

- [ ] `cip_sync_runs` shows `status='success'` for the most-recent current-state run
- [ ] `cip_sync_runs` shows `status='success'` for the most-recent backfill run (or `partial` with documented `error_detail`)
- [ ] Per-connector row counts match Zendesk UI: companies (orgs), contacts (users), tickets
- [ ] `cip_tickets_history` per-ticket row count averages 5-30 (sanity check on backfill validity)
- [ ] No ticket has > 500 history rows (sign of pagination bug)
- [ ] Manifest view `lens_tenant_manifest` shows Zendesk connector active + property catalog populated

## 13. Bug history (reference)

| Date | Bug | Root cause | Fix |
|---|---|---|---|
| 2026-05-13 | Wayward orgs ingest stuck in 22h infinite loop | Legacy `next_page` pagination on cursor-migrated portal | Cursor-incremental for users/tickets; time-based for orgs |
| 2026-05-15 | Backfill ingest 1,128 rows/ticket × 100 tickets repeatedly | Legacy `next_page` pagination on tickets backfill path | Cursor-incremental for backfill (matches current-state shape) |
| 2026-05-16 | 6 `valid_range` CheckViolations during backfill | Same-second audit timestamps | Defensive `valid_to <= valid_from: continue` in `_historical_records_for_ticket` |
| 2026-05-15 | 3 consecutive connection-drop batch failures aborted run | Transient Railway DB blip; orchestrator's 3-strike abort | Per-record SAVEPOINTs (the next-run succeeded) |
| 2026-05-16 | Backfill flush latency dominated by per-record DB roundtrips | Single-INSERT-per-record path; ~2 roundtrips × N records per flush | Batched persister + executemany INSERT per flush; see `SYNC-ORCHESTRATOR-GUIDE.md` §11. Zendesk benefits less than HubSpot because Zendesk per-ticket avg ~7 history rows (low) vs HubSpot contacts ~65 (high), but the win compounds for any future engagement-heavy entity. |

## 14. Property meaning — read the Glossary

Same principle as HubSpot: Zendesk's `title` field on ticket_fields doesn't always carry the operational meaning. Read the tenant's `docs/tenants/<tenant_uuid>/GLOSSARY.md` before querying. See [`PROPERTY-GLOSSARY-PATTERN.md`](PROPERTY-GLOSSARY-PATTERN.md).

## 15. Cross-references

- [`CONNECTOR-AUTHORING-GUIDE.md`](CONNECTOR-AUTHORING-GUIDE.md) — generic Protocol contract
- [`HUBSPOT-CONNECTOR-GUIDE.md`](HUBSPOT-CONNECTOR-GUIDE.md) — sibling guide
- [`ONBOARDING-A-NEW-TENANT.md`](ONBOARDING-A-NEW-TENANT.md) — per-tenant discovery + onboarding
- [`PROPERTY-GLOSSARY-PATTERN.md`](PROPERTY-GLOSSARY-PATTERN.md) — tenant property glossary
- [`SYNC-ORCHESTRATOR-GUIDE.md`](SYNC-ORCHESTRATOR-GUIDE.md) — orchestrator run-loop, advisory locks
- Zendesk API docs: https://developer.zendesk.com/api-reference/
- Zendesk incremental exports: https://developer.zendesk.com/documentation/ticketing/managing-tickets/using-the-incremental-export-api/
