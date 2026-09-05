---
id: CIP-SPEC-014
uuid: 85a50050-5e98-4fc8-b8d3-c9e3c842e113
title: Document Source Contract
type: contract
owner: tim
solve_for: Define what a document library IS in connector terms, so any tenant's documents onboard by the same path as a SaaS source instead of through a per-tenant script.
stage_label: trial
domain: eng
version: '1.0'
created: '2026-09-04'
last_modified: '2026-09-04'
last_reviewed: '2026-09-04'
review_cadence: 180
references:
  - id: CIP-SOP-001
    relationship: extends
  - id: CIP-SPEC-010
    relationship: builds-on
---

# Document Source Contract

## Why this exists

CIP's pitch is one platform serving a venture's data needs through a roster of
connectors that grows as sources arrive. That is true for structured sources.
It has not been true for documents.

Rocky Ridge's corpus (65 files, 4,404 chunks) reached `cip_knowledge_chunks`
through `scripts/migrate_rocky_ridge_to_cip.py`, a one-off written for the
2026-05-19 Hard Split and hardcoded to one tenant. There is no "ingest
documents for tenant X". The corpus has not moved since 2026-05-22, and nothing
noticed, because that path writes no heartbeat.

This document answers the four questions that decide whether the replacement is
a reusable connector or a second one-off.

## The finding that shapes everything below

**Documents already fit the Protocol. The script did not bypass a limitation;
it bypassed the contract.**

`CIPMapper` has carried a first-class method for this since M2:

```python
def ingest_as_knowledge(self, record: dict[str, object]) -> list[KnowledgeText]: ...
```

D-133 locked its return shape precisely so that "M5 wires real ingestion
against the same shape". The orchestrator already calls it, finalizes the five
required metadata keys, validates at the boundary, and hands the result to
`ingest_texts_noop`. Every part of that seam is built. Only the *body* of
`ingest_texts_noop` is still the M2 stub, and `cip/integration_mesh/knowledge/`
already contains the chunker, indexer and embedding client that body needs.

So this is not a new pipeline. It is a connector, a mapper, and replacing one
function body.

## Ruling 1: the unit of sync is the FILE

A record is one file. Chunks are a derived write.

`stream_records()` yields file records; `map()` emits a `CIPRow` targeting
`cip_files`; `ingest_as_knowledge()` returns that file's chunks as
`KnowledgeText`. This is the same shape a SaaS connector already has, where one
fetched object becomes one row plus several knowledge texts.

**Rejected: chunk-as-record.** It inverts the relationship the Protocol
expresses, gives `map()` nothing natural to write, and makes the idempotency
key a position rather than a content identity, which is the specific mistake
the script made.

## Ruling 2: cursor is R2 LastModified, identity is content_hash

These are two different jobs and the script conflated them.

`incremental_key(record)` must return a `datetime`. R2 object listings carry
`LastModified`, so the Protocol's cursor contract is satisfiable as written and
no Protocol change is needed.

`LastModified` decides what to *look at*. `content_hash` (sha256, already
computed) decides whether to *do work*. A file whose timestamp moved but whose
bytes did not is skipped after a hash comparison and costs no embedding spend.

**This is where the script was wrong**, and it is worth stating precisely
because the failure is silent. Its rerun guard read the set of `chunk_index`
values already stored and processed only the indices not present. The key was
chunk *position*. A file whose bytes changed but which still produced the same
number of chunks was skipped entirely, counted as processed, and its stale text
stayed retrievable forever. A file that shrank left its surplus tail chunks in
place. `content_hash` was computed and never consulted.

**Rejected: full re-embed every run.** Correct but wasteful, and it would make
a scheduled run expensive enough that nobody would schedule it.

## Ruling 3: deletion tombstones the FILE and deletes its chunks

**LOCKED by Tim, 2026-09-04** (PM decisions `505da403-6a0a-437a-ac90-e369e684ee5c`
then amended by `7d1c0148-e53e-4c1b-8ee8-d43fa5b58902`).

A file that vanishes upstream is tombstoned: `cip_files.tombstoned_at` is set
and the row survives with its `r2_path` and `sha256`, so the audit trail records
exactly what was removed and when. **Its derived chunks are DELETED** from
`cip_knowledge_chunks` and from the Pinecone namespace, scoped by `source_kind`.

### Correcting the first version of this ruling

As first written, this ruling said "every retrieval path filters tombstoned
chunks". That was unimplementable and shipped anyway, in this document, in
`cip_177`, and in the connector built against it. The retriever queries
`cip_knowledge_chunks` directly and never joins `cip_files`, where
`tombstoned_at` lives. There was no predicate to add. All three pieces reasoned
about the file record; none checked what retrieval actually reads.

Deleting the derived rows makes the property **structural** rather than a rule
every future query has to remember. Retrieval needs no change, and a retrieval
path written next year cannot forget to honour something it never has to do.
That is the same reasoning that unified the duplicated rerank swallow: an
obligation copied into N places is an obligation that will be dropped from one
of them.

Chunks are derived data. If the file returns, re-ingest regenerates them.

### What this obliges

1. Every delete is scoped by `source_kind`. `cip_knowledge_chunks` has a second
   producer (row-derived chunks under `cip_ticket_comment`,
   `cip_engagement_*`, `cip_ticket`); an unscoped delete destroys its rows.
2. **Pinecone is deleted BEFORE Postgres.** The two are separate calls and the
   Pinecone one is the one that fails or gets forgotten. Postgres-first would,
   on a Pinecone failure, leave the database saying the chunks are gone while a
   vector search still returned them: retrievable content nothing knows about,
   which is worse than not deleting because it looks correct. This order fails
   safe.
3. The vector id used to delete must be the id used to upsert. Both come from
   `knowledge.tombstone.vector_id_for` so they cannot drift; a mismatch leaves
   orphaned vectors no delete will ever find.
4. A purge without a Pinecone client is permitted but must WARN, because it
   leaves the vectors retrievable.

**Rejected: retrieval-side filtering**, for the reason above. **Rejected: hard
delete of the file record**, which loses the audit trail. **Rejected:
denormalising the flag onto chunks**, which leaves two tables to keep in step
with nothing enforcing it.

## Ruling 4: addressing is a library list, and it absorbs the source registry

A tenant has zero or more libraries. Each is addressed explicitly rather than
implied by tenant:

```yaml
document_libraries:
  - library_id: rocky-ridge-research-library
    name: Rocky Ridge Research Library      # human-readable, shown in listings
    r2_prefix: 80252ad9-72d5-4c5a-b273-af804224872e/knowledge/
    source_kind: cip_client_document
    client_id: null                          # null = tenant-wide
```

Adding a library is configuration. Adding a *tenant* is configuration. That is
the exit bar for this whole effort: a new tenant with a new document library
onboards with zero code changes.

**This subsumes the `cip_knowledge_sources` registry** proposed separately (PM
scope `bafaf134`, superseded 2026-09-04). That scope wanted an explicit registry
so "what documents do we have for Rocky Ridge" is answerable without writing
SQL. A connector that maintains its library row transactionally on each run
produces the same answer, plus freshness, for nothing. Two mechanisms answering
one question is the outcome to avoid.

### source_kind

`cip_client_document` is retained as the default. The richer taxonomy proposed
in PM scope `6f29d7a4` (`cip_sop`, `cip_contract`, `cip_training`) is allowed
per library via the `source_kind` key above, rather than being inferred.

The constraint that matters: **`cip_knowledge_chunks` already has a second
producer.** `knowledge/indexer.py` writes row-derived chunks under
`cip_ticket_comment`, `cip_engagement_note`, `cip_engagement_meeting`,
`cip_engagement_task` and `cip_ticket`. `source_kind` is the only discriminator
between the two, and it is an open enum. Every document-side delete, tombstone
or rewrite MUST be scoped by `source_kind`, or it destroys the other producer's
rows.

Retrieval will return a mix of both. That is intended: a chatbot answering from
a venture's knowledge should see its documents and its ticket history. Results
carry `source_kind` so a caller can scope when it wants to.

## Pull now, push later

The connector is **pull**: enumerate an R2 prefix, diff by `content_hash`.

PM scope `6f29d7a4` also specified a **push** ingress (`/cip/files/upload`, or
an MCP tool) for ad-hoc uploads. Push is deferred, not rejected. It lands on the
same pipeline: an upload writes the object and the `cip_files` row, and the next
connector run picks it up by hash exactly as it would any other file. Deciding
pull first keeps one ingestion path until there is a reason for two.

## What must not regress

**Image captioning.** Nine of Rocky Ridge's 65 files are JPEGs, and they are not
dead weight: they were vision-captioned at ingest into 26 chunks of real
description (annotated aerial maps with property boundaries, road labels, scale
bars and management zones). A port that reduces to text extraction silently
loses them. The mime-split test must assert image files still produce chunks.

**Both stores agree.** For any file, chunk count in Postgres and vector count in
its Pinecone namespace must match, and disagreement must be detectable.

## Verification

The design is satisfied when a reviewer, given this document and
`CONNECTOR-AUTHORING-GUIDE.md`, answers "none" to: *what code changes are
required to onboard a new tenant with a new document library?*

Concretely, the next task builds against:

| Thing | Value |
|---|---|
| Module | `cip/integration_mesh/connectors/document_library/` |
| Config key | `document_libraries` |
| Idempotency key | `content_hash` (sha256) |
| Cursor | R2 `LastModified` |
| Default source_kind | `cip_client_document` |

## Open, deliberately

- **Chunk-level provenance for captions.** A caption is model-generated text
  about an image, not the image. Whether retrieval should mark it as such is a
  quality question the retrieval eval should answer, not a contract question.
- **Re-caption on model change.** The same class of problem as re-embedding, and
  it should follow whatever policy the embedding version key establishes.
