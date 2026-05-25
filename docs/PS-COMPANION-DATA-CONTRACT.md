---
id: CIP-SPEC-012
uuid: 4f8d2a1e-9c3b-4e7a-b6d8-7e9f1a2b3c4d
title: Project Silk Companion Data Contract — keys, enums, ownership boundary
type: spec
owner: tim
solve_for: The shape and ownership rules for `companion_data` JSONB on the
  five PS-mirrored entity tables. Defines the 13 companion keys, three
  enumerations, the Twenty-vs-CIP authorship boundary, and the priority
  rule for engagement_health.
stage_label: adopt
domain: meta
version: '1.0'
created: '2026-05-22'
last_modified: '2026-05-22'
last_reviewed: '2026-05-22'
review_cadence: 180
authority_decisions:
- 250
references:
- CIP-SPEC-010
- CIP-SPEC-011
- CIP-FW-003
- CIP-FW-004
---

# Project Silk Companion Data Contract

This doc defines the **shape** and **ownership** of `companion_data` JSONB on the five PS-mirrored entity tables (`cip_clients`, `cip_companies`, `cip_contacts`, `cip_deals`, `cip_tickets`), plus the destination-side lens views in [`cip_26`](../cip/migrations/versions/cip_26_ps_lens_views.py) that read it.

Companion data is the **sidecar field model** Atlas locked under [CIP-FW-003](vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md) Q1 + reaffirmed for the Phase 2.7 dest-side recut. The schema column was added in [`cip_23`](../cip/migrations/versions/cip_23_phase26_schema.py); the column-level GRANT enforcing Twenty's write-back path was provisioned in [`cip_25`](../cip/migrations/versions/cip_25_project_silk_twenty_role.py); the read-side lenses ship in [`cip_26`](../cip/migrations/versions/cip_26_ps_lens_views.py).

## 1. Ownership boundary

Two parties write to PS's `cip_*` tables. They write to **different physical columns**:

| Column                              | Writer                                       | Authority                                                                              |
| ----------------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------- |
| `source_id`, `name`, `properties.*` | LensMirrorConnector (Pass 1/2 orchestration) | EcomLever — **overwritten every re-sync**. Never edit in PS; the mirror will clobber. |
| `companion_data`                    | Twenty CRM (via `cip_twenty_project_silk` role) | Project Silk — **never written by the mirror**. Mapper doesn't emit this column.       |

The structural enforcement is **column-level GRANT UPDATE (companion_data)** on the Twenty role from cip_25 plus the mapper's omission of `companion_data` from emitted fields (the mirror physically cannot write it). Atlas's Q1 verdict was "this is the entire enforcement layer" — no application-side validation needed.

## 2. The 18 companion keys

`companion_data` is JSONB. Keys are flat (no nesting) and the contract is **additive only**: future migrations may add keys; never repurpose or remove an existing key without a Tim-gated review.

| Key                       | Type     | Required | Description                                                                          |
| ------------------------- | -------- | -------- | ------------------------------------------------------------------------------------ |
| `ps_segment`              | enum     | yes      | Which PS sub-business this brand belongs to. Currently single-valued: `china_referral`. |
| `ps_onboarded_status`     | enum     | yes      | Where in the PS onboarding funnel. Drives the `lens_ps_china_brands_onboarded` view. |
| `ps_engagement_health`    | enum     | yes      | Current health signal. Drives the `lens_ps_china_brands_producing` view.             |
| `ps_local_alias_zh`       | string   | no       | Chinese-language brand alias used by the PS China CS team.                           |
| `ps_local_alias_en`       | string   | no       | English alias if different from the HubSpot/EcomLever canonical `name`.              |
| `ps_team_notes`           | string   | no       | Free-form notes from the PS team (rendered in Twenty).                               |
| `ps_commission_pct`       | number   | no       | Commission split percentage for this brand (0–100). Distinct from the per-deal commission attribution which lives on `cip_deals.properties.source`. |
| `ps_billing_currency`     | string   | no       | ISO 4217 code (e.g. `USD`, `CNY`). Defaults to deal currency if absent.               |
| `ps_invoice_cadence`      | enum     | no       | `monthly`, `quarterly`, `per-shipment`. Free until a fourth value is needed.         |
| `ps_payment_terms_days`   | integer  | no       | Net terms, e.g. 30, 60.                                                              |
| `ps_lead_owner_email`     | string   | no       | PS-team person responsible for this brand. Email key (matches `cip_owners`).         |
| `ps_first_onboarded_date` | date     | no       | ISO-8601 date string. The date PS started managing this brand (NOT the EcomLever close date). |
| `ps_last_reviewed_date`   | date     | no       | ISO-8601 date string. Set when a PS rep does the periodic engagement review.         |
| `ps_attribution_owner`    | enum     | no       | Whose 10% commission this brand's book is. `PS` = ours (even when a partner referred — we split). A partner value = their book. See §3.4. Drives `lens_ps_china_commission`. |
| `ps_conditional`          | enum     | no       | `finders_fee` flags Eric/Adina one-time-paid, flippable brands (partner referred but not earning ongoing). Blank otherwise. See §3.5. |
| `ps_lead_source`          | enum     | no       | Referrer for PS-owned brands — the commission-split key (pairs with `ps_commission_pct`). Same value set as `ps_attribution_owner` minus `unclassified`/`heavy_producer`. See §3.4. |
| `ps_sales_lead`           | string   | no       | PS staff email — sales owner → sales commission. CRM-filled going forward (users/owners table incoming). |
| `ps_cs_lead`              | string   | no       | PS staff email — CS owner → CS comp (usually a different person than sales). CRM-filled going forward. |

**Why these 18:** the first 13 are Tim's 2026-05-22 design (onboarding + health + financial annotations + ownership). The five added 2026-05-25 (PM cip_34 / china-commission-audit) are the **attribution layer**: who owns each brand's 10%, the finder's-fee flag, the lead-source split key, and the sales/CS commission owners. They make the China book's partner/staff commission splits computable off CIP (the `lens_ps_china_commission` reporting lens).

## 3. Enumerations

### 3.1 `ps_segment`

| Value             | Meaning                                                                  |
| ----------------- | ------------------------------------------------------------------------ |
| `china_referral`  | Wayward China referral brands — the only Phase 2.7 segment.              |

Future segments are added by Tim-gated review only (not Twenty-editable in the meantime — pin to `china_referral` until then).

### 3.2 `ps_onboarded_status`

| Value          | Meaning                                                                |
| -------------- | ---------------------------------------------------------------------- |
| `prospect`     | Brand exists in PS's view but no contract yet.                         |
| `contracted`   | Agreement signed; not yet shipping.                                    |
| `onboarded`    | Active PS-managed brand. Surfaced by `lens_ps_china_brands_onboarded`. |
| `paused`       | Temporarily inactive (e.g. seasonal, dispute).                         |
| `offboarded`   | Relationship ended.                                                    |

### 3.3 `ps_engagement_health`

| Value           | Meaning                                                                            |
| --------------- | ---------------------------------------------------------------------------------- |
| `producing`     | Brand is actively producing revenue. Surfaced by `lens_ps_china_brands_producing`. |
| `green`         | Healthy but not yet producing material revenue.                                    |
| `yellow`        | At-risk signal (slow communication, late payment, partial delivery).               |
| `red`           | Critical signal (escalation or dispute open).                                      |
| `unknown`       | Default before PS has scored the brand.                                            |

**Priority rule** (for any dashboard that picks a single health label per brand when multiple signals exist):

> `red` > `yellow` > `producing` > `green` > `unknown`

That is, a red flag overrides a "producing" label — `producing` is a positive signal, but a red is a more urgent operational signal. The lens views do not implement this priority (they filter on the exact enum value) — it's for downstream consumers that aggregate multiple signals into one cell.

### 3.4 `ps_attribution_owner` + `ps_lead_source`

| Value            | Meaning                                                                          |
| ---------------- | -------------------------------------------------------------------------------- |
| `PS`             | Project Silk's own book (incl. Tim's referrals — "Tim" is **not** a value, Tim = `PS`). |
| `Eric`           | Eric's partner book.                                                             |
| `Adina`          | Adina's partner book.                                                            |
| `OpenLight`      | OpenLight's partner book.                                                        |
| `Oceanwing`      | Oceanwing's partner book.                                                        |
| `Jeremy Dai`     | Jeremy Dai's partner book.                                                       |
| `Shallow`        | Shallow's partner book.                                                          |
| `heavy_producer` | Contractually-excluded heavy-producer brand (Exhibit A category). Attribution-only; not a referral partner. |
| `unclassified`   | Not yet attributed.                                                              |

`ps_lead_source` uses the same value set **except** `unclassified` and `heavy_producer` (those aren't referral sources). For a PS-owned brand it records who referred it (the split key); for a partner-owned brand `ps_lead_source` equals `ps_attribution_owner`.

### 3.5 `ps_conditional`

| Value         | Meaning                                                                              |
| ------------- | ------------------------------------------------------------------------------------ |
| `finders_fee` | A partner referred the brand and was paid a one-time finder's fee — they're not earning ongoing commission, so the brand is "flippable" to PS. |
| (blank/absent) | Not a finder's-fee arrangement (ongoing partner split, or PS-owned, or contractually excluded). |

## 4. The CIP ↔ Twenty boundary (Tim's locked answer, 2026-05-22)

The boundary is **one set of fields per entity, never overlapping**:

- **EcomLever-authoritative fields in PS:** identity (HubSpot/Zendesk ids), names, source-system properties JSONB. Twenty **cannot** write these (`cip_twenty_project_silk` has no UPDATE grant on them).
- **PS / Twenty-authoritative fields:** everything in `companion_data` listed above. The mirror **never** writes this column (mapper omits it).
- **CIP-only PS reporting fields:** financial summaries via [`lens_ps_china_brands_financial_summary`](../cip/migrations/versions/cip_26_ps_lens_views.py), aggregated from `cip_deals.amount` + `cip_deals.close_date`. The pipeline state stays in Twenty; CIP only shows the totals.

Twenty's user-facing UX never exposes the pipeline. Pipeline columns (`stage`, `pipeline`, `probability` on `cip_deals`) are **read-only** to Twenty and surfaced for context only.

## 5. The five views (Phase 2.7 lens recut)

All five live in [`cip_26`](../cip/migrations/versions/cip_26_ps_lens_views.py) and are double-scoped: hardcoded `tenant_id = '078a37d6-...'` (PS) PLUS `app.current_tenant` GUC equality. A session that hasn't set GUC sees zero rows.

| View                                              | Shape          | Filter                                                  |
| ------------------------------------------------- | -------------- | ------------------------------------------------------- |
| `lens_ps_china_brands_all`                        | per-brand      | (none — master)                                         |
| `lens_ps_china_brands_onboarded`                  | per-brand      | `ps_onboarded_status = 'onboarded'`                     |
| `lens_ps_china_brands_producing`                  | per-brand      | `ps_engagement_health = 'producing'`                    |
| `lens_ps_china_brands_by_original_attribution`    | per-deal       | (none — exposes EcomLever's `China Referral - <name>` sourcer) |
| `lens_ps_china_brands_financial_summary`          | per-brand agg  | (none — `SUM(amount), COUNT(deals), MIN/MAX(close_date)`) |

The attribution view's `attribution_sourcer` column is extracted via `SUBSTRING('China Referral - (.+)$')` from `cip_deals.properties->>'source'`. Deals not matching that prefix get `'(other)'`. The set of legitimate sourcers (Eric, Tim, Adina, Jeremy, OpenLight, Shallow, Jeremy Dai, ...) is **fixed**: those represent the historical commission-split partners from before PS took over the China line. New attributions are NOT created via this companion_data layer — that history is locked.

## 6. Defaults + bootstrapping

A freshly mirrored PS row has `companion_data = '{}'::jsonb`. The two filtered lens views (`onboarded`, `producing`) return zero rows for an empty companion_data set — by design. Twenty's first task on connecting is to populate `ps_segment` + `ps_onboarded_status` + `ps_engagement_health` for the existing 1,404 brands; the lenses then start surfacing rows.

A bootstrap script may eventually backfill `ps_segment = 'china_referral'` across all PS clients (single-valued enum) — that's a Tim-gated one-time write, not a recurring mirror task.

## 7. Cross-references

- [`docs/ARCHITECTURE-SPLIT.md`](ARCHITECTURE-SPLIT.md) (CIP-SPEC-010) — the CIP Hard Split
- [`docs/CROSS-TENANT-ACCESS-PATTERNS.md`](CROSS-TENANT-ACCESS-PATTERNS.md) (CIP-SPEC-011) — mirror-vs-grant picking rule; this doc sits inside the mirror branch
- [`docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md`](vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md) (CIP-FW-003) — Atlas Q1 sidecar-JSONB design
- [`docs/vision/ATLAS-REVIEW-ASSOCIATION-CONTRACT.md`](vision/ATLAS-REVIEW-ASSOCIATION-CONTRACT.md) (CIP-FW-004) — JSONB source-id contract used by the lens joins
- [`cip/migrations/versions/cip_23_phase26_schema.py`](../cip/migrations/versions/cip_23_phase26_schema.py) — adds `companion_data` JSONB column
- [`cip/migrations/versions/cip_25_project_silk_twenty_role.py`](../cip/migrations/versions/cip_25_project_silk_twenty_role.py) — provisions the column-level GRANT enforcing the boundary
- [`cip/migrations/versions/cip_26_ps_lens_views.py`](../cip/migrations/versions/cip_26_ps_lens_views.py) — the five PS-side lens views

---

_Resolves PM scope `250` — Phase 2.7 destination-side lens recut + companion_data contract._
