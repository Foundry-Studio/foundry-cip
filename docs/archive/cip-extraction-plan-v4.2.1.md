---
id: CIP-SPEC-901
uuid: 4bfe7767-a969-4906-a591-6e565a1abb16
title: Foundry-CIP Repo Extraction Plan
type: spec
owner: tim
solve_for: Retired/archived artifact retained for audit and historical context — cip-extraction-plan-v4.2.1.md.
stage_label: retire
domain: meta
version: v4.2
created: '2026-04-27'
last_modified: '2026-04-29'
last_reviewed: '2026-05-19'
review_cadence: 9999
project_id: client-intelligence-platform
pm_project_id: 596825db-61bc-4899-bc6c-e207489ca35d
author: Atlas (Cowork)
executor: Claude Code (terminal CLI)
extraction_target: foundry-cip
extraction_org: Foundry-Studio
modeled_after: WORKBENCH/tim/jos-phase8-repo-split-plan.md
supersedes: '(1) Cowork tasks #58 + #59 placeholder descriptions ("Create foundry-cip
  repo scaffolding" / "Move 8 CIP migrations") — this plan provides the executable
  detail those placeholders point at. (2) v1 (2026-04-27 morning) — superseded by
  v2 (2026-04-27 afternoon) after 3-subagent QC round (Stress Tester / Gap Analyst
  / Senior Reviewer) surfaced ~40 mechanical fixes + 7 architectural calls Tim resolved
  in-turn. (3) v2 (2026-04-27 afternoon) — superseded by v3 (2026-04-28) after 2-round
  LLM expert panel via foundry_mcp_consult_panel_expert. Round 1 surfaced 4 critical
  findings (Q6 packaging bug, Q3 chain-skip approach split, env-table cross-pollution,
  schema-compat check). Round 2 forced decisive answers — 7/7 unanimous on Option
  A pmmg01 sed-rewrite, 7/7 on move-into-package, 6/7 on Sketch 2 cross-pollution
  guard, 6/7 on runtime schema-compat check. Tim made final calls on the 3 lingering
  items via principles: YES entry-point console script (T9 discoverability), YES runtime
  schema-compat (T1 + T7 + D-026 defense-in-depth), runtime ScriptDirectory implementation
  (T8 no-post-hoc-memory). (4) v3 (2026-04-28) — superseded by v4 (2026-04-29) after
  Round-4 LLM panel on the M2 plan surfaced 6 patches landing in M2 plan v5 + a D-133
  amendment (KnowledgeText.metadata becomes TypedDict). v4 of THIS extraction plan
  re-pins the M2 cross-references (v4 → v5), notes the D-133 amendment in related_decisions,
  and re-runs a 3-subagent QC round (Stress Tester / Gap Analyst / Senior Plan Reviewer)
  against the post-amendment plan as a forward-guard.

  '
v4_revision_summary: 'Comprehensive QC + research-driven hardening. ~250 lines net
  change across plan + 12 artifacts. CROSS-REF SWEEP (planned): - Frontmatter: version
  v3 → v4, last_updated 2026-04-28 → 2026-04-29. - §1.3 M2 plan version check: grep
  expects "v5" not "v4". D-133 amendment landed-check added. - §0.2, §3.2, §6, §7,
  §8, §10.5, §12 cross-refs to "M2 plan v4" → "M2 plan v5". - related_decisions: D-133
  line annotated as amended 2026-04-29 (TypedDict). QC ROUND 4 INCORPORATED (3 subagents
  2026-04-29 — 73 findings, ~25 incorporated, ~25 falsified, ~23 polish-deferred):
  BLOCKERS resolved: - D-142 → D-152 collision sweep (Senior CONC-1, BLOCKER): D-142
  was already taken in DECISION-LOG.md by "Async-First Contract for Long-Running LLM
  Tools." Renumbered to D-152 across plan + 9 artifact files. - script.py.mako (Gap
  GAP-02 / Stress S5-2): Alembic revision template was missing from artifacts; without
  it, `alembic revision -m "..."` raises FileNotFoundError. Added to templates/ +
  extract-cip.sh copy step. - cip/migrations/__init__.py + versions/__init__.py (Gap
  GAP-03): script_location="cip:migrations" cannot resolve via importlib without these.
  Added to extract-cip.sh. - fileConfig(None) crash (Gap GAP-04): env.py raises TypeError
  when invoked via in-memory Config. Wrapped in None guard. - requirements.txt hand-edit
  (Stress S5-1, FND-S13 violation): update-foundry.sh + plan §6.8c rewritten — edit
  requirements.in, recompile via uv pip compile. Both gated. ARCHITECTURAL DECISIONS
  (3 items Tim delegated for research-backed call): - ITEM 1 (Senior CONC-2): foundry-cip-migrate
  wrapper REDUCED to `check` only. Industry data: don''t wrap stable upstream CLIs
  without orchestration; D-018/031/077 wrap-external-libs is for LLM Roster which
  adds real orchestration. Plain alembic passthrough doesn''t earn that pattern. Tim
  Decision-1 (T9 discoverability) preserved for the value-add command. - ITEM 2 (Stress
  S4-1): Cross-pollution guard advisory-lock DEFERRED to Phase 8. Industry data: pg_advisory_xact_lock
  is standard but + PgBouncer-style pooling hangs (IBM mcp-context-forge issue #4051);
  at our pre-Phase-8 single-deployment scale the TOCTOU window is non-exploitable.
  Documented as known-limitation in §10.11. - ITEM 3 (Senior CONC-10): Python `<3.13`
  upper bound DROPPED + matrix expanded to 3.11-3.14. PyPA explicitly warns against
  caps for libraries. HARDENING (incorporated mechanically): - lru_cache footgun in
  check_schema_compatibility (Senior CONC-3): replaced with (db_url, package_head)-keyed
  dict + threading.Lock. Auto-invalidates on package advance. - _get_package_head()
  fragile resource path (Senior CONC-12): switched to alembic.config.Config + ScriptDirectory.from_config
  — handles wheel/zip-installed packages. - Symmetric cross-pollution guard (Senior
  CONC-4): env.py also asserts alembic_version_cip has only cip_*-prefixed revisions.
  - Wheel-install CI job (Senior CONC-17 + Gap GAP-23): new job builds + installs
  wheel, asserts migrations + script.py.mako + env.py ship inside the wheel, runs
  `alembic upgrade head` from wheel-installed package. - Cross-pollution guard CI
  test (Gap GAP-16): new job seeds foreign alembic_version row, asserts upgrade fails
  with cross-pollution error, asserts FOUNDRY_CIP_ALLOW_CROSS_CHAIN=1 override works.
  - sed pattern tightening (Senior CONC-14): both cip_01 and pmmg01 down_revision
  rewrites now use anchored ^...$ patterns + pre-edit single-match assertion + post-edit
  single-match assertion (catches structural corruption). - update-foundry.sh manual-edit
  verification (Senior CONC-15): no longer trusts "yes" on the Atlas-orchestrated
  edits gate — actually greps for the required content. - Pre-flight 1.5d/e/f/g (Gap
  GAP-05/06/07): disk space ≥2GB, docker daemon running, repo name available pre-checks.
  - NOTICE file (Gap GAP-19): Apache 2.0 attribution best-practice file at repo root.
  - 11 new acceptance criteria (#47-#57) + 1 D-142-collision-resolved criterion (#58).
  GREENFIELD ALTERNATIVE (Senior CONC-11): documented in §0.4 the explicit rejection
  rationale (filter-repo retains modest historical value; greenfield isn''t earned
  at our scale). PHASE-8-DEFERRED concerns (Senior CONC-7 GitHub service account,
  advisory lock per ITEM 2): documented in §10.12 as known operational debt with explicit
  Phase 8 trigger. Subagent reports + raw findings archived at WORKBENCH/tim/cip-extraction-plan-qc-2026-04-29.md.

  '
v4_1_revision_summary: 'Round-5 verification pass (2 subagents — The Verifier + The
  Behavioral Delta — 2026-04-29). 4 patches applied: - VERIFY-1 (Behavioral Delta):
  tests/db/test_sk08_migration::test_alembic_can_load_migration would FAIL in the
  transient window between §6.3 (pmmg01 rewrite) and §6.2 (cip_* deletions) when committed
  separately. Fix: combined §6.3 + §6.2 into ONE atomic commit in update-foundry.sh;
  pmmg01 stage but no commit until §6.2 finishes; single commit message names both
  operations. Eliminates the multi-head transient. - VERIFY-2 (Verifier mismatch #20):
  monorepo pyproject.toml has NO [project] section (it''s pytest/ruff config only;
  packaging is via requirements.in/.txt). Fix: §6.8c rewritten to clarify the pin
  lives EXCLUSIVELY in requirements.in/.txt; update-foundry.sh now does `git add requirements.in
  requirements.txt` only (not pyproject.toml). - VERIFY-3 (Verifier mismatch #25):
  all 8 cip_*.py source migrations have CRLF line endings on disk; without normalization,
  acceptance #45 (LF endings) fails post-extraction. Fix: extract-cip.sh now runs
  `dos2unix` on all 8 cip_*.py files post-mv into cip/migrations/versions/. - VERIFY-4
  (Verifier mismatch #24, doc fix): artifacts directory has 30 files, not 26 as README
  claimed. Pre-flight check is allowlist-based (not count-based), so no script change
  needed; only README.md updated for accuracy. Confirmed-as-non-issue: Verifier mismatch
  #17 (Externalized Products section absent — that''s the plan''s intended ADD), #23
  (Python 3.10 in subagent sandbox — not Tim''s environment). Subagent reports archived
  at WORKBENCH/tim/cip-extraction-plan-qc-2026-04-29.md (Round-5 section appended).

  '
v4_2_revision_summary: 'Round-6 LLM expert panel (7-model consult_panel_expert, 6
  succeeded, 1 adapter bug; $0.22, ~4 min). Tim''s calls: A=accept, B=accept, C=reject
  (uv workspaces lose on venture-repos-are-separate fact). 4 BLOCKERs incorporated:
  - BLOCKER 1 (TruffleHog/Gitleaks full-history scan on SOURCE monorepo): plan §1.5h
  NEW. WORKBENCH→products rename does NOT truncate history (4 panel models flagged).
  Gitleaks `git clone --mirror` + scan with `--log-opts "--all"` BEFORE filter-repo
  runs. If findings: rotate secrets in source systems FIRST; the leak is already public
  to monorepo readers. - BLOCKER 2 (wheel content audit + run from outside repo):
  test.yml `wheel-install` job rewritten. `unzip -l dist/*.whl` audit asserts ≥8 cip_*.py
  + env.py + script.py.mako + __init__.py files. Then `cd /tmp` before `alembic upgrade
  head` so source-tree fallback can''t mask packaging bugs. - BLOCKER 3 (transitional-mode
  allowlist): migrations-env.py `assert_no_cross_pollution` rewritten. Old `FOUNDRY_CIP_ALLOW_CROSS_CHAIN=1`
  was binary-bypass — too coarse for Phase 8 transition. New: `FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS="rev1,rev2"`
  allowlist; guard tolerates listed revisions but still aborts on unexpected. Old
  env var preserved as deprecated alias for one minor-version window. - BLOCKER 4
  (idempotent rollback script): NEW file `rollback-extraction.sh`. Auto-detects 5
  situations (extraction not started / repo created+monorepo untouched / committed-not-pushed
  / pushed-private / pushed-PUBLIC) and prints the inverse sequence. DRY-RUN by default;
  execute via CIP_ROLLBACK_EXECUTE=1. Plan §11.0 NEW points at script; §11.1-§11.3
  retained as authoritative reference matrix. Calls A/B/C applied: - Call A (KnowledgeText.metadata
  = total=False + boundary validator): M2 plan v5 §4.1 + DECISION-LOG D-133 amendment
  refined. Mock mappers can emit `metadata={"source_id": ...}` only — orchestrator
  finalizes the rest before validate_knowledge_text_metadata() at boundary. New KnowledgeMetadataValidationError
  exception. Kills the lying-mock anti-pattern (Kimi 3-of-6 panel) while preserving
  fail-loud at boundary (GPT-5.4). - Call B (delete cip-cli.py wrapper, ship `python
  -m cip.db check`): cip-cli.py file deleted. cip-db.py adds `_cli_main()` + `if __name__
  == "__main__"`. pyproject.toml `[project.scripts]` block removed. CLAUDE.md template
  + extract-cip.sh + plan all updated. Industry pattern (`python -m pip`, `python
  -m uv`). - Call C (REJECT uv workspaces): plan §0.4 v4 greenfield-rejection note
  already covers separate-repo rationale; Round-6 loses on the venture-repos-are-separate-Git-repos
  fact (3-of-6 panel pushers all assumed shared workspace tooling, which CIP doesn''t
  have). Polish incorporated: - `git gc --prune=now --aggressive` post-atomic-commit
  (Round-6 STRONGLY-RECOMMENDED #4): update-foundry.sh §6.2.5 NEW. - Conventional
  Commits format on atomic commit: explicit BREAKING CHANGE footer + rollback command
  line in commit body. - Drop no-op `alembic check` step in CI (Round-6 polish CONC-9):
  test.yml comment notes removal rationale. - MIN_COMPATIBLE_DB_REVISION constant
  placeholder in cip-db.py (defaults to head until M3+). Polish NOT YET incorporated
  (deferred to Phase 1 polish or M2 work): - src/ layout (Kimi single-source). Decision:
  defer to a v5 polish round; significantly reshapes the package layout and is not
  blocking for extraction execution. - Replace MockMapper with FakeMapper. Decision:
  M2 plan v5 polish; not extraction scope. - Provider-SDK extras pattern (`pip install
  foundry-cip[zendesk,hubspot]`). Decision: M2/M3+ shape decision; not extraction
  scope. - 2nd admin + 2FA + transfer plan for foundry-cip GitHub repo Day 1 (Round-6
  STRONGLY-RECOMMENDED #10). Decision: documented in §10.12 as DAY-1 escalation (was
  Phase 8 in v4); operator action item, not script-side. Net change: ~600 lines across
  plan + 8 artifacts + 1 new script. M2 plan v5 → v5.2 inline (no file rename; revision
  marker in §4.1). Round-6 panel synthesis archived at WORKBENCH/tim/cip-extraction-plan-qc-2026-04-29.md
  (Round-6 section).

  '
related_decisions:
- D-118 — CIP framework lives in Integration Mesh
- D-122 — Domain ownership via CSS tag, not folder location
- D-123 — Schema authority via Alembic
- D-126 — Non-SQL schema governance (FalkorDB / Pinecone / R2)
- D-133 — KnowledgeText return type (amended 2026-04-29 — KnowledgeText.metadata becomes
  TypedDict; M2 v5 lock + extraction lock)
- D-134 — Protocol-based connector framework (M2 v5 lock)
- D-135 — App-layer SCD Type 2 (M2 v5 lock)
- D-152 — (locks at extraction time) CIP code lives in foundry-cip; monorepo consumes
  via pip; separate alembic_version tables.
v2_revision_summary: 'Resolved 7 architectural items via Tim 2026-04-27 turn: Q1 —
  pmmg01_backfill_comments_actor''s down_revision rewritten to async_03_agents_cols
  (cip_01''s old parent) — now §6.3. Q2 — 9 RLS test files (tests/migrations/test_rls_cip_*.py
  + their conftest.py) move to foundry-cip — added to §0.2 inventory. Q3 — Separate
  alembic_version tables: foundry-cip''s env.py uses version_table = "alembic_version_cip";
  monorepo keeps default — encoded in §3.10 + §6.3. Q4 — Accept WORKBENCH→products
  rename history truncation; foundry-cip history starts 2026-04-20; documented in
  CIP-EXTRACTION-NOTE.md. Q5 — Drop docs/ rename; keep top-level docs/ to align with
  M2 v4 path-pin. §3.2 + §0.4 updated. Q6 — Lock D-152 documenting the extraction;
  added to §6 commit batch. Q7 — Private-at-extraction, flip to public after §7 validation
  passes. §1.8 + §5 updated. Plus ~40 mechanical fixes (CRLF normalization, sed_i
  portable definition, pre-flight Python check, drop --license flag from gh repo create,
  expanded doc-drift sweep across 6 new files, pre-generated artifacts directory,
  repo metadata files, pyproject.toml hardening, tests scaffolding, Atlas receipt
  template, etc.) — see triage report below.'
---

# Foundry-CIP Repo Extraction Plan

## Headline

Extract the Client Intelligence Platform's docs + migrations + framework namespace from `Foundry-Agent-System` (monorepo) into a standalone `Foundry-Studio/foundry-cip` GitHub repo. Preserve git history. Rewire Alembic chain so foundry-cip's `alembic upgrade head` runs cleanly against an empty Postgres. Update Foundry-Agent-System to consume CIP via the standalone repo (foundry-cip becomes a pip-installable library). Ship a venture-onboarding documentation set inside foundry-cip so any future venture (or Foundry team member) can deploy CIP for a new tenant from the docs alone.

This plan covers Cowork tasks #58 (`Create foundry-cip repo scaffolding`) + #59 (`Move 8 CIP migrations`) plus the Foundry-side cleanup, validation, and venture-onboarding doc set those tasks imply but don't enumerate. It mirrors the JOS Phase 8 extraction plan's structure (`WORKBENCH/tim/jos-phase8-repo-split-plan.md`), adapted for CIP's multi-path source layout and code-only-extraction-now / data-extraction-later phasing.

**Junior-dev day-one lens:** every step has explicit commands. Every file edit has before/after. Every validation has an exact assertion. No "figure it out" moments.

---

## 0. Decision Context

### 0.1 Why split now

CIP is Foundry's Product #6. Its code, schema, and docs currently live inside the `Foundry-Agent-System` monorepo. Three forces drive the split:

1. **Cross-repo connector portability.** Phase 2+ ventures (Wayward, Rocky Ridge, Project Silk client work, future ones) write `CIPConnector` subclasses against the framework. Per D-134 the framework is `@runtime_checkable typing.Protocol` + optional ABC helpers — structural typing means a venture's connector can sit in `venture-<name>` repo and consume foundry-cip via `pip install foundry-cip`. This works only if foundry-cip is its own installable repo. While CIP lives inside Foundry-Agent-System, ventures would have to clone the entire monorepo (~50K LOC across PM, agents, JOS extraction notes, MCP, etc.) to get the framework.

2. **Architectural alignment with the established pattern.** JOS shipped 2026-04-25 as `Foundry-Studio/jordan-operating-system` — extracted from the same monorepo using `git filter-repo --subdirectory-filter`. The pattern is known to work and is documented (`operating-systems/JOS-EXTRACTION-NOTE.md`, `WORKBENCH/tim/jos-phase8-repo-split-plan.md`). CIP is a Product, JOS is a governance Standard — different content, same repo-shape problem. Reusing the JOS template lowers risk and gives Foundry one canonical extraction recipe.

3. **Sets up Phase 8 ("Scale & Extract") at low cost.** ARCHITECTURE.md §1 commits to "when CIP becomes a standalone deployable product, the cip_ tables migrate to a dedicated database." Today the data still lives in Foundry's shared Postgres (correct for Phase 1-3 single-digit-tenant scale). The CODE extraction now means: when Phase 8 schedules data-layer extraction, the library is already shaped for it — connection-string change, no code reshape.

**What this extraction is NOT:**

- NOT a deployment-layer split. CIP's data continues to live in Foundry's shared Postgres until Phase 8. Ventures don't deploy their own CIP today; Foundry runs CIP centrally and serves their tenants.
- NOT a service-ification. CIP is a Python library + Postgres schema, not a runtime service. Phase 4 will add REST/MCP consumption surfaces — those ship from the Foundry monorepo and call into foundry-cip, they don't live inside foundry-cip.
- NOT a venture-portability rewrite. The Protocol framework already works cross-repo (D-134). This extraction makes the framework's home repo importable.

### 0.2 What stays, what goes

**Goes to `foundry-cip`:**

| Source path (in monorepo) | Target path (in foundry-cip) | Note |
|---|---|---|
| `products/client-intelligence-platform/vision/*` | `docs/vision/*` | All five files: VISION, ROADMAP, PHASE-1-PLAN, PHASE-1-PLAIN-SPEC, PHASE-2.5-PLAN |
| `products/client-intelligence-platform/architecture/ARCHITECTURE.md` | `docs/architecture/ARCHITECTURE.md` | |
| `products/client-intelligence-platform/notes/*` | `docs/notes/*` | Initial braindump, vision conversation log — kept as historical record |
| `products/client-intelligence-platform/research/industry-landscape.md` | `docs/research/industry-landscape.md` | |
| `products/client-intelligence-platform/archive/*` | `docs/archive/*` | Superseded stage docs — kept as historical |
| `products/client-intelligence-platform/CLAUDE.md` | (replaced — see §3.6) | The original was Cowork-era; we ship a foundry-cip-shaped one |
| `products/client-intelligence-platform/README.md` | `README.md` | Top-level project README |
| `migrations/versions/cip_01_clients.py` | `migrations/versions/cip_01_clients.py` | **down_revision rewrite required — see §3.4** |
| `migrations/versions/cip_02_views.py` ... `cip_08_tickets_and_registry.py` | `migrations/versions/` (same names) | No down_revision changes — they chain only within CIP |
| `docs/cip/*` (10 docs + `_TEMPLATE.md` from Phase 1 deliverables) | `docs/*` (top-level — NO `runbooks/` subfolder) | The 10 documentation artifacts shipped in Phase 1 M0 + `_TEMPLATE.md` (frontmatter template). v2: kept at top-level `docs/` (not `docs/`) per Tim Q5 decision — aligns with M2 plan v5's hardcoded path references (`docs/CONNECTOR-AUTHORING-GUIDE.md` etc. — same paths as v4; v5 didn't reshape doc paths). Enumerate exact filenames at execution time via `ls docs/cip/*.md`. |
| `tests/migrations/test_rls_cip_clients.py` ... `test_rls_cip_views.py` etc. (9 RLS test files) | `tests/migrations/test_rls_cip_*.py` | v2 (Tim Q2 decision): RLS test files testing `cip_*` tables move to foundry-cip. Schema-and-tests live together. |
| `tests/migrations/conftest.py` | `tests/migrations/conftest.py` | The fixtures these RLS tests depend on (TENANT_A/B, `cip_rls_test_role`, session_as_tenant). Moves with the RLS tests. |

**Does NOT go (stays in monorepo):**

| Path | Why it stays |
|---|---|
| `docs/subsystems/integration/CONTRACT.md` | Foundry-side architecture contract — references CIP via D-118 but doesn't BE CIP |
| `docs/subsystems/knowledge/CONTRACT.md` + `graph/CONTRACT.md` + `storage/CONTRACT.md` | Foundry-side subsystem contracts CIP consumes |
| Future REST/MCP surfaces (`/cip/query`, `/cip/search`, `/cip/files`, `foundry_mcp_cip_*`) | Phase 4 deliverables — Foundry-monorepo-hosted services that CALL foundry-cip |
| `infrastructure/governance_registry.yaml` (D-118 + D-133/134/135 entries) | Monorepo's governance registry — references CIP but isn't CIP |
| PM scopes for CIP / CIPWAY / CIPRR | PM system is monorepo-side |
| Knowledge ingestion, Pinecone+FalkorDB infrastructure | Knowledge subsystem stays in monorepo (D-119 — CIP CONSUMES Knowledge subsystem, doesn't OWN it) |
| Foundry-Agent-System's Alembic chain entries (everything not `cip_*`) | These chain together independently of CIP |

**Brand-new in foundry-cip (not extracted, created fresh):**

- `pyproject.toml` — Python package metadata, declares `cip` as the importable package
- `LICENSE` — Apache 2.0
- `CONTRIBUTING.md`
- `CLAUDE.md` (foundry-cip-shaped, NOT a copy of monorepo's)
- `alembic.ini` — Alembic config pointing at `migrations/`
- `.gitignore`
- `.github/workflows/test.yml` — CI: pytest + mypy + alembic-upgrade-head against postgres:16-alpine
- `cip/__init__.py` (empty package init)
- `cip/integration_mesh/__init__.py` (empty — M2 work fills this)
- `tests/__init__.py` (empty)

### 0.3 The build-in-Foundry-then-export-per-venture pattern

Tim's framing (2026-04-27 turn): "we could build in foundry, then export out to ventures later? so things would be earmarked per venture?"

This is the future-state intent. The extraction itself doesn't deliver this — it sets up the conditions:

1. **Today (right after extraction):** foundry-cip ships the framework only. No connectors yet. M2 builds `cip/integration_mesh/` inside foundry-cip per the M2 v4 plan.
2. **M3 ships FixtureConnector** in foundry-cip — generic, not venture-specific. Likely lands at `cip/connectors/fixture/` or similar (M3 plan will firm up the location).
3. **Phase 2 ships Zendesk + HubSpot connectors** — these are generic enough that any venture could use them. They live in foundry-cip's `cip/connectors/` directory (proposed structure — M3 architecture decision).
4. **Phase 2+ venture-specific connectors** — when Wayward needs a Zendesk-customization that no other venture shares, that customization lives in `venture-wayward/` repo, NOT in foundry-cip. Wayward's repo imports foundry-cip and writes its own `WaywardZendeskConnector(ZendeskConnector)` subclass.
5. **Phase 8 export-per-venture** — when a venture graduates to its own deployment, any venture-specific code that landed in foundry-cip first (because we built before the venture had its own repo) can be `git filter-repo`'d out into the venture repo. This plan does NOT prescribe that mechanism — it's a Phase 8 concern.

**This extraction's posture on the pattern:** make foundry-cip's directory structure forward-compatible with `cip/connectors/<connector_name>/` but don't pre-create any connector folders. M3's plan will lock the connector-folder convention at the moment we have the first concrete connector to put there.

### 0.4 Approach: multi-path `git filter-repo`

JOS used `git filter-repo --subdirectory-filter operating-systems/jordan-operating-system` — single-source-directory case. CIP is multi-source: docs under `products/client-intelligence-platform/`, 8 migrations under `migrations/versions/`, 10+ runbook docs under `docs/cip/`, and the 9 RLS test files + conftest under `tests/migrations/`.

The full command:

```bash
git filter-repo \
  --path products/client-intelligence-platform/ \
  --path docs/cip/ \
  --path migrations/versions/cip_01_clients.py \
  --path migrations/versions/cip_02_views.py \
  --path migrations/versions/cip_03_sync_runs.py \
  --path migrations/versions/cip_04_files.py \
  --path migrations/versions/cip_05_contacts.py \
  --path migrations/versions/cip_06_companies.py \
  --path migrations/versions/cip_07_deals.py \
  --path migrations/versions/cip_08_tickets_and_registry.py \
  --path tests/migrations/test_rls_cip_clients.py \
  --path tests/migrations/test_rls_cip_views.py \
  --path tests/migrations/test_rls_cip_sync_runs.py \
  --path tests/migrations/test_rls_cip_files.py \
  --path tests/migrations/test_rls_cip_contacts.py \
  --path tests/migrations/test_rls_cip_companies.py \
  --path tests/migrations/test_rls_cip_deals.py \
  --path tests/migrations/test_rls_cip_tickets.py \
  --path tests/migrations/test_rls_cip_connector_property_registry.py \
  --path tests/migrations/conftest.py
```

(`--path-glob` was considered but explicit-path is auditable, fail-loud on missing files, and the count is small.)

**v2 note:** Pre-flight (§1.X) enumerates the actual filenames in `tests/migrations/test_rls_cip_*.py` at execution time and dynamically builds the path list. The 9 names listed above are the expected set — if the grep at execution time finds different names, the path list updates accordingly.

**v4 note (Senior CONC-11) — why filter-repo, not greenfield-with-cherry-pick:** A "greenfield repo with hand-cherry-picked salient commits" approach was considered and rejected for two reasons. (a) The WORKBENCH→products rename (2026-04-20) ALREADY truncates pre-rename history because filter-repo can't follow the rename across the path-set; the post-rename window is the only meaningful diff anyway, so filter-repo's history-preservation cost is real but contained. (b) M2 framework code starts landing in foundry-cip with full history starting at extraction; the pre-extraction window is read-only architectural history that doesn't need active editorship — filter-repo gives us provenance for "where did this file come from?" queries without requiring greenfield discipline. The greenfield alternative remains viable if a future security review finds blob-orphan concerns; right now the §4.1 secrets scan + the §2.2 large-blob audit cover the same surface.

After filter-repo, the extracted repo will have these top-level directories:

```
products/client-intelligence-platform/   # need to rename → top-level docs/ (per v2 Q5)
migrations/versions/                      # cip_*.py files
docs/cip/                                 # need to merge into top-level docs/ (per v2 Q5)
tests/migrations/                         # 9 RLS test files + conftest.py
```

§3 covers the post-extraction reorganization.

**v2 (Q4 decision):** `git filter-repo --path` does not preserve history across the WORKBENCH→products rename that landed 2026-04-20. CIP history pre-2026-04-20 (when the docs lived under `WORKBENCH/tim/research/client-intelligence-platform/`) is truncated in foundry-cip. This is documented in `CIP-EXTRACTION-NOTE.md` (§6.1) and the trade-off is explicitly accepted — the monorepo retains pre-rename history, anyone needing it has the `cip-extraction-point` tag as the reference point.

### 0.5 Repo target

`Foundry-Studio/foundry-cip` (matching `Foundry-Studio/jordan-operating-system` naming).

**v2 visibility (Q7 decision):** **Private at extraction. Flip to public after §7 validation passes.** This adds ~5 minutes to the timeline but gives a safety pause: any history error or missed-secret remains private during the validation window. After §7 confirms a clean extraction (CI green, no orphan refs, alembic upgrade head succeeds), we flip with `gh repo edit Foundry-Studio/foundry-cip --visibility public`. Public is the steady state — ventures need readable URLs for `pip install`.

JOS shipped this same pattern (private extraction, then public — except Tim has not flipped JOS to public yet, separate decision). For CIP the public-flip is part of this plan's acceptance.

### 0.6 Scope discipline — what this plan does and does not include

**In scope:**
- Repo creation, multi-path filter-repo extraction, post-extraction reorganization
- Reference fixes inside foundry-cip
- pyproject.toml + alembic.ini + LICENSE + CONTRIBUTING + foundry-cip CLAUDE.md
- Pre-push validation (secrets, large blobs, alembic-upgrade-head dry-run)
- Push to GitHub
- Foundry-side updates: CIP-EXTRACTION-NOTE.md stub, delete extracted paths, sweep references in CLAUDE.md / FOUNDRY-TAXONOMY.md / MANIFEST.md / governance_registry / .foundry-classify / scripts
- Both-repo validation
- Venture-onboarding documentation set (the doc stubs Tim asked for)
- PM updates
- Edge case catalog + rollback procedure + acceptance criteria
- `extract-cip.sh` automation script
- Claude Code handoff briefing

**Out of scope:**
- M2 framework code build (that's M2 plan v5 work, executes IN foundry-cip after this extraction lands)
- Connector implementations (M3 + Phase 2)
- LLM Roster integration (M5 — and the Roster's own extraction is in flight separately)
- Data-layer extraction to dedicated Postgres (Phase 8)
- REST/MCP consumption surfaces (Phase 4 — stays in Foundry monorepo)
- Charter-sync foundation (JOS had this; foundry-cip is a product repo not a doctrine repo, no charter-sync needed)
- Knowledge subsystem coupling (M5 wires this — out of extraction scope; gap-analyst's G-93 noted but deferred)

**v2 additions to in-scope (per Q1, Q2, Q3, Q6):**
- Rewrite `pmmg01_backfill_comments_actor.py`'s `down_revision` to `async_03_agents_cols` (new step in §6.3)
- Move 9 RLS test files + their `conftest.py` to foundry-cip (added to §0.2 inventory; sweep verified in §6)
- Configure foundry-cip's `migrations/env.py` with `version_table = "alembic_version_cip"` (separate from monorepo's `alembic_version`); §3.10 + §6.3
- Lock D-152 in monorepo's `docs/DECISION-LOG.md` documenting the extraction (new §6.X)

---

## 1. Pre-Flight Checks

### 1.1 Verify Phase 1 M0 documentation suite is complete

Phase 1 M0 ships 10 documentation artifacts (Tenant Onboarding Checklist, Connector Authoring Guide, etc. — see ROADMAP.md "Phase 1 — What ships — documentation"). Verify they exist before extraction:

```bash
cd /path/to/Foundry-Agent-System
ls docs/cip/ | wc -l   # expect ≥10 .md files
```

If any of the 10 are missing, **STOP**: complete M0 first. Extraction without the runbooks defeats the purpose (foundry-cip ships incomplete).

**Acceptance:** all 10 expected files present in `docs/cip/`. List them in the output of the pre-flight script.

### 1.2 Verify monorepo working tree is clean

```bash
git status
git stash list
```

Both must show empty / no relevant entries. If there are uncommitted changes or CIP-related stashes, **STOP**: the extraction operates on the committed state. Commit, stash-with-no-CIP-touch, or discard changes first.

### 1.3 Verify M2 plan v5 is locked

Plan version is the M2 framework spec foundry-cip will execute against post-extraction. Verify:

```bash
grep -E "^version:" WORKBENCH/tim/cip-m2-deep-plan.md
# expect: version: v5
```

If less than v5, the plan has not been through the latest panel rounds (Round-4 LLM panel + D-133 amendment). Stop and finish the plan first. (As of 2026-04-29 the plan is at v5 — this check is a forward guard.)

Additionally verify the D-133 amendment landed in DECISION-LOG.md:

```bash
grep -A 2 "Amendment (2026-04-29)" docs/DECISION-LOG.md
# expect: a heading "**Amendment (2026-04-29) — `KnowledgeText.metadata` becomes a TypedDict**" under D-133
```

If the amendment hasn't landed: the M2 plan v5 is referencing a decision lock that doesn't exist in DECISION-LOG.md yet. Stop and land the amendment first.

### 1.4 Install `git-filter-repo`

```bash
# macOS:
brew install git-filter-repo

# Linux / pip:
pip install git-filter-repo

# Verify:
git filter-repo --version
# expect: git filter-repo 2.x.x or later
```

`git-filter-repo` is the modern replacement for `git filter-branch` (which is deprecated and dangerous). The `git` project itself recommends it.

### 1.5 Authenticate `gh` CLI

```bash
gh auth status
# expect: "Logged in to github.com as <user>"
```

If not authenticated: `gh auth login` and follow the browser flow. The extraction script uses `gh` to create the target repo; it won't run unauthenticated.

### 1.5b Verify Python version

```bash
python --version | grep -E "Python 3\.(11|12)" || { echo "Need Python 3.11 or 3.12"; exit 1; }
```

Foundry-cip targets 3.11+ (per pyproject.toml). The extraction script + Alembic preflight need a compatible Python.

### 1.5c Verify the pre-generated artifacts directory exists (v4.2 — Verifier HIGH-F)

The authoritative artifact list is enforced by `extract-cip.sh §1.5c REQUIRED_ARTIFACTS` (the script's array is the canonical source of truth). The list below mirrors it for plan-reader convenience; if the two ever drift, the script wins.

```bash
ARTIFACTS=/path/to/Foundry-Agent-System/WORKBENCH/tim/cip-extraction-artifacts
test -d "$ARTIFACTS" || { echo "Pre-generated artifacts missing — see plan §A and Appendix B"; exit 1; }

# Required artifacts (script copies these into the extracted repo):
for f in extract-cip.sh update-foundry.sh rollback-extraction.sh \
         templates/LICENSE templates/NOTICE templates/SECURITY.md \
         templates/CLAUDE.md templates/CONTRIBUTING.md templates/CHANGELOG.md \
         templates/CIP-EXTRACTION-NOTE.md templates/_RESERVED.md \
         templates/pyproject.toml templates/alembic.ini \
         templates/migrations-env.py templates/script.py.mako \
         templates/cip-db.py \
         templates/conftest.py templates/preflight_alembic.py \
         templates/.gitignore templates/.gitattributes \
         templates/.github/workflows/test.yml \
         templates/.github/workflows/codeql.yml \
         templates/.github/dependabot.yml \
         templates/.github/CODEOWNERS \
         templates/.github/PULL_REQUEST_TEMPLATE.md \
         templates/.github/ISSUE_TEMPLATE/bug.md \
         templates/.github/ISSUE_TEMPLATE/feature.md \
         templates/.github/ISSUE_TEMPLATE/connector-proposal.md \
         templates/runbook-stubs/DEPLOYING-FOUNDRY-CIP-FOR-A-NEW-VENTURE.md \
         templates/runbook-stubs/EXPORTING-VENTURE-CONNECTORS.md \
         templates/runbook-stubs/STANDALONE-INTEGRATION-GUIDE.md \
         templates/runbook-stubs/TROUBLESHOOTING-AND-INCIDENT-RESPONSE.md; do
    test -f "$ARTIFACTS/$f" || { echo "MISSING: $ARTIFACTS/$f"; exit 1; }
done
echo "All artifacts present."
```

**v4.2 additions vs v4 list:** `rollback-extraction.sh` (Round-6 BLOCKER 4), `templates/NOTICE` (v4 Gap GAP-19), `templates/script.py.mako` (v4 Gap GAP-02), `templates/cip-db.py` (v3+v5.2 module CLI), `templates/conftest.py` (v2 — was missing from v4 list), 3 ISSUE_TEMPLATE files (v2 — were missing from v4 list). Removed: `templates/cip-cli.py` (v5.2 Call B retired; replaced by `python -m cip.db`).

If any are missing: STOP. Atlas writes them via the `cip-extraction-artifacts/` build that ships alongside this plan (see Appendix B for content).

### 1.5d Enumerate the actual runbook + RLS-test filenames

The path-set for the filter-repo command in §0.4 references explicit filenames. Verify they match what's on disk RIGHT NOW:

```bash
echo "=== runbook docs ==="
ls docs/cip/*.md

echo "=== cip_* migrations ==="
ls migrations/versions/cip_*.py

echo "=== RLS test files ==="
ls tests/migrations/test_rls_cip_*.py
ls tests/migrations/conftest.py
```

If counts or names don't match the §0.4 expected set: update the §0.4 path-list before extraction.

### 1.6 Verify the cip_01 migration chain pre-condition

This is the only migration with a non-CIP `down_revision`. Verify it before proceeding:

```bash
grep "^down_revision" migrations/versions/cip_01_clients.py
# expect: down_revision: Union[str, Sequence[str], None] = "async_03_agents_cols"
```

This is the chain's only foreign edge into Foundry's monorepo Alembic graph. The extraction rewrites this to `None` post-filter-repo (§3.4). The rewrite is mechanical; this pre-flight check just confirms the source state matches what the rewrite expects.

```bash
for f in migrations/versions/cip_0[2-8]*.py; do
    echo "=== $f ==="
    grep "^down_revision" "$f"
done
# expect each to chain to the previous cip_*: cip_02→cip_01, cip_03→cip_02, ..., cip_08→cip_07
```

If any cip_0[2-8] migration has a `down_revision` other than the previous cip_* migration, **STOP**: the chain has been modified since this plan was written. Re-verify and update §3.4 before proceeding.

### 1.6b Verify the symmetric monorepo chain dependency

A separate concern: any monorepo migration that chains ON cip_08 (downstream of CIP) will also break in the monorepo when cip_08 is deleted in §6.2. Pre-check:

```bash
# Find any monorepo migration whose down_revision points at any cip_*
grep -lE 'down_revision.*=.*"cip_0' migrations/versions/*.py | grep -v '^migrations/versions/cip_'
```

**Expected as of plan-authoring (2026-04-27):** `migrations/versions/pmmg01_backfill_comments_actor.py` (whose `down_revision = "cip_08_tickets_and_registry"`). Plan §6.3 rewrites this to `async_03_agents_cols` (cip_01's old parent), so the monorepo chain skips the now-extracted CIP segment.

If the grep returns ADDITIONAL files: each of them needs its own §6.3-style rewrite. Update §6.3 with the full list before proceeding.

### 1.5e Verify disk space (v4 — Gap GAP-05)

```bash
FREE_GB=$(df -k /tmp | awk 'NR==2 {print int($4/1024/1024)}')
[ "${FREE_GB}" -ge 2 ] || { echo "Need ≥2GB free in /tmp; have ${FREE_GB}GB"; exit 1; }
```

`git filter-repo` on a fresh clone + dry-run clone consumes roughly 2× the monorepo size in /tmp. The extract-cip.sh script enforces this gate; documenting here so manual operators see it too.

### 1.5f Verify Docker daemon is running (v4 — Gap GAP-06)

```bash
docker info >/dev/null 2>&1 || { echo "Docker daemon not reachable"; exit 1; }
```

`preflight_alembic.py` runs Postgres in a testcontainer; without Docker the §4 pre-push validation fails noisily mid-run. Catch it pre-flight.

### 1.5g Verify GitHub repo name is available (v4 — Gap GAP-07)

```bash
gh api "repos/Foundry-Studio/foundry-cip" >/dev/null 2>&1 && {
  echo "Foundry-Studio/foundry-cip already exists on GitHub. Pick a different name or delete first.";
  exit 1;
}
```

Avoids hitting `gh repo create` halfway through extraction only to fail with a name-collision.

### 1.5h Full-history secrets scan on SOURCE monorepo (v5.2 — Round-6 BLOCKER 1)

**Critical correction to v4 reasoning:** The 2026-04-20 WORKBENCH→products rename does NOT truncate history — renames change tree pointers but blob objects remain in the object database. Pre-rename secrets in any non-CIP file still exist in the monorepo's reachable history and could leak via `git filter-repo` if reachable refs (tags, branches) point at those commits. v5.2 adds an explicit full-history scan on the SOURCE monorepo BEFORE filter-repo runs.

```bash
# Install gitleaks if missing
which gitleaks >/dev/null 2>&1 || {
  echo "  gitleaks not found. Install via: brew install gitleaks  OR  go install github.com/gitleaks/gitleaks/v8@latest"
  exit 1
}

# Scan ENTIRE source monorepo history (all branches, all tags, all reflogs)
# from a fresh clone, NOT the working tree.
SOURCE_SCAN_DIR=/tmp/foundry-agent-system-secrets-scan
rm -rf "${SOURCE_SCAN_DIR}"
git clone --mirror https://github.com/Foundry-Studio/Foundry-Agent-System.git "${SOURCE_SCAN_DIR}"

# Mirror clone has full history including tags + branches; scan it
gitleaks detect --source "${SOURCE_SCAN_DIR}" --redact --report-format json --report-path /tmp/source-monorepo-leaks.json --log-opts "--all" || {
  echo "  ABORT: gitleaks found leaks in SOURCE monorepo history."
  echo "  Report: /tmp/source-monorepo-leaks.json"
  echo ""
  echo "  Pre-rotate any leaked secrets BEFORE proceeding with extraction."
  echo "  (filter-repo carries the reachable-blob universe; orphan blobs containing"
  echo "  pre-rename secrets WILL survive into the new repo unless gc'd post-extraction.)"
  exit 1
}

# Cleanup
rm -rf "${SOURCE_SCAN_DIR}"
echo "  Source monorepo full-history secrets scan: PASS"
```

**Acceptance:** gitleaks exit code 0 against the mirror clone. No JSON report findings.

**If findings exist:** rotate the secret(s) in the relevant systems FIRST (revoke API keys, change passwords). The leak is already public to anyone with read access to the monorepo. Filter-repo extraction does NOT make this worse — but it also doesn't fix it. Address the actual leak.

**Citation:** [gitleaks documentation](https://github.com/gitleaks/gitleaks). Also valid: TruffleHog (`trufflehog git file:///path/to/mirror --only-verified`).

### 1.6c Verify CRLF / line-ending state of cip_*.py files

```bash
# git tracks .py as text by default; line endings on disk should match what git stores.
# But if anyone committed via a CRLF editor and the .gitattributes weren't strict, the file
# may have CR-LF on disk. The §3.4 sed_i edit on cip_01 will fail silently if the line
# endings are unexpected. Catch it now:
file migrations/versions/cip_01_clients.py
# expect: "Python script, ASCII text" (NOT "with CRLF line terminators")
```

If the file shows CRLF: add `dos2unix migrations/versions/cip_01_clients.py` before the sed_i call in §3.4. Same for any other migration the script edits.

### 1.7 Coordinate the freeze window

While the extraction runs (Steps 2–5 take ~30 minutes; Steps 6–9 take another ~30), no one else commits to:
- Anything under `products/client-intelligence-platform/`
- Anything under `docs/cip/`
- Any `migrations/versions/cip_*.py`
- `CLAUDE.md`, `FOUNDRY-TAXONOMY.md`, `infrastructure/governance_registry.yaml`, `MANIFEST.md`

Coordination: post in inboxes (`tims-inbox.md`, `vans-inbox.md`) before starting, AND check no recent commits touch those paths.

```bash
git log --since="2 hours ago" --oneline -- \
    products/client-intelligence-platform/ \
    docs/cip/ \
    migrations/versions/cip_*.py \
    CLAUDE.md FOUNDRY-TAXONOMY.md \
    infrastructure/governance_registry.yaml \
    MANIFEST.md
```

If any commits land within the last 2 hours, escalate to the committer (Tim or Van) and confirm no in-flight work conflicts.

### 1.8 Create the GitHub target repo (private at extraction)

```bash
gh repo create Foundry-Studio/foundry-cip \
    --private \
    --description "Foundry Client Intelligence Platform — generic connector framework + tenant-partitioned data layer." \
    --homepage "https://github.com/Foundry-Studio/foundry-cip"
```

**v2 (Q7 + F-3 fixes):**
- `--private` — private at extraction; flip to public after §7 validation passes (per Q7).
- Dropped `--license=apache-2.0` — that flag creates an initial commit on the GitHub repo, which would conflict with our `git push` from the filter-repo'd local. We ship LICENSE via the extraction's bootstrap commit instead.
- Dropped `--add-readme=false` — `gh` doesn't add a README by default unless `--license` or `--gitignore` is set. With those flags removed the repo is born empty, ready for our push.

Set topic tags after creation (discoverability):

```bash
gh repo edit Foundry-Studio/foundry-cip \
    --add-topic client-intelligence \
    --add-topic data-platform \
    --add-topic alembic \
    --add-topic sqlalchemy \
    --add-topic postgres \
    --add-topic scd-type-2 \
    --add-topic multi-tenant \
    --add-topic rls \
    --add-topic connector-framework \
    --enable-issues \
    --enable-wiki=false \
    --enable-discussions=false
```

Verify:
```bash
gh repo view Foundry-Studio/foundry-cip
```

Should show: empty (no commits, no README, no LICENSE), private, topics set, wiki/discussions off, issues on.

If the repo already exists from a prior aborted attempt: **STOP** and confirm with Tim before deleting+recreating. Even a private repo deletion is logged on the GitHub org audit trail.

### 1.9 Tag the split point in the monorepo

After all pre-flight passes, tag the current `master` commit so the extraction is reproducible:

```bash
cd Foundry-Agent-System
git tag cip-extraction-point
git push origin cip-extraction-point
```

This tag mirrors `jos-extraction-point` from the JOS extraction. It marks the last monorepo commit before CIP code was carved out. The `git filter-repo` step in §2 operates on this tag's content. If the extraction needs to be re-run (deterministically), this tag is the reference.

---

## 2. Extract CIP Into New Repo

### 2.1 Fresh clone for extraction

`git filter-repo` REWRITES history. It must run on a fresh clone, never on a working copy you also use for development.

```bash
WORKDIR=/tmp/foundry-cip-extraction
rm -rf "$WORKDIR"
git clone https://github.com/Foundry-Studio/Foundry-Agent-System.git "$WORKDIR"
cd "$WORKDIR"
git checkout cip-extraction-point   # the tag from §1.9
```

### 2.2 Dry-run extraction (throwaway clone)

Before destroying real history, do a dry-run on a separate throwaway clone to verify the path-filter set is correct.

```bash
DRYDIR=/tmp/foundry-cip-dryrun
rm -rf "$DRYDIR"
git clone https://github.com/Foundry-Studio/Foundry-Agent-System.git "$DRYDIR"
cd "$DRYDIR"
git checkout cip-extraction-point

git filter-repo \
  --path products/client-intelligence-platform/ \
  --path docs/cip/ \
  --path migrations/versions/cip_01_clients.py \
  --path migrations/versions/cip_02_views.py \
  --path migrations/versions/cip_03_sync_runs.py \
  --path migrations/versions/cip_04_files.py \
  --path migrations/versions/cip_05_contacts.py \
  --path migrations/versions/cip_06_companies.py \
  --path migrations/versions/cip_07_deals.py \
  --path migrations/versions/cip_08_tickets_and_registry.py
```

**Verification queries:**

```bash
# File count after filter — should be the union of the matched paths
find . -type f -not -path './.git/*' | wc -l

# Confirm only the expected top-level directories survive
ls -d */ 2>/dev/null

# Confirm the 8 migration files survive
ls migrations/versions/cip_*.py | wc -l   # expect 8

# Confirm vision docs survive
ls products/client-intelligence-platform/vision/*.md | wc -l   # expect 5

# Confirm cip runbook docs survive
ls docs/cip/*.md | wc -l   # expect ≥10

# History should still exist on the surviving files
git log --oneline -- products/client-intelligence-platform/vision/VISION.md | head -5
```

Expected: ≥3 commits per surviving file (the file's full editing history). If history is missing, the `--path` set is wrong.

**Large blob audit:**
```bash
git rev-list --objects --all | \
  git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | \
  awk '$1 == "blob" && $3 > 500000' | sort -k3 -n -r | head -20
```

CIP doesn't have known large blobs, but verify nothing >500KB survives. If anything large exists (a stray PDF, an old CSV), evaluate whether to drop it via `git filter-repo --strip-blobs-bigger-than 500K` in the real extraction.

**Cleanup:**
```bash
cd /tmp && rm -rf "$DRYDIR"
```

**ESCALATE:** If any of the above counts are wrong, do NOT proceed. Diagnose the path-set mismatch first.

### 2.3 Run the real extraction

```bash
cd "$WORKDIR"   # the fresh clone from §2.1, NOT the dryrun

git filter-repo \
  --path products/client-intelligence-platform/ \
  --path docs/cip/ \
  --path migrations/versions/cip_01_clients.py \
  --path migrations/versions/cip_02_views.py \
  --path migrations/versions/cip_03_sync_runs.py \
  --path migrations/versions/cip_04_files.py \
  --path migrations/versions/cip_05_contacts.py \
  --path migrations/versions/cip_06_companies.py \
  --path migrations/versions/cip_07_deals.py \
  --path migrations/versions/cip_08_tickets_and_registry.py
```

Same command as the dry-run. `git filter-repo` is deterministic — same inputs produce same SHAs.

### 2.4 Verify extracted content integrity

Re-run the verification queries from §2.2 against the real extraction. Counts must match.

Additional integrity checks:

```bash
# Every surviving cip_*.py migration should have its full history
for f in migrations/versions/cip_*.py; do
    echo "=== $f ==="
    git log --oneline -- "$f" | wc -l
done
# expect: each line ≥1 (every file has ≥1 commit; most will have more)

# Confirm VISION.md history is intact
git log --follow --oneline -- products/client-intelligence-platform/vision/VISION.md | head -10

# Confirm the original `master` HEAD's tree is gone (extraction worked)
git log --oneline | head -5
```

The git log should show only commits that touched CIP-relevant paths. No "feat(pm-system): add task scheduler" commits should survive (those touched only PM, not CIP).

---

## 3. Reorganize and Fix Internal References

After §2, the extracted repo has the monorepo's nesting (`products/client-intelligence-platform/...`, `docs/cip/...`, `migrations/versions/cip_*.py`). Now make it a foundry-cip-shaped repo: top-level docs, top-level migrations, sensible structure.

### 3.0 Portable `sed_i` (used by §3.4, §6.4, §6.5)

Bash sed differs between macOS (BSD) and Linux (GNU). To make this plan run cleanly on either, scripts use a `sed_i` shim:

```bash
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed_i() { sed -i '' "$@"; }
else
  sed_i() { sed -i "$@"; }
fi
```

The `extract-cip.sh` script (Appendix A) defines this once at top. Manual `sed -i ...` invocations elsewhere in this plan are placeholders for `sed_i ...`.

### 3.1 Move products/client-intelligence-platform/ contents to top-level

```bash
cd "$WORKDIR"

# Move everything from products/client-intelligence-platform/ to top level + docs/
git mv products/client-intelligence-platform/vision docs/vision
git mv products/client-intelligence-platform/architecture docs/architecture
git mv products/client-intelligence-platform/notes docs/notes
git mv products/client-intelligence-platform/research docs/research
git mv products/client-intelligence-platform/archive docs/archive

# README.md and CLAUDE.md go to top-level (CLAUDE.md will be replaced in §3.6)
git mv products/client-intelligence-platform/README.md README.md
git mv products/client-intelligence-platform/CLAUDE.md docs/legacy-CLAUDE.md
# (we replace it; saving the old as legacy-CLAUDE.md in case it has content we want to reference)

# Remove the now-empty products/ tree
rmdir products/client-intelligence-platform
rmdir products
```

### 3.2 Merge docs/cip/* into top-level docs/ (v2 — drop docs/ rename)

**v2 (Q5 decision):** runbooks stay at top-level `docs/`, NOT in a `docs/` subfolder. M2 plan v5 hardcodes paths like `docs/CONNECTOR-AUTHORING-GUIDE.md` (same as v4 — v5 didn't reshape doc paths). Aligning the extraction with M2 v5 avoids cross-plan drift.

```bash
# Move each runbook from docs/cip/ to docs/
for f in docs/cip/*.md; do
    git mv "$f" "docs/$(basename "$f")"
done

# Remove the now-empty docs/cip/
rmdir docs/cip
```

After this step, `docs/` contains:
- `vision/` (subfolder, from §3.1)
- `architecture/` (subfolder, from §3.1)
- `notes/` (subfolder, from §3.1)
- `research/` (subfolder, from §3.1)
- `archive/` (subfolder, from §3.1)
- `legacy-CLAUDE.md` (from §3.1)
- The 10+ runbook .md files at top level (from this step) — no `runbooks/` subfolder.

### 3.3 Verify the post-reorg layout

```bash
tree -L 2 -d
# expect:
# .
# ├── docs
# │   ├── archive
# │   ├── architecture
# │   ├── notes
# │   ├── research
# │   └── vision
# ├── migrations
# │   └── versions
# └── tests
#     └── migrations
```

(v2: `docs/` is gone — runbooks live at top-level `docs/` per Q5. Plus `tests/migrations/` shows up because of the 9 RLS test files moved per Q2.)

Top-level docs files:
```bash
ls docs/*.md
# expect:
# docs/legacy-CLAUDE.md
# docs/CONNECTOR-AUTHORING-GUIDE.md
# docs/LENS-AUTHORING-GUIDE.md
# docs/MIGRATION-RUNBOOK.md
# docs/RLS-OPERATOR-GUIDE.md
# docs/SYNC-ORCHESTRATOR-GUIDE.md
# docs/FOUR-ACCESS-PATHS-REFERENCE.md
# docs/FIXTURE-TENANT-HANDBOOK.md
# docs/CIP-CSS-CLASSIFICATION-CONTRACT.md
# docs/PHASE-1-TO-PHASE-2-HANDOFF.md
# docs/TENANT-ONBOARDING-CHECKLIST.md
# docs/_TEMPLATE.md   (frontmatter template if present in monorepo)
```

If any directory is missing or unexpected, diagnose. Likely cause: the move set in §3.1 / §3.2 didn't match actual paths, OR the actual filenames diverged from the expected list (§1.5d should have caught this).

### 3.4 Rewrite cip_01's `down_revision` to `None`

This is the only migration-internal edit. cip_01_clients.py's `down_revision = "async_03_agents_cols"` points to a Foundry-monorepo migration that doesn't exist in foundry-cip. Foundry-cip's Alembic chain needs cip_01 as the root.

```bash
# Pre-fix: ensure file is LF-terminated (catches the §1.6c CRLF case)
dos2unix migrations/versions/cip_01_clients.py 2>/dev/null || true

# Edit migrations/versions/cip_01_clients.py
# Replace:
#   down_revision: Union[str, Sequence[str], None] = "async_03_agents_cols"
# With:
#   down_revision: Union[str, Sequence[str], None] = None
sed_i 's|down_revision: Union\[str, Sequence\[str\], None\] = "async_03_agents_cols"|down_revision: Union[str, Sequence[str], None] = None|' \
    migrations/versions/cip_01_clients.py
```

Also update the docstring's "Revises:" line to reflect the new state:

```bash
sed_i 's|^Revises: async_03_agents_cols, infra_disks_01, pm_06|Revises: None (foundry-cip alembic chain root)|' \
    migrations/versions/cip_01_clients.py
```

**Verify (mechanical):**
```bash
grep -E "^(down_revision|Revises:)" migrations/versions/cip_01_clients.py
# expect:
#   Revises: None (foundry-cip alembic chain root)
#   down_revision: Union[str, Sequence[str], None] = None
```

**Verify (Python syntax preserved — v2 addition per F-116):**
```bash
python -c "import ast; ast.parse(open('migrations/versions/cip_01_clients.py').read())"
# expect: silent success. ANY error means sed corrupted the file (e.g., a malformed sed
# pattern leaked across line boundaries). STOP and inspect.
```

**Verify (lint passes — v2 addition per G-39):**
```bash
# If foundry-cip ships a lint_migration.py, run it now. Otherwise:
python -m alembic check 2>&1 | head -20
# expect: any error shouldn't cite cip_01 specifically.
```

This is a textual edit only — no functional change to what cip_01 creates.

Commit this rewrite as a discrete commit (so the diff is auditable):

```bash
git add migrations/versions/cip_01_clients.py
git commit -m "extraction: rewrite cip_01 down_revision to None (foundry-cip alembic root)

The original points to async_03_agents_cols, a Foundry-monorepo migration
that doesn't exist in this repo. cip_01 becomes the root of foundry-cip's
own alembic chain.

This is a textual edit — cip_01's table creation logic is unchanged."
```

### 3.5 Create `pyproject.toml`

```bash
cat > pyproject.toml <<'EOF'
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "foundry-cip"
version = "0.1.0"
description = "Foundry Client Intelligence Platform — generic connector framework + tenant-partitioned data layer."
readme = "README.md"
requires-python = ">=3.11"
license = { file = "LICENSE" }
authors = [{ name = "Foundry Studio", email = "tim@foundry-studio.com" }]
keywords = ["client-intelligence", "data-platform", "connector-framework", "scd-type-2"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Database",
    "Topic :: Software Development :: Libraries :: Python Modules",
]
dependencies = [
    "sqlalchemy>=2.0,<3.0",
    "alembic>=1.13,<2.0",
    "psycopg[binary]>=3.1,<4.0",   # Postgres driver — pure python + binary
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.0",
    "mypy>=1.8",
    "testcontainers[postgres]>=4.0",
    "ruff>=0.4",
]

[project.urls]
Homepage = "https://github.com/Foundry-Studio/foundry-cip"
Documentation = "https://github.com/Foundry-Studio/foundry-cip/tree/master/docs"
Repository = "https://github.com/Foundry-Studio/foundry-cip"
Issues = "https://github.com/Foundry-Studio/foundry-cip/issues"

[tool.setuptools]
packages = ["cip", "cip.integration_mesh"]

[tool.setuptools.package-data]
"cip" = ["py.typed"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_unreachable = true
warn_unused_configs = true
disallow_untyped_defs = true

[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
addopts = ["-v", "--strict-markers", "--strict-config"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM"]
ignore = []
EOF
```

Note on dependencies:
- **No LLM Roster dependency** — per the 2026-04-27 framing, LLM Roster is becoming its own standalone service. M5 work will add a service-call client to whatever shape LLM Roster lands in. Extraction-time foundry-cip has no llm_roster references.
- **No FastAPI / web framework** — REST surfaces ship from the Foundry monorepo, not foundry-cip.
- **psycopg3 (`psycopg[binary]`)** matches Foundry's existing usage (`src/db/session.py` uses `postgresql+psycopg://`).

### 3.6 Create foundry-cip `CLAUDE.md`

```markdown
---
kind: contract
domain: client-intelligence-platform
---

# Foundry Client Intelligence Platform — foundry-cip

This is the standalone repo for **CIP**, Foundry's tenant-partitioned client intelligence platform. The framework code, schema migrations, and operating documentation all live here. Foundry-Agent-System (the monorepo) consumes foundry-cip via `pip install foundry-cip` and runs the migrations against its shared Postgres.

## What this repo is

- A Python library: `from cip.integration_mesh import CIPConnector, CIPMapper, run_sync`.
- A schema definition: 8 Alembic migrations creating the `cip_*` tables and SCD-type-2 history tables.
- A documentation set: vision, architecture, runbooks (TENANT-ONBOARDING-CHECKLIST, CONNECTOR-AUTHORING-GUIDE, etc.).

## What this repo is not

- Not a service. CIP runs in the caller's process via the orchestrator's `run_sync` function.
- Not a deployment. Foundry-Agent-System (or any consumer) handles deployment.
- Not the consumption surfaces. Metabase, REST API, MCP tools, chatbot — those live in Foundry-Agent-System.

## Orient

1. Read `README.md` (top-level).
2. Read `docs/vision/VISION.md` for the WHAT.
3. Read `docs/architecture/ARCHITECTURE.md` for the HOW.
4. Read `docs/vision/ROADMAP.md` for sequencing.
5. If shipping new framework code: read the M2 plan (the v5 `cip-m2-deep-plan.md` lives in the source-monorepo's WORKBENCH; once M2 ships, the plan archives to this repo's `docs/archive/`).
6. If shipping a connector: read `docs/CONNECTOR-AUTHORING-GUIDE.md`.

## Rules (inherited from Foundry but stated here for clarity)

- All timestamps UTC. All UUIDs v4.
- Every database query MUST include tenant_id scoping (D-026).
- All LLM calls go through the LLM Roster (D-018/D-031/D-077). M2 ships no LLM calls; M5 wires the Roster.
- Master branch only. No branches, no PRs (Foundry convention).
- Tests run against `postgres:16-alpine` via `testcontainers-python`. RLS tests require real Postgres; SQLite is not supported.

## Decisions that govern this repo

D-118 (CIP framework lives in Integration Mesh), D-122 (CSS tag ownership), D-123 (Alembic schema authority), D-126 (non-SQL schema governance), D-133 (KnowledgeText return type), D-134 (Protocol-based connector framework), D-135 (app-layer SCD Type 2). Full text in the source-monorepo's `docs/DECISION-LOG.md`. As of 2026-04-27, foundry-cip does not maintain its own DECISION-LOG; governance authority remains in Foundry-Agent-System.

## Repo Layout

```
foundry-cip/
├── cip/                          # The Python package (importable as `cip`)
│   ├── __init__.py
│   └── integration_mesh/         # M2 framework — Protocol + orchestrator + persister + ...
├── docs/
│   ├── vision/                   # VISION, ROADMAP, PHASE-1-PLAN, PHASE-1-PLAIN-SPEC, PHASE-2.5-PLAN
│   ├── architecture/             # ARCHITECTURE.md (Phase 0 data model, scaling, extraction story)
│   ├── runbooks/                 # 10 Phase 1 documentation artifacts
│   ├── notes/                    # Initial braindump, vision-discussion log
│   ├── research/                 # industry-landscape.md
│   └── archive/                  # Superseded stage docs from monorepo era
├── migrations/
│   └── versions/                 # 8 Alembic migrations: cip_01..cip_08
├── tests/                        # Test suite (M2 work fills this)
├── alembic.ini
├── pyproject.toml
├── LICENSE                       # Apache 2.0
├── README.md
├── CONTRIBUTING.md
└── CLAUDE.md                     # This file
```

## Commands

```bash
# Install (editable for dev):
pip install -e ".[dev]"

# Run migrations against a Postgres:
alembic upgrade head

# Run tests:
pytest

# Type-check:
mypy cip/

# Lint:
ruff check cip/ tests/
```
```

Save as `CLAUDE.md` at the repo root:

```bash
cat > CLAUDE.md <<'EOF'
[paste the markdown above]
EOF
```

(The `extract-cip.sh` automation script in Appendix A inlines the full template.)

### 3.7 Create `LICENSE` (Apache 2.0)

```bash
# Use the standard Apache 2.0 text. JOS shipped a copy at
# WORKBENCH/tim/phase8-artifacts/LICENSE — reuse it.
cp /path/to/Foundry-Agent-System/WORKBENCH/tim/phase8-artifacts/LICENSE LICENSE

# Verify:
head -5 LICENSE
# expect: "                                 Apache License" / "                           Version 2.0, January 2004"
```

### 3.8 Create `CONTRIBUTING.md`

```markdown
# Contributing to foundry-cip

This repo is part of [Foundry Studio](https://github.com/Foundry-Studio). It governs the Client Intelligence Platform — a generic connector framework + tenant-partitioned data layer.

## How to contribute

### Bug reports + feature requests

Open an issue. Include:
- What you tried
- What you expected
- What actually happened
- The version of foundry-cip + Python + Postgres
- A minimal reproduction if possible

### Pull requests

Foundry's working convention is master-branch development inside controlled environments — pull requests from external contributors are accepted but reviewed against the same governance bar applied internally:

1. Run the test suite locally — `pytest` against a real Postgres (testcontainers handles this).
2. Confirm `mypy cip/` passes (strict mode).
3. Confirm `ruff check cip/ tests/` passes.
4. New migrations need a corresponding revision in the Alembic chain — see `docs/MIGRATION-RUNBOOK.md`.
5. Connector contributions follow `docs/CONNECTOR-AUTHORING-GUIDE.md` — every connector implements the `CIPConnector` Protocol + ships a conformance-harness pass.

### Decision authority

Architectural decisions affecting this repo land in the source-monorepo's `docs/DECISION-LOG.md` (D-numbers). foundry-cip implements; it does not author governance. If your contribution would require a new D-number, open an issue first and we'll route to the source-monorepo for decision authoring.

## Code of conduct

Be useful, be specific, be kind. Disagreement is welcome; condescension is not.

## Ownership

Maintainer: Tim Jordan ([Foundry Studio](https://github.com/Foundry-Studio)).
Contact: tim@foundry-studio.com.
```

### 3.9 Create `alembic.ini`

```bash
cat > alembic.ini <<'EOF'
# foundry-cip Alembic configuration

[alembic]
script_location = migrations
prepend_sys_path = .
version_path_separator = os
output_encoding = utf-8

# DATABASE_URL is read from environment in env.py — not hardcoded here.
# Set DATABASE_URL=postgresql+psycopg://user:pw@host:5432/db

[post_write_hooks]
# (none for now; ruff format could go here later)

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
EOF
```

### 3.10 Create `migrations/env.py` (Alembic env)

The Alembic chain in foundry-cip needs an `env.py` to drive migrations. Copy the monorepo's pattern (without the monorepo-specific bits):

```python
# migrations/env.py
"""Alembic environment configuration for foundry-cip."""
from __future__ import annotations
import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
fileConfig(config.config_file_name)

# foundry-cip doesn't bundle ORM models — migrations are explicit op.create_table().
# target_metadata stays None.
target_metadata = None


def get_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set — alembic requires a Postgres connection string. "
            "Example: postgresql+psycopg://user:pw@host:5432/db"
        )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    context.configure(url=get_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config_dict = config.get_section(config.config_ini_section)
    config_dict["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(config_dict, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # NOTE: foundry-cip RLS policies use SET LOCAL app.current_tenant per-transaction.
        # Migrations bypass RLS by running as the schema-owner role; see Phase-2.5 plan.
        #
        # v2 (Q3 decision): version_table = "alembic_version_cip" — foundry-cip and
        # Foundry-Agent-System share Foundry's Postgres until Phase 8 (data-layer
        # extraction). Two repos × default `alembic_version` table = chain conflicts.
        # foundry-cip uses its OWN version table; the monorepo keeps the default.
        # Each repo's `alembic upgrade head` is independent.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=True,
            version_table="alembic_version_cip",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Save as `migrations/env.py`.

Also create `migrations/script.py.mako` (the standard Alembic template — copy from the monorepo unchanged):

```bash
cp /path/to/Foundry-Agent-System/migrations/script.py.mako migrations/script.py.mako
```

### 3.11 Create `.gitignore`

```bash
cat > .gitignore <<'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# Virtual environments
.venv/
venv/
ENV/
env/

# Testing
.pytest_cache/
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Local secrets / env files
.env
.env.local

# Build artifacts
*.log
EOF
```

### 3.12 Create the empty `cip/` and `cip/integration_mesh/` package init files

```bash
mkdir -p cip/integration_mesh
touch cip/__init__.py
touch cip/integration_mesh/__init__.py
touch cip/py.typed   # PEP 561 marker — signals to mypy that this package has type hints

# Sanity:
python -c "import sys; sys.path.insert(0, '.'); import cip; import cip.integration_mesh; print('OK')"
```

The `cip/integration_mesh/` directory is intentionally empty — M2 work fills it per `cip-m2-deep-plan.md` v5. Creating the empty namespace now means `import cip.integration_mesh` doesn't raise after extraction (a forward courtesy to M2 execution).

### 3.13 Create `tests/__init__.py` and `tests/conftest.py` stub

```bash
mkdir -p tests
touch tests/__init__.py

cat > tests/conftest.py <<'EOF'
# foundry: kind=test domain=client-intelligence-platform
"""Top-level pytest fixtures for foundry-cip.

M2 work expands this with the connector_conformance harness fixtures.
For now: a no-op placeholder so `pytest` runs without errors in an empty repo.
"""
from __future__ import annotations
EOF
```

### 3.14 Create `.github/workflows/test.yml`

```bash
mkdir -p .github/workflows
cat > .github/workflows/test.yml <<'EOF'
name: test
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: foundry_cip_test
        options: >-
          --health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5
        ports:
          - 5432:5432
    env:
      DATABASE_URL: postgresql+psycopg://postgres:postgres@localhost:5432/foundry_cip_test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Install
        run: pip install -e ".[dev]"
      - name: Alembic upgrade head
        run: alembic upgrade head
      - name: pytest
        run: pytest -v
      - name: mypy
        run: mypy cip/
      - name: ruff
        run: ruff check cip/ tests/
EOF
```

### 3.15 Stage and commit the reorganization

```bash
cd "$WORKDIR"
git add -A
git status   # review
git commit -m "scaffold: foundry-cip standalone-repo bootstrap

Created post-extraction:
  - pyproject.toml (foundry-cip package metadata, deps, mypy/pytest/ruff config)
  - LICENSE (Apache 2.0)
  - CLAUDE.md (foundry-cip-shaped, replaces monorepo's product-CLAUDE.md)
  - CONTRIBUTING.md
  - alembic.ini + migrations/env.py + migrations/script.py.mako
  - .gitignore
  - .github/workflows/test.yml (CI: pytest + mypy + ruff against postgres:16-alpine)
  - cip/ + cip/integration_mesh/ empty package namespaces (M2 fills these)
  - tests/conftest.py stub

Path moves:
  - products/client-intelligence-platform/{vision,architecture,notes,research,archive} → docs/{vision,architecture,notes,research,archive}
  - products/client-intelligence-platform/README.md → README.md (top-level)
  - docs/cip/ → docs/

cip_01 down_revision rewrite was committed separately for auditability."
```

### 3.16 Commit hygiene check

```bash
git log --oneline | head -10
# expect 3 categories of commits:
#   1. The original monorepo commits that touched CIP (preserved by filter-repo)
#   2. The "extraction: rewrite cip_01 down_revision" commit from §3.4
#   3. The "scaffold: foundry-cip standalone-repo bootstrap" commit from §3.15
```

---

## 4. Pre-Push Validation

### 4.1 Secrets scan

```bash
# Scan the entire history (not just working tree) for secret patterns
git log --all -p | grep -iE \
    "AKIA[0-9A-Z]{16}|sk-[a-zA-Z0-9]{40,}|ghp_[a-zA-Z0-9]{36,}|password\s*[:=]\s*['\"][^'\"]{8,}|api[_-]?key\s*[:=]\s*['\"][^'\"]{16,}" \
    | head -50
```

If any matches: STOP. The history needs a re-extraction with `git filter-repo --replace-text` to redact the secret, OR if the secret is truly in CIP-touched files (unlikely), the extraction needs to drop those files via `--invert-paths --path <bad-file>`.

CIP doesn't have known secret-bearing files. This scan should return zero matches. If it returns false positives (e.g., a docstring example with a fake API key), evaluate each manually.

### 4.2 Large blob audit (re-run after reorg)

```bash
git rev-list --objects --all | \
  git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | \
  awk '$1 == "blob" && $3 > 500000' | sort -k3 -n -r | head -20
```

Expect zero matches (CIP has no known large files). If anything appears: evaluate dropping via `git filter-repo --strip-blobs-bigger-than 500K`.

### 4.3 Alembic upgrade dry-run via testcontainer

This is the make-or-break check: foundry-cip's Alembic chain must apply cleanly to an empty Postgres.

```python
# /tmp/foundry-cip-extraction/scripts/preflight_alembic.py
"""Pre-push alembic dry-run against an ephemeral Postgres testcontainer."""
import os
import subprocess
from testcontainers.postgres import PostgresContainer


def main() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url()
        # testcontainers returns postgresql+psycopg2 — convert to psycopg3
        url = url.replace("postgresql+psycopg2://", "postgresql+psycopg://")
        os.environ["DATABASE_URL"] = url

        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print("ALEMBIC FAILED:")
            print(result.stdout)
            print(result.stderr)
            raise SystemExit(1)
        print(result.stdout)
        print("alembic upgrade head: OK")

        # Verify all 8 cip_* tables + their _history siblings exist
        from sqlalchemy import create_engine, text
        engine = create_engine(url)
        with engine.begin() as conn:
            tables = conn.execute(text(
                "SELECT tablename FROM pg_tables WHERE tablename LIKE 'cip_%' ORDER BY tablename"
            )).all()
            names = [r[0] for r in tables]
            print(f"\ncip_* tables created ({len(names)}):")
            for n in names:
                print(f"  {n}")
        # Expect 7 entity tables + 7 _history + cip_sync_runs + cip_connector_property_registry
        # = 16 total (cip_clients, cip_clients_history, cip_views, cip_views_history,
        #             cip_sync_runs, cip_files, cip_files_history,
        #             cip_contacts, cip_contacts_history,
        #             cip_companies, cip_companies_history,
        #             cip_deals, cip_deals_history,
        #             cip_tickets, cip_tickets_history,
        #             cip_connector_property_registry)
        assert len(names) == 16, f"Expected 16 cip_* tables, got {len(names)}: {names}"


if __name__ == "__main__":
    main()
```

Run it:

```bash
cd "$WORKDIR"
pip install -e ".[dev]"   # installs alembic, testcontainers, sqlalchemy, psycopg
python scripts/preflight_alembic.py
```

If this fails: STOP. The down_revision rewrite (§3.4) failed, OR a migration has a hidden monorepo dependency, OR the `migrations/env.py` is wrong. Diagnose before pushing.

### 4.4 Ruff + mypy sweep on the (empty) cip/ package

```bash
mypy cip/   # expect: "Success: no issues found in N source files"
ruff check cip/ tests/   # expect: "All checks passed!"
```

These should pass trivially since `cip/` is just empty `__init__.py` files at this stage. If they fail: the conftest.py stub or pyproject.toml config has an issue.

### 4.5 Final-commit-graph review

```bash
git log --oneline --all | wc -l
# expect: ≥30 (the union of CIP-touching commits + scaffold commits)

git log --oneline --all --graph | head -40
# expect: linear-ish history; no orphan branches
```

---

## 5. Push to GitHub

```bash
cd "$WORKDIR"

# Add the remote (gh repo create from §1.8 already created it; we just need to point at it)
git remote add origin https://github.com/Foundry-Studio/foundry-cip.git

# Push master + the cip-extraction-point tag (we'll re-tag inside foundry-cip if needed)
git push -u origin master

# Verify on GitHub
gh repo view Foundry-Studio/foundry-cip --web
```

If push fails with "remote has commits": the repo was not created empty (e.g., a README was added during `gh repo create`). Either delete-and-recreate the repo, OR `git push --force` after Tim's explicit confirmation (force-push to a fresh repo is safe; force-push to a populated repo is not).

---

## 6. Update Foundry-Agent-System (Source Side)

Now that foundry-cip exists on GitHub, update the source monorepo to (a) remove the extracted paths, (b) leave a stub note, (c) update internal references, (d) repair the Alembic chain.

### 6.1 Create `products/client-intelligence-platform/CIP-EXTRACTION-NOTE.md`

After deleting the CIP code from monorepo, leave a small stub at `products/client-intelligence-platform/CIP-EXTRACTION-NOTE.md` (mirroring `operating-systems/JOS-EXTRACTION-NOTE.md`):

```markdown
# CIP Extraction Reference

This file documents the extraction of CIP from the Foundry-Agent-System
monorepo into a standalone repository.

- **Extraction date:** YYYY-MM-DD
- **Split point tag:** `cip-extraction-point` (in this repo)
- **Source paths:**
  - `products/client-intelligence-platform/`
  - `docs/cip/`
  - `migrations/versions/cip_01_clients.py` … `cip_08_tickets_and_registry.py`
- **Target repo:** `Foundry-Studio/foundry-cip`
- **Tool used:** `git filter-repo --path ...` (multi-path)
- **Note:** Commit SHAs in foundry-cip differ from this monorepo due to filter-repo's history rewrite. Extraction is deterministic — running the same command on `cip-extraction-point` produces identical results.

## Where to find CIP now

- Code, docs, migrations: https://github.com/Foundry-Studio/foundry-cip
- Subsystem contracts that REFERENCE CIP (D-118 etc.): unchanged in this monorepo at `docs/subsystems/integration/CONTRACT.md` etc.
- PM scopes for CIP / CIPWAY / CIPRR: unchanged in this monorepo's PM system.
- D-118, D-122, D-123, D-126, D-133, D-134, D-135 (governance): unchanged in `docs/DECISION-LOG.md`.

## Why CIP code moved out (but governance stayed in)

CIP graduates to a standalone repo so ventures can `pip install foundry-cip` without dragging the full monorepo. Foundry-Agent-System still consumes foundry-cip as a dependency. Decision authority for CIP-affecting changes remains with this monorepo's DECISION-LOG; foundry-cip implements decisions, doesn't author them.

## SHA mapping

There is no 1:1 SHA mapping. To find the monorepo equivalent of a foundry-cip commit:

```bash
# In foundry-cip:
git log --oneline <foundry-cip-sha>

# In this monorepo (at or before cip-extraction-point):
git log --all --oneline --grep="<commit message snippet>" -- \
  products/client-intelligence-platform/ docs/cip/ migrations/versions/cip_*.py
```
```

### 6.2 Delete the extracted paths from monorepo

```bash
cd /path/to/Foundry-Agent-System

# Remove products/client-intelligence-platform/ — except CIP-EXTRACTION-NOTE.md (just created above)
git rm -r products/client-intelligence-platform/vision/
git rm -r products/client-intelligence-platform/architecture/
git rm -r products/client-intelligence-platform/notes/
git rm -r products/client-intelligence-platform/research/
git rm -r products/client-intelligence-platform/archive/
git rm products/client-intelligence-platform/CLAUDE.md
git rm products/client-intelligence-platform/README.md
# CIP-EXTRACTION-NOTE.md from §6.1 stays

# Remove docs/cip/
git rm -r docs/cip/

# Remove the 8 cip_* migrations
git rm migrations/versions/cip_01_clients.py
git rm migrations/versions/cip_02_views.py
git rm migrations/versions/cip_03_sync_runs.py
git rm migrations/versions/cip_04_files.py
git rm migrations/versions/cip_05_contacts.py
git rm migrations/versions/cip_06_companies.py
git rm migrations/versions/cip_07_deals.py
git rm migrations/versions/cip_08_tickets_and_registry.py

# v4.2 (Verifier HIGH-D 2026-04-29): also delete the 9 RLS test files +
# conftest. Per §0.2 v2 Tim Q2 decision: schema-and-tests-live-together —
# they move WITH the migrations to foundry-cip.
git rm tests/migrations/test_rls_cip_clients.py
git rm tests/migrations/test_rls_cip_views.py
git rm tests/migrations/test_rls_cip_sync_runs.py
git rm tests/migrations/test_rls_cip_files.py
git rm tests/migrations/test_rls_cip_contacts.py
git rm tests/migrations/test_rls_cip_companies.py
git rm tests/migrations/test_rls_cip_deals.py
git rm tests/migrations/test_rls_cip_tickets.py
git rm tests/migrations/test_rls_cip_connector_property_registry.py
git rm tests/migrations/conftest.py
```

**Note:** §6.10 Commit 2 batches §6.2 + §6.3 atomically (per v4.1 Verifier HIGH fix). The git rm sequence above is described separately for clarity but executes in a single atomic commit.

### 6.3 Repair monorepo's Alembic chain (v2 — Q1 decision)

**v2 (Q1 confirmed):** Pre-flight §1.6b identified `pmmg01_backfill_comments_actor.py` as the one downstream of cip_08. That file's `down_revision` is rewritten to `async_03_agents_cols` (cip_01's old parent) so the monorepo chain skips the now-extracted CIP segment cleanly:

```bash
# Pre-fix: handle CRLF
dos2unix migrations/versions/pmmg01_backfill_comments_actor.py 2>/dev/null || true

# Rewrite the down_revision
sed_i 's|down_revision.*=.*"cip_08_tickets_and_registry"|down_revision: Union[str, Sequence[str], None] = "async_03_agents_cols"|' \
    migrations/versions/pmmg01_backfill_comments_actor.py

# Update the "Revises:" docstring line if present
sed_i 's|^Revises: cip_08_tickets_and_registry|Revises: async_03_agents_cols (cip_* extracted to foundry-cip per D-152)|' \
    migrations/versions/pmmg01_backfill_comments_actor.py
```

**Verify:**
```bash
grep -E "^(down_revision|Revises:)" migrations/versions/pmmg01_backfill_comments_actor.py
# expect:
#   Revises: async_03_agents_cols (cip_* extracted to foundry-cip per D-152)
#   down_revision: Union[str, Sequence[str], None] = "async_03_agents_cols"

# Python syntax preserved
python -c "import ast; ast.parse(open('migrations/versions/pmmg01_backfill_comments_actor.py').read())"
```

**Sweep for any OTHER monorepo migration that chains on cip_*:**
```bash
grep -lE 'down_revision.*=.*"cip_0' migrations/versions/*.py | grep -v '^migrations/versions/cip_'
# After the pmmg01 fix above, expect: zero matches.
# If still non-empty, repeat the rewrite for each. Update plan with the new file list.
```

**Handle merge migrations (per Stress F-118):** Foundry uses occasional multi-parent merge revisions (e.g., `2026_04_21_1635-10affb36121c_merge_pmmg01_pm_10_approvals_heads.py`). Verify none have a `cip_*` parent:

```bash
grep -lE 'down_revision\s*=\s*\(' migrations/versions/*.py | xargs grep -l "cip_0" 2>/dev/null
# expect: zero matches. If a merge-rev cites cip_* as one of multiple parents, the rewrite is
# more delicate — needs careful editing of the tuple, not a simple sed.
```

**Existing alembic_version state (per Gap G-36):** Production Foundry Postgres already has alembic_version row pointing at HEAD (likely `pmmg01_backfill_comments_actor` or later). After the §6.3 rewrite, that revision_id still resolves — `pmmg01_backfill_comments_actor` is still a known revision in monorepo's chain, just re-parented. No alembic_version row update needed.

**Snippets for monorepo's CI:**
```bash
alembic check          # expect: no errors after §6.10 push
alembic heads          # expect: a single head, NOT cip_*
alembic history --verbose | head -20   # expect: linear chain, no cip_* entries
```

### 6.4 Update CLAUDE.md (monorepo)

```bash
# In the monorepo's CLAUDE.md "Repo Structure" section, the CIP entry currently reads:
#   ├── products/                    FOUNDRY PRODUCTS
#   │   ├── client-intelligence-platform/ (Product #6)
# Update to reflect that CIP code now lives in foundry-cip.
```

Specific find-and-replace in `CLAUDE.md`:

```bash
sed_i 's|client-intelligence-platform/ (Product #6)|client-intelligence-platform/ (Product #6 — CODE EXTRACTED to https://github.com/Foundry-Studio/foundry-cip; only CIP-EXTRACTION-NOTE.md remains)|' CLAUDE.md
```

Plus a section near the top of CLAUDE.md noting that several products now live as separate repos:

```markdown
## Externalized Products (consumed via separate repos)

- **JOS** (Jordan Operating System) — `Foundry-Studio/jordan-operating-system`. Consumed via `.jos/charter.yaml`. See `operating-systems/JOS-EXTRACTION-NOTE.md`.
- **CIP** (Client Intelligence Platform) — `Foundry-Studio/foundry-cip`. Consumed via `pip install foundry-cip`. See `products/client-intelligence-platform/CIP-EXTRACTION-NOTE.md`.

When the monorepo references CIP types or invokes CIP framework code, use:
```python
from cip.integration_mesh import CIPConnector, CIPMapper, run_sync, KnowledgeText
```
```

### 6.5 Update FOUNDRY-TAXONOMY.md

CIP is Product #6 in the taxonomy. Update its entry to note that the code lives in foundry-cip:

```markdown
### Product #6 — Client Intelligence Platform (CIP)

**Repo:** `Foundry-Studio/foundry-cip` (code, schema, docs).
**Consumes:** Knowledge subsystem (Pinecone+FalkorDB), Storage subsystem (R2), Integration subsystem.
**Consumed by:** Phase 4+ REST/MCP surfaces (in this monorepo); Phase 5 chatbot (`products/foundry-chatbot/`); ventures via `pip install foundry-cip`.
**Status:** Phase 1 in flight (M2 framework being built post-extraction).
```

### 6.6 Update infrastructure/governance_registry.yaml

D-118, D-133, D-134, D-135 entries reference CIP file paths in the monorepo. They need updating:

```bash
grep -nE "cip/integration_mesh|products/client-intelligence-platform" \
    infrastructure/governance_registry.yaml
```

For each match, decide:
- If it's a file-path reference to extracted code → update to point at foundry-cip's GitHub URL or remove (these are now external dependencies)
- If it's a conceptual reference (e.g., "framework lives in Integration Mesh subsystem") → leave unchanged

### 6.7 Update .foundry-classify.yaml

If `.foundry-classify.yaml` (or `infrastructure/conventions.yaml`) maps the deleted paths, update or remove those entries.

```bash
grep -nE "cip/|client-intelligence-platform|cip_0" infrastructure/conventions.yaml infrastructure/*.yaml 2>/dev/null
```

### 6.8 Sweep scripts that reference CIP paths

```bash
grep -rEln "cip/integration_mesh|products/client-intelligence-platform|migrations/versions/cip_0" scripts/ 2>/dev/null
```

For each script: either update path references, OR add a check at script-start that skips when run against the post-extraction monorepo.

### 6.8b Sweep additional documentation drift (v2 — Gaps G-19 through G-24)

```bash
# 1. products/foundry-chatbot/README.md references CIP paths (lines 60-62 cite ROADMAP/VISION/CHATBOT-ARCHITECTURE)
grep -nE "products/client-intelligence-platform" products/foundry-chatbot/README.md
# Update each reference to: https://github.com/Foundry-Studio/foundry-cip/blob/master/docs/<path>

# 2. WORKBENCH ventures
grep -nE "products/client-intelligence-platform" \
    WORKBENCH/tim/ventures/wayward/cip-onboarding/README.md \
    WORKBENCH/tim/ventures/rocky-ridge/cip-onboarding/README.md 2>/dev/null
# Same fix.

# 3. inboxes
grep -n "products/client-intelligence-platform" internal-tooling/inboxes/vans-inbox.md
# Same fix where applicable. Tim's inbox: similar grep.

# 4. Subsystem CONTRACT.md files
grep -nE "ARCHITECTURE.md|cip/integration_mesh|products/client-intelligence-platform" \
    docs/subsystems/integration/CONTRACT.md \
    docs/subsystems/knowledge/CONTRACT.md \
    docs/subsystems/graph/CONTRACT.md \
    docs/subsystems/storage/CONTRACT.md
# Update each to point at the foundry-cip GitHub URL.

# 5. DECISION-LOG.md — D-118, D-119, D-120, D-133, D-134, D-135 reference moved paths
grep -nE "cip/integration_mesh|products/client-intelligence-platform" docs/DECISION-LOG.md
# For each "Affects:" line referencing a moved path, append "(now in foundry-cip)" annotation.
```

For each match, update with the new external URL: `https://github.com/Foundry-Studio/foundry-cip/blob/master/docs/<path>`.

### 6.8c Add foundry-cip pip dependency to monorepo (v4 — FND-S13 compliance)

**v4 fix (Stress Tester S5-1):** Foundry's monorepo follows FND-S13 dependency-pinning discipline. `requirements.txt` is a `uv pip compile`-generated lockfile and **must NEVER be hand-edited**. The source-of-truth file is `requirements.in`. Hand-editing `requirements.txt` violates governance and the next `uv pip compile` will revert the change.

**v4 fix (Verifier mismatch #20):** Monorepo `pyproject.toml` has NO `[project]` section. It exists for pytest/ruff config only — packaging is via `requirements.in` / `requirements.txt`. **The foundry-cip pin lives in requirements.in/.txt EXCLUSIVELY.** Do NOT add a `[project.dependencies]` block to monorepo `pyproject.toml` — that would be a packaging-architecture change beyond extraction scope.

The correct flow:

```bash
# Step 1: Add the pin to requirements.in (NOT requirements.txt; NOT pyproject.toml)
echo "foundry-cip @ git+https://github.com/Foundry-Studio/foundry-cip.git@${FOUNDRY_CIP_SHA}" >> requirements.in

# Step 2: Recompile the lockfile via uv
uv pip compile requirements.in -o requirements.txt --python-version 3.11

# Step 3: Verify the pin landed in BOTH files
grep -q 'foundry-cip @ git' requirements.in
grep -q 'foundry-cip @ git' requirements.txt
```

Both files commit together per FND-S13 contract. The `update-foundry.sh` script enforces this via grep gates BEFORE the commit step; an operator who hand-edits requirements.txt and skips the .in file will fail the gate.

(The `${FOUNDRY_CIP_SHA}` is filled at execution time from `git rev-parse HEAD` inside the foundry-cip working tree after §5.)

**Note:** Until foundry-cip's M2 framework code lands (post-extraction work), this dep installs an empty package. That's fine — it reserves the import path. Monorepo code that needs to USE foundry-cip waits for M2 to ship.

### 6.9 Regenerate MANIFEST.md

The monorepo's MANIFEST.md is auto-generated; CIP entries now stale. Regenerate:

```bash
python scripts/generate_manifest.py --write
```

Verify `MANIFEST.md` no longer lists `products/client-intelligence-platform/vision/...`, `docs/cip/...`, `migrations/versions/cip_*.py`.

### 6.9b Add D-152 to DECISION-LOG.md (v2 — Q6 decision)

The extraction is itself a structural decision worthy of a D-number. Per `docs/operations/HOW-TO-ADD-A-DECISION.md`, append to `docs/DECISION-LOG.md`:

```markdown
### D-152: CIP Code Lives in `foundry-cip`; Monorepo Consumes via pip

**Date:** 2026-04-27
**Status:** LOCKED
**Decided By:** Tim Jordan
**Relates to:** D-118 (CIP framework in Integration Mesh), D-122 (Domain ownership via CSS), D-123 (Schema authority via Alembic).

**Context:** CIP grew inside `Foundry-Agent-System` from initial WORKBENCH-stage research to a Phase-1 product with locked decisions D-118 / D-119 / D-120 / D-121 / D-122 / D-133 / D-134 / D-135 and 8 schema migrations. Phase 2+ ventures (Wayward, Rocky Ridge, future) need to write `CIPConnector` subclasses against the Protocol contract. While CIP code lives inside the monorepo, ventures' connector repos can't `pip install` it without dragging the entire monorepo. JOS shipped 2026-04-25 with the same constraint and was solved via `git filter-repo` extraction.

**Decision:** CIP code, schema migrations, and operating documentation extract from `Foundry-Agent-System` to a standalone `Foundry-Studio/foundry-cip` repo. Foundry-Agent-System consumes foundry-cip via `pip install foundry-cip` (git+SHA-pinned in pyproject.toml until v1.0.0). Foundry-cip's Alembic chain uses a SEPARATE `version_table` (`alembic_version_cip`) so the two repos run `alembic upgrade head` against the SHARED Foundry Postgres without colliding. Data layer (cip_* tables in dedicated Postgres) extraction is deferred to Phase 8 ("Scale & Extract") per the existing CIP architecture commitment.

**Rationale:**
1. **Cross-repo connector portability.** Ventures install foundry-cip standalone; no monorepo coupling.
2. **JOS pattern proof.** Same extraction shape worked 2026-04-25 (single-subdirectory variant); CIP uses a multi-path filter-repo (a small extension).
3. **Sets up Phase 8 at low cost.** When data layer extracts to dedicated Postgres, code is already standalone-shaped; only connection-string change required.
4. **Code-only-now / data-later phasing.** Avoids the cross-repo Postgres operational complexity until scale demands it.

**Rejected alternatives:**
- **Keep CIP in monorepo, ship a thin extracted "interface" repo for ventures to import.** Rejected — adds maintenance overhead with two repos containing CIP shape.
- **Defer extraction until Phase 8.** Rejected — ventures already need CIP for Phase 2 (Wayward); waiting blocks the venture portability story.
- **Single shared `alembic_version` table.** Rejected — chain conflicts when two repos try to `upgrade head` against same DB.

**Implementing standard:** STD-13 (Postgres schema authority via Alembic). Plus ad-hoc: foundry-cip's pyproject.toml + alembic.ini + env.py concretely realize the shape.

**Affects:**
- `Foundry-Studio/foundry-cip` repo (new, public after §7 validation per Q7 decision)
- `Foundry-Agent-System` monorepo: removes CIP source paths, adds CIP-EXTRACTION-NOTE.md stub, pins foundry-cip in pyproject.toml/requirements
- `infrastructure/governance_registry.yaml` — D-152 registered
- `cip-extraction-point` git tag (immutable reference for re-running the extraction deterministically)

**Verification:** Plan §12 acceptance criteria. Both repos pass their respective `alembic upgrade head` + CI runs. Monorepo's `alembic check` succeeds. Foundry-cip's `pip install -e ".[dev]"` + `pytest` + `mypy cip/` all succeed.

**See also:** D-118 (framework home), D-123 (schema authority), JOS extraction pattern (`operating-systems/JOS-EXTRACTION-NOTE.md`), `WORKBENCH/tim/cip-extraction-plan.md` (this plan).
```

Also register D-152 in `infrastructure/governance_registry.yaml`:

```yaml
  # ── D-152 CIP code in foundry-cip (locked 2026-04-27) ─────────────
  - id: D-152
    type: decision
    title: "CIP Code Lives in foundry-cip; Monorepo Consumes via pip"
    description: "CIP framework, schema migrations, and runbooks extract from Foundry-Agent-System monorepo to Foundry-Studio/foundry-cip standalone repo. Monorepo consumes via pip-installable package (git+SHA-pinned). Separate alembic_version table per repo so `alembic upgrade head` from each repo coexists in the shared Foundry Postgres. Phase 8 will later move cip_* data to dedicated Postgres; code is already standalone-shaped for that future move."
    scope: [client-intelligence-platform, integration, meta]
    source: docs/DECISION-LOG.md
    decision: D-152
    status: active
```

### 6.10 Commit Foundry-side changes (v4.2 — atomic-commit + Conventional Commits + FND-S13 lockfile)

**v4.2 update (Verifier HIGH-C 2026-04-29):** the previous v2 plan body described 6 separate commits including a final `git add pyproject.toml requirements*.txt`. Both are now WRONG — v4.1 collapsed §6.3+§6.2 into one atomic commit (test_sk08_migration would otherwise fail in the transient multi-head window) and v4.1 also dropped pyproject.toml from the pin step (monorepo pyproject.toml has no [project] section per Verifier mismatch #20). Authoritative sequence below.

```bash
git status   # review

# Commit 1 — CIP-EXTRACTION-NOTE.md stub
git add products/client-intelligence-platform/CIP-EXTRACTION-NOTE.md
git commit -m "extraction: add CIP-EXTRACTION-NOTE stub (D-152)"

# Commit 2 — ATOMIC: pmmg01 down_revision rewrite + ALL CIP source deletions
# (v4.1 atomicity fix: splitting these into separate commits creates a transient
# multi-head Alembic state that fails tests/db/test_sk08_migration. v5.2 polish:
# Conventional Commits format with explicit BREAKING CHANGE footer + rollback line.)
git add migrations/versions/pmmg01_backfill_comments_actor.py
git rm -r products/client-intelligence-platform/{vision,architecture,notes,research,archive}/
git rm products/client-intelligence-platform/{CLAUDE.md,README.md}
git rm -r docs/cip/
git rm migrations/versions/cip_0{1,2,3,4,5,6,7,8}_*.py
git rm tests/migrations/test_rls_cip_*.py tests/migrations/conftest.py
git commit -m "feat(extraction)!: re-parent pmmg01 + remove CIP source paths (atomic, D-152)

CIP code now lives in https://github.com/Foundry-Studio/foundry-cip and is
consumed via pip. See D-152 in docs/DECISION-LOG.md.

BREAKING CHANGE: monorepo no longer ships CIP code or schema. Consumers
that import 'cip.integration_mesh' must depend on foundry-cip via
requirements.in.

Rollback: bash WORKBENCH/tim/cip-extraction-artifacts/rollback-extraction.sh"

# Commit 2.5 — v5.2: source-monorepo gc to expunge deleted CIP blobs
git reflog expire --expire=now --all
git gc --prune=now --aggressive
# (gc has no commit; results in a tighter object database for security review.)

# Commit 3 — documentation drift sweep + reference updates
git add CLAUDE.md FOUNDRY-TAXONOMY.md docs/subsystems/*/CONTRACT.md docs/DECISION-LOG.md \
    products/foundry-chatbot/README.md \
    WORKBENCH/tim/ventures/wayward/cip-onboarding/README.md \
    WORKBENCH/tim/ventures/rocky-ridge/cip-onboarding/README.md \
    internal-tooling/inboxes/vans-inbox.md \
    infrastructure/governance_registry.yaml \
    .foundry-classify.yaml \
    scripts/  # any updated scripts
git commit -m "extraction: sweep CIP path references; register D-152 in governance_registry"

# Commit 4 — regenerate MANIFEST.md
python scripts/generate_manifest.py --write
git add MANIFEST.md
git commit -m "extraction: regenerate MANIFEST.md (CIP entries now external)"

# Commit 5 — FND-S13 pin: requirements.in + uv pip compile (NOT pyproject.toml)
# Per FND-S13 (Verifier mismatch #20): monorepo pyproject.toml has no [project]
# section; pin lives EXCLUSIVELY in requirements.in/.txt. Edit requirements.in,
# recompile via uv, commit BOTH together.
echo "foundry-cip @ git+https://github.com/Foundry-Studio/foundry-cip.git@${FOUNDRY_CIP_SHA}" >> requirements.in
uv pip compile requirements.in -o requirements.txt --python-version 3.11
git add requirements.in requirements.txt
git commit -m "extraction: pin foundry-cip @ git+${FOUNDRY_CIP_SHA} per D-152

Tracker: D-152 + FND-S13
- Edit requirements.in (source-of-truth)
- Recompile requirements.txt via uv pip compile (lockfile)
- Both committed together per FND-S13 contract"
```

The atomic Commit 2 keeps the Alembic chain valid on every commit on the path. Commit 5 follows FND-S13 dependency-pinning discipline. Each subsequent commit has a granular rollback window via the v5.2 idempotent `rollback-extraction.sh` (see §11.0).

**v2 (Senior reviewer): gate the push behind foundry-cip CI green check (per §7).**

```bash
# DO NOT push to origin master until §7.1 + §7.2 ALL PASS.
# §7 has explicit gate language for this.
git push origin master
```

---

## 7. Validate Both Repos

**v2 gate (G-9):** §7.1 (foundry-cip validation) MUST PASS before §6.10's monorepo `git push` is executed. Validation order is:
1. Run §7.1 fully against foundry-cip.
2. ONLY IF §7.1 passes: run §7.2 against monorepo and gate §6.10 push on §7.2 passing too.
3. ONLY IF both pass: flip foundry-cip from private to public per §5 / Q7 decision.

If §7.1 fails: rollback per §11.1 (foundry-cip-only rollback). If §7.2 fails after §7.1 succeeded: rollback per §11.2.

### 7.1 foundry-cip validation

```bash
cd "$WORKDIR"

# 1. CI passes
gh run list --repo Foundry-Studio/foundry-cip --limit 1
# expect: success on the first push

# 2. Migration set is complete
ls migrations/versions/cip_*.py | wc -l   # expect 8

# 3. Alembic upgrade head passes
DATABASE_URL=postgresql+psycopg://... alembic upgrade head   # against a fresh test DB

# 4. Documentation set is complete (v2 — top-level docs, no docs/ subfolder)
ls docs/*.md | wc -l   # expect ≥14 (10 M0 runbooks + 4 venture-onboarding stubs + _TEMPLATE.md)
ls docs/vision/*.md | wc -l   # expect 5
ls docs/architecture/*.md | wc -l   # expect ≥1

# 5. No orphan references to monorepo paths
grep -rE "products/client-intelligence-platform|/Foundry-Agent-System/" docs/ cip/ tests/ --include="*.md" --include="*.py" 2>/dev/null
# expect: zero matches (or only intentional historical citations in docs/notes/, docs/archive/)

# 6. No accidental monorepo-path references in pyproject.toml or alembic.ini
grep -E "products/|Foundry-Agent-System" pyproject.toml alembic.ini
# expect: zero matches

# 7. py.typed marker exists
test -f cip/py.typed && echo OK || echo MISSING

# 8. cip module imports cleanly
python -c "import cip; import cip.integration_mesh; print('imports OK')"

# 9. mypy + ruff pass
mypy cip/ && ruff check cip/ tests/
```

### 7.1b Flip foundry-cip from private to public (v2 — Q7)

If all of §7.1 passes:
```bash
gh repo edit Foundry-Studio/foundry-cip --visibility public --accept-visibility-change-consequences
gh repo view Foundry-Studio/foundry-cip   # verify "public" in output
```

This is the irreversible step (any errors past here are publicly visible). The §4.1 secrets scan + §4.2 large-blob audit ran BEFORE this flip; §7.1 confirmed CI passes. Flip is safe.

### 7.2 Foundry-Agent-System validation

```bash
cd /path/to/Foundry-Agent-System

# 1. No orphan references to deleted CIP paths
grep -rE "products/client-intelligence-platform/(vision|architecture|notes|research|archive)|^docs/cip/" \
    --include="*.md" --include="*.py" --include="*.yaml" \
    docs/ src/ scripts/ infrastructure/ CLAUDE.md FOUNDRY-TAXONOMY.md MANIFEST.md 2>/dev/null
# expect: zero matches (or only inside CIP-EXTRACTION-NOTE.md which intentionally cites them)

# 1b. (v2 expanded sweep per Stress F-6) Also check raw-SQL cip_* table-name references
grep -rE "(FROM|JOIN|UPDATE|INSERT INTO)\s+cip_(clients|views|sync_runs|files|contacts|companies|deals|tickets|connector_property_registry)" \
    --include="*.py" --include="*.sql" --include="*.md" \
    src/ tests/ scripts/ 2>/dev/null
# expect: zero matches (or only in tests/migrations/test_rls_cip_*.py — but those should have been
# moved per Q2; if any remain in monorepo they need cleanup).

# 2. No orphan migration references
grep -rE "cip_0[1-8]_" migrations/ scripts/ src/ 2>/dev/null
# expect: zero matches

# 3. Alembic head still valid (no orphan chain)
alembic heads   # expect: a single head, NOT cip_08
alembic check   # expect: no errors

# 4. Tests pass (no test failures from missing CIP imports)
pytest tests/ -x   # expect: all green

# 5. CSS classification check passes
python scripts/check_registry_sync.py   # expect: exit code 0

# 6. system_describe.py runs (sanity check)
python scripts/system_describe.py   # expect: completes without error, no CIP-shaped errors
```

If any validation fails: rollback per §11 and diagnose.

---

## 8. Venture-Onboarding Documentation Set

Tim's 2026-04-27 ask: "in the CIP repo, we need guides, runbooks, explainers for adding this to other ventures, etc."

The Phase 1 M0 deliverables (the 10 docs in `docs/cip/`, now `docs/` in foundry-cip) cover the operational mechanics. This section identifies the GAPS — docs that should ship with the extraction so future ventures can onboard from foundry-cip alone.

### 8.1 Inventory of existing runbooks (post-extraction, in foundry-cip)

Confirmed present from M0 delivery (verified 2026-04-26 against monorepo `docs/cip/`):

1. TENANT-ONBOARDING-CHECKLIST.md
2. CONNECTOR-AUTHORING-GUIDE.md
3. LENS-AUTHORING-GUIDE.md
4. MIGRATION-RUNBOOK.md
5. RLS-OPERATOR-GUIDE.md
6. SYNC-ORCHESTRATOR-GUIDE.md
7. FOUR-ACCESS-PATHS-REFERENCE.md
8. FIXTURE-TENANT-HANDBOOK.md
9. CIP-CSS-CLASSIFICATION-CONTRACT.md
10. PHASE-1-TO-PHASE-2-HANDOFF.md

### 8.2 Gap analysis — what's missing for full venture-onboarding self-service

The 10 above are mostly *operational* — they tell an operator/dev how to do specific tasks. They presume someone is *already* onboarding a venture and knows why. The missing layer:

| Gap | Proposed runbook |
|---|---|
| "I have a new venture. How do I get CIP working for them?" — start-to-finish playbook | `docs/DEPLOYING-FOUNDRY-CIP-FOR-A-NEW-VENTURE.md` |
| "Foundry built a connector for venture X. Now venture X has its own engineering team. How do we move that connector to their repo?" | `docs/EXPORTING-VENTURE-CONNECTORS.md` (Phase 8 prep — stub now, fill at Phase 8) |
| "I'm an external developer who wants to use foundry-cip without Foundry. What's the bare-minimum integration?" | `docs/STANDALONE-INTEGRATION-GUIDE.md` |
| "What goes wrong, what to look for, how to recover" — runbook for incident response | `docs/TROUBLESHOOTING-AND-INCIDENT-RESPONSE.md` |

### 8.3 Stub the four new runbooks at extraction time

Each gets a stub — a one-page placeholder with a clear scope statement and a "TBD" body — committed during the extraction. The stubs commit foundry-cip to producing them; the actual content fills in as the relevant phase or use case lands.

For the full stub content of each, see Appendix C.

### 8.4 Cross-reference from CLAUDE.md

In foundry-cip's `CLAUDE.md`, the "Orient" section gets the new runbooks listed:

```markdown
## Orient

1. Read `README.md` (top-level).
2. Read `docs/vision/VISION.md` for the WHAT.
3. Read `docs/architecture/ARCHITECTURE.md` for the HOW.
4. Read `docs/DEPLOYING-FOUNDRY-CIP-FOR-A-NEW-VENTURE.md` if onboarding a new venture.
5. Read `docs/CONNECTOR-AUTHORING-GUIDE.md` if shipping a connector.
6. Read `docs/TROUBLESHOOTING-AND-INCIDENT-RESPONSE.md` if something is broken.
```

### 8.5 Acceptance for §8

- All 4 new stubs exist at `docs/<name>.md`.
- Each stub has `status: stub` in its frontmatter and a TBD body.
- Each stub is referenced from at least one of: README.md, CLAUDE.md, the matching vision/phase doc.

### 8.6 Stub fill-by triggers (v2 — Senior reviewer D19)

Each stub names a CONCRETE triggering event that obligates filling it. This prevents perpetual-stub decay:

| Stub | Trigger that obligates filling |
|---|---|
| `DEPLOYING-FOUNDRY-CIP-FOR-A-NEW-VENTURE.md` | Phase 2 M3 (Wayward Tenant Provisioning) — the playbook fills out the moment the first non-fixture venture provisioning happens, since that operator IS the trial run. |
| `EXPORTING-VENTURE-CONNECTORS.md` | Phase 8 (Scale & Extract) — when the first venture graduates to its own deployment. |
| `STANDALONE-INTEGRATION-GUIDE.md` | First external (non-Foundry) consumer expresses interest, OR foundry-cip's first PyPI release (whichever is first). |
| `TROUBLESHOOTING-AND-INCIDENT-RESPONSE.md` | First Phase 2 production incident OR Phase 6 (Intelligence & Alerts), whichever first. Stub is updated incrementally as incidents accumulate. |

The frontmatter for each stub includes a `fill_when: <trigger>` field. Plan §12 acceptance criterion verifies the field exists.

---

## 9. PM System Updates

### 9.1 Mark Cowork tasks #58 + #59 complete

Once §1–§7 pass, the Cowork task list (this session's TodoWrite tracker) updates:

- #58 (Stage 2a: Create foundry-cip repo scaffolding) → completed
- #59 (Stage 2b: Move 8 CIP migrations from monorepo to foundry-cip/migrations/versions/) → completed

### 9.2 Update Foundry PM project scopes

The monorepo's PM project for CIP (`596825db-...`) has a "Stage 1-3 — Repo extraction (CIP → foundry-cip)" scope. Mark `done`:

```bash
foundry_mcp_pm_mark_scope_done \
    tenant_id=4ebafb2d-01ba-434a-ac73-ea9603e7d0bb \
    scope_id=<the stage-1-3 scope_id>
```

(Get the scope_id via `foundry_mcp_pm_project_status`.)

Add a decision comment on the project capturing the extraction:

```bash
foundry_mcp_pm_comment \
    tenant_id=4ebafb2d-01ba-434a-ac73-ea9603e7d0bb \
    project_id=596825db-61bc-4899-bc6c-e207489ca35d \
    comment_type=decision \
    body="CIP extracted to Foundry-Studio/foundry-cip on YYYY-MM-DD. Cowork tasks #58 + #59 closed. M2 execution unblocked. Plan: WORKBENCH/tim/cip-extraction-plan.md."
```

### 9.2b Atlas write-log receipt batch (v2 — Senior C15 + Gap G-87/88/89)

Per Atlas DEFAULTS §3, every durable write Atlas commits gets a receipt in `internal-tooling/atlas-state/write-log.md`. The extraction generates a batch — append all in one session-end commit:

| receipt_id (template) | tier | surface | tag | authority_basis | source_basis | diff_summary |
|---|---|---|---|---|---|---|
| `2026-04-27T<HH:MM>Z-001A` | 2b | `cip-extraction-point` git tag | `[REPO-PROPOSAL]` | Tim turn 2026-04-27: "go write the patch on the plan, then report back" | none | Tag monorepo at HEAD prior to extraction |
| `...-002A` | 2b | github.com/Foundry-Studio/foundry-cip | `[REPO-PROPOSAL]` | Tim Q7: extraction approved | none | gh repo create (private) |
| `...-003A` | 2b | foundry-cip master branch | `[REPO-PROPOSAL]` | filter-repo extraction; deterministic from cip-extraction-point | `cip-extraction-point` SHA | git filter-repo + scaffold + push |
| `...-004A` | 1 | foundry-cip migrations/versions/cip_01_clients.py | `[AUTO-COMMIT]` | DEFAULTS §3 Level 1 — mechanical sed_i edit on extraction artifact | this plan §3.4 | Rewrote down_revision to None |
| `...-005A` | 2b | monorepo migrations/versions/pmmg01_backfill_comments_actor.py | `[REPO-PROPOSAL]` | Tim Q1: re-parent to async_03_agents_cols | this plan §6.3 | Sed_i down_revision rewrite |
| `...-006A` | 2b | monorepo: products/client-intelligence-platform/, docs/cip/, migrations/versions/cip_*.py, tests/migrations/test_rls_cip_*.py | `[REPO-PROPOSAL]` | Tim Q2 + Q6: extraction approved, D-152 locks deletion | this plan §6.2 | Delete CIP source paths |
| `...-007A` | 3 | monorepo docs/DECISION-LOG.md (D-152) | `[REPO-PROPOSAL]` | Tim Q6: lock D-152 | this plan §6.9b | Append D-152 entry |
| `...-008A` | 1 | monorepo CLAUDE.md, FOUNDRY-TAXONOMY.md, MANIFEST.md | `[AUTO-COMMIT]` | DEFAULTS §3 Level 1 — mechanical sweep updates | this plan §6.4–§6.9 | Reference updates |
| `...-009A` | 2a | foundry-cip GitHub repo visibility flip private→public | `[REPO-PROPOSAL]` | Tim Q7 | §7.1 validation pass | gh repo edit --visibility public |

Append these receipts to `internal-tooling/atlas-state/write-log.md` at session end (or after each gate as a step batch).

**Receipt-id allocation:** ISO timestamp at the actual write time + monotonic 4-char suffix (`001A`, `002A`, ..., `009A`). Suffix increments per-write-within-session.

**Reverts policy:** If the extraction rolls back per §11, append new receipts for each reverted entry with `disposition: reverted` + `reverts: <original-receipt-id>`. Do not delete the original receipts.

### 9.3 Open the M2 execution scope

The "[M2] Generic Connector Framework + conformance harness" scope on the CIP project was blocked on extraction. Update its status from `todo` → `in_progress` (or whatever maps to "ready to execute"):

```bash
foundry_mcp_pm_update_scope_progress \
    tenant_id=4ebafb2d-01ba-434a-ac73-ea9603e7d0bb \
    scope_id=<the M2 scope_id> \
    status=in_progress \
    note="Extraction landed. M2 plan v5 at WORKBENCH/tim/cip-m2-deep-plan.md. Ready for Claude Code handoff."
```

---

## 10. Edge Cases and Risks

### 10.1 Sensitive data in git history

The CIP-touching files don't have a known history of credentials, but the secrets scan in §4.1 catches the surprises. Mitigation: the scan runs BEFORE push, so no sensitive blob ever lands on GitHub.

If something is found: re-run filter-repo with `--replace-text` redaction, OR drop the file with `--invert-paths --path <file>`. Both rewrite history; both are reproducible from `cip-extraction-point`.

### 10.2 Stale clones of Foundry-Agent-System

After the monorepo deletes CIP paths (§6.2), anyone with a pre-deletion clone still has the CIP files locally. They'll see them as untracked-or-deleted on next `git pull`. Communication: post the extraction completion in `tims-inbox.md` and `vans-inbox.md` once §6 lands; mention `git pull --rebase` and `pip install foundry-cip` as the new way to access CIP.

### 10.3 CI breakage in Foundry-Agent-System after extraction

Foundry's CI runs `pytest`. If any test imports from `cip.integration_mesh` or references the deleted CIP paths, it'll fail. Mitigation:

```bash
# Pre-extraction:
grep -rE "from cip\.|import cip|products/client-intelligence-platform" tests/ --include="*.py"
# expect: zero matches (CIP framework code didn't exist yet — M2 work hasn't shipped)
```

If ANY matches: those tests would be broken by the extraction. Either remove them (if they were placeholders) or update them to use foundry-cip post-publish.

### 10.4 The cip_09 reservation collision

CIP M2 v4 plan keeps `cip_09` and `cip_10` slots reserved for Phase 3 cross-tenant grants. This extraction does NOT migrate cip_09 (because cip_09 doesn't exist yet). When Phase 3 lands, cip_09 will be authored INSIDE foundry-cip (chained on cip_08). The monorepo's Alembic chain has nothing to say about cip_09 because it's been extracted.

Risk: a future Foundry-Agent-System contributor accidentally creates a `cip_09_*.py` migration in the monorepo (perhaps copy-pasting an old reference that pre-dated the extraction). Mitigation: the §6.4 CLAUDE.md update warns against creating new cip_* migrations in the monorepo; foundry-cip is the schema-authority repo for CIP per D-123.

### 10.5 M2 plan v5 path-pin alignment

The v4 plan hardcodes paths like `cip/integration_mesh/base.py`. After extraction, the foundry-cip layout has `cip/integration_mesh/` at the top level (per §3.12). v4 paths align as-is — no plan rewrite needed.

### 10.6 Foundry-cip published-version drift

Once foundry-cip is on PyPI (or installed via git+https), Foundry-Agent-System's CI pins to a specific version. If foundry-cip ships v0.2.0 with a breaking API change, the monorepo's CI will fail until the pin updates. Mitigation: pin to a specific git SHA via `pip install "foundry-cip @ git+https://github.com/Foundry-Studio/foundry-cip@<sha>"` until 1.0.0 is reached.

### 10.7 The "build in Foundry, export to ventures" path is not yet wired

§0.3 lays out the future-state pattern but doesn't deliver mechanism. Risk: assuming Phase 8 will figure it out leaves teams building in foundry-cip's `cip/connectors/` for Wayward when they should be building in `venture-wayward/`. Mitigation: M3 plan locks the connector-folder convention; until then, the default is "build in foundry-cip's connectors/ if generic; build in `venture-<name>/` if venture-specific."

### 10.8 Documentation drift between monorepo and foundry-cip

`products/client-intelligence-platform/CIP-EXTRACTION-NOTE.md` (§6.1) is a thin pointer to foundry-cip. Risk: monorepo contributors update CIP-related docs in the monorepo without realizing the docs now live in foundry-cip. Mitigation: post-extraction, `products/client-intelligence-platform/` contains ONLY the EXTRACTION-NOTE.md — nothing else. Anyone trying to add CIP docs in the monorepo will see no docs/ structure and have to create one (which the §6.4 CLAUDE.md update flags as wrong).

### 10.9 Foundry Studio org permissions

`gh repo create Foundry-Studio/foundry-cip` requires owner-or-admin on the Foundry-Studio org. If the executing user lacks the permission, `gh repo create` will fail. Mitigation: pre-flight § 1.5 checks `gh auth status`; if the user is not authorized for Foundry-Studio, they can't authenticate as someone who is. Resolution: Tim creates the empty repo; the rest of the extraction can run as any contributor.

### 10.10 Interaction with the scheduled JOS-extraction infrastructure

The monorepo has scripts and CI for handling JOS extraction (e.g., `extract-jos.sh`, `update-foundry.sh`, the `.jos/charter.yaml` synchronization). None of those touch CIP paths. Mitigation: verified by `grep -l "cip" WORKBENCH/tim/phase8-artifacts/*.sh` (returns zero matches as of 2026-04-27).

### 10.11 Cross-pollution guard race-safety (v4 — Stress Tester S4-1, deferred to Phase 8)

**Surfaced by:** v4 Round-4 panel (Stress Tester subagent), 2026-04-29.

**Concern:** The cross-pollution guard in `cip/migrations/env.py` reads the `alembic_version` table contents OUTSIDE the migration's `context.begin_transaction()`, then proceeds to apply migrations. There is a TOCTOU window between "check no foreign revisions exist" and "actually start applying CIP migrations." A second concurrent migration runner could insert a foreign revision in that window.

**Why we're deferring the fix to Phase 8:** At our scale (single-tenant, single-deployment, pre-Phase-8 code-only extraction), this window is non-exploitable in practice. Three factors:
1. Foundry runs ONE foundry-cip migration session at a time. There is no second concurrent migrator that could race the window.
2. The migration's actual DDL takes a transaction-scoped lock on the target tables (Postgres standard behavior). Even if a hypothetical second migrator passed the cross-pollution check in the same window, it would BLOCK on the table lock — not race past it.
3. Phase 8 (CIP data-layer extraction to its own DB) makes this concern entirely moot: separate DBs cannot have cross-pollution by construction.

**The "industry-standard fix" we considered:** Wrap migration runs in `pg_advisory_xact_lock(hash_int8(tenant_id, "cip_migration_lock"))` per [PostgreSQL advisory lock docs](https://oneuptime.com/blog/post/2026-01-25-use-advisory-locks-postgresql/view) and the [Alembic concurrency-control patterns](https://medium.com/exness-blog/alembic-migrations-without-downtime-a3507d5da24d). Rejected for v4 because (a) the fix's primary value is at multi-replica deploy scale, and (b) advisory locks + future PgBouncer-style transaction pooling are known-bad — see [IBM mcp-context-forge issue #4051](https://github.com/IBM/mcp-context-forge/issues/4051) where Alembic + advisory-lock + PgBouncer hangs on multi-pod deploys. Adding the lock now adds operational risk for a guard that solves a problem we don't have yet.

**Tracking:** This section IS the deferral record. When Phase 8 schedules the data-layer extraction, the concern auto-resolves; this section can then be deleted as superseded. If pre-Phase-8 deployment ever scales to multi-instance migration runners (e.g., Railway adds replica deploys for the migration job specifically), reopen this concern and add the advisory lock at that point.

### 10.12 GitHub repo owner is Tim's personal account (v5.2 — escalated to DAY-1 per Round-6 panel)

**v5.2 (Round-6 Strongly-Recommended):** GPT-5.4 escalated this from Phase-8-deferred to DAY-1 governance risk. Quote: *"Personal-account ownership is not a Phase-8 problem; it is a Day-1 governance risk. Add a second admin immediately, enforce 2FA, document transfer plan, store repo settings/export somewhere, use signed tags/releases."*

**Day-1 actions Tim must perform BEFORE the public flip (§7.1b):**
1. **Add second admin** to `Foundry-Studio/foundry-cip`. If Foundry-Studio adds a `foundry-studio-bot` machine-user, that's preferred. Otherwise add Van's GitHub account as admin.
2. **Enforce 2FA** on the Foundry-Studio org (settings → Authentication security → Require two-factor authentication).
3. **Document transfer plan** in `docs/notes/` of foundry-cip: what happens to the repo if Tim's GH account is rotated/lost. Plain text plan; CC includes this in extraction §3.6.
4. **Pre-store repo settings** via `gh api repos/Foundry-Studio/foundry-cip > /tmp/foundry-cip-settings-backup.json` after `gh repo create` and check into a private location (e.g., 1Password, internal vault).
5. **Use signed tags + releases** for any future `v0.x.0` tag (`git tag -s v0.1.0 -m "..." + git push origin v0.1.0`).

**Why DAY-1 not Phase-8:** Public-flip + Tim-personal-ownership without a second admin = single-point-of-failure for the public surface. If Tim's GH account is compromised, foundry-cip loses its admin; if Tim is unavailable, repo settings can't be changed. Phase 8 was the wrong horizon — by Phase 8 the repo will have months of consumer pins, post-mortems will reference its commits, and admin-recovery will be that much harder.

**Acceptance:** §1.5g extended to also assert: at least one admin OTHER than Tim is configured before public flip. Pre-flight script can check via `gh api repos/Foundry-Studio/foundry-cip/collaborators --jq '[.[] | select(.permissions.admin) | .login] | length' >= 2`.

---

## 11. Rollback Procedure

### 11.0 Idempotent rollback script (v5.2 — Round-6 BLOCKER 4)

**v5.2 replaces the narrative §11.1–§11.3 procedure with an executable script:**

```bash
# Auto-detects current state (extraction created? monorepo committed? pushed? public?)
# Runs the inverse sequence appropriate to that situation.
# DRY-RUN by default. Set CIP_ROLLBACK_EXECUTE=1 to actually execute.
bash WORKBENCH/tim/cip-extraction-artifacts/rollback-extraction.sh

# Execute (after dry-run review):
CIP_ROLLBACK_EXECUTE=1 bash WORKBENCH/tim/cip-extraction-artifacts/rollback-extraction.sh
```

The script auto-classifies one of 5 situations:
- **A** — extraction not started (no-op)
- **B** — foundry-cip created, monorepo untouched
- **C** — foundry-cip created + monorepo committed locally, NOT pushed
- **D** — monorepo pushed + foundry-cip private (revert path; preferred if downstream consumers pinned SHA)
- **E** — monorepo pushed + foundry-cip PUBLIC (HALT — do not auto-delete; archive + forward-fix per security playbook)

The script prints exact commands + verification steps for each situation. §11.1–§11.3 below remain as authoritative reference for the situation matrix; the script is the executable surface.

### 11.1 Rollback before Foundry changes (Steps 1–5 failed)

If the failure happens before §6 (Foundry-side updates haven't started), rollback is clean:

```bash
# Delete the GitHub repo
gh repo delete Foundry-Studio/foundry-cip --yes

# Discard the local extraction working tree
rm -rf "$WORKDIR" "$DRYDIR"

# Remove the cip-extraction-point tag (if pushed)
git push --delete origin cip-extraction-point
git tag -d cip-extraction-point
```

The monorepo is unchanged. Diagnose the failure, adjust the plan, re-run §1.

### 11.2 Rollback after Foundry changes (Steps 6+ failed)

If §6 has committed but §7 validation failed, the monorepo has lost its CIP paths. Two options:

**Option A — Revert the monorepo commit, keep foundry-cip:**
```bash
cd /path/to/Foundry-Agent-System
git revert <the-extraction-cleanup-commit-sha> --no-edit
# Resolve any conflicts
git push origin master
```

The monorepo regains its CIP paths. foundry-cip stays on GitHub (no harm — it's a fresh repo with no consumers yet). The extraction can be re-attempted later.

**Option B — Hard reset (Tim's explicit confirmation required):**
```bash
cd /path/to/Foundry-Agent-System
# WARNING: destructive — only if Tim says yes in current turn
git reset --hard <commit-before-extraction-cleanup>
git push --force origin master
```

Use only if Option A's revert produces unmergeable conflicts.

### 11.3 Nuclear option — delete foundry-cip and start over (v2 — Stress F-9/F-41 fix)

If foundry-cip itself is the problem (extraction was wrong, history is corrupted, etc.):

```bash
# Delete the foundry-cip repo
gh repo delete Foundry-Studio/foundry-cip --yes

# DO NOT delete the cip-extraction-point tag — preserve reproducibility.
# Instead, rename the previous attempt's tag for forensic value:
git tag cip-extraction-attempt-1 cip-extraction-point   # save under different name
git push origin cip-extraction-attempt-1
# (cip-extraction-point still exists — points to the same commit. Re-running the
# extraction script against the same tag produces deterministic output, which is the
# whole point of the tag.)

# Wait for any cached clone of foundry-cip to invalidate (~5 min)
# Investigate root cause; update plan if needed; re-run §1 from scratch.
```

The monorepo's §6 changes need to be reverted via Option A or B.

---

## 12. Acceptance Criteria

The extraction is **DONE** when ALL of these pass:

| # | Criterion | Verification command / location |
|---|---|---|
| 1 | foundry-cip exists at github.com/Foundry-Studio/foundry-cip, public, with master branch | `gh repo view Foundry-Studio/foundry-cip` |
| 2 | All 8 cip_*.py migrations present in foundry-cip | `ls migrations/versions/cip_*.py \| wc -l` returns 8 |
| 3 | cip_01's down_revision rewritten to None | `grep "^down_revision" migrations/versions/cip_01_clients.py` matches `= None` |
| 4 | cip_02..cip_08 chain unchanged (each chains to previous cip_*) | grep loop confirms each `down_revision` matches expected |
| 5 | `alembic upgrade head` runs cleanly on a fresh testcontainer Postgres | scripts/preflight_alembic.py exits 0 |
| 6 | All 16 expected cip_* tables created (7 entity + 7 history + sync_runs + property_registry) | preflight_alembic.py count assertion |
| 7 | foundry-cip directory layout matches §3.3 spec (docs/, migrations/, cip/, tests/) | `tree -L 2 -d` |
| 8 | Vision docs present (5 files) | `ls docs/vision/*.md \| wc -l` returns 5 |
| 9 | Architecture doc present (≥1) | `ls docs/architecture/*.md \| wc -l` returns ≥1 |
| 10 | Runbook docs present (≥10 from M0 + ≥4 stubs from §8) | `ls docs/*.md \| wc -l` returns ≥14 |
| 11 | pyproject.toml + alembic.ini + LICENSE + README.md + CLAUDE.md + CONTRIBUTING.md all exist | `for f in pyproject.toml alembic.ini LICENSE README.md CLAUDE.md CONTRIBUTING.md; do test -f $f \|\| echo MISSING $f; done` |
| 12 | pyproject.toml has NO LLM Roster dep | `grep -i "llm_roster\|llm-roster" pyproject.toml` returns no matches |
| 13 | `pip install -e ".[dev]"` succeeds | run it; exit code 0 |
| 14 | `python -c "import cip; import cip.integration_mesh"` succeeds | exit code 0 |
| 15 | mypy strict passes on cip/ | `mypy cip/` returns 0 |
| 16 | ruff passes on cip/ + tests/ | `ruff check cip/ tests/` returns 0 |
| 17 | GitHub Actions CI green on first push | `gh run list --repo Foundry-Studio/foundry-cip --limit 1` shows success |
| 18 | No secrets in foundry-cip history | secrets scan from §4.1 returns no critical matches |
| 19 | No large blobs (>500KB) in foundry-cip history | large blob audit from §4.2 returns empty |
| 20 | Foundry-Agent-System monorepo deletes CIP paths | `git status` after §6.2 + §6.10 shows the deletions committed |
| 21 | Foundry monorepo's `alembic check` passes (no orphan chain) | run after §6.10 |
| 22 | Foundry monorepo CI still green | wait for next CI run after §6.10 push |
| 23 | CIP-EXTRACTION-NOTE.md exists in monorepo | `test -f products/client-intelligence-platform/CIP-EXTRACTION-NOTE.md` |
| 24 | Foundry CLAUDE.md updated with externalized-products section | `grep -c "Externalized Products" CLAUDE.md` returns ≥1 |
| 25 | FOUNDRY-TAXONOMY.md updated for Product #6 | `grep "foundry-cip" FOUNDRY-TAXONOMY.md` returns ≥1 |
| 26 | governance_registry.yaml has no orphan path references to deleted CIP files | grep returns no matches |
| 27 | MANIFEST.md regenerated, no CIP entries | `grep -c "client-intelligence-platform/" MANIFEST.md` returns 1 (just the EXTRACTION-NOTE pointer) |
| 28 | PM scope "Stage 1-3 — Repo extraction" marked done | `foundry_mcp_pm_project_status` shows `done` |
| 29 | PM decision comment posted on CIP project documenting the extraction | `foundry_mcp_pm_project_status` shows the comment |
| 30 | Cowork tasks #58 + #59 marked completed | this session's TodoWrite list |
| 31 | `cip-extraction-point` tag exists in monorepo | `git tag -l cip-extraction-point` returns the tag |
| 32 | Atlas write-log receipt batch appended | `internal-tooling/atlas-state/write-log.md` has receipts for the extraction commits |
| 33 | This plan archived to foundry-cip's `docs/archive/` | `ls foundry-cip/docs/archive/` includes `cip-extraction-plan.md` |
| 34 | M2 plan v5 also copied to foundry-cip's `docs/archive/` (per Gap G-105) | `ls foundry-cip/docs/archive/` includes `cip-m2-deep-plan.md` |
| 35 | (v2 — Q1) `pmmg01_backfill_comments_actor.py`'s `down_revision` rewritten to `async_03_agents_cols` in monorepo | `grep "down_revision" migrations/versions/pmmg01_backfill_comments_actor.py` shows the new value |
| 36 | (v2 — Q2) 9 RLS test files + `tests/migrations/conftest.py` present in foundry-cip | `ls foundry-cip/tests/migrations/test_rls_cip_*.py \| wc -l` returns 9 |
| 37 | (v2 — Q3) foundry-cip's `migrations/env.py` sets `version_table = "alembic_version_cip"` | `grep "version_table" foundry-cip/migrations/env.py` matches `"alembic_version_cip"` |
| 38 | (v2 — Q5) docs at top-level `docs/`, no `docs/runbooks/` subfolder | `ls -d foundry-cip/docs/runbooks 2>/dev/null` returns no such directory |
| 39 | (v2 — Q6) D-152 entry in monorepo's `docs/DECISION-LOG.md` | `grep -c "^### D-152:" docs/DECISION-LOG.md` returns 1 |
| 40 | (v2 — Q6) D-152 registered in `infrastructure/governance_registry.yaml` | `grep -c "id: D-152" infrastructure/governance_registry.yaml` returns 1 |
| 41 | (v2 — Q7) foundry-cip flipped from private to public AFTER §7.1 validation passed | `gh repo view Foundry-Studio/foundry-cip --json visibility \| jq -r .visibility` returns "public" |
| 42 | (v2 — F-13) Monorepo's pyproject.toml/requirements pins `foundry-cip @ git+...@<sha>` | `grep "foundry-cip" pyproject.toml requirements*.txt` shows the pin |
| 43 | (v2) `cip-extraction-point` tag preserved in monorepo (not deleted at any rollback) | `git tag -l cip-extraction-point` returns the tag |
| 44 | (v2 — Senior reviewer) CHANGELOG.md initialized at 0.1.0 in foundry-cip | `head -10 foundry-cip/CHANGELOG.md` shows v0.1.0 entry |
| 45 | (v2 — F-2) cip_*.py files in foundry-cip have LF line endings | `file foundry-cip/migrations/versions/cip_*.py \| grep -c "ASCII text$"` returns 8 |
| 46 | (v2 — Gap G-101) Initial GitHub issues created on foundry-cip | `gh issue list --repo Foundry-Studio/foundry-cip` shows ≥6 issues (M2 execute, Phase 8 placeholder, 4 runbook stubs) |
| 47 | (v4 — Gap GAP-23) Fresh-venv `pip install` smoke test from foundry-cip's git URL succeeds | `python -m venv /tmp/cip-venv && /tmp/cip-venv/bin/pip install "git+https://github.com/Foundry-Studio/foundry-cip.git@${SHA}" && /tmp/cip-venv/bin/python -c "import cip"` exit 0 |
| 48 | (v4 — Senior CONC-17) Wheel-install CI job present + green | `.github/workflows/test.yml` contains `wheel-install:` job; `gh run list` shows green |
| 49 | (v4 — Gap GAP-02 / Stress S5-2) `cip/migrations/script.py.mako` ships in the wheel | `python -c "from importlib import resources; assert resources.files('cip').joinpath('migrations/script.py.mako').is_file()"` exit 0 |
| 50 | (v4 — Gap GAP-03) `cip/migrations/__init__.py` + `cip/migrations/versions/__init__.py` exist | `test -f cip/migrations/__init__.py && test -f cip/migrations/versions/__init__.py` exit 0 |
| 51 | (v4 — Gap GAP-04) `alembic` invoked with no config file does NOT crash | `python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; cfg = Config(); cfg.set_main_option('script_location', 'cip:migrations'); s = ScriptDirectory.from_config(cfg); print(s.get_current_head())"` exit 0 |
| 52 | (v4 — Gap GAP-16) Cross-pollution guard CI test fires + override works | `.github/workflows/test.yml` contains `cross-pollution-guard:` job; both negative + override paths green |
| 53 | (v4 — ITEM 1 / Senior CONC-2) `foundry-cip-migrate` exposes ONLY `check` | `foundry-cip-migrate upgrade head` exits non-zero with "no longer wraps" message; `foundry-cip-migrate check` exits 0 |
| 54 | (v4 — ITEM 3 / Senior CONC-10) Python upper bound dropped + matrix expanded | `grep "requires-python" pyproject.toml` shows no `<` cap; `test.yml` matrix includes 3.11, 3.12, 3.13, 3.14 |
| 55 | (v4 — Stress S5-1 / FND-S13) `requirements.in` contains foundry-cip pin AND `requirements.txt` is uv-recompiled | `grep "foundry-cip @ git" requirements.in && grep "foundry-cip @ git" requirements.txt` exit 0 |
| 56 | (v4 — Senior CONC-15) update-foundry.sh manual-edit verification grep passes after Atlas-orchestrated edits | `grep -q "Externalized Products" CLAUDE.md && grep -q "foundry-cip" FOUNDRY-TAXONOMY.md` exit 0 |
| 57 | (v4 — Gap GAP-19) NOTICE file present at foundry-cip root | `test -f foundry-cip/NOTICE` exit 0 |
| 58 | (v4 — Senior CONC-1) D-142 collision resolved — uses D-152 throughout | `grep -c "D-152" WORKBENCH/tim/cip-extraction-plan.md` ≥10 AND `grep "^### D-142:" docs/DECISION-LOG.md` returns the existing async-first decision (untouched) |

---

## Appendix A: Automated extraction script (`extract-cip.sh`) — v2-era outline (STALE; see real script for canonical content)

**v4.2 (Verifier HIGH-E 2026-04-29):** The bash listing in §A.1 below is a v2-era outline that has NOT been updated through v3/v4/v4.1/v4.2 changes. It is missing: the v5.2 BLOCKER 1 gitleaks scan, the v4 cip-db.py + script.py.mako + NOTICE copies, the v4 disk/docker/repo-name pre-flights, the v4.1 CRLF normalization for all 8 cip files, the v4.1 atomic-commit pattern in update-foundry.sh, the v5.2 Conventional Commits format, and the v5.2 git gc step. **Do NOT execute Appendix A's bash literally.** The canonical content lives at `WORKBENCH/tim/cip-extraction-artifacts/extract-cip.sh` (530+ lines, fully maintained). Appendix A is preserved here only as historical context for what v2 thought the script would look like.


A bash script modeled on `extract-jos.sh` that automates §2–§5. Idempotent, includes safety pauses, OS-portable.

See full script at `WORKBENCH/tim/cip-extraction-artifacts/extract-cip.sh` (created at execution time per §A.1 below).

### A.1 Script outline (full version delivered with the plan during execution)

```bash
#!/usr/bin/env bash
set -euo pipefail

ORG="Foundry-Studio"
SOURCE_REPO="https://github.com/${ORG}/Foundry-Agent-System.git"
TARGET_REPO="foundry-cip"
WORKDIR="/tmp/${TARGET_REPO}-extraction"
ARTIFACTS_DIR="$(cd "$(dirname "$0")" && pwd)"

# Portable sed -i (macOS vs Linux)
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed_i() { sed -i '' "$@"; }
else
  sed_i() { sed -i "$@"; }
fi

CIP_PATHS=(
  --path products/client-intelligence-platform/
  --path docs/cip/
  --path migrations/versions/cip_01_clients.py
  --path migrations/versions/cip_02_views.py
  --path migrations/versions/cip_03_sync_runs.py
  --path migrations/versions/cip_04_files.py
  --path migrations/versions/cip_05_contacts.py
  --path migrations/versions/cip_06_companies.py
  --path migrations/versions/cip_07_deals.py
  --path migrations/versions/cip_08_tickets_and_registry.py
)

echo "=== foundry-cip Extraction ==="

# Step 2.2: Dry-run
DRYDIR=/tmp/foundry-cip-dryrun
rm -rf "$DRYDIR"
git clone "$SOURCE_REPO" "$DRYDIR"
cd "$DRYDIR"
git checkout cip-extraction-point
git filter-repo "${CIP_PATHS[@]}"
# Verification queries (as in §2.2)
read -p "Dry-run complete. Proceed to real extraction? [y/N] " -n 1 -r
[[ $REPLY =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
cd /tmp && rm -rf "$DRYDIR"

# Step 2.3 + 2.4: Real extraction
rm -rf "$WORKDIR"
git clone "$SOURCE_REPO" "$WORKDIR"
cd "$WORKDIR"
git checkout cip-extraction-point
git filter-repo "${CIP_PATHS[@]}"

# Step 3.1 + 3.2: Reorg
git mv products/client-intelligence-platform/vision docs/vision
git mv products/client-intelligence-platform/architecture docs/architecture
git mv products/client-intelligence-platform/notes docs/notes
git mv products/client-intelligence-platform/research docs/research
git mv products/client-intelligence-platform/archive docs/archive
git mv products/client-intelligence-platform/README.md README.md
git mv products/client-intelligence-platform/CLAUDE.md docs/legacy-CLAUDE.md
rmdir products/client-intelligence-platform; rmdir products
git mv docs/cip docs/runbooks

# Step 3.4: Rewrite cip_01 down_revision
sed_i 's|down_revision: Union\[str, Sequence\[str\], None\] = "async_03_agents_cols"|down_revision: Union[str, Sequence[str], None] = None|' \
    migrations/versions/cip_01_clients.py

# Step 3.5–3.14: Drop in pre-built scaffolding files from $ARTIFACTS_DIR
cp "$ARTIFACTS_DIR/pyproject.toml" pyproject.toml
cp "$ARTIFACTS_DIR/LICENSE" LICENSE
cp "$ARTIFACTS_DIR/CLAUDE.md" CLAUDE.md
cp "$ARTIFACTS_DIR/CONTRIBUTING.md" CONTRIBUTING.md
cp "$ARTIFACTS_DIR/alembic.ini" alembic.ini
cp "$ARTIFACTS_DIR/env.py" migrations/env.py
cp "$ARTIFACTS_DIR/.gitignore" .gitignore
cp "$ARTIFACTS_DIR/test.yml" .github/workflows/test.yml
mkdir -p cip/integration_mesh tests
touch cip/__init__.py cip/integration_mesh/__init__.py cip/py.typed tests/__init__.py
cp "$ARTIFACTS_DIR/conftest.py" tests/conftest.py

# Drop venture-onboarding stubs
cp "$ARTIFACTS_DIR/runbook-stubs/"*.md docs/

git add -A
git commit -m "scaffold: foundry-cip standalone-repo bootstrap"

# Step 4.1: Secrets scan
echo "=== Secrets scan ==="
git log --all -p | grep -iE "AKIA[0-9A-Z]{16}|sk-[a-zA-Z0-9]{40,}|ghp_[a-zA-Z0-9]{36,}" | head -20 || echo "Clean."

# Step 4.3: Alembic dry-run via testcontainer
python "$ARTIFACTS_DIR/preflight_alembic.py"

# Step 5: Push
git remote add origin "https://github.com/${ORG}/${TARGET_REPO}.git"
git push -u origin master

echo "=== Extraction complete. Now run update-foundry.sh from the monorepo. ==="
```

(Full script will be `~250` lines once expanded with verification queries from §2.2 + §2.4 + §4.1 + §4.2.)

### A.2 Companion script — `update-foundry.sh`

A second bash script automates §6 (Foundry-side cleanup). Same structure as `update-jos.sh`. ~150 lines.

---

## Appendix B: Repo template files

Pre-generated artifacts to be placed in `WORKBENCH/tim/cip-extraction-artifacts/` for the script in Appendix A to consume:

- `pyproject.toml` (full content from §3.5)
- `LICENSE` (Apache 2.0)
- `CLAUDE.md` (full content from §3.6)
- `CONTRIBUTING.md` (full content from §3.8)
- `alembic.ini` (full content from §3.9)
- `env.py` (full content from §3.10)
- `.gitignore` (full content from §3.11)
- `test.yml` (full content from §3.14)
- `conftest.py` (full content from §3.13)
- `preflight_alembic.py` (full content from §4.3)
- `runbook-stubs/DEPLOYING-FOUNDRY-CIP-FOR-A-NEW-VENTURE.md` (Appendix C)
- `runbook-stubs/EXPORTING-VENTURE-CONNECTORS.md` (Appendix C)
- `runbook-stubs/STANDALONE-INTEGRATION-GUIDE.md` (Appendix C)
- `runbook-stubs/TROUBLESHOOTING-AND-INCIDENT-RESPONSE.md` (Appendix C)
- `CIP-EXTRACTION-NOTE.md` (full content from §6.1)

---

## Appendix C: Venture-onboarding runbook stubs

### C.1 `DEPLOYING-FOUNDRY-CIP-FOR-A-NEW-VENTURE.md` stub

```markdown
---
status: stub
purpose: "Start-to-finish playbook for deploying foundry-cip on behalf of a new venture tenant."
owner: tim
created: 2026-04-27
---

# Deploying foundry-cip for a New Venture

> **Status: stub.** This document will be filled out once the first non-Wayward venture (Rocky Ridge or beyond) has been deployed end-to-end and the playbook is observed.

## Scope

This runbook covers the operator playbook for taking a venture from "we want CIP for them" → "their data is queryable, dashboards work, alerts fire."

## Outline (TBD)

1. **Pre-deployment checklist** — venture confirmed as a tenant, source-system credentials in hand, target Postgres ready.
2. **Tenant provisioning** — create venture in `tenants` table, run TENANT-ONBOARDING-CHECKLIST.md.
3. **Connector decision** — which connectors does this venture need? Map to existing connectors (HubSpot, Zendesk, QBO, etc.) or scope a new connector per CONNECTOR-AUTHORING-GUIDE.md.
4. **Initial sync** — first run, expect ramp-up, document any surprises.
5. **Lens definition** — what slices of the data does each consumer team see?
6. **Dashboards + reports** — Metabase setup per consumer.
7. **Sign-off** — venture confirms data quality, dashboards, scheduled reports.
```

### C.2 `EXPORTING-VENTURE-CONNECTORS.md` stub

```markdown
---
status: stub
purpose: "Procedure for moving a venture-specific connector out of foundry-cip into the venture's own repo at graduation."
owner: tim
created: 2026-04-27
phase_relevance: "Phase 8+"
---

# Exporting Venture Connectors

> **Status: stub.** This document fills out at Phase 8 when the first venture graduates to its own deployment.

## Scope

Some connectors start their lives inside foundry-cip's `cip/connectors/` (because we built them while the venture didn't have its own repo). When the venture graduates — gets its own engineering team, its own deployment, its own Postgres — those venture-specific connectors should move to the venture repo.

## Outline (TBD)

1. **Pre-export check** — is the connector truly venture-specific? (If it's reusable across ventures, it stays in foundry-cip.)
2. **`git filter-repo` extraction** — move the connector's files + history to the venture repo using the same multi-path pattern this extraction plan uses.
3. **Foundry-cip cleanup** — delete the extracted files from foundry-cip; leave a note pointing to the venture repo.
4. **Venture-side scaffolding** — venture repo needs to declare `foundry-cip` as a dependency.
5. **Test** — venture repo's CI can run the connector against the same fixture data.
```

### C.3 `STANDALONE-INTEGRATION-GUIDE.md` stub

```markdown
---
status: stub
purpose: "Bare-minimum integration guide for an external developer using foundry-cip without Foundry's runtime."
owner: tim
created: 2026-04-27
---

# Standalone Integration Guide

> **Status: stub.** This document fills out once foundry-cip has been adopted by at least one external (non-Foundry) deployment.

## Scope

You're a developer outside Foundry. You want to use foundry-cip's connector framework + schema in your own deployment, against your own Postgres, with your own LLM provider.

## Outline (TBD)

1. **Install** — `pip install foundry-cip`, set DATABASE_URL, run alembic.
2. **Tenant model** — choosing how `tenant_id` maps to your domain.
3. **First connector** — copy a generic connector (HubSpot or fixture) and adapt.
4. **Knowledge ingestion (optional)** — wire `ingest_as_knowledge` to your own embedding store.
5. **Consumption** — query the cip_* tables directly via SQL or layer your own API.
```

### C.4 `TROUBLESHOOTING-AND-INCIDENT-RESPONSE.md` stub

```markdown
---
status: stub
purpose: "Incident-response playbook: what fails, how it surfaces, how to recover."
owner: tim
created: 2026-04-27
---

# Troubleshooting and Incident Response

> **Status: stub.** This document fills out as real incidents accumulate.

## Scope

Reference for an on-call engineer facing a CIP-related incident. Symptoms → likely causes → recovery procedure.

## Outline (TBD)

1. **Sync failures** — `cip_sync_runs.status = 'failed'`. Reading `error_detail` JSONB. Re-running.
2. **Schema drift** — connector emits a record the mapper can't handle.
3. **RLS issues** — "I see no rows" surprise. Tracking `app.current_tenant`.
4. **Connection-pool exhaustion** — under multi-tenant load.
5. **Authority bug** — a record landed with `authority='ingested'` when it should be `agent_discovered`.
6. **Knowledge-ingest failures** — Pinecone/FalkorDB write rejected.
7. **Migration rollback** — when to `alembic downgrade`, when to forward-fix.
```

---

## Appendix D: Claude Code handoff briefing

A 2-page brief for the Claude Code session that executes this plan, modeled on `WORKBENCH/tim/phase8-artifacts/CC-BRIEFING.md`.

### D.1 What you're doing

Extracting CIP from `Foundry-Agent-System` into `Foundry-Studio/foundry-cip`. Then updating Foundry-Agent-System to consume foundry-cip as an external dependency. Finally, validating both repos work post-extraction.

### D.2 The full plan

`WORKBENCH/tim/cip-extraction-plan.md` — this document. ~1,500 lines, 33 acceptance criteria, 12 sections + 4 appendices. It's been through Atlas review + 3-subagent QC + Atlas CTO alignment.

### D.3 Pre-generated artifacts

All in `WORKBENCH/tim/cip-extraction-artifacts/`:

- `extract-cip.sh` — automates §2–§5 (extraction, fixes, validation, push)
- `update-foundry.sh` — automates §6 (Foundry-side cleanup)
- `pyproject.toml`, `LICENSE`, `CLAUDE.md`, `CONTRIBUTING.md`, `alembic.ini`, `env.py`, `.gitignore`, `test.yml`, `conftest.py`, `preflight_alembic.py`
- `runbook-stubs/` — 4 stub files for §8
- `CIP-EXTRACTION-NOTE.md` — Foundry-side stub

### D.4 Execution order

```
1. Pre-flight (§1) — manual checks
   - git status clean
   - git stash list — no CIP stashes
   - git filter-repo --version
   - gh repo create Foundry-Studio/foundry-cip --public

2. Run extract-cip.sh (§2–§5)
   - Dry-run extraction → review → real extraction
   - Reorg + cip_01 down_revision rewrite
   - Drop scaffolding files
   - Pre-push validation
   - Push to GitHub

3. Run update-foundry.sh (§6)
   - Tag split point
   - Remove CIP paths from monorepo
   - Repair Alembic chain
   - Update CLAUDE.md / FOUNDRY-TAXONOMY.md / governance_registry / MANIFEST
   - Commit + push

4. Validation (§7)
   - foundry-cip: CI green, alembic upgrade head OK, mypy + ruff pass
   - Foundry monorepo: no orphan refs, alembic check passes, CI green

5. PM updates (§9)
   - Mark scopes done
   - Decision comment

6. Atlas write-log receipt batch
```

### D.5 Critical gotchas

1. **`git filter-repo` needs a FRESH clone.** Don't run on a working copy.
2. **The script uses `read -p` for human approval.** Don't pipe input.
3. **cip_01 down_revision rewrite is the only migration edit.** Don't touch cip_02..cip_08 chains.
4. **MANIFEST.md must be REGENERATED** via `python scripts/generate_manifest.py --write`, not string-replaced.
5. **Foundry monorepo Alembic chain (§6.3) is symmetric to cip_01's rewrite.** Verify NO migration in monorepo chains on cip_* before deletion.
6. **Documentation drift mitigation (§10.8):** post-extraction, monorepo's `products/client-intelligence-platform/` contains ONLY the EXTRACTION-NOTE.md.

### D.6 Acceptance

33 items in §12. The key ones:
- foundry-cip CI green on first push
- alembic upgrade head produces 16 cip_* tables
- pyproject.toml has NO LLM Roster dep
- mypy + ruff pass on cip/
- Foundry monorepo `alembic check` passes
- PM scope marked done + decision comment posted
- Atlas write-log receipt batch appended

### D.7 Related files

- M2 framework plan (executes IN foundry-cip post-extraction): `WORKBENCH/tim/cip-m2-deep-plan.md` (v5)
- M2 panel prompt (Stage 7 reference): `WORKBENCH/tim/cip-m2-llm-panel-prompt.md`
- M2 assessment (QC rounds 1+2+3): `WORKBENCH/tim/cip-m2-plan-atlas-assessment.md`
- JOS extraction reference (precedent): `WORKBENCH/tim/jos-phase8-repo-split-plan.md`

---

*End of plan v2. Cleared 3-subagent QC round 2026-04-27. Atlas CTO alignment QC pending; then commit to `WORKBENCH/tim/cip-extraction-plan.md` and ready for Claude Code execution.*
