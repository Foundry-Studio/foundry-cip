---
kind: doc
domain: client-intelligence-platform
status: skeleton
last_updated: 2026-04-20
milestone: Phase-1-M0
---

# Four Access Paths Reference

> **Status:** skeleton stub — authored Phase 1 M0, populated as Phase 1 milestones land.
> Once final, this doc is the canonical reference for the four ways agents read from CIP. Phase 1 validates all four paths against the fixture tenant (M7 green-light gate).

## Purpose

Define the four agent access paths into CIP data — what each returns, when to use each, and how to verify each is live for a given tenant.

## Who reads this

- Agent authors choosing which path to query for a given information need.
- Consumption-surface engineers exposing these paths (REST/MCP/Chat in later phases).
- Anyone reviewing the M7 discoverability validation report.

## Related milestones

| Milestone | Relationship |
|-----------|--------------|
| M0 — Doc skeleton | Creates this skeleton. |
| M1 — Migrations | Populates Path 1 (Structured) baseline. |
| M4 — Lenses | Populates Path 1 curated-view layer. |
| M5 — Knowledge + Graph | Populates Paths 2 and 3. |
| M7 — Four-access-paths validation | Fills §6 green-light criteria and cross-refs `validation/M7-discoverability-report.md`. |

Cross-ref: [`VISION.md §7g`](../../products/client-intelligence-platform/vision/VISION.md), [`PHASE-1-PLAIN-SPEC.md §2`](../../products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md) acceptance item 11.

## Outline

### 1. Overview

TBD (M5) — the four paths as complementary, not competing; which is best for what question.

### 2. Path 1: Structured (`cip_*` + lenses)

TBD (M1, M4) — direct SELECT against `cip_*` tables and lens views; best for exact-match queries, aggregations, history reads.

### 3. Path 2: Derived Knowledge — vector + BM25

TBD (M5) — Pinecone (Qwen3-Embedding-4B, 1024d) + BM25 over text fields routed through `ingest_as_knowledge()`; best for semantic similarity and lexical recall.

### 4. Path 3: Derived Knowledge — graph

TBD (M5) — FalkorDB traversals over entities + relations extracted from the same text; best for multi-hop relationship queries.

### 5. Path 4: Originals

TBD (M5) — raw source files (documents, email bodies, note blobs) held in Unstructured Store / R2; best for citation + human review.

### 6. M7 green-light criteria

TBD (M7) — per-path assertion that a fixture-tenant query returns non-empty results; cross-tenant probe returns zero; validation report committed.

### 7. When to combine paths

TBD (M5) — common patterns (structured filter → knowledge rerank, graph expand → structured detail, etc.).

### 8. Phase 2+ evolution

TBD (M7) — Phase 2 re-validates against Wayward; Phase 4 exposes paths as MCP tools; Phase 5 routes a chatbot over them.
