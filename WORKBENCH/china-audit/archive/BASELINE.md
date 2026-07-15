# W0 — BASELINE

**2026-07-14. No changes made. Every later wave diffs against THIS FILE, not memory.**
All numbers read live from prod via the MCP read tool (`foundry_mcp_cip_query`, tenant
`078a37d6-6ae2-4e22-869e-cc08f6cb2787`). Reproduce any of them by re-running the SQL noted.

---

## 1. THE BOOK — verdict × reality

| reality | verdict | brands | billing |
|---|---|---|---|
| **REAL** | **china** | **1,623** | 1,101 |
| **REAL** | **unknown** | **550** | 542 |
| **REAL** | **not_china** | **431** | 299 |
| GHOST | unknown | 2,063 | 0 |
| GHOST | china | 550 | 0 |
| GHOST | not_china | 13 | 0 |
| JUNK | unknown | 121 | 0 |
| JUNK | china | 1 | 0 |

**REAL total: 2,604.** Ghosts and junk are never counted, never chased, never researched.

## 2. THE MASTER

| | |
|---|---|
| `ps_brands` rows | **5,352** |
| distinct real companies (collapse `canonical_brand_id`) | **4,500** |
| alias rows (double-counted in every lens but the chase list) | **852** |
| `ps_nationality_signals` rows | 8,575 |
| live pinned `ps_added_facts` | 432 |
| chase list (companies, post-cip_86 collapse) | **511** — 314 with an email, 157 with a phone |

## 3. WHO DECIDED — `ps_added_facts`, live rows

| asserted_by | value | rows |
|---|---|---|
| **Tim Jordan** | confirmed_yes | **276** |
| Claude (manual review, Tim-delegated) | confirmed_yes | 137 |
| **Tim Jordan** | confirmed_no | **6** |
| Claude (web crawl, Tim-delegated) | confirmed_yes | 5 |
| research agent | confirmed_no | 3 |
| research agent | confirmed_yes | 2 |
| Tim Jordan | `china_status_reverted` (import records) | 3 |

## 4. W1 TARGET SET — `manual_review` rows, by source

| source_system | points_to | rows | **restates the mailbox rule** | genuine review |
|---|---|---|---|---|
| **`tim:tier1_approval_2026_07_14`** | china | 170 | **131** ⚠️ | 39 |
| `manual:dupe_row_review_2026_07_14` | china | 116 | 0 | 116 |
| `tim:tier2_ruling_2026_07_14` | china | 57 | 0 | 57 |
| `manual:review_2026_07_13` | not_china | 44 | 0 | 44 |
| `tim:dupe_row_propagation_2026_07_14` | china | 31 | 0 | 31 |
| `manual:review_2026_07_13` | china | 17 | 0 | 17 |
| `tim:final_six_2026_07_14` | china | 13 | 0 | 13 |
| `tim:tier2_ruling_2026_07_14` | not_china | 4 | 0 | 4 |
| **`research:external_agent_2026_07_14`** | not_china | **3** ⚠️ | 0 | 3 |
| `tim:hk_is_china_2026_07_14` | china | 3 | 0 | 3 |
| **`research:external_agent_2026_07_14`** | china | **2** ⚠️ | 0 | 2 |
| `tim:dupe_row_propagation_2026_07_14` | not_china | 1 | 0 | 1 |

**W1 touches exactly two sets: the 131, and the 5 research-agent rows. Nothing else.**

## 5. W2 PREDICTED MOVEMENT — **MEASURED, not guessed**

Classifying every REAL brand by what evidence it actually holds:

| verdict today | W2 effect | brands | billing |
|---|---|---|---|
| china | stays **china** (approved indicator) | 1,537 | 1,041 |
| china | stays **china** (human pin) | 83 | 57 |
| china | **china → PROBABLE** | **3** | 3 |
| not_china | stays **not_china** (human pin) | 39 | 38 |
| not_china | **not_china → UNKNOWN** | **392** | 261 |
| unknown | stays unknown | 550 | 542 |

**After W2, REAL brands:** china **1,620** · probable **3** · not_china **39** · unknown **942**

- The **392** are brands whose only "not China" evidence is `wayward_country_other`. Tim: *"DONT
  ASSUME THAT WAYWARD DATA IS CORRECT."* The flag stays visible as corroboration; it stops deciding.
- The **3** are SZEE, Lille Home, Yoleo — the A4 three. They land at the top of Tim's probable
  queue, which is exactly *"they are LIKELY chinese, and I Will manually check each."*
- ⚠️ **W1 MUST run before W2.** The 3 legal-record `not_china` brands (ACE Supply, Actial
  Nutrition, Acupoint) currently classify as "human pin" because the research ingest wrote them
  companion `manual_review` rows. After W1 removes those, they fall correctly to the legal-record
  tier. Running W2 first would mislabel their provenance.

## 6. W3 TARGET — `is_chinese` on the money spine contradicts the verdict

| verdict | `is_chinese` | brands | rows | usage_billed | ps_gross_owed |
|---|---|---|---|---|---|
| china | **NULL** | **492** | 4,526 | **$535,149.93** | **$48,652.77** |
| china | **false** | **6** | 26 | $1,196.32 | $111.77 |

**The six hard-contradicts** — the spine says `false` while the verdict says china:

| brand | china evidence | billed |
|---|---|---|
| COOLIFE | manual_review, **phone_+86** | $753.33 |
| Heyvalue | manual_review, **phone_+86**, shared_owner_mailbox | $407.42 |
| Gelrova | **eric_sheet, on_exclusion_list** | $14.90 |
| Neathova | manual_review, **phone_+86** | $8.81 |
| Jarkyfine | manual_review, **phone_+86**, shared_owner_mailbox | $6.31 |
| MOSDART | manual_review, **phone_+86** | $5.55 |

Every one has a `+86` phone or sits on the frozen exclusion list. The spine is simply wrong.

## 7. W4 TARGET — the rate clock

`rate_6_expires` wrong (≠ `productive_date + INTERVAL '18 months'`): **2,371 of 2,829 deals (83.8%)**

## 8. INVARIANTS

**17 of 17 hold** (`python scripts/check_invariants.py`).

---

## Reproduce

```sql
-- §1  verdict x reality
SELECT r.reality, v.verdict, count(*), count(*) FILTER (WHERE r.ever_billed)
FROM lens_ps_china_verdict v JOIN lens_ps_brand_reality r USING (wayward_brand_id)
GROUP BY 1,2 ORDER BY 1,3 DESC;

-- §4  manual_review by source, and how many just restate the mailbox rule
SELECT source_system, points_to, count(*),
       count(*) FILTER (WHERE evidence ILIKE '%shares mailbox%')
FROM ps_nationality_signals WHERE signal='manual_review' GROUP BY 1,2 ORDER BY 3 DESC;

-- §6  the spine contradicting the verdict
SELECT v.verdict, m.is_chinese, count(DISTINCT m.wayward_brand_id), count(*),
       round(sum(m.usage_billed),2), round(sum(m.ps_gross_owed),2)
FROM ps_monthly_earnings m JOIN lens_ps_china_verdict v USING (wayward_brand_id)
WHERE (v.verdict='china') <> COALESCE(m.is_chinese,false) GROUP BY 1,2;
```
