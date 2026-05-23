---
id: CIP-SPEC-003
uuid: 9ffcdbf2-1ff5-4e2a-9fa6-f7ad604fcd7c
title: 'CIP Architecture — Phase 0: Data Model & Tenant Architecture'
type: spec
owner: tim
solve_for: Authoritative architecture spec — components, data flow, RLS pattern, lens
  engine, SCD-2 persister, four-paths consumption.
stage_label: trial
domain: eng
version: '1.0'
created: '2026-04-13'
last_modified: '2026-04-17'
last_reviewed: '2026-05-19'
review_cadence: 180
project_id: client-intelligence-platform
pm_project_id: 596825db-61bc-4899-bc6c-e207489ca35d
phase: 0
connects_to:
- docs/architecture/principles/DESIGN-PRINCIPLES.md#p-21
- docs/DECISION-LOG.md#d-117
- docs/DECISION-LOG.md#d-118
- docs/DECISION-LOG.md#d-119
- docs/DECISION-LOG.md#d-120
- docs/DECISION-LOG.md#d-121
- docs/subsystems/integration/CONTRACT.md
- docs/subsystems/knowledge/CONTRACT.md
- docs/subsystems/graph/CONTRACT.md
- docs/subsystems/memory/CONTRACT.md
- docs/subsystems/storage/CONTRACT.md
doc_type: architecture
status: active
---
# CIP Architecture — Phase 0: Data Model & Tenant Architecture

> **Scope:** This document covers the foundational architecture decisions for the Foundry Client Intelligence Platform. Every subsequent phase (connectors, pipelines, dashboards, chatbot, anomaly detection) builds on top of what is defined here.
>
> **Source of truth:** VISION.md defines WHAT CIP does. This document defines HOW.
>
> **2026-04-17 hardening pass:** Capability pillars locked as 8 durable PM scopes (D-117). Connector framework home committed (D-118). Derived knowledge strategy committed (D-119). Three-data-layer model made explicit (D-120). Discoverability baseline locked (D-121). Platform-wide multi-lens principle recorded as P-21.

---

## 1. Database Location

### Decision: Shared Foundry PostgreSQL, `cip_` Prefixed Tables

CIP tables live in the existing Foundry PostgreSQL instance on Railway alongside PM, agent, and other system tables. All CIP tables use a `cip_` prefix for clear namespace separation.

**Why shared:**

- Operational simplicity at current scale (10-50 tenants). One backup, one connection pool, one set of migrations.
- Foundry already runs PM, agents, knowledge, and governance in this database. CIP is another product — same deployment model.
- No cross-database joins needed; CIP can reference existing `tenants` and `users` tables directly.

**Why `cip_` prefix (not a separate PostgreSQL schema):**

- `cip_contacts` is grep-friendly, visible in any SQL client without schema qualification.
- Avoids `SET search_path` complexity with SQLAlchemy and connection pooling.
- Alembic migrations stay in a single migration chain — no multi-schema orchestration.
- The prefix makes extraction clean when CIP graduates to Stage 3 (standalone service): find all `cip_*` tables, move them.

**Stage 3 extraction path:** When CIP becomes a standalone deployable product, the `cip_` tables migrate to a dedicated database. The prefix ensures no table name collisions during migration. Application code already uses SQLAlchemy models with explicit table names, so the code change is just a connection string swap. Plan for this now; execute it later.

**What we reuse from the existing database:**

| Existing Table/Entity | CIP Uses It For |
|----------------------|-----------------|
| `tenants` (if exists) or PM tenant registry | Venture identity, parent-child hierarchy |
| `users` / actor registry | View ownership, access control |
| Alembic migration chain | Schema versioning |

---

## 2. Tenant & View Model

### Decision: Three-Level Scoping — tenant_id + client_id + Views

CIP serves a hierarchy: Foundry (super-tenant) operates ventures, ventures serve clients, and different teams within a venture see different slices of client data. This requires three distinct scoping mechanisms.

### 2a. Level 1: Venture Tenant (`tenant_id`)

Every CIP record has a `tenant_id` column (UUID, NOT NULL) identifying which venture owns the data. This satisfies D-026 (all queries scoped by tenant_id).

Venture tenants map to the existing PM system tenants:

| Venture | tenant_id | Role |
|---------|-----------|------|
| Project Silk | `078a37d6-6ae2-4e22-869e-cc08f6cb2787` | Consulting venture — CS, marketing |
| EcomLever | `dec814db-722a-4730-8e60-51afc4a5dad9` | E-commerce consulting |
| Rocky Ridge | `80252ad9-72d5-4c5a-b273-af804224872e` | Land management |
| Bob | `f554c334-43e5-458e-9857-0b268f8f99bf` | Bob platform |
| Foundry | `4ebafb2d-01ba-434a-ac73-ea9603e7d0bb` | Super-tenant (sees everything) |

### 2b. Level 2: Client (`client_id`)

Within a venture, data is further scoped by client. A `client_id` column (UUID, NOT NULL) identifies which client the record belongs to.

```sql
CREATE TABLE cip_clients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,  -- which venture this client belongs to
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL,   -- kebab-case, unique per tenant
    industry        TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, slug)
);

CREATE INDEX idx_cip_clients_tenant ON cip_clients(tenant_id);
```

**The Wayward case:** Wayward is a single client whose data is ingested once. Both Project Silk and EcomLever reference the same client record. The data rows carry the `client_id` for Wayward — the *venture* accessing the data determines what filter is applied (Level 3).

### 2c. Level 3: Views (Filter Configurations)

Views solve the "one dataset, multiple lenses" requirement. A view is a saved filter definition — not a materialized copy of data, not a PostgreSQL view, but an application-level configuration that determines what subset of client data a user/team sees.

```sql
CREATE TABLE cip_views (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    client_id       UUID NOT NULL REFERENCES cip_clients(id),
    name            TEXT NOT NULL,        -- "Project Silk China View"
    description     TEXT,
    filter_config   JSONB NOT NULL,       -- the filter definition
    owner_type      TEXT NOT NULL,        -- 'team', 'user', 'role'
    owner_id        TEXT NOT NULL,        -- team/user/role identifier
    is_default      BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_cip_views_tenant_client ON cip_views(tenant_id, client_id);
```

**`filter_config` schema:**

```json
{
    "description": "Project Silk staff — Chinese brand tickets only",
    "filters": [
        {"field": "tags", "op": "contains", "value": "chinese"},
        {"field": "source_connector", "op": "eq", "value": "zendesk"}
    ],
    "exclude_fields": ["internal_notes", "billing_details"],
    "freshness_override": null
}
```

**How views work at query time:** Application code loads the view config, translates filters to SQL WHERE clauses, and appends them to the base query (which is already scoped by `tenant_id` and `client_id`). Views never bypass tenant isolation — they only narrow within it.

**Reference implementations:**

| View | Venture | Client | Filter |
|------|---------|--------|--------|
| PS China View | Project Silk | Wayward | `tags contains 'chinese'` |
| EcomLever Full | EcomLever | Wayward | No filter (sees everything) |
| RR Staff View | Rocky Ridge | Rocky Ridge | No filter (single-client venture) |
| Ali Dashboard | EcomLever | Wayward | `type in ('ticket_metric', 'billing')` |

### 2d. Tenant Isolation: RLS + Middleware

**Primary enforcement: Application middleware.** Every database session sets tenant context before executing any query:

```python
# SQLAlchemy session setup
async def set_tenant_context(session: AsyncSession, tenant_id: str):
    await session.execute(
        text("SET LOCAL app.current_tenant_id = :tid"),
        {"tid": tenant_id}
    )
```

This matches the existing Foundry D-026 pattern. All CIP queries include `WHERE tenant_id = :tenant_id` via SQLAlchemy query construction.

**Secondary enforcement: PostgreSQL RLS.** Defense-in-depth. Even if application code has a bug, the database itself prevents cross-tenant data access:

```sql
ALTER TABLE cip_contacts ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_policy ON cip_contacts
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

Applied to all `cip_*` data tables. NOT applied to `cip_views` or `cip_connectors` (admin tables that Foundry super-tenant manages across ventures).

**RLS gotchas addressed:**

- CVE-2024-10976: Mitigated by `SET LOCAL` (transaction-scoped, not session-scoped). Context cannot leak between requests.
- Connection pooling: `SET LOCAL` resets at transaction end, so pooled connections don't carry stale tenant context.
- Superuser bypass: Application connects with a non-superuser role. RLS is tested with the application role, never `postgres`.
- Performance: `tenant_id` is the leading column in all composite indexes, so RLS policy evaluation uses index scans.

**Cross-tenant aggregation (Foundry super-tenant):** Uses SECURITY DEFINER functions that bypass RLS to run aggregate queries (counts, percentages, distributions) across tenants. Individual records are never exposed — only anonymized patterns.

```sql
CREATE FUNCTION cip_cross_tenant_ticket_distribution()
RETURNS TABLE(category TEXT, tenant_count BIGINT, avg_volume NUMERIC)
SECURITY DEFINER
AS $$
    SELECT category, COUNT(DISTINCT tenant_id), AVG(ticket_count)
    FROM cip_ticket_summaries
    GROUP BY category;
$$ LANGUAGE SQL STABLE;
```

---

## 3. Provenance Columns

### Decision: 9 Columns on Every CIP Data Table

Every record in CIP carries its full provenance — where it came from, when, how fresh it is, and what it replaced. This is a Day 1 requirement (VISION.md §7a) driven by CEO-level traceability needs and EU AI Act compliance (Articles 12-13, enforcement August 2026).

### Column Definitions

| Column | Type | Nullable | Purpose |
|--------|------|----------|---------|
| `tenant_id` | UUID | NOT NULL | Venture isolation (D-026) |
| `client_id` | UUID | NOT NULL | Client scoping within venture |
| `source_connector` | TEXT | NOT NULL | Which connector pulled this record (enum: `zendesk`, `hubspot`, `shopify`, `manual`, `agent`, etc.) |
| `source_id` | TEXT | NOT NULL | The external system's ID for this record (e.g., Zendesk ticket ID, HubSpot contact vid) |
| `ingested_at` | TIMESTAMPTZ | NOT NULL | When this record was first pulled into CIP |
| `refreshed_at` | TIMESTAMPTZ | NOT NULL | When this record was last updated from the source (equals `ingested_at` on first pull) |
| `previous_version_id` | UUID | NULL | Points to the prior version of this record in the history table (NULL for first version) |
| `ingestion_batch_id` | UUID | NOT NULL | Groups all records from a single connector run — enables batch-level rollback and debugging |
| `authority` | TEXT | NOT NULL DEFAULT 'validated' | Trust level of this data. Enum: `validated` (human-entered or source-of-truth API), `agent_discovered` (agent-written), `pending_review` (needs human check), `retracted` (known bad), `superseded` (replaced by newer record). Matches existing knowledge contract (VISION.md §7f). |

### Composite Indexes

```sql
-- Primary query pattern: all records for a tenant + client
CREATE INDEX idx_cip_{table}_tenant_client ON cip_{table}(tenant_id, client_id);

-- Provenance lookups: find all records from a specific source
CREATE INDEX idx_cip_{table}_source ON cip_{table}(source_connector, source_id);

-- Freshness queries: most recently refreshed first
CREATE INDEX idx_cip_{table}_freshness ON cip_{table}(tenant_id, client_id, refreshed_at DESC);

-- Batch operations: find all records from a specific ingestion run
CREATE INDEX idx_cip_{table}_batch ON cip_{table}(ingestion_batch_id);
```

### Unique Constraint: Source Deduplication

```sql
-- A record from a specific source should only exist once per tenant+client
ALTER TABLE cip_{table}
    ADD CONSTRAINT uq_cip_{table}_source
    UNIQUE (tenant_id, client_id, source_connector, source_id);
```

This prevents duplicate imports. On conflict (re-pull of same record), the application UPSERTs: update `refreshed_at`, compare fields, write old version to history if anything changed.

### EU AI Act Compliance Notes

Articles 12-13 require logging sufficient to identify malfunctions and performance drift in AI systems. For CIP, this means:

- Every recommendation an agent makes can be traced to the specific records it was based on (via `source_connector` + `source_id` + `refreshed_at`).
- If a record is later `retracted` or `superseded`, the audit trail shows what the system "believed" at any historical point.
- The `authority` field distinguishes human-validated facts from agent-inferred knowledge — critical when AI output is used for business decisions.

---

## 4. Temporal Versioning

### Decision: SCD Type 2 with History Tables (Design Now, Build Phase 2+)

### Pattern

Main tables (`cip_contacts`, `cip_tickets`, etc.) hold **current state only** — optimized for fast reads, simple joins, dashboard queries.

History tables (`cip_contacts_history`, `cip_tickets_history`, etc.) hold **all prior versions** with temporal bounds — optimized for audit trails and point-in-time queries.

### History Table Schema (Template)

```sql
CREATE TABLE cip_contacts_history (
    history_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id       UUID NOT NULL,      -- FK to main table's id
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_to        TIMESTAMPTZ,         -- NULL = was current until superseded
    changed_by      TEXT NOT NULL,        -- connector ID, user ID, or agent ID
    change_reason   TEXT,                 -- 'connector_refresh', 'manual_edit', 'agent_update'

    -- All columns from the main table are duplicated here
    -- (tenant_id, client_id, source_connector, source_id, ... all domain fields)

    CONSTRAINT valid_range CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE INDEX idx_cip_contacts_history_record ON cip_contacts_history(record_id);
CREATE INDEX idx_cip_contacts_history_temporal ON cip_contacts_history(record_id, valid_from, valid_to);
```

### Point-in-Time Query

```sql
-- What did we know about contact X on March 15?
SELECT * FROM cip_contacts_history
WHERE record_id = :contact_id
  AND tenant_id = :tenant_id
  AND valid_from <= '2026-03-15 00:00:00'
  AND (valid_to IS NULL OR valid_to > '2026-03-15 00:00:00');
```

### Trigger Mechanism (Phase 2+ Implementation)

```sql
CREATE OR REPLACE FUNCTION cip_archive_on_update()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO cip_contacts_history (
        record_id, valid_from, valid_to, changed_by, change_reason,
        -- all domain columns from OLD
    ) VALUES (
        OLD.id, OLD.refreshed_at, now(), current_setting('app.current_actor_id', true), 'connector_refresh',
        -- all domain values from OLD
    );

    -- Link the chain
    NEW.previous_version_id = (SELECT history_id FROM cip_contacts_history
                                WHERE record_id = OLD.id ORDER BY valid_from DESC LIMIT 1);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

### Implementation Timing: Phase 1 (Active from First Sync)

History tables and triggers ship in Phase 1 alongside the connector framework. They are active from the very first data sync.

**Why Phase 1, not Phase 2:** Month-over-month comparisons (e.g., last month's HubSpot billings vs this month) require historical baselines from the moment data starts flowing. If history capture is deferred, there's no prior state to compare against. The first full sync creates the baseline; every subsequent incremental sync archives changed records. By month two, the first comparison window is available.

**Write overhead:** Only changed records are archived — not the full dataset on each sync. For a Wayward-scale dataset (153K records), this adds ~10-20% to sync time. At current scale, the overhead is seconds, not minutes.

**Migration plan:** History tables are created in migration `cip_08_history_tables.py` and triggers attached immediately. No separate activation step.

---

## 5. Freshness Scoring

### Decision: Exponential Decay, Configurable Half-Life, Query-Time Computation

### Formula

```
freshness_score = 100 * 0.5 ^ (days_since_refresh / half_life)
```

Where `days_since_refresh = EXTRACT(EPOCH FROM (now() - refreshed_at)) / 86400`.

### Half-Life Configuration

| Entity Type | Half-Life (days) | Rationale |
|-------------|-----------------|-----------|
| Tickets | 7 | Support issues are urgent; week-old tickets are historical |
| Contacts | 30 | Contact info changes slowly |
| Deals / Pipeline | 14 | Deal stages move; two-week-old pipeline data is suspect |
| Call Notes | 21 | Recent calls matter most for relationship context |
| Documents / SOPs | 90 | Policies and procedures change infrequently |
| Financial Data | 1 | Stock/financial data stales immediately (stock venture) |

Half-lives are stored in a configuration table, not hardcoded:

```sql
CREATE TABLE cip_freshness_config (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type     TEXT NOT NULL UNIQUE,  -- 'ticket', 'contact', 'deal', etc.
    half_life_days  NUMERIC NOT NULL,
    weight          NUMERIC NOT NULL DEFAULT 0.3,  -- blend weight in combined scoring
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Query-Time Computation

Freshness is NOT stored as a column — it's computed at query time so it's always accurate:

```sql
SELECT *,
    100 * POWER(0.5, EXTRACT(EPOCH FROM (now() - refreshed_at)) / 86400.0 / :half_life) AS freshness_score
FROM cip_tickets
WHERE tenant_id = :tenant_id AND client_id = :client_id
ORDER BY freshness_score DESC;
```

### Blended Scoring (for search/retrieval)

When CIP queries combine relevance and freshness (e.g., agent RAG context, chatbot answers):

```
result_score = (relevance_weight * relevance) + (freshness_weight * freshness_score / 100)
```

Default weights: `relevance_weight = 0.7`, `freshness_weight = 0.3`. This matches the existing memory service's RRF fusion pattern. Weights are configurable per view.

### Performance Note

At 1M rows, the `POWER()` computation adds <1ms to query time — it's a scalar function on an indexed timestamp column. If performance becomes an issue at 10M+ rows, we add a materialized view refreshed hourly. For now, query-time is correct and simple.

---

## 6. Core Table Schemas

### 6a. Entity Tables

All entity tables share the 9 provenance columns defined in §3 plus entity-specific domain columns.

#### cip_contacts

```sql
CREATE TABLE cip_contacts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Provenance (§3)
    tenant_id           UUID NOT NULL,
    client_id           UUID NOT NULL REFERENCES cip_clients(id),
    source_connector    TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    refreshed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    previous_version_id UUID,
    ingestion_batch_id  UUID NOT NULL,
    authority           TEXT NOT NULL DEFAULT 'validated',

    -- Domain
    email               TEXT,
    phone               TEXT,
    first_name          TEXT,
    last_name           TEXT,
    company_name        TEXT,
    company_id          UUID,             -- FK to cip_companies if linked
    title               TEXT,
    country             TEXT,
    city                TEXT,
    tags                TEXT[] DEFAULT '{}',
    lifecycle_stage     TEXT,              -- lead, customer, subscriber, etc.
    properties          JSONB DEFAULT '{}', -- overflow for source-specific fields

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_cip_contacts_source UNIQUE (tenant_id, client_id, source_connector, source_id)
);

CREATE INDEX idx_cip_contacts_tenant_client ON cip_contacts(tenant_id, client_id);
CREATE INDEX idx_cip_contacts_email ON cip_contacts(tenant_id, email);
CREATE INDEX idx_cip_contacts_company ON cip_contacts(tenant_id, company_id);
CREATE INDEX idx_cip_contacts_freshness ON cip_contacts(tenant_id, client_id, refreshed_at DESC);
CREATE INDEX idx_cip_contacts_tags ON cip_contacts USING GIN(tags);
```

#### cip_companies

```sql
CREATE TABLE cip_companies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Provenance (§3)
    tenant_id           UUID NOT NULL,
    client_id           UUID NOT NULL REFERENCES cip_clients(id),
    source_connector    TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    refreshed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    previous_version_id UUID,
    ingestion_batch_id  UUID NOT NULL,
    authority           TEXT NOT NULL DEFAULT 'validated',

    -- Domain
    name                TEXT NOT NULL,
    domain              TEXT,
    industry            TEXT,
    country             TEXT,
    city                TEXT,
    employee_count      INTEGER,
    annual_revenue      NUMERIC,
    tags                TEXT[] DEFAULT '{}',
    properties          JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_cip_companies_source UNIQUE (tenant_id, client_id, source_connector, source_id)
);

CREATE INDEX idx_cip_companies_tenant_client ON cip_companies(tenant_id, client_id);
CREATE INDEX idx_cip_companies_name ON cip_companies(tenant_id, name);
CREATE INDEX idx_cip_companies_tags ON cip_companies USING GIN(tags);
```

#### cip_tickets

```sql
CREATE TABLE cip_tickets (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Provenance (§3)
    tenant_id           UUID NOT NULL,
    client_id           UUID NOT NULL REFERENCES cip_clients(id),
    source_connector    TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    refreshed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    previous_version_id UUID,
    ingestion_batch_id  UUID NOT NULL,
    authority           TEXT NOT NULL DEFAULT 'validated',

    -- Domain
    subject             TEXT,
    description         TEXT,
    status              TEXT,              -- open, pending, solved, closed
    priority            TEXT,              -- low, normal, high, urgent
    ticket_type         TEXT,              -- question, incident, problem, task
    requester_id        UUID,              -- FK to cip_contacts if linked
    requester_email     TEXT,
    assignee_name       TEXT,
    group_name          TEXT,
    tags                TEXT[] DEFAULT '{}',
    channel             TEXT,              -- email, chat, phone, web
    satisfaction_rating TEXT,
    first_response_at   TIMESTAMPTZ,
    resolved_at         TIMESTAMPTZ,
    source_created_at   TIMESTAMPTZ,       -- when created in the source system
    source_updated_at   TIMESTAMPTZ,
    properties          JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_cip_tickets_source UNIQUE (tenant_id, client_id, source_connector, source_id)
);

CREATE INDEX idx_cip_tickets_tenant_client ON cip_tickets(tenant_id, client_id);
CREATE INDEX idx_cip_tickets_status ON cip_tickets(tenant_id, client_id, status);
CREATE INDEX idx_cip_tickets_freshness ON cip_tickets(tenant_id, client_id, refreshed_at DESC);
CREATE INDEX idx_cip_tickets_tags ON cip_tickets USING GIN(tags);
CREATE INDEX idx_cip_tickets_source_dates ON cip_tickets(tenant_id, source_created_at DESC);
```

#### cip_deals

```sql
CREATE TABLE cip_deals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Provenance (§3)
    tenant_id           UUID NOT NULL,
    client_id           UUID NOT NULL REFERENCES cip_clients(id),
    source_connector    TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    refreshed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    previous_version_id UUID,
    ingestion_batch_id  UUID NOT NULL,
    authority           TEXT NOT NULL DEFAULT 'validated',

    -- Domain
    name                TEXT,
    stage               TEXT,              -- pipeline stage
    amount              NUMERIC,
    currency            TEXT DEFAULT 'USD',
    close_date          DATE,
    company_id          UUID,              -- FK to cip_companies
    contact_id          UUID,              -- FK to cip_contacts
    pipeline            TEXT,
    probability         NUMERIC,
    tags                TEXT[] DEFAULT '{}',
    properties          JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_cip_deals_source UNIQUE (tenant_id, client_id, source_connector, source_id)
);

CREATE INDEX idx_cip_deals_tenant_client ON cip_deals(tenant_id, client_id);
CREATE INDEX idx_cip_deals_pipeline ON cip_deals(tenant_id, client_id, stage);
CREATE INDEX idx_cip_deals_amount ON cip_deals(tenant_id, amount DESC);
```

#### cip_call_notes

```sql
CREATE TABLE cip_call_notes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Provenance (§3)
    tenant_id           UUID NOT NULL,
    client_id           UUID NOT NULL REFERENCES cip_clients(id),
    source_connector    TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    refreshed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    previous_version_id UUID,
    ingestion_batch_id  UUID NOT NULL,
    authority           TEXT NOT NULL DEFAULT 'validated',

    -- Domain
    subject             TEXT,
    body                TEXT,              -- full transcript or note content
    note_type           TEXT,              -- call, meeting, email, note
    contact_id          UUID,              -- FK to cip_contacts
    company_id          UUID,              -- FK to cip_companies
    deal_id             UUID,              -- FK to cip_deals
    participants        TEXT[],
    duration_seconds    INTEGER,
    source_created_at   TIMESTAMPTZ,
    tags                TEXT[] DEFAULT '{}',
    properties          JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_cip_call_notes_source UNIQUE (tenant_id, client_id, source_connector, source_id)
);

CREATE INDEX idx_cip_call_notes_tenant_client ON cip_call_notes(tenant_id, client_id);
CREATE INDEX idx_cip_call_notes_contact ON cip_call_notes(tenant_id, contact_id);
CREATE INDEX idx_cip_call_notes_date ON cip_call_notes(tenant_id, source_created_at DESC);
```

### 6b. Infrastructure Tables

#### cip_connectors (Connector Type Registry)

```sql
CREATE TABLE cip_connectors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,    -- 'zendesk', 'hubspot', 'shopify'
    display_name    TEXT NOT NULL,           -- 'Zendesk', 'HubSpot', 'Shopify'
    auth_type       TEXT NOT NULL,           -- 'api_key', 'oauth2', 'token'
    base_url        TEXT,
    streams         JSONB NOT NULL,          -- available data streams and their schemas
    rate_limits     JSONB,                   -- default rate limit config
    status          TEXT NOT NULL DEFAULT 'active',  -- 'active', 'beta', 'deprecated'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### cip_connector_configs (Per-Tenant Connector Instances)

```sql
CREATE TABLE cip_connector_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    client_id       UUID NOT NULL REFERENCES cip_clients(id),
    connector_id    UUID NOT NULL REFERENCES cip_connectors(id),
    credentials     JSONB NOT NULL,         -- encrypted at rest; API keys, OAuth tokens
    sync_schedule   TEXT,                   -- cron expression: '0 2 * * *' (daily at 2am)
    sync_mode       TEXT NOT NULL DEFAULT 'incremental',  -- 'full', 'incremental'
    last_sync_at    TIMESTAMPTZ,
    last_sync_status TEXT,                  -- 'success', 'partial', 'failed'
    config          JSONB DEFAULT '{}',     -- connector-specific settings
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (tenant_id, client_id, connector_id)
);

CREATE INDEX idx_cip_connector_configs_tenant ON cip_connector_configs(tenant_id);
```

#### cip_sync_runs (Ingestion Audit Log)

```sql
CREATE TABLE cip_sync_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_id       UUID NOT NULL REFERENCES cip_connector_configs(id),
    tenant_id       UUID NOT NULL,
    client_id       UUID NOT NULL,
    connector_name  TEXT NOT NULL,
    batch_id        UUID NOT NULL UNIQUE,   -- matches ingestion_batch_id on data records
    sync_mode       TEXT NOT NULL,           -- 'full' or 'incremental'
    status          TEXT NOT NULL,           -- 'running', 'success', 'partial', 'failed'
    records_pulled  INTEGER DEFAULT 0,
    records_created INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_skipped INTEGER DEFAULT 0,
    error_log       JSONB,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    cursor_state    JSONB,                  -- bookmark for incremental sync resume
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX idx_cip_sync_runs_tenant ON cip_sync_runs(tenant_id, client_id);
CREATE INDEX idx_cip_sync_runs_config ON cip_sync_runs(config_id, started_at DESC);
CREATE INDEX idx_cip_sync_runs_batch ON cip_sync_runs(batch_id);
```

---

## 7. Connector Interface Contract

### Decision: Python Protocol, Normalize Separate from Connector

Phase 0 defines the interface. Phase 1 implements it and refactors existing Zendesk/HubSpot scripts to comply.

### Interface Definition

```python
from typing import Protocol, Iterator, Any
from datetime import datetime

class CIPConnector(Protocol):
    """Standard interface for all CIP data connectors."""

    name: str               # 'zendesk', 'hubspot', 'shopify'
    auth_type: str          # 'api_key', 'oauth2', 'token'

    def authenticate(self, config: dict) -> bool:
        """Validate credentials and establish connection.
        Returns True if auth succeeds, raises ConnectorAuthError otherwise."""
        ...

    def discover_schema(self) -> dict:
        """Return available streams and their schemas.
        Format: {
            "streams": [
                {
                    "name": "tickets",
                    "schema": {"id": "string", "subject": "string", ...},
                    "key_property": "id",
                    "bookmark_property": "updated_at",
                    "supports_incremental": True
                }
            ]
        }"""
        ...

    def pull_full(self, stream: str) -> Iterator[dict]:
        """Full extraction of a stream. Handles pagination and rate limiting internally.
        Yields raw records as dicts."""
        ...

    def pull_incremental(self, stream: str, since: datetime, cursor_state: dict | None = None) -> Iterator[dict]:
        """Incremental extraction since a timestamp or cursor.
        Yields raw records. Updates cursor_state in-place for resume."""
        ...

    def get_rate_limits(self) -> dict:
        """Return rate limit config for this connector.
        Format: {"requests_per_minute": 200, "concurrent_requests": 4, "retry_after_header": True}"""
        ...

    def health_check(self) -> dict:
        """Quick connectivity check. Returns {"healthy": True/False, "message": "..."}"""
        ...
```

### Normalization Layer (Separate from Connector)

Normalization is NOT in the connector — it's a separate mapper layer. Connectors output raw records from the source API. Mappers transform raw records into CIP standard schemas.

**Why separate:**

- A Zendesk connector should not need to know about `cip_contacts` schema — it just pulls Zendesk data.
- Multiple connectors can map to the same CIP entity (Zendesk user → cip_contact, HubSpot contact → cip_contact).
- Mapping rules change independently of connector logic (new CIP field doesn't require connector code change).
- Mappers are testable in isolation with fixture data.

```python
class CIPMapper(Protocol):
    """Maps raw connector records to CIP entity schema."""

    source_connector: str   # 'zendesk'
    target_entity: str      # 'contact', 'ticket', 'company'

    def map(self, raw_record: dict) -> dict:
        """Transform a raw source record into a CIP entity dict.
        Output must include all provenance fields except tenant_id, client_id,
        and ingestion_batch_id (which are set by the ingestion framework)."""
        ...

    def get_field_mapping(self) -> dict:
        """Return the field mapping config for documentation/UI.
        Format: {"source_field": "target_field", ...}"""
        ...
```

**Example mapper:**

```python
class ZendeskToContactMapper:
    source_connector = "zendesk"
    target_entity = "contact"

    def map(self, raw: dict) -> dict:
        return {
            "source_connector": "zendesk",
            "source_id": str(raw["id"]),
            "email": raw.get("email"),
            "first_name": raw.get("name", "").split(" ")[0] if raw.get("name") else None,
            "last_name": " ".join(raw.get("name", "").split(" ")[1:]) if raw.get("name") else None,
            "phone": raw.get("phone"),
            "tags": raw.get("tags", []),
            "properties": {k: v for k, v in raw.items() if k not in MAPPED_FIELDS},
        }
```

### Ingestion Pipeline Flow

```
Connector.pull_incremental()
    → yields raw records
        → Mapper.map(raw_record)
            → adds provenance fields (tenant_id, client_id, batch_id set by framework)
                → UPSERT into cip_{entity} table
                    → ON CONFLICT (tenant_id, client_id, source_connector, source_id):
                        UPDATE refreshed_at, compare fields, archive old if changed
```

---

## 8. Metabase Integration Notes

Metabase is already deployed at `reports.project-silk.com`. CIP schema decisions affect Metabase directly.

**What matters now (Phase 0):**

- Table names must be human-readable. `cip_contacts` is fine; `cip_ct_v2_raw` is not. Metabase auto-generates column labels from table/column names.
- All FK relationships must be explicit (not just convention). Metabase auto-detects FKs for join suggestions.
- The `tags` column (TEXT[]) works with Metabase's array support for filtering. GIN indexes ensure performance.
- `JSONB` columns (`properties`, `filter_config`) are queryable in Metabase via custom SQL, but NOT via the visual editor. Domain-critical fields must be first-class columns, not buried in JSONB.
- Row-level security for embedded dashboards: Metabase supports parameterized embedding where `tenant_id` is injected by the embedding app. The CIP schema's `tenant_id` on every table maps directly to this pattern.

---

## 9. Entity Relationship Diagram

```
                    cip_connectors
                         │
                         │ 1:N
                         ▼
cip_clients ◄──── cip_connector_configs ────► cip_sync_runs
    │                                              │
    │ 1:N                                          │ batch_id
    ▼                                              ▼
┌─────────────────────────────────────────────────────────┐
│                   CIP Entity Tables                      │
│                                                          │
│  cip_contacts ◄────► cip_companies                      │
│       │                    │                             │
│       │ N:1                │ N:1                         │
│       ▼                    ▼                             │
│  cip_tickets          cip_deals                         │
│       │                    │                             │
│       │                    │                             │
│       └───────► cip_call_notes ◄────────┘               │
│                                                          │
│  All tables share: tenant_id, client_id, 9 provenance   │
│  columns, UPSERT on (tenant, client, source, source_id) │
└─────────────────────────────────────────────────────────┘
         │
         │ filtered by
         ▼
    cip_views ──► Application-level filter configs
                  (not PostgreSQL views)

    cip_freshness_config ──► Query-time decay parameters
```

---

## 10. Architecture Decisions — LOCKED (2026-04-13)

All 6 decisions approved by Tim during Cowork session. These are now locked for Phase 1 implementation.

| # | Decision | Resolution | Notes |
|---|----------|-----------|-------|
| 1 | **Database location** | Shared Foundry PostgreSQL, `cip_` prefix | Extract to dedicated DB at Stage 3 |
| 2 | **Client table** | Own `cip_clients` table, separate from PM tenants | Ventures = owners, clients = subjects. Different concepts. |
| 3 | **Credentials encryption** | Railway disk-level encryption for Stage 1 | App-level encryption (AES-256) deferred to Stage 2/3 when external customers onboard |
| 4 | **JSONB `properties` overflow** | Keep it. Real columns for dashboardable fields, JSONB for the rest | Promote frequently-queried JSONB fields to columns via migration as patterns emerge |
| 5 | **History tables** | Active from Phase 1, first sync | Month-over-month comparisons (e.g., billing) require baselines from day one. Cannot defer. |
| 6 | **Authority enum** | 5 levels, manual entries = `validated` | `source_connector = 'manual'` distinguishes human-entered data. Authority tracks trust, not origin. |

---

## Appendix A: Migration File Naming

CIP migrations follow the existing Alembic chain. Naming convention:

```
cip_01_base_tables.py          — clients, connectors, connector_configs, sync_runs, views, freshness_config
cip_02_entity_contacts.py      — cip_contacts + indexes
cip_03_entity_companies.py     — cip_companies + indexes
cip_04_entity_tickets.py       — cip_tickets + indexes
cip_05_entity_deals.py         — cip_deals + indexes
cip_06_entity_call_notes.py    — cip_call_notes + indexes
cip_07_rls_policies.py         — RLS on all entity tables
cip_08_history_tables.py       — (Phase 2) history tables + triggers
```

## Appendix B: Existing Wayward Data Mapping

Reference for Phase 1 connector development. Maps the existing proof-of-concept SQLite fields to CIP schema.

| Wayward SQLite Table | CIP Table | Record Count | Key Fields |
|---------------------|-----------|-------------|------------|
| zendesk_tickets | cip_tickets | 1,281 | id, subject, status, priority, tags, requester_id |
| zendesk_users | cip_contacts | 18,709 | id, name, email, phone, organization_id |
| zendesk_comments | (embedded in cip_tickets.properties or separate table TBD) | 5,214 | ticket_id, author_id, body |
| hubspot_contacts | cip_contacts | 45,687 | vid, email, firstname, lastname, company |
| hubspot_companies | cip_companies | 65,029 | companyId, name, domain, industry |
| hubspot_deals | cip_deals | 2,934 | dealId, dealname, amount, dealstage |
| hubspot_notes | cip_call_notes | 4,734 (1,662 Firefly) | hs_note_body, hs_timestamp, associations |

**Identity resolution note:** Zendesk users and HubSpot contacts both map to `cip_contacts`. Dedup by email address across sources. The `source_connector` + `source_id` unique constraint allows multiple source records per real person — identity resolution (merging them) is a Phase 2+ concern.

---

## 13. Capability Pillars — The Durable CIP Shape (D-117)

CIP is structured as **eight capability pillars** — durable work slices that describe what CIP *is*, independent of when things ship. Phases (what ships *when*) are tracked as a separate dimension (tags, milestone records, or parent-project links — TBD).

This shape is informed by industry reference architectures for long-lived data platforms (AWS, Databricks, Oracle all describe ingestion → storage → governance → consumption as pillars) plus CIP-specific needs (multi-lens filtering, push/sync, agent-native access).

| # | Pillar | Scope | Lives forever? |
|---|--------|-------|----------------|
| 1 | **Ingestion & Connectors** | External source pulls; connector framework (built inside Integration Mesh platform service — see §14); auth, rate limits, incremental sync; mapping to normalized schema | Yes — always adding sources |
| 2 | **Structured Store** | Postgres schema (cip_* tables), SCD Type 2 history, 9 provenance columns (D-026 + authority + lineage), freshness computation, `cip_files` metadata registry linking originals → derived chunks | Yes — always adding entities |
| 3 | **Unstructured Store** | Derived knowledge — RAG chunks via Knowledge Subsystem + GraphRAG entities/relationships via Graph Subsystem. No new retrieval infra built; we consume what exists (see §15) | Yes — always adding content types |
| 4 | **Lens Engine** | Multi-view filtering — `cip_views` table, `filter_config` JSONB, lens resolution, RLS policies. First-class home for the multi-lens principle (P-21) | Yes — always adding lenses |
| 5 | **Consumption Surfaces** | Dashboards (Metabase), REST API, chatbots, agent MCP tools, scheduled reports, white-label partner portals | Yes — always adding surfaces |
| 6 | **Push & Sync** | Outbound delivery to Chatwoot, partner CRMs (e.g., Project Silk Twenty), client Google Drive folders, partner portals, downstream systems | Yes — always adding destinations |
| 7 | **Intelligence & Alerts** | Anomaly detection, freshness scoring, proactive signals, investigative agents (cross-client and single-client) | Yes — always adding detectors |
| 8 | **Access & Operations** | Tenant isolation (RLS + SET LOCAL), access control, sync-run health, observability, technical-health budget (20-30% of capacity per industry norm) | Yes — the technical-health pillar |

**What this replaces:** The prior 8 scopes mixed phases and capabilities (e.g., "Vision & Architecture Lock" was a one-time gate; "Wayward v1 (First Tenant)" was a release phase). Old PM scopes are marked superseded; new scope_ids track these 8 pillars.

---

## 14. Ingestion & Connectors — Lives Inside Integration Mesh (D-118)

CIP's connector framework is built **inside the Integration Mesh platform service**, not as a CIP-internal module. Rationale:

- Integration Mesh's `docs/subsystems/integration/CONTRACT.md` explicitly states: *"There is no general connector framework yet — each integration is hand-built"* and *"Planned: General connector framework."*
- CIP's Phase 1 is the trigger for building that framework. CIP's Zendesk, HubSpot, Google Drive, WeChat, etc. connectors become the **first citizens** of a reusable Foundry-wide connector framework.
- Every other Foundry product (CRM, Knowledge System, future products) inherits the framework without re-building it.
- This complies with P-20 (One Home, Many Doors) and P-18 (Platform Services Own Shared Infrastructure).

**What CIP owns vs. what Integration Mesh owns:**

| Layer | Owner | Examples |
|-------|-------|----------|
| Raw API plumbing (HTTP, retries, rate limits, auth refresh, credential rotation) | Integration Mesh | Shared `APIClient` base, credential manager |
| Connector contract (CIPConnector Protocol, CIPMapper Protocol, pull_full, pull_incremental, normalize, rate_limits) | Integration Mesh (built as part of CIP Phase 1) | Protocol definitions, registry |
| Specific connector implementations (Zendesk, HubSpot, Shopify, Stripe, WeChat, Google Drive, Chatwoot, Amazon Seller Central) | Integration Mesh (CIP populates) | Each as a `<service>_client.py` + mapper registration |
| CIP-specific field mapping to normalized `cip_*` tables | CIP (consumes Integration Mesh connectors) | Mapper modules that read connector output and produce `cip_contacts`, `cip_tickets`, etc. rows |
| Sync orchestration, batch tracking, retry policy at the CIP level | CIP | `cip_sync_runs` table, pipeline orchestrator |

**Connector discoverability (D-121):** A new `integration_connectors` registry table (or extension of existing integration registry) lists every connector instance with: connector_name, auth_status, health_check_url, last_successful_run, version_pinned. Queryable via `foundry_mcp_db_query`.

---

## 15. Unstructured Store — CIP-Owned Pinecone + Postgres Staging + GraphRAG (D-119, revised D-d83c7e1d 2026-05-19)

> **REVISED 2026-05-19 by the CIP Hard Split (D-d83c7e1d).** The original D-119 wording said CIP would "consume the live Knowledge Subsystem (RAG)" inside Foundry-Agent-System. **That is no longer true.** CIP runs its own CIP-Pinecone index, its own embedding pipeline, and Postgres-staged `cip_knowledge_chunks` as the canonical source-of-truth. Foundry-Knowledge / Memory Service / per-venture stacks are off the CIP path entirely. See [ARCHITECTURE-SPLIT.md (CIP-SPEC-010)](../ARCHITECTURE-SPLIT.md).

### 15a. RAG (CIP-Owned)

Status: LIVE in `cip.integration_mesh.knowledge` (retriever) + `cip.integration_mesh.clients.pinecone` (PineconeClient) + `cip_knowledge_chunks` Postgres table (canonical staging).

- **Ingestion:** `KnowledgeIndexer.index(...)` — chunk (512 tokens), hash (dedup), embed (Qwen3-Embedding-4B Q8_0, **2,560-dim**, via CIP embedding endpoint), store in `cip_knowledge_chunks` (canonical) AND CIP-Pinecone (hot). (NB: indexer Pinecone-write wiring lands with the migration scope; until then, migrate via `scripts/migrate_chunks_postgres_to_pinecone.py`.)
- **Retrieval:** `KnowledgeRetriever.search(...)` — CIP-Pinecone-first hot path with reranker (Qwen3-Reranker-4B), graceful Postgres cosine fallback on `PineconeError`. Authority levels: `validated` | `draft` | `agent_discovered` | `pending_review`.
- **CIP-Pinecone:** index `foundry-cip` (cosine, serverless aws/us-east-1), host `foundry-cip-h705p9t.svc.aped-4627-b74a.pinecone.io`.
- **Namespace:** `cip__{tenant_id}__{client_id}` per (tenant, client). Tenant-wide content (no client scope) uses `cip__{tenant_id}___tenant`.
- **Source kinds in `cip_knowledge_chunks`:** `cip_client_document`, `cip_call_transcript`, `cip_ticket_body`, `cip_ticket_comment`, `cip_engagement_note`, `cip_email_thread`, `cip_sop`. Registered per-source with ingestion_config (D-026 tenant-scoped).
- **Foundry agents reach CIP-Pinecone exclusively via the bridge MCP tool** `foundry_mcp_cip_semantic_search` (scope filed under the hard-split reorg). Direct Pinecone access from outside the CIP product is prohibited.

### 15b. GraphRAG (Graph Subsystem)

Status: LIVE (`docs/subsystems/graph/CONTRACT.md`).

- `graph_extractor_service.extract_and_upsert(chunk_id, content, tenant_id, db)` — entity + relationship extraction via NuExtract 2.0 (LLM fallback)
- `graphrag_retriever_service.retrieve_via_graph(query, tenant_id, db)` — Cypher traversal + vector reranking
- FalkorDB per-tenant namespace (D-026). Non-fatal per D-067.

**CIP additions to `graph_templates` per venture:**
- New node types: `Client`, `Ticket`, `Deal`, `Order`, `Product`, `Campaign`, `Document`, `Transcript`
- New edge types: `SUBMITTED_TICKET`, `PURCHASED`, `OWNS_DEAL`, `WORKS_WITH`, `REFERENCED_IN`, `ESCALATED_TO`, `RESOLVED_BY`
- Existing types (Person, Project, Topic, Decision, Tool, Agent, Venture, Document, Date) are reused where they overlap.

### 15c. Ingestion Flow (One Pipeline, Two Derived Outputs)

```
Client document (PDF, transcript, ticket body, SOP)
    ↓
knowledge_ingester_service.ingest_text_content(...)
    ↓ (chunks → Pinecone + knowledge_chunks)     ↓ (auto-called via D-067 hook)
    RAG layer ready                         graph_extractor_service.extract_and_upsert(...)
                                                 ↓
                                            GraphRAG layer ready
```

One write path → both retrieval layers populated. No duplicated pipelines.

---

## 16. Three Data Layers — Originals, Derived, Structured (D-120)

CIP holds **three kinds of data**, each with a distinct store and a distinct discovery surface.

> **CIP Hard Split (D-d83c7e1d, locked 2026-05-19).** All three layers are **CIP-owned, not shared with Foundry-Knowledge or per-venture stacks**. CIP runs its own dedicated Pinecone index (`foundry-cip`, 2,560-dim, host `foundry-cip-h705p9t.svc.aped-4627-b74a.pinecone.io`), its own R2 prefix (`cip-originals/` under the shared `foundry-agent-system` bucket; graduates to a dedicated bucket at Stage 3), and its own embedding pipeline (Qwen3-Embedding-4B Q8_0, 2,560-dim, via the CIP embedding endpoint). Postgres `cip_knowledge_chunks` remains as canonical source-of-truth + staging; Pinecone is the hot-retrieval store. Foundry agents must access CIP-owned vectors via the bridge MCP tool `foundry_mcp_cip_semantic_search` — never directly through Pinecone. See [ARCHITECTURE-SPLIT.md (CIP-SPEC-010)](../ARCHITECTURE-SPLIT.md) for the data classification rule and migration plan.

| Layer | What it holds | Where it lives | Discovery surface |
|-------|---------------|----------------|-------------------|
| **Originals** | Actual files — PDFs, .docx, spreadsheets, images, ticket attachments, call recordings, deliverables | **CIP-R2** prefix `cip-originals/{tenant}/{client}/{source}/{source_id}/{file}` (graduates to dedicated bucket at Stage 3). Optionally mirrored to client Google Drive via Push & Sync | `cip_files` metadata table |
| **Derived Knowledge** | Chunks + embeddings (RAG) + entities + relationships (GraphRAG) extracted from originals | **CIP-Pinecone** index `foundry-cip` (2,560-dim cosine), namespace `cip__{tenant}__{client}` — plus **FalkorDB** (tenant-scoped namespace) for GraphRAG; `cip_knowledge_chunks` Postgres table holds canonical content + metadata + a Postgres-side embedding for fallback cosine search | `cip_knowledge_sources`, `cip_knowledge_chunks`, `graph_templates` |
| **Structured Data** | Normalized tabular rows — contacts, companies, tickets, deals, call-note metadata, sync runs | **Postgres** (`cip_*` tables, tenant_id scoped) | Standard SQL + `cip_*` registries |

### 16a. `cip_files` Metadata Table (Structured Store)

Tracks every original file CIP ingests. Lives in Structured Store (pillar #2).

```
cip_files (
    file_id             UUID PRIMARY KEY,
    tenant_id           UUID NOT NULL,
    client_id           UUID NOT NULL,
    r2_path             TEXT NOT NULL,         -- e.g., tenant_{venture}/cip/{client}/originals/{file_id}.pdf
    filename            TEXT NOT NULL,
    mime_type           TEXT,
    size_bytes          BIGINT,
    source_connector    TEXT NOT NULL,         -- 'google_drive' | 'zendesk_attachment' | 'manual_upload' | ...
    source_id           TEXT,                  -- connector-native id
    sha256              TEXT,                  -- content hash for dedup
    ingested_at         TIMESTAMPTZ NOT NULL,
    linked_chunk_ids    UUID[],                -- FK-style link to knowledge_chunks
    authority           TEXT,                  -- validated | draft | ...
    properties          JSONB,                 -- connector-native metadata
    -- (9 provenance columns per Phase 0 standard)
    ...
)
```

### 16b. R2 Path Convention (CIP Hard Split, D-d83c7e1d)

Stage 1/2 (shared bucket, CIP prefix):
```
foundry-agent-system/                          (CIP-R2 bucket, Stage 1+2)
    cip-originals/                             (CIP root prefix)
        {tenant_uuid}/
            {client_uuid}/
                {source_connector}/            (zendesk | hubspot | google_drive | manual_upload | ...)
                    {source_id}/
                        {file_name}.{ext}
        _deliverables/
            {tenant_uuid}/{client_uuid}/{deliverable_id}.{ext}
```

Stage 3 (external customer) graduates the tenant onto a dedicated bucket; the inner path structure stays the same (drop the `cip-originals/` root). Storage Service owns bucket selection per tenant; CIP code paths construct paths via `cip.integration_mesh.storage.r2_path_for(tenant_id, client_id, source_connector, source_id, file_name)`.

### 16c. Google Drive Integration

Google Drive plays **two roles** in CIP:
1. **As a source** (pull client docs from shared drives) → connector under Ingestion & Connectors (Integration Mesh)
2. **As a destination** (push deliverables to client-visible folders) → connector under Push & Sync

Both roles use the same Google Workspace client infrastructure already in Integration Mesh (`src/services/google_client.py`).

---

## 17. Discoverability Baseline (D-121)

Every CIP artifact gets a registry row that agents and scripts can query. This complies with NN-01 and STD-08 (Discoverable Registries). Nothing lives as invisible magic files.

| Artifact | Registry | Query via |
|----------|----------|-----------|
| CIP product itself | `products` table (per taxonomy) | `foundry_mcp_pm_venture_assets` |
| Clients | `cip_clients` (NEW) | SQL + `foundry_mcp_db_query` |
| Originals (files) | `cip_files` (NEW) | SQL + `foundry_mcp_db_query` |
| Derived chunks | `knowledge_chunks` (EXISTS) | knowledge_retriever service |
| Graph entities | FalkorDB Cypher (EXISTS) | graphrag_retriever service |
| Structured rows | `cip_contacts` / `cip_companies` / `cip_tickets` / `cip_deals` / `cip_call_notes` | SQL |
| Views / lenses | `cip_views` (NEW) | SQL + lens resolver service |
| Connectors | `integration_connectors` (NEW in Integration Mesh) | SQL + registry API |
| Connector configs (per-tenant) | `cip_connector_configs` (NEW) | SQL |
| Sync runs | `cip_sync_runs` (NEW) | SQL + observability dashboard |
| Knowledge source_types | `knowledge_sources` (EXISTS, CIP adds rows) | SQL |
| Graph node/edge types | `graph_templates` (EXISTS, CIP adds per-venture rows) | graph_template_manager |

All registries are tenant_id scoped. All registries are queryable by the MCP `foundry_mcp_db_query` tool and by `scripts/system_describe.py`.

---

## 18. Platform-Wide Principle — Multi-Lens by Default (P-21)

Locked in `docs/architecture/principles/DESIGN-PRINCIPLES.md` as **P-21: Multi-Lens by Default**. CIP is the first consumer and canonical example, but the principle applies to every Foundry data surface.

**Statement (abridged):** When data is collected, stored, or exposed, the system assumes an unknown number of future consumers with unknown filter requirements. Every data pillar, every output interface, and every retrieval path MUST be parameterized by a lens/view configuration so new consumers can be added without schema or code changes.

**How CIP enforces it:**
- Every query goes through the Lens Engine (pillar #4) — no direct-to-store paths that bypass filter config
- `cip_views` is first-class schema, not an afterthought
- RLS policies consume filter_config JSONB, not hardcoded column checks
- Push & Sync destinations (pillar #6) are filtered by lens at write time, not by consumer-side logic

---

## 19. Consumed Platform Services (Map)

| Platform Service | What CIP Uses It For | CIP Scope That Consumes It |
|------------------|---------------------|---------------------------|
| Storage Service (R2 + Postgres + Pinecone + FalkorDB) | Raw object store, relational data store, vector index, graph store | All pillars |
| Integration Mesh | Raw API plumbing + connector framework (which CIP Phase 1 builds) | Ingestion & Connectors |
| Knowledge Subsystem | RAG ingestion + hybrid retrieval | Unstructured Store |
| Graph Subsystem | GraphRAG entity extraction + graph retrieval | Unstructured Store |
| Governance (CSS/OSS) | Component classification, standards enforcement | All pillars (compliance) |
| Auth & Security | Tenant/client credential storage, encryption | Access & Operations, Ingestion & Connectors |
| PM System | Project tracking, scope/task management | Internal — all CIP work tracked here |

**NOT consumed:** Memory Service (agent-scoped, wrong semantic fit — see D-119).


## System overview

_TODO: author this section per the doc-standard._

## Boundaries

_TODO: author this section per the doc-standard._

## Technology choices

_TODO: author this section per the doc-standard._

