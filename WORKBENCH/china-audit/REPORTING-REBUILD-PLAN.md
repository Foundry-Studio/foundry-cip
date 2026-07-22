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
shown) **and** the RBAC default (restrictive matrix vs the locked full-access-seed decision).

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
9. **Verdict semantics** (RULES): china / not_china / unknown; `unknown` is a queue, never a denial;
   surfacing a verdict never changes it (review is read-only in the app; rulings happen in the data
   layer). Evidence types: only Tim-approved types (§ RULES.md 5) — the app only *displays* evidence.
10. **Access = role-based, assigned per person, admin-managed; unauthorized pages are INVISIBLE.**
    (Revises the "full-access seed" decision per Tim 2026-07-22 — no money gate.) Default-deny. Admins
    add users by email + assign roles; roles grant pages; an ungranted page is **absent from nav and
    404s on a direct hit** (not a 403). Full model in **§7.12**. Every gated screen also **logs a
    `page.view`** and exports log `export.download` (§7.13) — logging is cross-cutting, never opt-in.
11. **Read-only except Partners Admin.** The app touches only `lens_ps_*` through `ps_reporting_reader`.
    The one write surface (Partners Admin) goes through a governed path (§10 decision) — never the read
    role, always audited, JOS/venture governance applies.
12. **Git discipline** (RULES §12, and this repo's jos-sync hazard): `git branch --show-current` before
    staging; pathspec-scoped commits; build/commit foundry-cip docs from a **detached master worktree**
    (the jos-sync bot flips the main checkout mid-session). The reporting *app* repo (`reports-project-silk`)
    is master-only, no branches.

---

## 6. The data contract — lenses per screen (+ the data we're leaving on the table)

Full semantics in `LENS-CATALOG.md`. The read-map (screen → primary lenses):

| Screen | Primary lenses |
|---|---|
| Pipeline Overview | `monthly_summary`, `claim`, `partner_payout_summary`, `ar_aging`, `source_freshness` |
| Revenue & Billing ①② | `brand_revenue` (derived GMV/ad-spend, **gross**), `commission_ledger`, `monthly_summary` |
| Collections ③ | `commission_ledger` / `ps_stripe_invoices` (billed − collected, `amount_remaining`), `ar_aging` |
| **What Wayward Owes Us** ④⑤⑥ | `claim`, `ar_aging`, `wayward_reconciliation`, `wayward_stated`, `statement_drift` |
| Payments In ⑤ | `ps_payment_events` (+ `ps_stripe_balance_transactions`, `ps_stripe_payouts` for cash-recon) |
| Partners ⑦⑧ | `partner_payout_summary`, `commission_ledger.partner_fee_owed`, `ps_partner_payouts` |
| Brand & Product Perf | `commission_ledger`, `monthly_summary`, `product_eligibility`, `rate_schedule`, `china_verdict` |
| **Brand 360** (Deep) | `ps_brands`, `brand_contacts`, `china_verdict`/`china_evidence_grid`, `commission_ledger`, `claim`, `refund_allocation`, `rate_schedule` |
| Exceptions | `product_eligibility`(nulls), `china_verdict`(unknown+revenue), `china_contention`, `wayward_reconciliation`, `information_gaps`, freshness/invariants |
| **Statements** | `claim`, `statement_drift`, `ps_claim_statements` (+ FAS jobs, §9 Sprint 3) |
| Refunds (tab) | `refund_allocation`, `ps_stripe_disputes` |
| Excluded book | `excluded_partner_performance` |
| Counts (everywhere) | `lens_ps_china_companies` |

**Rich data the shipped app never reads (surface it):** `refund_allocation` (refund transparency),
`rate_schedule` (the 10/6/3 clock dates), `wayward_stated` (Wayward's own numbers), `excluded_partner_performance`
(Eric's book), `exclusion_status`, `china_companies` (the count grain), `monthly_summary` (trend lines),
and the data-asset tables `ps_stripe_charges` (card_country, fee/net), `ps_stripe_balance_transactions`
(authoritative fee/net ledger), `ps_stripe_payouts` (cash-out), `ps_stripe_disputes` (chargebacks). The
§Sprints put each to work. *(The 4-subagent review, step 3, will mine CIP for still more.)*

---

## 7. The target screen set (each = purpose · role · depths · lenses · content · acceptance · mapping)

> Build pattern for every screen (from `REPORTING-FRONTEND-IMPLEMENTATION §4`): **`defineQuery` DAL fn
> (auth + scope + composed SQL + Zod DTO) → Server Component renders DTO → i18n strings → vitest (shape
> test + a scope-isolation test).** Every screen ships loading / empty / error / no-access states, en+zh,
> light+dark, an as-of badge, keyboard/focus a11y.

**7.1 Pipeline Overview** — *home, all roles · Glance(+mini Working)*. Nine stage cards
(Revenue billed · Collected · Commission earned · Paid to us · **Still owed** · Owed partners · Paid
partners · **Net kept**) each with a period value + **trend sparkline**; mini AR-aging bar; a month
trend; an **alerts strip** (freshness + open-exceptions count). Lenses: `monthly_summary, claim,
partner_payout_summary, ar_aging, source_freshness`. *Accept:* every stage ties to a hand SQL check;
backlog card == `sum(ps_claim_owed) china`; sparklines render from `monthly_summary`. *Maps to:* reframe
Leadership + Finance homes into this.

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
owed/paid); products + rates; **contacts (incl. WeChat)**; refunds; a timeline (billings, payments,
rulings); CRM/ticket link. Lenses: `ps_brands, brand_contacts, china_verdict/china_evidence_grid,
commission_ledger, claim, refund_allocation, rate_schedule`. *Accept:* one brand's numbers match the
individual lenses; single join query (no N+1); a partner (V2) can only open THEIR brands. *Maps to:* NEW
— the crown-jewel Deep view; every brand name on every other screen links here.

**7.8 Exceptions / Needs-Attention** — *ops · Working*. The work queue: unknown-nationality-**with-revenue**,
missing fee-rate, no-partner-where-expected, attribution mismatch (`credited_other`), payment-recon
variance, refund spikes, stale sync, split-identity. Lenses: `product_eligibility`(nulls),
`china_verdict`(unknown), `china_contention`, `wayward_reconciliation`, `information_gaps`, freshness/
invariants. *Accept:* each sub-queue count ties to its lens; empty-state per sub-queue. *Maps to:* NEW
(re-home the Nationality Review Queue as one tab here + a CS view).

**7.9 Revenue & Billing** (①②) — *finance/ops · Working*. Per brand × product × month: revenue generated
(**derived GMV/ad-spend, labeled "derived (est.)"**) + Wayward billed; billing status; billed-vs-collected
gap. Lenses: `brand_revenue, commission_ledger, monthly_summary`. *Accept:* stage ① clearly labeled
derived; billed ties to the ledger. *Maps to:* NEW. *(True raw-GMV feed = §10 dependency.)*

**7.10 Statements & Reporting** — *finance/owner · Working*. **The deliverable.** Generate a Wayward
statement (pin as-of → **drift-check** → produce doc); partner statements; history of what was sent; the
schedule config. Bridges to the FAS report jobs (Sprint 3). Writing a pinned statement to
`ps_claim_statements` is a **governed write** (§10). Lenses: `claim, statement_drift, ps_claim_statements`.
*Accept:* pinning creates a `ps_claim_statements` row + a drift baseline; a generated statement matches the
live claim at pin time. *Maps to:* NEW — **highest-value gap.**

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
- **Roles are the page bundles.** Each role grants a defined set of pages — **Admin · Finance · Ops ·
  CS · Partner-Manager**. When adding/editing a user, the admin **assigns one or more roles**; the
  person's access = the **union** of their roles' pages. A per-page fine-tune per person is available
  for exceptions, but roles are the primary lever (Tim: "select what roles they have when I add them").
- **Multi-admin.** The **Admin** role reaches this screen and manages users/roles — **including granting
  Admin to someone else.** Make James an admin → James can then add users and assign roles too.
- No capability layer, no money gate (dropped 2026-07-22). Access is purely **person → roles → pages**.

*The admin UI:* a **People list** (name · email · roles · last-active) → **Edit person** (role
checkboxes + optional per-page fine-tune + Remove) · **Add person** (email + role checkboxes → save;
live on their next sign-in). Every change writes to the Activity Log (§7.13).

*Enforcement (wire all three):* nav renders only granted pages · the route returns **404** for an
ungranted surface (extend the seam's deny path redirect→notFound) · the DAL still runs `assertCan` per
surface (belt-and-suspenders). Schema: `app_users` + `app_user_roles` (exist); the role→page map in a
small seeded, admin-editable `app_role_pages` table (replaces the hard-coded `ROLE_SURFACE` matrix).

*Write path:* app-RBAC writes hit the app's OWN `app_*` Postgres via Next **server actions** (re-check
`admin` + zod + a log row in the same tx) — NOT the CIP read role, NOT the FAS API (that's only for CIP
money-input writes).

*Seed (Sprint 0):* **Tim + Van = Admin.** **James, Rhea, Sheila, Samantha** added; Tim assigns each
their roles in the UI. No one sees a page until a role grants it.

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
  · `admin.made_admin`.
- **Usage:** `page.view` (who opened which screen, when) · `export.download` (who downloaded what).
- **Money-input writes:** `statement.pinned` · `partner.added` · `partner.rate_set` (also logged on the
  FAS side; the app logs the initiating actor + action).

*Schema — `app_activity_log` (append-only, tamper-evident):* `id` · `at timestamptz` **(UTC)** ·
`actor_email` · `actor_roles text[]` · `action text` (the verb) · `target text` (the page / user / brand /
statement id) · `outcome ('success'|'failure')` · `ip inet` · `user_agent text` · `detail jsonb`.
**INSERT-only** grant — no UPDATE/DELETE from the app (the trail can't be edited), matching the existing
`app_audit_log` immutability. A **retention policy** on the noisy `page.view` stream (configurable; e.g.
12 months hot).

*The Report Builder (admin UI):* filter by **person · action type · date range · page/target · outcome**;
a results table; **Download CSV** of the filtered set — literally "who used the system for what, when."
Plus a per-person activity view and a per-page "who viewed this" view.

*Enforcement:* logging is **cross-cutting, not opt-in** — the seam logs `page.view` on every gated screen
render, exports log `export.download`, server actions log their `admin.*` verb in the same tx as the
change. A builder never has to "remember" to log. *Accept:* every login / page view / export / admin
change lands in `app_activity_log`; an admin can filter + download CSV; a non-admin can't reach the
Report Builder; the table rejects UPDATE/DELETE. *Maps to:* NEW — expands `app_audit_log` (RBAC-only
today) into the full activity log + the Report Builder screen.

**Supporting:** **Refunds** (tab in Payments/Brand-360 — `refund_allocation` + disputes) · **Data Health**
(the shipped Freshness, extended with coverage % + invariant status) · **Excluded-partner book**
(`excluded_partner_performance` — Eric et al., walled off, never in our claim).

**Cross-cutting (apply to all):** **trends** (sparklines/month lines off `monthly_summary`), **export**
(wire the "Export ▾" to real CSV/PDF download — currently an inert `<span>`), **depth tabs**
(Glance/Working/Deep), **per-role nav** (RBAC-filtered, no dead links — a disabled item with a tooltip,
never a 404).

---

## 8. The correctness fixes (do these FIRST — Sprint 0)

| # | Defect | Fix (what "done" looks like) | Acceptance test |
|---|---|---|---|
| **F1** | Brand-Perf "Collected" column is **gross billed** (`usage_fee_billed`), overstated ~$139k/13%; `brand_revenue` has no `usage_collected` | Relabel the column to what it is (**"Usage billed"**), or source true collected from the money engine; never call `brand_revenue` "collected" | column value == `sum(usage_fee_billed)` under a "billed" label; grep: no "collected" alias on a `brand_revenue` query |
| **F2** | "China brands" = **1,167** on Commission, **2,351** on 3 screens; the RULES grain (**1,951** companies) shown nowhere | Use `lens_ps_china_companies` for every count-said-out-loud; label populations ("claim-bearing", "with a verdict") where a subset is intended | one number for "the China book" app-wide, == `lens_ps_china_companies`; subset labels explicit |
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

**Sprint 0 — Correctness, access model, activity log & foundation reframe.** *Goal:* the app stops
lying, any admin can onboard the team, everything is logged, and the shell becomes the pipeline. *Scope:*
**(a)** F1–F6 correctness fixes (§8); **(b)** the **User & Access Admin** (§7.12, = F7) — add-user-by-email
(no invite), assign roles → pages, multi-admin, **hidden nav + 404**, the People-list / Edit-person UI,
audited server-action writes, the `app_role_pages` map, and the seed (Tim/Van admin; James/Rhea/Sheila/
Samantha added for Tim to assign roles); **(c)** the **Activity Log + Report Builder** (§7.13) —
`app_activity_log` (append-only) + cross-cutting `page.view`/`export.download`/`admin.*` logging + the
admin filter/download UI; **(d)** replace the flat role-home nav with the role-filtered pipeline nav;
collapse Leadership/Finance/CS homes → one **Pipeline Overview** (7.1); rename Commission Statement →
**What Wayward Owes Us** + add the `wayward_stated` cross-check. *Depends:* none. *Accept:* Overview
stages tie to lenses; counts use `china_companies`; no gross-labeled "collected"; **any admin can add a
user + assign roles + make another admin; an ungranted page is invisible + 404s; every login/page-view/
export/admin-change appears in `app_activity_log` and an admin can download it as CSV.** *Tests:*
money-SUM, count-grain, the access truth-table (role→page, hidden-nav, scope-isolation), the activity-log
test (each verb logged; table rejects UPDATE/DELETE), the 6 fix checks. *Escalate-if:* a lens for a stage
card is missing/changed, or the `app_role_pages`/activity-log schema needs a migration that touches a
shared contract.

**Sprint 1 — Core recovery money.** *Goal:* you can see and reconcile the whole owed picture. *Scope:*
finish **7.2** (recon tab buckets + drift + the Deep per-brand invoice) · **7.3 Collections** ·
**7.4 Payments-In** (incl. cash-recon Deep). *Depends:* Sprint 0. *Accept:* per §7 each; scope-isolation
tests pass. *Escalate-if:* `ps_stripe_invoices`/`amount_remaining` not exposed to the read role (add one
targeted GRANT, don't broaden).

**Sprint 2 — Operations & performance.** *Scope:* **7.5 Partners** (perf+payouts) · **7.6 Brand&Product**
(fixed + trends + rung) · **7.8 Exceptions** (all sub-queues; re-home the review queue) · **7.9 Revenue&Billing**
· **Excluded book** · **Refunds tab**. *Depends:* Sprint 0. *Accept:* per §7; every count labeled.

**Sprint 3 — Brand 360 + Statements + FAS reporting.** *Scope:* **7.7 Brand 360** (the Deep join; every
brand-name links here) · **7.10 Statements** (pin/drift/produce — governed write) · the **FAS report jobs**
(monthly Wayward statement, monthly per-partner statements, weekly collections, weekly review queue, daily
sync digest — built in Foundry-Agent-System, off the lenses, per `REPORTING-FRONTEND-IMPLEMENTATION §6`).
*Depends:* Sprints 0–2; the write-surface governance decision (§10). *Escalate-if:* the statement write
needs a new write role/tool → §10 decision.

**Sprint 4 — Polish + export + depth + external V2 groundwork.** *Scope:* wire **export** (CSV/PDF) ·
finish **depth tabs** everywhere · **Partners Admin** write surface (7.11 — after Tim's design riff) ·
zh native-review gate · CI/CD (branch protection, e2e). **External Wayward/partner surfaces stay V2**
pending the data work in §10.

---

## 10. Dependencies, data gaps & decisions for Tim

**Data/lens gaps (CIP-side — block specific screens, not the whole build):**
- **Partner isolation (V2 blocker):** the partner-safe lenses (`lens_ps_partner_statement` etc.) were
  **dropped in cip_110 and not rebuilt**, and there is **no email→partner→brand identity binding**
  (partner_id is an alias-heavy slug). Pointing partner screens at `commission_ledger` would **leak PS
  margin**. → V2 needs a new partner-safe lens + an identity table + the design riff. *This is why the
  custom-vs-Metabase-Pro rationale is unrealized in v1 — acknowledged, not a defect to fix in the app.*
- **Raw GMV stage ①:** Stripe lines are fee-lines only; GMV is **derived** (`usage_fee ÷ client_fee_rate`;
  rate populated 4674/4674). Ship derived-labeled; a true raw feed (Wayward/Amazon) is a follow-on ingest.
- **Coverage/exceptions lenses:** confirm `lens_ps_information_gaps` exists (Ops coverage %) or flag it as
  a small cip add.

**Decisions — RESOLVED (Tim, 2026-07-22; see §0):**
1. ✅ Write-surface path = **(A) governed FAS API**.
2. ✅ Partners = **one page + light add-partner write** (not a heavy admin screen).
3. ✅ Raw GMV = **ship derived**.
4. ✅ External Wayward view = **deferred; kept as a PM backlog item** (do NOT build in v1, do NOT drop).
5. ✅ Access model = **admin-managed per-person page grants + hidden nav + money gate** (§7.12).

**Still deferred to V2 (data-gated, backlog in PM — not v1 decisions):**
- **Partner-facing logins** (row-isolated) — needs the rebuilt partner-safe lens + the email→partner
  identity binding + a partner-design riff. External Wayward portal sits here too.

---

## 11. Testing strategy (mandatory per screen)

- **Unit:** every DAL fn gets (1) a DTO **shape test** and (2) a **scope-isolation test** (a partner/limited
  session cannot read another partner's/brand's rows — matters now for the RBAC seed, load-bearing for V2).
- **Contract:** a `zod.parse` **lens-contract test pinned to the migration head** — fails if a lens column
  the app depends on changes.
- **Money:** the money-SUM test (no JS money arithmetic), the count-grain test (`china_companies`), the
  net-of-refunds check.
- **Access:** the role→page truth-table (a user sees exactly their assigned roles' pages, an ungranted
  page 404s, multi-admin works, add-by-email creates an active user).
- **Activity log:** every logged verb (`auth.*`, `page.view`, `export.download`, `admin.*`) writes a row;
  the table rejects UPDATE/DELETE; the Report Builder filter + CSV download works and is admin-only.
- **Build-check:** no component imports the DB client; no `"use client"` imports `@/server/*`; dev-bypass
  hard-refused in prod.
- **E2E (Sprint 4):** Playwright — login → each screen renders → no 404s → export downloads.
- **CI:** typecheck + lint + tests + build-check on every push; branch protection on the app repo.

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
3. **4-subagent review:** pressure-test this plan for coherence + gaps, mine CIP for additional data
   opportunities (the unused lenses in §6 and beyond), and flag any other valuable work.
4. **Then, and only then:** the autonomous BUILD run executes Sprint 0 first.

---
*Plan of record for WCC P4 reporting. Supersedes the role-home screen set. Junior entry point: §1 → §3 →
§5 → §6 → §7 → your sprint in §9.*
