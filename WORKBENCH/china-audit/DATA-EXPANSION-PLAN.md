# CIP Data-Capture Expansion — Plan (WCC "Data Warehouse")

> **Status: PLANNING — nothing built.** Full design for capturing the raw data we have
> access to but don't store, so CIP becomes a **data asset** (reusable for reporting AND for
> CRM/data-products on other ventures), not just the commission engine. Authored 2026-07-18
> (Tim: "store raw GMV… HUGE for CRM on other projects… fold it all in — schema, pulling,
> calculations, the works, and plan the **blast radius**"). Sequenced BEFORE the reporting
> build (REPORTING-FRONTEND-*.md) — report on rich data, not thin.

Head migration: **cip_113** → new work is **cip_114+**. Read the migration-chain hazard
(§8) before any push.

> ### UPDATE 2026-07-18 — constraints locked (Tim)
> - **No Amazon API.** The Amazon ingest (F/G, old Sprint 3) is **dropped from this project.**
>   Seller-of-record for nationality stays a **manual / LLM web-enrichment** (exactly the
>   opportunity-queue reconciliation method), not a data pipeline here.
> - **Stripe: use the current key's scopes as-is (no expansion).** Probed live 2026-07-18 — the
>   restricted key already returns 200 on **invoices, customers, charges, subscriptions,
>   disputes, products, prices, balance_transactions, payouts, refunds, events.** So all of
>   B–E is in scope now, plus balance_transactions/payouts for cash reconciliation. **Caveat:**
>   `subscriptions` returned 0 rows — Wayward likely doesn't bill via Stripe subscriptions, so
>   MRR/subscription data may be empty; confirm at Sprint 2 and skip if so.
> - **Revised sprint set:** S1 Raw GMV → S2 Stripe extras (charges+card-country · disputes ·
>   products/prices · balance_transactions/payouts · subscriptions-if-any) → ~~S3 Amazon~~
>   (dropped) → S4 HubSpot engagement (optional).

---

## 1. What we're capturing (and why it's an asset)

| # | Data | Source | Why (reporting + sellable) | Access |
|---|---|---|---|---|
| A | **Raw GMV + ad-spend** per brand×product×month | derive now; Wayward/Amazon feed later | the funnel's stage ① + the core brand-performance metric | derive from fee÷rate now |
| B | **Stripe subscriptions/plans** (MRR, tier, status) | Stripe API (our key) | recurring-revenue analytics, churn | now* |
| C | **Stripe charges + card country + processing fee + net** | Stripe API | true cash movement, **card-country = nationality/risk signal** | now* |
| D | **Stripe disputes/chargebacks** | Stripe API | risk, refund-adjacent | now* |
| E | **Stripe product/price catalog** | Stripe API | what Wayward actually sells | now* |
| F | **Amazon seller-of-record** (INFORM Act name+address) | Amazon (scrape/API) | **the nationality source** we've hand-chased | pipeline |
| G | **Amazon product catalog + BSR + reviews/ratings + price** | Amazon | brand performance + **competitive market intel = highly sellable** | pipeline |
| H | HubSpot engagement/activity + deal-stage velocity | HubSpot API | behavioral CRM enrichment (firmographics already captured) | now |

*\*Stripe "now" is gated on the restricted key's read scopes — see §8 dependency.*

Priority: **A + C** first (highest value, uses data/keys we already have), then B/D/E, then
**F/G Amazon** as its own bigger project, then H.

---

## 2. Schema — a raw-facts layer (kept SEPARATE from the money lenses)

**Design rule (blast-radius control):** new capture lands in **thin raw-facts tables**; the
money engine (`lens_ps_commission_ledger` → `lens_ps_claim`) is **NOT touched**. Derived
metrics get their **own lenses**. This keeps the commission math isolated from data growth.
Every table: `tenant_id` + FORCE RLS + the `cip_tenant_scope` GUC policy (D-026), UUIDv4 PKs,
`ingested_at`/`source` provenance.

**cip_114 — raw revenue (A):**
- `ps_brand_revenue` (`wayward_brand_id`, `product_id`, `period_month`, `gmv`, `ad_spend`,
  `source` ∈ {derived, wayward_feed, amazon}, `rate_used`, `basis` ∈ {gross_billed}, `computed_at`).
  + `lens_ps_brand_revenue` (joins to eligibility for context) — the queryable asset.

**cip_115 — Stripe extras (B–E):**
- `ps_stripe_subscriptions` (`subscription_id`, `stripe_customer_id`, `wayward_brand_id`,
  `status`, `price_id`, `product_id`, `unit_amount`, `interval`, `current_period_start/end`,
  `mrr`, `created_at_stripe`).
- `ps_stripe_charges` (`charge_id`, `stripe_invoice_id`, `wayward_brand_id`, `amount`,
  `processing_fee`, `net`, `card_country`, `card_brand`, `funding`, `status`, `created_at_stripe`).
- `ps_stripe_disputes` (`dispute_id`, `charge_id`, `stripe_invoice_id`, `wayward_brand_id`,
  `amount`, `reason`, `status`, `created_at_stripe`).
- `ps_stripe_products` (`product_id`, `name`, `active`, `metadata`, `updated_at_stripe`).
- (card_country also feeds `ps_nationality_signals` as a soft signal — see §4.)

**cip_116 — Amazon (F–G), its own migration + connector:**
- `ps_amazon_sellers` (`wayward_brand_id`, `seller_id`, `business_name`, `address`,
  `country`, `marketplace`, `source_url`, `fetched_at`) — the seller-of-record.
- `ps_amazon_products` (`asin`, `wayward_brand_id`, `title`, `category`, `bsr`, `rating`,
  `review_count`, `price`, `currency`, `fetched_at`).

**cip_117 — HubSpot engagement (H, optional):** `cip_engagements` (activity history) — defer.

Descriptions for every table/column go in the migration docstring + SOURCE-MAP.md + a new
schema section in LENS-CATALOG.md.

---

## 3. Automated pulling (per FAS/JOS governance)

Mirror the shipped CIP ingest pattern (`ps_stripe_sync` + FAS `SYSTEM_SCHEDULES` + the
`SyncRunRecorder` heartbeat + `cip_sync_runs`).

- **Stripe extras (B–E):** EXTEND `cip/integration_mesh/sync/ps_stripe_sync.py` (same key +
  urllib transport + Events-API cursor + 24h lookback + weekly full). Add list/backfill for
  subscriptions, charges, disputes, products; hydrate-by-ID on events. New connector_id
  heartbeats: `ps-stripe-subs-v1` etc. (or fold into `ps-stripe-v1`). New FAS schedule if a
  separate cadence is wanted; else piggyback the hourly Stripe run.
- **Raw GMV (A):** a **calculation step** (not a pull) — recompute `ps_brand_revenue` after
  each Stripe sync (derive from the invoice lines ÷ eligibility rate). Idempotent upsert.
- **Amazon (F–G):** a **NEW structured connector** `cip/integration_mesh/connectors/amazon/`
  (connector.py + mapper.py, the Protocol pattern like hubspot/zendesk). Client = scraper or
  SP-API. Own FAS schedule (daily/weekly — Amazon is slow-changing) + `amazon-v1` heartbeat.
  This is the seller-of-record enrichment already scoped in AUTOMATIONS-PLAN §(1).
- **Governance:** all reads; no new MCP write tools; each new schedule carries the mandatory
  keys + `system-maintenance` tag + explicit `max_consecutive_failures`; freshness watchdog
  gets a `CONNECTOR_HEARTBEATS` entry per new connector (the pattern shipped in cbe5d238).

---

## 4. Calculations / derivations
- **Derived GMV** = `gross_usage_billed ÷ NULLIF(client_fee_rate,0)` (Connect); Boost
  `ad_spend = boost_fee ÷ NULLIF(boost_rate,0)`. Guarded (null/zero rate → NULL gmv, surfaced
  in Exceptions, never Infinity). `basis='gross_billed'` recorded so it can't be silently
  confused with net. `source='derived'`.
- **MRR** = subscription unit_amount normalized to monthly.
- **Net cash** = charge amount − processing_fee.
- **Card-country signal** — when a brand's Stripe card_country ∈ {CN,HK,MO}, insert a
  `ps_nationality_signals` row (`signal='stripe_card_country'`, soft strength) — a NEW,
  cheap corroboration for the china verdict (feeds the money engine's evidence, not its math).

---

## 5. BLAST RADIUS (what this touches — the important part)

**Overall: mostly ADDITIVE and well-contained IF the money engine stays untouched.** Impact
by surface, with the guard:

| Surface | Impact | Guard |
|---|---|---|
| **Money engine** (`commission_ledger`→`claim`) | **NONE if additive.** New data is side-tables + new lenses; commission stays on collected fees. | Do NOT modify existing money lenses. New metrics = new lenses only. Regression: recovery number penny-identical before/after each migration. |
| **RLS / tenant (D-026)** | each new table needs FORCE RLS + `cip_tenant_scope` policy | copy the policy in every migration; test cross-tenant SELECT is empty |
| **Migration chain** | cip_114–117; the **down_revision rebase-collision class (9× recurrence)** | fetch origin/master + `git status --short migrations/` for `??` before every push; alembic up/down/up on a local container; check `alembic_version` len ≤32 |
| **Invariant suite** (`ps_invariants.py`) | ADD invariants: gmv≥0, gmv×rate≈billed (reconciliation), charge-sum vs invoice-paid, new-table row sanity | additive; keep the 22 existing green |
| **Freshness watchdog** (FAS) | new syncs → new heartbeats | add `CONNECTOR_HEARTBEATS` entries (shipped pattern) |
| **FAS scheduler** | new schedules | seed-authoritative cron + explicit mcf + tag (WEP-D080) |
| **Nationality/money evidence** | card-country signal ADDS china evidence → a few unknowns may flip china (money moves) | expected + desirable; reconcile the delta, document it |
| **Stripe key scopes** | pulling new objects may exceed the restricted key's read scopes | **dependency** — verify/expand (§8) |
| **Storage/cost** | Amazon product/review data can be large | cap fields; store BSR/rating snapshots, not full review text (v1) |
| **Reporting plan (P4)** | BENEFIT — real ① GMV + richer screens | no conflict; reporting build comes after |

**The one real money-moving effect:** the card-country nationality signal can flip a few
brands to china (adds evidence). That's the system working — but it's a **reconciliation
event** (the backlog number will move), so it's gated behind an explicit review, not silent.

---

## 6. Backfill + reconciliation
- **Derived GMV:** one-time compute over ALL historical invoice lines → `ps_brand_revenue`;
  then ongoing after each Stripe sync. Reconcile: `sum(gmv × rate)` ≈ `sum(gross_billed)` per
  month (should tie by construction — a mismatch = a rate/basis bug).
- **Stripe extras:** full backfill via Stripe list endpoints (subs/charges/disputes/products)
  bounded by the account's history; then event-driven ongoing. Reconcile: charges paid vs
  `ps_stripe_invoices.amount_paid`; disputes vs refunds.
- **Amazon:** backfill seller-of-record + product snapshot for the full brand list (start with
  the billing brands); reconcile seller-country against existing china verdicts (agreement
  check — a disagreement is a research flag, per the reconciliation we just did).
- **Card-country signal reconciliation:** compute the would-be china flips FIRST, review, then
  apply (never silent) — same discipline as the 2026-07-18 opportunity-queue flips.

---

## 7. Sequencing into build sprints (staged, ready to start)
- **Sprint 1 — Raw GMV (A):** cip_114 (`ps_brand_revenue` + lens) · derivation calc + backfill
  · invariants · reconciliation · docs. *Highest value, our own data, low blast radius.*
- **Sprint 2 — Stripe extras (B–E):** verify/expand key scopes · cip_115 · extend
  `ps_stripe_sync` + backfill · charges/card-country/disputes/subs/products · card-country
  nationality signal (compute→review→apply) · heartbeats · invariants · docs.
- **Sprint 3 — Amazon (F–G):** the big one, own project — cip_116 · new `amazon/` connector +
  client (scrape/SP-API) · seller-of-record + product/BSR backfill · reconcile vs verdicts ·
  schedule + heartbeat · docs. *Access-reality spike first.*
- **Sprint 4 — HubSpot engagement (H, optional).**
- **THEN → reporting build** (P4, already planned/QC'd) on top of the enriched data.

Each sprint DoD: schema migrated (up/down/up verified) · pull automated + heartbeated ·
backfilled · reconciled (invariants green) · money-engine recovery number unchanged ·
documented (SOURCE-MAP + LENS-CATALOG + migration docstrings).

---

## 8. Dependencies, risks, open decisions
- **Stripe key scopes (dependency):** confirm the restricted key can read subscriptions/
  charges/disputes/products; if not, get a key with expanded READ scopes (Tim/Jake). *(Never
  a write scope.)*
- **Amazon access (risk/spike):** SP-API needs seller auth we likely lack → scraping (ToS +
  brittleness) vs a data vendor. **Decision:** run a small access spike before committing
  Sprint 3 scope.
- **Raw-GMV source (decision):** derived-now is the v1; is a **raw** Wayward/Amazon GMV feed
  worth pursuing, and from whom? (derived reconciles by construction, so it's honest; raw
  only matters if Wayward's GMV ≠ fee÷rate, e.g. tiered/blended rates.)
- **Card-country flips (review gate):** the china flips it implies get reviewed before apply.
- **Storage:** Amazon review/product volume — snapshot metrics, not full text, in v1.

---
*Plan-of-record for the data expansion. Pairs with AUTOMATIONS-PLAN.md (P3 ingest pattern),
PROGRAM.md, and the parked REPORTING-FRONTEND-*.md (built after this lands).*
