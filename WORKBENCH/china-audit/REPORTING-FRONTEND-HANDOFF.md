# Project Silk Reporting Frontend — Build Handoff

**Read this first.** This is the entry point + brief for the reporting/dashboard web app. It's
self-contained enough to scope and design from; the deep references are linked at the end. Handed
off 2026-07-20. The data foundation is **already built, reconciled, and reporting-ready** — this is a
frontend + auth + delivery build, no schema work.

---

## 1. What we're building

A **custom reporting web app** for the Project Silk × Wayward China-commission operation. Internal
staff (and later, external partners) log in with Google, land on dashboards scoped to their role, and
can **download** any report (CSV for data, PDF for formatted statements). Later, the same reports get
generated on a schedule and **sent** to people/places (email/Slack).

- **Lives at:** `reports.project-silk.com` (Tim provisions the domain).
- **Replaces:** Metabase for Project Silk (Metabase is being retired for PS; kept for other CIP things
  for now). This app is standalone.
- **Internal staff first; external (Wayward / partners) is a later, carefully-gated phase.**

## 2. Who uses it (roles + accounts)

Six audiences. **Internal** teams see full detail; **external** parties see curated data only. Exactly
what each sees, at three depths (glance / working / deep), is the locked list in
**[REPORTING-CONTENT-PLAN.md](REPORTING-CONTENT-PLAN.md)** — that is the authoritative "what to show."

| Role | Type | In one line |
|---|---|---|
| **Leadership** | internal | Top-line money, growth, "what needs me." |
| **Finance** | internal | The full money pipeline; collections; Wayward reconciliation. |
| **CS** (China team) | internal | Brand book, contacts, the nationality review queue, support. |
| **Ops** | internal | Data freshness/health, coverage gaps, identity hygiene. |
| **Wayward** | **external** | Curated: partnership value + transparent commission statement. |
| **Referral partners** | **external (V2)** | Scoped to *their own* brands only. |

**Google-OAuth accounts to allowlist** (initial):

| Email | Person | Role (initial) |
|---|---|---|
| `treckrg@gmail.com` | Tim | Admin / Leadership |
| `samantha@project-silk.com` | Samantha | Staff (CS / ops / finance) |
| `rhea@project-silk.com` | Rhea | Staff |
| `james@project-silk.com` | James | Staff |
| `sheila@project-silk.com` | Sheila | Staff |
| `van@project-silk.com` | Van | Staff |

**Gating model:** each user → one or more roles; a role only ever sees its own dashboards, and the data
layer refuses to serve another role's data. **Initially all internal staff get full access** — build
the permission **scaffold** (roles exist, admin can assign, the enforcement path is real) but don't
block internal staff on day one. External roles (Wayward/partners) are hard-gated to curated queries.
An **admin surface** (Tim) assigns roles + manages the allowlist.

## 3. Architecture & stack (house standard — mirrors `foundry-trader-dashboard`)

| Layer | Choice |
|---|---|
| Framework | **Next.js 16** (App Router) + **React 19** + **TypeScript** |
| Styling | **Tailwind** + **shadcn/ui** |
| DB driver | **`postgres`** (porsager) v3 — raw tagged-template SQL; **the lenses already do the SQL, no ORM** |
| Auth | **Auth.js v5** (`next-auth@5`), Google provider + email allowlist → role |
| Data fetching | **@tanstack/react-query** + **react-table** |
| Charts | **chart.js** + react-chartjs-2 |
| i18n | **next-intl** — App Router `[locale]`, **English + Chinese (zh)** (CS/ops/finance staff are Chinese-speaking) |
| Export | CSV (data) + PDF (formatted statements, e.g. the Wayward bill) |
| Deploy | **Railway** — a **new service in the Project Silk venture** (not the website monorepo). `next build` / `next start`, custom domain `reports.project-silk.com`. |

**Security spine (defense-in-depth — non-negotiable).** Post-CVE-2025-29927, **middleware is a
convenience gate, NOT the enforcement.** The real boundary is a **server-only Data Access Layer (DAL)**:

1. `middleware.ts` — cheap redirect for the unauthenticated (convenience only).
2. **DAL (`src/lib/dal/*`, server-only)** — re-checks the session on every call and applies:
   (a) tenant scope (`WHERE tenant_id = PS_TENANT` / `SET app.current_tenant`), (b) role scope (an
   external partner is filtered to THEIR brand set; Wayward never sees internal columns).
3. Server Components call the DAL and render DTOs — **no raw DB in components**.
4. Server Actions (admin writes) re-check auth+role — never trust the client.
   **Default-deny:** if no rule grants access, block.

## 4. Data access — this is the "API"

There is **no REST API**; the app reads the CIP Postgres **lenses** (SQL views) directly through a
read-only role. The lenses ARE the contract — they encode all the business logic (the 10/6/3 ladder,
refund-netting, GMV derivation, the china verdict). The app just selects + renders.

- **Read role:** a dedicated **read-only, PS-tenant-scoped** Postgres role — mint `ps_reporting_reader`
  (or reuse `cip_metabase_project_silk`). It must `SET app.current_tenant = '<PS_TENANT>'` per
  connection and **must NOT bypass RLS** (unlike the `postgres` superuser). It only sees PS-tenant rows.
  Tim/Claude provisions this role + the connection string as a Railway env var.
- **Tenant:** `PS_TENANT_ID = 078a37d6-6ae2-4e22-869e-cc08f6cb2787`.
- **Amounts are in DOLLARS** across all lenses/tables (already converted from Stripe cents).
- **Data dictionary:** **[LENS-CATALOG.md](LENS-CATALOG.md)** — every lens in plain English, by the
  question it answers. Also introspect live: the money lenses + tables carry **column COMMENTs**
  (units, gross/net, what-if warnings) added specifically for report-builders — read them.
- **A trap to respect:** `product_id` values are `'connect'` and **`'boosted'`** (never `'boost'`). And
  `lens_ps_brand_revenue.revenue_amount` is GMV for connect / ad-spend for boosted — **do not sum it
  across products.** (Both are documented in the column comments.)

The screen-by-screen mapping of content → lenses is in the content plan (the `mono` chip on each item
names the lens) and in **[REPORTING-FRONTEND-PLAN.md](REPORTING-FRONTEND-PLAN.md) §3** (an earlier
screen framing — cross-reference, but the content plan is the current authority).

## 5. Design constraints for the designer

- **Three depths per audience:** Glance (KPI tiles) → Working (lists/queues) → Deep (per-brand /
  per-transaction drill-down). Design the navigation around this.
- **Bilingual (en/zh)** — layouts must tolerate Chinese text; labels come from next-intl message files.
- **Light + dark** themes.
- **Internal vs external framing** — the Wayward/partner views are visually + functionally distinct
  (curated, trust-building, no internal columns). Treat them as a separate surface.
- **Export affordance** on every report (download CSV/PDF).
- **Data-freshness badge** — a small "data as of / all syncs green" indicator, since everyone needs to
  trust the numbers.
- Reference house look: `foundry-trader-dashboard`.

## 6. Suggested build phasing (for whoever implements)

1. **Foundation + one real screen (vertical slice)** — Railway service, Next.js skeleton, the read role
   + DAL, Auth.js Google + allowlist + role scaffold, and **one shared-core screen end-to-end** (Brand
   performance or the Commission statement) with export. Proves the whole stack.
2. **Admin/gating + the shared cores** — the 4 shared surfaces (commission statement, brand
   performance, nationality review queue, data freshness), then per-audience screens.
3. **External (Wayward) view** — its own gated slice, curated data only.
4. **Report automation & delivery** — scheduled generation + send (email/Slack).

## 7. Division of labor (this handoff)

**Designer:** using the content plan (§2 link) as the "what," produce the visual design / mockups for
the screens — respecting the constraints in §5 and the architecture in §3–4 (so designs are buildable).
**Then Claude Code implements** the Next.js app from the designs + these specs, and provisions Railway +
the read role + OAuth. Tim provisions the domain + the Google OAuth app credentials.

## 8. The bundle — documents to hand over

- **[REPORTING-CONTENT-PLAN.md](REPORTING-CONTENT-PLAN.md)** — *authoritative* "what each audience sees," 3 depths. (An HTML/visual version was also published for review.)
- **[REPORTING-FRONTEND-PLAN.md](REPORTING-FRONTEND-PLAN.md)** — locked decisions, roles/accounts, the screen framing (§3), the Metabase-vs-custom research.
- **[REPORTING-FRONTEND-IMPLEMENTATION.md](REPORTING-FRONTEND-IMPLEMENTATION.md)** — the detailed build plan: exact stack, the 4-layer security spine, the read-role setup, Phase-0 foundation steps, and the external security references (Next.js DAL, CVE-2025-29927, Auth.js RBAC, next-intl).
- **[LENS-CATALOG.md](LENS-CATALOG.md)** — the data dictionary (every lens, in plain English).
- **This doc** — the orientation + brief that ties them together.

> **Status of the data:** cip_114–119 are live in prod; all ingestions green; the money engine is
> reconciled; the lenses are labeled for reporting. Nothing on the data side blocks this build.
