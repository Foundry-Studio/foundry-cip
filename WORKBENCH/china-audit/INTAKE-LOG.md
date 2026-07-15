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
