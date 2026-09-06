---
id: CIP-SPEC-010
uuid: f8f54da6-9b9f-4d2a-b6e4-9c8f7d2e3a4b
title: CIP Hard Split — Data-Plane Architecture
type: spec
owner: tim
solve_for: Canonical rule for what data goes into CIP infrastructure vs Foundry/venture
  infrastructure. The 'hard split' architectural boundary.
stage_label: adopt
domain: meta
version: '1.1'
created: '2026-05-19'
last_modified: '2026-09-06'
last_reviewed: '2026-09-06'
review_cadence: 90
authority_decisions:
- d83c7e1d
- 859c0bd9
- c575c81c
- 9c866f55
---

# CIP Hard Split — Data-Plane Architecture

> **The rule:** CIP product owns its own Pinecone index, R2 prefix, and embedding pipeline. Tenant isolation happens **within** CIP infrastructure (namespace per tenant in CIP-Pinecone; path prefix per tenant in CIP-R2). Foundry / venture-side stacks serve **only NON-CIP data** (agent memory, internal Foundry knowledge, venture-specific docs).
>
> The split is by **data type**, not by deployment topology.

## Why this exists

CIP is a product with its own roadmap (Stage 1 → Stage 2 → Stage 3 graduation per VISION). For CIP to be sellable externally — and for daily operations to be uniform — its data plane has to be self-contained. The alternative (CIP routes content into Foundry's shared knowledge subsystem) couples CIP to FAS infrastructure that won't exist for external customers and makes operations less uniform (multiple Pinecones, multiple R2s, multiple credential sets, multiple monitoring stories).

This doc is the canonical reference. **If a contributor is deciding "where does this new content live?", the answer is in §1.**

## §1 — Data classification rule

### Goes into CIP infrastructure

| Data | Layer | Storage |
|------|-------|---------|
| CRM contacts, companies, deals, tickets | Structured | `cip_*` tables in Postgres |
| Customer support conversations (Zendesk ticket comments) | Structured + Knowledge | `cip_ticket_comments` + CIP-Pinecone |
| CRM engagement bodies (HubSpot notes, meetings, tasks) | Structured + Knowledge | `cip_engagements` + CIP-Pinecone |
| Call transcripts (Firefly via HubSpot, future direct Firefly connector) | Knowledge | CIP-Pinecone, content in `cip_engagements` |
| Customer-uploaded files (Zendesk attachments, HubSpot files, contracts) | Originals | CIP-R2 (`cip-originals/...`) + `cip_files` row |
| Tenant-uploaded knowledge docs (SOPs, training material — future capability) | Knowledge + Originals | CIP-R2 + CIP-Pinecone |
| Embeddings of any of the above | Knowledge | CIP-Pinecone (`cip__{tenant}__{client}` namespace) |
| Property catalog / glossary | Metadata | `cip_connector_property_registry` |
| Lens views / queryable surfaces | Lens | `cip_views` + `lens_*` SQL views |

**Rule of thumb:** if it's data ABOUT a client of a Foundry venture, it goes into CIP.

### Goes into Foundry / venture infrastructure

| Data | System | Storage |
|------|--------|---------|
| Agent conversation memory | Foundry memory subsystem | `memory_chunks` + Foundry-Pinecone |
| Internal Foundry knowledge (SOPs Foundry agents read, research, training material) | Foundry knowledge subsystem | `knowledge_chunks` + Foundry-Pinecone (`foundry-agent-system` index, 1024d) |
| Per-venture internal docs (venture playbooks, internal research) | Venture's own stack (if any) | Venture-specific Pinecone / R2 (if provisioned) |
| PM data (projects, scopes, decisions) | PM subsystem | PM tables (separate schema) |
| Engineering / ops data (model directory, access routes, fleet inventory) | Various | Various Foundry tables |

**Rule of thumb:** if it's data ABOUT Foundry, its ventures, or how they operate internally, it does NOT go into CIP.

### Edge cases

| Case | Decision |
|---|---|
| A Foundry agent uses CIP via MCP — where does its conversation log live? | Foundry memory subsystem. The agent's interactions are internal to FAS; CIP is just a data source the agent queries. |
| A venture wants to upload their internal SOPs and have a CIP agent answer questions about them | CIP — but file under "tenant-uploaded knowledge docs". The venture is acting as a CIP tenant whose CLIENT is itself. This is the future tenant-document-upload capability. |
| Foundry's internal `knowledge_chunks` has chunks tagged `cip_doc` from earlier work | These were a legacy bridge attempt (pre-hard-split). Migrate OUT of Foundry-Knowledge, INTO the CIP tenant's namespace on the fabric (Path B), drop the `cip_*` source_type values from Foundry. The destination changed 2026-09-06 (see §2.5); the rule that this data does not belong in Foundry's own plane did not change. |
| A connector emits both metadata AND a recording URL (HubSpot Call with hs_call_recording_url) | Structured fields go to `cip_engagements`; recording URL gets staged to CIP-R2 (when Layer 3 ships) and its `cip_files` row links back to the engagement. |
| Cross-tenant lookups (e.g., "show me all CIP content matching X across all tenants") | Foundry agents query via MCP bridge tool with explicit tenant_id list. Pinecone namespace isolation means each tenant query is separate; aggregation happens app-side. |

## §2 — CIP infrastructure

### CIP-Pinecone

> **Retiring under Path B, see §2.5.** Ratified 2026-09-06 (FAS PM decision `9c866f55`). CIP-Pinecone stops being the hot-retrieval surface once the per-tenant cutover completes; it is decommissioned after the FR-53 coexistence bridge (60-90 days). Until then it keeps serving reads exactly as described below.

- **Index name**: `foundry-cip`
- **Host**: `foundry-cip-h705p9t.svc.aped-4627-b74a.pinecone.io`
- **Dimension**: 2,560 (full Qwen3-Embedding-4B Q8_0 output)
- **Metric**: cosine
- **Region**: aws/us-east-1 (serverless)
- **Namespace pattern**: `cip__{tenant_id}__{client_id}` (or `cip__{tenant_id}___tenant` for tenant-level content without a client)
- **Created**: 2026-05-19 via Pinecone API (`POST /indexes`)
- **Env vars**:
  - `CIP_PINECONE_API_KEY` — shared with Foundry account, different index
  - `CIP_PINECONE_INDEX_HOST` — the canonical URL above
  - `CIP_PINECONE_INDEX_NAME` — `foundry-cip`

### CIP-R2
- **Bucket**: `foundry-agent-system` (shared R2 bucket, Stage 1/2)
- **Prefix**: `cip-originals/` — all CIP-owned files live under this prefix
- **Full path pattern**: `cip-originals/{tenant_uuid}/{client_uuid}/{source_connector}/{source_id}/{file_name}`
- **Stage 3 evolution**: enterprise customers can graduate to dedicated buckets via `CIP_R2_BUCKET_NAME` env var without code changes
- **Env vars**:
  - `CIP_R2_BUCKET_NAME`, `CIP_R2_ACCESS_KEY_ID`, `CIP_R2_SECRET_ACCESS_KEY`, `CIP_R2_ENDPOINT_URL`, `CIP_R2_PATH_PREFIX`

### CIP-Embedding

> **Retiring under Path B, see §2.5.** Ratified 2026-09-06 (FAS PM decision `9c866f55`). The CIP embedding pipeline is superseded by ingestion re-pointed at the FAS knowledge fabric; it is retired third in the cutover order, after the FR-53 coexistence bridge (60-90 days). Until then it keeps producing embeddings exactly as described below.

- **Model**: Qwen3-Embedding-4B Q8_0 (2,560 dim)
- **Endpoint**: server-b Ollama via Tailscale (`http://100.100.10.110:11434`) or tunneled hostname
- **Fallback**: OpenRouter `qwen/qwen3-embedding-4b` (1024 dim — incompatible with CIP-Pinecone; fallback is for DEGRADED reads, not writes)
- **Client**: `cip.integration_mesh.clients.EmbeddingClient` (thin HTTP wrapper per Tim 2026-05-17 option A)

### CIP-Postgres (cip_* tables)
- **Today**: shared Railway Postgres instance with Foundry's other tables
- **Phase 8 evolution**: extracted to dedicated PostgreSQL instance per Phase 0 decision #1
- **Tenant isolation**: RLS on every `cip_*` table via `app.current_tenant` GUC
- **Knowledge fabric staging**: `cip_knowledge_chunks` table still carries embeddings as the source-of-truth + audit layer; CIP-Pinecone is the hot-retrieval surface. (Two stores; CIP-Pinecone is derived from `cip_knowledge_chunks`.)
  **Superseded 2026-09-06 (Path B), see §2.5.** The FAS knowledge fabric (`kf_*` schema) becomes the hot-retrieval surface as each tenant cuts over; CIP-Pinecone's role above is what is being replaced. `cip_knowledge_chunks` keeps its audit/staging role for the duration of the FR-53 bridge. Its disposition after the bridge (retained as permanent audit trail vs. retired once the fabric's own audit layer is trusted) is not decided here; it is FAS S6-D, task 38.

## §2.5 — Knowledge-host relocation (Path B, ratified 2026-09-06)

Tim ruled 2026-09-06 (FAS PM decision `9c866f55`, "Path B") that the KNOWLEDGE layer of CIP infrastructure relocates. Nothing else in this document changes. This section states what moves, what does not, the order it moves in, how tenant isolation is preserved at the new host, and how this ruling relates to other canon.

### What moves

The canonical host for CIP knowledge (chunks, embeddings, retrieval) becomes the FAS knowledge fabric: the `kf_*` schema on the shared Postgres, using pgvector, addressed through one fabric router and one grants model. This is a relocation of the host, not a fragmentation of the retrieval surface. CIP-Pinecone and CIP-Embedding (§2 above) are the infrastructure being replaced.

### The retrieval API does not fork

`foundry_mcp_cip_semantic_search` (§4) keeps its name and its signature. Its implementation re-points at the fabric, per tenant, canary-gated. There is no second retrieval surface for CIP content; callers of the MCP tool see no interface change.

### Cutover order

1. **Consumer cutover, per tenant, canary-gated.** `foundry_mcp_cip_semantic_search` re-points at the fabric one tenant at a time behind a canary gate. This step is mandatory and comes first: nothing else in this relocation proceeds ahead of proving reads are correct against the new host for a given tenant.
2. **Ingestion re-point.** New content for a cutover tenant is embedded and written to the fabric instead of to CIP-Embedding / CIP-Pinecone.
3. **CIP-Pinecone and CIP-Embedding retirement.** Both retire after the FR-53 coexistence bridge (60-90 days), which runs so that dual-write and dual-read paths can be compared before the legacy infrastructure is switched off.

### What does NOT move

- CIP-R2 originals (§2, `cip-originals/...`) stay the immutable record. Unchanged.
- `cip_files`: unchanged.
- All structured `cip_*` tables (CRM contacts, companies, deals, tickets, engagements, property registry, etc.): unchanged.
- Lens views (`cip_views` + `lens_*` SQL views): unchanged.
- RLS on `cip_*` tables: unchanged.
- CIP-SPEC-010 §1 (the data classification rule: client-of-a-venture data goes into CIP): unchanged. Path B is a hosting-mechanics decision, not a reclassification of what counts as CIP data.

### Tenant isolation on the fabric

The fabric enforces tenant isolation the same way FAS's own knowledge does, applied to CIP tenants as well:

- `tenant_id` on every row.
- Grants pushdown: a query only reaches rows its caller's grants cover.
- A fail-closed post-check after retrieval, so a grants-model gap fails the read rather than silently over-returning.
- Row-level security: threaded in shadow mode before GATE B, then forced (enforced, not advisory) after GATE B.

### Relationship to other canon

- **JOS-D0076** ("CIP as the canonical KB host for the portfolio") stays parked and unamended. Its purpose is to forbid parallel retrieval surfaces across the portfolio, not to pin the hosting mechanics underneath a single surface. Path B keeps one retrieval surface (`foundry_mcp_cip_semantic_search`) and one grants model; it changes what sits behind that surface. Confirmed by the JOS trunk session reading D0076 on `origin/main`.
- **CIP-SPEC-010 §1** is unchanged, per above.
- **FAS PM decision `9c866f55`** is this ruling's authority (Path B itself).
- **FAS decision `03865891`** (the audience-tier classification ruling) is a separate, unrelated decision and is unaffected by this section.

### Consequences for tooling (not fixed in this amendment)

`scripts/generate_cip_cheatsheet.py`'s `_is_drift` function and its `_pinecone_inventory` helper assume CIP-Pinecone is the hot-retrieval surface, and on that assumption treat venture rows appearing on the Foundry side as drift. Under Path B that assumption stops holding: once a tenant is cut over, venture rows living on the FAS fabric under a CIP-registered source are the correct, expected state, not drift. `generate_cip_cheatsheet.py` and FAS's `cip_hard_split_drift_sweep` both need their drift rule updated to account for this before the first venture is migrated to the fabric. This amendment does not change the script; it flags the gap so the update happens before it causes false drift alarms.

## §3 — Foundry / venture infrastructure (off-limits to CIP)

### Foundry-Pinecone
- **Index name**: `foundry-agent-system`
- **Host**: `foundry-agent-system-h705p9t.svc.aped-4627-b74a.pinecone.io`
- **Dimension**: 1024 (Qwen3 matryoshka-truncated)
- **Use**: agent memory (`memory_chunks`) + Foundry knowledge subsystem (`knowledge_chunks`)
- **CIP relationship**: CIP does NOT write to this index. CIP does NOT read from this index. Period.

### Foundry-R2
- **Bucket**: `foundry-agent-system`
- **Use**: agent assets, venture artifacts, PM attachments — paths NOT prefixed with `cip-originals/`
- **CIP relationship**: CIP shares the bucket but uses only the `cip-originals/` prefix. Operations are scoped to that prefix.

### Venture-specific stacks (if any)
- Venture-Trader, Venture-EcomLever-internal, etc. may have their own Pinecone projects or R2 buckets for venture-internal use. These are off-limits to CIP. CIP gets venture data via connectors (Zendesk, HubSpot) — NOT by reading from venture-internal storage.

## §4 — The bridge pattern (how Foundry agents access CIP content)

Foundry agents that need to query CIP content do NOT share Pinecone with CIP. Instead, FAS exposes an MCP tool:

```
foundry_mcp_cip_semantic_search(
    tenant_id: UUID,
    client_id: UUID | None,
    query: str,
    top_k: int = 10,
    source_kinds: list[str] | None = None,
    rerank: bool = True,
) -> list[CIPSearchHit]
```

Implementation calls `cip.integration_mesh.knowledge.KnowledgeRetriever` against CIP-Pinecone with the specified namespace. Same pattern as `foundry_mcp_pm_*` for the PM subsystem.

**Future:** as more CIP capabilities ship, FAS gets more bridge tools: `foundry_mcp_cip_manifest`, `foundry_mcp_cip_query_lens`, `foundry_mcp_cip_files_get`, etc.

## §5 — Stage 1 / 2 / 3 implications

| Stage | What "CIP infrastructure" means |
|-------|-------------------------------|
| **Stage 1** (now — internal tool, single tenant) | One CIP-Pinecone index + one R2 prefix on shared bucket. Wayward lives in `cip__dec814db__661ecab4`. |
| **Stage 2** (multi-tenant platform, Foundry + Rocky Ridge) | Same CIP-Pinecone index, more namespaces. Same R2 bucket, more prefixes. Each tenant's data plane is namespace-scoped within shared infrastructure. |
| **Stage 3** (external customers) | Each enterprise customer can optionally graduate to (a) dedicated Pinecone PROJECT, (b) dedicated R2 BUCKET, (c) dedicated Postgres INSTANCE. Code changes are env-var-only (`CIP_PINECONE_INDEX_HOST`, `CIP_R2_BUCKET_NAME`, `DATABASE_URL`). The namespace pattern stays the same; everything moves cleanly. |

## §6 — Migration history

| Date | Migration | Notes |
|------|-----------|-------|
| 2026-05-11 | `458fb208` Knowledge taxonomy CHECK constraint extended | Permitted `cip_doc / cip_ticket / cip_note / cip_fixture_*` source_types in Foundry-Knowledge — **legacy bridge attempt, superseded by hard split**. Any chunks under those source_types in Foundry-Knowledge should be migrated to CIP-Pinecone + dropped from Foundry-Knowledge. |
| 2026-05-17 | Layer 2 v1 shipped (Postgres-native vectors) | `cip_knowledge_chunks` table, 31,840 vectors for Wayward. Storage choice was pragmatic given missing credentials at the time. |
| 2026-05-19 | CIP-Pinecone provisioned + hard-split locked | Decision `d83c7e1d`. CIP-Pinecone index created, env vars set, this doc written. |
| 2026-05-19 | Vectors migrated Postgres → CIP-Pinecone | Via `scripts/migrate_chunks_postgres_to_pinecone.py`. Postgres remains source-of-truth + staging; Pinecone is hot-retrieval. |
| (pending) | Foundry-Knowledge CIP-tagged chunks migrated out | Scope filed in PM; depends on per-venture audit. |

## §7 — Cross-references

- VISION.md (CIP-FW-001) — top-level product vision
- ARCHITECTURE.md (CIP-SPEC-003) — overall architecture
- ROADMAP.md (CIP-SPEC-008) — Stage 1/2/3 progression
- PROPERTY-GLOSSARY-PATTERN.md (CIP-SOP-016) — semantic layer for connector data
- TENANT-ONBOARDING-CHECKLIST.md (CIP-SOP-010) — operator runbook
- PM decision `d83c7e1d` — Hard split (this doc's authority decision)
- PM decision `c575c81c` — Canonical tenant UUIDs (EcomLever + Wayward)
- PM decision `859c0bd9` — JOS adoption
