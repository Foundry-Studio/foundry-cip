# SOURCE MAP — every source of truth for the Wayward × Project Silk book

**Last verified:** 2026-07-20 against prod (schema head `cip_119`).

> **UPDATE 2026-07-20 — several "manual / never-ingested" flags below are now STALE.**
> Stripe is LIVE-SYNCED: `ps-stripe-v1` (the money spine — invoices/lines/customers/
> refunds, hourly) + `ps-stripe-extras-v1` (charges +card_country, payouts, the
> `balance_transactions` fee/net ledger, disputes, products, prices — every other day).
> The derived-GMV + Stripe data-asset surface landed in **cip_114–119** (see
> `WORKBENCH/china-audit/DATA-EXPANSION-PLAN.md` + `LENS-CATALOG.md`). Row counts and the
> "❌ manual / no schedule" cells below predate that — for Stripe, trust the migrations +
> the live `cip_sync_runs` heartbeats over this doc.
> ⚠️ **Partially stale (2026-07-16).** Head is now `cip_109`; the cip_100–109 wave (WeChat fields,
> `ps_partner_payouts`, the whole money engine) isn't reflected below, and the book counts have moved.
> Source-of-truth *buckets* are still valid; for money lenses + live counts see
> [../WORKBENCH/china-audit/LENS-CATALOG.md](../WORKBENCH/china-audit/LENS-CATALOG.md).
**2026-07-15 refresh:** the nationality verdict is now **3-state** (china / not_china / unknown —
`probable` retired in cip_95); the old `cip_clients` nationality system + 4 dead views were removed
(cip_97); two dead tables dropped and the raw `cip_*` layer documented (cip_98/99). This program's
read-first map is now `WORKBENCH/china-audit/PROGRAM.md`.
**Why this exists:** an entire analysis was built on `ps_*` tables while HubSpot, Zendesk, the
knowledge base and an identity graph sat unread **in the same database**, syncing hourly. Brands
were graded *"cannot be proven Chinese"* — including a client whose Chinese product library we had
already ingested. **Read this before you conclude any data is missing.**

> ## The rule
> **"Not in the database" NEVER means "not provable."** It means *go and get it* — or *ask the
> human who knows*. Absence of evidence is an **ingestion gap** or a **research task**. It is
> never a verdict.

---

## THE SEVEN BUCKETS

Every table belongs to exactly one. The bucket tells you **who owns the value and what its
lifecycle is** — which is what stops raw feed data, human judgement and derived conclusions from
being silently blended together (the failure that caused the 2026-07-14 reset).

| bucket | who writes it | may a human edit it? |
|---|---|---|
| **1. RAW** | a connector, on a schedule | ❌ never |
| **2. IDENTITY** | resolution logic | ❌ (corrections go via ADDED) |
| **3. LABELS** | a source's own classification | ❌ |
| **4. EVENTS** | derived from RAW | ❌ |
| **5. ADDED** | **a named human** | ✅ **this is the point** |
| **6. DECISIONS** | derivation, reading ADDED first | ❌ (a decision *pins*; only ADDED moves it) |
| **7. FRESHNESS** | the schedulers | ❌ |

---

## 1. RAW — what the feeds say. Never edited. Refreshed on schedule.

### ✅ Already syncing, hourly, in this database — **CONSUME, DO NOT REBUILD**

| table | rows | what it holds | schedule |
|---|---|---|---|
| **`cip_companies`** | **132,311** | HubSpot companies — **`country`, `domain`, `region`, `language`, `city`, `industry`** + a `properties` JSONB | `cip_wayward_hubspot` — **:17 hourly** |
| **`cip_contacts`** | **87,115** | HubSpot contacts — **`email`, `phone`, `firstname`, `lastname`, `jobtitle`** | same |
| `cip_deals` | 5,209 | HubSpot deals, pipeline stages | same |
| `cip_engagements` | 12,552 | emails / calls / notes | same |
| **`cip_tickets`** + comments | 4,174 / 12,869 | **Zendesk** — per-brand CS activity | `cip_wayward_zendesk` — **:47 hourly** |
| **`cip_knowledge_chunks`** | **36,492** | the knowledge base — **ingested client libraries** *(Grownsy is in 10 chunks)* | — |
| `cip_clients` | 1,527 | the PS lens mirror; carries `wayward_brand_id` | `cip_ps_lens_mirror` — **:37 hourly** |
| `cip_*_history` | 1.5M+ | full change history on companies/contacts/deals | — |

**Connector health (verified 2026-07-14):** HubSpot ✅ (844 successful runs, 124k rows), Zendesk ✅,
LensMirror ✅. A `cip_freshness_watchdog` already runs at **:23 and :53**.

**`cip_connector_property_registry` (99 rows)** documents every synced property, with
`plain_english_meaning`, `coverage_pct` and **`watch_out_for`**. Read it before guessing what a
HubSpot field means.

> ⚠️ **Available in HubSpot but NOT being synced:** `hyphen_gmv_rank`, `hyphen_units_sold_rank`,
> `hyphen_overlapping_gmv` — brand **performance** data, registered but with no storage column.
> **Worth adding to the sync.**

### Ours — the Wayward book

| table | rows | source | scheduled? |
|---|---|---|---|
| `ps_stripe_invoice_lines` | 75,658 | Stripe — **the money spine**. `is_ps_base` = usage fees (our base); everything else is creator pass-through | ❌ **manual** |
| `ps_stripe_invoices` | 15,307 | Stripe | ❌ manual |
| `ps_stripe_customers` | 5,754 | Stripe — `metadata.brandId`, `auth0id`, `intCustomerType`, `delinquent` | ❌ manual |
| `ps_brand_observations` | 32,694 | **Slack `#amazon-brand-connections`** + Eric's sheets + partner claims. Append-only evidence | ❌ manual |
| `ps_payment_events` | 2,271 | **Jake's monthly reports** — what Wayward says it paid us | ❌ manual |

### 🔴 Never ingested

| source | status |
|---|---|
| **Brand websites** (1,345 known) | never fetched. `.cn` TLD, Chinese-language content and **ICP filing numbers** are hard nationality evidence |
| **Amazon storefront "Sold by"** | never fetched. Sellers must disclose the legal entity + address |
| **Rhea's partner roster & rates** | not received |
| **WeChat ids** | Jake's list incoming (P1) → WeChat contact field + a 2nd brand contact being added to `ps_brand_contacts` |

---

## 2. IDENTITY — who is who

| table | rows | notes |
|---|---|---|
| `ps_brands` | 5,352 | **the brand master.** PK = `wayward_brand_id`. 12 FKs point at it. `canonical_brand_id` collapses split identities (SpaceAid billed usage on one id and was PAID on another) |
| **`cip_identity_links`** | **19,205** | **a pre-existing identity graph** (`left_connector`/`left_source_id` ↔ `right_connector`/`right_source_id`, with `confidence` + `method`). Links Zendesk ↔ HubSpot. **Not yet folded in — two identity systems is one too many** |
| `ps_partner_aliases` | 251 | 236 raw spellings → the real partners. `xq` = `Xueqiu` = `雪球` = **Kerry** |

**Join keys, ranked:**

| key | strength | coverage |
|---|---|---|
| `wayward_brand_id` (Stripe `metadata.brandId`, or the `description` field) | **exact** | 99.9% of usage lines |
| `hubspot_company_id` (from the Slack feed) | **exact** | 1,347 brands → **1,321 resolve** in `cip_companies` |
| `auth0id` | exact | 100% of registered brands |
| domain / email | ❌ **NEVER a key** | **531 emails map to >1 brand** — `dpathania@artica.com` → **19**; `creators@wayward.com` → 11. **Candidate-generator only → `probable`, never `confirmed`** |
| brand name | ❌ never | 689 duplicate-name groups |

---

## 3. LABELS — a source's classification (not a raw fact, and it can be wrong)

| table | what | trap |
|---|---|---|
| `ps_excluded_brands` | 817 rows / **807 brands** — the frozen list (2025-11-18) | **10 brands sit in TWO buckets.** Use `lens_ps_exclusion_status` (aggregated); a raw join **fans out and inflates by 8.6%** |
| `deal_source` (obs) | "China Referral - Tim/Eric/Adina/…" — whose book | *provenance, not permission* |
| flat-fee vs rev-share | from **Eric's own sheet** | **not a contract concept.** But it decides winnability: flat-fee = nobody earns ongoing |
| `intCustomerType` | Stripe — `PARENT_BRAND` | the 474 without it were never onboarded through the brand flow |

> **BrüMate**: on the exclusion list (OceanWing) *and* flagged US by Wayward. It is **American,
> referred by a Chinese partner**. The list asserts a **referral channel**, not a nationality.

---

## 4. EVENTS — the date pipeline *(to build)*

Five different dates with real lags. **Never compare across stages by month.**

```
usage month → Wayward reconciles → invoice to brand → brand pays → Wayward pays US
                                                                    (1–3 months later)
```
**Measured:** payment lands **2 months** after usage (794 brand-matches), sometimes 1 or 3.

Per **deal** (brand × product): `onboarded` · `productive_date` (first billed sale) ·
`dormant_since` (90d) · `reactivated_at`.

---

## 5. ADDED — what humans tell us. **Outranks every machine signal.**

| table | rows | |
|---|---|---|
| **`ps_added_facts`** | 751 | Tim's determinations, Rhea's roster, Jake's lists, decoded referrer codes, **and the activation evidence the contested Boost book turns on** |

**PINNED**: automated evidence may **flag** a pinned fact in the conflicts queue — it may **never
flip it**. Only a superseding human row moves it. Loader: `scripts/load_added_facts.py`.

---

## 6. DECISIONS — derived, THREE-state (cip_95), and they pin

`verdict ∈ {china, not_china, unknown}` in `lens_ps_china_verdict`. (`probable` retired cip_95 — a
pinyin PERSONAL name is not a verdict; the evidence grid flags it and routes it.)

- **`unknown`** → a research/data task. **Never "no."** It propagates as NULL, never as false.
- **`not_china`** requires a human ruling or a LEGAL record (`amazon_seller_entity` /
  `uspto_trademark_owner`) — **never** Wayward's country flag.
- Evidence lives as **rows** (`ps_nationality_signals`, ~8,531) — one per source. Slack=CN and
  HubSpot=US **coexist**; disagreement surfaces in the conflicts queue.
- Precedence: **ADDED (a human) > `on_exclusion_list` > CHINA WINS > not_china > unknown.**
- Book today: **china 1,600 · not_china 310 · unknown 652** (REAL companies, `lens_ps_china_companies`).

**Ownership** (`is this deal ours`) — the settled, schema-reviewed deal rules now live in
`WORKBENCH/china-audit/OWNERSHIP-RULES.md` (2026-07-15). **The deal is brand × PRODUCT.**

---

## 7. FRESHNESS

| | |
|---|---|
| `cip_sync_runs` (4,220) | per-run: connector, status, rows, timings, errors |
| `schedule_definitions` (41) | `cip_wayward_hubspot` :17 · `cip_wayward_zendesk` :47 · `cip_ps_lens_mirror` :37 · `cip_freshness_watchdog` :23,:53 |
| 🔴 **gap** | **our Stripe / Slack / Jake ingests are MANUAL.** No schedule, no invariants, no post-sync recompute |

---

## THE TRAPS — every one of these has already cost money

1. **`commission_fees` is NOT our base.** ~**4.6× larger** than usage fees ($13.6M vs $2.97M). It's creator pass-through. **Use `usage_fees`.**
2. **`amount` is DOLLARS, not cents.** Dividing by 100 understated the whole book by 100×.
3. **`billing_month` ≠ the billing cycle.** It's the month the usage is *for*; they differ by 1–7 months, and the 10/6/3 step-down is month-sensitive.
4. **A VOIDED invoice was never billed.** Counting voids inflated "billed" by **$561,209** and made *collected > billed* on 73 rows. **A REFUNDED usage fee was not, in the end, *received*** — `usage_collected` nets succeeded refunds (their `is_ps_base` invoice share only), per the contract's "actually received" (cip_113 / `lens_ps_refund_allocation`).
5. **Use CALENDAR MONTHS, not day counts.** `+365+183` = 548 days, but 18 calendar months is 546–549 — month 19 slipped inside and kept 6%.
6. **NULL ≠ zero.** NULL = *we don't know* (must never become a number). A sentinel (`'unassigned'`) = *we know there is none*. Collapsing them turned unknowns into confident $0.00.
7. **A raw join to `ps_excluded_brands` FANS OUT.** 817 rows, 807 brands.
8. **A migration a script overwrites is not a fix.** cip_68 corrected data; the next `--apply` silently re-broke it.
