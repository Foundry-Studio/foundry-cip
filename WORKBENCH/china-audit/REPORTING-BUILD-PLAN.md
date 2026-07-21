# Project Silk Reporting — Build Plan (executable)

**Status:** Build-ready + **hardened by a 4-seat expert panel** (2026-07-20 — see §17). BUILD confirmed
(build-vs-buy overruled by Tim). One architectural change adopted: **Better Auth** replaces Auth.js v5
(§17.2). Pin **Next.js ≥ 16.2.6** (live CVEs). **Audience:** a developer picking this up
cold — every step says *what to do · depends on · edge cases · acceptance*. **Authority order:** the
**content plan** wins on *what to show*; the **design handoff** (`handoff/`) wins on *how it looks*; this
doc owns *how it is built*. It is **the executable plan** — it supersedes for build purposes the earlier
`REPORTING-FRONTEND-{PLAN,IMPLEMENTATION}.md` (kept for history/rationale). **This revision** folds in a
3-lens QC pass (stress / gaps / senior review) + a CTO alignment pass — see §15 for what changed and why.

> **Nature of this tool (governance):** it is **read-only visibility** — it *reports* the money state, it
> does not *move* money or mutate verdicts. The two write surfaces (nationality ruling, statement send) are
> deliberately deferred and governed. This keeps it consistent with the program's action-freeze: showing
> "what Wayward owes" is reporting, not collecting.

---

## 0. Why we're building this (the problem)
Project Silk earns a management commission on the Amazon-agency revenue of the **Chinese brands** in the
Wayward book — a **10 / 6 / 3 %** ladder on *collected* usage fees. Today "who owes what, what's paid,
what's drifted, which brands are even Chinese" lives in Postgres "lens" views, legible only to someone who
writes SQL at 1 a.m. This app makes it **legible and trustworthy to the team, in their language**:
Leadership sees the ask, Finance works the ledger, CS runs the nationality queue, Ops watches freshness.
It is **read-only reporting over an already-built data engine** — no business logic in the frontend; the
lenses are the API; the app selects and renders. **Success:** a signed-in staffer sees a number they trust
(as-of date + freshness badge), drills glance→ledger, exports it — and an external partner can *never* see
anything but their own rows.

---

## 1. Architecture

### 1.1 Stack (locked)
| Concern | Choice | Notes |
|---|---|---|
| Framework | **Next.js ≥ 16.2.6** (pin — earlier 16.x has live CVEs, §17.1) App Router + **React 19** + **TS** (strict) | `proxy.ts` (Node runtime) not `middleware.ts`; Dependabot + 48h patch SLO. |
| Styling | **Tailwind v4** (CSS-first `@theme`, no `tailwind.config.js`) + **shadcn/ui** | shadcn is TW-v4/React-19 ready. |
| DB driver | **postgres.js** (porsager) v3 — raw tagged-template SQL | Lenses encode the logic; no ORM. |
| Auth | **Better Auth** (DB sessions) — Google (§17.2, supersedes Auth.js v5) | native instant revocation + RBAC; authz still the per-request DAL check. |
| Data | **RSC → server-only DAL → zod DTO → render**; tables are **searchParams-driven Server Components** | react-query only for a *genuinely* client-only widget (none in v1). |
| Tables | `@tanstack/react-table` headless, server-fed; **[nuqs](https://nuqs.dev)** for typed searchParams | **server-side sort** (column allowlist — §17.7) + server paginate via URL params; never client-sort a capped slice. |
| Charts | **chart.js** + `react-chartjs-2` (`'use client'`) | jade primary / gold secondary; no SSR canvas. |
| i18n | **next-intl** — `[locale]` (`en`/`zh`), all pages **dynamic** | §6. |
| Export | CSV streamed from `sql.cursor()`; PDF via **weasyprint on FAS** (§10.2) | never block the Node loop. |
| RBAC schema migrations | **node-pg-migrate** (raw SQL, matches the no-ORM ethos) | `app_*` tables + writer role. cip lens gaps stay in foundry-cip. *Alt: Drizzle Kit — 2026 mainstream; §16 / panel.* |
| Deploy | **Railway** auto-deploy (§16) into the website's Railway project; `reports.project-silk.com` | single persistent Node process → one long-lived pool. |

Pin exact versions (no `^`); commit the lockfile. `next-auth@beta` installs a moving tag → **pin the
resolved version** after install and record it in the changelog (confirm at build whether v5 is still beta).

### 1.2 The security spine — a single enforced wrapper (post CVE-2025-29927)
Middleware/`proxy.ts` is **NOT** a boundary (that CVE let attackers spoof `x-middleware-subrequest` to skip
it). The boundary is the **server-only DAL**, and — critically — it is **not hand-rolled per function**.
Every data read/write goes through **one** higher-order wrapper so no step can be forgotten:

```ts
// src/server/dal/define-query.ts   (import 'server-only')
export function defineQuery<A, R>(surface: Surface, fn: (tx, ctx: Ctx, args: A) => Promise<R>) {
  return async (args: A): Promise<R> => {
    const ctx = await requireSession()          // 1. auth() or throw Unauthenticated
    assertActive(ctx)                            // 2. app_users.status === 'active' (fresh DB read) or throw
    assertCan(ctx, surface)                      // 3. default-deny role→surface grant or throw Forbidden
    return withTenant(ctx, async (tx) => fn(tx, ctx, args))   // 4. tx + SET LOCAL tenant (+ partner) scope
  }
}
```
`requireSession/assertActive/assertCan/grantsFor` all read the `app_*` tables **fresh per request** (§4) —
never the JWT — so a suspension or grant change takes effect on the next click. A build-time check (§10.5)
**fails CI** if any `src/server/dal/*` query is not created by `defineQuery`, if `src/app/**` imports the db
client, or if a DAL file lacks `import 'server-only'`. This wrapper is the one audited, unit-tested seam.

### 1.3 The transaction scope — RLS GUC + snapshot consistency (`withTenant`)
Two traps solved in one place. (a) With a pooled driver a bare `SET` leaks the tenant GUC to the next
request → use `SET LOCAL` inside a transaction. (b) Four separate lens reads in one screen can straddle an
hourly-sync commit → **hero total ≠ ledger**. **REVISED FIX (panel):** prefer **one composed query / CTE
per screen** — a single SQL statement is one implicit snapshot even under READ COMMITTED, giving
cross-lens consistency **without a long-lived transaction**. This avoids the sharp footgun both the security
and infra reviewers flagged: a multi-statement `REPEATABLE READ` transaction (esp. if a slow CSV cursor runs
inside it) pins the `xmin` horizon and **blocks autovacuum on the OPERATIONAL primary we're a guest on** —
a read-only app bloating someone else's DB. So: compose per screen; keep `withTenant` for the GUC only
(short); set **`ALTER ROLE ps_reporting_reader SET idle_in_transaction_session_timeout='15s'`** (statement_
timeout does NOT cover idle-in-transaction); and run **CSV exports OUTSIDE** any snapshot tx (an export
tolerates READ COMMITTED — §10.2). Capture one `as_of` per render.
```ts
export async function withTenant<T>(ctx: Ctx, fn: (tx)=>Promise<T>): Promise<T> {
  return sql.begin(async (tx) => {
    await tx`set transaction isolation level repeatable read`
    await tx`select set_config('app.current_tenant', ${PS_TENANT}, true)`      // LOCAL
    if (ctx.partnerId) await tx`select set_config('app.current_partner', ${ctx.partnerId}, true)`  // §12
    return fn(tx)
  })
}
```
**Every screen that shows multiple lenses composes them into ONE `defineQuery`** (one snapshot), and shows
the single `as_of` on every tile so the snapshot is explicit. (The tenant GUC is belt-and-suspenders today —
`ps_*` is single-tenant PS and the views are owner-run — but it's the fence if that ever changes and is
required for the partner RLS in §12.)

### 1.4 `numeric` / `bigint` are JS **strings** in postgres.js — money footgun
By default postgres.js returns `numeric`/`bigint` as **strings** (to preserve precision). Rules
(revised per panel — do NOT coerce money to `number`): **(1) aggregate money in SQL** (`SUM(...)` in the
lens query) — **never** `a + b` in JS (`"100.50"+"200.25" = "100.50200.25"`, a silent wrong total).
**(2) keep money a STRING end-to-end** — DO NOT register a global `numeric→number` type parser and DO NOT
`z.coerce.number()` money fields; a JS `number` is float64 and re-opens the precision hole (`0.1+0.2 !==
0.3`), and a global parser blunt-coerces rates too. Use a **branded type** `type USD = string & { readonly
__brand: 'USD' }` so money is **un-addable by construction** (`usdA + usdB` won't typecheck) — the compiler
now enforces "aggregate only in SQL." Format for display with `Intl.NumberFormat` / next-intl `format.number`
(§6). `bigint` counts → `number` is fine (tiny); `bigint` IDs → keep string. A unit test asserts the
SQL-side `SUM` string equals the app total.

### 1.5 Repo & deploy shape
```
reports-project-silk/                      # standalone repo (recommended, §14)
├── src/
│   ├── app/[locale]/(auth)/login/  (app)/{layout,leadership,finance,cs,ops,commission,brands,review-queue,freshness,admin}
│   ├── server/{db.ts, auth/*, dal/*, dto/*}
│   ├── components/{chrome/, ui/[shadcn], charts/, states/}
│   ├── i18n/{routing.ts, request.ts, messages/{en,zh}.json}
│   └── styles/globals.css                 # Tailwind v4 @theme (Jade tokens)
├── migrations/                            # node-pg-migrate (app_* schema)
├── proxy.ts · next.config.ts · Dockerfile · railway.json · .env.example · docs/lens-columns.json
```
`next.config.ts`: `output:'standalone'`, a `headers()` CSP/HSTS block (§10.7), **`cacheComponents` OFF**
(live money). Dockerfile: pinned Node (match Railway), `next build`, `next start` binding `$PORT`; Railway
healthcheck → `/api/health` (promote the temp route). Attach the domain after first green deploy.

### 1.6 Next.js 16 specifics that bite
- `proxy.ts` (root), export `proxy`, **Node runtime** (edge unsupported — fine, we need Node for `postgres`).
- All authed pages render **dynamically**: call `setRequestLocale(locale)` in each `[locale]` layout/page (or
  `export const dynamic = 'force-dynamic'`). **Never** `generateStaticParams` an authed dynamic route
  (`brands/[id]`) — only the locale segment may be statically listed, and even that is optional here.
- Reads on the request path stay uncached; do not enable `cacheComponents` in v1.

---

## 2. Data contract — lenses each screen binds to (verified live 2026-07-20; full dump `docs/lens-columns.json`)
All amounts **dollars**. `product_id ∈ {'connect','boosted'}` — never `'boost'`. `brand_revenue.revenue_type
∈ {'gmv','ad_spend'}`; **never sum GMV + ad-spend** (different units). **Canonical hero "still owed":**
`SELECT round(sum(ps_claim_owed),2) FROM lens_ps_claim WHERE verdict='china'` (= $13,922.15 / 387 brands
today; **one shared `getStillOwed()` DAL helper**, used by both Commission and Leadership so they can't
diverge). **Status chips** bind to `lens_ps_wayward_reconciliation.delta_status`:
`acknowledged_unpaid · credited_other_unpaid · unacknowledged_unpaid · paid_partial · paid_settled ·
no_claim`. **Verdict**: `china/not_china/unknown`; **strength**: `definitional/confirmed/strong/human/
legal_record/∅`. **review_priority**: `high/medium/low`. **aging_bucket**: `1-3 / 3-6 / 6+ months / no
accrued fee`. **reality**: `REAL/GHOST/JUNK` (**filter JUNK out of every brand list**). **Freshness pill**:
derive green/amber/red from `source_freshness.status` (`success/human/no schedule`) + `hours_since` — do
**not** render the raw `freshness` prose. Evidence columns (`china_evidence`, `not_china_evidence`) are
**comma+space-joined signal names** → split on `', '` into chips.

| Screen | Lens(es) → key columns |
|---|---|
| Commission Statement | `commission_ledger`(product_id, period_month, usage_collected, mgmt_rate, mgmt_fee_owed, partner_of_record, partner_fee_owed) · `claim`(brand_name, mgmt_fee_owed, wayward_paid, ps_claim_owed) · `wayward_reconciliation`(delta_status, wayward_paid, wayward_ack_commission) · `statement_drift`(drift_amount, drift_direction — **0 rows until a statement is pinned, §13**) |
| Nationality Review Queue | `china_contention`(brand_name, verdict, verdict_strength, china_evidence, not_china_evidence, contention_type, review_priority, usage_collected) · `china_verdict`(evidence detail). **v1 READ-ONLY** (§7). |
| Brand Performance | `brand_revenue`(product_id, period_month, revenue_type, revenue_amount, rate_used, rate_missing) · `monthly_summary` · `product_eligibility` · `rate_schedule`(rate_10_until, rate_6_until) |
| Data Freshness (Ops home) | `source_freshness` · **G1 `information_gaps` (missing lens)** · **G4 `cip_sync_runs` (Next-run/Fail columns — not in source_freshness)** |
| Leadership Home | `claim` · `monthly_summary` · `china_verdict` · `wayward_reconciliation` · **`ar_aging`** (aged-receivables tile) · **G5 disputes source (no lens; `ps_stripe_disputes`=16 rows)** |
| Finance Home | `monthly_summary` · `ar_aging` · `partner_payout_summary` · **G2 cash lens (`ps_stripe_balance_transactions` base table)** |
| CS Home | `china_verdict` · `brand_reality`(filter JUNK) · `china_contention` · **G3 support lens (`cip_tickets` multi-tenant base table)** |

**Under-specified UI elements with no lens** → §11 (build a source or drop for v1): the Nationality
"6-model signal spread" (sourced from a CSV in the mock — **no lens column**), Data-Freshness
coverage-%/exceptions, Leadership disputes tile.

---

## 3. Phase 0 — Foundation + one real screen (the go/no-go slice)
**Goal:** deployed, authed, bilingual shell where **Commission Statement** renders live with export — end to
end. Everything after is "more screens on the same pattern."

### 0.0 Prerequisites to confirm/provision BEFORE scaffolding (§14)
- **Google OAuth = EXTERNAL consent** (decided). It MUST be External: the audience mixes a personal Gmail
  (`treckrg@gmail.com` — Tim), `@project-silk.com` Workspace accounts, **and** external partners
  (`ali@wayward.com` etc.). "Internal" consent only admits the Workspace org, so it can't serve the other
  two — External + our own allowlist is the only fit. Config (new *Google Auth Platform* UI → Branding /
  Audience / Clients): **non-sensitive scopes only** (`openid email profile` — no Gmail/Drive/sensitive
  scopes → no heavyweight verification); **Testing** mode initially with the allowlist as test users (≤100,
  no "unverified" warning for them); **publish + verify** the app before onboarding partners at scale.
  Redirect URIs `https://reports.project-silk.com/api/auth/callback/google` + `http://localhost:3000/api/
  auth/callback/google`. The **app's `app_users` allowlist is the real gate** (§4) — Google just proves
  identity. **Gates Phase 0.**
- **Read role credential** — set `PS_REPORTING_READER_DB_PASSWORD` on the Railway service, re-run cip_120
  (idempotent `ALTER ROLE … PASSWORD`), form `REPORTING_DB_URL=postgresql://ps_reporting_reader:<pw>@<host>/
  railway?sslmode=require`. **Decide the DB target** (§14): prod-direct (with hard query caps) vs a read
  replica. *Accept:* `psql "$REPORTING_DB_URL" -c "select count(*) from lens_ps_claim"` returns a number; an
  `insert` is denied.
- **Writer role** — mint `ps_reporting_writer` (separate from the reader) for the `app_*` RBAC writes only;
  `REPORTING_WRITER_DB_URL` env.
- **Local-dev DB + auth stub** (§9) — stand these up first or a junior can't run anything day one.

### 0.1 Scaffold
`npx create-next-app@latest` (TS, App Router, Tailwind, ESLint, `src/`). `npx shadcn@latest init` (TW-v4 /
React-19 path). Add `postgres next-auth@beta zod next-intl @tanstack/react-table chart.js react-chartjs-2
server-only node-pg-migrate`. *Edge:* if shadcn writes `tailwind.config.js`, migrate to `@theme` (§0.3).
*Accept:* `next dev` renders; `tsc --noEmit` + eslint clean; versions pinned + recorded.

### 0.2 DB singleton (`src/server/db.ts`)
`postgres(REPORTING_DB_URL, { max: Number(env.DB_POOL_MAX ?? 10), idle_timeout: 30, connect_timeout: 10,
prepare: true, types: moneyTypeParsers, connection: { statement_timeout: 10000 } })`. Guard a `globalThis`
singleton so dev hot-reload doesn't spawn pools. **`max` from env**, sized `floor(prod_connection_headroom /
replicas)`; a comment forbids Railway autoscaling until that math is redone. **If a transaction-mode
PgBouncer ever fronts the DB, `prepare:true` breaks** — pin a direct connection. **CTO backstop:** also set
`ALTER ROLE ps_reporting_reader SET statement_timeout='10s'` (a tiny cip change) so a runaway/cartesian
reporting query is killed by Postgres itself and can never load-DoS the shared prod DB — defense in depth
with the per-query `LIMIT` discipline (§10.6). *Accept:* `/api/health` selects `1`; a deliberate
`pg_sleep(20)` is killed at 10s.

### 0.3 Theme tokens (`globals.css`, Tailwind v4 `@theme`) — lift the Jade palette verbatim
`@theme` light tokens + `.dark` overrides (values in the handoff §5). **Self-host** Newsreader / Public Sans
/ IBM Plex Mono via `next/font/local` (not the Google `<link>` — CSP + offline). Status-chip, rate-rung, and
freshness colors live in ONE typed map `components/ui/tokens.ts` (single source, keyed by the real enum
values in §2). **Both themes must pass a contrast check** (esp. muted `#a39c86` on cream); adjust the token,
don't ship failing contrast. *Accept:* token page renders both themes; cookie-driven SSR theme (§6).

### 0.4 Auth (Auth.js v5) — see §4 for the full model. Phase-0 slice: Google sign-in, identity-only JWT,
`requireSession/assertActive/assertCan` reading `app_*`, the no-access screen, role→home redirect.

### 0.5 i18n (next-intl) — `routing.ts` (`locales:['en','zh']`, `defaultLocale:'en'`,
`localePrefix:'as-needed'`); `request.ts` with **`getMessageFallback` → the `en` string** (next-intl does
NOT auto-fallback; a missing `zh` key otherwise renders raw). `setRequestLocale` in the `[locale]` layout.
Money labels + the china/nationality glossary get a **named zh review gate** (owner + key list) in the DoD
before any external exposure. *Accept:* `/zh/commission` renders Chinese chrome; toggle preserves route;
a missing zh key shows English, not a key.

### 0.6 The shared chrome (`components/chrome/*`) — build once, fill per role
`Sidebar` (222px jade; role label; nav from `roles.ts`; freshness+identity+**Sign out** footer), `TopBar`
(52px; breadcrumb; freshness pill; EN/中 toggle; `Export ▾`), `PageHeader` (gold kicker, Newsreader title,
subtitle, 2px rule with **depth tabs**), `KpiGrid`, `DataTable` (ink top rule, uppercase headers, mono
right-aligned numbers, totals row). **Depth tabs (Glance/Working/Deep)** are **routed view-states** — each
maps to a route or `?depth=` param with defined content (§8 enumerates per screen; a screen with only one
depth hides the tabs). **Every sidebar nav item is enumerated** in §8 as in-scope-route / deferred-stub /
removed — no dead links. *Accept:* shell matches the mockup at 1340px, reflows ≤900px with no body
horizontal scroll, all nav items resolve.

### 0.7 First real screen — **Commission Statement** (the template every other screen copies)
- **DAL** `dal/commission.ts` = `defineQuery('finance', async (tx, ctx) => { … })` → ONE snapshot selecting
  the four lenses; returns a typed object. Ledger **display grain**: default **per-brand aggregate** (join
  `commission_ledger`→`claim`, `SUM` fees per brand in SQL), server-sorted by balance desc, server-paginated
  (top-N + "show all" via `?page=`); the per-brand-product-month rows are a Deep drill, not the default.
- **DTO** `dto/commission.ts` — zod, `z.coerce.number()` on every money field, pinned to §2 columns; a
  future column rename fails **here**, loudly. `zod.parse` a live row in CI (pin to migration head).
- **Page** (Server Component): KPI tiles (hero from `getStillOwed()`; earned/collected/paid), the per-brand
  ledger `DataTable`, the reconciliation delta strip (colored by `delta_status`), the drift card, a
  **"N brands unpriced (rate_missing) — $X GMV/ad-spend not in the ask"** reconciliation line so the headline
  understatement is visible. `fmtUSD(null) → '—'` (defined rule). Product/status/rate chips from the token map.
- **Freshness** pill + header "through <max period_month>" (parse `period_month` as a **calendar date, no tz
  shift**; show `last_success` in one declared tz **with a label**). **Export ▾** → CSV now; **PDF item
  disabled** until §10.2.
*Edge:* 0 rows → empty state; `rate_missing` → badge + the reconciliation line; `statement_drift` 0 rows →
"no pinned statement yet" (not an error, and it must NOT imply "reconciled"). *Accept:* live numbers match a
direct SQL check; CSV streams; both locales + themes; a non-Finance role is **server-denied**; keyboard-nav +
focus-visible on the table, export menu, and depth tabs.

### 0.8 Deploy Phase 0 — Railway service; env set; green; attach domain; verify Google OAuth on the real
domain + that the connection is `ps_reporting_reader` (not a superuser); e2e hits `/api/auth/callback/google`
**and** `/zh/commission` (the known proxy-composition footgun, §4.5). *Accept:* a real allowlisted user signs
in on the domain and sees live Commission Statement. **Go/no-go gate for everything after.**

---

## 4. Auth model (reconciled — identity-only JWT + per-request DB authz)
The draft's "JWT sessions" but "authz fresh from DB" was contradictory and missed suspension. Reconciled:
- **JWT carries identity only** (email, name). It is **never** read for authz server-side. `maxAge: 900s`
  (15 min) + rotation so a stale token can't outlive a revocation by long; `AUTH_SECRET` rotation
  invalidates all sessions (documented).
- **`signIn` callback returns `true` for any Google account** (so the user object exists) — it does **not**
  gate the allowlist. Gating happens in-app: `requireSession()` loads `app_users` + roles + grants in one
  query; **no `active` allowlist row or zero effective surfaces → render the designed "You're in Google but
  not on the list" no-access screen** (identity + Sign out), never a stack trace. `assertActive` denies
  `suspended`. This exactly matches the delivered Login/UI-States mockups.
- **Multi-role** (e.g. Samantha = CS·Ops·Finance): access = union; **home = the highest-priority role's home**
  by a fixed order `[admin, leadership, finance, cs, ops, partners]`. **Zero-role internal** user → no-access
  screen. Reconcile the seed's `Developer`/`Admin` labels: `Admin` = the `admin` surface; `Developer` is not
  a surface (drop it or alias to `admin`).
- `app/api/auth/[...nextauth]/route.ts` → `handlers`. `auth.config.ts`/`auth.ts` split kept for
  **organization** (DB-touching callbacks out of the redirect path) — *not* runtime-mandated (proxy is Node
  in Next 16). `pages: { signIn:'/login', error:'/login?error' }`.

### 4.5 `proxy.ts` composition (next-intl × Auth.js — the documented footgun)
Wrap `auth` as the outer proxy; run the next-intl middleware only for non-API/static paths.
```ts
export default auth((req) => {
  const { pathname } = req.nextUrl
  if (pathname.startsWith('/api') || pathname.startsWith('/_next') || /\.\w+$/.test(pathname)) return
  if (!req.auth && !pathname.includes('/login')) return NextResponse.redirect(new URL('/login', req.url))
  return intlMiddleware(req)   // never prefixes /api/auth/* — the OAuth callback must stay bare
})
export const config = { matcher: ['/((?!api|_next|.*\\..*).*)'] }
```
*Accept (Phase 0 e2e):* `/api/auth/callback/google` is reachable un-prefixed; `/zh/commission` localizes;
the unauth redirect fires once.

---

## 5. RBAC — People, Permissions, Roles (admin surface + enforcement model)
**Tables** (reporting repo's `app_*` schema, node-pg-migrate, owned by `ps_reporting_writer`):
- `app_users(email PK, display_name, status ['active'|'invited'|'suspended'|'external'], created_at)`
- `app_user_roles(email FK, role)` — many roles; access = union.
- `app_permissions(email FK, surface, grant ['full'|'view'|'none'|'locked'])` — per-person override of role
  defaults; `locked` = external, can't be granted internal.
- `app_partner_brands(email FK, wayward_brand_id)` — **the external row-isolation source of truth** (§12).
  Defined now even though external screens are deferred, so the isolation helper + test bind to a real shape.
- `app_audit_log(id, at, actor_email, action, target_email, detail jsonb)` — every invite/remove/role/grant
  change appends here **in the same transaction** as the change. **Append-only:** `ps_reporting_writer` is
  granted `INSERT` only on this table (no `UPDATE`/`DELETE`) so the trail is tamper-evident from the app.
  (Decision §14: also audit exports + external data access once external lands.)

**The role→surface default-deny matrix** (this is the `assertCan` truth table — write it exactly):

| Role \ Surface | leadership | finance | cs | ops | partners | statements | admin |
|---|---|---|---|---|---|---|---|
| leadership | full | view | view | view | view | view | none |
| finance | view | full | view | view | view | full | none |
| cs | none | none | full | view | none | none | none |
| ops | none | none | view | full | none | none | none |
| partners | none | none | none | none | full | none | none |
| admin | full | full | full | full | full | full | full |
| referral (external) | locked | locked | locked | locked | locked | locked | locked |

`assertCan(ctx, surface)` = effective grant (role default ∪ per-person override; `none`/`locked` win for
external) ≥ `view`. **Surface→route guards:** `commission,statements → statements`; `review-queue → cs`;
`brands → cs∪finance∪leadership` (any-of); `freshness → ops`; `/leadership|/finance|/cs → the same-named
surface`; `admin → admin`. Internal staff **seed at full** on their role surfaces; admin shrinks per person.
The Permissions matrix cell-cycle (Full→View→None) is a **Server Action** re-checking `admin` + zod + write +
audit, in one tx; external can never be granted internal (server rejects, UI shows `locked`).
*Accept:* invite creates `invited` + audit row; a cell change persists + logs; a non-admin cannot reach any
admin Server Action; a `suspended` user is denied everywhere (in the truth-table test); external can't be
granted an internal surface.

---

## 6. i18n / theming details
- **Dynamic rendering** everywhere (authed) — `setRequestLocale` per layout; no static gen of authed routes.
- **Theme SSR:** next-themes persists to localStorage → the server can't match. So: read a **`theme` cookie**
  in the root server layout, set `class="dark"` on `<html>` server-side, pass to `ThemeProvider`, add
  `suppressHydrationWarning`. The toggle writes the cookie + flips the class.
- **zh fallback** wired via `getMessageFallback`; **zh review gate** named in §13.

---

## 7. Phase 1 — 4 shared cores + admin + login
Repeat the §0.7 template (defineQuery → DTO → RSC → export) for each; each ships loading skeleton, empty,
error boundary, no-access, EN+中, light+dark, as-of badge, keyboard/focus a11y.
- **Brand Performance** — glance KPIs + per-brand table (`brand_revenue`, ⚠ never sum gmv+ad_spend; badge
  `rate_missing`), monthly-collected area chart (jade). Each brand links → Brand 360 stub (§8).
- **Nationality Review Queue** — `china_contention` by `review_priority`; evidence `text`→chips (split `', '`);
  verdict+strength chips. **READ-ONLY**: render the mock's "Your call" column **disabled** with "ruling is
  logged in the data layer" — do **not** build the write (governed, §13/§14). The 6-model "signal spread"
  visual has **no lens** → drop for v1 or build G6 (§11).
- **Data Freshness** (Ops home) — `source_freshness` grid (green/amber/red from status+hours_since), the
  per-connector popover, `information_gaps` (needs **G1**), Next-run/Fail (needs **G4**). The freshness pill
  component built here is reused everywhere; **define its behavior when the DB is down** (it needs a read) —
  degrade to a neutral "freshness unavailable," never crash the shell.
- **Admin · People & Permissions** (§5) + **Login** + default-deny + no-access + UI-States set.

*Acceptance:* all four live + export; freshness/export/tag/state components shared (no dup); the role×surface
truth-table test green; security build-check green; G1+G4 shipped (or their tiles explicitly deferred).

## 8. Depth tabs + per-role nav (enumerate — no dead links)
- **Depth:** Homes = Glance only (hide tabs). Shared cores = Working default; **Deep** = the drill (e.g.
  Commission Deep = per-brand-product-month ledger; Nationality Deep = full evidence for one brand;
  routed via `?depth=deep` or a sub-route). If a Deep view isn't in v1, the tab is **disabled with a
  tooltip**, not a dead link.
- **Nav per role** (from the mockups) → mark each **route / stub / removed** for v1: e.g. Leadership {Growth
  trend→home section, Money trend→home, Needs attention→home, Brand 360→stub}; CS {Contact book→**stub**,
  Onboarding→**stub**, Support→**stub or G3**, Brand 360→stub}; Ops {Coverage/Exceptions/Info-gaps→Freshness
  sections or G1/G4, Identity health→**stub**, Sync & automation→Freshness}. A **stub** renders a "coming
  soon" placeholder within the chrome (never a 404). Enumerate the full list in `docs/nav-map.md` at build.

## 9. Local dev + test infrastructure (BLOCKER — do in Phase 0)
- **DB:** a dev can't develop against complex prod lenses locally. Path: a **schema-only + lens `pg_dump`
  from prod → a local Postgres container**, plus a small seed script for a handful of brands (technique per
  the cip team's schema-only-from-prod approach), OR a read-only tunnel to the prod reader for dev only.
  Document one and script it (`scripts/dev-db.sh`).
- **Auth stub:** a `DEV_AUTH_BYPASS` that injects a fake session with a chosen role for local + Playwright —
  **hard-refused at boot when `NODE_ENV==='production'`** (the env guard). Never ships enabled.
- **Fixtures/seed** for e2e so the deny-path + a screen render without real Google creds.

## 10. Cross-cutting
- **10.1 States** (from `UI States`): loading skeleton, empty, error boundary, no-access (identity +
  Sign out + "Request access" CTA → define target: mailto Tim+Van or a form), the **export menu** (CSV/PDF
  dropdown; **not** a progress spinner — rename the mock's state), freshness popover. Every data screen wires
  all six; each CTA's destination is defined.
- **10.2 Export** — **CSV** streamed row-by-row from `sql.cursor()` (never materialize 16k rows), respecting
  the caller's role scope, row-capped. **PDF** (statements only) rendered by **weasyprint on a small FAS
  endpoint** — off the Node event loop (the interactive process never blocks); the PDF menu item is disabled
  until this lands.
- **10.3 Charts** — `'use client'` react-chartjs-2; jade/gold; area for volume, thin lines for compare; axes
  + legend; `prefers-reduced-motion`; **text/number redundancy, never color-only** (a11y).
- **10.4 Errors/observability** — root error boundary; DAL throws typed `Unauthenticated/Forbidden/NotFound/
  Upstream`; structured server logs (pick pino or the platform logger); never leak SQL/PII; an audit-log
  viewer for admins.
- **10.5 Testing/CI** — (a) `assertCan` truth table (every role × surface **incl. suspended + zero-role**);
  `fmtUSD` incl. null; the money-SUM-in-SQL-equals-JS test. (b) DTO zod parses a live lens row (pinned to
  migration head). (c) **build-time security check**: `src/app/**` never imports `@/server/db`; every
  `src/server/dal/*` is `import 'server-only'` and routes through `defineQuery`; **any interactive-table
  Route Handler runs the same wrapper**. (d) Playwright e2e: sign-in, deny path, a screen renders, CSV
  downloads, locale+theme toggles, the OAuth-callback + `/zh` proxy check. (e) **prod guard**: boot refuses
  if `DEV_AUTH_BYPASS` set under `NODE_ENV=production`.
- **10.6 Perf** — 16k-row lenses are sliced server-side (pagination/aggregation); **never** ship them to the
  client; **hard-cap every lens query with a server LIMIT**; benchmark the ledger query (>300ms → request a
  covering index from the cip team, a backend follow-up).
- **10.7 Security headers** — `next.config` `headers()`: a real **CSP** (self + the fonts we self-host + no
  inline unless nonce'd), **HSTS**, `X-Frame-Options: DENY`/`frame-ancestors 'none'`, `Referrer-Policy`.
- **10.8 a11y** — keyboard nav + `focus-visible` on tables, export menu, freshness popover, depth tabs;
  ARIA table semantics; **every color-coded signal also carries text/icon** (status chips, freshness pill,
  rate rungs, evidence chips — WCAG 1.4.1); contrast pass on **both** token sets; zh numeric `dir` LTR.

## 11. Backend prerequisites — lens gaps (small **foundry-cip** migrations, migration-safety checklist applies)
These are **prod cross-repo CIP migrations**, not "no schema work" — run each with the cip discipline (fetch
origin, check for untracked sibling migrations, override the ambient prod `DATABASE_URL` to a local
container, verify chain head). A **Phase-0/1 smoke test SELECTs each lens AS `ps_reporting_reader`** so a
missing grant fails in CI, not prod. Re-running cip_120 re-enumerates + grants new `lens_ps_*`.

| # | Gap | Fix | Blocks |
|---|---|---|---|
| G1 | `lens_ps_information_gaps` absent (only `ps_information_gaps` table) | new PS-scoped lens + grant | Data Freshness (P1) |
| G2 | Finance cash tile ← `ps_stripe_balance_transactions` (base table) | new `lens_ps_cash_ledger` OR drop the raw-cash tile | Finance Home (P2) |
| G3 | CS support ← `cip_tickets` (multi-tenant base) | new `lens_ps_support_tickets` (PS-brand-scoped) OR defer to Brand 360 | CS Home (P2) |
| G4 | Data-Freshness Next-run/Fail not in `source_freshness` | extend `source_freshness` or a `lens_ps_sync_runs` (PS-scoped over `cip_sync_runs`) | Data Freshness (P1) |
| G5 | Leadership disputes tile — no lens (`ps_stripe_disputes`=16) | new `lens_ps_disputes` OR drop the tile v1 | Leadership Home (P2) |
| G6 | Nationality "6-model signal spread" — no lens (was a CSV) | decide if it's rebuildable from `ps_nationality_signals`; else drop v1 | Review Queue (P1) |

None block **Phase 0**. Sequence G1/G4/G6 before P1 screens, G2/G3/G5 before P2 — or drop the specific tile
with a visible note.

## 12. External partner isolation (deferred build — mechanism specified now)
The success criterion "a partner never sees anything but their own rows" must **not** ride on an app-side
`WHERE` a developer might forget. Mechanism: `app_partner_brands` (§5) is the source of truth;
`defineQuery` sets `SET LOCAL app.current_partner = ctx.partnerId`; a **separate set of partner-only views**
declared `security_invoker=true` with an **RLS policy** `wayward_brand_id IN (select wayward_brand_id from
app_partner_brands where email = current_setting('app.current_partner'))` — so **the database refuses
cross-partner rows even if the app forgets**, and no internal view is ever reachable by an external role.
The isolation **test asserts the negative** (a synthetic external user's every reachable path returns only
mapped brands; internal-only surfaces 403). **v1 builds + tests this scaffold; the partner *screens* wait
for a design riff** (deferred by decision — do not invent them).

## 13. Definition of done (per phase)
- **P0:** live Commission Statement on domain, real user+role, CSV, EN+中, light+dark, read-only role, deny
  path proven, OAuth+proxy e2e green, security build-check green.
- **P1:** 4 cores + admin + login; shared components; role×surface truth-table (incl. suspended/zero-role)
  green; G1+G4 (+G6 decision) shipped; zh review gate passed for the shipped money labels.
- **P2:** 3 homes + dark toggle; G2/G3/G5 shipped or tiles deferred with a note.
- **P3:** Brand 360 iterating; external scaffold enforced + negative-tested (no external screens until design).
  **Named gate before ANY external user is onboarded:** an internet-facing app reading the prod DB + exposing
  partner money must pass a **security review** (the partner RLS negative-test, CSP, the DAL boundary audit,
  export scoping, secret posture) — do not flip on an external account without it.
- **P4:** report automation planned separately (FAS + the weasyprint PDF path); statement-pinning is what
  makes `statement_drift` non-zero — until then drift is disclosed-inert.

## 14. Decisions — RESOLVED (Tim, 2026-07-20)
1. **Repo** — a **standalone git repo** under the Project Silk org (§16), *deployed* into the Railway
   project that owns `project-silk.com` DNS (the website's project) so the `reports.` subdomain + cert are
   trivial. Maximize automation (§16). ✅
2. **OAuth** — **External consent, allowlist-gated** (§0.0/§4). Tim = `treckrg@gmail.com` (personal),
   staff = `firstname@project-silk.com` (Workspace), partners external (e.g. `ali@wayward.com`). ✅
3. **DB target** — **prod-direct with guardrails for v1** (read-only role + `statement_timeout` + per-query
   `LIMIT` + small pool), **read replica as the documented best-practice upgrade** (§16). Textbook says
   "reporting → replica"; at this scale the guardrails make prod-direct acceptable — **on the panel's list.** ✅
4. **Tools** — `node-pg-migrate` (raw-SQL, matches our no-ORM ethos) with **Drizzle Kit** noted as the 2026
   mainstream alternative; **weasyprint-on-FAS** for PDF. Both **on the panel's list.** ✅

## 15. What the QC rounds changed (audit trail)
3-lens QC (stress / gap / senior). **Incorporated:** single `defineQuery` boundary (was per-fn boilerplate);
identity-only JWT + per-request status check + the no-access/zero-role/multi-role model (was contradictory
JWT-authz, missed suspension); REPEATABLE-READ snapshot + `numeric`-as-string handling (money-correctness);
the real `proxy.ts` composition (was a dangling `§4.5` ref); the explicit role×surface matrix; local-dev DB
+ auth stub; RBAC migration tooling + writer role; expanded lens gaps G4–G6 + the "smoke-test as the reader"
CI check; depth-tab + nav enumeration; a11y + CSP sections; date/tz + null-money + status-enum + hero-agg
pinned; next-themes-cookie + setRequestLocale + zh-fallback; searchParams tables (one data path); CSV-via-
cursor + weasyprint PDF; `app_partner_brands` + partner RLS. **Escalated to §14** (not silently decided):
repo home, OAuth type/accounts, DB target. **Judged noise / already-covered:** none material discarded; a few
findings (drift 0-rows, rate_missing) were already present and got strengthened, not added.

## 16. Repo, deploy & CI/CD automation (researched 2026-07-20 — "measure twice, cut once")
**Repo:** one **standalone** repo `reports-project-silk` under the Project Silk GitHub org (not a monorepo
package — cleaner CI, its own deploy, no root-dir juggling). It reads the CIP prod DB over the network; it
does **not** live in the cip repo.
**Deploy target:** a **new Railway service in the same Railway project as `project-silk-website`** — that
project already owns `project-silk.com` DNS + certs, so adding the `reports.` subdomain is one record.
Railway → New Service → connect the GitHub repo. `next.config` `output:'standalone'`; Dockerfile (pinned
Node) or Nixpacks; bind `$PORT`; healthcheck `/api/health`.
**Automation (the "as much as possible" ask):**
- **Auto-deploy on push to `main`**, with **"Wait for CI"** enabled so Railway only ships after GitHub
  Actions is green (never deploys a red build).
- **GitHub Actions CI** on every PR + push: `tsc --noEmit`, eslint, unit tests (the `assertCan` truth table
  + money-SUM test), the **build-time security check** (§10.5c), and Playwright e2e (§10.5d). Branch
  protection on `main` requires green CI.
- **PR preview environments** (Railway PR deploys) so a screen can be reviewed on a real URL before merge —
  each preview points at the **read-only** reporter role (never a writer) and a **non-prod** `AUTH_SECRET`.
- **Custom domain** `reports.project-silk.com` via Railway Networking (auto TLS); add the CNAME to
  `project-silk.com` DNS. **Secrets** in Railway per-environment (prod vs preview); `AUTH_SECRET` rotation
  documented (invalidates sessions). No secret in git; `.env.example` is the contract (§0/§10).
- **Migrations in CI/deploy:** run `node-pg-migrate up` as a **release/pre-start step** (never on first
  request — that starves the pool). The cip lens-gap migrations (G1–G6) run via the cip repo's own path.

**DB-target detail (decided v1 = prod-direct + guardrails; replica = best-practice upgrade):** research
consensus is that reporting belongs on a **read replica** (isolation from the operational primary). For v1's
scale (~6 users, then a few partners) the guardrails — read-only `ps_reporting_reader`, `statement_timeout`
10s at the role, per-query `LIMIT`, `max` pool from env, no autoscaling — make **prod-direct acceptable and
far simpler**. A Railway Postgres **read replica** is the first-class upgrade the moment load or isolation
demands it (reporting tolerates seconds of replica lag). Flagged for the panel.

## 17. Expert-panel hardening (4-seat panel, 2026-07-20 — BUILD confirmed)
Decision: **we build** (the build-vs-buy pivot the contrarian raised was considered and **overruled by
Tim** — off the table). Below are the panel's sound, build-relevant findings, folded in as requirements.
Where marked **SUPERSEDES**, this is authoritative over the earlier inline text.

**17.1 Framework CVEs — pin Next.js ≥ 16.2.6 + a patch process (URGENT).** "Next.js 16" is currently
vulnerable: the May-2026 security release patched a **new proxy/middleware auth-bypass via `.rsc`
segment-prefetch (GHSA-267c-6grr-h53f, hits 16.0–16.2.4)**, a **self-host WebSocket SSRF (CVSS 8.6 — ours,
because we self-host on Railway not Vercel)**, and a **Server-Function DoS**. Pin ≥16.2.6, add
Dependabot/Renovate, and adopt a **patch-within-48h-of-advisory SLO**. (The bypass *validates* our thesis:
the proxy is skippable, the DAL still enforces.)

**17.2 Auth library → Better Auth (SUPERSEDES the Auth.js v5 choice in §1.1/§4).** All four seats flagged
that **Auth.js/next-auth v5 went maintenance-mode (2025-09-26), is perpetually beta, and its own maintainers
now steer new projects to Better Auth.** Decisive for us: we were hand-rolling identity-only-JWT + a
per-request DB status read *specifically to fake DB-session semantics* — **which is Better Auth's native
model** (a sessions table, immediate revocation, killable/listable sessions, org/RBAC) and slots straight
into our `app_users` posture. Greenfield ⇒ no migration cost. **Adopt Better Auth**, Google provider, DB
sessions on our Postgres. The authz is STILL the per-request DAL check (§1.2) — Better Auth handles identity
+ session lifecycle. Set `trustHost`. Keep the seam thin. *(This is the one architectural change from the
committed plan — surfaced to Tim.)*

**17.3 Money = string end-to-end** (done inline, §1.4 — branded `USD` type, no `numeric→number` coercion).
**17.4 Snapshot = one composed query per screen + `idle_in_transaction_session_timeout`** (done inline, §1.3).

**17.5 Partner RLS must be PROVEN fail-closed (not silent theater).** RLS fails *open* on misconfig, so the
guarantee lives entirely in assertions, enforced before any external user exists:
- **Assert `ps_reporting_reader` is `rolsuper=false` AND `rolbypassrls=false`** at boot + in CI — a LIVE risk
  here because our operational role connects as `postgres`/BYPASSRLS; if the reader inherits that, isolation
  is theater and every partner sees the whole book.
- Base tables need **`FORCE ROW LEVEL SECURITY`** and the reader must **not own** them. They live in the
  operational DB owned by the cip team (cross-repo coupling we don't control) → **this is the strongest
  argument for moving partner-facing reads onto a separate reporting DB** (logical-replicate just the lens
  base tables; own the RLS there). Until then, internal-only.
- **GUC-absent → ZERO rows:** policy uses `current_setting('app.current_partner', true)` (missing_ok) and
  `wayward_brand_id IN (SELECT … WHERE email = that)` so a forgotten GUC yields *nothing*, never *all*.
- **Negative test runs AS `ps_reporting_reader`** (not the owner) and asserts: (a) partner sees only mapped
  brands, (b) **GUC-absent returns zero rows**, (c) internal-only views are unreachable, (d) the role-attr
  assertion above. Confirm prod Postgres **≥ 15** (security_invoker) — verify, don't assume.

**17.6 `defineQuery` completeness (the build-check is now load-bearing security).** Make it AST/lint-grade
(not regex) and cover EVERY data entry point: RSC fetches, **Route Handlers**, **Server Actions** (the
Permissions cell-cycle especially — a Server Action is a public POST), `generateMetadata`,
`generateStaticParams`, `route.ts`, `instrumentation`/cron. Rules: **scoping identifiers come from `ctx`
(session), NEVER from `args`/searchParams** (else a partner sets `?partner=someone_else` — IDOR); `Surface`
is a **closed union**, `assertCan` throws; **fail closed under RSC streaming** (a thrown `Forbidden` aborts
the response — test that nothing privileged flushes to a denied client); add React **taint APIs**
(`experimental_taintObjectReference` / `taintUniqueValue`) on raw rows + the DB creds as the belt to
`server-only`'s suspenders. State loudly: **`defineQuery` is NOT the row-isolation boundary — RLS is** — so
nobody "optimizes" a partner query off the `security_invoker` views.

**17.7 `ORDER BY` / identifier injection + sorting correctness.** postgres.js parameterizes *values*, not
*identifiers* — `sql\`… order by ${userCol}\`` from `?sort=` is injection. **Whitelist sortable columns
(zod enum) + `sql(col)` escaping.** And **sort server-side always**: client-sorting a paginated slice
answers "who owes the most" WRONG. **Adopt [nuqs](https://nuqs.dev)** for type-safe searchParams (don't
hand-roll parse/validate across sort+filter+page+depth × 8 screens).

**17.8 i18n enum labels (biggest i18n gap).** DB enums (`delta_status`, `verdict`, `verdict_strength`,
`aging_bucket`, `reality`, `review_priority`, evidence-signal names) arrive one-language → a zh UI half-English
on exactly the money/nationality terms. **Route every enum through the message catalog** (extend the
`tokens.ts` map already keyed by enum for *color* to also carry the localized *label*). Add next-intl **TS
augmentation** (missing/renamed key = `tsc` error). `fmtUSD` calls next-intl **`format.number({style:
'currency'})`**, never `'$'+toFixed`. Gate `text-transform`/letter-spacing to **Latin only** (CJK). Brand
names + free-text evidence stay source-language (can't translate data).

**17.9 Deploy hardening.** **PR previews point at a SEEDED NON-PROD DB, not the prod reader** (else real
commission money renders on ephemeral public URLs + preview pools draw down prod's ~100-conn budget) — reuse
the §9 schema-only + lens `pg_dump` seed. Put a **WAF/edge (Cloudflare)** in front of Railway: rate-limit
Server Actions/App-Router (the DoS CVE + allowlist brute-force), **strip `x-middleware-subrequest`** inbound,
block unauth `.rsc`/segment-prefetch to protected paths. **Lock egress** to {reporting DB, Google OAuth, FAS
weasyprint} — block `169.254.169.254` + internal IPs (neuters the SSRF class). `prepare:false` if a
transaction-mode pooler is ever added (**boot tripwire**, not a comment). Set `application_name='reports-ps'`
(visible in `pg_stat_activity`). `/api/health` = bare `select 1`, **not** through `defineQuery`.

**17.10 Observability floor (launch-blockers — a guest on someone's prod OLTP).** `pg_stat_statements`
filtered to the reader role; **connection-count alerting by role at ~70% of `max_connections`** (catches
pool leaks / preview creep / accidental autoscale); external **uptime + error monitoring** (Sentry) +
**ship structured logs** (Railway logs are ephemeral) stamped with request-id + `as_of`; **per-query timing
emitted from `defineQuery`** `{query_name, duration_ms, row_count, as_of}` → p95-per-screen for free, alert
on the >300ms benchmark; **one *verified* PITR test-restore**; a documented **reporting kill-switch** (REVOKE
the reader / scale app to 0 during a sync incident).

**17.11 Lens-contract drift = a SCHEDULED monitor, not just deploy-time.** The lenses are a cross-repo API
changed by hourly syncs + charter bots; a rename or *semantic* change breaks money silently until reporting
redeploys. Add a **scheduled (hourly/daily) contract test** that SELECTs each lens **as the reader**,
zod-parses a row, and checks enum domains against the token map → alarms in hours. Also assert the
"filter `reality != 'JUNK'` everywhere" rule centrally (one forgotten filter = wrong totals).

**17.12 DB-target honesty + connection split.** Railway has **no one-click managed read replica** — the real
options are self-operated Patroni HA or **logical replication of the lens base tables into a separate small
reporting Postgres** (which also gives us a place we own `FORCE RLS`). Write that upgrade path as a *project*,
not a toggle. The concrete **threshold to move reporting off the primary = external-partner onboarding**
(untrusted internet concurrency + blast radius, not just load). Keep the **reader and writer pools able to
point at DIFFERENT hosts from day one** so a later replica move doesn't strand the writable `app_*` schema.

**17.13 app_\* least-privilege.** `ps_reporting_writer` has privileges on the `app_*` tables **and nothing
else** (CI privilege assertion); prefer `app_*` in a **separate database/service** from operational data;
append-only audit (have); **pull export-audit forward for internal users** (log who/surface/rows/`as_of`
from day one — cheap INSERT into the trail we're already building).

**17.14 Explicitly NOT doing (discarded / deferred).** The Metabase/Superset/Evidence **build-vs-buy** pivot
(Tim ruled build). "Ship documents/Slack digests instead of a dashboard" — report automation is already
**P4**; the dashboard is the product. Charts stay **chart.js** (design-specced) but **colors driven from
`tokens.ts`/CSS vars** so dark mode + PDF don't drift (Recharts noted as an SVG alternative, not adopted).
Short-TTL cache keyed to the sync heartbeat = a **post-v1** perf win, noted not built.

## Appendix — research sources (2026)
Next.js 16 upgrade + proxy rename; CVE-2025-29927 (Datadog/JFrog/OffSec); Auth.js v5 migration + session
strategies + RBAC; shadcn Tailwind-v4/React-19; postgres.js pooling + numeric-as-string; next-intl routing +
`setRequestLocale`; next-themes SSR/flash. (URLs in the build session's research log.)
