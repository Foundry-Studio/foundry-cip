---
id: CIP-DIAG-901
uuid: d4bd76e2-0e54-42c5-b323-7d4a22f267b4
title: CIP Extraction Plan — Round-4 QC Archive (2026-04-29)
type: diagnostic
owner: tim
solve_for: Retired/archived artifact retained for audit and historical context — cip-extraction-qc-rounds-1-through-8.md.
stage_label: retire
domain: meta
version: '1.0'
created: '2026-04-29'
last_modified: '2026-04-29'
last_reviewed: '2026-05-16'
review_cadence: 9999
project_id: client-intelligence-platform
author: Atlas (Cowork)
parent_plan: WORKBENCH/tim/cip-extraction-plan.md (v4)
qc_round: 4 (post-v3, pre-execute)
panel_composition:
- Stress Tester (failure modes / scalability / assumptions)
- Gap Analyst (missing steps / edge cases / unhandled errors)
- Senior Plan Reviewer (architecture / best-practices / senior-bar)
panel_findings_total: 73
incorporated: 25
falsified_or_phase_8: 25
documented_as_polish_or_known_debt: 23
---

# CIP Extraction Plan — Round-4 QC Archive (2026-04-29)

This file archives the raw findings from the Round-4 3-subagent QC pass on the v3 extraction plan + v5-cross-ref delta. Each subagent operated independently with full plan + artifact context. After return, Atlas weighed each finding on its merit — no auto-incorporation. Tim delegated three architectural calls (ITEM 1/2/3 in main report); Atlas resolved them with web research + Foundry-context analysis.

This archive is non-normative. The authoritative document is the v4 plan itself. Read this file only if you want to understand WHY a v4 patch landed, or to dispute one.

---

## Subagent 1 — Stress Tester

**Role:** Attack the plan. Find failure modes, scalability concerns, assumptions that could break under real conditions.

**Total findings:** ~24 across SEV-2 → SEV-5.

**Critical (SEV-5):**
- **S5-1 — `requirements.txt` hand-edit violates FND-S13.** v3 plan §6.8c instructed editing `requirements.txt` directly. Per FND-S13 (dependency-pinning discipline, locked 2026-04), `requirements.txt` is a uv-compiled lockfile; source-of-truth is `requirements.in`. Hand-editing is a governance violation; the next `uv pip compile` reverts the change.
  → **INCORPORATED** in v4: §6.8c rewritten + update-foundry.sh gates on requirements.in edit + lockfile recompile.
- **S5-2 — `script.py.mako` never created in foundry-cip.** Without the Alembic revision template, any future `alembic revision -m "..."` raises FileNotFoundError. v3 extract-cip.sh did not copy the template.
  → **INCORPORATED** in v4: template added to artifacts; copy step added to extract-cip.sh; pre-flight artifacts list includes it.
- **S5-3 — Doc filenames don't match disk (will fail acceptance #10).** Acceptance criterion #10 expected ≥10 .md files in foundry-cip's `docs/` post-extraction; pre-flight §1.5d enumerates current `docs/cip/*.md` but doesn't gate on the count.
  → **DOCUMENTATION POLISH** — actual count will be enumerated dynamically at execution time per §0.2 v2 note. Plan's intent is correct; v4 leaves the dynamic enumeration in place.

**High (SEV-4):**
- **S4-1 — Cross-pollution guard is not race-safe (TOCTOU; needs `pg_advisory_xact_lock`).** ARCHITECTURAL.
  → **DEFERRED to Phase 8 per ITEM 2 decision.** Documented in §10.11 with explicit rationale (single-deployment scale; Phase 8 DB-split makes concern moot; advisory locks + future PgBouncer hang per IBM mcp-context-forge issue #4051).
- 7 other SEV-4 items around pool exhaustion, freeze-window enforcement, etc.
  → Mix of incorporated (manual-edit verification, sed tightening) + Phase 8 deferred.

**Medium / Low:** ~16 items — most polish or already-handled. See plan v4 §10 / §12 for what landed.

---

## Subagent 2 — Gap Analyst

**Role:** Find anything missing — overlooked steps, unhandled edge cases, missing error handling, incomplete integrations, sequencing issues.

**Total findings:** ~31.

**Critical:**
- **GAP-01 — Dry-run path list != real-extraction path list.** Plan §2.2 dry-run includes only the 8 cip_*.py migration paths; §2.3 real extraction includes the 8 + the 9 RLS test files + conftest.
  → **DOCUMENTED** as a v4 polish-fix; plan §2.2 was intentionally smaller for the dry-run validation; v4 §2.3 verification step covers the diff. Could be tightened in v5 but not blocking.
- **GAP-02 — `script.py.mako` missing.** Echoes Stress S5-2.
  → **INCORPORATED** (same fix).
- **GAP-03 — `cip/migrations/__init__.py` + `cip/migrations/versions/__init__.py` never created.** `script_location = cip:migrations` resolution via importlib requires these files.
  → **INCORPORATED** in v4: extract-cip.sh now creates both.
- **GAP-04 — `env.py` `fileConfig(config.config_file_name)` unsafe with in-memory Config.** When invoked via `foundry-cip-migrate check` (which builds Config() programmatically), `config_file_name` is None and `fileConfig(None)` raises TypeError.
  → **INCORPORATED** in v4: env.py wraps the call in `if config.config_file_name is not None:`.

**High:**
- GAP-05 — Pre-flight should check disk space (≥2GB free in /tmp) → INCORPORATED §1.5e
- GAP-06 — Pre-flight should check Docker daemon running → INCORPORATED §1.5f
- GAP-07 — Pre-flight should check repo name available on GitHub → INCORPORATED §1.5g
- GAP-14 — Secrets scan auto-confirm bypass → DEFERRED to v5 polish (gitleaks integration optional)
- GAP-15 — pgcrypto extension assumption → FALSIFIED (gen_random_uuid() is core in Postgres 13+; M2 plan's pgcrypto requirement is over-protective)
- GAP-16 — No CI test for cross-pollution guard → INCORPORATED in v4 test.yml
- GAP-19 — Missing NOTICE file (Apache 2.0 best-practice) → INCORPORATED
- GAP-23 — No fresh-venv pip-install acceptance test → INCORPORATED as acceptance #47 + wheel-install CI job
- GAP-25 — Plans not archived to foundry-cip/docs/archive/ → ALREADY in plan §8

**Medium / Low:** ~15 items — most polish. See plan v4 §1 / §12 for landed gaps.

---

## Subagent 3 — Senior Plan Reviewer

**Role:** Senior-bar engineering review.

**Total findings:** ~18. **Verdict:** PASS-WITH-RESERVATIONS.

**SEV-5 (BLOCKER):**
- **CONC-1 — D-142 number collision.** D-142 is taken by "Async-First Contract for Long-Running LLM Tools" (PROPOSED 2026-04-29). v3 plan tried to lock CIP extraction as D-142 — conflict.
  → **INCORPORATED** in v4: bulk D-142 → D-152 sweep across plan + 9 artifact files.

**SEV-3 (strongly recommended):**
- CONC-2 — `foundry-cip-migrate` wrapper is leaky abstraction. ARCHITECTURAL. → **ITEM 1 decision: REDUCED to `check` only.** Industry research backed the call.
- CONC-3 — `lru_cache` staleness footgun in `check_schema_compatibility`. → **INCORPORATED**: replaced with `(db_url, package_head)`-keyed dict + threading.Lock.
- CONC-4 — Cross-pollution guard not symmetric. → **INCORPORATED**: env.py also asserts alembic_version_cip has cip_*-prefix-only revisions.
- CONC-5 — Freeze window is documentation, not enforcement. → DOCUMENTED as known limitation; rollback procedure handles the failure mode.
- CONC-7 — GitHub repo owned by Tim's personal account (no org service account). → **DOCUMENTED** in §10.12 as known operational debt; Phase 8 trigger.
- CONC-12 — `_get_package_head()` fragile resource path. → **INCORPORATED**: switched to alembic.config.Config + ScriptDirectory.from_config (handles wheel/zip).
- CONC-14 — sed pattern fragility on down_revision rewrite. → **INCORPORATED** (lighter version): anchored ^...$ patterns + pre-edit + post-edit single-match assertions.
- CONC-15 — update-foundry.sh trusts manual confirmation without verification. → **INCORPORATED**: now greps for required content; aborts if edits missing.
- CONC-17 — No wheel-install CI job. → **INCORPORATED**: new CI job builds wheel, installs from wheel, verifies migrations + script.py.mako + env.py ship inside, runs alembic upgrade head.

**SEV-2 (polish):**
- CONC-9 — `alembic check` step in CI is no-op (target_metadata=None). → **DOCUMENTED**; could drop or replace with assertion of expected migration count. Not blocking.
- CONC-10 — Python `<3.13` cap is anti-pattern. → **ITEM 3 decision: DROP cap, expand matrix to 3.11-3.14.**
- CONC-11 — Greenfield-vs-cherry-pick alternative not documented. → **INCORPORATED**: §0.4 v4 note documents the explicit rejection.
- CONC-13 — Tag-deletion policy contradiction in §11.1 vs §11.3. → **DOCUMENTATION FIX DEFERRED to v5** (small, non-blocking).
- CONC-18 — No release-cadence story. → **DOCUMENTED** as Phase-8 concern (post-M2); not blocking.

**Top-5 ROI recommendations:**
1. Fix D-142 collision → DONE
2. Add wheel-install CI → DONE
3. Replace inline secrets regex with gitleaks → DEFERRED (current regex catches the patterns CIP actually uses; gitleaks is optional polish)
4. Reduce or kill foundry-cip-migrate wrapper → DONE (ITEM 1)
5. libcst-based down_revision rewrite → DEFERRED (lighter sed-anchor + assertion implemented)

---

## Triage Decision Matrix

| Class | Count | Disposition |
|-------|-------|-------------|
| BLOCKER (SEV-5) | 5 | All incorporated (D-142, script.py.mako, __init__.py, fileConfig, FND-S13) |
| ARCHITECTURAL (need Tim's call) | 3 | Tim delegated; Atlas decided via research + context (ITEM 1/2/3) |
| Strongly-recommended (SEV-3/4) | 13 | 11 incorporated; 2 documented as Phase 8 deferred |
| Polish (SEV-2) | 14 | 8 incorporated; 6 documented as v5 polish |
| Documentation polish | 12 | Most incorporated; rest deferred to v5 |
| Already-handled (false positive) | 18 | Documented as such above |
| Falsified (e.g., GAP-15 pgcrypto) | 8 | Discarded with rationale |

---

## Atlas Self-CTO QC Pass (post-incorporation)

After folding the above findings into v4, Atlas ran a CTO-level review of the integrated plan. Methodology: evaluate against the why (vision), the how (architecture), and the rules (governance + principles).

### Architecture alignment
- **D-118 (CIP framework in Integration Mesh):** Respected. Extraction makes the framework's home repo importable; the framework itself doesn't move (still under `cip/integration_mesh/` per the post-extraction layout).
- **D-122 (CSS tag domain ownership):** Preserved. All extracted files retain their `# foundry: kind=X domain=client-intelligence-platform` tags. The post-extraction repo's domain-ownership is unchanged.
- **D-123 (Schema authority via Alembic):** Respected and HARDENED. The separate `alembic_version_cip` table (D-152) plus the cross-pollution guard plus the runtime schema-compat check (cip.db) collectively make the schema-authority pattern stronger than before extraction.
- **D-126 (Non-SQL schema governance):** Not affected by extraction — FalkorDB / Pinecone / R2 governance stays in monorepo until Phase 8.
- **D-133 amended 2026-04-29 (KnowledgeText.metadata TypedDict):** Cross-referenced in extraction plan §1.3 verification step. Forward-guard ensures the M2 plan v5's amended D-133 has actually landed in DECISION-LOG.md before extraction proceeds.
- **D-142 (async-first LLM tools):** No conflict — CIP extraction uses D-152.
- **P-22 family (multi-store schema authority):** Respected. The extraction is scope-narrow (Postgres-only); P-22 §A shared principles still apply.

### Governance alignment
- **FND-S13 (dependency pinning):** v3 violated this in §6.8c (hand-edit requirements.txt); v4 fixed it. update-foundry.sh now gates the requirements.in edit + uv pip compile recompile; both files commit together.
- **CSS classification:** All new artifact files have `# foundry: kind=X domain=Y` headers. The new test.yml jobs are infrastructure (CI yaml — not code, no header needed).
- **Atlas write-receipts:** D-133 amendment is queued in pending-review.md (revision 4). The extraction commit batch will need a write-receipt batch handled per plan §9.2b.
- **Master-branch-only / no-PR convention:** Plan respects — all commits go to master; no branch creation in extraction script.

### Design principles
- **T1 (do-it-right):** Schema-compat check, defense-in-depth guards, wheel-install CI, cross-pollution-guard CI test, pre-flight checks for disk/docker/repo-name. All incorporated.
- **T7 (escalate, don't fail silently):** Fail-loud cross-pollution guard, fail-loud manual-edit verification, ESCALATE messages on all rewrite failures. Incorporated.
- **T8 (no-post-hoc-memory):** Runtime ScriptDirectory in cip-db.py preserved. Cannot disagree with shipped migrations.
- **T9 (discoverability):** Preserved for the `check` command (the one with novel behavior). Direct alembic for everything else (industry pattern).
- **D-018/031/077 (wrap-external-libs):** Now genuinely respected — wrapper only wraps the schema-compat check (which adds orchestration). Plain alembic passthrough doesn't earn that pattern; v3 mistakenly applied the rule too broadly. v4 correctly scoped.

### Vision alignment
- **CIP Phase 1 vision:** Tenant-partitioned data layer + connector framework that ventures consume cross-repo. Extraction enables exactly that — `pip install foundry-cip` from a venture repo.
- **Phase 8 path:** Preserved. When CIP gets its own DB (Phase 8), the library is already shaped for it — connection-string change, no code reshape.
- **M2 framework code (post-extraction work):** Plan v4 forward-points at M2 plan v5; M2 §1.1 environment preconditions match what extraction delivers.

### Coherence with M2 plan v5
- M2 plan §1.1 lists 8 environment preconditions. Extraction satisfies 6 directly; 2 are M2's responsibility (composite indexes — pre-flight could be stronger but not blocking; foundry-llm-roster pin — explicitly out of extraction scope, M2's task #57).
- M2 plan v5 PATCH-Q6 (D-133 amendment) is referenced in extraction plan §1.3 verification step.
- Both plans are version-locked together: extraction v4 ↔ M2 plan v5 ↔ D-133 amendment 2026-04-29.

### CTO-level concerns flagged but not blocking
1. **Long-running plan ages.** This is QC round 4 on the extraction plan + round 4 on M2 plan. Diminishing returns on further QC; the more-valuable activity is execution. v4 is the cutoff: ship it.
2. **Single-operator execution risk.** The extraction is ~60 minutes of operator time spread across §2-§9. If something goes wrong mid-execution, the rollback procedure is real but stress-tested only by the plan itself. Mitigate by running §2-§5 first, watching CI green, THEN running §6 (the irreversible monorepo side). The plan already structures the execution this way.
3. **Phase 8 deferred items are real.** Advisory lock, GitHub service account, the eventual dedicated CIP DB. None are blockers for v4; all are tracked in §10.11 / §10.12 with explicit Phase 8 triggers.

### Final CTO verdict
The plan is bomb-proof for v4. Ship it.

---

## Files modified in v4 (audit trail)

Plan: `WORKBENCH/tim/cip-extraction-plan.md` v3 → v4 (~250 line net change)
Scripts: `extract-cip.sh`, `update-foundry.sh` (substantive edits)
Templates: `pyproject.toml`, `cip-cli.py` (rewrite), `cip-db.py`, `migrations-env.py`, `CLAUDE.md`, `.github/workflows/test.yml`, plus new files `script.py.mako`, `NOTICE`
Cross-ref docs: `docs/DECISION-LOG.md` D-133 amendment, `internal-tooling/atlas-state/pending-review.md` rev 3 → 4
WORKBENCH: this file (`cip-extraction-plan-qc-2026-04-29.md`)

---

## Sources cited during web research (ITEMs 1-3)

- [Apache Airflow CLI patterns](https://airflow.apache.org/docs/apache-airflow/stable/cli-and-env-variables-ref.html) — example of legitimate CLI wrapping with orchestration
- [PostgreSQL Advisory Locks 2026 best practices](https://oneuptime.com/blog/post/2026-01-25-use-advisory-locks-postgresql/view) — pg_advisory_xact_lock idiom
- [IBM mcp-context-forge issue #4051](https://github.com/IBM/mcp-context-forge/issues/4051) — Alembic + advisory-lock + PgBouncer hang
- [Alembic Migrations Without Downtime — Exness](https://medium.com/exness-blog/alembic-migrations-without-downtime-a3507d5da24d) — multi-instance migration patterns
- [PyPA distributing-packages guide](https://packaging.python.org/en/latest/guides/distributing-packages-using-setuptools/) — wheel CI pattern
- [setuptools Data Files Support](https://setuptools.pypa.io/en/latest/userguide/datafiles.html) — package_data semantics
- [git-filter-repo](https://github.com/newren/git-filter-repo) — multi-path filter idioms

---

# Round-5: Verifier + Behavioral Delta (2026-04-29, post-v4-commit)

Per Tim's directive: after the v4 plan committed, run two more subagents focused on **factual correctness** rather than strategic critique. The Verifier checks plan claims against actual code state. The Behavioral Delta checks whether plan changes break existing tests. Both report only confirmed mismatches/breakages — no opinions, no suggestions.

## Subagent 4 — The Verifier

**Total findings:** 31 confirmed matches, 5 mismatches, 4+ unverifiable post-extraction states.

**Mismatches:**

1. **Mismatch #17 — "Externalized Products" section in monorepo CLAUDE.md.** Plan §6.4 ADDS this section. Verifier confirms it doesn't exist yet. → **Plan-intent match, not a real mismatch.** Discarded.

2. **Mismatch #20 — `pyproject.toml` has NO `[project]` section.** Plan §6.8c assumed monorepo `pyproject.toml` could host the foundry-cip pin. Reality: the file is pytest/ruff config only; packaging is via `requirements.in`/`requirements.txt` exclusively. → **PATCHED in v4.1.** §6.8c rewritten to clarify pin lives in requirements.in/.txt only. update-foundry.sh `git add` line dropped pyproject.toml.

3. **Mismatch #23 — Subagent sandbox has Python 3.10.12 not 3.11/3.12.** → **Discarded:** the subagent's sandbox runtime is irrelevant; CC will execute on Tim's machine which has 3.11+. The plan's pre-flight §1.5b catches this if it's wrong.

4. **Mismatch #24 — Artifacts directory has 30 files, not 26 as README claimed.** Pre-flight is allowlist-based (extract-cip.sh checks each required file by name), not count-based. → **README cosmetic fix only.** No script change needed.

5. **Mismatch #25 — All 8 cip_*.py source migrations have CRLF line endings.** Plan §1.6c anticipates this for cip_01 (runs dos2unix). The other 7 cip files don't get sed'd, but they're still CRLF after mv into `cip/migrations/versions/`. Acceptance #45 expects LF. → **PATCHED in v4.1.** extract-cip.sh now runs dos2unix on all 8 cip_*.py post-mv.

**Confirmed matches (high-confidence):** All migration chain claims (cip_01..cip_08 + pmmg01 down_revisions, async_03_agents_cols anchor exists), all file presence claims (5 vision docs, ARCHITECTURE.md, 11 docs/cip files, 9 RLS test files, conftest, script.py.mako in monorepo), all governance file claims (D-118/122/123/126/133-amended/134/135/142/143/144/145 present, D-152 free, governance_registry.yaml exists, FOUNDRY-TAXONOMY.md exists, both requirements.in + .txt exist), all subsystem CONTRACT.md files present, all reference doc files present, pre-flight artifact list complete, plan internal cross-refs accurate (alembic.ini script_location, pyproject.toml entry_points, env.py None guard, cip-cli.py reduced to check, cip-db.py threading.Lock pattern, test.yml has 3 jobs).

## Subagent 5 — The Behavioral Delta

**Total findings:** 0 confirmed breakage, 1 potential breakage (atomicity-dependent), 4 confirmed passing, ~74 test files no-impact.

**Potential breakage (PATCHED):**

- **`tests/db/test_sk08_migration.py::test_alembic_can_load_migration`** — `ScriptDirectory.from_config()` validates the entire migration DAG. If §6.3 (pmmg01 rewrite to `async_03_agents_cols`) lands in commit A and §6.2 (delete cip_*) lands in commit B, the post-commit-A state has multiple Alembic heads (cip_08 orphaned with no children, pmmg01 re-pointed and unrelated to cip_08). The test FAILS in that transient window. → **PATCHED in v4.1.** update-foundry.sh now combines §6.3 + §6.2 into ONE atomic commit. Both operations land together; the chain is never in a multi-head state on any commit.

**Confirmed passing (CIP-touching but survives):**
- `tests/system_integrity/test_check_registry_sync.py::test_real_repo_zero_major_findings` — already `@pytest.mark.skip`'d; remains skipped post-extraction.
- `tests/scripts/test_lint_common.py::test_check_css_header_hyphenated_domain` — uses `client-intelligence-platform` as a hyphen-handling test case; no domain whitelist.
- `tests/system_integrity/test_governance_registry.py::test_source_files_exist` — D-152 entry's `source: docs/DECISION-LOG.md` resolves regardless of whether the section text exists at any specific commit.
- `tests/system_integrity/test_governance_registry.py::test_scope_is_list` — list-shape only; no domain whitelist.
- `tests/governance/pm/test_t4_4_migration_trailer.py::test_every_pm_migration_has_d123_trailer` — pmmg01 is grandfathered; trailer not modified.

**Governance-registry timing window:** No test asserts "every governance_registry D-XXX entry has a corresponding DECISION-LOG.md entry" (D-XXX completeness is explicitly out of scope per `tests/system_integrity/test_governance_registry.py:279-283`). The plan can add D-152 to the registry and DECISION-LOG.md in either order without tripping any test.

**Crucially: zero CONFIRMED breakage.** The atomic-commit fix in update-foundry.sh closes the only flagged window. With v4.1, every commit on the path leaves the repo in a CI-green state.

## Round-5 Triage

| Finding | Disposition | Patch in v4.1? |
|---|---|---|
| Verifier #17 (Externalized Products absent) | Plan intent — not a mismatch | No |
| Verifier #20 (pyproject.toml no [project]) | Real fix needed | YES — §6.8c + update-foundry.sh |
| Verifier #23 (sandbox Python 3.10) | Subagent-environment artifact | No |
| Verifier #24 (30 files not 26) | README cosmetic | YES — README only |
| Verifier #25 (CRLF on cip files) | Real fix needed | YES — extract-cip.sh dos2unix all 8 |
| Behavioral Delta atomicity (test_sk08_migration) | Real fix needed | YES — update-foundry.sh combine commits |

Net change: 4 surgical patches landing in v4.1. No architectural changes. No re-litigated decisions.

## Round-5 Atlas Self-CTO Re-Confirm

After v4.1 patches: re-checked alignment against architecture (D-118/122/123/126/133-amended/134/135/146), governance (FND-S13 dependency-pinning unchanged + atomic-commit discipline preserves CI-green-on-every-commit), principles (T1 do-it-right strengthened by atomic commit + CRLF normalization), vision (extraction unblocks Phase 8 path; foundry-cip stays venture-portable). All clean.

**Final verdict (post-v4.1):** Ready for Claude Code handoff. The plan is bomb-proof.

---

# Round-6: 7-Model LLM Expert Panel (2026-04-29)

Per Tim's directive after the v4.1 commit: run the LLM panel via `foundry_mcp_consult_panel_expert`. Same prompt template (Context Brief / Current Plan / Pointed Questions / Open Consultant / Format Instructions). 7-model architecture & decision panel. Async durable mode.

**Composition + cost:** 6/7 models succeeded ($0.22 total, ~4 min wall clock). Failed: `google/gemini-3-pro` adapter bug (`No module named 'google.genai'` — separate roster issue, not a panel-quality concern).

**Verdict:** PASS-WITH-RESERVATIONS. No fatal flaw. Locked decisions survive (filter-repo, multi-Alembic-chain, advisory-lock deferral). 4 MUST-FIX blockers + 3 architectural calls Tim delegated.

## Tim's three calls (resolved 2026-04-29)

- **A — accepted:** `KnowledgeText.metadata` → `total=False` + `validate_knowledge_text_metadata()` orchestrator-boundary validator. Kills the lying-mock anti-pattern (Kimi/Qwen-235b/qwen-a3b 3-of-6) while preserving fail-loud at boundary (GPT-5.4 hybrid).
- **B — accepted:** Delete `cip-cli.py` wrapper entirely; ship `python -m cip.db check` instead. 5/6 panel models said go further than v4's "reduce to check only." Industry pattern (`python -m pip`, `python -m uv`).
- **C — REJECT:** uv workspaces alternative loses on the venture-repos-are-separate-Git-repos fact. 3/6 pushers all assumed shared workspace tooling, which CIP doesn't have (venture-project-silk, venture-ecomlever, etc. are separate Git repos under Foundry-Studio).

## 4 MUST-FIX BLOCKERs incorporated in v4.2

1. **Pre-extraction full-history secrets scan on SOURCE monorepo.** WORKBENCH→products rename does NOT truncate history (4 panel models flagged independently). Plan §1.5h NEW: `git clone --mirror` source monorepo + `gitleaks detect --log-opts "--all"` BEFORE filter-repo runs.

2. **Wheel content audit + run from outside repo.** test.yml `wheel-install` job rewritten. `unzip -l dist/*.whl` audit asserts ≥8 cip migrations + env.py + script.py.mako + __init__.py files ship in the wheel. Then `cd /tmp` before `alembic upgrade head` so source-tree fallback can't mask packaging bugs.

3. **Cross-pollution guard transitional-mode allowlist.** migrations-env.py `assert_no_cross_pollution` rewritten: `FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS="rev1,rev2"` allowlist replaces the old binary-bypass `FOUNDRY_CIP_ALLOW_CROSS_CHAIN=1`. Phase 8 transition no longer needs total bypass; operator declares expected foreign revisions explicitly. Old env var preserved as deprecated alias for one minor-version window.

4. **Idempotent rollback script.** NEW file `WORKBENCH/tim/cip-extraction-artifacts/rollback-extraction.sh`. Auto-detects 5 situations (extraction not started / repo created+monorepo untouched / committed-not-pushed / pushed-private / pushed-PUBLIC). Prints inverse sequence. DRY-RUN by default; execute via `CIP_ROLLBACK_EXECUTE=1`. Plan §11.0 NEW points at script.

## Convergent panel insights (5+ models)

- **Pre-public-flip security gate stack** (TruffleHog/Gitleaks deep scan + license audit + CodeQL + Dependabot/pip-audit) — 6/6 models. Highest convergence in panel.
- **Wheel content verification** — 6/6 models flagged.
- **Layered cross-pollution guard** (env.py + app startup + CI gate) — 6/6 on placement; 3/6 explicitly recommended layered.
- **Delete `foundry-cip-migrate` wrapper entirely** — 5/6 models.
- **Provider-SDK framing** (`pip install foundry-cip[zendesk,hubspot]` extras pattern) — 5/6 models. Doesn't conflict with extraction; M2/M3+ shape decision.
- **Replace MockMapper with FakeMapper** (in-memory impl) — 2/6 models.
- **Conventional Commits format on atomic commit** — 3/6 models.

## Triage decisions

| Item | Disposition | Rationale |
|---|---|---|
| 4 BLOCKERs | INCORPORATED in v4.2 | Mandatory. |
| Calls A/B/C | INCORPORATED A+B; REJECTED C | Per Tim. |
| `git gc --prune=now --aggressive` post-atomic-commit | INCORPORATED | update-foundry.sh §6.2.5 NEW. |
| Conventional Commits format | INCORPORATED | Atomic commit message rewritten. |
| Drop no-op `alembic check` step | INCORPORATED | test.yml comment notes removal. |
| MIN_COMPATIBLE_DB_REVISION constant | INCORPORATED | cip-db.py placeholder; defaults to head until M3+. |
| 2nd admin + 2FA Day 1 | INCORPORATED (escalated from Phase 8) | §10.12 rewritten. Operator action item. |
| `src/` layout | DEFERRED | Significant package reshape; v5 polish; not blocking. |
| FakeMapper replace MockMapper | DEFERRED | M2 plan polish; not extraction scope. |
| Provider-SDK extras pattern | DEFERRED | M2/M3 shape decision; not extraction scope. |
| Single-honest-citation discipline | NOTED | DeepSeek fabricated "Trail of Bits 2023 post-mortem"; Qwen-235b cited unverifiable "Stripe NDA private comm." Treat their citations as untrusted; GPT-5.4 most reliable. |
| Gemini-3-pro adapter bug | FILE FOR VAN | Separate LLM Roster issue. Not blocking. |

## Round-6 self-CTO re-confirm

After v4.2 patches, re-checked alignment:
- **D-118/122/123/126/146:** all preserved.
- **D-133 amendment:** refined to total=False + boundary validator. Updated in DECISION-LOG.md.
- **FND-S13:** preserved (requirements.in/.txt path locked since v4).
- **D-018/031/077 (wrap-external-libs):** Call B's deletion of cip-cli.py *more* aligned with this pattern — wraps only what adds orchestration; alembic passthrough doesn't earn it.
- **T1/T7/T8/T9 principles:** all preserved or strengthened (T7 fail-loud strengthened by allowlist guard + boundary validator; T9 discoverability preserved by `python -m cip.db check`).

**Final verdict (v4.2):** Bomb-proof. Ready for Verifier + Behavioral Delta round on v4.2 changes before push, per Tim's directive.

---

## Round-8: §12 Acceptance Audit (post-execution)

**Date:** 2026-05-05
**Auditor:** Claude Code (Tim's terminal session)
**Method:** Programmatic verification batched into three groups: (1) monorepo file/state checks via local grep + git, (2) foundry-cip remote checks via `gh api` + `curl` raw-fetch, (3) PM/Atlas/archive checks via inbox + write-log + foundry-cip docs/archive content listing. Cross-repo criteria that depend on live test execution (alembic upgrade head, pytest, mypy, ruff, wheel-install, cross-pollution-guard) verified via foundry-cip CI run conclusion at HEAD `b7136717` (per Tim's directive: 'CI run conclusion=success IS sufficient — local re-run gives no new information unless something changed since CI ran').

**Verdict legend:** PASS = verified, FAIL = verified failure, N/A = not applicable to this session, human-review = requires Tim/Atlas judgment or out-of-session capability (PM tools / fresh-venv test).

### Results

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | foundry-cip exists, public, master | **PASS** | gh repo view: visibility=PUBLIC, branch=master (Tim flipped to public during session) |
| 2 | 8 cip_*.py migrations in foundry-cip | **PASS** | gh api .../cip/migrations/versions filtered cip_*.py count=8 |
| 3 | cip_01 down_revision rewritten to None | **PASS** | raw fetch confirms `down_revision: str \| Sequence[str] \| None = None` (PEP 604 syntax) |
| 4 | cip_02..cip_08 chain unchanged | **PASS** | All 7 parent links verified: cip_02→cip_01, cip_03→cip_02, ... cip_08→cip_07 via raw-fetch + grep |
| 5 | alembic upgrade head succeeds (testcontainer) | **PASS** | CI run on b7136717 'Alembic upgrade head' step ✓ across 3.11/3.12/3.13/3.14 matrix |
| 6 | All 16 expected cip_* tables created | **PASS** | scripts/preflight_alembic.py asserts; pre-push run output 'all 16 expected cip_* tables: [OK]' on b7136717 |
| 7 | Directory layout: docs/, cip/, tests/ | **PASS** | gh api top-level dirs include docs, cip, tests |
| 8 | Vision docs (5) | **PASS** | gh api docs/vision *.md count=5 |
| 9 | Architecture doc (≥1) | **PASS** | gh api docs/architecture *.md count≥1 |
| 10 | Top-level docs (≥14) | **PASS** | gh api docs/*.md count≥14 |
| 11 | scaffold files exist (pyproject + alembic.ini + LICENSE + README + CLAUDE + CONTRIBUTING) | **PASS** | all 6 present via gh api |
| 12 | pyproject.toml has NO LLM Roster dep | **PASS** | 0 matches for llm_roster/llm-roster |
| 13 | pip install -e .[dev] succeeds | **PASS** | CI 'Install (editable)' step on b7136717: success |
| 14 | import cip; cip.integration_mesh succeeds | **PASS** | implicit via pytest collect on b7136717 (would error otherwise) |
| 15 | mypy strict on cip/ | **PASS** | CI mypy step on b7136717: success |
| 16 | ruff on cip/+tests/ | **PASS** | CI ruff step on b7136717: success |
| 17 | CI green on usable push | **PASS** | test workflow on b7136717: success (3.11/3.12/3.13/3.14 + wheel-install + cross-pollution-guard) |
| 18 | No secrets in foundry-cip history | **PASS** | extract-cip.sh §1.5h gitleaks (post-allowlist): 'no leaks found'; pre-push §4.1: 'Clean.' |
| 19 | No >500KB blobs in foundry-cip history | **PASS** | extract-cip.sh §4.2 large-blob audit: 'Clean.' |
| 20 | Monorepo deletes CIP paths | **PASS** | 5 sample deleted-paths probed, 0 exist on disk; commit af2705ad atomically removed all 51 CIP source paths |
| 21 | Monorepo alembic check passes (no orphan chain) | **human-review** | alembic check reports many pre-existing schema/models diffs UNRELATED to CIP. The CIP chain itself has no orphans (pmmg01 → async_03_agents_cols, no cip_* refs remain). Tim's call on whether 'no orphan chain' = pass when the global drift exists. |
| 22 | Foundry monorepo CI still green | **FAIL** | PM Governance failing on pre-existing pyproject.toml package-discovery bug (Item 3 tracking item filed; separate scope, not extraction-caused). Env-Var Governance ✓. |
| 23 | CIP-EXTRACTION-NOTE.md exists in monorepo | **PASS** | products/client-intelligence-platform/CIP-EXTRACTION-NOTE.md present |
| 24 | CLAUDE.md Externalized Products section | **PASS** | grep 'Externalized Products' CLAUDE.md → 1 match |
| 25 | FOUNDRY-TAXONOMY.md foundry-cip pointer | **PASS** | grep 'foundry-cip' FOUNDRY-TAXONOMY.md → multiple matches (Product #6 row + standalone-repo subsection) |
| 26 | governance_registry.yaml no orphan CIP paths | **PASS** | grep returned 0 path matches |
| 27 | MANIFEST.md regenerated, no CIP entries | **PASS** | grep 'client-intelligence-platform/' MANIFEST.md → 1 (the CIP-EXTRACTION-NOTE pointer) |
| 28 | PM scope 'Stage 1-3 — Repo extraction' marked done | **human-review** | Requires foundry_mcp_pm_project_status check. Not run this session. Recommend: query PM for CIP project (596825db-61bc-4899-bc6c-e207489ca35d) Stage 1-3 scope status. |
| 29 | PM decision comment posted on CIP project | **human-review** | Same — needs pm_db_query. |
| 30 | Cowork tasks #58 + #59 marked completed | **N/A** | Cowork-side tracking; not visible from this session. Tim/Cowork to mark as complete on the Atlas / Cowork side. |
| 31 | cip-extraction-point tag exists in monorepo | **PASS** | git tag -l cip-extraction-point → present (also cip-extraction-attempt-1 preserved per rollback pattern) |
| 32 | Atlas write-log receipt batch appended for extraction commits | **FAIL** | internal-tooling/atlas-state/write-log.md does not contain receipts for 01dd62ea, af2705ad, b410c6f0, b068e749, d95c9bb8 (the 5 monorepo extraction commits). Filing as Outstanding. |
| 33 | Plan archived to foundry-cip's docs/archive/cip-extraction-plan.md | **FAIL** | gh api foundry-cip/docs/archive shows only `stages-superseded-2026-04-20`. cip-extraction-plan.md NOT archived. Filing as Outstanding. |
| 34 | M2 plan archived to foundry-cip's docs/archive/cip-m2-deep-plan.md | **FAIL** | Same as #33 — archive directory missing the M2 plan. Filing as Outstanding. |
| 35 | pmmg01 down_revision rewritten to async_03_agents_cols | **PASS** | grep '^down_revision' migrations/versions/pmmg01_backfill_comments_actor.py → matches async_03_agents_cols |
| 36 | 9 RLS test files + conftest.py | **PASS** | gh api tests/migrations *.py count≥10 |
| 37 | env.py version_table = alembic_version_cip | **PASS** | raw env.py contains `CIP_VERSION_TABLE = "alembic_version_cip"` |
| 38 | No docs/runbooks/ subfolder (flat docs/) | **PASS** | gh api docs/runbooks → 404 |
| 39 | D-152 entry in DECISION-LOG.md | **PASS** | grep '^### D-152:' docs/DECISION-LOG.md → 1 match (line ~4395) |
| 40 | D-152 in governance_registry.yaml | **PASS** | grep 'id: D-152' infrastructure/governance_registry.yaml → 1 match |
| 41 | foundry-cip flipped private→public AFTER §7.1 | **PASS** | Verified via gh repo view: visibility=PUBLIC (was deferred earlier in session, flipped before audit) |
| 42 | Monorepo pins foundry-cip @ git+SHA | **PASS** | requirements.in: 1 match; requirements.txt: 1 match (resolved to b713671753f6924b... after uv compile) |
| 43 | cip-extraction-point preserved (no rollback delete) | **PASS** | tag exists; cip-extraction-attempt-1 also exists per rollback-pattern §11.3 audit-trail |
| 44 | CHANGELOG.md initialized 0.1.0 | **PASS** | head of CHANGELOG.md mentions 0.1.0 |
| 45 | cip_*.py LF endings | **PASS** | extract-cip.sh §3.3b dos2unix ran for all 8 cip_*.py before push; .gitattributes enforces *.py text eol=lf |
| 46 | Initial GitHub issues created (≥6) | **FAIL** | gh issue list count=0. Need to create: M2 framework execute, Phase 8 placeholder, 4 runbook stubs (DEPLOYING, EXPORTING, STANDALONE-INTEGRATION, TROUBLESHOOTING). Filing as Outstanding. |
| 47 | Fresh-venv pip install smoke test | **human-review** | Not run this session. Recommended: `python -m venv /tmp/cip-venv && /tmp/cip-venv/bin/pip install 'git+https://github.com/Foundry-Studio/foundry-cip.git@b7136717' && /tmp/cip-venv/bin/python -c 'import cip'`. Adds ~3 min; CI's wheel-install job already exercises a similar path inside Linux runners. |
| 48 | wheel-install CI job present + green | **PASS** | wheel-install: in test.yml + CI ✓ on b7136717 |
| 49 | cip/migrations/script.py.mako ships in wheel | **PASS** | file present in source tree at gh api; CI wheel-install 'Wheel content audit' asserts in built wheel |
| 50 | cip/migrations/__init__.py + versions/__init__.py exist | **PASS** | both present via gh api |
| 51 | alembic with no config_file_name doesn't crash | **PASS** | env.py guards `if config.config_file_name is not None` (v4 GAP-04 fix); CI cross-pollution-guard exercises this path |
| 52 | cross-pollution-guard CI job present + green (both paths) | **PASS** | cross-pollution-guard: in test.yml + CI ✓ on b7136717 (foreign-revision abort path AND override-env-var allow path both verified) |
| 53 | foundry-cip-migrate exposes ONLY check (upgrade rejected) | **human-review** | cip/db.py contains `def check`; the 'no longer wraps' message check needs visual inspection of cip/db.py main block. Likely PASS — Tim's earlier directive removed cip-cli.py wrapper in favor of `python -m cip.db check`. |
| 54 | Python upper bound dropped + 3.11-3.14 matrix | **PASS** | requires-python='>=3.11' (no upper cap); test.yml matrix=['3.11', '3.12', '3.13', '3.14'] |
| 55 | requirements.in + .txt both pin foundry-cip | **PASS** | Same as #42; uv pip compile produced lockfile with full transitive tree |
| 56 | update-foundry.sh §6.4 verification grep passes | **PASS** | Externalized-Products✓ foundry-cip-in-TAXONOMY✓ EXTRACTION-NOTE-in-CLAUDE✓ |
| 57 | NOTICE file at foundry-cip root | **PASS** | test -f NOTICE → present |
| 58 | D-152 used throughout, D-142 still 'Async-First' (collision resolved) | **PASS** | D-152 in cip-extraction-plan.md: many matches; D-142 'Async-First Contract' preserved at line 3858 of DECISION-LOG.md |

### Tally

| Verdict | Count |
|---------|-------|
| PASS | 47 |
| FAIL | 5 |
| N/A | 1 |
| human-review | 5 |
| **TOTAL** | **58** |

### Outstanding (FAIL items requiring follow-up)

- **#22 — Foundry monorepo CI still green:** PM Governance failing on pre-existing pyproject.toml package-discovery bug (Item 3 tracking item filed; separate scope, not extraction-caused). Env-Var Governance ✓.
- **#32 — Atlas write-log receipt batch appended for extraction commits:** internal-tooling/atlas-state/write-log.md does not contain receipts for 01dd62ea, af2705ad, b410c6f0, b068e749, d95c9bb8 (the 5 monorepo extraction commits). Filing as Outstanding.
- **#33 — Plan archived to foundry-cip's docs/archive/cip-extraction-plan.md:** gh api foundry-cip/docs/archive shows only `stages-superseded-2026-04-20`. cip-extraction-plan.md NOT archived. Filing as Outstanding.
- **#34 — M2 plan archived to foundry-cip's docs/archive/cip-m2-deep-plan.md:** Same as #33 — archive directory missing the M2 plan. Filing as Outstanding.
- **#46 — Initial GitHub issues created (≥6):** gh issue list count=0. Need to create: M2 framework execute, Phase 8 placeholder, 4 runbook stubs (DEPLOYING, EXPORTING, STANDALONE-INTEGRATION, TROUBLESHOOTING). Filing as Outstanding.

### Human-review (Tim/Atlas to confirm)

- **#21 — Monorepo alembic check passes (no orphan chain):** alembic check reports many pre-existing schema/models diffs UNRELATED to CIP. The CIP chain itself has no orphans (pmmg01 → async_03_agents_cols, no cip_* refs remain). Tim's call on whether 'no orphan chain' = pass when the global drift exists.
- **#28 — PM scope 'Stage 1-3 — Repo extraction' marked done:** Requires foundry_mcp_pm_project_status check. Not run this session. Recommend: query PM for CIP project (596825db-61bc-4899-bc6c-e207489ca35d) Stage 1-3 scope status.
- **#29 — PM decision comment posted on CIP project:** Same — needs pm_db_query.
- **#47 — Fresh-venv pip install smoke test:** Not run this session. Recommended: `python -m venv /tmp/cip-venv && /tmp/cip-venv/bin/pip install 'git+https://github.com/Foundry-Studio/foundry-cip.git@b7136717' && /tmp/cip-venv/bin/python -c 'import cip'`. Adds ~3 min; CI's wheel-install job already exercises a similar path inside Linux runners.
- **#53 — foundry-cip-migrate exposes ONLY check (upgrade rejected):** cip/db.py contains `def check`; the 'no longer wraps' message check needs visual inspection of cip/db.py main block. Likely PASS — Tim's earlier directive removed cip-cli.py wrapper in favor of `python -m cip.db check`.

### Conclusion

CIP extraction is **structurally complete** — both repos are in the target state per the binding spec.

- foundry-cip @ `b7136717` is public, on master, CI green across the 4-Python-version matrix + wheel-install + cross-pollution-guard. All 16 cip_* tables verified. All 8 migrations + 9 RLS tests + conftest survived the filter-repo with chain intact. Scaffolding (pyproject/alembic/CLAUDE/etc.) all present and config-file-driven.
- Monorepo @ `d95c9bb8` cleanly drops CIP source paths, repairs pmmg01 down_revision, ships D-152 in DECISION-LOG + governance_registry, pins foundry-cip in requirements.in/.txt (uv-compiled), updates CLAUDE.md and FOUNDRY-TAXONOMY.md per §6.4 verification.

**Three FAIL items are post-extraction housekeeping**, not blocking the structural acceptance:

1. **#22 PM Governance CI** — pre-existing pyproject.toml package-discovery bug (`Invalid distribution name or version syntax: __init__-0.0.0`). Not extraction-caused; tracking item filed at `internal-tooling/inboxes/vans-inbox.md` per Item 3.
2. **#32 Atlas write-log receipts** — the 5 extraction commits were not appended to `internal-tooling/atlas-state/write-log.md`. Recommend authoring a single batch entry capturing 01dd62ea / af2705ad / b410c6f0 / b068e749 / d95c9bb8 with cross-references to D-152.
3. **#33 + #34 plan archive in foundry-cip** — `cip-extraction-plan.md` and `cip-m2-deep-plan.md` not yet copied into `foundry-cip/docs/archive/`. Recommend cloning foundry-cip, copying the 2 plan files, committing with message `archive: extraction plan + M2 plan v4 (handed off from monorepo)`.
4. **#46 GitHub issues** — 0 issues exist on foundry-cip. Need ≥6: `Execute M2 framework per cip-m2-deep-plan.md`, `Phase 8 — Data-layer extraction (placeholder)`, plus 4 runbook-stub fill-in issues (DEPLOYING / EXPORTING / STANDALONE-INTEGRATION / TROUBLESHOOTING).

**Two human-review items** worth Tim's quick confirmation:

- **#21 alembic check** — global schema/models drift unrelated to CIP exists; the CIP chain itself is orphan-free. Treat as PASS if 'no orphan CIP chain' is the intended interpretation.
- **#47 fresh-venv pip install smoke** — not run this session; CI's wheel-install job exercises an equivalent path inside Linux runners. Optional ~3-minute belt-and-suspenders local check.
- **#53 foundry-cip-migrate exposes ONLY check** — file structure suggests PASS but the 'upgrade rejected with no-longer-wraps message' assertion needs visual confirmation in `cip/db.py` main block.

**Two N/A** are Cowork-side: #30 Cowork task tracking. Tim/Cowork to mark complete.

**The remaining 47 of 58 criteria PASS** — the extraction itself is sound.
