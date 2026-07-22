# Project Silk Reporting — Rebuild & Correction Plan (P4 / WCC4)

> **THIS IS THE PLAN OF RECORD for the reporting frontend.** It supersedes the screen set in
> `REPORTING-BUILD-PLAN.md` (which drifted to role-home dashboards) and re-anchors on the operational
> money-recovery pipeline defined in `REPORTING-FRONTEND-PLAN.md` (the *what/why*) +
> `REPORTING-FRONTEND-IMPLEMENTATION.md` (the *how*) + `REPORTING-CONTENT-PLAN.md` (the *content per
> audience × depth*) + `LENS-CATALOG.md` (the *data*). Authored 2026-07-22 after a 3-reviewer audit of
> the shipped app.
>
> **Read order for a junior picking this up cold:** §1 (why) → §3 (the model) → §5 (the rules you may
> not break) → §6 (the data) → §7 (the screens) → §9 (your sprint). Then build.

---

## 0. Decisions locked (2026-07-22, Tim)

1. **Write-surface path = (A) governed FAS API.** Money-input writes (Statements pin, Partners
   economics) go through a governed Foundry-Agent-System endpoint that writes + audits; the frontend
   stays read-only on the CIP DB. *(RBAC-admin writes are separate — they touch the app's OWN `app_*`
   auth DB, not CIP — see §7.12.)*
2. **Partners = one page.** Build the Partners performance + payouts page; the "admin" side is a **light
   write on it** (add a partner / simple changes), not a heavy separate screen — routed through the
   governed FAS API.
3. **Raw GMV = ship derived** (label "derived (est.)"). No raw-feed dependency taken on now.
4. **External Wayward view = deferred.** Not built now; **kept as a backlog item in PM** (§10) so it's
   never lost.
5. **Access model = role-based, assigned per person, multi-admin, add-by-email (no invitations); a page
   you're not granted is HIDDEN (absent from nav; 404 on direct hit).** No money gate — that was just an
   example. Any admin can add users, assign roles, and make others admin. Full design in **§7.12** —
   replaces the earlier "full-access seed" framing (F7).
6. **Full activity/usage logging + an admin Report Builder** — every login, page view, export, and admin
   change is logged by code to Postgres (append-only), and admins can filter + **download** "who used the
   system, for what, when." Tim: "very, very important." Design in **§7.13** (best practices researched).

> **POST-REVIEW HARDENING (2026-07-21, four-reviewer pass — ALL DECISIONS RESOLVED).** A coherence,
> CIP-data-mining, governance/security, and blind-spots review pressure-tested this plan against the shipped
> code + the CIP lenses. The sound findings are folded in (base-table/lens workstream §6/§6.1; access-model +
> activity-log hardening §7.12/§7.13; the FAS write contract §10.1; CI-in-0a + the 0a/0b split §9), and **all
> six decisions are now made and baked in (§10.2)** — including two Tim decided against my rec: **CS rules
> nationality IN-APP** via a governed write (§5 rule 9, §7.8, §10.1) and **Tim is the sole non-demotable
> owner** (§7.12). The §7.14 workflow-state layer is **APPROVED**. Nothing here is open; this doc is
> execution-ready.

---

## 1. What went wrong, and what "right" is

**What we shipped (2026-07-21):** a live, deployed, authenticated, bilingual Next.js app at
`reports.project-silk.com` with 9 **role-home** screens (Leadership / Finance / CS / Commission /
Brand Performance / Nationality Review / Data Freshness / Admin / Login). The plumbing is good. The
*product* is wrong.

**Why it's wrong:** the program is a **recovery operation** — collect the ~$13.7k Wayward owes Project
Silk in commission on Chinese-owned brands, **hand Wayward defensible claim statements, chase what's
overdue, and reconcile our claim against Wayward's own numbers.** The plan-of-record
(`REPORTING-FRONTEND-PLAN.md §3`) organizes the app around **that money flow** — "follow a dollar."
We instead built role-home BI *glance* dashboards. The result tells you *status* but gives you **no way
to do the recovery work**: there is no Statements screen (the deliverable), no Collections/chase list,
no Payments-In, no Brand-360, no Exceptions queue, no Partners screen, and the reconciliation lives only
as a fragment of one screen.

**How the drift happened (so we never repeat it):** the *correct* plan
(`REPORTING-FRONTEND-PLAN` + `REPORTING-FRONTEND-IMPLEMENTATION`) was silently "superseded for
execution" by `REPORTING-BUILD-PLAN.md`, which was written against a **design handoff** that had already
re-framed the pipeline into role-homes. The build followed the design, not the plan. Three plan docs
disagreed and **none was reconciled**; P4 was **never kicked off in PM** with its task structure
(`PROGRAM.md` rule: "projects created at kickoff only"). This document + the PM buildout that follows it
close that gap: **one plan of record, one PM board, notes on every task.**

**Corrected intent, one line:** *An internal operational tool that walks a dollar from revenue →
billed → collected → commission earned → paid → **still owed**, lets Finance/Ops **chase and reconcile**
it, and **produces the statement** we hand Wayward — with the external partner/Wayward surfaces as a
data-gated V2.*

---

## 2. Document reconciliation (what each doc is now)

| Doc | Status now |
|---|---|
| **THIS doc (`REPORTING-REBUILD-PLAN.md`)** | ✅ **Plan of record.** Screens, corrections, sprints, acceptance. |
| `REPORTING-FRONTEND-PLAN.md` | ✅ Live — the decisions & the screen intent (§3 "follow a dollar"). Not superseded; this doc executes it. |
| `REPORTING-FRONTEND-IMPLEMENTATION.md` | ✅ Live — the build *how* (security spine, read-map §2, phasing). Its "superseded by BUILD-PLAN" banner is **wrong and must be removed** (doc-hygiene, §12). |
| `REPORTING-CONTENT-PLAN.md` | ✅ Live — the content per audience × Glance/Working/Deep. |
| `LENS-CATALOG.md` | ✅ Live — the data contract. The single source for every number & lens. |
| `REPORTING-BUILD-PLAN.md` | ⚠️ **Superseded for the screen set** (role-homes). Keep ONLY its §1 security-spine + §16 deploy/CI material, which we honor. Its Phase-1/§7/§8 screen enumeration is dead. |
| `REPORTING-FRONTEND-HANDOFF.md` | Historical — the design-bundle handoff. Design system kept (§4.3); screen taxonomy dead. |
| `reporting-design-handoff/` (mockups) | ✅ **Design system kept** (palette, type, chrome, component patterns — Tim likes them). The *role-home screen list* is not the target; re-skin the operational screens with these visuals. |

---

## 3. The mental model — follow a dollar

```
① Revenue generated → ② Wayward billed the client → ③ Billed, not yet collected (COLLECTIONS)
  → ④ Client paid Wayward = COMMISSION EARNED (10/6/3) → ⑤ Wayward paid us
  → ⑥ STILL OWED TO US (the recovery number) → ⑦ We owe partners → ⑧ We paid partners → ⑨ NET WE KEEP
```
Plus the two cross-cutting actions the pipeline exists to support:
- **Reconcile** — our claim vs Wayward's own stated/attributed numbers (`delta_status`), drift-checked.
- **Produce the statement** — pin an as-of claim, drift-check it, hand it to Wayward.

**Audiences (v1 = internal only):** Owner/Admin (Tim), Developer (Van), Finance, Operations, CS.
**External (v2, data-gated — see §10):** Wayward curated view, Referral-partner row-isolated logins.

**Three depths (every screen states which it offers):**
- **Glance** — 5-second KPI tiles.
- **Working** — the lists & queues used daily to *do the job* (chase list, review queue, exceptions).
- **Deep** — per-brand / per-transaction drill-down for investigation & reconciliation (Brand 360, the
  per-brand claim "invoice"). **The shipped app has essentially zero Deep — that's a headline gap.**

---

## 4. Current state — the honest keep / fix / reframe / build inventory

### 4.1 KEEP (good — do not rebuild)
- **The security spine** — the single `defineQuery(surface, fn)` seam (`src/server/dal/define-query.ts`):
  `requireSession → assertCan (default-deny) → withTenant → composed SQL → Zod DTO`. Server-only DAL,
  no raw DB in components, money-as-branded-string. This is more rigorous than the plan sketched. Keep it
  as the enforcement boundary for every screen.
- **The read role** `ps_reporting_reader` (cip_120 — 37 `lens_ps_*` views, no writes, 21/21 smoke).
- **Deploy + domain + OAuth** — live on Railway at `reports.project-silk.com`, Better-Auth Google login
  working, the TXT-verified custom domain, the 60s query cache.
- **i18n scaffold** (en/zh, next-intl) — keep; zh still needs the native-review gate before any external
  exposure.
- **The design system** — jade palette, Newsreader/Public-Sans/IBM-Plex type, the sidebar+topbar chrome,
  KPI-tile + table + chip components. **Re-use verbatim for the operational screens.**
- **Two screens that are genuinely on-target:**
  - **Commission Statement** = the plan's **"What Wayward Owes Us"** (④⑤⑥) with the `delta_status`
    reconciliation + statement-drift. Best-delivered screen — *reframe/rename*, don't rebuild.
  - **Nationality Review Queue** = CS's review queue (`lens_ps_china_contention`). Keep; it's a Working
    view, not a top-level pipeline screen — re-home it under CS/Exceptions.
  - **Brand Performance** and **Data Freshness** are close to the plan's Brand&Product-Perf and
    Data-Health — keep, but fix (see §8) and extend to their planned Working/Deep content.

### 4.2 FIX (correctness — §8 details each)
The six money-labeling defects (Brand-Perf "Collected"=gross, china-count grain & inconsistency, the
Finance waterfall lens-splice, the non-reconciling `→` arrows, the "90+"=180+ mislabel, the rung not
shown) **and** the RBAC model: the shipped app ships a **fixed per-role matrix** (`ROLE_SURFACE`) with no
admin control and no hidden nav — replace it with the **admin-managed, per-person, role-based, default-deny**
model of §7.12 (which *supersedes* the earlier "full-access seed" framing — see §0.5/§8 F7). Both the old
matrix and the new model are default-deny; the defect is the *lack of admin control + hidden nav*, not the
restrictiveness.

### 4.3 REFRAME (right data, wrong container)
- **Leadership / Finance / CS "home" screens** → collapse into the plan's **Pipeline Overview** (one
  all-role home, 9 stage cards + trend + alerts) + push their real content into the operational screens.
  The role-home taxonomy goes away; **role → which screens you can see** is enforced by RBAC, not by
  duplicating a "home" per role.
- **Admin (People & Permissions)** — keep as the **internal RBAC admin** (users/roles/screen-access +
  audit) — this IS wanted (`REPORTING-FRONTEND-IMPLEMENTATION §12`). But it is **not** the plan's
  **Partners Admin** write-surface (§7.11) — that is a *separate, new* screen.

### 4.4 BUILD (missing — the bulk of the work)
Statements & Reporting · Collections · Payments-In · Brand-360 · Exceptions/Needs-Attention · Partners
(perf+payouts) · Revenue&Billing · Excluded-partner book · Partners Admin (write) · plus cross-cutting:
**trends/time-series, export/download, depth (Working/Deep) on every screen.** (External Wayward/partner
surfaces = V2, §10.)

---

## 5. Governance & contracts — the constitution (a junior may NOT break these)

1. **The seam is law.** EVERY data read goes through `defineQuery`. No component imports the DB client.
   No raw rows leave the DAL — return a Zod-validated DTO. A build-check test enforces this; keep it green.
2. **Money is a string, aggregated in SQL.** `USD` is a branded string; `Number()` only in the display
   formatter. **Never** add/subtract/derive money in JS — do it in the composed SQL (the MoM %, the
   deltas, everything). Ratios/percentages: compute in SQL.
3. **Counts said out loud use `lens_ps_china_companies`** (one row per company), NEVER the row-level
   `lens_ps_china_verdict` (RULES.md §, `LENS-CATALOG` — the company book is **1,951**, the verdict-row
   count is 2,351, the claim-bearing subset is 1,167 — do not conflate). Label every population.
4. **"Collected" means `usage_collected` — net of succeeded refunds (cip_113).** `lens_ps_brand_revenue`
   is a **data asset, NOT the money engine**; its `usage_fee_billed` is **gross billed**, has **no**
   `usage_collected` column, and must **never** be labeled "collected." Billed ≥ collected; billed stays
   gross.
5. **We do not re-implement the money math.** Per-product eligibility, the 10/6/3 ladder, the partner
   5% cut, and the `ps_claim_owed = GREATEST(mgmt_fee_owed − wayward_paid, 0)` per-brand floor all live
   in the lenses. The app **reads** `claimable` / `mgmt_fee_owed` / `ps_claim_owed` — it never recomputes
   them. **Corollary:** `ps_claim_owed` is floored per brand, so `Σearned − Σpaid ≠ Σowed` — never render
   those three as a subtraction chain (§8 F4).
6. **`wayward_client_fee_rate` is NOT our commission.** It's what Wayward charges the client. Our rate is
   the 10/6/3 `mgmt_rate`. Surface the rung; never label the client fee rate as "our rate."
7. **The canonical still-owed number** is the live query
   `SELECT round(sum(ps_claim_owed),2) FROM lens_ps_claim WHERE verdict='china'` — always prefer the live
   query over any written figure. (It's ~$13.7–13.9k and drifts hourly; that's correct, not a bug.)
8. **Partner isolation is the DAL `WHERE`, not middleware** (post CVE-2025-29927). For V2 partner
   logins, the row filter is asserted in the query. Middleware is a convenience redirect only.
9. **Verdict semantics** (RULES): china / not_china / unknown; `unknown` is a queue, never a denial.
   **CS MAY RULE NATIONALITY IN-APP (Tim, 2026-07-21 — supersedes the old "review is read-only" rule).** A
   CS selection of china/not_china is a **hard added_fact** — same authority and mechanism as Tim's word in
   chat (`ps_added_facts`, top-rank evidence) — written through the **governed FAS write** (§10.1), NEVER the
   read role. Two invariants: **(a)** the ruling carries **reporting-engine provenance** (`asserted_by` = the
   CS person, `source_ref` = `reporting-app`, `asserted_at`) so the trail shows *who selected it in the tool
   and when* (the "show evidence it was selected in the reporting engine" requirement); **(b)** it
   **propagates across the company's sibling brand rows** (one company = many `ps_brands` rows — a ruling
   pinned to one leaks; see the split-identity hazard). *Surfacing* a verdict without ruling is still
   read-only, and only CS/admin see the ruling control. Evidence types: only Tim-approved types (RULES.md 5).
10. **Access = role-based, assigned per person, admin-managed; unauthorized pages are INVISIBLE.**
    (Revises the "full-access seed" decision per Tim 2026-07-22 — no money gate.) Default-deny. Admins
    add users by email + assign roles; roles grant pages; an ungranted page is **absent from nav and
    404s on a direct hit** (not a 403). Full model in **§7.12**. Every gated screen also **logs a
    `page.view`** and exports log `export.download` (§7.13) — logging is cross-cutting, never opt-in.
11. **The CIP read role is SELECT-only on `lens_ps_*` — and there are THREE write classes, none of them
    on that role.** The app reads CIP only through `ps_reporting_reader` (lens views only; **base tables
    are denied** — see rule 11a). Writes never touch the read role and split into three governed paths:
    **(i) CIP money-critical writes** — statement pin, partner economics, **and CS nationality rulings**
    (§7.8; a verdict flips claim eligibility) → the **governed FAS API** (§10.1), which uses its *own* CIP
    write credential and re-validates the rules server-side; **(ii) app-RBAC writes** (users/roles/role→page
    map) → Next **server actions** on the app's OWN `app_*` DB; **(iii) app workflow-state + activity-log
    writes** (§7.14 chase/dispute/exception/statement-status, and INSERT-only `app_activity_log` §7.13) →
    server actions on `app_*`, never CIP. All are audited. ("Read-only except Partners Admin" was inaccurate.)
11a. **A screen may read only a lens, never a base table.** Six shipped/planned screens route at base
    tables the read role cannot SELECT (`ps_payment_events`, `ps_stripe_balance_transactions/payouts`,
    `ps_partner_payouts`, `ps_brands`, `ps_claim_statements`, `ps_stripe_disputes`, `ps_stripe_invoices`).
    Each needs a **PS-scoped `lens_ps_*` view + a targeted GRANT** created in CIP *before* its screen can be
    built — the dependency register is **§6.1**. Never widen the read role to a base table; add a lens.
12. **Git discipline** (RULES §12, and this repo's jos-sync hazard): `git branch --show-current` before
    staging; pathspec-scoped commits; build/commit foundry-cip docs from a **detached master worktree**
    (the jos-sync bot flips the main checkout mid-session). The reporting *app* repo (`reports-project-silk`)
    is master-only, no branches.

---

## 6. The data contract — lenses per screen (+ the data we're leaving on the table)

Full semantics in `LENS-CATALOG.md`. The read-map (screen → primary lenses):

> **Lens vs base table:** entries marked ⛔ are **base tables the read role cannot SELECT** — each needs a
> PS-scoped `lens_ps_*` + GRANT first (register **§6.1**). Names below are corrected to the *actual* 37-view
> roster (the CIP-data-mining review caught three wrong references — see §6.1 notes).

| Screen | Primary lenses (⛔ = needs a lens+grant, §6.1) |
|---|---|
| Pipeline Overview | `monthly_summary`, `claim`, `partner_payout_summary`, `ar_aging`, `source_freshness`, `rate_clock` (cliff alert), `deal_timeline` (payment-lag) |
| Revenue & Billing ①② | `brand_revenue` (derived GMV/ad-spend, **gross**), `commission_ledger`, `monthly_summary` |
| Collections ③ | `commission_ledger`, ⛔`ps_stripe_invoices` (billed − collected, `amount_remaining`, `hosted_invoice_url`), `ar_aging`, `deal_timeline` (collected-not-remitted); + ⛔`ps_stripe_customers.delinquent` flag |
| **What Wayward Owes Us** ④⑤⑥ | `claim`, `ar_aging`, `wayward_reconciliation`, `wayward_stated`, `statement_drift`, `identity_provenance`/`identity_health` (claim-confidence) |
| Payments In ⑤ | ⛔`ps_payment_events` (+ ⛔`ps_stripe_balance_transactions`, ⛔`ps_stripe_payouts` for cash-recon); variance from `wayward_stated` **not** `rev_share_variance` (empty — §6.1) |
| Partners ⑦⑧ | `partner_payout_summary`, `commission_ledger.partner_fee_owed`, ⛔`ps_partner_payouts` |
| Brand & Product Perf | `commission_ledger`, `monthly_summary`, `product_eligibility`, `rate_schedule`, `rate_clock` (live 10/6/3 countdown), `china_verdict` |
| **Brand 360** (Deep) | ⛔`ps_brands`, `brand_contact_book`, `china_verdict`/`china_evidence_grid`, `commission_ledger`, `claim`, `refund_allocation`, `rate_schedule`, `deal_timeline` (ready-made timeline), `added_current` (Tim's rulings + rationale), `identity_provenance` (why-china), `brand_hubspot` (CRM link) |
| Exceptions | `product_eligibility`(nulls), `china_verdict`(unknown+revenue), `china_contention`, `wayward_reconciliation`, `open_questions` (+ base `ps_information_gaps`), `attribution_at_risk` (124 bleeding), `identity_provenance`/`health` (split-identity), freshness/invariants |
| **Statements** | `claim`, `statement_drift`, ⛔`ps_claim_statements`, `added_current`+`identity_provenance` (evidence packet), `rate_clock` (+ FAS jobs, §9 Sprint 3) |
| Refunds (tab) | `refund_allocation`, ⛔`ps_stripe_disputes`, ⛔`ps_stripe_credit_notes` ($42.9k outside the engine) |
| Excluded book | `excluded_partner_performance` |
| Counts (everywhere) | `lens_ps_china_companies` |

**High-value lenses the shipped app never reads (the CIP-data-mining review surfaced these, each with a
live count — surface them):**
- **`deal_timeline`** (2,833 rows) — the Brand-360 timeline *already exists*; **1,637 "collected-but-never-
  remitted-to-us"** = a recovery worklist; avg payment lag 1.8mo → a Overview KPI.
- **`rate_clock`** — the live 10/6/3 countdown (1,808 at 10%; **138 brands' 10% window closes ≤30 days**) →
  a "rate cliff" revenue-protection alert the tool completely lacks. (The plan's static `rate_schedule` has
  no countdown.)
- **`attribution_at_risk`** (124 brands `someone_else_earning`, +85 winnable) — names *which* of the
  164-brand `credited_other` dispute bucket is actively bleeding.
- **`identity_provenance` + `identity_health`** — **$709k of collected revenue rests on a weak
  `stripe_description` fuzzy match** → a claim-confidence badge on statements (the `feedback_split_identity_
  leaks_decisions` hazard, made visible).
- **`added_current`** (`ps_added_facts`, 751 rows) — Tim's **745 manual rulings + rationale + source** = the
  Brand-360 evidence panel ("why china, who ruled it, when"); where "Tim's word = top-rank evidence" lives.
- **`ps_stripe_credit_notes`** (23 notes, $42.9k incl. a $38.6k `order_change`) — Wayward credits sitting
  outside the money engine; a recon signal on §7.2/Refunds.
- **`ps_stripe_customers.delinquent`** (357) / `balance` / `address_country` (41 CN/HK) — a Stripe-native
  collections flag + extra nationality corroboration.
- **`wayward_stated` as a queue, not a tile** — **639 of 1,241 brands** have Wayward's stated fees-paid ≠ our
  recorded paid = a ranked reconciliation worklist (and the real source for §7.4's variance column).
- Plus the already-noted `refund_allocation`, `excluded_partner_performance`, `exclusion_status`,
  `china_companies`, `monthly_summary`, and the `ps_stripe_charges` card_country **as evidence display**
  (NOT a new recovery pool — 689 of the CN/HK-card brands are *already* ruled china; card_country only
  *shows why*, it doesn't add claims).

### 6.1 CIP-lens dependency register (a CIP-migration workstream, NOT app work) — **the biggest hole the review found**

The security spine denies the read role every base table (rule 11a), but six screens route straight at base
tables — so **4–5 cross-repo foundry-cip migrations are on the critical path for Sprints 1–3 and were
unscheduled.** (This re-imports the old `REPORTING-BUILD-PLAN §11` gap register that the "keep only the
spine + deploy" instruction silently dropped.) Each row = **one PS-scoped `lens_ps_*` view + a `GRANT SELECT
… TO ps_reporting_reader`**, built in foundry-cip (detached-master worktree, jos-sync discipline), verified
by a lens-contract test, *before* the dependent screen is built:

| # | Screen(s) blocked | Base table(s) | Deliverable (new lens or grant) | When |
|---|---|---|---|---|
| G1 | Exceptions §7.8 | `ps_information_gaps` | ✅ **RESOLVED — no cip add.** `lens_ps_open_questions` already exists (the aggregated ask-queue); repoint. `lens_ps_information_gaps` **does not exist** — the plan's §10 open item is closed. | 0a (doc) |
| G2 | Payments-In §7.4 | `ps_payment_events`, `ps_stripe_balance_transactions`, `ps_stripe_payouts` | `lens_ps_cash_ledger` (payments-in + payout/fee/net cash-recon), PS-scoped | Sprint 1 |
| G3 | Collections §7.3 | `ps_stripe_invoices` | `lens_ps_open_invoices` (open/`amount_remaining`/aging/`hosted_invoice_url`/`uncollectible`) — invariant check: 12,262 "paid" invoices carry $1.71M `amount_remaining` | Sprint 1 |
| G4 | Refunds §7.13 tab | `ps_stripe_disputes`, `ps_stripe_credit_notes` | `lens_ps_refund_events` (disputes + credit notes) | Sprint 2 |
| G5 | Partners §7.5 | `ps_partner_payouts` | grant via `partner_payout_summary` if it already covers, else `lens_ps_partner_payouts` | Sprint 2 |
| G6 | Brand-360 §7.7 | `ps_brands`, contacts | `ps_brands` header via a `lens_ps_brand_header`; contacts via existing `lens_ps_brand_contact_book` (1,401 rows, 386 WeChat) | Sprint 3 |
| G7 | Statements §7.10 | `ps_claim_statements` | read via `lens_ps_statement_drift` (already joins pinned rows) + a thin `lens_ps_statements_history`; **writes** go through the FAS API (§10.1), not the reader | Sprint 3 |
| G8 | Data-Health §7.1 | — | `lens_ps_source_freshness` lacks next-run/failure columns (old G4); extend it to carry `mode` + last-success heartbeat so the freshness pill can't false-green (§7.1) | Sprint 1 |

**Three naming/legacy corrections the review caught (apply in doc now — 0a):**
- **`lens_ps_information_gaps` DOES NOT EXIST** → use `lens_ps_open_questions` (+ base `ps_information_gaps`).
- **`brand_contacts` → `lens_ps_brand_contact_book`** (the base is `ps_brand_contacts`; the lens name differs).
- **⚠️ `lens_ps_china_commission` is a legacy TRAP — do NOT wire it into any money screen.** It computes a
  flat `commission_10pct_of_paid`, violating the 10/6/3 ladder (§5 rules 5–6). The engine is
  `lens_ps_commission_ledger`/`lens_ps_claim`. Flag `china_commission` for deprecation.
- **`rev_share_variance` is effectively empty** (0 of 2,271 payment events have |variance|>0.01) — §7.4's
  variance column must source from `wayward_stated`, not this.

---

## 7. The target screen set (each = purpose · role · depths · lenses · content · acceptance · mapping)

> Build pattern for every screen (from `REPORTING-FRONTEND-IMPLEMENTATION §4`): **`defineQuery` DAL fn
> (auth + scope + composed SQL + Zod DTO) → Server Component renders DTO → i18n strings → vitest (shape
> test + a scope-isolation test).** Every screen ships loading / empty / error / no-access states, en+zh,
> light+dark, an as-of badge, keyboard/focus a11y.

**7.1 Pipeline Overview** — *home, all roles · Glance(+mini Working)*. **Nine** stage cards, the §3 model
in order — **① Revenue generated (derived est.)** · ② Revenue billed · ③ Collected · ④ Commission earned ·
⑤ Paid to us · **⑥ Still owed** · ⑦ Owed partners · ⑧ Paid partners · **⑨ Net kept** — each with a period
value + **trend sparkline**; mini AR-aging bar; a month trend; an **alerts strip** (freshness + open-
exceptions count + a **rate-cliff count** from `rate_clock`: "N brands' 10% window closes ≤30d"). Lenses:
`monthly_summary, claim, partner_payout_summary, ar_aging, source_freshness, rate_clock, deal_timeline`.
*Accept:* every stage ties to a hand SQL check; backlog card == `sum(ps_claim_owed) china`; sparklines
render from `monthly_summary`; **population-consistency — the cards must NOT render as a single subtraction
chain across incompatible bases** (① ② are `brand_revenue` gross; ⑥ is `claim` net-and-floored). No `→`
arrow implies gross−net arithmetic (the F3/F4 trap; the acceptance tests *population compatibility*, not just
magnitude). *Maps to:* reframe Leadership + Finance homes into this.

**7.2 What Wayward Owes Us** (④⑤⑥) — *finance/owner · Glance+Working+Deep*. Per-china-brand owed → paid →
still-owed + aging; **Reconciliation tab** = `delta_status` buckets (**acknowledged_unpaid** = strongest
ask, **credited_other_unpaid** = the 164-brand negotiation, unacknowledged, paid_partial/settled) + the
`wayward_stated` cross-check; a **drift banner** (pre-statement). Deep = the per-brand claim "invoice"
(usage lines, refunds netted, payments applied). Lenses: `claim, ar_aging, wayward_reconciliation,
wayward_stated, statement_drift, commission_ledger, refund_allocation`. *Accept:* totals reconcile to
`lens_ps_claim`; each `delta_status` bucket count matches the lens; drift banner appears when a pinned
statement differs. *Maps to:* **rename the existing Commission Statement screen to this**; add the
stated-numbers cross-check + the Deep invoice.

**7.3 Collections** (③) — *finance/ops · Working*. Billed-but-not-collected: open invoices,
`amount_remaining`, aging of the uncollected, ranked chase list. Lenses: `commission_ledger` /
`ps_stripe_invoices`, `ar_aging`. *Accept:* the ranked list sums to the billed−collected gap; sortable by
overdue. *Maps to:* NEW.

**7.4 Payments In** (⑤) — *finance · Working+Deep*. Cash-received ledger: Wayward's payments to us, dated,
fee breakdown, against what was owed; rev-share stated-vs-computed variance; Deep = cash reconciliation
(payouts ↔ balance-transaction fees/net). Lenses: `ps_payment_events`, `ps_stripe_balance_transactions`,
`ps_stripe_payouts`. *Accept:* payment totals tie to `ps_payment_events`; variance column matches
`rev_share_variance`. *Maps to:* NEW (the shipped "cash this period" was deferred as gap G2).

**7.5 Partners — Performance & Payouts** (⑦⑧) — *finance/Rhea · Working+Deep*. Per partner: brands driven
+ revenue/collected generated, then `partner_fee_owed` → paid → still-owed; drill to per-brand×product.
Lenses: `partner_payout_summary, commission_ledger.partner_fee_owed, ps_partner_payouts`. *Accept:* per
partner still-owed ties to `partner_payout_summary`. *Maps to:* NEW (currently a single Finance tile).
*(The partner-**facing** row-isolated variant = V2, §10.)*

**7.6 Brand & Product Performance** — *all · Glance+Working*. Per brand × product: revenue, collected,
commission earned, **month trend**, which **10/6/3 rung**, eligibility/fee-rate, nationality; top/bottom
movers. Lenses: `commission_ledger, monthly_summary, product_eligibility, rate_schedule, china_verdict`.
*Accept:* GMV vs ad-spend never summed; the rung shown is the `mgmt_rate` ladder, NOT the client fee rate
(F1/F6). *Maps to:* **fix + extend the shipped Brand Performance** (relabel "Collected", add the rung,
add trends).

**7.7 Brand 360 / Account Lookup** — *CS especially, all roles · Deep*. ONE brand, everything: header
(name, nationality + evidence, partner, signup, disposition); financials (revenue/billed/collected/earned/
owed/paid); products + rates + **live rung countdown** (`rate_clock`); **contacts incl. WeChat**
(`brand_contact_book`); refunds; **the ready-made timeline** (`deal_timeline` — billings, payments, rulings,
reactivation, payment-lag — *already exists, no new SQL*); an **evidence panel** (`added_current` = Tim's
ruling + rationale + source; `china_evidence_grid` = the per-signal matrix incl. card_country as *why*; an
`identity_provenance` **confidence badge** if the brand's claim rests on a weak join); CRM deep-link
(`brand_hubspot`). Lenses: `⛔ps_brands`(→`lens_ps_brand_header` §6.1), `brand_contact_book,
china_verdict/china_evidence_grid, commission_ledger, claim, refund_allocation, rate_schedule, rate_clock,
deal_timeline, added_current, identity_provenance, brand_hubspot`. *Accept:* one brand's numbers match the
individual lenses; single join query (no N+1) with a single-`wayward_brand_id` predicate pushed down (per-
brand, so it **cannot use the tenant-global memo** — verify it doesn't scan the whole book, cf §7 perf);
a partner (V2) can only open THEIR brands. *Maps to:* NEW — the crown-jewel Deep view; **a stub route ships
in Sprint 0 so every brand-name link resolves (never a 404); filled in Sprint 3.**

**7.8 Exceptions / Needs-Attention** — *ops · Working*. The work queue: unknown-nationality-**with-revenue**,
missing fee-rate, no-partner-where-expected, attribution mismatch (`credited_other`) + **actively-bleeding
attribution** (`attribution_at_risk`: 124 "someone else earning", +85 winnable), payment-recon variance,
refund spikes, stale sync, **split-identity** (`identity_provenance`/`identity_health`: the $709k-on-fuzzy-
join risk), and the **ask-queue** (`open_questions` — 39 nationality-conflict questions already queued for
Tim, by `ask_who`/`ask_channel`/priority). Lenses: `product_eligibility`(nulls), `china_verdict`(unknown),
`china_contention`, `wayward_reconciliation`, `attribution_at_risk`, `identity_provenance`/`health`,
`open_questions`, freshness/invariants. *Accept:* each sub-queue count ties to its lens; empty-state per
sub-queue. *Maps to:* NEW (re-home the Nationality Review Queue as one tab here + a CS view).

**Nationality Review = a WRITE surface (RESOLVED, Tim 2026-07-21 — §10.2 #2 = option b).** The
"Confirm china / Keep not-china" buttons are **live**: a CS selection is a **hard verdict** — same authority
as Tim's word in chat — written to `ps_added_facts` through the **governed FAS write** (§10.1; NOT a bare
`app_*` action, because a verdict flips claim eligibility = money-critical). Requirements (per §5 rule 9):
the write records **reporting-engine provenance** (`asserted_by`=CS person, `source_ref`=`reporting-app`,
`asserted_at`) and **propagates across the company's sibling brand rows**; FAS re-verifies the actor is
CS/admin and re-applies the added-facts rules server-side; the change logs `nationality.ruled` both sides;
the verdict then flows through the normal lens (top-rank, one-directional). The ruling control is visible
only to CS/admin. *Maps to:* NEW write surface on the re-homed review queue — the first user of the FAS
write endpoint (§10.1), alongside statement-pin.

**7.9 Revenue & Billing** (①②) — *finance/ops · Working*. Per brand × product × month: revenue generated
(**derived GMV/ad-spend, labeled "derived (est.)"**) + Wayward billed; billing status; billed-vs-collected
gap. Lenses: `brand_revenue, commission_ledger, monthly_summary`. *Accept:* stage ① clearly labeled
derived; billed ties to the ledger. *Maps to:* NEW. *(True raw-GMV feed = §10 dependency.)*

**7.10 Statements & Reporting** — *finance/owner · Working+Deep*. **The deliverable — and it must be
*defensible*, not just a totals table.** A statement you hand Wayward is a negotiation weapon; a bare total
loses the argument. Four parts:
- **The evidence packet (Deep).** Each claimed brand embeds *why* it's owed: verdict + evidence
  (`china_evidence_grid`, card_country), **Tim's ruling + rationale** (`added_current`), the collected lines
  netted of refunds, the **rung clock** (`rate_clock`), payments applied, and a **claim-confidence badge**
  (`identity_provenance` — flag the ~$709k that rests on a fuzzy join *before* Wayward does).
- **A pre-pin data-quality gate.** Before a statement can be pinned it runs a checklist and **warns/blocks**
  on: stale sync (esp. the manual payment feed, §7.1), any claimed brand with `unknown` verdict + revenue,
  missing fee-rate, or an open drift. No statement goes out on a number the tool itself distrusts.
- **Pin = a governed write that freezes provenance, not just the total** (§10.1 FAS API). Pinning writes a
  `ps_claim_statements` row **and snapshots the derivation** (per-brand verdict/evidence/rate/lines that
  produced the number) so the claim is reconstructable months later. Sets the drift baseline.
- **A lifecycle that closes the loop** *(APPROVED — part of §7.14; ships with Statements in Sprint 3)*:
  draft → **sent** → acknowledged → paid/disputed, with **payment→statement linkage** ("did Wayward pay
  against statement #3?"). App-owned state (`app_statement_status`), audited, never touches CIP money math.
  Without this, the statement is fire-and-forget and reconciliation stays in spreadsheets.

Lenses: `claim, statement_drift, ⛔ps_claim_statements`(§6.1 G7)`, added_current, identity_provenance,
rate_clock, china_evidence_grid`. *Accept:* pinning creates a `ps_claim_statements` row + a frozen
provenance snapshot + a drift baseline; the data-quality gate blocks a stale/unknown-verdict pin; a generated
statement matches the live claim at pin time and shows the per-brand evidence. *Maps to:* NEW — **highest-
value gap.**

**7.11 Partners — light write (folded into the Partners page, 7.5).** Per Tim (decision 2): NOT a heavy
separate screen. The Partners page (7.5) gets a small admin affordance for people with the
**manage-partners** capability: **add a partner** (+ basic edits like set/override a commission rate,
map an alias). Writes go to `ps_partner_registry / ps_partner_credit / ps_partner_aliases` **through the
governed FAS API** (decision 1). *Accept:* a write appends an audit row in the same tx; a user without
the capability never sees the affordance and the FAS endpoint rejects them. *Maps to:* NEW (small).

**7.12 User & Access Admin — THE ACCESS MODEL** *(internal admin · WRITE on the app's own `app_*` DB)*.
Where any admin onboards the team and controls who sees what. Designed per Tim 2026-07-22 (simplified —
**no money gate**, role-based, multi-admin, no invitations).

*Principle:* **role-based, assigned per person, admin-managed. Default-deny — a page you're not granted
is invisible (absent from nav; direct URL → 404, not a 403 that reveals it exists).**

- **Add a user by email, no invitation.** An admin types the person's Google email → they're a user
  (`active` immediately). Nothing is sent; the person just signs in with Google and their access is
  already there. Any admin can add / edit / remove users.
- **Roles are the page bundles.** Each role grants a defined set of pages. **Every screen is a grantable
  page — including `Admin` (User & Access) and `Activity Log`** (Tim 2026-07-21, §10.2 #4: "I can say they
  can see the admin or the activity log or not"). Internal roles: **Admin · Finance · Ops · CS ·
  Partner-Manager.** When adding/editing a user, the admin **assigns one or more roles**; access = the
  **union** of their roles' pages. A per-page fine-tune per person is available for exceptions, but roles are
  the primary lever (Tim: "select what roles they have when I add them").
- **Multi-admin.** The **Admin** role reaches this screen and manages users/roles — **including granting
  Admin to someone else.** Make James an admin → James can then add users and assign roles too.
- No capability layer, no money gate (dropped 2026-07-22). Access is purely **person → roles → pages**.

*Guardrails (RESOLVED — Tim 2026-07-21, §10.2 #3):*
- **Last-admin guard (non-bypassable).** The system refuses to remove or demote the *last* admin (and
  handles the two-admins-demote-each-other race) — otherwise nobody can reach the admin surface and recovery
  is only via `seed-allowlist.cjs` / direct DB.
- **Tim is the SOLE non-demotable owner.** Only Tim (`owner` flag) cannot be demoted or removed by anyone.
  **Every other admin — Van included — is a normal admin** who can be demoted/removed by another admin.
  Tim's un-removable ownership is the backstop that makes the rest safe: whatever an admin does, Tim can
  always walk it back.
- **Editing the role→page map is admin-allowed but fully audited (detection over prevention).** Remapping is
  powerful (an admin could add the `admin` or `activity-log` page to another role) — but per Tim's model
  admins *do* control what people see, so it stays admin-editable. The guardrails are: every map edit emits
  **`admin.role_pages_changed`** (§7.13), granting the `admin` page **is** the make-admin action (logged as
  such), and Tim (sole owner) can reverse anything. No silent, unlogged escalation is possible.
- **Roles are a fixed, migration-controlled set** (`admin, finance, ops, cs, partner-manager` — the CHECK
  constraint stays). Admins edit the *map* (role→pages) and *assignments* (person→roles); admins do **not**
  invent new roles. `referral` stays reserved for the external-lock floor (below), never internal.
- **The external-lock floor is preserved (H7 — a real leak risk).** Today `referral = locked` wins over any
  internal grant; that floor is the *only* thing keeping partners out while V2 isolation (RLS + partner-safe
  lens + email→partner identity) is unbuilt. The union model keeps a **non-overridable "external identity →
  hard-deny ALL internal surfaces"** floor, and **adding any partner is gated on the §11 scope-isolation
  test actually passing first.**
- **Add-by-email = warn-and-confirm, not a hard domain lock.** Tim signs in with a personal Gmail, so a
  `@project-silk.com` lock won't work — instead a typo'd/unexpected address triggers a confirm step, and
  **admin grants get extra friction** (a typo must not silently mint a stranger admin).
- **Per-person fine-tune precedence = deny/lock wins** (matches the shipped `effectiveGrant`): an explicit
  per-person deny overrides a role grant; a lock is absolute. State it so allow+deny never silently leaks.
- **Drop the vestigial `invited` status.** Add-by-email is active-immediately; `requireSession` admits only
  `active`, so `invited` is dead state that would silently block sign-in. Remove or repurpose it.

*The admin UI:* a **People list** (name · email · roles · last-active) → **Edit person** (role
checkboxes + optional per-page fine-tune + Remove) · **Add person** (email + role checkboxes → save;
live on their next sign-in). Every change writes to the Activity Log (§7.13).

*Enforcement — authorize at the ROUTE, not only in the seam (governance H4).* The shipped `(app)` layout
only **authenticates** (`requireSessionOrRedirect`); per-surface authz lives *inside* `defineQuery`, so a
page enforces access **only if it happens to call a guarded DAL** — a static/derived page, or one that
forgets, is viewable by any authenticated user, and "hidden nav + 404" can't be delivered by "extend the
seam's deny path" alone. So wire **all four**: **(1)** a **route-level `path → surface` assert** in the
`(app)` layout (or per-segment) that decides the 404; **(2)** nav renders only granted pages; **(3)** the
DAL keeps `assertCan` as true belt-and-suspenders (do **not** throw `notFound()` from inside the seam — it
couples routing to the DAL and mis-fires on composed pages that call one allowed + one denied DAL → partial
404); **(4)** ship a **`not-found.tsx`** so an ungranted surface renders **byte-identical to a genuinely
missing route** (today the deny path is a *500*, and "exists-but-forbidden" must be indistinguishable from
"doesn't exist"). Schema: `app_users` + `app_user_roles` (exist); the role→page map in a small seeded,
admin-editable `app_role_pages` table (replaces the hard-coded `ROLE_SURFACE` matrix); a per-person override
table (proposed `app_permissions`, carrying `locked`/`none`) for the fine-tune, deny-wins.

*Write path:* app-RBAC writes hit the app's OWN `app_*` Postgres via Next **server actions** (re-check
`admin` + zod + a log row in the same tx) — NOT the CIP read role, NOT the FAS API (that's only for CIP
money-input writes).

*Seed (Sprint 0b):* **Tim = owner-Admin (the sole non-demotable owner); Van = Admin.** **James, Rhea,
Sheila, Samantha** added; Tim assigns each their roles in the UI. No one sees a page until a role grants it.

*Maps to:* **reframe + extend the shipped "People & Permissions" Admin** — keep the read model, turn on
the writes (audited server actions), replace the fixed per-role matrix with admin-assigned roles + the
`app_role_pages` map, add hidden nav + 404, build the People-list / Edit-person / Add-by-email UI.

**7.13 Activity Log & Report Builder** *(internal admin · the usage/audit trail — Tim: "very, very
important")*. Everything meaningful that happens is logged **by code** to Postgres, and admins can filter
and **download reports** of who used the system, for what, when. Best practices researched 2026-07-22
(Graylog / Google-Cloud audit-logging / ZenGRC / Sonar — see the chat report for links).

*What is logged (server-side, standardized action verbs):*
- **Auth:** `auth.login` · `auth.login_failed` · `auth.logout`.
- **Access/admin:** `admin.user_added` · `admin.user_removed` · `admin.role_granted` · `admin.role_revoked`
  · `admin.made_admin` · **`admin.role_pages_changed`** (editing the role→page map — the highest-privilege
  action, §7.12).
- **Usage:** `page.view` (who opened which screen, when) · `export.download` (who downloaded what).
- **Money-input writes:** `statement.pinned` · `partner.added` · `partner.rate_set` (also logged on the
  FAS side; the app logs the initiating actor + action).

*Schema — `app_activity_log`:* `id` · `at timestamptz` **(UTC)** · `actor_email` · `actor_roles text[]` ·
`action text` (the verb) · `target text` (the page / user / brand / statement id) · `outcome
('success'|'failure')` · `ip inet` · `user_agent text` · `detail jsonb`. A **retention policy** on the noisy
`page.view` stream (configurable; e.g. 12 months hot).

*Append-only must be ARCHITECTED, not asserted (governance H3 — the existing `app_audit_log` is NOT actually
immutable: it's a plain table whose grants the app role bypasses because that role owns it).* Do it for real:
**create `app_activity_log` owned by a migration/admin role, `GRANT INSERT` (only) to the app role, and
verify the app role is neither the table owner nor a superuser** — otherwise the grant is a no-op. Belt-and-
suspenders: a `BEFORE UPDATE OR DELETE` trigger that `RAISE`s. **Wording:** grant-based append-only is
*tamper-resistant from the app* — Tim/Van with DB access can still edit — so call it that, **not
"tamper-evident,"** unless we add a hash-chain or off-box log shipping (a possible V2). Apply the same fix to
`app_audit_log`.

*The Report Builder (admin UI):* filter by **person · action type · date range · page/target · outcome**;
a results table; **Download CSV** of the filtered set — literally "who used the system for what, when."
Plus a per-person activity view and a per-page "who viewed this" view.

*Enforcement:* logging is **cross-cutting, not opt-in** — but **`page.view` logs at the route/layout
boundary keyed by pathname, NOT inside the data seam** (governance M1): the seam's cache short-circuits on a
hit (so seam-logging under-counts) and its grain is per-DAL-call (a multi-query page — Brand-360, Exceptions
— would emit several rows per navigation). Route-boundary logging is once-per-page and cache-independent.
Every log INSERT is **best-effort** — a logging failure must **never** fail the request. Exports log
`export.download`; server actions log their `admin.*` verb in the same tx as the change.

*Who reads it = a grantable page (RESOLVED, Tim 2026-07-21 — §10.2 #4).* The activity log captures
employee-surveillance PII (`actor_email`, `ip`, `user_agent`, brand/person targets), but Tim's model is
simple: **`Activity Log` is just another page in the access map** — an admin grants "can see the Activity
Log" per person/role, exactly like any screen (§7.12). No special owner-lock. IP/user-agent **are** captured
(they're useful in the trail); retention keeps a stated rationale on the `page.view` stream. *(This is Tim's
risk posture — visibility is controlled by the same page-grant machinery, backed by the append-only table +
his sole ownership, not by hard-wiring the reader set.)*

*Accept:* every login / page view / export / admin change lands in `app_activity_log`; **anyone granted the
Activity Log page** can filter + download CSV; a person **without** that page can't reach it (hidden nav +
404); the table **rejects UPDATE/DELETE at the DB level** (verified: app role is not owner/superuser).
*Maps to:* NEW — expands `app_audit_log` (RBAC-only today) into the full activity log + the Report Builder
screen (itself a grantable page).

**7.14 Recovery workflow-state layer** *(app-owned writes · **APPROVED, Tim 2026-07-21 — §10.2 #1**)*.
**The gap the blind-spots review found:** the reframe fixes the *screens*, but the plan keeps
the app **read-only on CIP** — so the actual recovery *work* never lives in the tool. The chase status
("called X, promised pay-by Y, follow up Z"), the **164-brand dispute** negotiation (currently just a bucket
total), which exceptions were **worked vs dismissed**, and "did Wayward pay against statement #3" all stay in
spreadsheets and WeChat — **the exact failure this rebuild exists to end.** The activity log records that you
*looked*, not what you *decided*.

*The fix is small and already-permitted* — the **same audited server-action pattern already blessed for RBAC
(§7.12) and the activity log (§7.13)**, on the app's OWN `app_*` DB, **never touching CIP money math**:
- `app_chase_notes` — per-brand/per-statement chase log (contact, promised-pay date, next-follow-up, owner).
- `app_dispute_state` — per-line state for the `credited_other`/`attribution_at_risk` negotiation (open /
  contesting / conceded / won), so the 164-brand lever is *worked*, not just counted.
- `app_exception_state` — dismiss/snooze/assign an exception so a worked queue empties.
- `app_statement_status` — the §7.10 statement lifecycle (draft→sent→ack→paid/disputed) + payment linkage.
- **An assignee/owner** on each queue (chase, exceptions, review) — RBAC grants *visibility*, but nobody
  *owns* a queue today.

*Everything here is app-state ABOUT CIP data, not a CIP write* — money numbers stay live-read from the
lenses; only the human workflow layer is writable, audited, reversible. **This is the line between a dashboard
and a recovery tool.** It slots as **Sprint 2–3** (chase/dispute after the money screens exist), the
statement-lifecycle piece merges into §7.10, and it opens the door to **event alerts** (Wayward payment
landed, a brand aged past 90d, a rate-cliff) instead of the passive-only freshness pill.

**Supporting:** **Refunds** (tab in Payments/Brand-360 — `refund_allocation` + disputes + `credit_notes`) ·
**Data Health** (the shipped Freshness, extended with coverage % + invariant status — **keyed on the sync
heartbeat + `mode` (scheduled/manual/on-demand) + the "unowned risk" flag, NOT `max(data timestamp)`**: a
manual, multi-day-stale feed must read RED, not green — the manual **Jake payment feed** (what Wayward paid us,
behind `ps_payment_events`) was found **8 days stale** and a naive pill would hide the single biggest risk to
a claim number) · **Excluded-partner book** (`excluded_partner_performance` — Eric et al., walled off, never
in our claim).

**Cross-cutting (apply to all):** **trends** (sparklines/month lines off `monthly_summary`), **export**
(wire the "Export ▾" to real CSV/PDF download — currently an inert `<span>`), **depth tabs**
(Glance/Working/Deep), **per-role nav** (RBAC-filtered, no dead links — a disabled item with a tooltip,
never a 404), **bilingual from the start** (en+zh first-class — the staff are Chinese-speaking; §9 Sprint 0a,
not a Sprint-4 polish — with a **bilingual termbase** for the terms of art), plus an **affordances backlog**
(global brand quick-search / ⌘K → Brand-360; contact-to-action mailto/copy-WeChat on Brand-360+chase;
permalinks/deep-links to a brand or filtered view; **"derived (est.)" labeling on ALL provisional numbers**,
esp. partner payouts on the 5% default until Rhea's roster lands; saved views + bulk-select for export/
statement; clickable `hosted_invoice_url` chase links) and, for **scale**, server-side paging/virtualization
on the thousand-row tables and a **responsive** Glance+chase for mobile (the 10s `statement_timeout` will
bite Brand-360/Exceptions otherwise — set per-screen query budgets).

---

## 8. The correctness fixes (do these FIRST — Sprint 0a)

| # | Defect | Fix (what "done" looks like) | Acceptance test |
|---|---|---|---|
| **F1** | Brand-Perf "Collected" column is **gross billed** (`usage_fee_billed`), overstated ~$139k/13%; `brand_revenue` has no `usage_collected` | Relabel the column to what it is (**"Usage billed"**), or source true collected from the money engine; never call `brand_revenue` "collected" | column value == `sum(usage_fee_billed)` under a "billed" label; grep: no "collected" alias on a `brand_revenue` query |
| **F2** | "China brands" = **1,167** on Commission, **2,351** on 3 screens; the RULES grain (**1,951** companies) shown nowhere | Use `lens_ps_china_companies` for every count-said-out-loud; label populations ("claim-bearing", "with a verdict") where a subset is intended. **⚠️ This is a DISPLAY-count swap ONLY — do NOT re-scope the money DALs by company.** The money correctly aggregates at **brand × product** grain (verdict-scoped); preserve that grain-split (money = brand×product, nationality = company) — swap only the shown *count* | one number for "the China book" app-wide, == `lens_ps_china_companies`; subset labels explicit; the money SUMs are unchanged (still brand×product) |
| **F3** | Finance waterfall **splices** `brand_revenue` (all-china gross "billed") into the `claim` (claimable net) chain — false continuity | Don't render incompatible-population stages as one flow; separate the data-asset revenue from the money-engine stages, or gate/label both identically | the pipeline stages come from one consistent population/basis; no gross→net mixing in a single arrow chain |
| **F4** | Finance `earned → paid → owed` arrows imply a subtraction; $32,943 − $23,286 ≠ $13,942 (per-brand floor) | Drop the `→` subtraction framing; show the three as related-but-not-additive figures with a one-line note re the per-brand floor | no rendered arithmetic that doesn't reconcile; the floor is explained |
| **F5** | "Aged 90+ days" filters the **6+ month (180+)** bucket only; drops the 3–6mo bucket | Label the actual bucket ("180+ days / 6+ months"), or aggregate the true 90+ (3+ months) set | label matches the bucket(s) summed; if "90+", it includes 3–6mo |
| **F6** | The 10/6/3 rung is never shown; the "Fee rate" column is the **Wayward client fee rate** | Surface the `mgmt_rate` rung (from `rate_schedule`/ledger); relabel the client-fee column so it can't be mistaken for our commission | a rung chip (10/6/3) exists; the client-fee column is labeled as Wayward's |
| **F7** | RBAC ships a fixed **per-role** matrix with no admin control and no hidden nav | Replace with the **admin-managed, role-based, per-person model** (§7.12): add-user-by-email (no invite), assign roles → pages, multi-admin, default-deny, **hidden nav + 404** for ungranted pages, a real admin UI. Onboard the team through it | any admin can add a user + assign roles + make another admin; an ungranted page is absent from nav + 404s on direct visit; every change is logged |

---

## 9. Sprints (sequenced, drift-proof — each maps 1:1 to a PM sprint in step 2)

> Each sprint below has **Goal · Scope · Depends-on · Acceptance · Tests · Escalate-if.** Ordering =
> highest recovery value + dependency-safe. Sprints are sized so the autonomous BUILD run can execute one
> without hitting an escalation mid-flight.

> **Sprint 0 was three sprints in one hat** (correctness + full RBAC + full audit + reframe) — the review
> flagged it violates this plan's own "sized so the BUILD run executes one without escalation" rule. **Split
> into 0a (correctness + reframe — lens-backed, autonomous-safe, ships trust fast) and 0b (auth + audit +
> route authz — the highest-blast-radius work, HUMAN-REVIEWED, not autonomous-first).** CI moves into 0a.

**Sprint 0a — Correctness & foundation reframe** *(lens-backed only — no new auth, autonomous-safe).*
*Goal:* the app stops lying and the shell becomes the pipeline. *Scope:* **(a)** F1–F6 correctness fixes
(§8); **(b)** the three §6.1 lens-name corrections (information_gaps→open_questions; brand_contacts→
brand_contact_book; flag china_commission do-not-wire) — doc/read-map only; **(c)** replace the flat
role-home nav with the role-filtered pipeline nav; collapse Leadership/Finance/CS homes → one **Pipeline
Overview** (7.1, all nine cards, population-consistent); rename Commission Statement → **What Wayward Owes
Us** + add the `wayward_stated` cross-check; **(d)** a **Brand-360 stub route** so brand-name links never
404; **(e)** **en+zh first-class** + the bilingual termbase (not deferred); **(f)** **stand up CI** (typecheck
+ lint + the build-check + money-SUM + count-grain tests on every push — governance H6: do NOT wait for
Sprint 4, since 0b rewrites auth). *Depends:* none. *Accept:* Overview stages tie to lenses + are
population-consistent; counts use `china_companies` (display-only, money grain unchanged); no gross-labeled
"collected"; the freshness pill keys on the heartbeat/mode; CI is green and blocking. *Tests:* money-SUM,
count-grain, the 6 fix checks, build-check. *Escalate-if:* a lens for a stage card is missing/changed.

**Sprint 0b — Access model, activity log & route authz** *(HUMAN-REVIEWED — the security-critical subsystem;
§10.2 #3–#4 are now decided, but keep a human in the loop on the auth/audit build rather than running it
fully autonomously).* *Goal:* any admin can onboard the team safely, and everything is logged immutably.
*Scope:* **(a)** the **User & Access Admin** (§7.12, = F7) — add-user-by-email (warn-confirm), assign
roles → pages (**every screen a grantable page, incl. `Admin` and `Activity Log`**), multi-admin **with the
last-admin guard + Tim as the SOLE non-demotable owner + audited role-map edits (`admin.role_pages_changed`)**,
**route-level authz + `not-found.tsx` (byte-identical 404)**, the People-list/Edit-person UI, audited
server-action writes, the `app_role_pages` map + `app_permissions` override (deny-wins), the fixed
migration-controlled role set, drop the `invited` vestige, the **external-lock floor**, and the seed (**Tim =
owner-Admin, Van = Admin**; James/Rhea/Sheila/Samantha added); **(b)** the **Activity Log + Report Builder**
(§7.13) — `app_activity_log` **architected append-only** (separate owner role + INSERT-only grant + trigger;
app role verified non-owner), route-boundary best-effort `page.view` + `export.download` + `admin.*` (incl.
`admin.role_pages_changed`) logging, and the filter/**CSV download** UI **behind the grantable `Activity Log`
page** (this CSV export is in-scope now even though general "Export ▾" wiring is Sprint 4). *Depends:* 0a.
*Accept:* any admin can add a user + assign roles + make another admin; **the last admin cannot be removed;
Tim cannot be demoted by anyone; remapping the admin page is logged**; an ungranted page is invisible + 404s
byte-identically to a missing route; every login/page-view/export/admin-change lands in `app_activity_log`;
**the table rejects UPDATE/DELETE at the DB level**; only a person granted the Activity Log page can download
the CSV. *Tests:* the access truth-table (role→page, hidden-nav, route-authz, scope-isolation, last-admin
guard, Tim-non-demotable, external-lock), the activity-log test (each verb; DB-level immutability;
Activity-Log-page-gated Report Builder). *Escalate-if:* the `app_*` schema needs a migration touching a
shared contract; the app role turns out to own the log table.

**Sprint 1 — Core recovery money (+ the first CIP lenses + the FAS write-endpoint spec).** *Goal:* you can
see and reconcile the whole owed picture. *Scope:* the **§6.1 CIP-lens workstream G2/G3/G8** (build
`lens_ps_cash_ledger`, `lens_ps_open_invoices`, extend `source_freshness` — in foundry-cip, detached-master
worktree, lens-contract tested) **as the gating prerequisite**; then finish **7.2** (recon buckets + drift +
the Deep per-brand invoice + the identity-confidence badge) · **7.3 Collections** (delinquent flag +
clickable invoice links) · **7.4 Payments-In** (variance from `wayward_stated`, not the empty
`rev_share_variance`; cash-recon Deep). **Also: author the FAS money-write contract SPEC** (§10.1) so Sprint
3 has something to call. *Depends:* Sprint 0a/0b. *Accept:* per §7 each; scope-isolation tests pass; the new
lenses pass their contract test. *Escalate-if:* a §6.1 lens needs a schema change beyond a view+grant.

**Sprint 2 — Operations & performance (+ the approved workflow-state).** *Scope:* the **§6.1 G4/G5 lenses**;
then **7.5 Partners** (perf+payouts) · **7.6 Brand&Product** (fixed + trends + the `rate_clock` rung) ·
**7.8 Exceptions** (all sub-queues incl. `attribution_at_risk` + split-identity + the ask-queue; re-home the
review queue) · **7.9 Revenue&Billing** · **Excluded book** · **Refunds tab** (+ `credit_notes`); and the
**§7.14 chase / dispute / exception workflow-state** (APPROVED — app-owned, audited server actions on
`app_*`). *Depends:* Sprint 0a/0b, Sprint 1 lenses. *Accept:* per §7; every count labeled;
population-consistent; a worked exception/chase persists across renders. *(The nationality-ruling write on
the re-homed review queue depends on the FAS endpoint (Sprint 3) — ships read-only here, live in Sprint 3.)*

**Sprint 3 — Brand 360 + Statements + Nationality-ruling write + the FAS endpoint + FAS reporting.** *Scope:*
the **§6.1 G6/G7 lenses**; **build the governed FAS write endpoint** to the Sprint-1 spec (its own CIP write
credential, server-side re-validation of money rules AND the added-facts/provenance/propagation rules, actor
re-verification, idempotency, dual-side audit) **before** the writes that need it; then the three write
surfaces + the Deep view: **7.7 Brand 360** (the Deep join; every brand-name links here) · **7.10 Statements**
(the defensible evidence packet + pre-pin data-quality gate + provenance-freeze pin + the approved lifecycle
`app_statement_status`) · **the §7.8 Nationality-ruling write** (CS selects china/not-china → `ps_added_facts`
via FAS, with reporting-engine provenance + sibling-row propagation; go-live of the buttons that shipped
read-only in Sprint 2) · the **FAS report jobs** (monthly Wayward + per-partner statements, weekly collections
+ review queue, daily sync digest — off the lenses, per `REPORTING-FRONTEND-IMPLEMENTATION §6`). *Depends:*
Sprints 0–2; the §10.1 contract (approved). *Accept:* a CS ruling writes an `added_fact` with app-source
provenance, propagates to sibling rows, logs `nationality.ruled` both sides, and the verdict lens reflects it;
a statement pin freezes provenance. *Escalate-if:* the FAS contract build surfaces a rule the endpoint can't
re-validate server-side.

**Sprint 4 — Polish + export + depth + external V2 groundwork.** *Scope:* wire the general **export** (CSV/
PDF) across screens · finish **depth tabs** · **Partners Admin** light write (7.11 — after Tim's design riff)
· the **zh native-review gate** *before any external exposure* (internal zh already shipped in 0a) · e2e/
Playwright + branch protection (CI itself landed in 0a) · responsive + server-side paging on the heavy
tables. **External Wayward/partner surfaces stay V2** pending the data work in §10.

---

## 10. Dependencies, data gaps & decisions for Tim

**Data/lens gaps (CIP-side — block specific screens, not the whole build):** the full **§6.1 register** now
schedules these as a CIP-migration workstream. Highlights:
- **The base-table/read-role wall (§6.1) — the biggest hole:** 4–5 screens route at base tables the read role
  can't SELECT; each needs a PS-scoped lens + grant, built before its screen. Threaded into Sprints 1–3.
- **Partner isolation (V2 blocker):** the partner-safe lenses (`lens_ps_partner_statement` etc.) were
  **dropped in cip_110 and not rebuilt**, and there is **no email→partner→brand identity binding**
  (partner_id is an alias-heavy slug). Pointing partner screens at `commission_ledger` would **leak PS
  margin**. → V2 needs a new partner-safe lens + an identity table + the design riff. *This is why the
  custom-vs-Metabase-Pro rationale is unrealized in v1 — acknowledged, not a defect to fix in the app.*
- **Raw GMV stage ①:** Stripe lines are fee-lines only; GMV is **derived** (`usage_fee ÷ client_fee_rate`;
  rate populated 4674/4674). Ship derived-labeled; a true raw feed (Wayward/Amazon) is a follow-on ingest.
- **Coverage/exceptions lens — RESOLVED:** `lens_ps_information_gaps` **does not exist**; use the existing
  `lens_ps_open_questions` (+ base `ps_information_gaps`). No cip add needed (§6.1 G1).

### 10.1 The governed FAS money-write contract (APPROVED, Tim 2026-07-21 — §10.2 #5; design in Sprint 1)
Decision 1 routes every CIP money-critical write through "a governed FAS API." **Three write actions ride it:
(i) statement pin (§7.10), (ii) partner economics — add/rate (§7.11), and (iii) CS nationality rulings
(§7.8) — a verdict flips claim eligibility, so it is money-critical and goes through the same doorway, NOT a
bare `app_*` action.** Tim's plain-terms description (from chat) *is* the sign-off; the contract specifies:
**(1)** how the reports app authenticates to FAS (a scoped **service token**, not the app's reader role);
**(2)** actor propagation — the initiating user + roles travel to FAS and are **re-verified against app-RBAC
on the FAS side** (e.g. FAS confirms the ruler is CS/admin), not trusted; **(3)** **idempotency** (a retried
pin / add / ruling can't double-write); **(4)** **FAS re-validates the rules server-side** — for money: count-
grain, net-of-refunds, money-as-string, the per-brand `ps_claim_owed` floor; **for a nationality ruling: it
writes `ps_added_facts` with reporting-engine provenance (`asserted_by`=CS person, `source_ref`=`reporting-
app`, `asserted_at`) and PROPAGATES across the company's sibling brand rows** — never trusting numbers/flags
the app sends; **(5)** FAS uses its **own** CIP write credential; **(6)** **dual-side audit** (the app logs the
initiating actor + action — `statement.pinned` / `partner.added` / `nationality.ruled`; FAS logs the committed
write). This is the highest-stakes boundary in the system. *Van + I detail it in Sprint 1 (task); it is built
in Sprint 3 before any screen that writes.*

**Decisions — RESOLVED (Tim, 2026-07-22; see §0):**
1. ✅ Write-surface path = **(A) governed FAS API** (contract in §10.1).
2. ✅ Partners = **one page + light add-partner write** (not a heavy admin screen).
3. ✅ Raw GMV = **ship derived**.
4. ✅ External Wayward view = **deferred; kept as a PM backlog item** (do NOT build in v1, do NOT drop).
5. ✅ Access model = **admin-managed per-person page grants + hidden nav** (§7.12). *(Corrected: "+ money
   gate" was a stale leftover — there is **no money gate**, per §0.5/§5.10/§7.12.)*

### 10.2 DECISIONS — RESOLVED (Tim, 2026-07-21; the four-reviewer pass)
> All six are decided and **baked into the plan** (nothing here is open). Two changed my recommendation —
> #2 (Tim chose in-app ruling) and #3 (Tim-only owner). Where a decision changed a screen or a rule, the
> section is edited to match (cited below).

1. ✅ **Ship the §7.14 recovery workflow-state layer — YES.** App-owned chase notes / dispute state /
   exception state / statement lifecycle, audited, never touching CIP money. Slots Sprint 2–3. (§7.14 now
   APPROVED; PM scope active.)
2. ✅ **CS rules nationality IN-APP — option (b)** *(Tim overrode the read-only rec).* A CS selection is a
   **hard verdict** to `ps_added_facts` via the governed FAS write (§10.1), same authority as Tim's chat
   word, carrying **reporting-engine provenance** and **sibling-row propagation**. (Changed §5 rule 9;
   §7.8 is now a write surface; §10.1 write action (iii).)
3. ✅ **Tim is the SOLE non-demotable owner** *(not Tim+Van).* Everyone else — Van included — is a normal
   demotable admin; the last-admin guard prevents zero-admins. *Notify-on-admin-grant kept as a light default
   (a heads-up, not a second-party approval) — Tim can veto.* (§7.12 guardrails.)
4. ✅ **Activity Log = a grantable page**, not owner-gated. An admin grants "can see the Activity Log" per
   person/role like any screen; IP/UA are captured in the trail; retention rationale on `page.view`. (§7.13.)
5. ✅ **FAS money-write contract — APPROVED** (the six requirements; Tim signed off on the plain-terms
   version). Covers statement pin + partner economics + nationality rulings. Van + I detail it in Sprint 1,
   built Sprint 3. (§10.1.)
6. ✅ **The $12,035→$13,922 move — closed.** Tim has seen it; it's legit (drift / sync recovery), no action.

**Still deferred to V2 (data-gated, backlog in PM — not v1 decisions):**
- **Partner-facing logins** (row-isolated) — needs the rebuilt partner-safe lens + the email→partner
  identity binding + a partner-design riff + the **external-lock floor** proven by a passing isolation test
  (§7.12/H7). External Wayward portal sits here too.

---

## 11. Testing strategy (mandatory per screen)

- **Unit:** every DAL fn gets (1) a DTO **shape test** and (2) a **scope-isolation test** (a partner/limited
  session cannot read another partner's/brand's rows — matters now for the RBAC seed, load-bearing for V2).
- **Contract:** a `zod.parse` **lens-contract test pinned to the migration head** — fails if a lens column
  the app depends on changes.
- **Money:** the money-SUM test (no JS money arithmetic), the count-grain test (`china_companies`), the
  net-of-refunds check.
- **Access:** the role→page truth-table (a user sees exactly their assigned roles' pages, an ungranted
  page 404s **at the route boundary, byte-identical to a missing route**, multi-admin works, add-by-email
  creates an active user, **the last-admin guard holds, Tim (sole owner) can't be demoted by anyone, a
  role-map edit emits `admin.role_pages_changed`, the `Activity Log` page gates the Report Builder, the
  external-lock floor denies an external identity every internal surface**).
- **Activity log:** every logged verb (`auth.*`, `page.view`, `export.download`, `admin.*` incl.
  `admin.role_pages_changed`, `statement.pinned`, `partner.added`, `nationality.ruled`) writes a row; the
  table rejects UPDATE/DELETE; the Report Builder filter + CSV download works and is gated by the grantable
  `Activity Log` page (not hard-wired to admin).
- **Nationality-ruling write (§7.8):** a CS ruling writes `ps_added_facts` with `source_ref=reporting-app`
  provenance, propagates across the company's sibling brand rows, logs `nationality.ruled`, and a non-CS/admin
  user has no ruling control; FAS rejects a ruling from an unauthorized actor.
- **Build-check:** no component imports the DB client; no `"use client"` imports `@/server/*`; dev-bypass
  hard-refused in prod.
- **Activity-log immutability:** a DB-level test that `UPDATE`/`DELETE` on `app_activity_log` is refused for
  the app role (proves append-only is architected, not just granted — governance H3).
- **CI stands up in Sprint 0a (governance H6 — NOT Sprint 4):** typecheck + lint + tests + build-check on
  every push, green-and-blocking, *before* 0b rewrites auth. Branch protection + E2E follow in Sprint 4.
- **E2E (Sprint 4):** Playwright — login → each screen renders → no 404s → export downloads.

---

## 12. What happens after this doc (the process, so we don't drift)

1. **Doc-hygiene (do with this commit):** remove the wrong "superseded" banner on
   `REPORTING-FRONTEND-IMPLEMENTATION.md`; add a "superseded for screen set → see REPORTING-REBUILD-PLAN"
   banner to `REPORTING-BUILD-PLAN.md`; update `PROGRAM.md` P4 to reflect *shipped-Phase-0 + this
   correction plan* and add a DECISION OF RECORD ("2026-07-22: reporting re-anchored to the operational
   pipeline; role-home build corrected"). **All via the detached master worktree, pathspec-scoped.**
2. **PM buildout:** kick off P4 in PM properly — this plan → sprints → **a task per §7 screen / §8 fix /
   §9 sprint item, each with a full note** (goal, lenses, acceptance, escalate-if) so the board *is* the
   plan. Nothing built off-board again.
3. **4-subagent review — ✅ DONE (2026-07-21).** Coherence, CIP-data-mining, governance/security, and
   blind-spots reviewers pressure-tested the plan against the shipped code + the lenses. Sound findings folded
   in (§6.1 lens workstream, §7.12/§7.13 hardening, §10.1 FAS contract, the 0a/0b split, CI-in-0a, the data
   adds, §7.14 workflow-state); **six items surfaced to Tim in §10.2.**
4. **Then, and only then:** the autonomous BUILD run executes **Sprint 0a first (correctness — autonomous-
   safe)**. **Sprint 0b (auth/audit) is HUMAN-REVIEWED and gated on §10.2 #3–#4** — the security review
   recommends *not* handing the highest-blast-radius subsystem to the autonomous run before those answers.

---
*Plan of record for WCC P4 reporting. Supersedes the role-home screen set. Junior entry point: §1 → §3 →
§5 → §6 → §7 → your sprint in §9.*
