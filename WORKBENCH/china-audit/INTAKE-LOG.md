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

---

## 2026-07-15 — Jake's payment reports Dec 2025–Jun 2026 (7 sheets) — RECONCILE (no new writes)

Re-drop to confirm the earlier `ps_payment_events` ingest dropped nothing. Line-by-line across all 7
months (Dec CSV + Jan–Jun xlsx; naming drifts "Rev Share"→"Referral Report").

- **Columns:** stable 12-col core all months (+ SIGNUP_DATE / MONTHS_FROM_SIGNUP from Jan; Rev Share
  Start Date / Days Since in May; a duplicate MONTHS col in Jan/Jun). **Every sheet column maps to a
  `ps_payment_events` column — nothing un-captured.** `REV_SHARE_OWED` → `rev_share_stated`.
- **Numbers tie:** `TOTAL_AMOUNT_PAID` matches EXACTLY every month (Dec 83,982.61 · Jan 134,292.93 ·
  Feb 173,035.43 · Mar 236,283.65 · Apr 192,686.16 · May 96,213.45 · Jun 60,786.91). Row counts tie
  (2,271 total). 100% of BRAND_IDs are in ps_brands.
- **Minor:** `rev_share_stated` sum is off by pennies in 3 months (Jan $0.01, Mar $0.26, Apr $0.20 —
  <$0.50 across 2,271 rows; per-row rounding, immaterial; chase only if asked).
- **Documentation:** every money table is fully commented (0 uncommented cols); the one gap was the
  new `ps_partner_payouts` → fixed in **cip_102** (now 0 uncommented).
- **Data not from primary sources:** the payment amounts + stated rev share (what Wayward paid us) —
  only in these sheets, already backfilled (Dec–Jun). Added "automate the payment reports" to
  DATA-WE-NEED. **No missing items to backfill** — the 7 months are complete and reconciled.
