# Project Silk Reporting Frontend — Implementation Plan

> ⚠ **SUPERSEDED FOR EXECUTION (2026-07-20)** by
> [REPORTING-BUILD-PLAN.md](REPORTING-BUILD-PLAN.md) — the executable plan built against the delivered
> design handoff (`reporting-design-handoff/`) and hardened by a 3-lens QC + CTO pass. Build from that
> doc. This one is kept for rationale/history.
>
> **Junior-dev-executable build plan.** Pairs with the decision-level
> [REPORTING-FRONTEND-PLAN.md](REPORTING-FRONTEND-PLAN.md) (the *what/why*); this is the
> *how*. Nothing built yet. Authored 2026-07-18, QC'd (see §12).

## 0. References (read these first)

- **Decision plan:** REPORTING-FRONTEND-PLAN.md (screens, decisions, roles, accounts).
- **Reference implementation to mirror:** `c:\Users\Tim Jordan\code\foundry-trader-dashboard`
  — same house pattern (Next 16 + `postgres` raw + Auth.js v5 + read-only role + Railway).
  Copy its `src/lib/db.ts`, `src/auth.ts`, folder layout, and `.env.example` shape.
- **Data engine:** the CIP lenses — [LENS-CATALOG.md](LENS-CATALOG.md).
- **Best-practice sources (2025, verified online):**
  - Next.js Data Security / DAL — https://nextjs.org/docs/app/guides/data-security
  - "How to Think About Security in Next.js" — https://nextjs.org/blog/security-nextjs-server-components-actions
  - **CVE-2025-29927** (middleware auth-bypass) — never trust middleware as the sole auth gate.
  - Auth.js v5 RBAC — https://authjs.dev/guides/role-based-access-control
  - next-intl App Router — https://next-intl.dev/docs/getting-started/app-router

---

## 1. Architecture

### 1.1 Stack (mirror trader-dashboard — proven in-house on Railway)
| Concern | Choice | Why |
|---|---|---|
| Framework | **Next.js 16** App Router + React 19 + TypeScript | house standard |
| Styling | **Tailwind v4 + shadcn/ui** | house standard |
| DB driver | **`postgres`** (porsager) v3, raw tagged-template | lenses do the SQL; no ORM needed |
| Auth | **Auth.js v5** (`next-auth@5`) Google provider | trader-dashboard proves it |
| Data fetching | **@tanstack/react-query** + **react-table** | house standard |
| Charts | **chart.js + react-chartjs-2** | house standard |
| Validation | **zod** | DTO + server-action input validation |
| i18n | **next-intl** | App Router `[locale]`, en/zh |
| Tests | **vitest** | house standard |
| Node | ≥ 20 | — |

### 1.2 The four layers (security spine)
Defense-in-depth (post-CVE-2025-29927 — **middleware is a convenience gate, NOT the enforcement**):

```
1. Middleware (edge)     → locale routing + "is there a session?" fast redirect. NOT authoritative.
2. Data Access Layer     → src/data/*, `import "server-only"`. EVERY function:
   (the real gate)          (a) await auth() → deny if no session
                            (b) tenant scope: WHERE tenant_id = PS_TENANT (D-026)
                            (c) role/partner scope: partners filtered to THEIR brand set
                            (d) return a minimal DTO (zod-validated), never a raw row
3. Server Components      → call the DAL; render DTOs. No raw DB in components.
4. Server Actions         → Partners Admin writes; re-check auth+role here (never trust the client).
```
**Default-deny:** if no rule grants access, block. Partner isolation is enforced in the DAL
query (the `WHERE` clause), so a bug in middleware or a forged header can NOT leak another
partner's rows.

### 1.3 Repo & deploy
- **New repo** `project-silk-reporting` (NOT inside the website Astro monorepo — different
  framework/lifecycle). Under the Project Silk venture on GitHub.
- **Railway:** new service in the Project Silk project. Claude sets up via Railway CLI:
  service, env vars, custom domain `reports.project-silk.com`, `next build`/`next start`.
- Metabase (retained for other CIP) relocated off that domain before DNS cutover.

### 1.4 Data access — the read role  ✅ MINTED (cip_120, applied to prod 2026-07-20; smoke-tested 21/21)
- **`ps_reporting_reader`** is live: `LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`,
  `GRANT SELECT` on the **37 `lens_ps_*` views ONLY** — the curated reporting contract. No base
  tables, no multi-tenant `cip_*` tables, no non-PS lenses, **no INSERT/UPDATE/DELETE**. Lenses
  run as owner (`postgres`) so they resolve their own base-table/`cip_*` reads; the app reads
  PS-scoped data through them without holding those grants. This is *tighter* than the original
  plan (which listed a few base tables) — the 37 lenses cover every screen (e.g.
  `lens_ps_source_freshness` replaces a raw `cip_sync_runs` grant). If a screen ever needs a
  base table the lenses don't expose, add ONE targeted `GRANT SELECT` (never broaden to `cip_*`).
- **Verified 21/21** (smoke test): reads all reporting lenses incl. cip-joining ones via owner
  views; **denied** on base tables, `cip_*` multi-tenant tables, non-PS lenses, and every write.
  Consistent with §12 — RLS is belt-and-suspenders; `ps_*` is single-tenant PS by construction,
  so the lens surface is structurally PS-only.
- **Build-time credential step (backend, at deploy):** the migration reads the password from
  `PS_REPORTING_READER_DB_PASSWORD` (idempotent CREATE-or-ALTER). Set that var on the reporting
  Railway service, re-run `cip_120` (or `ALTER ROLE ps_reporting_reader PASSWORD …`), then
  `REPORTING_DB_URL = postgresql://ps_reporting_reader:<pw>@<prod-host>/railway`. (Role is minted
  now with a placeholder secret held out-of-band; it stays dormant until this step.)
- Frontend connects with this role only. The Partners Admin **write** path does NOT use it (§8).

---

## 2. Data model → screens (the read map)

Screen → lenses (full contents in PLAN.md §3). DTO = the minimal fields each screen needs.

| Screen | Primary lenses | Notes |
|---|---|---|
| Pipeline Overview | monthly_summary, claim, partner_payout_summary, ar_aging, cip_sync_runs | headline stage cards |
| Revenue & Billing | commission_ledger, stripe_invoice_lines, monthly_summary | see §2.1 raw-revenue |
| Collections | ps_stripe_invoices | billed − collected, aging |
| What Wayward Owes Us | claim, ar_aging, wayward_reconciliation, wayward_stated, statement_drift | recon = a tab |
| Payments In | ps_payment_events | cash ledger |
| Partners | partner_payout_summary, commission_ledger, ps_partner_payouts, ps_partner_registry | perf + payout |
| Brand & Product Perf | commission_ledger, monthly_summary, product_eligibility, rate_schedule, china_verdict | |
| Brand 360 | ps_brands, brand_contacts, china_verdict, commission_ledger, claim, refund_allocation | single-brand join |
| Exceptions | product_eligibility(nulls), china_verdict(unknown), wayward_reconciliation, invariants | ops queue |
| Statements | claim, statement_drift, ps_claim_statements | + FAS jobs (§7) |
| Partners Admin (write) | ps_partner_registry/credit/aliases | §8 |
| Refunds (tab) | refund_allocation | |
| Data Health | cip_sync_runs, invariants | |

### 2.1 Raw revenue ① — a real finding (decision needed)
The Stripe lines are **fee lines only** (usage/commission/cc/saas; qty always 1) — **raw
GMV/ad-spend is NOT ingested.** It IS derivable: `GMV ≈ usage_fee ÷ wayward_client_fee_rate`
(rate is populated 4674/4674 in `lens_ps_product_eligibility`). **Plan:** stage ① ships as a
**derived** figure, clearly labelled "derived (est.)". **True raw GMV = a follow-on ingest
dependency** (a Wayward/Amazon feed) — flagged, not blocking. → **decision for Tim** (§11).

---

## 3. Phase 0 — Foundations (the skeleton)

Each step: **do · deps · edge cases · acceptance.**

**0.1 Mint `ps_reporting_reader`** — ✅ DONE (`cip_120_reporting_reader_role`, applied to prod
2026-07-20). GRANT SELECT on the 37 `lens_ps_*` views only (lens-only — see §1.4); no write.
*Accept (met):* role SELECTs every lens; `INSERT`/`UPDATE`/`DELETE`/`CREATE` denied; base
tables + multi-tenant `cip_*` + non-PS lenses denied. Smoke test **21/21**.

**0.2 Scaffold Next.js 16 app** — `create-next-app` (TS, App Router, Tailwind); add shadcn;
copy folder layout from trader-dashboard (`src/app/[locale]/(app)/…`, `src/data`,
`src/features`, `src/components`, `src/lib`). *Accept:* `next dev` renders a page; `tsc` +
eslint clean.

**0.3 DB layer `src/lib/db.ts`** — copy trader-dashboard: module-singleton `postgres()`,
`max:5, prepare:false, ssl:"require"`, `application_name`, URL from `REPORTING_DB_URL`; export
`PS_TENANT_ID`. *Edge:* Railway proxy resets (prepare:false handles it); pool exhaustion
(cap 5). *Accept:* `/api/health` runs `SELECT 1` green.

**0.4 Auth (`src/auth.ts` + `auth.config.ts`)** — Auth.js v5 split config; Google provider +
`AUTH_ALLOWED_EMAILS` allowlist (copy trader-dashboard's signIn callback); `AUTH_MODE=stub`
for dev; **add a role map** `AUTH_ROLE_MAP` (email→role) surfaced in the `jwt`/`session`
callbacks (extend the TS `Session/JWT` interfaces with `role` + `partnerId?`). *Edge:* email
not in allowlist → deny; empty allowlist → deny-all (fail closed). *Accept:* stub renders as
Tim; a non-listed Google account is rejected; `session.user.role` present.

**0.5 i18n (next-intl)** — `routing.ts` (`locales:['en','zh'], defaultLocale:'en',
localePrefix:'as-needed'`), `[locale]` segment, `messages/en.json` + `zh.json`,
`getRequestConfig`. *Edge:* missing key → falls back to key, never crashes; currency/number/
date via `Intl` per-locale. *Accept:* `/zh` renders Chinese for a seeded string; language
switch persists.

**0.6 Middleware** — next-intl locale middleware + a **session-presence** redirect (unauth →
`/sign-in`). **Comment in code: this is a convenience gate; real auth is the DAL (CVE-2025-
29927).** *Accept:* unauth hitting a screen → sign-in; locale prefix works.

**0.7 DAL scaffold (`src/data/`)** — `import "server-only"` at top; a `requireSession()`
helper (calls `auth()`, throws on none); a `scoped()` helper that returns the tenant filter +
(for partner role) the partner's brand-id set; a `toDTO()` zod pattern. *Edge:* importing a
`src/data` module from a client component MUST fail the build (`server-only`). *Accept:* a
sample DAL fn returns a scoped DTO; client import errors at build.

**0.8 App shell** — nav (role-gated menu items), i18n switcher, user menu, shadcn theme
(brand palette), loading/empty/error states. *Accept:* shell renders; a partner-role session
sees only partner nav.

**0.9 Railway deploy** — new service in PS project via Railway CLI; env vars (AUTH_*,
REPORTING_DB_URL=ps_reporting_reader, AUTH_URL); domain `reports.project-silk.com` (after
Metabase moves); `next start`. *Deps:* Tim provisions Google OAuth creds + the 6 accounts +
DNS. *Accept:* deployed; real Google login works for an allowlisted account; one live lens
query renders in prod.

**Phase 0 Definition of Done:** an allowlisted user logs in via Google at
reports.project-silk.com, sees the shell in en/zh, and one real number off a lens — with the
DAL enforcing tenant scope.

---

## 4. Phase 1 — Core money screens

Per-screen build pattern (repeat for every screen): **DAL fn(s) (auth+scope+DTO) → react-query
hook → feature component (table/chart) → i18n strings → vitest (incl. a scope-isolation test).**

- **1.1 Pipeline Overview** — DAL: `getPipelineSummary(period)` → stage totals + sparkline
  series. UI: stage cards + mini charts + alerts strip. *Accept:* the 9 stage numbers match a
  hand SQL check against the lenses; backlog card == `sum(ps_claim_owed) china`.
- **1.2 What Wayward Owes Us** — DAL: `getClaims(filter)`, `getReconciliation()`. UI: table
  (brand → owed/paid/still-owed/aging) + reconciliation tab (delta_status) + drift banner.
  *Accept:* totals reconcile to `lens_ps_claim`; drift banner shows when a pinned statement
  differs.
- **1.3 Brand 360** — DAL: `getBrand360(brandId)` (joins verdict, ledger, claim, contacts,
  refunds, timeline). UI: header + financial panels + products + contacts + timeline.
  *Accept:* one brand's numbers match the individual lenses; a partner can only open THEIR
  brands (404/deny otherwise).

---

## 5. Phase 2 — Operations screens
Partners (perf+payouts) · Brand & Product Performance · Collections · Payments In · Exceptions.
Same build pattern. **Exceptions** = union queries for the ops gaps (unknown nationality w/
revenue, null fee-rate, no-partner, recon mismatch, stale sync). *Accept per screen:* totals
tie to source lenses; empty-state renders; sortable/filterable; scope-isolation test passes.

## 6. Phase 3 — Statements + automated reporting (FAS, independent)
- **Statements screen** — pin an as-of claim (writes a `ps_claim_statements` row — a governed
  write, §8), drift-check, preview.
- **FAS report jobs** (in Foundry-Agent-System, the existing scheduler pattern — same as the
  payment-reminder/watchdog): monthly **Wayward China statement**; monthly **per-partner
  statements** (each partner's own data only); optional internal weekly digest. Branded,
  email/PDF. **Governance:** these read the lenses; no new write tools. *Accept:* a dry-run
  generates the correct statement for a fixture month; partner statement contains ONLY that
  partner's brands.

## 7. Phase 4 — Partners external + write surface + cutover
- **Partner-design riff FIRST** (Tim) — then: partner Google logins (row-isolated via DAL) +
  the **Partners Admin write surface** (§8).
- **Metabase cutover:** confirm what the retained Metabase serves; move it off
  reports.project-silk.com; point DNS to the frontend; abandon the old money cards.

---

## 8. The write surface (Partners Admin) — needs a decision (§11)
Everything else is read-only. Partners Admin mutates money inputs
(`ps_partner_registry/credit/aliases`) → **governance-sensitive** (PROGRAM decision
2026-07-14: new write tools go through the tool-creation contract + FAS/JOS governance).
**Two options:**
- **(A) Governed FAS API/tool** — the frontend calls a governed FAS endpoint that writes +
  audits. Aligns with the governance decision; keeps the frontend read-only-DB.
- **(B) Next.js server actions + a narrowly-scoped write role** (`ps_partner_writer`, only the
  partner tables) + zod validation + an audit-log row per change.
**Recommendation: (A)** for governance alignment, unless the FAS round-trip is deemed
over-engineering for a low-frequency admin action → then (B) with audit. **→ confirm with Tim.**

---

## 9. Cross-cutting concerns
- **Security:** DAL default-deny; DTOs (never raw rows); `server-only`; auth re-checked in
  server actions; no secrets client-side; read-only DB role; scope-isolation unit tests are
  mandatory per screen.
- **Performance:** react-query caching + revalidate; lens queries are pre-aggregated (cheap)
  but paginate large tables (Brands, Payments); connection pool cap 5 (Railway); avoid N+1 in
  Brand 360 (single join query).
- **Errors/empty:** DB-down → friendly retry; empty lens → explicit empty-state (not a blank);
  a brand with no data → 200 with "no activity yet."
- **Observability:** `/api/health` (DB + auth); structured logs; surface CIP data-freshness
  (last sync) on Data Health + a global stale banner.
- **i18n:** all strings externalized to messages; zh translations reviewed by a Chinese
  speaker (Tim's staff); `Intl.NumberFormat` for currency/§ per locale.
- **Testing:** vitest; every DAL fn has (1) a shape test and (2) a **scope-isolation test**
  (a partner session cannot read another partner's/brand's rows). CI runs typecheck + lint +
  tests.
- **Governance:** D-026 tenant scope on every read; write surface per §8; the CIP read role
  is least-privilege.

## 10. Dependencies & risks
| Item | Owner | Risk if late |
|---|---|---|
| Google OAuth creds + 6 accounts + DNS | **Tim** | blocks 0.9 real-auth (stub unblocks dev) |
| Metabase URL move off reports.project-silk.com | Claude/Tim | blocks DNS cutover only |
| Raw-GMV feed (stage ①) | Wayward/Tim | ① stays "derived" — not blocking |
| Write-surface governance decision (§8) | **Tim** | blocks Phase 4 Partners Admin only |
| Partner-design riff | **Tim** | blocks Phase 4 partner logins only |

## 11. OPEN ARCHITECTURAL DECISIONS — confirm before/at build
1. **Raw GMV ①:** ship derived-now (recommended) vs. pursue a raw feed first (who provides?).
2. **Write surface (§8):** governed FAS API (A, recommended) vs scoped write role + server
   actions (B).
3. **New repo `project-silk-reporting`** (recommended) vs a package in the website monorepo.
4. **Partner data model:** confirm `ps_partner_registry`/`ps_partner_credit` cleanly map an
   OAuth email → a partner → their brand set (needed for row-isolation) — verify at Phase-2.

## 12. QC record + status

**3-way subagent QC (2026-07-18) — Stress Tester, Gap Analyst, Senior Reviewer.** All three
verified findings against the actual CIP migrations. Verdict: sound screens/phasing, but the
**Phase-0 foundations + partner-facing half need rework**. Converging findings incorporated /
decided:
- **Partner logins → V2** (Tim). Verified blockers: the partner-SAFE lenses (cip_70's
  `lens_ps_partner_statement` etc., built to HIDE our margin from partners) were **dropped in
  cip_110 and not rebuilt**; pointing partner screens at `lens_ps_commission_ledger` would
  leak PS economics. AND there is **no email→partner→brand identity** in the DB (partner_id is
  an alias-heavy text slug). → V2 needs a new partner-safe lens + a real identity-binding
  table + the design riff. **On the roadmap, not v1.**
- **Internal staff = v1 NOW**, with **DB-backed RBAC admin** (users/roles/permissions +
  junction + audit), resolved fresh per request — fixes the QC "env allowlist / stale-JWT /
  fail-open default" findings; default-deny; admin UI to manage users + role→screen access.
- **Read pattern fix:** Server Components → `zod.parse` DTO from the `server-only` DAL (NOT a
  client react-query hook — that can't compile; the reference uses zero react-query).
- **RLS is not a safety net** (lenses are owner-run views, don't expose tenant_id) → the DAL
  `WHERE` is the asserted boundary; `ps_*` is single-tenant PS by construction.
- **"Proven in-house" was false** for the security spine (the reference is the middleware-only
  CVE anti-pattern) → the DAL gate is greenfield, with a build-time test that nothing bypasses
  it; **hard-guard stub-auth out of prod.**
- **Next 16:** `proxy.ts` (not `middleware.ts`); **`zod.parse` as a lens-contract test pinned
  to the migration head**; acceptance asserts **live queries**, not stale constants.
- **Raw GMV → stored in a lens** (guarded ÷), not derived in TS — folded into the
  DATA-EXPANSION plan (built first).
- Plus: effective-dated + validated rate writes; materialize/benchmark heavy lenses; DNS/cert
  cutover runbook; error/sign-out/expiry pages; CSP + rate-limit; freshness from the sync
  heartbeat; population-label footnotes; zh domain-glossary review gate.

**Resequenced (Tim, 2026-07-18):** the **data-capture expansion** (DATA-EXPANSION-PLAN.md)
ships FIRST; this reporting build resumes after — at which point v1 (internal + RBAC) is the
first sprint set, on the enriched data. **CTO alignment pass + the coherent rewrite happen
when we return to the reporting build.**

**Phase-0 progress (2026-07-20):** read role `ps_reporting_reader` **shipped** (cip_120, 21/21
smoke test — see §1.4 / §3.0.1). The DB security spine is proven and ready. Remaining Phase-0
(Next.js scaffold, Auth.js/RBAC admin, Railway service) awaits the designer's mockups + the
Google OAuth credentials. No frontend code written yet — by design.

---
*Plan-of-record for the P4 build. Junior-dev entry point = §3 (Phase 0), reading §1–2 first.*
