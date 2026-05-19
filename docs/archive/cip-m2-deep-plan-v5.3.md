---
id: CIP-SPEC-903
uuid: 76013d36-8c6d-4705-ac12-3c286bcbee0e
title: CIP Phase 1 — Milestone 2 Deep Implementation Plan
type: spec
owner: Atlas (author) / Claude Code (executor)
solve_for: Retired/archived artifact retained for audit and historical context — cip-m2-deep-plan-v5.3.md.
stage_label: retire
domain: meta
version: v5.3
created: '2026-05-05'
last_modified: '2026-04-29'
last_reviewed: '2026-05-19'
review_cadence: 9999
milestone: Phase-1-M2
---

# CIP Phase 1 — Milestone 2 Deep Implementation Plan
## Generic Connector Framework + Conformance Harness

> **Scope:** Junior-dev-day-one reference for shipping M2 of CIP Phase 1. Architecture decisions, file-by-file signatures, sequencing, edge cases, acceptance criteria, doc fill-ins.
>
> **Status (v5.3, 2026-04-29):** Ready for implementation inside `Foundry-Studio/foundry-cip` (HEAD `b7136717`, public, CI green). 7 QC rounds complete: Round 1 (3 internal subagents) → Round 2 (Verifier + Behavioral Delta) → Round 3 (LLM expert panel — 7 expert + 5 research models) → Round 4 (LLM expert panel surfaced 6 v5 patches) → Round 5 (post-execution Verifier on extraction plan v4) → Round 6 (LLM expert panel — Tim accepted Calls A/B/C) → Round 7 (Verifier surfaced 1 BLOCKER + 6 HIGH on v4.2; all fixed). Plan landed on D-152 after a four-collision D-number renumber chain (D-142 → D-143 → D-146 → D-152 — the latter is the canonical CIP extraction lock per `docs/DECISION-LOG.md` line 4395).
>
> **Precondition (LANDED 2026-04-29):** foundry-cip repo extraction is complete. Repo lives at https://github.com/Foundry-Studio/foundry-cip; CI green at HEAD `b7136717`; monorepo consumes via `pip install foundry-cip @ git+SHA` per FND-S13 lockfile discipline. All paths in this plan assume the post-extraction layout — `cip/integration_mesh/` is the canonical home (per D-118 semantic ownership + D-146 physical location).
>
> **v2 revision summary:** See `cip-m2-plan-atlas-assessment.md` for the full QC-findings triage. Sections changed in v2: §1.1 (new — env preconditions), §3 (persistence folded into integration_mesh), §4.1 (KnowledgeText + ALLOWED_CIP_TABLES locked), §4.3 (TokenBucket lock fix), §4.5 (persister SQLAlchemyError translation + allowlist), §4.7 (recorder owns its own connection), §4.8 (single stream_records call, protocol validator, cursor write in batch txn, retry budget, dedupe, tz-aware requirement, safety window), §5.1.1 (new — canonical fixtures), §8.13 (new — out of scope), §9 (verification methods spelled out), §13 (open questions resolved; pre-locked design choices referenced).
>
> **v3 revision summary:** Fixes 10 CRITICAL mechanical bugs + 8 HIGH + 15 MED/LOW from QC Round 2. Also resolves two architectural loose ends: R2-A1 SQLAlchemy 2.x transaction idiom (orchestrator now takes an Engine, creates a per-batch Session via `with Session(engine) as db, db.begin():`), R2-A2 `_finalize()` moved AFTER the `with recorder:` block so it reads finalized fields the recorder sets in `__exit__`. D-numbers re-pointed to next-free slots: **D-133** (KnowledgeText return type), **D-134** (Protocol-based connector framework), **D-135** (SCD Type 2 at application layer) — prior D-130/D-131/D-132 references in v2 were wrong; those numbers now belong to unrelated PM / task-dispatcher decisions that landed between v2 and v3. Migration slots renumbered: `cip_09_rename_sync_runs_metadata` → `cip_11_rename_sync_runs_metadata`, `cip_10_sync_runs_counter_split` → `cip_12_sync_runs_counter_split` (SPEC §2 AC #1 reserves `cip_09` for Phase 3 cross-tenant grants and `cip_10` is reserved adjacent). Counter name sweep completed: all `rows_ingested` / `rows_skipped` references now use the M-24 split (`rows_received`, `rows_created`, `rows_updated`, `rows_skipped_unchanged`, `rows_skipped_drift`, `rows_skipped_duplicate`, `rows_history`).
>
> **v4 revision summary:** Round 3 QC was an LLM panel (7 expert + 5 research models). Two architectural commitments confirmed by 5/7 expert + 3/3 useful research models: R2-A1 (Engine signature) + R2-A2 (`_finalize` after `with`). Two qwen models pushed savepoint pattern, rejected by stronger models on lock-duration grounds. Three CRITICAL panel findings + four HIGH triaged through CTO lens against actual Foundry deployment context (see `cip-m2-plan-atlas-assessment.md` Round 3 section): (1) `SET LOCAL` + PgBouncer concern is moot because Foundry doesn't use PgBouncer — but the underlying CORRECTNESS issue (forgetting `apply_tenant_context()` on auxiliary connection paths) is real and gets a new conformance test (Test 7 — post-commit RLS isolation) + docstring HOWTO showing the `event.listens_for(Engine, "begin")` pattern for ventures wanting belt-and-suspenders. (2) FOR UPDATE deadlock isn't real at single-tenant scale (M2's first 6+ months) — but cheap deterministic ORDER BY source_id added now to prevent the deadlock class entirely; advisory-lock dual-run prevention deferred to M3 with explicit §8.13 row. (3) Connection-pool exhaustion at 100-tenant scale isn't M2's problem — Foundry baseline pool is 5+10 across the platform; documented in §8.13 deferral. Plus four refinements: per-batch Session creation now uses `autoflush=False, expire_on_commit=False` to prevent mid-batch implicit-flush deadlocks; `validate_connector_shape()` docstring updated to address decorated `stream_records` edge case (defer beartype dep — 3-of-7 expert models say defer); new optional `cursor_safety_window_seconds: int` Protocol property for per-connector override (300s default unchanged); §13 open questions reframed with empirical findings (Airbyte zendesk uses 180s lookback; 300s is "defensible heuristic, not empirically grounded"). Net change: ~150 lines added, no architecture reshape.
>
> **v5 revision summary (2026-04-29):** Round-4 LLM expert panel (7 models on the v4 plan) surfaced 3 SEV-5 mandatory + 3 SEV-3-4 strongly-recommended fixes. All 6 folded in. Plus one architectural amendment to D-133 (KnowledgeText.metadata shape).
>
> **The 6 v5 patches:**
>
> 1. **PATCH-Q4 (SEV-5, mandatory) — `SyncRunRecorder.__exit__` does column-minimal UPDATE.** The v4 recorder's `__exit__` writes the FULL audit row back, which clobbers `cursor_state` if a separate transaction wrote a cursor advance between `__enter__` and `__exit__`. 5 of 7 models converged on this exact one-question bet — strongest single signal in the round. v5 fix: `__exit__` UPDATEs only the columns the recorder OWNS (`status`, `ended_at`, `error_detail`, the row-counter fields) and explicitly EXCLUDES `cursor_state`. The orchestrator main loop already writes `cursor_state` inside the per-batch transaction (§4.8 line ~1431); recorder must not touch it. See §4.7 patch.
>
> 2. **PATCH-NR-1 (SEV-5, mandatory) — `SET LOCAL app.current_tenant` resets via `PoolEvents.checkout` listener.** Foundry doesn't use PgBouncer (per Round-3 ruling), but a stale `app.current_tenant` GUC can survive across pool checkouts on a SQLAlchemy QueuePool too — `SET LOCAL` resets at transaction boundary, but if a caller holds a connection across multiple transactions (rare but legal) the GUC value from the last `SET LOCAL` persists until the next `SET LOCAL` overwrites it. v5 fix: register a `event.listens_for(Engine, "checkout")` listener that issues `RESET app.current_tenant` (or `SELECT set_config('app.current_tenant', '', false)`) on every checkout. Belt-and-suspenders to the explicit `apply_tenant_context()` calls. See §4.7 + new §1.2 (Engine setup).
>
> 3. **PATCH-Q3 (SEV-5, mandatory) — `inspect.unwrap()` chain in `validate_connector_shape()`.** v4's docstring noted the `__wrapped__` decorator-chain edge case but kept the simple `inspect.isgeneratorfunction(connector.stream_records)` check. Round-4 panel: deferring this to v5 was right at v4 time, but with v5 in flight, the actual fix is one line — replace the direct check with `inspect.isgeneratorfunction(inspect.unwrap(connector.stream_records))`. `inspect.unwrap()` walks the entire `__wrapped__` chain (recursive). Connectors using `@functools.wraps`-correct decorators now pass; connectors using broken decorators still fail with a clear error. See §4.11 patch.
>
> 4. **PATCH-Q6 (SEV-3, strongly-recommended) — `KnowledgeText.metadata` becomes `KnowledgeTextMetadata` TypedDict.** D-133 amended 2026-04-29 (see DECISION-LOG.md). 6 of 7 panel models flagged `metadata: dict[str, object]` as a semver hole at the framework boundary. **Final shape (refined per Round-6 Call A — supersedes the line below):** `class KnowledgeTextMetadata(TypedDict, total=False)` with the same key set; required-keys-at-boundary enforcement moved to `validate_knowledge_text_metadata()` orchestrator-side validator. Mappers emit only what they know (often just `source_id`); orchestrator finalizes operational metadata (tenant_id, source_system, etc.) before validator runs. Eliminates the "lying mock" anti-pattern Kimi-k2.5 flagged in Round-6. **The original v5 description below is preserved for audit context but superseded by Call A:** ~~`class KnowledgeTextMetadata(TypedDict)` with required core keys + `NotRequired` extensions; M2 MockMapper's `metadata={}` becomes `metadata={"source_id": …, "source_system": "fixture", "extracted_at": _utcnow(), "tenant_id": tid, "connector_version": "0.0.0"}`~~. See §4.1 binding code + DECISION-LOG.md D-133 Amendment block (Round-6 refinement note).
>
> 5. **PATCH-NR-2 (SEV-4, strongly-recommended) — `try/finally` wrapper around the orchestrator's `stream_records()` generator iteration.** v4's main loop iterates the generator without a try/finally — if the orchestrator raises mid-iteration (e.g., a TimezoneNaiveError on batch 7 of 50), the generator's underlying network connection / pagination cursor leaks. v5 fix: wrap the `for batch in connector.stream_records(...)` block in `try: … finally: stream.close()` after capturing the generator handle to a local variable. See §4.8 patch.
>
> 6. **PATCH-NR-7 (SEV-3, strongly-recommended) — tz-aware datetime validators on `KnowledgeText.metadata` + `CIPRow.fields` datetimes.** v4 has tz-naive rejection on `incremental_key()` only (line ~1412). Round-4 panel: extend the same guard to ANY datetime crossing the boundary into KnowledgeText.metadata or CIPRow.fields. v5 adds `_assert_tz_aware(value, field_name)` helper called by the orchestrator before metadata is finalized (§4.1) and by the persister before INSERT (§4.5). Same `TimezoneNaiveError` exception class. See §4.1 + §4.5 patches.
>
> **D-133 amendment (2026-04-29):** Outer `KnowledgeText` shape and return-type lock both stand. Inner `metadata` shape sharpens from open `dict[str, object]` to `KnowledgeTextMetadata` TypedDict. Migration cost is zero — M2 has not executed yet. See DECISION-LOG.md D-133 Amendment block.
>
> **Out of scope for v5 (v4 stands as written):** All other Round-3 panel decisions, all sections not enumerated in the 6 patches above. v5 is targeted; no architecture reshape.
>
> **v5.2 revision summary (Round-6 panel + Tim's three calls, 2026-04-29):** Round-6 LLM expert panel surfaced 3 architectural calls Tim delegated to Atlas with research-backed decision authority. All three resolved + applied:
>
> - **Call A — `KnowledgeText.metadata` shape REFINED to `total=False` + boundary validator.** PATCH-Q6 from v5 sharpened. Mappers emit only what they know; orchestrator finalizes operational metadata; `validate_knowledge_text_metadata()` enforces the 5 required core keys (`source_id`, `source_system`, `extracted_at`, `tenant_id`, `connector_version`) at the boundary into the Knowledge+Graph layer. New exception class `KnowledgeMetadataValidationError` (raised by validator). Eliminates the "lying mock" anti-pattern (Kimi-k2.5 / Qwen-235b / Local-qwen-a3b panel concern). DECISION-LOG.md D-133 Amendment block carries the full rationale.
> - **Call B — `foundry-cip-migrate` console wrapper RETIRED entirely.** v4's "reduce to `check` only" was insufficient per panel 5/6 consensus. Industry pattern (`python -m pip`, `python -m uv`) replaces with `python -m cip.db check`. `cip-cli.py` deleted. `cip-db.py` adds `_cli_main()` + `if __name__ == "__main__"`. `[project.scripts]` block removed from `pyproject.toml`. CLAUDE.md commands updated.
> - **Call C — uv workspaces alternative REJECTED.** 3/6 panel models pushed to skip the extraction in favor of monorepo + uv workspaces. Loses on the venture-repos-are-separate-Git-repos fact (Wayward, Rocky Ridge, Project Silk all live in separate repos under Foundry-Studio org; uv workspaces don't span Git boundaries). D-146 standalone-repo extraction stands.
>
> Plus 4 panel-surfaced BLOCKERs incorporated: pre-extraction full-history secrets scan on SOURCE monorepo (BLOCKER 1, applied to extraction plan), wheel content audit + run wheel-install CI from outside repo (BLOCKER 2), cross-pollution guard `FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS` allowlist (BLOCKER 3), idempotent rollback-extraction.sh (BLOCKER 4). All landed in extraction execution per `cip-extraction-plan-qc-2026-04-29.md` Round-6 archive.
>
> Plus 1 architectural detail — `KnowledgeText` outer shape stays `@dataclass(frozen=True)` (D-133 outer-shape lock unchanged); only the inner `metadata` shape sharpened.
>
> **v5.3 revision summary (Round-7 Verifier round, 2026-04-29):** post-extraction Verifier + Behavioral Delta surfaced 1 BLOCKER + 6 HIGH on the v4.2 plan + Round-6 patches. All 7 fixed:
>
> 1. **Verifier BLOCKER — gitleaks scan defined in plan but not enforced by extract-cip.sh.** Plan §1.5h was prose-only. Fixed: extract-cip.sh now runs `git clone --mirror` of source monorepo + `gitleaks detect --log-opts "--all"` BEFORE filter-repo. `CIP_SKIP_GITLEAKS=1` escape hatch documented.
> 2. **Verifier HIGH-A — orchestrator §4.8 didn't actually CALL `validate_knowledge_text_metadata()`.** Validator was defined but dead code. Fixed: orchestrator now finalizes missing metadata keys via `setdefault`, then calls validator BEFORE handing texts to `ingest_texts_noop()`. Validation errors are FATAL (re-raised); non-validation knowledge-hook errors remain non-fatal per D-067.
> 3. **Verifier HIGH-B — `__init__.py` exports incomplete.** Public API didn't expose `validate_knowledge_text_metadata`, `KNOWLEDGE_TEXT_REQUIRED_KEYS`, `KnowledgeMetadataValidationError`. Fixed: all three added to imports + `__all__`.
> 4. **Verifier HIGH (class duplication) — `KnowledgeMetadataValidationError` defined in BOTH base.py AND exceptions.py** (different classes; `isinstance` checks would fail across modules). Fixed: canonical home is `exceptions.py`; `base.py` validator does lazy import-at-use to avoid circular import.
> 5. **Verifier HIGH-C — Plan §6.10 still described 6 separate commits + pyproject.toml staging** (contradicting v4.1 atomic-commit fix and v4.1 pyproject.toml-no-touch fix). Fixed in extraction plan only — the §6.10 narrative now matches the script's atomic Commit 2 + FND-S13 lockfile flow.
> 6. **Verifier HIGH-D — Plan §6.2 omitted 9 RLS test deletions + conftest.py.** Fixed in extraction plan body.
> 7. **Verifier HIGH-F — §1.5c artifact list missing 7 required artifacts.** Fixed; matches the real script's REQUIRED_ARTIFACTS array.
>
> Behavioral Delta verdict: **0 confirmed test breakage** post-Round-6 patches. v4.1 atomic-commit fix preserved; v4.2 changes don't break any existing test assertion.
>
> 7 LOW-severity doc-drift items remain deferred (monorepo `alembic check`, sed-pattern narrative, §3.10 env.py snippet, CI test using deprecated alias, this revision-summary text inconsistency itself, M2 plan version label staleness — that one IS THIS bump). All non-functional.
>
> **Bottom line for CC at M2 dispatch:** the binding code blocks in §4 are correct and current. Top-of-file v5 PATCH-Q6 description was superseded by v5.2 Call A — the strikethrough above shows what was replaced. Trust the §4.1 + §5 + §4.8 + §4.10 binding code; the revision summary is audit-trail context.

---

## 0. TL;DR

M2 ships three things:

1. A **Protocol-defined connector + mapper contract** (`CIPConnector`, `CIPMapper`, `PropertyDescriptor`, `CIPRow`, `RateLimitPolicy`) that any future connector (FixtureConnector in M3, Zendesk/HubSpot in Phase 2, etc.) MUST satisfy.
2. A **sync orchestrator** that drives any Protocol-compliant connector end-to-end: `authenticate → stream_records (paginate) → map → persist (current + history) → knowledge-ingest hook → write cip_sync_runs row`.
3. A **six-test conformance harness** that validates any connector+mapper pair meets the contract: protocol compliance, incremental sync, property registry populated, SCD history, sync-run audit, tenant scoping.

No real connector ships in M2. M2's acceptance is: the framework runs end-to-end against a **mock Protocol implementation** inside the harness. The real FixtureConnector lands in M3.

**Repo target (LOCKED 2026-04-29):** `Foundry-Studio/foundry-cip` (public, HEAD `b7136717`, CI green). Extraction landed per D-146. Connector framework lives under `cip/integration_mesh/` (canonical post-D-146 physical path; D-118 semantic ownership "inside Integration Mesh" preserved). M2 build executes inside this repo; consumers (Foundry-Agent-System monorepo, future venture repos) consume via `pip install foundry-cip @ git+https://github.com/Foundry-Studio/foundry-cip.git@<sha>`.

**External dep:** `foundry-llm-roster` installed via git subpath (`pip install "foundry-llm-roster @ git+https://github.com/Foundry-Studio/foundry-agent-system.git#subdirectory=src/llm_roster"`). M2 itself does not call LLMs, but the knowledge-ingest hook signature must accept that LLM calls happen one layer down.

---

## 1.1 Environment Preconditions (v2)

Before Claude Code begins M2, these must be true in `foundry-cip`:

- **Python** `>=3.11` declared in `pyproject.toml` (`requires-python = ">=3.11"`). PEP 604 union types, `from __future__ import annotations`.
- **Postgres** `>=14` with `pgcrypto` extension enabled (for `gen_random_uuid()` in migrations; RLS + `SET LOCAL`).
- **Alembic** `>=1.13`. `alembic upgrade head` runs green on a fresh DB before any M2 code is written. Confirms task #59 (migrations move) actually landed correctly.
- **testcontainers-python** pinned to a recent release; Postgres image pinned `postgres:16-alpine`. CI + local dev share the same image tag.
- **pytest** `>=8`, **pytest-cov**, **mypy** `>=1.8` with strict-mode config committed as `mypy.ini`.
- **foundry-llm-roster** pinned to a specific SHA per §11. Task #57 has resolved the subpath install.
- **Composite index** exists on every `cip_{entity}` table: `(tenant_id, source_connector, source_id)`. Verified by: `SELECT indexname FROM pg_indexes WHERE tablename LIKE 'cip_%' AND indexdef ILIKE '%source_connector%source_id%'`. If missing on any user-data table, add a migration before M2.
- **CI surface:** GitHub Actions workflow in `foundry-cip/.github/workflows/test.yml` runs `pytest` + `mypy` + `coverage` against Postgres testcontainer. Failing CI blocks merge.
- **`foundry_mcp_*` connectivity:** Cowork session in foundry-cip can reach the PM MCP (Railway URL per CLAUDE.md). Verified by calling `foundry_mcp_system_status`.

## 1.2 Engine setup — `app.current_tenant` reset on every pool checkout (v5 PATCH-NR-1)

**v5 PATCH-NR-1 (Round-4 panel SEV-5, mandatory).** A `RESET app.current_tenant` (or equivalent `set_config` call) MUST fire on every connection checkout from the SQLAlchemy pool. Round-3 closed the PgBouncer-specific concern (Foundry doesn't use PgBouncer), but the underlying defense-in-depth is independent of pool implementation: any code path that holds a connection across multiple transactions can leave a stale `app.current_tenant` GUC visible to the NEXT caller's transaction until that next caller's `SET LOCAL` overwrites it. `SET LOCAL` resets at transaction boundary; it does NOT reset at checkout. Without this listener, a forgetting code path (no `apply_tenant_context()` call) inherits the previous caller's tenant — silent RLS bypass.

**Where this lives:** `cip/db/engine.py` (or wherever the M2 executor places the Engine factory). The listener is registered ONCE at Engine construction, applied to every checkout for the lifetime of the process.

**Reference implementation:**

```python
# foundry: kind=service domain=client-intelligence-platform touches=storage
"""CIP Engine factory with tenant-context reset listener (v5 PATCH-NR-1)."""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine


def make_engine(database_url: str, **kw) -> Engine:
    """Construct a CIP Engine with the v5 PATCH-NR-1 checkout listener.

    Every connection checkout RESETs app.current_tenant. Callers that need
    to scope queries to a tenant MUST call apply_tenant_context(conn, tid)
    explicitly (this listener does NOT auto-apply tenants — that would
    re-introduce the same forget-to-set bug class with the opposite
    failure mode).
    """
    engine = create_engine(database_url, **kw)

    @event.listens_for(engine, "checkout")
    def _reset_tenant_context(dbapi_connection, connection_record, connection_proxy):
        """v5 PATCH-NR-1: clear any prior session-level GUC before this
        connection is handed to a new caller. Belt-and-suspenders to the
        explicit apply_tenant_context() calls everywhere else.
        """
        cur = dbapi_connection.cursor()
        try:
            # Both syntaxes work; the SELECT form is portable across
            # Postgres versions and clearer about scope (false = session-level).
            cur.execute("SELECT set_config('app.current_tenant', '', false)")
        finally:
            cur.close()

    return engine
```

**Conformance test:** `tests/integration_mesh/test_post_commit_rls_isolation.py` (Round-3 added — Test 7) already asserts `current_setting('app.current_tenant', true)` is empty after every batch commit. With v5 PATCH-NR-1, a stronger invariant holds: it's empty at every CHECKOUT, period. Add a regression-guard test `test_engine_checkout_resets_tenant_guc.py` that:
1. Applies a tenant context on checkout #1, commits, returns to pool.
2. Forces a fresh checkout on the same physical connection (use `pool.LIFO`).
3. Asserts `current_setting('app.current_tenant', true) = ''` BEFORE any application code runs.

**Acceptance criterion:** `make_engine()` returns an Engine where every checkout has run the listener. Verified by the regression-guard test above.

## 1. Context & Authoritative Sources

Before writing any code, read in this order:

1. `products/client-intelligence-platform/vision/PHASE-1-PLAIN-SPEC.md` — §3 binding file paths, §4 binding Protocol shapes, §5 FixtureConnector data shape, §11 six conformance tests, §12 milestone order. This doc is **normative**. If this plan conflicts with the SPEC, the SPEC wins.
2. `products/client-intelligence-platform/vision/PHASE-1-PLAN.md` — §SPEC S2 (framework-in-Integration-Mesh rationale), §PLAN M2 exit criteria.
3. `docs/DECISION-LOG.md` — D-026 (tenant_id scoping), D-118 (CIP framework in Integration Mesh), D-119 (Knowledge+Graph consumption of CIP data), D-120 (Three Data Layers), D-121 (Discoverability Registries), D-122 (CSS tag ownership), D-123 (Schema Authority), D-133 (KnowledgeText return type), D-134 (Protocol-based connector framework), D-135 (SCD Type 2 at application layer), plus any D-128+ from the extraction batch.
4. `docs/cip/CONNECTOR-AUTHORING-GUIDE.md` skeleton — §1 Protocol contract, §2 file layout, §§3–10 per-method docs, §11 conformance, §12 reference implementation. M2 populates §§1–5, §§7–8, §§10–12 (§6 `describe_schema()` → registry partial-populated, fully done in M6; §9 `ingest_as_knowledge` partial, fully done in M5).
5. `docs/cip/SYNC-ORCHESTRATOR-GUIDE.md` skeleton — §§1–6, §§8–10 populated by M2; §7 knowledge-ingest hook partial (done M5).
6. `docs/subsystems/integration/CONTRACT.md` — D-118 states CIP framework is inside Integration Mesh.
7. Migration files `migrations/versions/cip_01_*` through `cip_08_*` — understand the existing table shape the orchestrator writes to: 9 provenance columns (`tenant_id, client_id, source_connector, source_id, ingested_at, refreshed_at, previous_version_id, ingestion_batch_id, authority`), SCD Type 2 history tables (`cip_{entity}_history`), `cip_sync_runs` audit row, `cip_connector_property_registry` (no history).

---

## 2. Architecture Decisions

### 2.1 Protocols + light ABC wrapper (hybrid)

**Decision:** Use `typing.Protocol` for the public contract (`CIPConnector`, `CIPMapper`) because:
- Structural typing lets new connectors live in any repo without importing a base class from foundry-cip.
- Phase 2 Wayward + Rocky Ridge connectors may live in separate repos — structural compatibility is what we want, not nominal.
- Aligns with Airbyte/Singer source-SDK direction (declarative spec + structural interface).

**But also:** ship a thin optional ABC (`CIPConnectorBase`) that connectors CAN inherit from to get:
- Default `rate_limit_policy` property
- Default batch-size handling
- `_log_debug()` helper
- Runtime `isinstance` check in the orchestrator path — if the connector instance is a `CIPConnectorBase`, we get helpful error messages (`"Your connector forgot to implement authenticate()"`) instead of just an `AttributeError`.

Protocols give static structural typing; the ABC gives runtime safety net for plugins. Both coexist. The SPEC §4 Protocol shapes are the normative contract.

**Web research:** Python docs on `typing.Protocol` (PEP 544, runtime_checkable caveats); Real Python's "Protocol vs ABC" guide; FastAPI's use of Protocols for dependency injection boundaries. Key takeaway: `@runtime_checkable` Protocols only check method existence, not signatures. For full signature validation, we use the conformance harness (see §4.6).

### 2.2 `@dataclass(frozen=True)` for value objects

`PropertyDescriptor`, `CIPRow`, `RateLimitPolicy`, `SyncRunState`, `CursorState` are all frozen dataclasses. Rationale:
- Immutability prevents accidental mutation between connector → orchestrator → persister.
- `frozen=True` gives us `__hash__` (useful for deduping property-registry writes).
- Pydantic would be overkill here — these are internal value objects, not wire payloads. LLM Roster types use Pydantic because they serialize to LLM providers; connector rows are DB-bound.

### 2.3 Orchestrator is procedural, not class-based

The sync orchestrator is a single function (`run_sync`) plus helpers. Not a class. Rationale:
- No state that persists across calls beyond the DB.
- Class-based orchestrators in Airbyte SDK became hard to test (deep `self.` state).
- A function taking `(connector: CIPConnector, mapper: CIPMapper, db: Session, tenant_id: UUID, client_id: UUID | None, sync_mode: Literal["full", "incremental"])` is explicit and test-friendly.

Helpers that ARE classes: `_SCDDiffer` (Type-2 diff strategy), `_SyncRunRecorder` (context manager for the `cip_sync_runs` row lifecycle). These have real state or protocol (context-manager shape).

### 2.4 SCD Type 2 differ, not just "upsert"

The existing `cip_*` tables have `_history` siblings. The orchestrator must:
1. Look up the current `cip_{entity}` row by `(tenant_id, source_connector, source_id)`.
2. Diff the new `CIPRow.fields` against the current row (excluding provenance columns and SCD metadata).
3. If unchanged → update `refreshed_at` on current row, increment `rows_skipped_unchanged` (v3 R2-C9).
4. If changed → copy current row to `cip_{entity}_history` (with a fresh `history_id`, `archived_at=now()`), update current row with new values, increment `rows_updated` + `rows_history`.
5. If new → insert into `cip_{entity}`, increment `rows_created`.

The differ is a strategy object because `cip_connector_property_registry` has NO history table — it's updated in place (per SPEC §5 comment). So the differ exposes a `should_write_history(table_name: str) -> bool` decision.

**Web research:** Kimball SCD Type 2 patterns. Classic approach is triggers; modern approach is application-layer because it's testable. Dagster and dbt both do this at model layer. Fivetran uses soft-delete + versioning (their `_fivetran_synced` column ≈ our `refreshed_at`, their `_fivetran_deleted` ≈ our authority flag semantics).

### 2.5 Cursor state is JSONB, opaque to orchestrator

`cip_sync_runs.cursor_state` is JSONB. The orchestrator treats it as an opaque dict. The connector's `incremental_key(record)` returns a `datetime`; the orchestrator serializes `{"last_incremental_key": iso_str}` and the connector's `stream_records(cursor, ...)` receives this dict back on the next run.

This matches Airbyte `state.json` and Singer `STATE` message shape. Keeps connectors free to stash connector-specific cursor data (e.g., HubSpot's "after" tokens) without the orchestrator caring.

### 2.6 Transaction boundaries: per-batch commit

**Decision:** Commit once per batch of N records (batch_size default = 500), NOT per-record and NOT per-full-sync.

- Per-record: too many round trips, transaction overhead dominates.
- Per-full-sync: huge transactions, WAL pressure, no partial-progress recovery.
- Per-batch: industry standard. On batch failure, the batch rolls back but earlier batches persist; orchestrator records a `partial` sync-run and the next run picks up from the last successful batch's cursor.

Within each batch transaction, `SET LOCAL app.current_tenant = :tenant_id` (per D-026 + RLS policy `cip_tenant_scope`). The orchestrator sets this at batch-transaction begin.

### 2.7 Knowledge-ingest hook is a stub in M2

M2 implements the hook SIGNATURE and call site. Actual Pinecone+FalkorDB wiring lands in M5. In M2, `ingest_as_knowledge(record)` returns `list[str]` (empty list is legal, meaning "no text to ingest"), and the orchestrator logs the count but doesn't push to Pinecone yet.

This keeps M2 independent of M5's Knowledge+Graph infrastructure. Per D-067, knowledge extraction failures are non-fatal — the orchestrator logs and continues.

### 2.8 Rate limiting: sleep-based, simple in M2

`RateLimitPolicy(requests_per_second: float, burst: int)`. The orchestrator uses a simple token-bucket implementation (in-process, per-connector-instance). No distributed coordination. If/when we need cross-process rate limiting in Phase 2, we add a Redis-backed variant; M2 doesn't need it because M2 only runs against the FixtureConnector in tests.

### 2.9 CSS classification on every new file

Every Python file gets `# foundry: kind=X domain=Y touches=Z` as the first line. Every markdown doc gets the YAML frontmatter. Per D-122, domain ownership is determined by this tag, not folder location. Connector framework files = `kind=service domain=client-intelligence-platform touches=integration`. Conformance harness = `kind=test domain=client-intelligence-platform`. Doc files = `kind=doc domain=client-intelligence-platform`.

---

## 3. Target `foundry-cip` Repo Layout (post-extraction) [v2]

Assumes tasks #58–#64 land first. This is the layout M2 writes INTO.

**v2 change:** Per Gap Cat 3 — `cip/persistence/` was not sanctioned by SPEC §3. Folded into `cip/integration_mesh/` to stay SPEC-honest. `cip/knowledge_hook/` collapsed into a single file within `integration_mesh/` — no new top-level packages.

```
foundry-cip/
├── cip/                                    (Python package)
│   ├── __init__.py
│   ├── integration_mesh/
│   │   ├── __init__.py
│   │   ├── base.py                         M2 — Protocols, dataclasses, KnowledgeText, ALLOWED_CIP_TABLES
│   │   ├── orchestrator.py                 M2 — run_sync()
│   │   ├── scd_differ.py                   M2 — SCD Type 2 diff utility
│   │   ├── sync_run_recorder.py            M2 — owns its own short-lived connection for cip_sync_runs writes
│   │   ├── rate_limit.py                   M2 — token bucket
│   │   ├── tenant_context.py               M2 — apply_tenant_context() (SET LOCAL)
│   │   ├── persister.py                    M2 — CIPRowPersister — writes CIPRow to cip_{entity} + history
│   │   ├── validation.py                   M2 — validate_connector_shape() runtime Protocol conformance
│   │   ├── knowledge_hook.py               M2 — stub ingest_texts(); M5 replaces
│   │   └── exceptions.py                   M2 — ConnectorError hierarchy (adds TimezoneNaiveError)
├── migrations/
│   └── versions/
│       ├── cip_01_clients.py               (moved from monorepo)
│       ├── cip_02_views.py
│       ├── cip_03_sync_runs.py
│       ├── cip_04_files.py
│       ├── cip_05_contacts.py
│       ├── cip_06_companies.py
│       ├── cip_07_deals.py
│       └── cip_08_tickets_and_registry.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py                         M2 — shared fixtures (DB session, tenant_id)
│   ├── fixtures/
│   │   └── connector_conformance/          M2 — six conformance tests
│   │       ├── __init__.py
│   │       ├── conftest.py                 M2 — MockConnector, MockMapper fixtures
│   │       ├── test_protocol_compliance.py M2
│   │       ├── test_incremental_sync.py    M2
│   │       ├── test_property_registry.py   M2
│   │       ├── test_scd_history.py         M2
│   │       ├── test_sync_run_audit.py      M2
│   │       └── test_tenant_scoping.py      M2
│   └── integration_mesh/
│       ├── test_orchestrator_unit.py       M2 — non-harness orchestrator tests
│       ├── test_scd_differ.py              M2
│       ├── test_rate_limit.py              M2
│       └── test_sync_run_recorder.py       M2
├── docs/
│   ├── CONNECTOR-AUTHORING-GUIDE.md        M2 — fills §§1–5, 7–8, 10–12
│   └── SYNC-ORCHESTRATOR-GUIDE.md          M2 — fills §§1–6, 8–10
├── pyproject.toml                          (from extraction)
├── alembic.ini                             (from extraction)
├── README.md                               (from extraction)
└── CLAUDE.md                               (from extraction)
```

**Path-inference note (LOCKED 2026-04-29):** Path is `cip/integration_mesh/` per D-146 + post-extraction reality. foundry-cip HEAD `b7136717` already has the empty `cip/integration_mesh/` namespace + `__init__.py`; M2 fills it.

---

## 4. File-by-File Build Plan

Each subsection = one file. Each file has: purpose, full signature, acceptance criteria, test pointer.

### 4.1 `cip/integration_mesh/base.py` [v2: adds KnowledgeText, ALLOWED_CIP_TABLES; locks ingest_as_knowledge return type] [v5 PATCH-Q6: KnowledgeText.metadata becomes TypedDict per D-133 amendment 2026-04-29]

**Purpose:** The normative contract. Every connector+mapper in every phase conforms to these Protocols.

**First line:** `# foundry: kind=service domain=client-intelligence-platform touches=integration`

**v2 additions (pre-locked as D-133):** `KnowledgeText` dataclass and `ALLOWED_CIP_TABLES` / `ALLOWED_HISTORY_TABLES` frozen registries. `CIPMapper.ingest_as_knowledge()` returns `list[KnowledgeText]`, NOT `list[str]` — this is the Protocol shape M5 will use without modification.

**v5 PATCH-Q6 (2026-04-29):** `KnowledgeText.metadata` is now `KnowledgeTextMetadata` (a TypedDict with required core keys + NotRequired extensions), NOT an open `dict[str, object]`. Outer frozen-dataclass shape is unchanged. D-133 amended; see DECISION-LOG.md for rationale + rejected alternatives. Required imports now include `TypedDict, NotRequired` from `typing` and `datetime` from `datetime`.

**v5 PATCH-NR-7 (2026-04-29):** Add a `_assert_tz_aware(value: datetime, field_name: str) -> None` helper to base.py; raises `TimezoneNaiveError` if `value.tzinfo is None or value.utcoffset() is None`. Called by orchestrator before metadata is finalized into `KnowledgeText` and by persister before INSERT on any datetime field of `CIPRow.fields`. Same exception class as the existing incremental_key tz-naive check (line ~1412 of v4).

```python
def _assert_tz_aware(value: datetime, field_name: str) -> None:
    """v5 PATCH-NR-7. Raises TimezoneNaiveError on tz-naive datetimes.

    Called everywhere a datetime crosses the framework boundary into
    KnowledgeTextMetadata or CIPRow.fields. Silent tz-naive datetimes are a
    correctness landmine in cross-DB / cross-timezone deployments — fail fast.
    """
    if not isinstance(value, datetime):
        return  # type ignored elsewhere; this is a tz-naivete guard only
    if value.tzinfo is None or value.utcoffset() is None:
        raise TimezoneNaiveError(
            f"{field_name} must be tz-aware UTC datetime; got naive: {value!r}"
        )
```

**Imports:**
```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Iterator, Literal, Protocol, runtime_checkable
from uuid import UUID
```

**Contents:**

```python
# ── Value objects (frozen dataclasses) ─────────────────────────────────

@dataclass(frozen=True)
class PropertyDescriptor:
    """One property that a connector exposes, registered in cip_connector_property_registry.

    Emitted by CIPConnector.describe_schema().
    """
    connector: str
    object_type: str           # "ticket", "contact", "deal", etc.
    property_name: str         # canonical name
    data_type: str             # "string", "integer", "timestamp", "json", etc.
                               # v3: renamed from `property_type` to match the
                               # `cip_connector_property_registry.data_type` SQL
                               # column the orchestrator upserts into (R2-C5).
    storage_location: Literal["column", "overflow"]
    column_name: str | None    # required if storage_location == "column"
    cip_table: str             # "cip_tickets", "cip_contacts", ...
    description: str | None = None
    is_custom: bool = False    # True = tenant-defined custom field (HubSpot custom prop, etc.)


@dataclass(frozen=True)
class CIPRow:
    """One row the mapper emits. Orchestrator persists to target_table + history on change."""
    target_table: str                # "cip_tickets", "cip_contacts", ...
    source_id: str                   # stable ID from source system
    fields: dict[str, object]        # domain columns (subject, status, email, ...)
    overflow: dict[str, object] = field(default_factory=dict)
    client_id: UUID | None = None    # None = tenant-level row (rare)
    authority: Literal["agent_discovered", "ingested", "validated"] = "ingested"


@dataclass(frozen=True)
class RateLimitPolicy:
    """In-process rate limiting for stream_records calls."""
    requests_per_second: float
    burst: int = 1

    def __post_init__(self):
        if self.requests_per_second <= 0:
            raise ValueError("requests_per_second must be > 0")
        if self.burst < 1:
            raise ValueError("burst must be >= 1")


# Module-level default (v2: avoid the frozen-dataclass-class-attr pattern).
# v3: single canonical name — `DEFAULT_RATE_LIMIT`. Do NOT add a
# `RateLimitPolicy.DEFAULT` classmethod; R2-C6 resolved the naming ambiguity
# in favor of the module-level constant. CIPConnectorBase's default also
# references this name (R2-C6).
DEFAULT_RATE_LIMIT = RateLimitPolicy(requests_per_second=10.0, burst=5)


# ── Module-level TSP constants (v3 — R2-C2) ───────────────────────────────
# These are Tunable Starting Points. Adjust with data after first real
# connector lands. Names are canonical — orchestrator imports them from here.

DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS: int = 300
"""H-13. How far the orchestrator rewinds the stored cursor before passing it
to `connector.stream_records()`. Absorbs clock skew + eventual-consistency
replica lag at the source. 300s = 5 minutes. Connector authors can override
per-sync via the `cursor_safety_window_seconds=` kwarg on `run_sync()`."""

MAX_RATE_LIMIT_SLEEP_SECONDS: int = 300
"""M-21. Orchestrator caps `RateLimitExceeded.retry_after_seconds` at this
value. Prevents a buggy/malicious connector from parking the sync for an
hour. If a source system really needs >5min, break the sync and let the
caller reschedule."""

MAX_BATCH_RATE_LIMIT_RETRIES: int = 3
"""H-6. Per-batch budget for rate-limit retries. After this many retries on
the SAME batch, the batch is counted as one `consecutive_batch_failures`
increment and the orchestrator moves on."""

MAX_CONSECUTIVE_BATCH_FAILURES: int = 3
"""H-8. Cross-batch budget. After this many consecutive batch failures, the
orchestrator aborts with `status='partial'`. Prevents infinite loops when
the remote API is sustained-down."""


class KnowledgeTextMetadata(TypedDict, total=False):
    """v5.2 PATCH-Q6 — D-133 amended 2026-04-29 (Round-6 panel synthesis).

    Framework-owned metadata keys for KnowledgeText. ALL keys are NotRequired at
    type level (`total=False`); the orchestrator's `validate_knowledge_text_metadata()`
    enforces the required-core contract at the boundary CROSSING moment (when text
    leaves the connector→mapper layer and is handed to the Knowledge+Graph layer).
    This separates SHAPE (TypedDict, mypy-strict checks key names) from REQUIRED-AT-EMISSION
    (orchestrator-validated, fail-loud).

    Why total=False not required-keys: 3-of-6 panel models flagged that mock mappers
    populating placeholder values (`source_system='fixture'`, `connector_version='0.0.0'`)
    create a 'lying mock' anti-pattern. With total=False, mappers emit only the keys
    they genuinely know; orchestrator finalizes operational metadata at boundary; mock
    mappers no longer have to lie. Kimi-k2.5: 'By M5, when the orchestrator populates
    real data, you might discover that the MockMapper's placeholder format doesn't
    match the orchestrator's expectations, leading to integration failures late in
    the cycle.'

    Connectors that need source-specific fields subclass this TypedDict in their own
    module:

        class HubSpotKnowledgeMetadata(KnowledgeTextMetadata):
            hs_object_id: NotRequired[str]
            hs_pipeline_stage: NotRequired[str]

    Framework-owned core keys (orchestrator-populated, validated at boundary):
      - source_id          str          REQUIRED at boundary; raised by validator
      - source_system      str          REQUIRED at boundary
      - extracted_at       datetime     REQUIRED at boundary; tz-aware UTC
      - tenant_id          UUID         REQUIRED at boundary
      - connector_version  str          REQUIRED at boundary; connector's own semver

    Framework-owned optional extensions:
      - authority           "agent_discovered" | "ingested" | "validated"
      - record_updated_at   datetime tz-aware UTC
      - ingestion_batch_id  UUID

    mypy-strict catches typos in metadata keys at CI time. Adding a new field is a
    non-breaking change. Removing or renaming a required field is breaking
    (semver-major) IF the validator's required-set changes too.
    """
    source_id: str
    source_system: str
    extracted_at: datetime
    tenant_id: UUID
    connector_version: str
    authority: Literal["agent_discovered", "ingested", "validated"]
    record_updated_at: datetime
    ingestion_batch_id: UUID


# v5.2 (Round-6 Call A): orchestrator-boundary validator. Called by the
# orchestrator AFTER mapper.ingest_as_knowledge() returns and BEFORE handing the
# list to ingest_texts_noop() (M2) / real Knowledge+Graph wiring (M5). If the
# orchestrator can fill missing required keys from its own state (e.g., it knows
# tenant_id + ingestion_batch_id + extracted_at), it does so before validating.
# Mappers don't have to populate operational keys they don't know.
KNOWLEDGE_TEXT_REQUIRED_KEYS: frozenset[str] = frozenset({
    "source_id", "source_system", "extracted_at", "tenant_id", "connector_version",
})


def validate_knowledge_text_metadata(
    metadata: KnowledgeTextMetadata, *, where: str = "KnowledgeText emission",
) -> None:
    """v5.2 (Round-6 Call A): boundary-crossing validation of KnowledgeText metadata.

    Called by the orchestrator AFTER mapper output + orchestrator finalization, BEFORE
    handing to the Knowledge+Graph layer. Raises KnowledgeMetadataValidationError on
    any missing required key OR TimezoneNaiveError on tz-naive datetime.

    Args:
        metadata: dict-shaped KnowledgeTextMetadata (still a dict at runtime).
        where: human-readable string for the error message — e.g. "ingest_as_knowledge
               output" or "M5 Knowledge layer entry".
    """
    # Lazy-import the exceptions to avoid a circular import (exceptions.py
    # doesn't import base.py, so import-here is safe). v5.2 (Verifier HIGH-B):
    # canonical home for both exception classes is exceptions.py — base.py
    # imports them at use-site.
    from .exceptions import KnowledgeMetadataValidationError, TimezoneNaiveError

    missing = KNOWLEDGE_TEXT_REQUIRED_KEYS - metadata.keys()
    if missing:
        raise KnowledgeMetadataValidationError(
            f"KnowledgeText metadata missing required keys at {where}: {sorted(missing)}. "
            f"Mapper output (or orchestrator finalization) must populate all 5 core keys."
        )
    # tz-aware enforcement (PATCH-NR-7 unchanged)
    for k in ("extracted_at", "record_updated_at"):
        v = metadata.get(k)
        if v is not None and isinstance(v, datetime):
            if v.tzinfo is None or v.utcoffset() is None:
                raise TimezoneNaiveError(
                    f"KnowledgeText.metadata['{k}'] must be tz-aware UTC at {where}; "
                    f"got naive: {v!r}"
                )


@dataclass(frozen=True)
class KnowledgeText:
    """A text chunk the mapper emits for downstream Knowledge ingestion.

    Outer shape: frozen dataclass (locked at M2 by D-133 — connector cannot
    mutate mid-pipeline).
    Inner `metadata` shape: KnowledgeTextMetadata TypedDict with `total=False`
    (sharpened by D-133 amendment 2026-04-29; refined to total=False by Round-6
    panel synthesis 2026-04-29 — Call A).

    Required-at-boundary contract enforced by `validate_knowledge_text_metadata()`,
    NOT by the type. Mock mappers can emit `metadata={}`; orchestrator fills
    operational metadata; validator runs at boundary.
    """
    text: str
    metadata: KnowledgeTextMetadata


# ── Allowed CIP tables (v2 allowlist; closed enum) ─────────────────────

ALLOWED_CIP_TABLES: frozenset[str] = frozenset({
    "cip_clients",
    "cip_companies",
    "cip_contacts",
    "cip_deals",
    "cip_files",
    "cip_tickets",
    "cip_views",
    "cip_connector_property_registry",
})

# Tables that have sibling _history tables for SCD Type 2.
HISTORY_TABLE_BY_CURRENT: dict[str, str] = {
    "cip_clients": "cip_clients_history",
    "cip_companies": "cip_companies_history",
    "cip_contacts": "cip_contacts_history",
    "cip_deals": "cip_deals_history",
    "cip_files": "cip_files_history",
    "cip_tickets": "cip_tickets_history",
    "cip_views": "cip_views_history",
    # cip_connector_property_registry intentionally absent — no history.
    # cip_sync_runs intentionally absent — audit log, not domain table.
}


@dataclass(frozen=True)
class SyncRunState:
    """Snapshot of what the orchestrator returns to callers."""
    run_id: UUID
    batch_id: UUID
    status: Literal["success", "partial", "failed"]
    # v2: precise counter semantics per QC M-24.
    rows_received: int          # raw count yielded by connector.stream_records
    rows_created: int           # new rows INSERTed into cip_{entity}
    rows_updated: int           # existing rows UPDATEd with new values
    rows_skipped_unchanged: int # diffed identical → only refreshed_at bumped
    rows_skipped_drift: int     # mapper.map raised SchemaDriftError
    rows_skipped_duplicate: int # intra-batch dedupe dropped this row
    rows_history: int           # SCD history rows written
    started_at: datetime
    ended_at: datetime
    error_detail: dict | None = None
    # v3 (R2-C3): the orchestrator's `_finalize()` builder passes
    # `cursor_state=...` to this dataclass. Without this field, construction
    # raises TypeError. Default None — full-sync runs and empty-stream runs
    # have no cursor advance.
    cursor_state: dict | None = None

    @property
    def rows_processed(self) -> int:
        """Rows that were acted on (created + updated + skipped_unchanged)."""
        return self.rows_created + self.rows_updated + self.rows_skipped_unchanged


# ── Protocols (the normative contract) ────────────────────────────────

@runtime_checkable
class CIPConnector(Protocol):
    connector_id: str
    tenant_id: UUID

    def authenticate(self) -> None: ...
    def stream_records(
        self,
        cursor: dict | None,
        batch_size: int,
    ) -> Iterator[dict]: ...
    def describe_schema(self) -> list[PropertyDescriptor]: ...
    def incremental_key(self, record: dict) -> datetime: ...

    @property
    def rate_limit_policy(self) -> RateLimitPolicy: ...

    # v4 (Round-3 panel): per-connector override of the cursor safety window.
    # REQUIRED on every connector — Protocol membership is structural and
    # @runtime_checkable enforces it via isinstance(). Connectors that want
    # the global default just return DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS
    # (CIPConnectorBase does this for free). Connectors that want a tighter
    # or wider lookback override with a constant or computed value.
    #
    # The orchestrator reads this property when its `cursor_safety_window_seconds`
    # kwarg is not explicitly passed by the caller (kwarg=None → use
    # connector.cursor_safety_window_seconds). See §4.8 run_sync().
    #
    # Empirical justification (from LLM panel research):
    #   - Airbyte's zendesk source uses 180s lookback (constants.py L9, gemini-3-pro citation)
    #   - HubSpot has no published replica-lag SLA — 300s is defensible heuristic
    #   - Zendesk's own incremental-export docs recommend cursor-driven semantics
    #     over fixed lookback windows
    # See §13 Q1 for full rationale.
    @property
    def cursor_safety_window_seconds(self) -> int: ...


@runtime_checkable
class CIPMapper(Protocol):
    object_type: str
    target_table: str

    def map(self, record: dict) -> Iterable[CIPRow]: ...
    def overflow_fields(self) -> list[str]: ...
    def authority(self) -> Literal["agent_discovered", "ingested", "validated"]: ...
    # v2: locked return type (D-133). M5 populates KnowledgeText.metadata.
    def ingest_as_knowledge(self, record: dict) -> list[KnowledgeText]: ...


# ── Optional ABC (runtime safety net) ─────────────────────────────────

class CIPConnectorBase:
    """Optional base class. Connectors can inherit for default rate_limit_policy
    and helpful AttributeError messages. Not required — structural compat is enough."""

    connector_id: str = ""
    tenant_id: UUID  # subclasses set in __init__

    @property
    def rate_limit_policy(self) -> RateLimitPolicy:
        # v3 (R2-C6): use the module-level DEFAULT_RATE_LIMIT. There is
        # intentionally NO `RateLimitPolicy.DEFAULT` classmethod.
        return DEFAULT_RATE_LIMIT

    @property
    def cursor_safety_window_seconds(self) -> int:
        # v4 (Round-3): default is the module-level constant. Override in a
        # subclass to set a per-connector lookback (e.g., Zendesk's docs
        # suggest cursor-driven semantics rather than fixed lookback).
        return DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS

    def authenticate(self) -> None:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement authenticate()"
        )

    def stream_records(self, cursor, batch_size):
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement stream_records()"
        )

    def describe_schema(self):
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement describe_schema()"
        )

    def incremental_key(self, record):
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement incremental_key()"
        )


class CIPMapperBase:
    """Optional mapper base."""
    object_type: str = ""
    target_table: str = ""

    def overflow_fields(self) -> list[str]:
        return []

    def authority(self) -> Literal["agent_discovered", "ingested", "validated"]:
        return "ingested"

    def ingest_as_knowledge(self, record: dict) -> list[KnowledgeText]:
        return []

    def map(self, record: dict):
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement map()"
        )
```

**Acceptance criteria:**
- File imports clean (no circular deps).
- `@runtime_checkable` decorator in place so `isinstance(x, CIPConnector)` works at runtime for method-existence checks.
- All five Protocol methods on `CIPConnector` and four on `CIPMapper` match SPEC §4 verbatim (signatures, names, types).
- `PropertyDescriptor` has exactly 9 fields matching SPEC §4.
- `CIPRow` includes `authority` (default `"ingested"`) — needed for Phase 3 agent-discovered rows (D-024 territory).

**Test pointer:** `tests/fixtures/connector_conformance/test_protocol_compliance.py` (§4.8 below).

---

### 4.2 `cip/integration_mesh/exceptions.py`

**Purpose:** Typed errors so the orchestrator can route failures correctly.

**First line:** `# foundry: kind=service domain=client-intelligence-platform touches=integration`

**Contents:**

```python
class ConnectorError(Exception):
    """Base class. Orchestrator catches this and routes by subtype."""


class AuthenticationError(ConnectorError):
    """Raised by connector.authenticate() on credential failure. Non-retryable."""


class RateLimitExceeded(ConnectorError):
    """Raised by stream_records() when source-system rate limit hit.
    Orchestrator honors retry_after_seconds and backs off."""
    def __init__(self, retry_after_seconds: float, *args):
        super().__init__(*args)
        self.retry_after_seconds = retry_after_seconds


class SchemaDriftError(ConnectorError):
    """Raised by mapper.map() when a record has a field the mapper doesn't understand.
    Orchestrator logs + skips the record (partial sync) instead of aborting."""


class PersistenceError(ConnectorError):
    """Raised by the row persister on DB errors.
    Orchestrator rolls back the batch transaction and records partial."""


class TimezoneNaiveError(ConnectorError):
    """v3 (R2-C1). Raised by the orchestrator when a connector returns a
    tz-naive datetime from `incremental_key()` or when a stored cursor's
    `last_incremental_key` is tz-naive.

    Silently coercing tz-naive timestamps to UTC (or to local) would corrupt
    the cursor on DST transitions and cross-region retries — we'd either
    re-process records we've already ingested or miss records. Fail fast,
    fail loud. Connector authors MUST return tz-aware datetimes.
    Non-retryable."""


class KnowledgeMetadataValidationError(ValueError):
    """v5.2 (Round-6 Call A). Raised by `validate_knowledge_text_metadata()` when
    a KnowledgeText emits to the boundary missing one of the 5 required core
    metadata keys (source_id, source_system, extracted_at, tenant_id,
    connector_version). Inherits from ValueError (not ConnectorError) — this is
    a CIP-internal contract violation, not a connector author's fault. Mappers
    typically only know `source_id`; the orchestrator should fill the rest at
    finalization time before validation. Non-retryable."""
```

**Acceptance criteria:** Six exception classes, five inherit from `ConnectorError`, `KnowledgeMetadataValidationError` inherits from `ValueError` (v5.2 distinction — internal contract violation, not connector fault), `RateLimitExceeded` takes `retry_after_seconds`, `TimezoneNaiveError` + `KnowledgeMetadataValidationError` importable from the package root.

---

### 4.3 `cip/integration_mesh/rate_limit.py`

**Purpose:** Simple in-process token-bucket for `RateLimitPolicy`. Used by the orchestrator to pace calls into `stream_records`.

**First line:** `# foundry: kind=service domain=client-intelligence-platform touches=integration`

**Contents:**

```python
from __future__ import annotations
import time
import threading
from .base import RateLimitPolicy


class TokenBucket:
    """Thread-safe token bucket for in-process rate limiting.

    Not distributed. For distributed rate limiting in Phase 2+, swap for a
    Redis-backed implementation; public API stays the same (acquire())."""

    def __init__(self, policy: RateLimitPolicy):
        self.policy = policy
        self._tokens = float(policy.burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        """Block until `tokens` tokens are available. Returns when consumed.

        v2 fix (QC L-26 / Senior #3): release lock around time.sleep so shared
        buckets don't serialize. Re-acquire + re-check token math after sleep."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(
                    self.policy.burst,
                    self._tokens + elapsed * self.policy.requests_per_second,
                )
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                shortfall = tokens - self._tokens
                sleep_for = shortfall / self.policy.requests_per_second
            # Lock released here — other threads can make progress.
            time.sleep(sleep_for)
```

**Acceptance criteria:**
- Bucket respects `burst` ceiling.
- `acquire()` blocks correctly when tokens depleted.
- Thread-safe (lock around token math).

**Test pointer:** `tests/integration_mesh/test_rate_limit.py` — at least 3 tests: burst-capacity, rate-limited-pause, concurrent-access.

**Edge case:** If `requests_per_second` is 0, `acquire()` would sleep forever. The orchestrator validates `policy.requests_per_second > 0` at start; `base.py` `RateLimitPolicy` could add a `__post_init__` validator, but since it's frozen, use a `@classmethod` validator called from orchestrator startup.

---

### 4.4 `cip/integration_mesh/tenant_context.py` [v2: used by persister + recorder]

**Purpose:** Apply `SET LOCAL app.current_tenant = :tenant_id` at the start of every batch transaction so RLS policies `cip_tenant_scope` work correctly.

**First line:** `# foundry: kind=service domain=client-intelligence-platform touches=integration,security`

**Contents:**

```python
from __future__ import annotations
from typing import Union
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

# v3 (R2-C4): widened type. Both Session (orchestrator's per-batch handle)
# and Connection (recorder's short-lived handle) expose .execute(text, params).
# Union typing lets mypy --strict accept both call sites without per-call-site
# casts. Keep this alias local to the module — it's not a public contract.
SessionOrConnection = Union[Session, Connection]


def apply_tenant_context(db: SessionOrConnection, tenant_id: UUID) -> None:
    """Set the per-transaction tenant context.

    MUST be called inside an open transaction (SET LOCAL scope = txn).
    MUST be called before any cip_* read or write.

    Accepts either a SQLAlchemy `Session` (orchestrator) or a `Connection`
    (recorder's own short-lived handle from `engine.begin()`). Both support
    `.execute(text, params)`; the SET LOCAL is transaction-scoped in both.

    Per D-026 + D-127, every query inside this txn is automatically filtered to
    `tenant_id` by the RLS policy `cip_tenant_scope` (cmd=ALL) on every cip_*
    table.

    v4 (Round-3 panel CRIT-1) — pooler safety:
        SET LOCAL is bound to the current transaction. As soon as the
        transaction commits or rolls back, the GUC is cleared. This is
        intentional and is what makes SET LOCAL safe under PgBouncer
        TRANSACTION pooling — the connection is returned to the pool with
        no residual tenant state.

        This is NOT safe under SESSION pooling (the GUC would persist
        across transactions, potentially serving the next tenant's queries
        with the previous tenant's RLS context). M2's deployment target
        (Railway, plain QueuePool, no PgBouncer) is fine. Phase 2 ventures
        deploying behind PgBouncer MUST run in transaction-pooling mode.

    v4 (Round-3 panel) — belt-and-suspenders pattern for venture-side
    deployments wanting auto-applied tenant context:

        # In your engine setup module (NOT M2 framework code):
        from sqlalchemy import event
        from cip.integration_mesh import apply_tenant_context

        @event.listens_for(engine, "begin")
        def _set_tenant(conn):
            tenant_id = your_tenant_resolver()  # request scope, etc.
            if tenant_id is not None:
                apply_tenant_context(conn, tenant_id)

        This pattern auto-fires on every engine.begin() and Session.begin().
        M2 itself does NOT use this pattern — orchestrator/recorder/persister
        all call apply_tenant_context() explicitly. The pattern exists for
        Phase 2+ ventures that want it as a backstop. Conformance Test 7
        (post-commit RLS isolation, §5.8) catches missed call sites either
        way.
    """
    db.execute(
        text("SET LOCAL app.current_tenant = :tid"),
        {"tid": str(tenant_id)},
    )
```

**Acceptance criteria:**
- Uses parameterized `text()` with `SET LOCAL` (not `SET` — must be txn-scoped).
- Casts UUID to str for Postgres GUC.
- Docstring references D-026 + D-127 + `cip_tenant_scope`.
- v3 (R2-C4): Accepts both `Session` and `Connection` via `SessionOrConnection` union alias; mypy strict passes at both call sites (orchestrator passes Session, recorder passes Connection).

**Test pointer:** `tests/fixtures/connector_conformance/test_tenant_scoping.py`.

---

### 4.5 `cip/integration_mesh/persister.py` [v2: ALLOWED_CIP_TABLES allowlist + SQLAlchemyError translation]

**Purpose:** Take a `CIPRow` + tenant context and write it to `cip_{entity}` (current table) and `cip_{entity}_history` (if the SCD differ decides a history row is warranted).

**First line:** `# foundry: kind=service domain=client-intelligence-platform touches=integration,storage`

**Contents (signature-level):**

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .base import CIPRow, ALLOWED_CIP_TABLES, HISTORY_TABLE_BY_CURRENT
from .scd_differ import SCDDiffer
from .exceptions import PersistenceError


@dataclass
class PersistResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    history: int = 0


class CIPRowPersister:
    """Writes a CIPRow into cip_{entity} and optionally cip_{entity}_history.

    Assumes:
    - Caller has already applied tenant context (apply_tenant_context()).
    - Caller owns the transaction (persister does not commit).
    """

    def __init__(self, db: Session, differ: SCDDiffer):
        self.db = db
        self.differ = differ

    def persist(
        self,
        row: CIPRow,
        *,
        tenant_id: UUID,
        connector_id: str,
        batch_id: UUID,
    ) -> PersistResult:
        # v2 (QC Senior #5 / M-18): closed-enum allowlist. Refuse unknown
        # table names BEFORE any SQL interpolation. Stops a buggy/malicious
        # mapper writing to arbitrary tables.
        if row.target_table not in ALLOWED_CIP_TABLES:
            raise PersistenceError(
                f"Unknown target_table {row.target_table!r}; "
                f"allowed: {sorted(ALLOWED_CIP_TABLES)}"
            )

        history_table = HISTORY_TABLE_BY_CURRENT.get(row.target_table)
        # history_table is None for cip_connector_property_registry (no history).

        try:
            # 1. SELECT ... FOR UPDATE by (tenant_id, source_connector, source_id).
            # 2. If no current row → INSERT new; return created=1.
            # 3. If exists → differ.diff(...).
            #    - not changed: UPDATE refreshed_at only; return skipped_unchanged=1.
            #    - changed + history_table is not None: INSERT old state into
            #      history_table; UPDATE current; return updated=1, history=1.
            #    - changed + history_table is None: UPDATE current in-place;
            #      return updated=1, history=0.
            ...
        except SQLAlchemyError as sqle:
            # v2 (QC H-8): translate ALL SQLAlchemy errors to PersistenceError
            # so the orchestrator's except PersistenceError catches them.
            raise PersistenceError(str(sqle)) from sqle
```

**Persist implementation details (junior-dev level):**

For step 2 (INSERT new):
```sql
INSERT INTO {row.target_table} (
    id, tenant_id, client_id, source_connector, source_id,
    ingested_at, refreshed_at,
    previous_version_id, ingestion_batch_id, authority,
    {row.fields keys, comma-separated},
    overflow
) VALUES (
    gen_random_uuid(), :tenant_id, :client_id, :source_connector, :source_id,
    now(), now(),
    NULL, :batch_id, :authority,
    {:field_1, :field_2, ...},
    :overflow::jsonb
)
RETURNING id
```

For step 3 (UPDATE with history):
```sql
-- 3a. Select the current row FOR UPDATE (lock).
-- v4 (Round-3 panel CRIT-2 partial): explicit ORDER BY source_id ensures
-- two concurrent batches that touch overlapping records acquire row locks
-- in the SAME order, preventing the deadlock class. Single-row SELECT in
-- the persister loop already has only one source_id, so the ORDER BY is
-- belt-and-suspenders here — but the orchestrator's _dedupe_by_source_id
-- is also v4-modified to preserve ascending source_id order before the
-- per-record persist loop runs.
SELECT id, {all domain columns}, overflow
FROM {row.target_table}
WHERE tenant_id = :tenant_id
  AND source_connector = :source_connector
  AND source_id = :source_id
ORDER BY source_id
FOR UPDATE
-- 3b. If differ says changed AND should_write_history:
INSERT INTO {row.target_table}_history (
    history_id, id, tenant_id, client_id, source_connector, source_id,
    ingested_at, refreshed_at, previous_version_id, ingestion_batch_id,
    authority, archived_at,
    {domain columns copied from current row}, overflow
) VALUES (...)
-- 3c. UPDATE current:
UPDATE {row.target_table}
SET refreshed_at = now(),
    previous_version_id = (new history_id if we wrote one, else keep),
    {domain columns = new values}, overflow = :overflow::jsonb,
    ingestion_batch_id = :batch_id
WHERE id = {current id}
```

**Edge cases:**
- JSON/overflow diff: differ compares via canonical JSON serialization (sorted keys) to avoid false positives from key-order changes.
- Null vs missing: if `row.fields` omits a column, treat as "no change"; do NOT null out existing values.
- Table with no history sibling (`cip_connector_property_registry`): differ returns `should_write_history=False`. Persister skips the history insert.
- Very large overflow JSONs: no special handling in M2; rely on Postgres JSONB to handle. Flag for M6 if we see real-world overflows >1MB.

**Acceptance criteria:**
- Parameterized SQL (no f-string injection).
- `FOR UPDATE` lock to prevent lost-update race in concurrent batches.
- v4 (Round-3 panel CRIT-2): `ORDER BY source_id` before `FOR UPDATE`. Cheap deterministic ordering that prevents the deadlock class even before advisory-lock dual-run prevention lands in M3 (§8.13).
- Returns `PersistResult` with correct counts.
- Raises `PersistenceError` on DB errors (IntegrityError, etc.) with context.

**Test pointer:** `tests/fixtures/connector_conformance/test_scd_history.py`.

---

### 4.6 `cip/integration_mesh/scd_differ.py`

**Purpose:** Decide whether a new `CIPRow` is different enough from the current DB row to warrant a history record.

**First line:** `# foundry: kind=service domain=client-intelligence-platform touches=integration`

**Contents:**

```python
from __future__ import annotations
import json
from dataclasses import dataclass


# Tables that are updated in-place, no history (per SPEC §5 + cip_08 migration).
NO_HISTORY_TABLES = frozenset({"cip_connector_property_registry", "cip_sync_runs"})


# Columns that are pure metadata and should never count as "changes".
METADATA_COLUMNS = frozenset({
    "id", "ingested_at", "refreshed_at",
    "previous_version_id", "ingestion_batch_id",
})


@dataclass
class DiffResult:
    changed: bool
    changed_columns: list[str]
    write_history: bool


class SCDDiffer:
    """Pure function wrapped in a class for injection/testing.

    Decides:
    1. Are the domain columns materially different?
    2. If yes, should we also write a history row (based on target table)?
    """

    def should_write_history(self, target_table: str) -> bool:
        return target_table not in NO_HISTORY_TABLES

    def diff(
        self,
        *,
        target_table: str,
        current_row: dict,
        new_fields: dict,
        new_overflow: dict,
    ) -> DiffResult:
        changed_columns: list[str] = []

        # Compare domain columns.
        for key, new_val in new_fields.items():
            if key in METADATA_COLUMNS:
                continue
            if self._normalize(current_row.get(key)) != self._normalize(new_val):
                changed_columns.append(key)

        # Compare overflow via canonical JSON.
        cur_of = self._canonical(current_row.get("overflow") or {})
        new_of = self._canonical(new_overflow or {})
        if cur_of != new_of:
            changed_columns.append("overflow")

        changed = bool(changed_columns)
        return DiffResult(
            changed=changed,
            changed_columns=changed_columns,
            write_history=changed and self.should_write_history(target_table),
        )

    @staticmethod
    def _normalize(v):
        if isinstance(v, dict):
            return json.dumps(v, sort_keys=True, default=str)
        if isinstance(v, list):
            return json.dumps(v, sort_keys=True, default=str)
        return v

    @staticmethod
    def _canonical(d: dict) -> str:
        return json.dumps(d, sort_keys=True, default=str)
```

**Acceptance criteria:**
- `NO_HISTORY_TABLES` contains both registry + sync_runs.
- Metadata columns never trigger a history row.
- Overflow JSON comparison uses canonical sort to dodge key-order false positives.
- Returns detailed `DiffResult` (the orchestrator logs `changed_columns` in DEBUG).

**Test pointer:** `tests/integration_mesh/test_scd_differ.py` — minimum 8 cases: unchanged, one domain col changed, overflow changed, metadata-only change (should be unchanged), registry table (no history), missing keys in new, type coercion (int vs str "42"), null vs missing.

---

### 4.7 `cip/integration_mesh/sync_run_recorder.py` [v2: owns its own connection, SET LOCAL per recorder write]

**Purpose:** Manage the `cip_sync_runs` row lifecycle as a context manager so the orchestrator can't forget to close the row.

**v2 redesign (QC C-1, C-2, Senior #1, #2):** Recorder takes a SQLAlchemy `Engine`, not a `Session`. It opens a fresh short-lived connection for each of its two writes (INSERT on enter, UPDATE on exit). Each connection does its own `BEGIN → SET LOCAL app.current_tenant → write → COMMIT` inside `engine.begin()`. This means:

- Recorder NEVER commits the orchestrator's session.
- Recorder's INSERT runs with tenant context set → passes RLS on `cip_sync_runs`.
- Orchestrator's batch session is fully independent.
- `cursor_state` is NO LONGER owned by the recorder; the orchestrator writes it inside each batch txn (QC C-4 fix).

**First line:** `# foundry: kind=service domain=client-intelligence-platform touches=integration`

**Contents:**

```python
from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .base import SyncRunState
from .tenant_context import apply_tenant_context


@dataclass
class _MutableCounters:
    # v2: precise counter semantics (QC M-24).
    rows_received: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    rows_skipped_unchanged: int = 0
    rows_skipped_drift: int = 0
    rows_skipped_duplicate: int = 0
    rows_history: int = 0
    error_detail: dict | None = None
    # v3 (R2-A2 + R2-C3 consistency): mutable slot the orchestrator writes
    # each time it advances the cursor inside a batch txn. `_finalize()`
    # reads this after the `with recorder:` block exits to build the
    # immutable SyncRunState.cursor_state field.
    cursor_state: dict | None = None


class SyncRunRecorder:
    """Context manager. On __enter__ inserts a cip_sync_runs row with
    status='running'. On __exit__ updates status + counters + ended_at.

    Usage:
        with SyncRunRecorder(engine, tenant_id=..., client_id=..., connector_id=...,
                             connector_name=..., sync_mode="incremental") as run:
            run.counters.rows_received += 1
            run.counters.cursor_state = {"last_incremental_key": "..."}
            # on exception, __exit__ records 'failed' with error_detail.
    v3 (R2-C9): counter names reflect the M-24 split (rows_received, rows_created,
    rows_updated, rows_skipped_unchanged, rows_skipped_drift, rows_skipped_duplicate,
    rows_history). The old `rows_ingested` / `rows_skipped` are retired.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        tenant_id: UUID,
        client_id: UUID | None,
        connector_id: str,
        connector_name: str,
        sync_mode: str,
    ):
        # v2: take an Engine, not a Session. Recorder owns its own
        # short-lived connections for cip_sync_runs writes.
        self.engine = engine
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.connector_id = connector_id
        self.connector_name = connector_name
        self.sync_mode = sync_mode
        self.run_id: UUID = uuid4()
        self.batch_id: UUID = uuid4()
        self.started_at: datetime = datetime.now(timezone.utc)
        self.counters = _MutableCounters()

    def __enter__(self) -> "SyncRunRecorder":
        # v2: fresh short-lived connection owned by recorder; tenant context
        # SET LOCAL inside this txn so RLS on cip_sync_runs passes (QC C-2 fix).
        # engine.begin() auto-commits on exit; the cip_sync_runs row becomes
        # observable immediately ("watch sync live" operator UX).
        with self.engine.begin() as conn:
            apply_tenant_context(conn, self.tenant_id)
            conn.execute(
                text(
                    """
                    INSERT INTO cip_sync_runs (
                        id, tenant_id, client_id, connector_id, connector_name,
                        batch_id, sync_mode, status, started_at, run_metadata
                    ) VALUES (
                        :id, :tenant_id, :client_id, :connector_id, :connector_name,
                        :batch_id, :sync_mode, 'running', :started_at, '{}'::jsonb
                    )
                    """
                ),
                {
                    "id": str(self.run_id),
                    "tenant_id": str(self.tenant_id),
                    "client_id": str(self.client_id) if self.client_id else None,
                    "connector_id": self.connector_id,
                    "connector_name": self.connector_name,
                    "batch_id": str(self.batch_id),
                    "sync_mode": self.sync_mode,
                    "started_at": self.started_at,
                },
            )
        return self
        # v3 (R2-A3): `metadata` → `run_metadata` column rename pre-requisite.
        # Add a migration `cip_11_rename_sync_runs_metadata.py` before M2 ships
        # that renames cip_sync_runs.metadata to cip_sync_runs.run_metadata to
        # avoid collision with SQLAlchemy Declarative.metadata. Renumbered from
        # v2's `cip_09` because SPEC §2 AC #1 reserves `cip_09` (and by
        # adjacency `cip_10`) for Phase 3 cross-tenant grants. If renaming is
        # blocked, fall back to keeping `metadata` column name here and
        # documenting the footgun.

    def __exit__(self, exc_type, exc_val, exc_tb):
        ended_at = datetime.now(timezone.utc)
        if exc_type is not None:
            status = "failed"
            # v2: sanitize — never write raw exception repr that could contain
            # record PII (QC Gap Cat 7).
            self.counters.error_detail = {
                "type": exc_type.__name__,
                "message": _redact(str(exc_val)),
            }
        elif self.counters.error_detail is not None:
            status = "partial"
        else:
            status = "success"

        # v2 capture for orchestrator to read post-exit.
        self.final_status = status
        self.final_ended_at = ended_at

        # v2 (QC H-15): wrap finalization in try/except so we NEVER swallow
        # the primary exception. Log and let original propagate.
        #
        # v5 PATCH-Q4 (Round-4 panel SEV-5, mandatory — 5 of 7 models converged
        # on this exact bet): the UPDATE explicitly EXCLUDES `cursor_state`.
        # The orchestrator main loop writes `cursor_state` inside each batch's
        # transaction (§4.8 — the per-batch cursor write). If __exit__ wrote
        # the full row including cursor_state, a stale value (or None — recorder
        # never sets cursor_state on its instance) would clobber the cursor
        # advance the orchestrator just committed. Recorder owns: status,
        # ended_at, error_detail, all rows_* counters. Recorder does NOT own:
        # cursor_state (orchestrator writes that per-batch), batch_id (set
        # at __enter__ INSERT and immutable). The column list below MUST stay
        # the recorder's owned-set; do not re-add cursor_state on regression.
        try:
            with self.engine.begin() as conn:
                apply_tenant_context(conn, self.tenant_id)
                conn.execute(
                    text(
                        """
                        UPDATE cip_sync_runs
                        SET status = :status,
                            ended_at = :ended_at,
                            rows_received = :rows_received,
                            rows_created = :rows_created,
                            rows_updated = :rows_updated,
                            rows_skipped_unchanged = :rows_skipped_unchanged,
                            rows_skipped_drift = :rows_skipped_drift,
                            rows_skipped_duplicate = :rows_skipped_duplicate,
                            rows_history = :rows_history,
                            error_detail = CAST(:error_detail AS jsonb)
                            -- v5 PATCH-Q4: cursor_state EXCLUDED on purpose.
                            -- Orchestrator writes cursor_state per-batch in §4.8.
                        WHERE id = :id
                        """
                    ),
                    {
                        "status": status,
                        "ended_at": ended_at,
                        "rows_received": self.counters.rows_received,
                        "rows_created": self.counters.rows_created,
                        "rows_updated": self.counters.rows_updated,
                        "rows_skipped_unchanged": self.counters.rows_skipped_unchanged,
                        "rows_skipped_drift": self.counters.rows_skipped_drift,
                        "rows_skipped_duplicate": self.counters.rows_skipped_duplicate,
                        "rows_history": self.counters.rows_history,
                        "error_detail": (
                            None if self.counters.error_detail is None
                            else json.dumps(self.counters.error_detail, default=str)
                        ),
                        "id": str(self.run_id),
                    },
                )
        except Exception as finalize_err:
            import logging
            logging.getLogger(__name__).error(
                "sync_run finalize UPDATE failed (cip_sync_runs row stays 'running'): %s",
                finalize_err,
            )
        # Do NOT suppress original exception — return None.

        # v3 (R2-A3): cip_sync_runs needs new counter columns
        # (rows_received, rows_skipped_unchanged, rows_skipped_drift,
        # rows_skipped_duplicate) per v2 counter split. Author
        # cip_12_sync_runs_counter_split.py BEFORE M2 ships; drop the old
        # rows_ingested/rows_skipped or keep as generated columns for
        # back-compat. Renumbered from v2's `cip_10` for the same SPEC §2 AC #1
        # reservation reason as the `cip_11` migration above.


def _redact(msg: str) -> str:
    """Best-effort redaction of PII patterns from error strings."""
    # M2 stub: trim very long strings, mask email-like tokens.
    import re
    msg = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                 "<email-redacted>", msg)
    return msg[:2000]
```

**v3 (R2-C8) — `snapshot()` removed.** The v2 draft carried a stale `snapshot()`
method using retired counter names (`rows_ingested`, `rows_skipped`) and
wrongly indented outside the class. It wasn't called anywhere. The
orchestrator's `_finalize()` in §4.8 now builds `SyncRunState` directly from
`recorder.counters` + `recorder.final_status` + `recorder.final_ended_at`
after the `with recorder:` block exits, so an in-run snapshot API is
redundant. If a future milestone needs mid-run observability, add it then
(deferred to Phase 8 per §8.13 heartbeat row).

**Note:** Needs `import json` at top.

**Acceptance criteria:**
- `cip_sync_runs` row visible (committed) during the run — operators can watch live.
- On exception, status = `failed` and error_detail populated.
- On counters.error_detail set manually (for partial-batch failures) but no exception: status = `partial`.
- Otherwise: `success`.
- `cursor_state` serialized as JSONB.

**Test pointer:** `tests/integration_mesh/test_sync_run_recorder.py` — 5 cases: success path, exception path, partial path, cursor_state write, concurrent runs with different batch_ids don't collide.

---

### 4.8 `cip/integration_mesh/orchestrator.py` [v2: single stream_records call, batch-scope cursor writes, safety-window, rate-limit budget]

**Purpose:** The top-level function that drives a connector end-to-end. v2 rewrite incorporates QC Round 1 findings C-4, C-5, H-6 through H-13, M-16, M-21.

**First line:** `# foundry: kind=service domain=client-intelligence-platform touches=integration`

**Key v2 changes vs v1 (lineage):**
- C-4: `cursor_state` persisted via `UPDATE cip_sync_runs` in the SAME transaction as the batch's row writes (was: written in recorder `__exit__` → could drift on crash).
- C-5: replaced `isinstance()`-only validation with `validate_connector_shape()` in new `validation.py` (checks method arity/signatures via `inspect`).
- H-6: per-batch rate-limit-retry counter; after 3 consecutive `RateLimitExceeded` retries on the SAME batch, the batch is counted as a consecutive-failure increment (prevents infinite retry loops when the remote stays 429).
- H-7: `SchemaDriftError` wraps `list(mapper.map(rec))` — partial yields from a generator are discarded atomically.
- H-8: batch body in `try/except/finally`; `db.rollback()` always in `finally` so post-commit exceptions (knowledge-hook, cursor UPDATE) leave no half-open transaction.
- H-9: `batch_latest_key` scoped to the batch; only merged into the session-wide `latest_key` AFTER `db.commit()` succeeds.
- H-10: ONE `connector.stream_records(adjusted_cursor, batch_size)` call per run. The orchestrator iterates the generator it returns and chunks the yielded records into batches of `batch_size`. (v1 re-invoked `stream_records` every loop iteration with the advancing cursor — wasteful and broke connectors that assume single-pass semantics.)
- H-11: each batch is deduped on `source_id` before persist — remote endpoints often repeat IDs across page boundaries.
- H-12: `connector.incremental_key(rec)` MUST return a tz-aware `datetime`; tz-naive triggers `TimezoneNaiveError` (fail fast, fail loud — a naive timestamp stored as cursor would be silently wrong on DST shift or cross-region retry).
- H-13: `cursor_safety_window_seconds=300` (TSP) subtracted from the stored cursor before passing to `stream_records`. Protects against clock skew + eventual consistency on the remote (records written to the remote database just before our previous cursor's `last_incremental_key` but visible only after — we'd miss them otherwise).
- M-16: `_register_properties_best_effort` now emits a real `INSERT ... ON CONFLICT DO UPDATE` that preserves `is_custom=true` via `GREATEST(cip_connector_property_registry.is_custom::int, EXCLUDED.is_custom::int)::boolean`.
- M-21: `RateLimitExceeded.retry_after_seconds` is capped at 300s at the orchestrator; anything above 300 is truncated with a warning.

**Key v3 changes vs v2 (lineage):**
- R2-A1: orchestrator now takes an `engine: sa.Engine`, NOT a pre-opened `Session`. Each batch creates a fresh Session via `with Session(engine) as db, db.begin():` — the SQLAlchemy 2.x idiomatic pattern. This eliminates the `InvalidRequestError: A transaction is already begun on this Session` crash that v2 would hit on first batch (Session auto-begins in 2.x, `db.begin()` then raises). The recorder already takes an Engine (§4.7); both components now share the ownership model. Callers pass exactly one Engine.
- R2-A2: `_finalize()` moved AFTER the `with recorder:` block. v2 called `_finalize()` inside the block, which read `recorder.final_status` / `recorder.final_ended_at` — but those attributes are set in `__exit__`, so the inside-with call raised AttributeError on abort paths. v3 uses a `run_abort` flag + break-out pattern: early-exit paths set the flag and break out of the loop; the `with` exits normally; `_finalize()` runs after.
- R2-C7: `cursor_state` bind expression fixed from `sa.func.to_json(new_cursor)` (a SQL-builder expression — wrong type for an executor bind) to `json.dumps(new_cursor, default=str)` + `CAST(:c AS jsonb)`. Added `import json` at module top.
- R2-H3: `validate_connector_shape()` raises `ProtocolShapeError`; the orchestrator does NOT catch it. Entry-shape failures propagate to the caller with zero DB rows touched — matches fail-fast intent.

**Contents (full signature + pseudocode):**

```python
from __future__ import annotations
import json
import logging
import time
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .base import (
    CIPConnector, CIPMapper, KnowledgeText, SyncRunState,
    validate_knowledge_text_metadata,  # v5.2 (Verifier HIGH-A): boundary validator
    DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS,  # 300 — TSP in base.py
    MAX_RATE_LIMIT_SLEEP_SECONDS,          # 300 — TSP in base.py
    MAX_BATCH_RATE_LIMIT_RETRIES,          # 3   — TSP in base.py
    MAX_CONSECUTIVE_BATCH_FAILURES,        # 3   — TSP in base.py
)
from .exceptions import (
    AuthenticationError,
    RateLimitExceeded,
    SchemaDriftError,
    PersistenceError,
    TimezoneNaiveError,
    KnowledgeMetadataValidationError,  # v5.2 (Verifier HIGH-A): raised by boundary validator
)
from .rate_limit import TokenBucket
from .scd_differ import SCDDiffer
from .sync_run_recorder import SyncRunRecorder
from .tenant_context import apply_tenant_context
from .persister import CIPRowPersister
from .validation import validate_connector_shape
from .knowledge_hook import ingest_texts_noop

log = logging.getLogger(__name__)


def run_sync(
    connector: CIPConnector,
    mapper: CIPMapper,
    engine: sa.Engine,
    *,
    tenant_id: UUID,
    client_id: UUID | None = None,
    sync_mode: Literal["full", "incremental"] = "incremental",
    batch_size: int = 500,
    initial_cursor: dict | None = None,
    cursor_safety_window_seconds: int | None = None,
) -> SyncRunState:
    """Drive one connector through authenticate → stream → map → persist → audit.

    v4 (Round-3 panel): `cursor_safety_window_seconds` kwarg defaults to
    `None`. None means "use the connector's `cursor_safety_window_seconds`
    property" (which itself defaults to `DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS`
    in CIPConnectorBase). Callers can still override per-call by passing an
    explicit int.

    v3 (R2-A1): signature takes an `engine` — the orchestrator creates one
    fresh Session per batch via `with Session(engine) as db, db.begin():`
    (SQLAlchemy 2.x idiomatic pattern). v2 took a pre-opened Session and
    called `db.begin()` per batch, which crashes in 2.x because Session
    auto-begins on first DB op.

    Returns the finalized SyncRunState built from `recorder.counters` +
    finalized fields set by `recorder.__exit__` (v3 R2-A2: `_finalize()` is
    called AFTER the `with recorder:` block).

    Does NOT raise on partial failures (records them as cip_sync_runs.status='partial').
    Does raise on fatal framework errors (AuthenticationError, TimezoneNaiveError,
    connector-shape validation errors on entry).
    """
    # ── 0. Validate connector shape (C-5). Fails fast before we write a sync_run row.
    #     Raises ProtocolShapeError (TypeError subclass); orchestrator lets it
    #     propagate — entry-shape failures are caller bugs, not run failures.
    validate_connector_shape(connector, mapper)

    bucket = TokenBucket(connector.rate_limit_policy)
    differ = SCDDiffer()

    # Recorder takes the Engine (v2, per §4.7). It opens its own short-lived
    # connection for the INSERT-row-at-enter and UPDATE-row-at-exit, never
    # sharing any orchestrator Session.
    recorder = SyncRunRecorder(
        engine=engine,
        tenant_id=tenant_id,
        client_id=client_id,
        connector_id=connector.connector_id,
        connector_name=connector.__class__.__name__,
        sync_mode=sync_mode,
    )

    # v3 (R2-A2): early-exit paths set this flag + break, so the `with`
    # exits normally and `_finalize()` runs AFTER. No more reads of
    # recorder.final_status inside the with block.
    consecutive_batch_failures = 0

    with recorder as run:
        # ── 1. Authenticate (outside any batch txn).
        try:
            connector.authenticate()
        except Exception as e:
            raise AuthenticationError(str(e)) from e

        # ── 2. Register properties (best-effort; M6 hardens this).
        _register_properties_best_effort(engine, connector, tenant_id)

        # ── 3. Compute safety-window-adjusted cursor (H-13).
        cursor = initial_cursor if sync_mode == "incremental" else None
        # v4 (Round-3 panel): kwarg overrides; None falls back to connector's property.
        effective_window = (
            cursor_safety_window_seconds
            if cursor_safety_window_seconds is not None
            else connector.cursor_safety_window_seconds
        )
        adjusted_cursor = _apply_safety_window(cursor, effective_window)

        # ── 4. ONE stream_records call per run (H-10). Iterate its generator and
        #    chunk into `batch_size` batches locally.
        #
        # v5 PATCH-NR-2 (Round-4 panel SEV-4): wrap the generator in
        # `contextlib.closing()` so .close() fires on ANY exit path (normal
        # completion, exception, KeyboardInterrupt). Without this, an
        # orchestrator-side exception (e.g., TimezoneNaiveError on batch 7 of
        # 50) leaves the connector's underlying HTTP session / pagination
        # cursor open until GC. .close() throws GeneratorExit into the
        # generator; the connector's `finally:` blocks catch it and clean up
        # network state. (Add `from contextlib import closing` at top.)
        record_iter = _chunked(
            connector.stream_records(adjusted_cursor, batch_size),
            batch_size,
        )
        # Note: _chunked() must yield from the underlying generator AND must
        # propagate .close() — implementation in §4.8 helpers wraps the input
        # in a try/finally so the inner generator's .close() runs when
        # _chunked itself is closed. See _chunked() definition below.

        aborted = False
        for raw_batch in record_iter:
            if aborted:
                break
            # Rate-limit retry budget per batch (H-6).
            batch_rl_retries = 0
            batch_committed = False

            while not batch_committed:
                try:
                    bucket.acquire()  # paces normal calls

                    # ── 4a. Dedupe on source_id within the batch (H-11).
                    batch = _dedupe_by_source_id(raw_batch)
                    batch_latest_key: datetime | None = None  # H-9

                    # ── 4b. Persist batch. v3 (R2-A1): per-batch Session from
                    #     the Engine, using SQLAlchemy 2.x idiomatic
                    #     `with Session(engine) as db, db.begin():`. Session
                    #     auto-begins on first op; the outer `db.begin()` wraps
                    #     the whole batch in a single txn that commits on
                    #     normal exit and rolls back on exception.
                    try:
                        # v4 (Round-3 panel HIGH): explicit autoflush=False +
                        # expire_on_commit=False prevents subtle mid-batch
                        # implicit-flush deadlocks. Per-batch Session is
                        # short-lived; no benefit to autoflush, real cost in
                        # surprise.
                        with Session(engine, autoflush=False, expire_on_commit=False) as db, db.begin():
                            apply_tenant_context(db, tenant_id)
                            persister = CIPRowPersister(db, differ)

                            for rec in batch:
                                # H-7: list() wraps the generator so a mid-yield drift
                                # error discards any partial rows.
                                try:
                                    rows = list(mapper.map(rec))
                                except SchemaDriftError as sd:
                                    log.warning(
                                        "schema drift on record %s: %s",
                                        _safe_id(rec), sd,
                                    )
                                    run.counters.rows_skipped_drift += 1
                                    continue

                                for row in rows:
                                    result = persister.persist(
                                        row,
                                        tenant_id=tenant_id,
                                        connector_id=connector.connector_id,
                                        batch_id=run.batch_id,
                                    )
                                    run.counters.rows_created += result.created
                                    run.counters.rows_updated += result.updated
                                    run.counters.rows_skipped_unchanged += result.skipped
                                    run.counters.rows_history += result.history

                                # Non-fatal knowledge-ingest hook (D-067).
                                # v5.2 (Round-6 Call A — Verifier HIGH-A 2026-04-29):
                                # validate metadata at the orchestrator boundary BEFORE
                                # handing texts to ingest_texts_noop. Per D-133 amendment,
                                # mappers may emit total=False metadata; orchestrator
                                # FINALIZES required core keys (tenant_id, source_system,
                                # extracted_at, connector_version — known by orchestrator
                                # state) then calls validate_knowledge_text_metadata.
                                try:
                                    raw_texts = mapper.ingest_as_knowledge(rec)  # list[KnowledgeText]
                                    if raw_texts:
                                        finalized_texts = []
                                        for t in raw_texts:
                                            # Orchestrator-finalize: fill keys mappers don't know
                                            md = dict(t.metadata)
                                            md.setdefault("source_system", connector.connector_id)
                                            md.setdefault("tenant_id", tenant_id)
                                            md.setdefault("connector_version", getattr(connector, "version", "0.0.0"))
                                            md.setdefault("extracted_at", _utcnow())
                                            md.setdefault("ingestion_batch_id", run.batch_id)
                                            # Boundary validation — raises KnowledgeMetadataValidationError
                                            # or TimezoneNaiveError on contract violation.
                                            validate_knowledge_text_metadata(md, where=f"ingest_as_knowledge for record {_safe_id(rec)}")
                                            finalized_texts.append(KnowledgeText(text=t.text, metadata=md))
                                        ingest_texts_noop(finalized_texts)  # M5 replaces with real impl
                                except (KnowledgeMetadataValidationError, TimezoneNaiveError):
                                    # Validation errors are FATAL — re-raise (the contract
                                    # was violated; do NOT swallow it as "non-fatal").
                                    raise
                                except Exception as ke:
                                    log.warning(
                                        "knowledge-ingest failed (non-fatal): %s", ke,
                                    )

                                # H-12: tz-naive datetimes are a silent correctness bug.
                                try:
                                    k = connector.incremental_key(rec)
                                except Exception as e:
                                    log.warning("incremental_key failed on %s: %s",
                                                _safe_id(rec), e)
                                    k = None
                                if k is not None:
                                    if k.tzinfo is None or k.utcoffset() is None:
                                        raise TimezoneNaiveError(
                                            f"incremental_key returned tz-naive datetime "
                                            f"for record {_safe_id(rec)}: {k!r}"
                                        )
                                    if batch_latest_key is None or k > batch_latest_key:
                                        batch_latest_key = k

                            run.counters.rows_received += len(batch)

                            # ── 4c. Write cursor_state INSIDE the same transaction (C-4).
                            #     v3 (R2-C7): json.dumps(..., default=str) — the bind
                            #     value MUST be a JSON string (Postgres CASTs it to
                            #     jsonb). sa.func.to_json(...) is a SQL-builder
                            #     expression, not a bind value, and fails at executor.
                            if batch_latest_key is not None:
                                new_cursor = {
                                    "last_incremental_key": batch_latest_key.isoformat(),
                                }
                                db.execute(
                                    sa.text(
                                        "UPDATE cip_sync_runs "
                                        "SET cursor_state = CAST(:c AS jsonb) "
                                        "WHERE id = :id"
                                    ),
                                    {
                                        "c": json.dumps(new_cursor, default=str),
                                        "id": str(run.run_id),
                                    },
                                )
                                run.counters.cursor_state = new_cursor

                            # `with db.begin():` commits on normal exit.
                        batch_committed = True
                        consecutive_batch_failures = 0

                    except PersistenceError as pe:
                        # The `with db.begin():` context rolled the batch back.
                        consecutive_batch_failures += 1
                        log.error("batch failed: %s (consecutive=%d)",
                                  pe, consecutive_batch_failures)
                        run.counters.error_detail = _redact({
                            "type": "PersistenceError",
                            "message": str(pe),
                            "consecutive_failures": consecutive_batch_failures,
                        })
                        if consecutive_batch_failures >= MAX_CONSECUTIVE_BATCH_FAILURES:
                            log.error(
                                "%d consecutive batch failures, aborting run",
                                MAX_CONSECUTIVE_BATCH_FAILURES,
                            )
                            aborted = True  # v3 (R2-A2): break out of the with cleanly
                            break
                        break  # break out of the rl-retry while, move to next batch

                except RateLimitExceeded as rl:
                    batch_rl_retries += 1
                    sleep_s = min(rl.retry_after_seconds, MAX_RATE_LIMIT_SLEEP_SECONDS)
                    if sleep_s < rl.retry_after_seconds:
                        log.warning(
                            "RateLimitExceeded asked for %ss, capped at %ss (M-21)",
                            rl.retry_after_seconds, MAX_RATE_LIMIT_SLEEP_SECONDS,
                        )
                    if batch_rl_retries > MAX_BATCH_RATE_LIMIT_RETRIES:
                        # H-6: rate-limit exhaustion counts as a batch failure.
                        consecutive_batch_failures += 1
                        log.error(
                            "rate-limit retries exhausted on batch "
                            "(retries=%d, consecutive_failures=%d)",
                            batch_rl_retries, consecutive_batch_failures,
                        )
                        run.counters.error_detail = _redact({
                            "type": "RateLimitExhaustion",
                            "batch_retries": batch_rl_retries,
                            "consecutive_failures": consecutive_batch_failures,
                        })
                        if consecutive_batch_failures >= MAX_CONSECUTIVE_BATCH_FAILURES:
                            aborted = True  # v3 (R2-A2)
                            break
                        break
                    log.warning("rate limited (retry %d/%d), sleeping %ss",
                                batch_rl_retries, MAX_BATCH_RATE_LIMIT_RETRIES, sleep_s)
                    time.sleep(sleep_s)
                    continue  # retry same batch

    # v3 (R2-A2): `with recorder:` has exited. `recorder.final_status` and
    # `recorder.final_ended_at` are now populated by `__exit__`. Build and
    # return the finalized state here — outside the with.
    return _finalize(recorder)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _finalize(recorder: SyncRunRecorder) -> SyncRunState:
    """Build the post-__exit__ SyncRunState using the finalized fields the
    recorder sets in its __exit__ (status, ended_at).

    v3 (R2-A2): MUST be called AFTER the `with recorder:` block has exited.
    Reads `recorder.final_status` and `recorder.final_ended_at`, which are
    only set inside `recorder.__exit__`.
    """
    return SyncRunState(
        run_id=recorder.run_id,
        batch_id=recorder.batch_id,
        status=recorder.final_status,        # set in recorder.__exit__
        started_at=recorder.started_at,
        ended_at=recorder.final_ended_at,    # set in recorder.__exit__
        rows_received=recorder.counters.rows_received,
        rows_created=recorder.counters.rows_created,
        rows_updated=recorder.counters.rows_updated,
        rows_skipped_unchanged=recorder.counters.rows_skipped_unchanged,
        rows_skipped_drift=recorder.counters.rows_skipped_drift,
        rows_skipped_duplicate=recorder.counters.rows_skipped_duplicate,
        rows_history=recorder.counters.rows_history,
        error_detail=recorder.counters.error_detail,
        cursor_state=getattr(recorder.counters, "cursor_state", None),
    )


def _apply_safety_window(
    cursor: dict | None, window_seconds: int
) -> dict | None:
    """H-13: rewind the stored cursor's last_incremental_key by window_seconds
    to catch records that were written on the remote just before the cursor's
    instant but only became visible (due to replica lag, index update, etc.)
    after our previous sync completed. Pure function; window_seconds=0 disables."""
    if cursor is None or window_seconds <= 0:
        return cursor
    key_iso = cursor.get("last_incremental_key")
    if not key_iso:
        return cursor
    from datetime import timedelta
    parsed = datetime.fromisoformat(key_iso)
    if parsed.tzinfo is None:
        # Don't silently upgrade — the cursor was written by us, so if it's naive
        # it's a bug we want to see.
        raise TimezoneNaiveError(
            f"stored cursor last_incremental_key is tz-naive: {key_iso!r}"
        )
    adjusted = parsed - timedelta(seconds=window_seconds)
    return {**cursor, "last_incremental_key": adjusted.isoformat()}


def _chunked(gen, size: int):
    """Chunk a generator of records into lists of `size`. The final chunk may
    be smaller. Does NOT re-invoke the producer; consumes its generator once."""
    batch: list[dict] = []
    for rec in gen:
        batch.append(rec)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _dedupe_by_source_id(batch: list[dict]) -> list[dict]:
    """H-11: keep only the LAST occurrence of each source_id within a batch
    (matches 'last write wins' for SCD Type 2)."""
    seen_idx: dict[str, int] = {}
    for i, rec in enumerate(batch):
        sid = str(rec.get("source_id") or rec.get("id") or "")
        if not sid:
            continue
        seen_idx[sid] = i
    return [batch[i] for i in sorted(seen_idx.values())] if seen_idx else list(batch)


def _register_properties_best_effort(
    engine: sa.Engine, connector: CIPConnector, tenant_id: UUID,
) -> None:
    """Upsert property descriptors into cip_connector_property_registry.
    Best-effort: log but don't fail the sync on a registry write error.

    v3 (R2-A1): takes an Engine, opens a short-lived Session for this
    registry write. Isolated from the orchestrator's per-batch Sessions so
    a registry write failure can't poison later batch transactions.

    M-16: real INSERT ... ON CONFLICT DO UPDATE with is_custom preservation.
    R2-C5: uses `p.data_type` (field was renamed from `property_type` in
    PropertyDescriptor to match the SQL column name).
    """
    try:
        props = connector.describe_schema()
    except Exception as e:
        log.warning("describe_schema failed (non-fatal): %s", e)
        return

    try:
        # v4 (Round-3 panel HIGH): autoflush=False + expire_on_commit=False
        # — same rationale as the per-batch Session in run_sync above.
        with Session(engine, autoflush=False, expire_on_commit=False) as db, db.begin():
            apply_tenant_context(db, tenant_id)
            for p in props:  # p: PropertyDescriptor
                db.execute(
                    sa.text(
                        """
                        INSERT INTO cip_connector_property_registry (
                            tenant_id, connector_id, object_type, property_name,
                            data_type, is_custom, storage_location, column_name,
                            description
                        ) VALUES (
                            :tenant_id, :connector_id, :object_type, :property_name,
                            :data_type, :is_custom, :storage_location, :column_name,
                            :description
                        )
                        ON CONFLICT (tenant_id, connector_id, object_type, property_name)
                        DO UPDATE SET
                            data_type        = EXCLUDED.data_type,
                            storage_location = EXCLUDED.storage_location,
                            column_name      = EXCLUDED.column_name,
                            description      = EXCLUDED.description,
                            -- is_custom is true if EITHER side is true (OR semantics)
                            is_custom = (
                                cip_connector_property_registry.is_custom
                                OR EXCLUDED.is_custom
                            )
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "connector_id": connector.connector_id,
                        "object_type": p.object_type,
                        "property_name": p.property_name,
                        "data_type": p.data_type,
                        "is_custom": p.is_custom,
                        "storage_location": p.storage_location,
                        "column_name": p.column_name,
                        "description": p.description,
                    },
                )
    except Exception as e:
        log.warning("property registry write failed (non-fatal): %s", e)


def _safe_id(rec: dict) -> str:
    return str(rec.get("id") or rec.get("source_id") or "?")


def _redact(d: dict) -> dict:
    """Strip obvious PII (emails) from error_detail JSONB before persist.
    Matches the recorder's _redact (keep in sync). Conservative: we only
    scrub string values that look like emails."""
    import re
    EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    def _scrub(v):
        if isinstance(v, str):
            return EMAIL.sub("<redacted:email>", v)
        if isinstance(v, dict):
            return {k: _scrub(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_scrub(x) for x in v]
        return v
    return _scrub(d)
```

**Acceptance criteria (verified by harness + unit tests; see §9 for the exact verification method per criterion):**
- v4 signature: `run_sync(connector, mapper, engine, *, tenant_id, client_id=None, sync_mode="incremental", batch_size=500, initial_cursor=None, cursor_safety_window_seconds=None) -> SyncRunState`. (v3 R2-A1 dropped the explicit `db: Session` positional — the orchestrator creates per-batch Sessions from the Engine internally. v4 changed `cursor_safety_window_seconds` default from `DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS` to `None` so the connector's own per-connector property is consulted when the caller doesn't override. SPEC §3 path-set is now locked at `cip/integration_mesh/` per D-146; signature is canonical.)
- `stream_records` is invoked EXACTLY ONCE per run (asserted in `test_incremental_sync.py::test_stream_records_called_once` by a Mock counter on the FixtureConnector).
- Each batch is deduped on `source_id` (asserted in `test_incremental_sync.py::test_intra_batch_dedupe`).
- tz-naive `incremental_key()` raises `TimezoneNaiveError` (asserted in `test_incremental_sync.py::test_tz_naive_rejected`).
- `cursor_state` row on `cip_sync_runs` is updated in the same transaction as the batch's inserts (asserted in `test_incremental_sync.py::test_cursor_atomic_with_batch` — simulate a post-commit crash and verify cursor is either fully advanced or not at all).
- `RateLimitExceeded` triggers sleep + retry on the same batch, capped at `MAX_RATE_LIMIT_SLEEP_SECONDS=300` and `MAX_BATCH_RATE_LIMIT_RETRIES=3` (asserted in `test_incremental_sync.py::test_rate_limit_budget`).
- `SchemaDriftError` at mapper level discards any partial rows from the same record's `map()` generator (asserted in `test_sync_run_audit.py::test_drift_is_atomic_per_record`).
- Knowledge-ingest hook failure is logged, non-fatal (D-067).
- Final `SyncRunState` reflects the recorder's post-`__exit__` fields (status, ended_at set in `__exit__`).

**Test pointer:** `test_incremental_sync.py`, `test_sync_run_audit.py`, `test_tenant_scoping.py`.

---

### 4.9 `cip/integration_mesh/knowledge_hook.py` [v2: takes `list[KnowledgeText]`, not `list[str]`]

**Purpose:** Placeholder so the orchestrator import doesn't break. M5 replaces this with real Pinecone+FalkorDB ingestion. Locked to `list[KnowledgeText]` now (D-133) so M5 does NOT churn the Protocol signature.

**First line:** `# foundry: kind=service domain=client-intelligence-platform touches=knowledge`

**Contents:**

```python
from __future__ import annotations

from .base import KnowledgeText


def ingest_texts_noop(texts: list[KnowledgeText]) -> None:
    """M2 stub. M5 replaces with actual Knowledge+Graph ingestion.

    Per D-067, extraction failures are non-fatal. Orchestrator logs and
    continues. This function MUST match M5's real signature:
    `def ingest_texts(texts: list[KnowledgeText]) -> None`. Keeping the
    input type locked (D-133) avoids Protocol churn at the M5 boundary.
    """
    # Intentionally a no-op in M2.
    _ = texts  # suppress unused warning
    return None
```

**Acceptance criteria:** File exists, importable, no-op. Signature takes `list[KnowledgeText]` not `list[str]`. `mypy --strict` passes on the orchestrator's invocation.

---

### 4.10 `cip/integration_mesh/__init__.py`

Re-export the Protocols + dataclasses + `run_sync` + exceptions + validation entry point for the public API.

```python
# foundry: kind=service domain=client-intelligence-platform touches=integration
"""CIP Integration Mesh public API."""
from .base import (
    CIPConnector, CIPMapper,
    CIPConnectorBase, CIPMapperBase,
    PropertyDescriptor, CIPRow, RateLimitPolicy, SyncRunState,
    KnowledgeText,
    KnowledgeTextMetadata,  # v5 PATCH-Q6 (D-133 amendment 2026-04-29)
    KNOWLEDGE_TEXT_REQUIRED_KEYS,  # v5.2 (Round-6 Call A — Verifier HIGH-B)
    validate_knowledge_text_metadata,  # v5.2 (Round-6 Call A — Verifier HIGH-B)
    ALLOWED_CIP_TABLES, HISTORY_TABLE_BY_CURRENT,
    DEFAULT_RATE_LIMIT,
    DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS,
    MAX_RATE_LIMIT_SLEEP_SECONDS,
    MAX_BATCH_RATE_LIMIT_RETRIES,
    MAX_CONSECUTIVE_BATCH_FAILURES,
)
from .exceptions import (
    ConnectorError, AuthenticationError, RateLimitExceeded,
    SchemaDriftError, PersistenceError, TimezoneNaiveError,
    KnowledgeMetadataValidationError,  # v5.2 (Round-6 Call A)
)
from .orchestrator import run_sync
from .validation import validate_connector_shape, ProtocolShapeError

__all__ = [
    "CIPConnector", "CIPMapper",
    "CIPConnectorBase", "CIPMapperBase",
    "PropertyDescriptor", "CIPRow", "RateLimitPolicy", "SyncRunState",
    "KnowledgeText",
    "KnowledgeTextMetadata",  # v5 PATCH-Q6
    "KNOWLEDGE_TEXT_REQUIRED_KEYS",  # v5.2 (Verifier HIGH-B)
    "validate_knowledge_text_metadata",  # v5.2 (Verifier HIGH-B)
    "ALLOWED_CIP_TABLES", "HISTORY_TABLE_BY_CURRENT",
    "DEFAULT_RATE_LIMIT",
    "DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS",
    "MAX_RATE_LIMIT_SLEEP_SECONDS",
    "MAX_BATCH_RATE_LIMIT_RETRIES",
    "MAX_CONSECUTIVE_BATCH_FAILURES",
    "ConnectorError", "AuthenticationError", "RateLimitExceeded",
    "SchemaDriftError", "PersistenceError", "TimezoneNaiveError",
    "KnowledgeMetadataValidationError",  # v5.2 (Verifier HIGH-B)
    "run_sync",
    "validate_connector_shape", "ProtocolShapeError",
]
```

---

### 4.11 `cip/integration_mesh/validation.py` [NEW in v2 — closes C-5]

**Purpose:** Runtime entry-check that a given connector + mapper satisfy the CIP Protocols at BOTH the method-present level (what `isinstance()` catches) AND the signature level (what `isinstance()` misses). Called once at the top of `run_sync()`; raises before any DB row is written.

**First line:** `# foundry: kind=service domain=client-intelligence-platform touches=integration`

**Contents:**

```python
from __future__ import annotations

import inspect
from typing import Any, get_type_hints

from .base import CIPConnector, CIPMapper


class ProtocolShapeError(TypeError):
    """Raised when a connector/mapper instance fails shape validation."""


# Method → expected (positional_arg_count_including_self, required_kwargs).
# `...` for positional count means "any" (used where the spec allows varargs).
_CONNECTOR_SHAPE: dict[str, tuple[int, frozenset[str]]] = {
    "authenticate":     (1, frozenset()),
    "stream_records":   (3, frozenset()),   # self, cursor, batch_size
    "describe_schema":  (1, frozenset()),
    "incremental_key":  (2, frozenset()),   # self, record
}

_MAPPER_SHAPE: dict[str, tuple[int, frozenset[str]]] = {
    "map":                 (2, frozenset()),  # self, record
    "overflow_fields":     (1, frozenset()),
    "ingest_as_knowledge": (2, frozenset()),  # self, record
}

_CONNECTOR_ATTRS = frozenset({"connector_id", "rate_limit_policy", "cursor_safety_window_seconds"})  # v4: cursor_safety_window_seconds added — required Protocol member
_MAPPER_ATTRS    = frozenset({"object_type", "target_table"})


def validate_connector_shape(connector: Any, mapper: Any) -> None:
    """Raise ProtocolShapeError if connector/mapper don't satisfy CIP shape.

    Checks (in order):
    1. isinstance against @runtime_checkable Protocols (missing methods).
    2. Required class attributes exist (connector_id, etc.).
    3. Each method's parameter count matches the spec (wrong signatures).
    4. stream_records MUST be a generator function (inspect.isgeneratorfunction).
    5. map MUST be a generator function.

    Does NOT verify TYPE annotations — that's the conformance harness.

    v4 (Round-3 panel HIGH) — known false-negative on decorated methods:
        `inspect.isgeneratorfunction()` returns False for a function wrapped
        in a decorator that doesn't preserve the underlying generator nature.

    v5 PATCH-Q3 (Round-4 panel SEV-5, mandatory): use `inspect.unwrap()` to
        walk the entire `__wrapped__` chain before checking generator-ness.
        Connectors using `functools.wraps`-correct decorators now pass;
        connectors using broken decorators (no `__wrapped__` attribute) still
        fail with the original error message.

        Defer beartype/typeguard runtime-typecheck dep — 3-of-7 Round-3 panel
        models recommended deferral; gemini-3-pro alone pushed adoption.
        Adding 50KB+ dep with import-time cost for one validator is over-
        engineering at M2 scale (≤3 connectors in next 12 months).
    """
    # (1) + (2) connector
    if not isinstance(connector, CIPConnector):
        raise ProtocolShapeError(
            f"{type(connector).__name__} does not satisfy CIPConnector "
            f"(missing one of: authenticate, stream_records, describe_schema, "
            f"incremental_key, connector_id, rate_limit_policy)"
        )
    for attr in _CONNECTOR_ATTRS:
        if not hasattr(connector, attr):
            raise ProtocolShapeError(
                f"{type(connector).__name__} missing required attribute {attr!r}"
            )

    # (1) + (2) mapper
    if not isinstance(mapper, CIPMapper):
        raise ProtocolShapeError(
            f"{type(mapper).__name__} does not satisfy CIPMapper"
        )
    for attr in _MAPPER_ATTRS:
        if not hasattr(mapper, attr):
            raise ProtocolShapeError(
                f"{type(mapper).__name__} missing required attribute {attr!r}"
            )

    # (3) method arity
    _check_arity("connector", connector, _CONNECTOR_SHAPE)
    _check_arity("mapper", mapper, _MAPPER_SHAPE)

    # (4) stream_records generator check
    # v5 PATCH-Q3: inspect.unwrap() walks __wrapped__ chain so decorator-wrapped
    # generator functions (using @functools.wraps) pass the check.
    sr = connector.stream_records.__func__ if hasattr(connector.stream_records, "__func__") else connector.stream_records
    if not inspect.isgeneratorfunction(inspect.unwrap(sr)):
        raise ProtocolShapeError(
            f"{type(connector).__name__}.stream_records must be a generator "
            f"function (use `yield`, not `return [...]`). If using a decorator, "
            f"ensure it preserves __wrapped__ via functools.wraps and yields "
            f"from the inner generator."
        )

    # (5) map generator check
    # v5 PATCH-Q3: same inspect.unwrap() pattern.
    mp = mapper.map.__func__ if hasattr(mapper.map, "__func__") else mapper.map
    if not inspect.isgeneratorfunction(inspect.unwrap(mp)):
        raise ProtocolShapeError(
            f"{type(mapper).__name__}.map must be a generator function"
        )


def _check_arity(
    role: str, obj: Any, shape: dict[str, tuple[int, frozenset[str]]],
) -> None:
    for name, (expected_pos, required_kwargs) in shape.items():
        method = getattr(obj, name)
        sig = inspect.signature(method)
        # Bound methods have self already removed from sig; compensate by
        # subtracting 1 from expected_pos.
        expected = expected_pos - 1
        actual_positional = [
            p for p in sig.parameters.values()
            if p.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if len(actual_positional) != expected:
            raise ProtocolShapeError(
                f"{role} {type(obj).__name__}.{name} has "
                f"{len(actual_positional)} positional parameter(s); "
                f"expected {expected}"
            )
        for kw in required_kwargs:
            if kw not in sig.parameters:
                raise ProtocolShapeError(
                    f"{role} {type(obj).__name__}.{name} missing "
                    f"required keyword argument {kw!r}"
                )
```

**Acceptance criteria:**
- `validate_connector_shape(MockConnector(), MockMapper())` returns `None` on conforming instances.
- A connector whose `stream_records` returns a list (not a generator) raises `ProtocolShapeError`.
- A connector whose `incremental_key` takes no record argument raises `ProtocolShapeError`.
- A mapper missing `overflow_fields` raises `ProtocolShapeError` (caught at the `isinstance` step).

**Test pointer:** `tests/integration_mesh/test_validation.py::{test_valid, test_stream_records_not_generator, test_incremental_key_wrong_arity, test_missing_overflow_fields}`.

---

## 5. Conformance Harness — Six Tests (§SPEC §11)

All six live under `tests/fixtures/connector_conformance/`. The harness runs against a `MockConnector` + `MockMapper` defined in that folder's `conftest.py` (NOT a real FixtureConnector — that's M3). Each test is self-contained and parametrized over `(MockConnector, MockMapper)` fixtures so that when M3 lands, the same tests re-run against the real `FixtureConnector` with zero changes.

### 5.1 `conftest.py` — shared fixtures

Defines:
- `mock_connector(tenant_id)` — factory returning a `MockConnector` instance with configurable record stream.
- `mock_mapper()` — returns a `MockMapper` mapping to `cip_contacts`.
- `db_session()` — fresh in-memory SQLite OR Postgres testcontainer depending on test needs (RLS tests need Postgres; logic tests can use SQLite). Prefer Postgres via testcontainers for correctness.
- `seeded_migrations(db_session)` — runs alembic upgrade head on the test DB so cip_* tables exist.
- `TEST_TENANT_ID = UUID("00000000-0000-0000-0000-0000000000cc")` (use session-scoped).

Mock impls (import `KnowledgeText` at top of conftest.py: `from cip.integration_mesh import CIPConnectorBase, CIPMapperBase, CIPRow, KnowledgeText, PropertyDescriptor, DEFAULT_RATE_LIMIT`):

```python
# MockConnector
class MockConnector(CIPConnectorBase):
    connector_id = "mock-connector-v1"
    rate_limit_policy = DEFAULT_RATE_LIMIT  # explicit — validator checks attr presence
    def __init__(self, tenant_id, records, schema):
        self.tenant_id = tenant_id
        self._records = list(records)
        self._schema = [PropertyDescriptor(**s) for s in schema]
        self.authenticated = False
    def authenticate(self):
        self.authenticated = True
    def stream_records(self, cursor, batch_size):
        last_key = None
        if cursor and "last_incremental_key" in cursor:
            last_key = datetime.fromisoformat(cursor["last_incremental_key"])
        # NOTE v2: the orchestrator now calls stream_records ONCE per run
        # (H-10). Yield every eligible record; the orchestrator handles chunking.
        # batch_size remains a hint the connector MAY use for page-size tuning.
        for rec in self._records:
            rec_ts = datetime.fromisoformat(rec["updated_at"])
            if last_key and rec_ts <= last_key:
                continue
            yield rec
    def describe_schema(self):
        return self._schema
    def incremental_key(self, record):
        # Must return tz-aware datetime (H-12). fromisoformat on our UTC strings does.
        return datetime.fromisoformat(record["updated_at"])

# MockMapper
class MockMapper(CIPMapperBase):
    object_type = "contact"
    target_table = "cip_contacts"
    def map(self, record):
        yield CIPRow(
            target_table="cip_contacts",
            source_id=record["id"],
            fields={
                "first_name": record.get("first_name"),
                "last_name": record.get("last_name"),
                "email": record.get("email"),
            },
            overflow={k: v for k, v in record.items()
                      if k not in {"id", "first_name", "last_name", "email", "updated_at"}},
            authority="ingested",
        )
    def overflow_fields(self):
        return ["mock_extra_1", "mock_extra_2"]
    def ingest_as_knowledge(self, record):
        # v2: locked return type list[KnowledgeText] (D-133).
        # v5.2 (Call A 2026-04-29): with total=False the mapper only populates
        # keys it KNOWS — `source_id` here. Orchestrator finalizes the rest
        # (source_system, extracted_at, tenant_id, connector_version) before
        # calling validate_knowledge_text_metadata() at the boundary.
        # No more "lying mock" — placeholder values gone.
        email = record.get("email")
        if not email:
            return []
        return [KnowledgeText(
            text=email,
            metadata={"source_id": record["id"]},
        )]
```

### 5.1.1 Canonical fixture records [v2 — closes Gap Analyst finding #4]

Fixed corpus used across ALL six conformance tests so the property registry + SCD + incremental-key paths all key off the same input. Lives in `tests/fixtures/connector_conformance/fixtures/records.py`:

```python
# foundry: kind=fixture domain=client-intelligence-platform
"""Canonical fixture records used by the conformance harness.

Each record is a dict (not a dataclass) because that matches what real
connectors yield from their paginated API calls. Timestamps are UTC ISO-8601
WITH timezone — tz-naive timestamps would be rejected by the orchestrator.
"""
from datetime import datetime, timezone

def _ts(h: int) -> str:
    # Deterministic timestamps: 2026-04-20 00:00:00+00:00 + h hours.
    return datetime(2026, 4, 20, h, 0, 0, tzinfo=timezone.utc).isoformat()

CANONICAL_CONTACTS: list[dict] = [
    # Baseline 10 records (T0..T9) for incremental-sync test.
    {"id": "c001", "source_id": "c001", "first_name": "Alice",  "last_name": "Ng",     "email": "alice@ex.com",  "updated_at": _ts(0)},
    {"id": "c002", "source_id": "c002", "first_name": "Bob",    "last_name": "Patel",  "email": "bob@ex.com",    "updated_at": _ts(1)},
    {"id": "c003", "source_id": "c003", "first_name": "Carlos", "last_name": "Reyes",  "email": "carlos@ex.com", "updated_at": _ts(2)},
    {"id": "c004", "source_id": "c004", "first_name": "Dana",   "last_name": "Singh",  "email": "dana@ex.com",   "updated_at": _ts(3)},
    {"id": "c005", "source_id": "c005", "first_name": "Elena",  "last_name": "Torres", "email": "elena@ex.com",  "updated_at": _ts(4)},
    {"id": "c006", "source_id": "c006", "first_name": "Farouk", "last_name": "Umar",   "email": "farouk@ex.com", "updated_at": _ts(5)},
    {"id": "c007", "source_id": "c007", "first_name": "Greta",  "last_name": "Vargas", "email": "greta@ex.com",  "updated_at": _ts(6)},
    {"id": "c008", "source_id": "c008", "first_name": "Hiro",   "last_name": "Watts",  "email": "hiro@ex.com",   "updated_at": _ts(7)},
    {"id": "c009", "source_id": "c009", "first_name": "Inez",   "last_name": "Xu",     "email": "inez@ex.com",   "updated_at": _ts(8)},
    {"id": "c010", "source_id": "c010", "first_name": "Juno",   "last_name": "Yoo",    "email": "juno@ex.com",   "updated_at": _ts(9)},
]

# Delta records used by the "second run" portion of test_incremental_sync.
DELTA_CONTACTS: list[dict] = [
    {"id": "c011", "source_id": "c011", "first_name": "Kai",  "last_name": "Zhao", "email": "kai@ex.com",  "updated_at": _ts(10)},
    {"id": "c012", "source_id": "c012", "first_name": "Lena", "last_name": "Ade",  "email": "lena@ex.com", "updated_at": _ts(11)},
    # Duplicate source_id within a single batch — dedup test fixture.
    {"id": "c003", "source_id": "c003", "first_name": "Carlos", "last_name": "Reyes", "email": "carlos-v2@ex.com", "updated_at": _ts(12)},
]

# Schema: 3 column-stored + 2 overflow-stored = 5 property descriptors.
CANONICAL_SCHEMA = [
    # column-stored
    {"object_type": "contact", "property_name": "first_name", "data_type": "string", "is_custom": False, "storage_location": "column",   "column_name": "first_name", "description": "Given name."},
    {"object_type": "contact", "property_name": "last_name",  "data_type": "string", "is_custom": False, "storage_location": "column",   "column_name": "last_name",  "description": "Family name."},
    {"object_type": "contact", "property_name": "email",      "data_type": "string", "is_custom": False, "storage_location": "column",   "column_name": "email",      "description": "Primary email."},
    # overflow-stored
    {"object_type": "contact", "property_name": "mock_extra_1", "data_type": "string", "is_custom": True, "storage_location": "overflow", "column_name": None, "description": "Tenant-defined custom property 1."},
    {"object_type": "contact", "property_name": "mock_extra_2", "data_type": "string", "is_custom": True, "storage_location": "overflow", "column_name": None, "description": "Tenant-defined custom property 2."},
]
```

Rationale for locking the corpus now: three of six conformance tests (incremental sync, property registry, SCD history) each construct their own inline records in v1, so regressions in one can pass while another silently uses a different shape. A single canonical corpus catches this.

**v3 (R2-H2) fixture count invariants** — assert these at the top of the first test that imports the fixtures, so a fixture-file regression fails loud:

```python
from tests.fixtures.connector_conformance.fixtures.records import (
    CANONICAL_CONTACTS, DELTA_CONTACTS, CANONICAL_SCHEMA,
)

assert len(CANONICAL_CONTACTS) == 10, "baseline corpus must be 10 records"
assert len(DELTA_CONTACTS) == 3, "delta corpus must be 3 records (2 new + 1 dup)"
assert len({r["source_id"] for r in DELTA_CONTACTS}) == 2, \
    "delta must contain exactly 2 distinct source_ids (c011, c012, + duplicate c003)"
assert len(CANONICAL_SCHEMA) == 5, "schema must be 5 descriptors (3 column + 2 overflow)"
# After a first full sync then a delta run, cip_contacts should hold 12 rows
# (10 baseline + 2 new; c003 was updated in place, not added — it already existed).
```

### 5.2 `test_protocol_compliance.py`

- `isinstance(MockConnector(...), CIPConnector)` → True (method existence).
- `isinstance(MockMapper(), CIPMapper)` → True.
- Construct a broken connector (missing `incremental_key`); assert `isinstance` → False.
- Verify each method signature: use `inspect.signature` to compare against the Protocol's `__annotations__`. If the Protocol has a param named `cursor`, the implementation must too.
- Regression guard: if someone adds a required method to `CIPConnector`, this test fails for `MockConnector`. Forces conscious update.

### 5.3 `test_incremental_sync.py`

- Seed `MockConnector` with 10 records, timestamps `T0 … T9`.
- Run `run_sync(...)` first time with `initial_cursor=None, sync_mode="incremental"`; expect all 10 ingested.
- Read back the `cip_sync_runs` row's `cursor_state`; expect `{"last_incremental_key": T9.isoformat()}`.
- Add 3 more records with `T10 … T12`; run `run_sync(...)` again passing the prior cursor; expect ONLY the new 3 ingested.
- Assert `rows_created = 3, rows_skipped_unchanged = 0, rows_skipped_duplicate = 0` (because `source_id` is unique per record in this scenario). v3 (R2-C9): counter names reflect the M-24 split.
- Variant: second run with one record having same `id` as a prior record but different `email`; expect `rows_updated = 1, rows_history = 1`.

### 5.4 `test_property_registry.py`

- `MockConnector` returns 5 `PropertyDescriptor` entries via `describe_schema()` — 3 column-stored, 2 overflow-stored.
- Run `run_sync(...)`.
- Query `cip_connector_property_registry WHERE connector='mock-connector-v1'`; expect exactly 5 rows with matching `storage_location` and `column_name`.
- Re-run the sync with a 6th property added; expect 6 rows after second run (upsert, no duplicates).
- Edge case: property with `is_custom=True` already exists in the registry; verify the connector's upsert doesn't clobber `is_custom`. (Test depends on SQL shape above.)

### 5.5 `test_scd_history.py`

- Seed 1 record with `email=a@x.com`. Run sync. Expect 1 row in `cip_contacts`, 0 in `cip_contacts_history`.
- Mutate same record: `email=b@x.com`. Run sync again. Expect 1 row in `cip_contacts` (email=b), 1 row in `cip_contacts_history` (email=a, archived_at set).
- Mutate only `refreshed_at`-related metadata (no domain change): expect 0 new history rows.
- Verify `previous_version_id` on current row points to the most recent history row.
- Verify ordering: `cip_contacts_history` can be walked backwards through `previous_version_id` to reconstruct the full change log.

### 5.6 `test_sync_run_audit.py`

- Success path: sync 5 records; assert `cip_sync_runs` row has `status='success'`, `rows_received=5, rows_created=5, rows_updated=0, rows_skipped_unchanged=0`, `started_at < ended_at`, `error_detail IS NULL`.
- Failure path: inject a persister exception; assert `status='failed'`, `error_detail` JSONB populated with `type=PersistenceError`.
- Partial path: 2 successful batches, 3rd batch fails; assert `status='partial'` (NOT `failed`), `error_detail` populated, `rows_received` + `rows_created` reflect only the successful batches.
- Assert `batch_id` is unique across runs (UUIDs).
- v3 (R2-C9): counter names reflect the M-24 split (no `rows_ingested` / `rows_skipped`).

### 5.7 `test_tenant_scoping.py`

- **Requires real Postgres** (RLS doesn't work in SQLite). Use `testcontainers-python` or a dedicated test DB role.
- Seed tenant A with 5 records, tenant B with 3 records — via two separate `run_sync` calls with different `tenant_id`.
- Query `cip_contacts` as tenant A (SET LOCAL app.current_tenant = A); expect 5 rows only.
- Query as tenant B; expect 3 rows only.
- Query as tenant C (no rows exist); expect 0 rows.
- Query as superuser without SET LOCAL: expect all 8 (bypass guard).
- Assert `apply_tenant_context` is called inside every batch transaction (spy or log-assertion).
- Assert the mapper/orchestrator NEVER read/write a row with a `tenant_id` different from the context — intentionally stage such a row via raw SQL + superuser, then verify `run_sync` as tenant A does not observe it.

### 5.8 `test_post_commit_rls_isolation.py` [v4 — Round-3 panel CRIT-1 mitigation]

**Purpose:** Catch the failure mode that 6 of 7 expert-panel models flagged as severity-5: forgetting to call `apply_tenant_context()` on any auxiliary connection path (recorder, knowledge hook, property-registry write, future M5/M6 paths). PgBouncer is moot for Foundry's actual deployment, but the underlying CORRECTNESS issue ("a connection returned to the pool with stale tenant context could serve the next caller's queries") is real for any pool-based deployment, including SQLAlchemy `QueuePool` if a future change accidentally allows GUC to outlive a transaction.

**Test invariant:** After every batch commit, the `app.current_tenant` GUC is empty on every checked-out pool connection. SET LOCAL is transaction-scoped — if it ever survives a commit, the test catches it.

**Scenario:**
1. Run a full incremental sync end-to-end against `MockConnector + MockMapper` for tenant A (10-record canonical fixture).
2. After the orchestrator returns, BEFORE any other transaction begins, check out a fresh connection from the engine's pool: `with engine.connect() as conn:`.
3. Execute `SELECT current_setting('app.current_tenant', true) AS tenant`. The `true` second argument tells Postgres to return empty string (not error) if the GUC was never set.
4. Assert the result is `''` (empty) or `None`. If it's the tenant-A UUID, GUC leaked across transactions — RLS failure mode.
5. Variant: do the same after the recorder's `__exit__` UPDATE has run. Same assertion.
6. Variant: induce a mid-batch exception (force `MockMapper.map` to raise), let `with db.begin():` roll back, then check the GUC. Should still be empty.
7. Variant: run a full sync for tenant A, then immediately run a full sync for tenant B (back-to-back on the same engine). Inside tenant B's sync, assert `apply_tenant_context` is called and that tenant B's RLS query sees ONLY tenant B's rows. (Catches the leak that GUC carry-over would cause.)

**Why this test is the actual CRIT-1 mitigation:**

- The panel framing was "PgBouncer transaction-pooling breaks SET LOCAL" — but `gpt-5.4 research` reconciled the alarm: "**`SET LOCAL` is the right primitive** for RLS tenant scoping **if and only if every batch is an explicit transaction and the GUC is set inside that transaction before any protected SQL**." The threat is forgetting the `apply_tenant_context()` call, not the SET LOCAL primitive itself.
- Foundry doesn't use PgBouncer (verified: `src/db/session.py` uses `pool_pre_ping=True` + default `QueuePool`, no PgBouncer in `.env.example` or any config). But the test's invariant ("GUC is gone after commit") is the right contract regardless of pool implementation.
- This test SHOULD PASS today (Postgres SET LOCAL is correctly transaction-scoped). It exists as a regression guard against future code changes that accidentally introduce session-scoped GUC use.

**Acceptance criteria:**
- All four scenarios pass against `MockConnector + MockMapper`.
- Test fails if a future change uses `SET app.current_tenant` (without LOCAL) anywhere in the framework.
- Test parametrizable via the `connector_under_test` fixture (so M3's FixtureConnector reuses it without changes).

**Test pointer:** `tests/fixtures/connector_conformance/test_post_commit_rls_isolation.py`.

**Harness-wide acceptance criteria:**
- All seven test modules pass against `MockConnector + MockMapper`.
- All seven test modules are PARAMETRIZABLE via a pytest fixture so M3's `FixtureConnector` plugs in with zero test rewrites (fixture name: `connector_under_test`).
- Each test file has `# foundry: kind=test domain=client-intelligence-platform` on line 1.
- `conftest.py` fixtures use session-scope for DB setup, function-scope for per-test tenant/cursor state.

---

## 6. Non-Harness Unit Tests

Beyond the 6 conformance tests, M2 ships targeted unit tests for internals:

- `tests/integration_mesh/test_scd_differ.py` — 8+ cases (§4.6 above).
- `tests/integration_mesh/test_rate_limit.py` — burst, steady-state, concurrent (§4.3 above).
- `tests/integration_mesh/test_sync_run_recorder.py` — 5 cases (§4.7 above).
- `tests/integration_mesh/test_orchestrator_unit.py` — orchestrator tests with mocked persister/recorder, specifically:
  - 3-consecutive-failure abort.
  - RateLimitExceeded retry behavior.
  - SchemaDriftError increments skipped, doesn't abort.
  - Knowledge-hook exception is logged but non-fatal.
  - `_validate_protocol_instance` rejects non-compliant mocks.

Coverage target: **≥90% line coverage on `cip/integration_mesh/`** for M2 exit.

---

## 7. Dependency Graph (build order)

```
base.py       ◄── no deps, write first
exceptions.py ◄── no deps
    │
    ├─► rate_limit.py     (uses base.RateLimitPolicy)
    ├─► scd_differ.py     (pure, no cip deps)
    ├─► tenant_context.py              (sqlalchemy only)
    │
    ├─► persister.py                   (uses base.CIPRow, scd_differ, exceptions, ALLOWED_CIP_TABLES)
    ├─► sync_run_recorder.py  (uses base.SyncRunState)
    │
    └─► orchestrator.py   (uses everything above)
         │
         └─► tests/fixtures/connector_conformance/*  (uses orchestrator + base)
```

**Build order (v3 — R2-C10: `__init__.py` promoted before the harness step so the conformance tests can `from cip.integration_mesh import ...`):**
1. Scaffold `foundry-cip/cip/` package with `__init__.py` files (empty re-exports stub is fine at this stage).
2. Write `base.py` + `exceptions.py`. Add type-check: `mypy cip/integration_mesh/base.py` clean.
3. Write `rate_limit.py` + `scd_differ.py` + `tenant_context.py` + `persister.py` + `validation.py`. Unit tests for each.
4. Write `sync_run_recorder.py`. Unit tests.
5. Write `orchestrator.py`. Unit tests with mocked deps.
6. **Update `cip/integration_mesh/__init__.py` with public-API re-exports** (v3: promoted ahead of harness tests — the harness imports from the package root, so re-exports must exist before the tests run).
7. Write `tests/fixtures/connector_conformance/conftest.py` (MockConnector/MockMapper) + `tests/fixtures/connector_conformance/fixtures/records.py` + the six test files. Run them; all green.
8. Populate `docs/cip/CONNECTOR-AUTHORING-GUIDE.md` §§1–5, 7–8, 10–12 (fill in from the SPEC + what was actually built).
9. Populate `docs/cip/SYNC-ORCHESTRATOR-GUIDE.md` §§1–6, 8–10.
10. Run full test suite (`pytest -v`); coverage ≥90%.
11. Commit + push; M2 gate.

---

## 8. Edge Cases & Failure Modes (Complete Catalog)

### 8.1 Authentication
- Invalid credentials → `AuthenticationError` on first call → orchestrator records `status='failed'`, re-raises to caller.
- Token expires mid-sync → connector MUST raise `AuthenticationError` again on next `stream_records`; orchestrator treats as fatal (for M2 — Phase 2 may add auto-refresh).

### 8.2 Rate limits
- Source-system 429 → connector raises `RateLimitExceeded(retry_after_seconds=N)` → orchestrator sleeps N + retries the same batch.
- Indefinite rate limit (API down) → after 3 consecutive batch failures, abort with `partial`.
- Our own token-bucket exhausted → bucket blocks; no exception.

### 8.3 Partial sync
- Batch 1–4 succeed, batch 5 fails → cursor advanced through batch 4; sync run is `partial`; next run picks up from batch 4's `last_incremental_key`.
- Failure in `mapper.map()` (SchemaDriftError) → skip record, continue batch.
- Failure in `persister.persist()` (PersistenceError) → rollback batch, increment consecutive_batch_failures; abort after 3.

### 8.4 Schema drift
- Connector returns a record with fields the mapper's domain-column list doesn't cover → mapper emits overflow, NO SchemaDriftError (expected behavior).
- Connector returns a record missing a mapper-required field → mapper raises `SchemaDriftError`; orchestrator skips, logs.
- New property introduced in source → connector's `describe_schema()` emits the descriptor; registry upserts; existing tenant rows get nulls until next sync cycle.

### 8.5 Cursor resumption
- `initial_cursor=None` + `sync_mode="incremental"` on first run → full pull (behaves as full sync).
- `sync_mode="full"` → cursor is passed as None regardless of `initial_cursor`, full pull.
- Cursor points to a time in the future (clock skew) → no records returned; sync completes with `rows_received=0, rows_created=0`. Log warning.
- Cursor stored as ISO string; orchestrator parses via `datetime.fromisoformat`. Connector responsible for timezone-aware timestamps.

### 8.6 Tenant scoping
- `apply_tenant_context` forgotten → RLS blocks all reads/writes; persister raises `PersistenceError`; batch fails.
- Wrong tenant_id in context vs CIPRow → RLS blocks the insert; `PersistenceError`.
- Superuser bypass → tests intentionally use non-superuser test role. `tests/conftest.py` documents this.

### 8.7 Concurrent runs
- Two orchestrator calls against the same connector+tenant → separate `batch_id`s (UUIDv4); no collision in `cip_sync_runs`.
- FOR UPDATE lock in persister prevents lost-update races at the row level.
- `cip_sync_runs` `batch_id` has UNIQUE constraint — verified by migration.

### 8.8 Knowledge-ingest hook
- Hook raises any exception → log + continue (D-067 non-fatal).
- Hook returns `[]` → count 0, no warning.
- Hook called per-record, not per-row (one source record can map to multiple rows).

### 8.9 Property registry race
- Two connectors (same tenant) register overlapping properties → `INSERT ON CONFLICT DO UPDATE` handles cleanly.
- Custom-property flag preservation: if existing row `is_custom=True`, UPDATE must NOT set it to False. Use `is_custom = EXCLUDED.is_custom OR cip_connector_property_registry.is_custom` (once-true-stays-true) OR use WHERE clause to skip the update.

### 8.10 Empty streams
- `stream_records` returns no records on first call → loop exits immediately; status `success`; counters all 0; `cursor_state` unchanged.
- Source API returns pagination token pointing to empty page → connector implementation detail; `stream_records` returns empty iterator.

### 8.11 Very large records
- Record >10MB → no special M2 handling; persister just INSERTs. Postgres TOAST handles. Log if `len(json.dumps(rec)) > 1e6`.
- Batch size × record size > memory → batch_size is caller-configurable; default 500 × ~1KB typical = ~500KB, fine.

### 8.12 Clock skew
- Connector's `incremental_key` uses source clock; our `refreshed_at` uses DB clock. A small gap is fine. Document in `CONNECTOR-AUTHORING-GUIDE.md`.
- v2: `cursor_safety_window_seconds=300` (TSP) applied at §4.8 `_apply_safety_window()` absorbs skew up to 5 minutes without manual intervention. Connector authors don't need to correct for skew themselves.
- v2: tz-naive `incremental_key` raises `TimezoneNaiveError` — silently truncating tzinfo would create a skew landmine.

### 8.13 Out of Scope for M2 [v2 — explicit deferral list closes Gap Analyst finding #7 + Senior Reviewer's scope-drift point]

The following are intentionally NOT part of M2 and MUST NOT be built during M2. Each has a downstream milestone (or explicit Phase-2+ deferral) where it lands.

| Item | Deferred to | Rationale |
|---|---|---|
| Async connectors (`async def stream_records`) | Phase 2 (post-benchmark) | SPEC §2 locks sync-only for Phase 1. Adding `asyncio` here would force every connector author to choose sync-vs-async. |
| Distributed rate limiting (Redis token bucket) | M6 (scale harden) | M2 is single-process; `multiprocessing.Lock` is sufficient. Cross-process coordination is a net-new concern. |
| Retry beyond 3 consecutive batch failures | Never | Caller restarts the sync; M2's orchestrator does NOT own exponential-backoff retry across runs. |
| Dead-letter queue for unrecoverable records | Phase 2 | DLQ is an ops concern; M2 records `status='partial'` and relies on operator re-run. |
| Real `ingest_as_knowledge` (Pinecone + FalkorDB write) | M5 Knowledge wiring | M2 ships the signature + no-op; M5 wires the real ingest. |
| Credential resolution (vault, Secrets Manager) | M6 | M2 accepts creds via env vars; secrets store integration lands once multiple connectors exist. |
| Config UI / admin panel | Phase 2 or Phase 2.5 | Out of scope — M2 is library-first, operator invocation is CLI/pytest. |
| Observability dashboards (Grafana, OTel tracing) | Phase 2 | `logging` module + `cip_sync_runs` SELECT is M2's observability surface. |
| Retention / archival of `cip_*_history` tables | Phase 3 | Data lifecycle is a separate decision; M2 keeps everything forever. |
| VACUUM / autovacuum tuning | Phase 3 ops hardening | Postgres defaults suffice for fixture-scale M2 tests. |
| `cip_cross_tenant_grants` enforcement in orchestrator | Phase 3 | M2 uses single-tenant RLS; cross-tenant views are queried by downstream services, not written by the orchestrator. |
| Webhook-driven incremental sync (push, not pull) | Phase 2.5 | M2 is poll-based; webhook receiver is a different subsystem (integration-mesh/webhooks). |
| Connector manifest / metadata catalog | M6 | Per-connector `manifest.yaml` lands with M6 when we need agent discoverability. |
| Circuit breaker (global "stop all syncs for this tenant") | Phase 2 | One sync-run's failure doesn't pollute another's; no M2 need. |
| Per-batch heartbeat UPDATE on `cip_sync_runs` (live-watch observability) | Phase 8 | v3 (R2-H8) — Senior Reviewer #7 proposed mid-sync heartbeat writes. Worth adding, but a Phase 8 observability concern; M2's single-commit-at-exit via recorder's `__exit__` is sufficient. |
| Advisory-lock dual-run prevention (`pg_advisory_xact_lock(hash_int8(tenant_id, connector_name))` at `run_sync` start) | M3 (FixtureConnector lands) | v4 (Round-3 panel CRIT-2 deferral). Two run_sync processes on the same `(tenant, connector)` can theoretically deadlock or lost-update under READ COMMITTED. Real risk emerges at multi-tenant scale (Phase 2+); not a real failure mode at single-tenant M2 acceptance. v4 ships cheap deterministic `ORDER BY source_id` before `FOR UPDATE` (§4.5) which prevents the deadlock class entirely. Advisory lock is the principled fix at scale; defer to M3 alongside FixtureConnector + concurrent-sync conformance test. gpt-5.4 expert: "more valuable than perfecting per-row lock strategy". |
| Concurrent-sync race conformance test (multiprocessing-based) | M3 | v4 (Round-3 panel CRIT-2 deferral). Pairs with advisory-lock work above. Not testable today against MockConnector alone (single-process pytest) — needs FixtureConnector + cross-process orchestration. |
| Scale-tier connection pool sizing (`pool_size=20, max_overflow=40, pool_pre_ping=True, pool_recycle=3600` defaults in `create_engine`) | Phase 2 (Wayward onboarding) | v4 (Round-3 panel CRIT-3 deferral). Foundry baseline platform pool is `pool_pre_ping=True, pool_recycle=1800` (from `src/db/session.py`); CIP framework inherits the caller's engine config, doesn't impose its own. M2 single-tenant Wayward + Rocky Ridge load fits the existing baseline. Multi-tenant scale-up is a deployment-config concern, not a framework concern. Document recommended tuning in CONNECTOR-AUTHORING-GUIDE.md §10 when first multi-tenant deployment lands. |
| Set-based bulk-DML refactor (stage→merge instead of per-record persist loop) | M6 or Phase 2 | v4 (Round-3 panel HIGH deferral). gpt-5.4 research: "Bad app-layer pattern: one round-trip per record. Good app-layer pattern: stage batch → do set-based SQL." Real cost at >10K-records/sync; M2's MockConnector is 10 records, M3 FixtureConnector is small. Per-record persist with `FOR UPDATE` lock is correct and testable; bulk refactor lands when first real high-volume connector hits the perf ceiling. |
| Beartype / typeguard runtime-typecheck dependency | Never (or post-M5 if needed) | v4 (Round-3 panel HIGH deferral). 3-of-7 expert models recommended deferral; only gemini-3-pro pushed adoption. M2 ships ~3 connectors over 12 months. Cost of 50KB+ dep + import-time overhead > value at this scale. `validate_connector_shape()` + conformance harness covers the failure space. Revisit if M5+ surfaces a real annotation-mismatch bug. |
| App-layer SCD audit / DB-trigger guard against out-of-band UPDATEs | Phase 8 (governance) | v4 (Round-3 panel MEDIUM deferral). qwen3.5-35b-thinking flagged: app-layer SCD can't catch out-of-band ad-hoc UPDATEs that bypass the orchestrator. M2's single writer is `CIPRowPersister` (no other code touches `cip_*` tables). Real risk is operator-side `UPDATE cip_contacts SET ...` from a psql shell. Mitigation: GRANT-based RLS that denies UPDATE except via service role (governance, not framework), or DB trigger that mirrors current→history on UPDATE (deferred audit pattern). |

If something is NOT in this table and NOT in the §4 file list, it is also out of scope by default. Add it to this table if you discover it during implementation rather than silently building it.

---

## 9. Acceptance Criteria — M2 Gate [v2: each criterion has an explicit verification method]

M2 is done when ALL of these pass. Each item lists the exact command/grep/pytest-selector the builder or reviewer runs to verify.

| # | Criterion | Verification method |
|---|---|---|
| 1 | `cip/integration_mesh/base.py` matches SPEC §4 Protocol shapes byte-for-byte. | `python scripts/check_protocol_drift.py` (compares AST of `base.py` to SPEC §4 code block) — exit code 0 required. |
| 2 | All files listed in §3 exist with correct CSS classification headers. | `for f in $(git ls-files 'cip/integration_mesh/*.py' 'tests/fixtures/connector_conformance/*.py'); do grep -q '^# foundry: kind=' "$f" || { echo "MISSING CSS: $f"; exit 1; }; done` |
| 3 | `pytest tests/` — 100% green. | `pytest tests/ -v --tb=short` (exit code 0). |
| 4 | `pytest tests/fixtures/connector_conformance/` — all 6 tests pass against `MockConnector`. | `pytest tests/fixtures/connector_conformance/ -v` (6 PASSED, 0 FAILED, 0 SKIPPED). |
| 5 | Coverage ≥90% on `cip/integration_mesh/`. | `pytest --cov=cip.integration_mesh --cov-report=term-missing --cov-fail-under=90`. |
| 6 | `mypy cip/` — 0 errors. | `mypy --strict cip/integration_mesh/` (exit code 0, or explicit `# type: ignore[code]` with rationale). |
| 7 | `docs/CONNECTOR-AUTHORING-GUIDE.md` §§1–5, 7–8, 10–12 populated; status `draft`. | `python scripts/check_doc_sections.py docs/cip/CONNECTOR-AUTHORING-GUIDE.md --required-sections 1,2,3,4,5,7,8,10,11,12 --min-status draft` (script checks frontmatter `status:` + section non-empty). |
| 8 | `docs/SYNC-ORCHESTRATOR-GUIDE.md` §§1–6, 8–10 populated; status `draft`. | `python scripts/check_doc_sections.py docs/cip/SYNC-ORCHESTRATOR-GUIDE.md --required-sections 1,2,3,4,5,6,8,9,10 --min-status draft`. |
| 9 | `scripts/check_registry_sync.py` (CSS drift check) passes. | `python scripts/check_registry_sync.py` (exit code 0). |
| 10 | No import of `src.llm_roster.*` inside M2 code. | `! grep -R "src\.llm_roster" cip/integration_mesh/ 2>/dev/null` — must return no matches (knowledge-hook stays stub until M5). |
| 11 | `foundry-llm-roster` declared in `pyproject.toml` dependencies. | `grep -q 'foundry-llm-roster' pyproject.toml`. |
| 12 | PM scope `[M2] Generic Connector Framework` marked `mark_scope_done` with exit-criteria receipt. | `foundry_mcp_pm_project_status project_code=CIP-PHASE1` — scope appears under `completed`. |
| 13 | Decision comment on CIP project logging M2 exit + next (M3 readiness). | `foundry_mcp_pm_project_status project_code=CIP-PHASE1` — most-recent comment has `comment_type=decision` and mentions M2 exit. |
| 14 | Write-log receipt batch appended. | `tail -50 internal-tooling/atlas-state/write-log.md` — most-recent receipts cover M2 merge. |
| 15 | `stream_records` is invoked EXACTLY ONCE per run (H-10 regression guard). | `pytest tests/fixtures/connector_conformance/test_incremental_sync.py::test_stream_records_called_once -v`. |
| 16 | `validate_connector_shape` rejects broken connectors (C-5 guard). | `pytest tests/integration_mesh/test_validation.py -v` (all 4 cases PASSED). |
| 17 | tz-naive `incremental_key` raises `TimezoneNaiveError` (H-12 guard). | `pytest tests/fixtures/connector_conformance/test_incremental_sync.py::test_tz_naive_rejected -v`. |
| 18 | `cursor_state` updated in same transaction as batch writes (C-4 guard). | `pytest tests/fixtures/connector_conformance/test_incremental_sync.py::test_cursor_atomic_with_batch -v`. |
| 19 | Rate-limit retry budget enforced (H-6 guard). | `pytest tests/fixtures/connector_conformance/test_incremental_sync.py::test_rate_limit_budget -v`. |
| 20 | Recorder runs in its own connection (§4.7 regression guard). | `pytest tests/integration_mesh/test_sync_run_recorder.py::test_recorder_uses_own_connection -v` — asserts no transaction leaks into caller's Session. |
| 21 | `ALLOWED_CIP_TABLES` allowlist blocks writes to unknown tables (persister guard). | `pytest tests/integration_mesh/test_persister.py::test_unknown_table_rejected -v`. |
| 22 | `_register_properties_best_effort` preserves `is_custom=true` across upserts (M-16 guard). | `pytest tests/fixtures/connector_conformance/test_property_registry.py::test_is_custom_preserved -v`. |

---

## 10. Doc Fill-in Specs

### 10.1 `docs/CONNECTOR-AUTHORING-GUIDE.md` — M2 fills §§1–5, 7–8, 10–12

**§1 Protocol contract:** Copy the `CIPConnector` + `CIPMapper` Protocol definitions from `base.py`. Normative voice ("Your connector MUST implement `authenticate()`…"). Include the optional `CIPConnectorBase` mention.

**§2 File layout:** Template folder structure for `platform/integration-mesh/src/connectors/cip/<connector>/` (or, in the foundry-cip world, `cip/integration_mesh/connectors/<connector>/`) — `__init__.py`, `connector.py`, `mapper.py`, `fixtures/` (for integration tests).

**§3 authenticate():** Env-var conventions (`{CONNECTOR}_API_KEY`), credential-resolution order (env > secret-store stub > explicit), `AuthenticationError` when to raise.

**§4 stream_records(cursor, batch_size):** Cursor shape (dict with `"last_incremental_key"` key), batch-size policy (respect caller's value, cap at connector's max-page-size), pagination pattern (generator, yield one record at a time, let orchestrator count).

**§5 incremental_key(record):** Return a timezone-aware `datetime`. Orchestrator stores `isoformat()`. On ambiguous records (no updated_at field), raise; orchestrator treats as sync-wide failure.

**§7 CIPMapper.map(record):** Emit ≥1 `CIPRow` per record. One record → multiple rows is allowed (e.g., a Zendesk ticket with N comments = 1 ticket row + N comment rows, if we choose that shape).

**§8 Authority selection:** `"ingested"` for connector-sourced data (default). `"agent_discovered"` for Phase 3 ventures where an LLM agent infers a field. `"validated"` when a human or trusted agent confirms. Phase 1 uses only `"ingested"`.

**§10 Rate-limit policy:** Expose via `@property rate_limit_policy`. Default `RateLimitPolicy.DEFAULT` (10 rps, burst 5). Override per source-system docs. Orchestrator honors via TokenBucket.

**§11 Passing the conformance harness:** Point to `tests/fixtures/connector_conformance/`. Must pass all 6 before merge.

**§12 Reference implementation:** Point forward to M3's FixtureConnector for a copy-and-adapt example.

Sections §6 `describe_schema()` → registry and §9 `ingest_as_knowledge()` are partially populated (mechanism described) but marked `TBD (M6)` / `TBD (M5)` for full semantics.

### 10.2 `docs/SYNC-ORCHESTRATOR-GUIDE.md` — M2 fills §§1–6, 8–10

**§1 Responsibilities:** Orchestrator owns: iteration, batching, transaction boundaries, sync-run records, rate limiting, cursor advancement. Connector owns: source API interaction, record shape, auth, rate-policy emission.

**§2 Orchestrator ↔ connector boundary:** Exact 5 Protocol methods the orchestrator depends on (SPEC §4). Nothing else. Any additional behavior is connector-private.

**§3 Control flow:** The numbered flow from §4.8 above. Diagrammable as: `enter recorder → authenticate → register properties (best-effort) → loop(stream→map→persist→hook→advance cursor) → exit recorder`.

**§4 cip_sync_runs lifecycle:** `status`: `running → {success, partial, failed}`. Fields: `id, tenant_id, client_id, connector_id, connector_name, batch_id, sync_mode, rows_*, started_at, ended_at, cursor_state, error_detail, metadata`. Row is committed at start (observable during long syncs).

**§5 Batching + pagination:** Default `batch_size=500`. Cursor advances per-batch after successful commit. Full vs incremental mode: full passes `cursor=None` always; incremental passes `{"last_incremental_key": ...}`.

**§6 Transaction boundaries:** One txn per batch. `BEGIN → apply_tenant_context → INSERT/UPDATE batch rows → COMMIT`. On error: ROLLBACK; orchestrator increments consecutive-failure count. Abort after 3.

**§8 Failure modes + partial sync:** Catalog from §8 above (auth, rate-limit, schema drift, persistence).

**§9 Observability:** Structured logs (module-level `log`). Per-batch DEBUG. Per-failure WARNING or ERROR. `cip_sync_runs` row is the primary operational artifact.

**§10 Idempotency:** Re-running a sync does NOT produce duplicate rows (source_id uniqueness + UPDATE path). History rows are intentionally non-idempotent (each actual change → one new history row). `batch_id` is unique per run via UUIDv4; orchestrator does NOT dedupe against prior `batch_id`s.

Section §7 Knowledge-ingest hook is `TBD (M5)` beyond stub mention.

---

## 11. LLM Roster Subpath Dependency

M2's `pyproject.toml` (in foundry-cip) declares:

```toml
[project]
dependencies = [
    # ... other deps ...
    "foundry-llm-roster @ git+https://github.com/Foundry-Studio/foundry-agent-system.git@<pinned-sha>#subdirectory=src/llm_roster",
]
```

Rationale: M2 itself doesn't call LLMs. The Knowledge hook in M5 will. Declaring the dep in M2 pyproject.toml means the scaffold import-path `from cip.integration_mesh.knowledge_hook import ingest_texts` works today, and M5's swap-in doesn't change `pyproject.toml`.

Pin to a specific SHA (not `master`) to prevent upstream changes from breaking foundry-cip CI. Bump deliberately.

Task #57 (LLM Roster pip subpath enablement) must land first. The `src/llm_roster/` folder in the monorepo needs a sibling `pyproject.toml` so `pip install "... #subdirectory=src/llm_roster"` works.

---

## 12. CSS Classification Table (every new file) [v2: paths updated to match §3 post-consolidation layout]

| File | kind | domain | touches |
|------|------|--------|---------|
| `cip/integration_mesh/base.py` | service | client-intelligence-platform | integration |
| `cip/integration_mesh/exceptions.py` | service | client-intelligence-platform | integration |
| `cip/integration_mesh/rate_limit.py` | service | client-intelligence-platform | integration |
| `cip/integration_mesh/tenant_context.py` | service | client-intelligence-platform | integration,security |
| `cip/integration_mesh/scd_differ.py` | service | client-intelligence-platform | integration |
| `cip/integration_mesh/persister.py` | service | client-intelligence-platform | integration,storage |
| `cip/integration_mesh/sync_run_recorder.py` | service | client-intelligence-platform | integration |
| `cip/integration_mesh/orchestrator.py` | service | client-intelligence-platform | integration |
| `cip/integration_mesh/validation.py` | service | client-intelligence-platform | integration |
| `cip/integration_mesh/knowledge_hook.py` | service | client-intelligence-platform | knowledge |
| `cip/integration_mesh/__init__.py` | service | client-intelligence-platform | integration |
| `tests/conftest.py` | test | client-intelligence-platform | — |
| `tests/fixtures/connector_conformance/conftest.py` | test | client-intelligence-platform | — |
| `tests/fixtures/connector_conformance/fixtures/records.py` | fixture | client-intelligence-platform | — |
| `tests/fixtures/connector_conformance/test_*.py` (6 files) | test | client-intelligence-platform | — |
| `tests/integration_mesh/test_*.py` (5 files: scd_differ, rate_limit, persister, sync_run_recorder, validation) | test | client-intelligence-platform | — |
| `docs/cip/CONNECTOR-AUTHORING-GUIDE.md` | doc | client-intelligence-platform | — |
| `docs/cip/SYNC-ORCHESTRATOR-GUIDE.md` | doc | client-intelligence-platform | — |

v2 changes from v1:
- Removed the phantom `cip/persistence/__init__.py` + `cip/knowledge_hook/__init__.py` rows — v1 plan invented a `cip/persistence/` package that isn't in SPEC §3; persister.py + knowledge_hook.py are siblings of orchestrator.py under `cip/integration_mesh/`.
- Added `cip/integration_mesh/validation.py` (new in §4.11).
- Added `tests/fixtures/connector_conformance/fixtures/records.py` (new in §5.1.1, `kind=fixture`).
- Bumped `tests/integration_mesh/test_*.py` count from 4 → 5 (added `test_validation.py`).
- Fixed doc paths from `docs/` to `docs/cip/` (the M0 skeletons already live there).

Python: `# foundry: kind=X domain=Y touches=Z` as line 1.
Markdown: YAML frontmatter with `kind:`, `domain:`, `status:`, `last_updated:`, `milestone:`.

---

## 13. Open Questions / Decisions to Resolve Before M2 Execute [v2: six prior Qs resolved, three new Qs surfaced for LLM panel]

**Resolved in v2 (closed during QC Round 1 / Atlas CTO review):**

1. ✅ **Final path under `foundry-cip/`.** Locked: `cip/integration_mesh/` (flat — persister + knowledge_hook + validation all siblings of orchestrator). No separate `cip/persistence/` package. Task #60 (SPEC §3 rewrite) echoes this.

2. ✅ **Testcontainers vs local Postgres for RLS tests.** Locked: testcontainers-python with session-scoped Postgres container. Non-superuser role created inside the container's setup fixture. No "alternative CI path" — one path only.

3. ✅ **D-numbers to lock for M2.** Locked pre-execute (v3: re-pointed after discovering v2's proposed numbers had been taken by unrelated PM/task-dispatcher work that landed between v2 and v3 authoring; v5 amendment to D-133 lands 2026-04-29):
   - **D-133 (amended 2026-04-29):** `CIPMapper.ingest_as_knowledge(record) -> list[KnowledgeText]` where `KnowledgeText` is a frozen dataclass `KnowledgeText(text: str, metadata: KnowledgeTextMetadata)`. The outer dataclass shape and return type are unchanged from the original lock. The INNER `metadata` shape sharpens from open `dict[str, object]` to `KnowledgeTextMetadata` TypedDict (required core keys: `source_id`, `source_system`, `extracted_at`, `tenant_id`, `connector_version`; `NotRequired` extensions: `authority`, `record_updated_at`, `ingestion_batch_id`). Locking the richer return type NOW (M2) so M5 does not churn the Protocol signature. (Was D-132 in v2; original D-133 in v3 used open dict; amended 2026-04-29 per v5 PATCH-Q6.) See DECISION-LOG.md D-133 Amendment block for full rationale + rejected alternatives (Pydantic, reserved-namespace dict).
   - **D-134:** CIP connector framework is Protocol-based (`@runtime_checkable`), with optional `CIPConnectorBase` / `CIPMapperBase` ABC helpers for authors who want inheritance. Validation performed at `run_sync()` entry via `validate_connector_shape()` in `validation.py`. (Was D-130 in v2.)
   - **D-135:** SCD Type-2 diffing applied at the application layer (`SCDDiffer.should_write_history()`), not via Postgres trigger. Rationale: app-layer is testable, trigger would require per-table DDL that's harder to unit-test against the canonical fixture corpus. (Was D-131 in v2.)
   - `batch_size=500` stays a TSP per DEFAULTS, not a D-number.

4. ✅ **`run_sync` sync or async?** Locked: **sync**. SQLAlchemy Session, blocking I/O. Matches Foundry's DB-bound-service pattern. If async is ever needed, wrap `run_sync` in `run_in_executor` — no M2-time refactor.

5. ✅ **Knowledge-ingest hook signature.** Resolved via D-133 above: `list[KnowledgeText]`, not `list[str]`.

6. ✅ **Rate-limit integration test.** Locked: unit tests of `TokenBucket` + orchestrator's retry-budget logic are sufficient for M2. Real rate-limit clock behavior verified in M4 when the first real connector (HubSpot) hits a real 429. No flaky wall-clock tests in M2 CI.

**Resolved by Round-3 LLM panel (Stage 7 of Turn-6 directive — 7 expert + 5 research models):**

7. ✅ **Cursor safety window — 300s default + per-connector override.** Panel research: HubSpot has no published replica-lag SLA. Airbyte's zendesk source uses 180s lookback (`gemini-3-pro` cited GitHub `airbyte/airbyte-integrations/connectors/source-zendesk-support/source_zendesk_support/streams.py` constants.py L9). Zendesk's own incremental-export docs recommend cursor-driven semantics over fixed lookback (`gemini-3-pro` + `gpt-5.4 research` both confirm). Panel consensus: 300s is "defensible heuristic, not empirically grounded." v4 keeps 300s as `DEFAULT_CURSOR_SAFETY_WINDOW_SECONDS` AND adds optional `cursor_safety_window_seconds` Protocol property (§4.1) for per-connector override (Zendesk connector should override to ~180s; HubSpot can stay at 300s).

8. ✅ **Per-batch transaction at scale — defer multi-tier batching to first real bottleneck.** Panel: at 100 tenants × 20 batches each = 2K tx/min ballpark, the per-batch transaction model becomes pool-pressure-sensitive. v4 explicitly defers to Phase 2 / M3 (§8.13: scale-tier pool sizing + set-based bulk DML rows added). M2 ships single-tenant Wayward + Rocky Ridge first; Foundry baseline pool config (`pool_pre_ping=True, pool_recycle=1800` in `src/db/session.py`) is sufficient. Document tuning recommendations in CONNECTOR-AUTHORING-GUIDE.md §10 when first multi-tenant deployment lands.

9. ✅ **FOR UPDATE row-lock — cheap deterministic ORDER BY now, advisory-lock dual-run prevention deferred.** Panel: real deadlock risk at concurrent-sync scale, not real at single-tenant M2 acceptance. v4 adds `ORDER BY source_id` before `SELECT … FOR UPDATE` in §4.5 (cheap; prevents deadlock class entirely even before advisory lock lands). Advisory-lock pattern (`pg_advisory_xact_lock(hash_int8(tenant_id, connector_name))` at `run_sync` start) deferred to M3 alongside FixtureConnector + concurrent-sync conformance test (§8.13). gpt-5.4 expert: advisory lock "more valuable than perfecting per-row lock strategy" — at concurrent-sync scale, blocking the second `run_sync` entirely is cleaner than sharpening row-lock semantics.

**Surfaced + handled in v4 from Round-3 panel (not in original §13):**

10. ✅ **`SET LOCAL app.current_tenant` correctness under any pool implementation.** Panel CRIT-1 (6 of 7 expert models, sev 5). Foundry-specific reality check: `src/db/session.py` uses plain SQLAlchemy QueuePool, no PgBouncer, so the panel's specific PgBouncer-transaction-pooling angle is moot. But the underlying CORRECTNESS issue (forgetting `apply_tenant_context()` on auxiliary connection paths → RLS bypass) is real. v4 adds new Conformance Test 7 (§5.8 `test_post_commit_rls_isolation.py`) that asserts `current_setting('app.current_tenant', true)` is empty after every batch commit — catches the actual failure mode. Plus tenant_context.py docstring HOWTO showing the `event.listens_for(Engine, "begin")` belt-and-suspenders pattern for ventures wanting auto-applied tenant context (M2 framework itself does NOT use this pattern — explicit `apply_tenant_context()` calls stay the rule).

11. ✅ **`autoflush=True` mid-batch implicit-flush deadlock surface.** Panel HIGH (3 models). v4 makes per-batch Session creation explicit: `Session(engine, autoflush=False, expire_on_commit=False)` in both orchestrator main loop and `_register_properties_best_effort` (§4.8). Cheap and removes a surprise.

12. ✅ **Decorated `stream_records` false-negative on `inspect.isgeneratorfunction`.** Panel HIGH (1 model — gpt-5.4 expert). v4 adds docstring note in §4.11 documenting the `__wrapped__` chain pattern + `functools.wraps` requirement for connector authors using decorators. M2 ships strict check + documented workaround; v5 may add `inspect.unwrap()` traversal if a real connector hits this. Beartype/typeguard runtime-typecheck dep deferred (3-of-7 panel models say defer; only gemini-3-pro advocates).

**v3 architectural commitments confirmed by Round-3 panel:**

- **R2-A1 (Engine signature)** confirmed by 5/7 expert + 3/3 useful research models. No model directly contradicted.
- **R2-A2 (`_finalize` after `with recorder:`)** — no model addressed it; implicitly accepted.
- **D-135 (app-layer SCD)** confirmed by 4 expert + 3 research as industry-mainstream (Dagster, dbt, Fivetran all do app-layer in 2025-26).
- **Two qwen models pushed savepoint pattern in single long-lived Session** — rejected by 5 stronger models on lock-duration grounds (kimi-k2.5: "Do NOT use begin_nested(): This holds the parent connection open for the entire sync duration"; gemini-3-pro: "Savepoints would also hold locks for the duration of the entire sync"). v3's per-batch Session pattern stands.

**Resolved by Round-4 LLM panel (2026-04-29 — 7 expert models on the v4 plan):**

13. ✅ **`SyncRunRecorder.__exit__` row-clobber risk on `cursor_state` (PATCH-Q4, SEV-5).** 5 of 7 panel models converged on this exact one-question bet — strongest single signal in the round. v4 recorder's `__exit__` UPDATEs the full audit row including any value of `cursor_state` from the recorder's instance (which is None or stale). Orchestrator main loop writes `cursor_state` per-batch in §4.8. If `__exit__` runs after the last batch's cursor write, it clobbers. v5 fix: column-minimal UPDATE in `__exit__` excluding `cursor_state` explicitly, with a no-regress comment. See §4.7.

14. ✅ **`SET LOCAL app.current_tenant` doesn't reset across pool checkouts (PATCH-NR-1, SEV-5).** Foundry doesn't use PgBouncer (Round-3 closed that angle), but the underlying defense-in-depth is independent of pool implementation. v5 adds a `event.listens_for(Engine, "checkout")` listener that issues `SELECT set_config('app.current_tenant', '', false)` on every checkout. Belt-and-suspenders to the explicit `apply_tenant_context()` calls. Listener registered in `cip/db/engine.py` make_engine() factory. See new §1.2.

15. ✅ **`inspect.unwrap()` on `validate_connector_shape()` generator check (PATCH-Q3, SEV-5).** v4 documented the decorator-chain edge case but kept the simple direct check. v5: replace `inspect.isgeneratorfunction(connector.stream_records)` with `inspect.isgeneratorfunction(inspect.unwrap(connector.stream_records))`. Connectors using `@functools.wraps`-correct decorators now pass; broken decorators still fail with a clear error. See §4.11.

16. ✅ **`KnowledgeText.metadata` semver risk on open dict (PATCH-Q6, SEV-3 — opens D-133 amendment).** 6 of 7 models second-guessed the original D-133 shape `metadata: dict[str, object]`. Tim opened the door to amendment 2026-04-29: "for q6, what RIGHT? we an amend d-133. old decisions may be base don bad info." Amendment lands: `KnowledgeText.metadata` becomes `KnowledgeTextMetadata` TypedDict. Outer frozen-dataclass shape unchanged. Required core keys (5) + `NotRequired` extensions. Connectors extend via TypedDict subclassing. mypy-strict catches typos at CI time. Migration cost: zero — M2 has not executed yet. See §4.1 + DECISION-LOG.md D-133 Amendment block.

17. ✅ **Generator cleanup on orchestrator-side exception (PATCH-NR-2, SEV-4).** v4 iterates `connector.stream_records()` without explicit close on exception path. v5: `_chunked()` MUST be implemented with `yield from` (propagates `.close()` from outer to inner generator); orchestrator's executor wraps the `for raw_batch` loop in `try/finally` with `record_iter.close()`. Documented in §4.8 patch comment.

18. ✅ **tz-aware datetime guards on metadata + CIPRow.fields (PATCH-NR-7, SEV-3).** v4 has tz-naive rejection on `incremental_key()` only. v5 adds `_assert_tz_aware(value, field_name)` helper in base.py; called by orchestrator before metadata is finalized into KnowledgeText (§4.1) and by persister before INSERT on any datetime field of `CIPRow.fields` (§4.5). Same `TimezoneNaiveError` exception class. See §4.1 patch.

**Out of scope for v5 (v4 stands):** Round-3 panel decisions all stand. v5 is targeted; no architecture reshape.

---

## 14. Handoff Notes for Claude Code

- Execute in this repo: `foundry-cip` (clone URL TBD post-extraction).
- Start from `pyproject.toml` + `alembic.ini` already present (from extraction).
- Install deps: `pip install -e ".[dev]"` — must include `foundry-llm-roster` from subpath, `sqlalchemy`, `alembic`, `testcontainers-python`, `pytest`, `pytest-cov`, `mypy`.
- Run migrations locally: `alembic upgrade head` (confirms `cip_*` tables exist before M2 code touches them).
- Build order = §7 build order.
- Self-verify against §9 acceptance criteria before reporting done.
- On ambiguity, stop and ask. Do NOT invent behavior not in this plan or the SPEC.
- Put all work on `master`. No branches, no PRs. One commit per logical unit (e.g., `M2: base Protocols`, `M2: orchestrator`, `M2: conformance harness`, `M2: doc fill-in`).

---

## 15. Web Research Citations

Consulted for current best practices; no direct copy-paste.

- Python `typing.Protocol` + PEP 544 — docs.python.org/3/library/typing.html#typing.Protocol
- Protocols vs ABCs — Real Python "Python Protocols: Leveraging Structural Subtyping"
- Airbyte CDK (source connectors) — docs.airbyte.com/connector-development/cdk-python (state/cursor pattern, batched stream reads)
- Singer spec — github.com/singer-io/getting-started (STATE message shape, incremental replication keys)
- Fivetran docs — fivetran.com/docs (SCD approach, `_fivetran_synced` / `_fivetran_deleted` metadata)
- Kimball SCD Type 2 — Ralph Kimball "The Data Warehouse Toolkit" (classic pattern; we apply at app layer)
- Postgres `SET LOCAL` + RLS — postgresql.org/docs/current/sql-set.html + postgresql.org/docs/current/ddl-rowsecurity.html
- Token-bucket rate limiting — Wikipedia "Token bucket" + aiolimiter library reference (in-process, per-instance)
- SQLAlchemy `FOR UPDATE` — docs.sqlalchemy.org/en/20/orm/queryguide/select.html#row-locking
- testcontainers-python — testcontainers-python.readthedocs.io (Postgres container for RLS tests)

---

*End of Plan. Ready for QC Round 1.*
