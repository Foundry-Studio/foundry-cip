# SCHEMA AUDIT — Round 1: does the schema HOUSE our four sources?

**Scope (Tim, 2026-07-15):** before automations, confirm the current schema cleanly houses everything
we get from **Stripe, HubSpot, the Slack `#amazon-brand-connections` thread, and Zendesk** — and
sweep out fields/tables that aren't needed or aren't intuitive. Not auditing automations here; just
making sure the shape is right for when we do.
**Method:** live prod schema + the connector property registry + the ingest code, 2026-07-15.
**Nothing changed** — this is findings + recommendations. Schema changes happen only on Tim's yes.

---

## VERDICT

**The schema houses all four sources well.** No source is losing data it captures. The real findings
are: (a) a handful of Wayward's OWN money numbers live only in JSONB, un-typed — and P5 needs them;
(b) a few genuinely dead tables (the "like the nationality one" cases); (c) the raw `cip_*` source
tables carry almost no column documentation, which hurts human/agent readability; (d) `SOURCE-MAP.md`
itself is now stale. WeChat + a 2nd brand contact are known-new and already on P1.

---

## PER-SOURCE COVERAGE

| source | how it lands | tables | coverage |
|---|---|---|---|
| **Stripe** | manual ingest (`ingest_stripe_invoices.py`, `ingest_stripe_customers.py`) | `ps_stripe_invoices` (25 cols), `_invoice_lines` (20, the money spine), `_customers` (18) | **Good.** Amounts (due/paid/remaining/subtotal/total), status/paid/collection_method, periods, `is_ps_base`, `fee_type`, `billing_month`, `address_country`, `delinquent`, `customer_type`, `auth0_id`. Everything the money math needs is typed. |
| **HubSpot** | `hubspot-v1` connector, hourly :17 | `cip_companies` (132k), `cip_contacts` (87k), `cip_deals` (5.2k), `cip_engagements`, `cip_tickets` | **Good, with a typed-access gap** — see Finding 1. Core fields typed; Wayward's money fields sit in the `properties` JSONB. |
| **Slack thread** | manual ingest (`ingest_slack_brand_connections.py`) → `ps_brand_observations` | 14 fields/event × 1,348 events | **Good.** Extracts identity (hubspot_company_id/deal_id, wayward_brand_id), contact (name, email), nationality (country, website), attribution (deal_source, referral_source), and fees (usage_fee/saas_fee). One contact per event (the signup person) — the 2nd contact + WeChat is the known P1 add. |
| **Zendesk** | `zendesk-v1` connector, hourly :47 | `cip_tickets` (4.4k), `cip_ticket_comments` (12.8k) | **Adequate.** Synced clean. `via_channel` sits in overflow (minor). Deeper CS-field audit deferred — dormancy is now SALES-based (not Zendesk), so Zendesk is low-stakes for this program. |

---

## FINDINGS

### 1. ⭐ HIGH VALUE — Wayward's own money numbers are captured but only in JSONB
`cip_deals.properties` holds Wayward's stated per-brand figures, un-typed:
| field | populated | why it matters |
|---|---|---|
| `total_fees_paid` | 2,911 / 5,216 deals | **What Wayward SAYS a brand has paid** — the other side of P5's owed-vs-paid |
| `lifetime_usage_fees_generated` | 3,473 | Wayward's usage-fee number to reconcile against our Stripe spine |
| `lifetime_gmv` | 3,484 | brand scale |
| `amazon_seller_type` | 276 | China-relevant (seller entity type) |
| `hyphen_gmv_rank` / `hyphen_units_sold_rank` (on `cip_companies`) | 2,870 / 132k | brand performance rank |

They ARE synced (a lens already casts some out of JSONB), but JSONB-only means every consumer
re-parses and re-casts. **Recommendation:** promote the money-relevant ones to typed columns (or a
dedicated typed lens) so P2's engine and P5's reconciliation read them as first-class, cast-once.
Decision belongs with the P2 math design (what exactly to type), flagged here so it's not discovered
mid-build.

### 2. Dead / unneeded tables (the "like the nationality column" cases)
| table | rows | finding | recommend |
|---|---|---|---|
| `cip_test_trace` | 0 (1 col) | test artifact in prod | **drop** |
| `ps_classification_rules` | 10 | created cip_39 for the old nationality classifier; **read by no live code** (grep: only migrations). Orphaned like the cip_97 removals. | **drop** (Tim confirms) |
| `cip_marketing_emails` | 0 | HubSpot object, never synced | drop or leave (dead schema) |
| `cip_contact_lists` / `cip_contact_list_memberships` | 0 / 0 | HubSpot lists, never synced | drop or leave |
*(A deeper COLUMN-level dead sweep across all 55 tables is Round 2 — this round is table-level +
the source lens.)*

### 3. Naming / documentation — the raw `cip_*` layer is undocumented
27 of 55 tables have no table comment; the gap is entirely the **raw `cip_*` source tables**
(0/24 columns commented on `cip_companies`, 0/37 on `cip_engagements`, etc.). Our own `ps_*` audit
tables are well-commented. The field meanings DO exist — in `cip_connector_property_registry`
(`plain_english_meaning`, `watch_out_for`) — but not on the columns, so a human or agent reading the
table directly is flying blind. **Recommendation:** add table comments to the `cip_*` tables (at
minimum a one-liner + "field meanings: see cip_connector_property_registry"); optionally sync the
registry's `plain_english_meaning` onto the JSONB-backed columns. Low-risk, high readability payoff.

### 4. `docs/SOURCE-MAP.md` is stale
Dated 2026-07-14, pre-cip_95/97. Says china_status is **4-state** with `probable` (retired), lists
`ps_added_facts` as **3 rows** (now 751), and predates the nationality-system removal.
**Recommendation:** refresh it as part of this round (it's the map everyone reads first).

### 5. Confirmed-new for P1 (already tracked, restated for completeness)
WeChat contact field + a 2nd brand contact (primary/secondary, name+email+wechat). Jake's WeChat
list is the first data. Separate from partner attribution (already per-product).

---

## SLACK #amazon-brand-connections — deep check (2026-07-15)
The channel is an automated **n8n** feed: one structured message per new brand
(`*Label*: value`), parsed by `scripts/ingest_slack_brand_connections.py` into
`ps_brand_observations`.
- **Schema is ready — every field has a home.** `ps_brand_observations` is a generic key-value fact
  store (one row per field, with `source_system` + a Slack permalink `source_ref`), so ANY field the
  feed carries lands cleanly as an observation. This is the "facts vs conclusions" design — Slack
  says Country=CN, HubSpot says US, both coexist as facts; the decision layer resolves them.
- **We capture 14 fields** (all populated): brand_name, website, contact_name, email,
  connection_event_at, products_synced, referral_source, wayward_brand_id, country, deal_source,
  usage_fee, saas_fee (+ hubspot_company_id / hubspot_deal_id from the link URLs). `usage_fee`/
  `saas_fee` are only on ~897 of 1,348 (logged only on China-referral deals — expected).
- **The one gap is INGEST completeness, not schema:** the parser maps a FIXED 12-label whitelist
  (`_FIELDS`), so any NEW n8n label is silently dropped. Not verifiable from this environment (no
  Slack token / read tool / stored sample) — **needs one raw "New Amazon Brand Connection" message
  to diff against the 12.**
- **Automation design rule (P3):** the rebuilt ingest should parse EVERY `*Label*: value` generically
  (not a fixed whitelist) so a new n8n field auto-flows in as an observation with no code change.
  That is the "goes in clean" guarantee.

## WHAT THIS ROUND DID NOT DO (proposed Round 2, needs Tim's input)
- **Column-level dead sweep** across all tables (which specific columns nothing reads).
- **The "is anything MISSING that we NEED" gut-check** — coverage against *what the source provides*
  is mechanical and done here; coverage against *what we practically need* requires Tim's braindump
  (the same one queued for the math phase). That's the higher-value pass and it's collaborative.
