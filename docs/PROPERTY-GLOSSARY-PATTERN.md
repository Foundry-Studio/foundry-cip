---
kind: doc
domain: client-intelligence-platform
status: active
last_updated: 2026-05-16
authors: [tim, cc-session-2026-05-16]
audience: [connector maintainers, new-tenant operators, agents querying CIP data, anyone who reads CIP data]
---

# The Tenant Property Glossary — CIP's plain-English semantic layer

> **The cardinal rule:** CIP stores ~1,000+ columns and JSONB keys per tenant (HubSpot alone has 1,170 properties for Wayward). The source-system label and description don't carry the actual meaning at THIS tenant. CIP MUST own a plain-English semantic layer on top, with confidence levels, so humans and agents can use the data correctly without archaeology.
>
> Every tenant gets a `GLOSSARY.md` file at `docs/tenants/<tenant_uuid>/GLOSSARY.md`. Every important column has an entry. Every entry has a confidence level. **No silent assumptions about what a column means.**

## Why this exists

On 2026-05-16, while answering "which Chinese clients are attributed to Tim?" we spent four round-trips guessing at `paid_referral` / `rev_share_partner` / `deal_owner` before discovering that Wayward actually uses `source` to encode affiliate-owner attribution (values like `"China Referral - Tim"`, `"China Referral - Eric (LYTASAUR)"`). The vendor `label` was just `"Source"`. The vendor `description` was blank. **The semantic layer between source schema and tenant business reality didn't exist.**

Tim's directive: "all columns must have our own internal description in logical and intuitive wording... be intuitive, not assume, research what it likely is, ask questions when onboarding, and leave 'possible' or 'tentative' when confidence is low or unknown."

This document defines the pattern CIP uses to solve that.

## The shape of a glossary entry

Every entry has these fields. The first four are required; the rest are strongly recommended.

| Field | Description | Example for `cip_deals.properties->>'source'` (Wayward) |
|---|---|---|
| `source_name` | Canonical name as the connector returns it | `source` |
| `cip_location` | Where in CIP this data lives | `cip_deals.properties->>'source'` (JSONB key) OR `cip_companies.name` (first-class column) |
| `plain_english_meaning` | **The new semantic layer.** Plain-language description of what this means at THIS tenant. Include examples. | "Affiliate-owner attribution for the deal. Format is typically 'China Referral - {person}'. Tim Jordan = 'China Referral - Tim'; Eric (LYTASAUR) = 'China Referral - Eric'; OpenLight = 'China Referral - OpenLight'. Non-affiliate sources include 'Organic', 'Paid Marketing', 'Event / Trade Show', 'Other'." |
| `confidence` | One of: `verified` / `inferred` / `tentative` / `unknown` | `verified` |
| `vendor_label` | Source-system label (auto-pulled from API) | "Source" |
| `vendor_description` | Source-system description (often blank) | (none) |
| `data_type` | string / number / datetime / enumeration / boolean / array / object | enumeration |
| `top_values` | Auto-derived top-N values + counts | "China Referral - Eric (809), Organic (282), China Referral - Adina (200), China Referral - Tim (380), 17 more" |
| `coverage` | Auto-derived coverage stat | "1.6% of deals have this set (49 of 3,057)" |
| `used_to_answer` | Sample business questions this column helps with | "Who gets commission attribution? Which deals are Tim's? Is this referral or organic?" |
| `aliases` | Lookup hints — alternate names a human/agent might search for | `affiliate_owner`, `referral_partner`, `attribution_source` |
| `watch_out_for` | NULL coverage, dirty values, mis-tagging, gotchas | "NULL on 98% of deals (only set on referred deals). Wayward's `segment='Chinese Brand'` tag is a SEPARATE field and is severely under-applied — don't use it as the canonical 'is Chinese?' signal." |
| `last_reviewed_at` | YYYY-MM-DD | 2026-05-16 |
| `last_reviewed_by` | Name | Tim Jordan |

## Confidence levels with behavioral rules

The confidence level is the most important field — it tells humans and agents how to USE the column.

| Level | Meaning | Agent / chatbot behavior when using this column |
|---|---|---|
| **`verified`** | Reviewed and confirmed by a human who knows the business | Use freely, no caveat |
| **`inferred`** | AI inferred from values + name + label, plausible but unconfirmed by a human | Use, but caveat with "Inferring from field name + sample data; verify before relying on this for revenue / legal / commission decisions" |
| **`tentative`** | Machine-generated baseline only (top values + coverage), no semantic meaning attached | Use only if no `verified` alternative exists; caveat strongly; recommend the user ask for clarification before trusting the result |
| **`unknown`** | Field exists in the data but no information about what it means | Refuse to use for analysis; surface "this column exists but I don't know what it means — can you tell me?" to the user |

## How a glossary gets populated

Three modes, in increasing rigor:

### Mode 1 — Auto-baseline (zero human effort)
On every connector run, a discovery step:
1. Pulls the full property catalog from the source's properties API (HubSpot `/crm/v3/properties/{type}`, Zendesk `/api/v2/ticket_fields.json`, etc.)
2. Samples the top-N distinct values per column + counts NULLs / coverage
3. Writes `tentative` entries for any column that doesn't already have a higher-confidence entry

This guarantees every column has SOMETHING in the glossary. Confidence is `tentative` by default. The `top_values` + `coverage` fields are objectively correct — the only thing missing is the semantic meaning.

### Mode 2 — AI-assisted onboarding interview (high-leverage, ~10 min per entity)
During tenant onboarding (per `ONBOARDING-A-NEW-TENANT.md` Phase 4.5), an agent walks the operator through high-traffic columns one at a time:

1. Agent shows the auto-baseline ("This column has 21 distinct values, top 5 are X / Y / Z. The values look like they encode affiliate ownership. Confirm?")
2. Operator either **confirms** (bumps confidence to `verified`, no rewrite needed), **corrects** (overwrites with the right explanation, marks `verified`), or **skips** ("I don't know" — stays `tentative`)
3. For columns where the AI is highly confident (e.g., obvious from name + values), it can self-promote to `inferred` without a human confirming, BUT NEVER to `verified`

10 minutes per entity, 30-40 columns reviewed per entity, 90% of query traffic covered.

### Mode 3 — Just-in-time annotation (lazy fill)
For any low-traffic column, when a query first uses it OR a user asks "what is this column?", the agent surfaces the auto-baseline and prompts the user to upgrade the entry. Only columns people actually CARE about get the full treatment.

## The "not every column" rule

Wayward's HubSpot alone has 1,170 properties. Full-treatment annotation of every column is ~100 hours per tenant — not realistic, and most of those columns will never be queried. The rule:

- **REQUIRED `verified` annotation** for every column on the first-class column set (domain columns on `cip_*` tables — ~80 fields total across all entities)
- **REQUIRED `verified` or `inferred` annotation** for any JSONB key that's been used in a query in the last 90 days (auto-tracked via a small query-log table, future scope)
- **AUTO-BASELINE `tentative` annotation** for everything else
- **The long tail of vendor-defined fields nobody queries stays `tentative` indefinitely** — no human time wasted

This gets ~95% of the value at ~5% of the effort.

## Where the glossary lives

Three layers that stay in sync:

1. **Source of truth: YAML or Markdown** at `docs/tenants/<tenant_uuid>/GLOSSARY.md`. Editable by humans. Reviewable in PRs. Survives DB wipes.
2. **(Future) Materialized into DB**: `cip_connector_property_registry` extended with new fields (description, plain_english_meaning, aliases, watch_out_for, confidence). A scheduled sync from the markdown → DB. Queryable by SQL / lens views. Enables agents to filter by confidence at query time.
3. **(Future) Surfaced via manifest**: `lens_tenant_manifest` (scope `bfc3d5d0`) gains a "Property catalog" section that joins the registry to current row counts. Agents and humans get one view that says "here's what's queryable, what each column means, how confident the meaning is."

For v1 (this scope `0246851d`), only layer 1 is built. Agents read the markdown like any other doc. Layer 2 + 3 follow if precision-at-query-time becomes a binding constraint.

## How a new connector starts off

A connector ships a **starter glossary** — the canonical fields the connector populates, with `inferred` confidence for fields the connector author understood from the vendor docs. This file lives in the connector's own folder (`cip/integration_mesh/connectors/<connector>/STARTER-GLOSSARY.md`).

On tenant onboarding, the starter glossary is COPIED into the tenant's `GLOSSARY.md` as a baseline, then the operator overrides / extends with tenant-specific knowledge. This means new tenants don't start from zero — they start from "what the connector author thought, plus what other tenants have learned."

## How a new tenant onboards

Per `ONBOARDING-A-NEW-TENANT.md` Phase 4.5 (Property Annotation Interview):

1. Auto-baseline runs (machine mode 1)
2. Starter glossary copied in if the connector ships one
3. Operator + agent walk through the entity-by-entity glossary review
4. Output: `docs/tenants/<tenant_uuid>/GLOSSARY.md` with at least `verified` entries for every domain column and `verified` or `inferred` for every JSONB key used in any known query

## How an agent uses the glossary

When an agent (chatbot, MCP-tool-using agent, or anything querying CIP) needs to issue a query against a tenant's data:

1. **Read the tenant's `GLOSSARY.md`** first (it's small — ~50 KB per tenant once populated)
2. **For each column the query intends to use:**
   - If `verified` → use without caveat
   - If `inferred` → use, attach caveat to the response: "Note: I'm inferring `<column>` means `<meaning>` from name + sample data. Verify before acting on this."
   - If `tentative` → ASK before using: "I see `<column>` exists with values like X, Y, Z. Looks like it encodes `<guess>`. Should I use it that way?"
   - If `unknown` → REFUSE: "I'd need to use `<column>` here but I don't know what it means at this tenant. Can you tell me, or should I look at something else?"
3. **After answering**, if the user confirms or corrects a `tentative` / `unknown` entry, the agent SHOULD propose updating the glossary (and the operator approves or rewrites the proposed entry).

## Connection to other CIP capabilities

| Capability | How it relates to the glossary |
|---|---|
| **Tenant Manifest (`bfc3d5d0`)** | The manifest's "Property catalog" section IS the glossary surfaced through SQL/MCP. Future scope materializes the glossary into the registry table for SQL-side filtering. |
| **Schema Drift Detector (`6e7f08bb`)** | When the source's property catalog changes (new field, value-distribution shift, type change), the drift detector flags the corresponding glossary entry — confidence drops automatically to `inferred` until re-reviewed. |
| **Onboarding runbook** | Phase 4.5 (Property Annotation Interview) is when the glossary is populated for a new tenant. |
| **Connector Authoring Guide** | New connectors ship a `STARTER-GLOSSARY.md` in the connector folder. |
| **Add-a-Use-Case procedure (`0e9b06e6`)** | Phase 1 (Tenant Profile) and Phase 2 (Gap Audit) consume the glossary to identify what's queryable. |

## Working example

See `docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/GLOSSARY.md` — EcomLever tenant / Wayward client glossary, populated as the first real-world instance. Use it as the model for any future tenant's glossary.

## Cross-references

- [`docs/ONBOARDING-A-NEW-TENANT.md`](ONBOARDING-A-NEW-TENANT.md) — Phase 4.5 references this pattern
- [`docs/CONNECTOR-AUTHORING-GUIDE.md`](CONNECTOR-AUTHORING-GUIDE.md) — starter glossary requirement
- [`docs/HUBSPOT-CONNECTOR-GUIDE.md`](HUBSPOT-CONNECTOR-GUIDE.md) and [`docs/ZENDESK-CONNECTOR-GUIDE.md`](ZENDESK-CONNECTOR-GUIDE.md) — reference the Wayward glossary as the working example
- PM scope `0246851d` — the scope this doc was authored under
