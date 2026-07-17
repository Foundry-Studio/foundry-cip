# P4 — deploy + verify runbook (Stripe goes live)

**Pre-verified 2026-07-17 (read-only, while P2 built):** FAS pins cip by SHA at
`requirements.txt:87` · admin enable path = `schedule_api.update_schedule(db, schedule_id,
enabled=True)` (caller commits) · Railway FAS env has `SLACK_SYSTEM_BOT_TOKEN` + `SLACK_BOT_TOKEN`;
`SLACK_ALERTS_CHANNEL` unset → alerts go to the default **#foundry-ops-alerts** (where the existing
watchdog already posts) · the 6 new schedules are **live in prod `schedule_definitions`, all
`enabled=False`, no next_fire_at** (FAS redeployed 32b25b57 and reconciled) · the refactored
freshness watchdog is running clean post-deploy (fires every 30 min, `consecutive_failures=0`,
6 completed tasks in the last 3h) · no `STRIPE_API_KEY` anywhere yet (expected).

## What Tim provides (the ONLY human prerequisite)
A **restricted read-only Stripe key** (Wayward's Stripe account → Developers → API keys → Create
restricted key):
- **Read** on: **Invoices · Customers · Credit notes · Charges · Refunds · Events** (+ Balance
  transactions if we ever reconcile cash-out; optional now). Everything else **None**. No writes.
- Name it `foundry-cip-sync (read-only)`. It is ADDITIVE — the key used for the 2026-07-13 manual
  pull (wherever it lives) is untouched; nothing is overwritten, so no capture-old-credential step.
- Hand it to the orchestrator session ONCE (env var for the step-0 run) + set it on Railway
  (`Foundry-Agent-System` service → `STRIPE_API_KEY`). Never in the repo, never in a commit.

## Order of operations (each step gated on the previous)
1. **P2 merged + pushed** on foundry-cip master → note the SHA.
2. **Apply `cip_111` to prod** (evidence tables + events table MUST exist before any sync run):
   `FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS=<current FAS head — re-check at run time; was
   d232_behavior_subsystem_schema on 2026-07-16>` then `alembic upgrade head`. Verify:
   `alembic_version_cip = cip_111_*`, three tables exist with FORCE RLS.
3. **Per-scope key probe** — one GET per required scope with the new key (invoices, customers,
   credit notes, charges, refunds, events; limit=1). A 403 here = fix the key now, not Sunday 03:03.
4. **Step-0 FULL refresh** (closes the 2026-07-13→now gap + seeds the cursor): run
   `run_ps_stripe_sync(engine, tenant_id=PS, mode="full")` from the local repo against prod
   (deliberate prod write — the same operation the manual ingest was, now via the module), with
   `STRIPE_API_KEY` in the command environment only. Duration ≈ 2-3 min.
5. **Verify parity + correctness** (the plan §3 gates — REFRAMED after the P2 truncation finding):
   P2's QC proved the ORIGINAL ingest dropped every invoice line past the 10th (no `has_more`
   pagination on the embedded lines page). Prod signature confirms real impact: **1,196 invoices sit
   at EXACTLY 10 lines and zero above** — a truncation ceiling, so today's "collected" is likely
   UNDERSTATED. The step-0 full refresh (fixed module) will recover those lines. Therefore the gate
   is NOT "totals unchanged" — it is:
   - **Existing lines byte-stable**: every pre-refresh `(stripe_line_id)` row unchanged in amount/
     status/month (the refresh may only ADD lines and update statuses that genuinely changed).
   - **Every collected delta attributable**: new lines may only belong to invoices that had exactly
     10 lines pre-refresh (the truncated set) or invoices created/changed after 2026-07-13. Any
     other delta = stop and investigate.
   - Capture before/after: per-month collected totals + recovery + the truncated-invoice list;
     report the recovered $ to Tim (it is NEW claimable money on china brands, straight into the
     live lenses).
   - `lens_ps_claim` recovery: expected to move ONLY upward by the recovered china-brand share.
   - Idempotency: immediately run incremental once → ~0 changes.
   - Invariants: `scripts/check_invariants.py` → 21/21.
   - **Refund-overlap recon**: `scripts/reconcile_refund_overlap.py` — the C1 question answered
     with real data (covered / partially-covered / uncovered refund economics). UNCOVERED remainder
     ≠ 0 → bring to Tim before ANY derivation change (tables stay evidence-only regardless).
6. **Bump the FAS pin** — `requirements.txt:87` → the P2 SHA. Tier C commit (`Local-Verified: C`),
   run the migrations-untracked check before push (house rule), push, wait for Railway deploy.
7. **Enable the schedules** (admin path, per WEP-D080 — NOT by editing seed):
   `update_schedule(db, "<id>", enabled=True)` + commit, for: `cip_ps_stripe`,
   `cip_ps_stripe_full`, `cip_ps_invariants`, `cip_ps_signal_harvest`, `cip_wayward_hubspot_full`,
   `cip_wayward_zendesk_full`. Verify `next_fire_at` populates for all 6.
8. **Watch the first live hour**: the :07 stripe run + :12 invariants + :27 harvester each produce a
   `cip_sync_runs` / task row; confirm statuses + counters; confirm NO ops-channel noise (quiet
   success is the pass state).
9. **Add the watchdog entry** (now that data flows): FAS `cip_freshness_watchdog.py`
   `TENANT_ENTITY_MATRIX` PS row += `("ps_stripe_invoice_lines", "ingested_at", True)`
   (alert_when_empty=True — the money table must scream, never skip). Small FAS commit (Tier B).
10. **Staged alarm test** (prove the scream path end-to-end): invoke `post_ops_alert("[staged
    test] stripe freshness alarm wiring check", component="cip-freshness")` once via a one-off
    `railway run` — confirm it lands in #foundry-ops-alerts. (The real staleness path was
    unit-tested in P3; this validates the live channel + token.)

## Rollback (any step)
- Disable the 6 schedules (same admin path). The system returns to today's state (manual snapshot).
- `alembic downgrade -1` removes the cip_111 evidence tables (nothing else references them).
- Pin revert = ordinary requirements.txt revert commit.
- The step-0 full refresh is upsert-only over existing keys — it cannot delete history; the
  pre-refresh parity baseline (step 5) is the audit trail.

## Success = (all true)
hourly `cip_sync_runs` rows accumulating · invariants 21/21 on the :12 cadence · harvester
heartbeats on :27 · watchdog covering `ps_stripe_invoice_lines` with alert_when_empty · recovery
number moves ONLY when reality moves · zero ops-channel noise in a quiet week · Sunday 03:03 full
completes < timeout.
