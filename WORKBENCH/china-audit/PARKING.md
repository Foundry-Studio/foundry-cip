# PARKING — discoveries that must NOT expand the wave they were found in

The protocol: a wave does exactly what its spec says. Anything else found along the way lands here,
with enough detail that the wave it belongs to can pick it up cold.

---

## P1 — 148 `manual_review` rows are ALIAS PROPAGATIONS, not reviews → **belongs to W5**

**Found during:** W1 QC, 2026-07-14.
**Do NOT fix in W1.** W1's spec was "exactly two row-sets, nothing else" — the 131 rubber-stamps and
the 5 research escorts. Both done, zero verdict movement. This is a different defect.

| source_system | points_to | rows | asserted_by |
|---|---|---|---|
| `manual:dupe_row_review_2026_07_14` | china | 116 | Claude (manual review, Tim-delegated) |
| `tim:dupe_row_propagation_2026_07_14` | china | 31 | Tim Jordan |
| `tim:dupe_row_propagation_2026_07_14` | not_china | 1 | Tim Jordan |

Their evidence text gives them away:

> *"Duplicate row of 'AIxibu'. **The brand carries HARD China evidence on its other row**
> (chinese_email_domain, eric_sheet…)"*

**These are not investigations. They are identity operations.** Each one exists to carry a verdict
from one row of a company to its sibling rows — work that `canonical_brand_id` should be doing and
isn't, because exactly one view consumes it and that view is parked.

**The two cases are NOT the same and must not be lumped:**

- **The 32 `tim:dupe_row_propagation` rows are HONEST.** Tim ruled the BRAND. Propagating his ruling
  to the brand's other rows is faithful execution, and `asserted_by = Tim Jordan` is true — he did
  decide it. **Leave these alone even in W5.** The row is redundant, not wrong.
- **The 116 `manual:dupe_row_review` rows are a WORKAROUND.** I hand-checked 111 brand names and then
  wrote a `manual_review` row per duplicate to force the verdict across. `asserted_by` is honest
  (it says Claude), but the SIGNAL claims human authority the content doesn't support.

**Why it is not urgent:** every one of these brands has hard evidence on a sibling row. The verdict
is CORRECT. The provenance is what's ugly.

**W5 disposition:** once `lens_ps_china_companies` rolls up by `canonical_brand_id`, a company's
verdict derives from the union of its rows' evidence and these propagation rows stop being load-
bearing. At that point: retire the 116 (verify verdicts hold at company level first), keep the 32.

---

## P2 — `ps_added_facts` holds 137 rows asserted by `Claude (manual review, Tim-delegated)`
**Belongs to:** the Phase 2 conversation about MCP write tools / D-129 actor attribution.

The table is documented as *"what a HUMAN tells us — THIS OUTRANKS EVERY AUTOMATED SIGNAL."* 150 of
435 live rows (34.5%) are agent-written. Tim genuinely delegated them ("you check each one MANUALLY
and make a decision"), and `asserted_by` names the agent honestly — so this is a labelling question,
not a fraud.

**The real fix is structural, and it is exactly what D-129 gives us:** called through MCP under
OAuth, `asserted_by` is stamped from cryptographic identity and cannot be typed. An agent literally
cannot write "Tim Jordan". That is the argument FOR the write tools, and it should be made in Phase 2
— under the governance gate in FOUNDATION-PLAN.md, not before.

**Do not "fix" this by editing strings.** The string was never the problem.

---

## P3 — `canonical_brand_id` is CORRECT but INCOMPLETE → **Phase 2 / Tim's spreadsheets**

**Found during:** W5 CTO QC, 2026-07-14.
**Do NOT fix in W5.** The roll-up is right *given* canonical_brand_id. This is about the pointer
itself being under-populated — a different job.

`canonical_brand_id` links **exact-name** duplicates. It does not link:

- **name variants** — `Grownsy` and `Selgrownsy` share the mailbox `catherine@grownsy.com` and are
  almost certainly one company. They count as TWO. (This is the very brand whose split identity
  started the whole problem.) Same shape: `NZI NZI`/`NZINZI`, `Petra Tools`/`PetraTools`.
- **company-domain siblings** — **44 company-domain mailboxes span more than one "company",
  covering 121 companies.** Those are candidates for merging.

**Why it is not urgent:** it does not make any verdict wrong. Both Grownsy rows are `china`. It
makes the company COUNT slightly high — we say 1,591 where the truth is somewhere near 1,470-1,550.
It is a precision problem, not a correctness one.

**Why it is not trivial:** a company-domain mailbox is strong evidence of one owner, but the
identity audit found that **email is a "same OPERATOR" signal, not "same COMPANY"** —
`zhou_yintong@163.com` runs 18 unrelated private-label brands. Merging on operator is arguably right
for the CHINA decision (nationality follows the operator) and WRONG for revenue (18 separate billing
relationships). **That is a policy call for Tim, not a data call**, and it should be made before any
merge key is chosen.

**Disposition:** raise it in Phase 3 when Tim brings his spreadsheets — he may simply know which of
the 44 are one company.

---

## P4 — W6 attic move, BLOCKED by a concurrent session → do when repo is quiescent

**Found during:** W6 pre-check, 2026-07-14.

35 dead one-off scripts are ready to move to `scripts/attic/` (6 dated `_*_2026_05_22`, plus
backfills / seeds / rocky-ridge / research / smoke-test scripts). None are imported by the app or
any kept script; verified by grep over src/ and cip/.

**BUT:** at pre-check a concurrent session was mid-sweep across **28 scripts in `scripts/`** (an
import cleanup — removing `from uuid import UUID` and similar), all uncommitted. A bulk `git mv` on
top of that is the exact parallel-agent collision class in memory
([[feedback_parallel_agent_commit_bundling]], [[feedback_concurrent_session_git_reset_data_loss]]):
it would bundle their edits into my commit, or lose them to the move.

**Disposition:** when `git status --short scripts/` is clean, `git mv` the 35 into `scripts/attic/`
+ a one-line README, in ONE pathspec-scoped commit. Pure cleanup, no data change.

**KEEP — do NOT attic:** the tools of record (check_invariants, _guard, ingest_amazon_sellers,
load_added_facts, ingest_usa_research, preflight_alembic, harvest_nationality_signals-until-rewrite;
~~decide_nationality~~ deleted in cip_97 with the old nationality system, 2026-07-15),
the 18 live-pipeline scripts, and the 3 `run_wayward_*` scripts cited as onboarding templates in
docs/ (run_wayward_initial_sync, _hubspot_only, _zendesk_only).
