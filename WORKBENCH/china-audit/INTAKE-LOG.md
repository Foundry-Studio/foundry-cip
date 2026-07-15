# INTAKE LOG — sheets Tim provides, and what each produced

Client files live in `intake/` (gitignored). This is the git-tracked record of what we did with
each. No dollar amounts recorded here. DB provenance (source_system / asserted_by / ps_added_facts)
is the primary audit trail.

---

## 2026-07-15 — "Wayward Overdue Invoices 5_11" (overdue/collection sheet, 331 clients)

Wayward-origin. Two tabs, same 331 clients. Keys: `stripe_customer_id`, `brand_id` (= our
`wayward_brand_id`). Sheet2 carries `Country-code` (the China tag). Sheet1 carries contact-process
Yes/No flags (Contacted via WeChat/WhatsApp/Zendesk/Website — **flags, not contact IDs**) + notes.

**Investigation:** 100% coverage — all 330 brands + 331 Stripe customers already in our system.

**Actions taken (Tim-approved, applied to prod, direct SQL):**
- **Flipped 4 CN-tagged unknowns → china** via a `wayward_country_cn` signal (the sheet's CN tag;
  these 4 had zero prior signals): **QOKNUL, Serravine, StarVal, CONQUECO.** China book 1,600 →
  **1,604**; `is_chinese` re-derived (39 spine rows); guard held; **21/21 invariants**.
- **Linked** orphan Stripe customer `cus_Sr38jfE8pRIaiL` (Garveelife) → GarveeLife brand (was null;
  brand already `china`).
- **Seeded 3 additional brand contacts** (new emails that differ from our billing email):
  lacozy, PetraTools, Nuanced Media.

**Confirmed, KEPT (Tim ruling):** 29 brands are `china` in our book but tagged **US** on the sheet —
kept china. Every one carries real evidence (Eric's/exclusion list = definitional, plus
chinese_email_domain / +86 / chinese_partner). The sheet's "US" is Wayward's own unreliable flag —
the exact mislabeling this audit exists to catch. **Zero** CN-tagged brands were `not_china`.

**Not ingested (not needed):** overdue amounts, follow-up/deactivation flags, contact-process Yes/No
flags, collection notes.

**Notes for later:**
- This is **not** Jake's WeChat list (no WeChat IDs). `ps_brand_contacts` already has a `wechat`
  column + `is_primary`/`role`/`job_title` — the multi-contact schema is ready; reconcile per-brand
  when Jake's list lands.
- **Deferred option (Tim's call):** 232 of these overdue brands have no `ps_brand_contacts` row
  (their billing email lives in `ps_stripe_customers` but isn't copied into contacts). Could
  populate for outreach if wanted — held, since it's existing data, not new info.

---

## 2026-07-15 — "China brands with provided wechat" (Wayward brand export, 549 China brands)

Wayward-origin. 76 cols; the useful block is a **named-person contact** (`contact_first_name/
last_name/email`) + `wechat_id` (Jake filled in) + `source` (referral). 100% country_code=CN.

**Schema (cip_100, applied):** `ps_brand_contacts.wechat` → `wechat_id` + new `wechat_phone`. Jake's
WeChat column mixes handles and phone numbers; we now hold them apart (a phone is also callable and
a +86 nationality signal). Ingest auto-routes each value.

**Ingest (Tim-approved, applied to prod, set-based, guarded):**
- **Contacts:** 243 new + 306 enriched; **237 wechat_id + 149 wechat_phone** landed (all 386 WeChat
  values; we previously held zero).
- **Flipped 88 → china** (87 CN-unknowns + ELTRIKO) via `wayward_country_cn` from this export.
- **Added ELTRIKO** to `ps_brands` — the 1 China-list brand missing from our system (backfill detail
  later when it bills).
- **Referral source → 549 `ps_brand_observations` (`field=referral_source`)** — data only (incl.
  `referral(Adina)`, `referral(xq)`); NOT wired into attribution decisions. Audit later.
- **China book 1,604 → 1,708** (+104 = 82 flipped companies + ~22 already-china brands promoted
  GHOST→REAL now that they have a contact). **21/21 invariants.**

**KEPT (Tim ruling):** **Wyze** — on the CN list but `not_china` in our book via a human ruling
(Seattle US company). Left not_china; the ingest explicitly excludes it.

**Note:** operational lesson — the per-row ingest was too slow over the Railway proxy and ran long
in the background; a set-based re-run then errored (ELTRIKO already added) and rolled back clean.
Net effect landed exactly once. Future bulk ingests: set-based from the start.
