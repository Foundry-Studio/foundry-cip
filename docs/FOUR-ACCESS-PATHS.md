---
kind: doc
domain: client-intelligence-platform
status: draft
last_updated: 2026-05-10
milestone: Phase-1-M6
---

# Four Access Paths Reference

> **Status:** draft — promoted from skeleton 2026-05-10 alongside the M6 discoverability completeness pass. Reflects deployed reality at HEAD post-M6. Sections §§1-9 populated. M7 will re-verify each path's per-tenant green-light criteria against the fixture tenant + add the validation-report cross-link.

## Purpose

Define the four agent access paths into CIP data — what each returns, when to use each, and how to verify each is live for a given tenant.

## Who reads this

- Agent authors choosing which path to query for a given information need.
- Consumption-surface engineers exposing these paths (REST/MCP/Chat in later phases).
- Anyone reviewing the M7 discoverability validation report.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Created this skeleton. |
| M1 — Migrations | Populates Path 1 (Structured) baseline. |
| M4 — Lens Engine | Populates Path 1 curated-view layer. |
| M5 — Metabase platform service | Lights up Path 1 for human consumption via cip_metabase_role + lens_* views. |
| **M6 — Discoverability registry completeness pass** | **This draft.** Verification tests cover Path 1 + Path 4; populates §§1-§9 with deployed-reality content. Paths 2 + 3 remain pseudo-coded since the platform-service surfaces (`knowledge_retriever_service`, `graphrag_retriever_service`) live in monorepo, not foundry-cip. |
| M7 — Four-access-paths validation | Fills §5 green-light criteria with per-tenant assertions and cross-refs `validation/M7-discoverability-report.md`. |

Cross-ref: [`VISION.md §7g`](../../products/client-intelligence-platform/vision/VISION.md), [`PHASE-1-PLAIN-SPEC.md §2`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md) acceptance item 11.

## 1. Path 1 — Structured via SQL

**Definition.** Tabular intelligence served from `cip_*` tables (or the M5-deployed `lens_*` Postgres views) via parameterized SQL with explicit tenant context. Best for exact-match queries, aggregations, history reads, dashboard tiles.

**Working SQL snippet:**

```sql
SET LOCAL app.current_tenant = '<tenant-uuid>';
SELECT name, region FROM lens_eu_west_companies LIMIT 10;
```

**Expected fixture row count.** ~10 for the eu-west subset (50 STANDARD companies × ~1/5 region distribution per the deployed Faker seed=42 corpus).

**Error mode — forget `SET LOCAL`.** RLS evaluates `tenant_id = NULL` → 0 rows returned (safe-fail; not all rows). Symptom: empty result that looks like missing data; reality is authorization blocking.

**Error mode — query raw `cip_companies` as `cip_metabase_role`.** Postgres returns `permission denied for table cip_companies`. M5's grant matrix is a P-21 enforcement layer — the role only has SELECT on `lens_*` views. Native SQL questions in Metabase that touch raw tables fail loud.

**Downstream service.** Phase 1 raw: `foundry_mcp_db_query` (monorepo MCP tool). Phase 4 wrapped: `foundry_mcp_cip_query` (lens-aware wrapper).

**Cross-link.** [`docs/RLS-SET-LOCAL-OPERATOR-GUIDE.md`](RLS-SET-LOCAL-OPERATOR-GUIDE.md), [`docs/METABASE-OPERATOR-GUIDE.md`](METABASE-OPERATOR-GUIDE.md), [`docs/LENS-AUTHORING-GUIDE.md`](LENS-AUTHORING-GUIDE.md).

---

## 2. Path 2 — Derived Knowledge (vector + BM25)

**Definition.** Embedded text intelligence served from a tenant-scoped Pinecone namespace plus a Postgres-side BM25 index — chunks of ticket bodies, call transcripts, document content, SOPs, venture-scoped research. Best for semantic-similarity search and lexical recall.

**Working pseudocode snippet:**

```python
from cip_consumer import knowledge_retriever_service  # platform service

results = knowledge_retriever_service.retrieve(
    query="refund request body",
    tenant_id=tenant_id,
    source_types=["cip_doc"],   # see source-type taxonomy note below
)
# Returns: list of (chunk_text, score, metadata) with cip_* source references.
```

**Source-type taxonomy note.** The deployed `knowledge_sources.source_type` CHECK constraint allows `{document_library, web_collection, expert_corpus, repo_documentation}`. CIP-tagged source types (`cip_doc`, `cip_ticket`, `cip_note`, `cip_fixture_*`) per VISION §7g are aspirational — they require an alignment migration tracked at PM scope `458fb208-...`. Today, CIP content tagged via the knowledge subsystem uses `document_library` / similar; the `source_types=` filter resolves against those values until the alignment lands. Rocky Ridge's existing 1,533 chunks (per the LOL audit) sit under this taxonomy.

**Error mode — missing tenant context.** `knowledge_retriever_service` MUST be called with an explicit `tenant_id`; if omitted, the retriever's tenant-scope assertion fails loud. M7 procedure validates that no caller path bypasses the tenant gate.

**Downstream service.** Phase 1 raw: `knowledge_retriever_service` direct Python import (monorepo platform service). Phase 4 wrapped: `foundry_mcp_cip_search` (MCP tool surface).

**Cross-link.** Knowledge Subsystem CONTRACT.md (monorepo `docs/subsystems/knowledge/`).

---

## 3. Path 3 — Derived Knowledge (graph)

**Definition.** Entity-relationship hops served from FalkorDB — nodes for tenant entities (companies, contacts, deals, tickets, files, etc.) plus edges for cross-entity references extracted from text bodies. Best for multi-hop relationship queries ("which companies filed tickets that mention deal X?") and traversal-style discovery.

**Working pseudocode snippet:**

```python
from cip_consumer import graphrag_retriever_service  # platform service

results = graphrag_retriever_service.hop_query(
    seed_entity_id=company_id,
    hop_types=["filed_ticket", "raised_issue"],
    tenant_id=tenant_id,
)
```

**Phase status note.** FalkorDB integration is partial in Phase 1 — the platform service exists (monorepo), but cross-tenant namespace isolation + ingest pipeline coverage haven't been validated against the fixture tenant yet. M7 gates this. Expect Path 3 to be flaky-but-improving until Phase 4 hardening.

**Error mode — missing tenant context.** Tenant-scoped namespace lookup; missing `tenant_id` returns empty result rather than cross-tenant data (safe-fail). Validated by M7's per-path probe.

**Downstream service.** Phase 1 raw: `graphrag_retriever_service` direct Python import. Phase 4 wrapped: rolled into `foundry_mcp_cip_search` with a graph-boost flag (the same Phase 4 search tool serves both Path 2 and Path 3).

**Cross-link.** Graph Subsystem CONTRACT.md (monorepo `docs/subsystems/graph/`).

---

## 4. Path 4 — Originals

**Definition.** Raw source files served from Cloudflare R2 — PDFs, transcripts, exports, client uploads. Indexed by `cip_files` rows whose `r2_path` column points at the canonical R2 object key. Best for citation, human review, legal/compliance retrieval, replay of original payload.

**Working code snippet:**

```python
from cip_consumer import storage_service  # platform service
from sqlalchemy import text

cip_file = db.execute(
    text("SELECT r2_path FROM cip_files WHERE cip_file_id = :id AND tenant_id = :tid"),
    {"id": file_id, "tid": tenant_id},
).first()
signed_url = storage_service.sign_url(cip_file.r2_path, expiry_seconds=300)
```

**Expected fixture path pattern.** `fixture://<source_id>` for FixtureMapper-generated documents (per M3 Δ6 — FixtureMapper synthesizes a stable `r2_path` because the corpus has no real R2 upload). Real connectors (HubSpot, Zendesk, etc.) write actual R2 keys of form `<tenant_id>/<connector>/<source_id>/<filename>` per the platform's R2 layout convention.

**Error mode — missing cip_files row.** The lookup returns None; caller decides whether that's a 404 or a "file not yet indexed" backoff signal.

**Error mode — R2 object missing despite cip_files row.** `storage_service.sign_url` returns the URL but the GET returns 404. Symptom of corpus-vs-storage drift; investigate via the `<tenant_id>/cip/<client_id>/originals/...` R2 prefix listing.

**Downstream service.** Phase 1 raw: `storage_service.sign_url(cip_file.r2_path)`. Phase 4 wrapped: `foundry_mcp_cip_files`.

---

## 5. How to verify each path is live (per-tenant)

Each path has a canonical discovery query + smoke check. M7 will execute these against the fixture tenant + emit `validation/M7-discoverability-report.md`. Until then, these are the runbook checks any operator can run.

| Path | Discovery query | Smoke check |
|------|----|----|
| 1 — Structured | `SELECT count(*) FROM cip_connector_property_registry WHERE tenant_id = :tid` returns >0 | `SELECT * FROM lens_<name> LIMIT 1` returns expected shape |
| 2 — Knowledge vector | `SELECT DISTINCT source_type FROM knowledge_sources WHERE tenant_id = :tid` returns the tenant's tagged types | `knowledge_retriever_service.retrieve(query="...", tenant_id=:tid)` returns ≥1 hit |
| 3 — Knowledge graph | `MATCH (n {tenant_id: $tid}) RETURN labels(n), count(*)` (or analogous Cypher) returns node-type distribution | `graphrag_retriever_service.hop_query(seed_entity_id=..., tenant_id=:tid)` returns ≥1 hop |
| 4 — Originals | `SELECT r2_path FROM cip_files WHERE tenant_id = :tid LIMIT 1` returns valid path | `storage_service.sign_url(r2_path)` produces a 200-resolvable URL |

The M6 verification suite at `tests/integration_mesh/test_discoverability_completeness.py` programmatically asserts Paths 1 and 4 for the fixture tenant; Paths 2 and 3 are platform-service tests that live in the monorepo (M7 covers them in monorepo).

---

## 6. When to use each (decision tree)

- **Need a count, value, or join across structured records?** → Path 1.
- **Need semantic-similarity search over text bodies?** → Path 2.
- **Need entity hops or relationship traversal?** → Path 3.
- **Need to retrieve original source content for citation?** → Path 4.
- **Combined queries.** Common composition: Path 1 to filter the candidate set (e.g., "deals over $50K in eu-west"), Path 2 for semantic re-ranking on the candidates' associated text, Path 4 for citation back to the original document. Path 3 extends this when relationships are load-bearing ("show me deals where the contact also filed a high-priority ticket in the last 30 days").

---

## 7. Common pitfalls

- **Forgetting `SET LOCAL app.current_tenant`.** RLS returns 0 rows; looks like missing data, actually authorization blocking. Path 1 specifically.
- **Querying raw `cip_*` tables instead of `lens_*` views from `cip_metabase_role`.** Permission denied (M5 P-21 enforcement). Operator dashboards must target lens views.
- **Knowledge taxonomy alignment drift.** Today `source_type='document_library'` for fixture content; CIP-style tags (`cip_doc` etc.) require the alignment migration (PM scope `458fb208-...`). Path 2 `source_types=` filters resolve against the deployed taxonomy until alignment lands.
- **FalkorDB connection state.** Phase 1 partial; expect Path 3 to be flaky-but-improving until Phase 4 hardening.
- **Auto-generated lens views.** M5 ships hardcoded `lens_all_companies` + `lens_eu_west_companies`. M6 doesn't auto-generate per-tenant views — Phase 2 ships that auto-generator (PM task #143). Until then, every new lens needs a new migration + manual `CREATE VIEW`.

---

## 8. Phase 1 vs Phase 4 mapping

| Path | Phase 1 (raw) | Phase 4 (wrapped) |
|------|---------|---------|
| 1 — Structured | `foundry_mcp_db_query` | `foundry_mcp_cip_query` |
| 2 — Knowledge vector | `knowledge_retriever_service` direct | `foundry_mcp_cip_search` |
| 3 — Knowledge graph | `graphrag_retriever_service` direct | `foundry_mcp_cip_search` (graph-boost flag) |
| 4 — Originals | `storage_service.sign_url(cip_file.r2_path)` | `foundry_mcp_cip_files` |

The Phase 1 → Phase 4 transition is wrapping, not rewriting: same underlying services, exposed through MCP tools that agents can invoke directly. M7 validates the raw-call surface; Phase 4 picks up the MCP-tool authoring against the validated raw surface.

---

## 9. Where to get help

- **Atlas** thought-partner via Cowork session for architecture / scope questions.
- **PM scopes:**
  - `e47f3cf4-89dc-4b31-9c88-08f13a072300` — M5 lens views + `cip_metabase_role` (Path 1).
  - `6eb57ad7-adbb-40da-af4f-4fc7665f48bf` — M6 discoverability completeness (this draft).
  - `458fb208-...` — Knowledge source-type taxonomy alignment (deferred; affects Path 2 source_types filter resolution).
  - PM task #143 — Phase 2 auto-generator commit-watcher (affects M6 future-state for Path 1 lens views).
- **Related docs:** [`LENS-AUTHORING-GUIDE.md`](LENS-AUTHORING-GUIDE.md), [`METABASE-OPERATOR-GUIDE.md`](METABASE-OPERATOR-GUIDE.md), [`RLS-SET-LOCAL-OPERATOR-GUIDE.md`](RLS-SET-LOCAL-OPERATOR-GUIDE.md), [`MIGRATION-RUNBOOK.md`](MIGRATION-RUNBOOK.md).
- **Cross-system contracts** (monorepo): Knowledge Subsystem CONTRACT.md, Graph Subsystem CONTRACT.md, Storage Service contract.
