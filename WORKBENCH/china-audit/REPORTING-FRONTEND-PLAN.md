# Project Silk — CIP Reporting Frontend Plan (P4 / WCC4)

> **Status: PLANNING — nothing built yet.** This is the anti-drift reference for the
> reporting build. Supersedes the "P4 = Metabase Dashboards" framing in PROGRAM.md:
> we are building a **custom frontend on the CIP lenses**, and **retiring Metabase as
> the Project Silk reporting tool**. Authored 2026-07-18 from a planning session with Tim.

---

## 0. DECISIONS (locked 2026-07-18)

1. **Kill Metabase for Project Silk reporting.** The Wayward-China money reporting moves
   to a **custom frontend**. Metabase is **kept for now for other CIP things** (any
   non-PS-money dashboards it still serves) — retire that later, separately.
2. **The engine is the CIP lenses, NOT Metabase.** All money math lives in Postgres
   views (`lens_ps_*`). Metabase was only ever *a viewer* on them. The custom frontend
   is a different viewer on the **same** lenses — so killing Metabase costs nothing
   structural. This is **custom-on-the-lenses**, NOT "custom on the Metabase engine"
   (Metabase embedding for per-user interactive views is a Pro feature — ruled out).
3. **No Metabase Pro. Ever, for this.** (Confirmed by Tim.)
4. **Stack = custom Next.js** (App Router + TS + Tailwind + shadcn), the same pattern as
   `foundry-trader-dashboard`. Reads the lenses via a **read-only Postgres role**,
   PS-tenant-scoped.
5. **Lands at `reports.project-silk.com`.** That URL currently hosts Metabase → it gets
   reassigned to the custom frontend. The retained-for-CIP Metabase relocates to a new
   internal URL (TBD).
6. **Auth = Google OAuth** (free even in Metabase OSS; trivial + role-scoped in custom).
   Initial account allowlist (Tim will set up the project-silk.com accounts):
   - `treckrg@gmail.com` — **Tim** — Owner/Admin (sees all)
   - `samantha@project-silk.com` — Samantha — staff (CS/ops/finance — role TBD)
   - `rhea@project-silk.com` — Rhea — Partners (owns the partner roster)
   - `james@project-silk.com` — James — staff (role TBD)
   - `sheila@project-silk.com` — Sheila — staff (role TBD)
   - `van@project-silk.com` — Van — Developer (all / technical + data health)
7. **Chinese-language UI (i18n, en + zh).** CS/Ops/Finance staff are Chinese-speaking.
   Trivial in custom; painful in Metabase — a real reason for custom.
8. **Scheduled reports are INDEPENDENT of the frontend** — FAS-scheduled jobs generate +
   send statements (the pattern already running for the CIP syncs / payment reminder).
9. **Deploy on Railway, in the Project Silk project.** Likely as a service in / alongside
   the `project-silk-website` deployment (evaluate monorepo-app vs separate service).
10. **Sales is out of scope** — that's Twenty CRM. This tool is **reporting only**.

---

## 1. Why custom (the Metabase capability research, 2026-07-18)

| Requirement | Metabase OSS (free) | Verdict |
|---|---|---|
| Google OAuth login | ✅ free (only *multiple domains* needs Pro) | fine either way |
| Who-sees-which-**screens** (groups/collections) | ✅ free | fine either way |
| Scheduled reports to specific people/times | ✅ free (basic subscriptions) | we do this in FAS anyway |
| **Per-user ROW isolation** (a partner sees only THEIR rows) | ❌ **Pro $575/mo**, and **doesn't apply to native SQL** | **blocker** — won't pay |
| Branded/product UX | ❌ generic Metabase chrome | custom wins |
| Chinese i18n | ❌ painful | custom wins |

The row-isolation + branding + i18n needs — for an **external-facing, access-controlled,
bilingual** product with **partner logins** — are exactly where Metabase OSS strains and
Pro is required. A custom frontend does all of it **free and owned**. Metabase's only
unique value (free ad-hoc point-click exploration) is covered for us by direct SQL on the
lenses (Tim + Claude + Van).

---

## 2. Architecture

```
foundry-cip Postgres  ──(lens_ps_* views = THE ENGINE)──┐
                                                         │  read-only role, PS-tenant-scoped
   Custom Next.js frontend (reports.project-silk.com) ───┘   → renders the 10 screens
   FAS scheduler ── generates + emails/PDFs statements ──┘   → external reporting (independent)

   Metabase (kept for other CIP things, for now) ── same lenses, relocated off reports.project-silk.com
```

- **Data/engine:** existing `lens_ps_*` lenses (cip_104–113). No new engine work — the
  reporting build is READ-ONLY on top of what's shipped.
- **Read path:** a dedicated **read-only role** (reuse `cip_metabase_project_silk` or mint
  `ps_reporting_reader`), scoped to the PS tenant. Frontend queries lenses through it.
- **App:** Next.js (App Router) + TypeScript + Tailwind + shadcn/ui; charts via a JS lib
  (Recharts/visx-class); i18n (en/zh). Mirrors `foundry-trader-dashboard`.
- **Auth:** NextAuth Google provider + the account allowlist (§0.6) → role → screen + data
  scope. **Partner accounts see only their own rows** (enforced in the query layer — the
  thing Metabase can't do free).
- **Reporting:** FAS jobs (not the frontend) build + send statements on a schedule.
- **Deploy:** Railway, Project Silk project. `reports.project-silk.com`.

---

## 3. THE SCREENS — the operational money pipeline

Mental model — follow a dollar:
```
① Revenue generated → ② Wayward billed client → ③ Collections (billed, uncollected)
  → ④ Client paid Wayward = COMMISSION EARNED → ⑤ Wayward paid us → ⑥ STILL OWED TO US
  → ⑦ We owe partners → ⑧ We paid partners → ⑨ NET WE KEEP
```

Every screen: **purpose · primary role · what you see · source lenses.**

### 3.1 Pipeline Overview  *(home — all roles)*
- **See:** one card per stage (this period + trend sparkline) — Revenue billed · Collected ·
  Commission earned · Paid to us · **Still owed to us** (the canonical backlog, currently
  **$13,896.57**) · Owed to partners · Paid partners · **Net kept**. Mini AR-aging bar,
  mini month trend, an alerts strip (freshness + exceptions count).
- **Lenses:** `lens_ps_monthly_summary`, `lens_ps_claim`, `lens_ps_partner_payout_summary`,
  `lens_ps_ar_aging`, `cip_sync_runs`.

### 3.2 Revenue & Billing  ①②  *(finance/ops)*
- **See:** per brand × product × month — revenue generated + what Wayward billed the client
  (`usage_billed`), billing status; totals billed by period; billed-vs-collected gap.
- **Lenses:** `ps_stripe_invoices` / `_lines`, `lens_ps_commission_ledger`, `lens_ps_monthly_summary`.
- **⚠ data check:** raw GMV/ad-spend (stage ①) may not be ingested — confirm; if not, the
  funnel **starts at "billed."**

### 3.3 Collections  ③  *(finance/ops)*
- **See:** billed but **not yet collected** — open invoices, `amount_remaining`, aging of the
  uncollected; the gap between "billed" and "we can earn on it."
- **Lenses:** `ps_stripe_invoices` (status, amount_remaining).

### 3.4 What Wayward Owes Us  ④⑤⑥  *(finance/owner — the recovery engine)*
- **See:** per china brand — `usage_collected` → `mgmt_fee_owed` (10/6/3) → `wayward_paid` →
  **`ps_claim_owed`** (still owed), with aging. **Reconciliation is a TAB/filter here, not a
  screen:** `delta_status` buckets (acknowledged-unpaid = strongest ask; credited-other =
  the negotiation) + their stated-numbers cross-check + drift-check before a statement.
- **Lenses:** `lens_ps_claim`, `lens_ps_ar_aging`, `lens_ps_wayward_reconciliation`,
  `lens_ps_wayward_stated`, `lens_ps_statement_drift`.

### 3.5 Payments In  ⑤  *(finance)*
- **See:** the cash-received ledger — Wayward's payments to us, dated, fee breakdown, against
  what was owed; rev-share stated-vs-computed variance.
- **Lenses:** `ps_payment_events`.

### 3.6 Partners — Performance & Payouts  ⑦⑧  *(finance / Rhea / partner-facing)*
- **See:** per partner — brands they drive + **revenue/collected they generate**
  (performance), then `partner_fee_owed`, **paid** (`ps_partner_payouts`), **still-owed**;
  drill to per-brand×product splits. **Partner-facing variant = one partner sees only their
  own rows** (the row-isolation case).
- **Lenses:** `lens_ps_partner_payout_summary`, `lens_ps_commission_ledger.partner_fee_owed`,
  `ps_partner_payouts`, `ps_partner_registry`.

### 3.7 Brand & Product Performance  *(all)*
- **See:** aggregate per brand × product — revenue, collected, commission earned, month
  trend, which **10/6/3** rung, eligibility/fee-rate, nationality tag; sort/filter; top &
  bottom movers.
- **Lenses:** `lens_ps_commission_ledger`, `lens_ps_monthly_summary`,
  `lens_ps_product_eligibility`, `lens_ps_rate_schedule`, `lens_ps_china_verdict`.

### 3.8 Brand 360 / Account Lookup  *(CS especially — all roles)*
- **See:** ONE brand, everything — header (name, nationality + evidence, partner, signup,
  disposition); financials (revenue, billed, collected, commission earned, owed, paid);
  products + rates; contacts; refunds; a timeline (billings, payments, rulings); CRM/ticket
  link. The page CS opens when a brand contacts them.
- **Lenses:** `ps_brands`, `ps_brand_contacts`, `lens_ps_china_verdict`,
  `lens_ps_commission_ledger`, `lens_ps_claim`, `lens_ps_refund_allocation`.

### 3.9 Exceptions / Needs-Attention  *(operations)*
- **See:** the ops work queue — brands still **unknown nationality** with revenue; **missing
  fee rate**; **no partner** where one is expected; **attribution mismatch**
  (credited-other); **payment reconciliation variance**; **refund spikes**; **stale sync**;
  split-identity conflicts. "What we fix today."
- **Lenses:** `lens_ps_product_eligibility` (nulls), `lens_ps_china_verdict` (unknown),
  `lens_ps_wayward_reconciliation`, freshness/invariants.

### 3.10 Statements & Reporting  *(finance/owner)*
- **See:** generate a Wayward statement (pin as-of → drift-check → produce doc); partner
  statements; history of what was sent; the schedule config (which report → whom → when).
  Bridges to the FAS report jobs (§5).
- **Lenses:** `lens_ps_claim`, `lens_ps_statement_drift`, `ps_claim_statements`.

### Supporting (not front-and-center)
- **Refunds** (tab in Payments / Brand-360; finance) — `lens_ps_refund_allocation`:
  `usage_refunded` netted, raw, effect on collected.
- **Data Health** (ops/dev) — sync heartbeats (`cip_sync_runs`), freshness, invariant status,
  last full refresh.
- **Excluded-partner book** (reference; owner) — Eric et al., **walled off, never in our
  claim** — `lens_ps_excluded_partner_performance`.

---

## 4. Roles → access (who sees what)

| Role | People (provisional) | Screens |
|---|---|---|
| Owner/Admin | Tim | everything |
| Developer | Van | everything + Data Health |
| Finance | (Samantha? / TBD) | Pipeline, Owed-vs-Paid, Payments In, Partners-payout, Statements, Brand 360, Refunds |
| Operations | (TBD) | Exceptions, Collections, Data Health, Brand 360, setup views |
| CS | (TBD) | Brand 360, Brand & Product Performance (read), limited |
| Partner (Rhea + external partners) | Rhea; partner logins | **their own** Partner statement only (row-isolated) |

**Open:** confirm each named account's actual role (Samantha/James/Sheila), and whether
**external partners get logins** (row-isolated) or **just emailed statements** (simpler).

---

## 5. Reporting — scheduled statements (independent of the frontend)

Built as **FAS scheduler jobs** off the lenses (same governance as the CIP syncs):
- **Wayward China Statement** — monthly; branded; drift-checked; → Tim / the Wayward
  contact. The claim by brand + nationality evidence + aging + total.
- **Partner Statements** — monthly; **per partner, their own data only**; → each partner.
- **Internal digest** (optional) — weekly numbers → the team (could be a Metabase
  subscription while Metabase lingers, or a FAS job).
- Delivery: email / Slack / PDF. Sent at specific times to specific people = the FAS
  scheduler. **Not** Metabase.

---

## 6. Metabase retirement (Project Silk) — the record

- **What's being killed:** Metabase's role as the **Project Silk money-reporting** surface.
  The custom frontend at `reports.project-silk.com` replaces it.
- **What's kept (for now):** any **other CIP** dashboards Metabase still serves — retire
  those later, separately. The `cip_metabase_role` DB role stays live for that.
- **URL move:** `reports.project-silk.com` → custom frontend. Retained Metabase → a new
  internal URL (TBD, e.g. `metabase-internal…`).
- **Old money cards:** the Metabase cards built on the pre-rebuild lenses
  (`ps_monthly_earnings` etc., dropped in cip_110) are **abandoned, not repaired** —
  superseded by the frontend. (This closes the "repair cards app-side in P4" note.)
- **Pre-kill check (done? no):** confirm exactly what `reports.project-silk.com` Metabase
  serves today (CIP-money-only vs also CRM/marketing) before final cutover.

---

## 7. Open questions / decisions still needed (before/at build)

1. **Stage ① data:** do we ingest raw revenue/GMV, or does the funnel start at "billed"?
2. **Repo:** new app inside the `project-silk-website` monorepo, or a separate repo/service?
3. **Role mapping:** confirm Samantha/James/Sheila roles → screen access.
4. **Partner logins:** external partner accounts (row-isolated) vs emailed statements only.
5. **Retained-Metabase new URL** + exact list of what it keeps serving.
6. **Read role:** reuse `cip_metabase_project_silk` or mint `ps_reporting_reader`.
7. **Charting lib + i18n framework** specifics (build-time).

---

## 8. Rough build phases (NOT started — for sequencing only)

- **P0 — Skeleton:** read-only role · Next.js scaffold · Google OAuth + allowlist · i18n
  (en/zh) · Railway deploy to reports.project-silk.com · one live lens query end-to-end.
- **P1 — Core money:** Pipeline Overview · What Wayward Owes Us · Brand 360.
- **P2 — Operations:** Partners · Brand & Product Performance · Collections · Payments In ·
  Exceptions.
- **P3 — Output:** Statements screen + FAS report jobs (Wayward + partner statements).
- **P4 — External + cutover:** partner logins/isolation · polish · Metabase money-cards
  cutover + URL move.

---

*Plan-of-record for WCC P4. Pairs with PROGRAM.md (program), AUTOMATIONS-PLAN.md (P3),
LENS-CATALOG.md (the read-surface these screens consume).*
