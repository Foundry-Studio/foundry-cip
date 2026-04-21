---
doc_type: handoff-spec
project_id: client-intelligence-platform
phase: 1
intended_audience: claude-code-architect
status: authoritative
owner: tim
authors: [atlas]
created: 2026-04-20
last_updated: 2026-04-20
pairs_with: PHASE-1-PLAN.md
---

# CIP Phase 1 — Claude Code Handoff SPEC

> **You (Claude Code) are reading this FIRST, before writing any code.** This doc is your complete instruction set for CIP Phase 1 plain-jane. Pair with `PHASE-1-PLAN.md` for context. If anything here contradicts `PHASE-1-PLAN.md`, stop and escalate — don't guess.
>
> **Before writing code:** summarize your understanding of this SPEC back to Atlas (prose, one page max). Atlas will correct the SPEC (not you) where your summary surfaces a plan hole. Iterate until your summary and Atlas's intent are aligned. Only then does the builder subagent begin.

---

## 1. Scope in one sentence

Build a **tenant-neutral, blank-slate CIP product** (generic CIPConnector + CIPMapper framework, FixtureConnector as the only Phase 1 connector, two lenses on fixture data, Metabase dashboard with lens switcher, full discoverability registry, four access paths validated, ten doc artifacts) such that a second engineer could onboard any reasonable tenant to the product using the ten docs alone, without Atlas or Tim in the room.

No HubSpot. No Zendesk. No Wayward. No push targets. No cross-tenant grants. No chatbot. No MCP surface (beyond what already exists). No REST API. Those are Phase 2+ and must not creep in.

## 2. Acceptance criteria

Phase 1 is complete when all of these are simultaneously true:

1. Migrations cip_01 through cip_08 (including `cip_connector_property_registry` inside cip_08) applied cleanly to dev DB. **cip_09 is NOT in Phase 1** — reserved for Phase 3 cross-tenant grants.
2. `CIPConnector` and `CIPMapper` Protocols live in `platform/integration-mesh/src/connectors/cip/base.py` with zero tenant-specific hints.
3. Ingestion pipeline orchestrator implemented with SCD differ + `cip_sync_runs` audit. Entry point: `run_sync(connector_id, tenant_id, client_id, db)`.
4. `FixtureConnector` + `FixtureMapper` implemented against the fixture shape in §5. Deterministic. Re-seeding produces byte-identical state.
5. `scripts/seed_fixture_tenant.py` implemented with `--reset` flag. Idempotent.
6. `cip_connector_property_registry` populated by `FixtureConnector.describe_schema()` at connector setup.
7. Two `cip_views` rows on fixture tenant: `Lens-A Full View` (empty filter) and `Lens-B Region-EMEA View` (filter: `{"region": "EMEA"}`).
8. Metabase deployed as a platform service. Two dashboards, one per lens, with parameter-based lens switcher.
9. Knowledge Subsystem ingestion live for fixture ticket/note/document text. Graph extraction via non-fatal post-vector hook (D-067).
10. RLS + SET LOCAL verified on every `cip_*` table via smoke tests (cross-tenant query returns zero rows).
11. Four-access-paths validation report committed at `products/client-intelligence-platform/validation/M7-discoverability-report.md` with all four paths green against the fixture tenant.
12. All ten doc artifacts in `docs/cip/` reviewed and complete (see §9).
13. Connector-conformance test harness exists at `tests/fixtures/connector_conformance/` — any future `CIPConnector` subclass can use it to validate Protocol compliance.

Any acceptance criterion missed = Phase 1 incomplete.

## 3. File paths — authoritative

Do not deviate without escalating.

```
migrations/versions/cip_01_*.py                              cip_clients + history
migrations/versions/cip_02_*.py                              cip_views + history
migrations/versions/cip_03_*.py                              cip_sync_runs (no history)
migrations/versions/cip_04_*.py                              cip_files + history
migrations/versions/cip_05_*.py                              cip_contacts + history
migrations/versions/cip_06_*.py                              cip_companies + history
migrations/versions/cip_07_*.py                              cip_deals + history
migrations/versions/cip_08_*.py                              cip_tickets + history + cip_connector_property_registry

platform/integration-mesh/src/connectors/cip/base.py         CIPConnector + CIPMapper Protocols
platform/integration-mesh/src/connectors/cip/orchestrator.py ingestion pipeline orchestrator
platform/integration-mesh/src/connectors/cip/fixture/__init__.py
platform/integration-mesh/src/connectors/cip/fixture/connector.py     FixtureConnector
platform/integration-mesh/src/connectors/cip/fixture/mapper.py        FixtureMapper
platform/integration-mesh/src/connectors/cip/fixture/data.py          synthetic data generators
platform/integration-mesh/src/connectors/cip/fixture/schema.py        describe_schema() payload

scripts/seed_fixture_tenant.py                               idempotent fixture DB seeder

tests/fixtures/connector_conformance/                        generic CIPConnector test harness
tests/fixtures/lens/golden_files/                            Lens-A / Lens-B expected row sets

products/client-intelligence-platform/validation/M7-discoverability-report.md

docs/cip/_TEMPLATE.md                                        doc skeleton
docs/cip/TENANT-ONBOARDING-CHECKLIST.md
docs/cip/CONNECTOR-AUTHORING-GUIDE.md
docs/cip/LENS-AUTHORING-GUIDE.md
docs/cip/MIGRATION-RUNBOOK.md
docs/cip/RLS-SET-LOCAL-OPERATOR-GUIDE.md
docs/cip/SYNC-ORCHESTRATOR-GUIDE.md
docs/cip/FOUR-ACCESS-PATHS.md
docs/cip/FIXTURE-TENANT-HANDBOOK.md
docs/cip/CSS-CLASSIFICATION-CONTRACT.md
docs/cip/PHASE-1-TO-PHASE-2-HANDOFF.md
```

Any new file not listed here: escalate to Atlas first.

## 4. Protocol shapes — binding

### `CIPConnector` Protocol

```python
class CIPConnector(Protocol):
    connector_id: str  # e.g. "fixture_v1"
    tenant_id: UUID

    def authenticate(self) -> None: ...
    def stream_records(self, cursor: dict | None, batch_size: int) -> Iterator[dict]: ...
    def describe_schema(self) -> list[PropertyDescriptor]: ...

    @property
    def rate_limit_policy(self) -> RateLimitPolicy: ...

    def incremental_key(self, record: dict) -> datetime: ...
```

No methods beyond this. No `ingest()`, no `sync()` — those are orchestrator responsibilities.

### `CIPMapper` Protocol

```python
class CIPMapper(Protocol):
    object_type: str  # e.g. "companies"
    target_table: str  # e.g. "cip_companies"

    def map(self, record: dict) -> Iterable[CIPRow]: ...
    def overflow_fields(self) -> list[str]: ...
    def authority(self) -> Literal["agent_discovered", "ingested", "validated"]: ...
    def ingest_as_knowledge(self, record: dict) -> list[str]: ...  # field names whose text goes to Knowledge ingester
```

### `PropertyDescriptor` (populates `cip_connector_property_registry`)

```python
@dataclass
class PropertyDescriptor:
    connector: str
    object_type: str
    property_name: str
    property_type: str   # "string" | "number" | "datetime" | "enumeration" | "reference"
    storage_location: Literal["column", "overflow"]
    column_name: str | None   # if storage_location == "column"
    cip_table: str
    description: str | None
    is_custom: bool
```

## 5. FixtureConnector data shape — binding

Fixture produces deterministic synthetic data seeded by a single random seed declared at the top of `scripts/seed_fixture_tenant.py`.

- ~50 **companies** with `region` ∈ {`EMEA`, `AMER`, `APAC`, `LATAM`}, `language` ∈ {`en`, `zh`, `es`, `fr`, `de`, `pt`, `ja`}, `industry` ∈ {`retail`, `saas`, `manufacturing`, `services`}.
- ~200 **contacts** linked to companies by `associated_company_id`.
- ~300 **deals** linked to contacts and companies.
- ~500 **tickets** with subject/body generated from a deterministic template set (templates live in `fixture/data.py`).
- ~100 **documents** uploaded to R2 under the fixture tenant namespace, each with a corresponding `cip_files` row.
- ~50 **notes** attached to companies/deals/tickets with body text.

Row counts are rough guidance; exact counts from the seeded PRNG are fine. Byte-identical repeatability is the hard requirement.

**`cip_clients` population:** one `cip_clients` row per fixture company. Document this pattern in the Connector Authoring Guide — note that other tenants may define `cip_clients` differently.

## 6. Lens Engine — binding

### Two lenses on fixture tenant

**`Lens-A Full View`**
```
view_name: "Lens-A Full View"
filter_config: {}
```

**`Lens-B Region-EMEA View`**
```
view_name: "Lens-B Region-EMEA View"
filter_config: {"region": "EMEA"}
```

### Lens resolver

Signature:
```python
def resolve_lens(view_id: UUID, base_query: Select, db: Session) -> Select:
    """Returns base_query with the lens filter composed onto it."""
```

Composition rules:
- Lens filter is **AND**-composed with RLS (RLS is already active via `SET LOCAL`).
- `filter_config={}` is a no-op — return `base_query` unchanged.
- `filter_config` keys map to column names on the base table (Phase 1 scope — more sophisticated resolution is Phase 4+).
- Unknown keys raise `UnknownLensFilterField`; caller decides whether to fail or log.

### Lens test harness

Golden files in `tests/fixtures/lens/golden_files/`:
- `lens_a_cip_tickets.json` — all fixture ticket IDs.
- `lens_b_cip_tickets.json` — only ticket IDs whose company is in EMEA.

Test: `assert resolved_rows == golden`. Bit-for-bit.

## 7. RLS + SET LOCAL — binding

Every `cip_*` table has an RLS policy:
```sql
CREATE POLICY cip_tenant_scope ON cip_<table>
  USING (tenant_id = current_setting('app.current_tenant')::uuid);
ALTER TABLE cip_<table> ENABLE ROW LEVEL SECURITY;
```

Every request that touches `cip_*` tables must call:
```python
db.execute(text(f"SET LOCAL app.current_tenant = :t"), {"t": str(tenant_id)})
```

Middleware enforces this. Metabase connection uses a service account with RLS bypass **disabled**.

Smoke test pattern (must ship in M1):
```python
def test_rls_blocks_cross_tenant():
    with session_scope(tenant_id=OTHER_TENANT):
        rows = db.execute(select(cip_clients)).all()
        assert rows == []
```

## 8. Forbidden imports — binding

Per D-018, D-031, D-077 (LLM Roster is mandatory):
- **Do not import:** `openai`, `anthropic`, `google.generativeai`, `cohere`, any other direct LLM SDK.
- **Do use:** `llm_call_sync(request, db)`, `llm_call_complete(request, db)`, `llm_call(request, db)` from the Roster.

Per CLAUDE.md:
- **Do not** hardcode tenant, client, or connector names in code. All behavior comes from config.
- **Do not** branch on tenant identity (`if tenant == "wayward": ...` is forbidden).
- **Do not** skip CSS classification. Every new file must start with `# foundry: kind=X domain=Y` (Python) or include `kind:`/`domain:` frontmatter (Markdown/YAML).

## 9. Documentation Suite — binding

All ten docs follow the template at `docs/cip/_TEMPLATE.md`:
```
# Title

> Purpose: <one paragraph>
> Audience: <who reads this>
> When to use: <trigger conditions>

## Step-by-step
1. ...
2. ...

## Common pitfalls

## Where to get help
```

Doc authoring discipline:
- **M0:** author all ten skeletons. Each doc has all sections as empty headers with TODO markers.
- **M1–M6:** fill in each doc as the milestone that produces its subject matter completes.
- **M7:** fresh-reviewer pass — any doc gap that would block a second engineer using the doc alone is an M7 fix.
- **M8:** locked at Phase 1 exit.

Doc ownership during build: whichever milestone produces the subject matter owns the doc fill-in for that milestone. The Migration Runbook gets filled during M1; the Connector Authoring Guide during M2–M3; the Lens Authoring Guide during M4; etc.

## 10. Four Access Paths — binding (M7 validation)

Agent acts with only generic `foundry_mcp_*` tools. Must light up all four paths against the fixture tenant:

1. **Structured.** Enumerate fixture columns via `cip_connector_property_registry`; read rows with `SET LOCAL`; cross-check RLS blocks wrong tenant.
2. **Derived Knowledge — vector + BM25.** Enumerate source_types via `knowledge_sources`; retrieve chunks by fixture content query; confirm `cip_fixture_*` source references.
3. **Derived Knowledge — graph.** Enumerate node/edge types via `graph_templates`; retrieve by graph-hop query; confirm entity-linked citations.
4. **Originals.** Enumerate via `cip_files`; resolve `cip_file_id` → signed R2 URL via Storage Service; fetch bytes.

Report template at `validation/M7-discoverability-report.md` — pass/fail per path with evidence (query text, result sample, failure mode if failed).

## 11. Connector-conformance test harness — binding

Generic pytest fixtures in `tests/fixtures/connector_conformance/`:
- `test_protocol_compliance(connector)` — verifies all Protocol methods present and typed correctly.
- `test_incremental_sync(connector, orchestrator)` — runs two syncs, verifies second sync only pulls changed records.
- `test_property_registry_populated(connector, db)` — after setup, `cip_connector_property_registry` has rows matching `describe_schema()`.
- `test_scd_history(connector, orchestrator, db)` — modifies a record between syncs, verifies `_history` row created.
- `test_sync_run_audit(connector, orchestrator, db)` — verifies `cip_sync_runs` row well-formed.
- `test_tenant_scoping(connector, orchestrator, db)` — wrong tenant_id returns zero rows.

FixtureConnector must pass all six. Phase 2 HubSpot/Zendesk connectors will also run this harness.

## 12. Milestone order — binding

Execute in order. Do not parallelize across milestones unless Atlas explicitly authorizes.

```
M0  Vision Lock + Doc Skeletons + this SPEC reviewed by Atlas
M1  Foundation (migrations cip_01–cip_08 + RLS smoke tests)
M2  Generic Connector Framework + conformance harness
M3  FixtureConnector + seeder + registry population
M4  Lens Engine + golden-file test harness
M5  Metabase platform service
M6  Discoverability registry completeness pass
M7  Four Access Paths validation + doc hardening
M8  Product-Ready Gate: plain-jane lock
```

Milestone exits (see `PHASE-1-PLAN.md` §PLAN for full criteria):
- M0 exit: Atlas approves your SPEC-understanding summary.
- M1 exit: migrations applied, RLS verified, two docs drafted.
- M2 exit: framework passes own tests, two more docs drafted.
- M3 exit: fixture data flowing, history captured on second sync, chunks + graph populated, two more docs drafted.
- M4 exit: two lenses resolve correctly matching golden files, one more doc drafted.
- M5 exit: Metabase lens switcher works.
- M6 exit: registry completeness verified, one more doc drafted.
- M7 exit: four-access-paths report green, doc suite hardened.
- M8 exit: plain-jane locked.

## 13. Escalation rules

Stop and escalate to Atlas if:
- Any acceptance criterion in §2 seems impossible given the SPEC.
- Any Protocol shape in §4 doesn't support the fixture shape in §5.
- A milestone exit criterion can't be met without scope that isn't in §2.
- You're tempted to add a file not in §3.
- You find a D-number (decision lock) that would be violated.
- A doc artifact in §9 needs content that nothing in the SPEC tells you.

Escalation = a short prose message to Atlas naming the mismatch. Do not guess, do not proceed.

## 14. What you hand back

At M8 exit:
- Working code at the paths in §3.
- All ten docs at `docs/cip/` reviewed and final.
- Validation report at `validation/M7-discoverability-report.md` green.
- PM task updates (via `foundry_mcp_pm_task_update`) logging each milestone's completion under the appropriate scope.
- A Phase 1 retrospective note at `products/client-intelligence-platform/retrospectives/phase-1-retro.md` — what worked, what surprised, what Phase 2 should inherit.

---

## Confirm-understanding protocol

Before writing any code:

1. Read this SPEC end-to-end.
2. Read `PHASE-1-PLAN.md`.
3. Read `docs/cip/_TEMPLATE.md` (after creating it in M0).
4. Write a one-page prose summary of your understanding to Atlas. Cover: Phase 1 scope in your own words; the acceptance criteria; the ten docs and when they get filled; the four access paths; the non-negotiables (§8) with specific examples of what you will NOT do.
5. Wait for Atlas to confirm or correct.
6. Iterate until Atlas confirms.
7. Only then does the builder subagent start M1.

This loop is deliberate. Atlas pays for the iteration in tokens; Tim pays for mistakes in weeks. Iteration is cheaper.
