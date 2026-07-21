# Project Silk Reporting — Design Handoff Package

**Read this first.** This folder is the **design + frontend build brief** for the Project Silk × Wayward
commission reporting web app at `reports.project-silk.com`. It is meant to be dropped into the
**foundry-cip** repo and handed to a Claude Code session to implement.

The **data + backend are already built and reporting-ready** — this is a frontend + auth + delivery
build, reading the CIP Postgres "lens" views read-only. No schema work.

---

## 0. How to use this package (Claude Code)

1. Read this README end to end — it is the self-contained design spec.
2. Open the mockups in `mockups/` as the visual + interaction reference. They are **Design Component
   (`.dc.html`) files**: each one's source is plain inline-HTML markup plus a small logic class, so you
   can lift exact tokens (hex, fonts, spacing), layout, copy, and component structure directly from the
   source. `mockups/Design Handoff Spec.dc.html` is the same spec rendered visually.
3. Cross-reference the **authoritative product docs already in this repo** (§1). This README is the
   *design* layer on top of them.
4. Implement in the stack in §2, honoring the security spine in §3 and the data traps in §4.
5. Build in the phasing in §9. Four surfaces are intentionally **not designed yet** (§10) — spec them
   in words / hold for a design riff, do not invent them.

> Mockups render live in the Omelette design project they came from. Opened as flat files they may not
> execute (the DC runtime `support.js` loads from a hosted URL), but the **source is the reference** —
> you are recreating these in React, not embedding them.

---

## 1. Authoritative source docs (already in the repo)

These live at `WORKBENCH/china-audit/` in foundry-cip. This package sits alongside them.

| Doc | What it is |
|---|---|
| `REPORTING-FRONTEND-HANDOFF.md` | The product brief + orientation (entry point). |
| `REPORTING-CONTENT-PLAN.md` | **Authoritative** "what each audience sees," at 3 depths. The content contract. |
| `REPORTING-FRONTEND-PLAN.md` | Locked decisions, roles/accounts, the screen framing, Metabase-vs-custom research. |
| `REPORTING-FRONTEND-IMPLEMENTATION.md` | Detailed build plan: stack, the 4-layer security spine, read-role setup, phase-0 steps. |
| `LENS-CATALOG.md` | The data dictionary — every lens in plain English, by the question it answers. |

If a design detail here conflicts with the content plan, **the content plan wins** on *what to show*;
this package wins on *how it looks and behaves*.

---

## 2. Stack (house standard — mirrors `foundry-trader-dashboard`)

- **Next.js 16** (App Router) + **React 19** + **TypeScript**
- **Tailwind** + **shadcn/ui**
- DB driver **`postgres`** (porsager) v3 — raw tagged-template SQL; the lenses already do the SQL, no ORM
- Auth **Auth.js v5** (`next-auth@5`), Google provider + email allowlist → role
- Data **@tanstack/react-query** + **react-table**; charts **chart.js** + react-chartjs-2
- i18n **next-intl** — App Router `[locale]`, **English + 中文**
- Export CSV (data) + PDF (formatted statements)
- Deploy **Railway** — a new service in the Project Silk venture; custom domain `reports.project-silk.com`

## 3. Security spine (defense-in-depth — non-negotiable)

Post-CVE-2025-29927, **middleware is a convenience gate, NOT enforcement.** The real boundary is a
**server-only Data Access Layer (DAL)**:

1. `middleware.ts` — cheap redirect for the unauthenticated (convenience only).
2. **DAL (`src/lib/dal/*`, server-only)** — re-checks the session on every call; applies (a) tenant scope
   (`SET app.current_tenant = PS_TENANT`), (b) role scope (external partner filtered to THEIR brand set;
   Wayward never sees internal columns).
3. Server Components call the DAL and render DTOs — no raw DB in components.
4. Server Actions (admin writes) re-check auth + role. **Default-deny:** if no rule grants access, block.

## 4. Data access — the "API" is the lenses

No REST API. Read the CIP Postgres **lenses** (`lens_ps_*` views) through a read-only, PS-tenant-scoped
role (`ps_reporting_reader`). The lenses encode all business logic (the 10/6/3 ladder, refund-netting,
GMV derivation, the china verdict). The app selects + renders.

- **Tenant:** `PS_TENANT_ID = 078a37d6-6ae2-4e22-869e-cc08f6cb2787`
- **Amounts are in DOLLARS** across all lenses.
- **Traps to respect:**
  - `product_id` values are `'connect'` and `'boosted'` — **never `'boost'`**.
  - `lens_ps_brand_revenue.revenue_amount` is **GMV for connect / ad-spend for boosted** — **do not sum
    across products** (different units).
  - Quote the canonical still-owed figure **live** from `lens_ps_claim` (mock shows `$13,712.58`); never
    hard-code it. All figures in the mockups are **illustrative pending live lens queries.**

---

## 5. Design system — "Jade editorial" (locked)

Warm cream surfaces, deep jade rails, gold for statement emphasis, **Newsreader** serif headlines over a
**Public Sans** UI, and an **IBM Plex Mono** column wherever numbers must line up. Flat cells divided by
rules; a 12px card radius. This **intentionally overrides the bound "Modernist" design system** — that was
a deliberate product decision; ignore DS-adherence lint on these files.

### Tokens — light
| Token | Hex | Use |
|---|---|---|
| Ground | `#e9e7e2` | app backdrop |
| Surface | `#faf9f6` | main content area |
| Card | `#fffdf8` | tiles, panels |
| Rail (jade) | `#0d443f` | sidebar |
| Accent jade | `#0e5049` | primary, active, links |
| Jade bright | `#12a37f` | healthy/status dots |
| Gold | `#b8860b` / `#e9d9b8` | the ask, drift, logo mark |
| Ink | `#22302d` | text, 2px section rules |
| Muted | `#6a7370` / `#8a8877` / `#a39c86` | secondary text |
| Border | `#e6e3da` | hairlines |

### Tokens — dark (pinned in `Commission Statement Dark`)
| Token | Hex | Use |
|---|---|---|
| Ground | `#0f1a17` | app backdrop |
| Surface | `#16241f` | tiles |
| Rail | `#0a1512` | sidebar |
| Accent jade | `#2dd4bf` | primary, active (brightened) |
| Gold | `#e6c98f` | the ask, drift |
| Text | `#e6ece9` | body |
| Rules | light at 8–18% opacity | dividers |

### Status ramp (both themes, as `.tag` chips)
`Acknowledged·unpaid` amber `#fef3c7`/`#92600a` · `Credited other` violet `#efe9fd`/`#5a49c9` ·
`Unacknowledged` slate `#eef1f5`/`#5b6b80` · `Paid partial` teal `#d6f5ec`/`#0b7a68` ·
`Settled` green `#dcfce7`/`#15803d`. Rate rungs: 10% jade · 6% blue · 3% violet.

### Type & shape
- **Newsreader** — headlines, big numbers, card titles. **Public Sans** — UI, body, labels.
  **IBM Plex Mono** — money, IDs, lens names, timestamps.
- Card radius **12px**, controls **6–9px**, chips **999px**. Content padding **24–28px**, gaps **12–20px**.
  Section rule **2px** ink; row rule **1px**.
- **Charts** (chart.js): filled area for volume, thin lines for compare, clear axes + legend. Jade =
  primary series, gold = secondary. No 3D, no heavy gradients.

### Principles
- **Depth is the spine.** Every surface is Glance → Working → Deep, shown as underline tabs. Homes are
  Glance; shared cores are Working; drill-downs are Deep.
- **Trust is visible.** A freshness badge in every top bar; every report has an as-of date + Export.
- **Accent = attention.** Jade carries the page; gold/amber flags the ask & drift; red for aged/error;
  green dots = healthy.
- **Default-deny**, enforced server-side.

---

## 6. The shared chrome (every screen = one shell, filled per role)

| Part | Spec |
|---|---|
| Sidebar | 222px jade rail. Role label + nav; active item = cream text + gold 3px left border. Freshness + signed-in identity pinned to the bottom. |
| Top bar | 52px. Left: breadcrumb (mono). Right: freshness pill, EN/中 toggle, `Export ▾` (jade). |
| Header | Gold uppercase kicker, Newsreader title, muted subtitle; a 2px ink rule under it with the depth tabs (underline) sitting on that rule. |
| KPI grid | Flat cells inside one 1px-bordered, 12px-radius container; the hero cell is jade-filled with a serif number. |
| Tables | 1.5px ink top rule, uppercase 10.5px headers, 1px row rules, mono right-aligned numbers, a totals row with a 2px top rule. |
| Export + freshness | `Export ▾` → CSV (data) / PDF (statement). The freshness pill opens a per-connector popover. Both are shared components (see `UI States`). |

---

## 7. Screen → role → depth → lens map

| Screen (mockup file) | Role(s) | Depth | Key lenses |
|---|---|---|---|
| **Commission Statement** | Finance · (Wayward curated) | Working · Deep | `lens_ps_commission_ledger` · `lens_ps_claim` · `lens_ps_wayward_reconciliation` · `lens_ps_statement_drift` |
| **Nationality Review Queue** | CS · Ops · Leadership | Working | `lens_ps_china_contention` · `lens_ps_china_verdict` |
| **Brand Performance** | CS · Finance · Wayward · Leadership | Glance · Working | `lens_ps_brand_revenue` · `lens_ps_monthly_summary` · `lens_ps_product_eligibility` · `lens_ps_rate_schedule` |
| **Data Freshness** (= Ops home) | Ops · (all, badge) | Glance · Working | `lens_ps_source_freshness` · `cip_sync_runs` · `lens_ps_information_gaps` |
| **Leadership Home** | Leadership | Glance | `lens_ps_claim` · `lens_ps_monthly_summary` · `lens_ps_china_verdict` · `lens_ps_wayward_reconciliation` |
| **Finance Home** | Finance | Glance | `lens_ps_monthly_summary` · `lens_ps_ar_aging` · `lens_ps_partner_payout_summary` · `ps_stripe_balance_transactions` |
| **CS Home** | CS | Glance | `lens_ps_china_verdict` · `lens_ps_brand_reality` · `lens_ps_china_contention` · `cip_tickets` |
| **Login & Access** | all (unauth) | — | Auth.js Google · email allowlist → role |
| **Admin People and Permissions** | Admin (Tim, Van) | — | allowlist · role grants (server action, logged) |
| **UI States** | all (shared) | — | loading · empty · error · export · freshness · no-access |
| **Commission Statement Dark** | theme reference | — | dark palette for the theme toggle |

---

## 8. Roles → access & the allowlist

Each user → one or more roles; a role only sees its own dashboards; the DAL refuses another role's data.
**Internal staff start at full access** (build the scaffold — roles exist, admin can assign, enforcement
path is real — but don't block internal staff day one). **External roles are hard-gated to curated
queries.** Admin (Tim, Van) invites/removes people and sets per-person grants in the permission grid; all
changes are logged.

| Role | Type | Sees |
|---|---|---|
| Leadership | internal | Top-line money, growth, "what needs me", needs-attention rollup. |
| Finance | internal | Full money pipeline, ledger, collections, payouts, reconciliation, statements. |
| CS | internal | Brand directory, review queue, contact book, onboarding, support, Brand 360. |
| Ops | internal | Data freshness, coverage, exceptions, information gaps, identity health. |
| Partners | internal | Partner performance & payouts (Rhea); the Partners Admin write-surface. |
| Referral partner | **external · gated** | Their own referred brands only — row-isolated. Never the full book, our margin, or Wayward's numbers. |

**Initial Google-OAuth allowlist:** `treckrg@gmail.com` (Tim · Admin/Leadership) ·
`van@project-silk.com` (Van · Developer/Admin) · `samantha@project-silk.com` (CS/Ops/Finance) ·
`rhea@project-silk.com` (Partners) · `james@project-silk.com` (CS) · `sheila@project-silk.com` (Finance).

---

## 9. Build phasing

0. **Foundation + one real screen** — Railway service, Next.js skeleton, `ps_reporting_reader` + DAL,
   Auth.js Google + allowlist + role scaffold, i18n (en/zh), and **one shared-core screen end-to-end**
   with export (Commission Statement or Brand Performance). Proves the whole stack.
1. **Admin/gating + the 4 shared cores** — Commission Statement, Brand Performance, Nationality Review
   Queue, Data Freshness; the Admin People & Permissions surface; login + default-deny.
2. **Per-audience homes** — Leadership, Finance, CS (Ops's home = Data Freshness). Dark theme toggle.
3. **External (Wayward) view** — its own gated slice, curated data only *(design pending — §10)*.
4. **Report automation & delivery** — scheduled generation + send (email/Slack).

---

## 10. Not designed yet — by decision (do not invent)

| Surface | Why it's held |
|---|---|
| **Wayward external portal** | Deferred until the CRM lands (better source data then). Will be a curated commission statement + partnership scorecard, visually distinct framing, no internal columns. |
| **Brand 360 (Deep)** | The per-brand drill-down every role links into — verdict + evidence, financials, contacts, support, timeline. Spec'd in words in the content plan; build iteratively against the chrome. |
| **Partners Admin (write-surface)** | Add partner, assign brands, set commission rates. Gets its own design riff at build time (it mutates money inputs — governed). |
| **Scheduled reports & delivery** | FAS-scheduled generate + send: monthly statement, weekly collections & review queue, daily sync digest. |

---

## 11. Package contents

```
handoff/
├── README.md                     ← this file (the design + build brief)
└── mockups/
    ├── Design Handoff Spec.dc.html          ← the spec, rendered visually
    ├── Commission Statement.dc.html         ← shared core · Finance (flagship)
    ├── Commission Statement Dark.dc.html    ← dark palette reference
    ├── Nationality Review Queue.dc.html      ← shared core · CS
    ├── Brand Performance.dc.html             ← shared core · all
    ├── Data Freshness.dc.html                ← shared core · Ops home
    ├── Leadership Home.dc.html               ← glance home
    ├── Finance Home.dc.html                  ← glance home
    ├── CS Home.dc.html                       ← glance home
    ├── Admin People and Permissions.dc.html  ← access control (people + permission grid)
    ├── Login & Access.dc.html                ← entry + default-deny
    ├── UI States.dc.html                     ← shared states (loading/empty/error/export/freshness/no-access)
    ├── Commission Statement explorations.dc.html ← archive: the 1a/1b/1c directions + working EN/中 toggle
    └── support.js                            ← the DC runtime (for reference)
```

Authoritative product docs remain in the repo at `WORKBENCH/china-audit/` (§1).
