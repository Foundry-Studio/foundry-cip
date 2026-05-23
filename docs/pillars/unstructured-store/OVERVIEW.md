---
doc_type: overview
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
---
<!-- OVERVIEW.md per JOS-S19 -->
---
doc_type: overview
declared_thing: foundry-cip-unstructured-store
declared_thing_kind: subsystem
owner: tim
status: active
created: 2026-05-21
last_modified: 2026-05-21
last_reviewed: 2026-05-21
review_cadence: 90
audience: [dev, product, agent]
diataxis_type: explanation
---

# Overview — CIP Pillar 3: Unstructured Store

## What this is

The bridge from CIP's body-bearing records (tickets, notes, documents, call transcripts) to FAS's Knowledge subsystem (Pinecone for chunks + vectors) and Graph subsystem (FalkorDB for entities + relationships). CIP doesn't own the storage — per D-119, retrieval lives in FAS — but CIP owns the ingestion hook + provenance.

`CIPMapper.ingest_as_knowledge()` emits `KnowledgeText` for body-bearing entity types; the orchestrator dispatches to the FAS Knowledge service. Source-type values like `cip_fixture_ticket`, `cip_fixture_note`, `cip_fixture_doc` carry provenance.

## What's inside

| Feature | Status | Code |
|---|---|---|
| `knowledge-ingestion-hook` | in-progress (bronze) | `cip.integration_mesh.orchestrator` |

1 feature tagged `pillar:unstructured-store`. More features will land as Phase 4 (agent access) lights up.

## Status

- **Lifecycle:** building — ingestion hook wired; retrieval-side pending
- **Maturity:** bronze — fixture-data path proved; Wayward real-data path lands Phase 2
- **Health summary:** the wiring works; the proof points are deferred to Phase 2
- **Last reviewed:** 2026-05-21

## What's NOT here

- **The vector store + graph store** → FAS Knowledge & Memory system (FKM); see [`Foundry-Agent-System/docs/systems/knowledge-and-memory/`](../../../../Foundry-Agent-System/docs/systems/knowledge-and-memory/)
- **The retrieval surfaces** → FAS MCP tools (`foundry_mcp_knowledge_search`, `foundry_mcp_knowledge_file_chunks`)
- **The original files (R2)** → Pillar 2's `cip_files` metadata table + FAS Storage service
- **CIP-side chatbot consumption** → planned Phase 5

## Relationships

- **Parent:** [`foundry-cip`](../../../)
- **Siblings:** Pillars 1, 2, 4-8
- **External dependencies:** FAS Knowledge & Memory system (FKM)
- **Cross-references:** depends on Pillar 1 (Ingestion provides body-bearing records); FAS provides the storage + retrieval

## Where to go next

| Doc | When to open it |
|---|---|
| [`docs/FOUR-ACCESS-PATHS.md`](../../FOUR-ACCESS-PATHS.md) | The 4 read paths (Structured, Derived Knowledge vector+BM25, Derived Knowledge graph, Originals) |
| `cip/integration_mesh/orchestrator.py` | The dispatch site |
| FAS `docs/systems/knowledge-and-memory/OVERVIEW.md` | The other side of the hook |
